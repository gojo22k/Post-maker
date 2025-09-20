from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from config import *
from random import choice
import requests
import re
import json
from difflib import SequenceMatcher
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time
from urllib.parse import quote

# Ensure the bot token is set correctly
app = Client("ANIFLIX_POST_BOT", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

kitsu_api_url = "https://kitsu.io/api/edge"
anilist_api_url = "https://graphql.anilist.co"
anime_api_url = "https://raw.githubusercontent.com/OtakuFlix/ADATA/refs/heads/main/anime_data.txt"
user_inputs = {}

# Default fallback image for when API calls fail
DEFAULT_ANIME_IMAGE = "https://via.placeholder.com/800x600/34495e/ecf0f1?text=ANIFLIX"

season_bullets = {
    "01": "❶", "02": "❷", "03": "❸", "04": "❹", "05": "❺",
    "06": "❻", "07": "❼", "08": "❽", "09": "❾", "10": "❿",
    "11": "⓫", "12": "⓬", "13": "⓭", "14": "⓮", "15": "⓯",
    "16": "⓰", "17": "⓱", "18": "⓲", "19": "⓳", "20": "⓴"
}

# Health check endpoint
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'OK')

def run_health_check_server():
    server_address = ('', 10000)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    httpd.serve_forever()

def make_request_with_retry(url, timeout=10, max_retries=3):
    """Make HTTP request with retry logic and proper error handling"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=timeout, headers=headers)
            if response.status_code == 200:
                return response
            else:
                print(f"Request failed with status {response.status_code}, attempt {attempt + 1}")
        except requests.exceptions.RequestException as e:
            print(f"Request error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)  # Wait before retry
    return None

def validate_image_url(url):
    """Validate if image URL is accessible by Telegram"""
    if not url:
        return False
    
    try:
        # Check if URL is reachable and returns an image
        response = requests.head(url, timeout=5)
        content_type = response.headers.get('content-type', '').lower()
        
        # Check if it's an image and accessible
        if response.status_code == 200 and 'image' in content_type:
            return True
    except:
        pass
    
    return False

async def load_anime_cache():
    """Load anime list for suggestions with error handling"""
    try:
        response = make_request_with_retry(anime_api_url)
        if response:
            data = response.json()
            return [anime["name"] for anime in data]
    except Exception as e:
        print(f"Failed to load anime cache: {e}")
    return []

def similarity(a, b):
    """Calculate similarity between two strings"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def get_anime_suggestions(input_name, anime_list, limit=5):
    """Get closest anime name suggestions"""
    return [
        anime for anime, _ in sorted(
            [(anime, similarity(input_name, anime)) for anime in anime_list if similarity(input_name, anime) > 0.4],
            key=lambda x: x[1], reverse=True
        )[:limit]
    ]

def clean_html_tags(text):
    """Remove HTML tags from text and handle special characters"""
    if not text: 
        return text
    text = re.sub('<.*?>', '', text)
    for a, b in [('&quot;', '"'), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&nbsp;', ' '), ('<br>', '\n'), ('<br/>', '\n'), ('<br />', '\n')]:
        text = text.replace(a, b)
    return text.strip()

def format_spoiler_text(text):
    """Format spoiler text to avoid deployment issues"""
    if not text or text == "No synopsis available.": 
        return "No synopsis available."
    text = clean_html_tags(text)
    for ch in '|*_`[]()':
        text = text.replace(ch, f"\\{ch}")
    return text

def truncate_synopsis(synopsis, max_length=200):
    """Truncate synopsis to fit within character limits"""
    if not synopsis or synopsis == "No synopsis available.": 
        return "No synopsis available."
    if len(synopsis) <= max_length: 
        return synopsis
    truncated = synopsis[:max_length]
    for sep in ['.', ' ']:
        idx = truncated.rfind(sep)
        if idx > max_length - 50: 
            return synopsis[:idx+1] if sep=='.' else synopsis[:idx]+"..."
    return synopsis[:max_length]+"..."

# Step 1: Get correct name/aid from your database
def get_aid_for_anime(anime_name):
    """Get anime AID and poster from database with error handling"""
    try:
        response = make_request_with_retry(anime_api_url)
        if response:
            for anime in response.json():
                if anime["name"].lower() == anime_name.lower():
                    # Get the first poster URL if available
                    poster_url = None
                    if 'poster' in anime and anime['poster']:
                        posters = [p.strip() for p in anime['poster'].split(',')]
                        poster_url = posters[0] if posters else None
                    return anime["name"], anime.get("aid"), poster_url
    except Exception as e:
        print("AID fetch error:", e)
    return None, None, None

# Step 2: Get anilist id from anilist search
def get_anilist_id(anime_name):
    """Get AniList ID with error handling"""
    query = '''
    query ($search: String) { Media (search: $search, type: ANIME) { id } }
    '''
    try:
        response = requests.post(
            anilist_api_url,
            json={'query': query, 'variables': {'search': anime_name}},
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if data.get('data') and data['data'].get('Media'):
                return data['data']['Media']['id']
    except Exception as e:
        print("AniList ID error:", e)
    return None

# Step 3: Get AniZip Data (primary source)
def fetch_ani_zip(anilist_id):
    """Fetch episode data from ani.zip API"""
    try:
        response = requests.get(f"https://api.ani.zip/mappings?anilist_id={anilist_id}", timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print("Ani.zip error:", e)
    return None

def search_kitsu_anime(anime_name):
    """Search anime on Kitsu with error handling"""
    try:
        url = f"{kitsu_api_url}/anime?filter[text]={quote(anime_name)}"
        response = make_request_with_retry(url)
        if response:
            data = response.json()
            if 'data' in data and data['data']:
                return data['data'][0]['id'], data['data'][0]['attributes'].get('posterImage', {}).get('original')
    except Exception as e:
        print(f"Kitsu search error: {e}")
    return None, None

def fetch_kitsu_details(anime_id):
    """Fetch Kitsu details with error handling"""
    try:
        url = f"{kitsu_api_url}/anime/{anime_id}"
        response = make_request_with_retry(url)
        if response:
            data = response.json()
            if 'data' in data:
                d = data['data']['attributes']
                rating = d.get('averageRating', 'N/A')
                if rating != 'N/A' and float(rating) > 10:
                    rating = str(round(float(rating) / 10, 2))
                synopsis = d.get('synopsis', 'No synopsis available.')
                return rating, synopsis, d.get('status', '').lower(), d.get('posterImage', {}).get('original')
    except Exception as e:
        print(f"Kitsu details error: {e}")
    return "N/A", "No synopsis available", "finished", None

def fetch_episode_image(anime_id, episode_number):
    """Fetch episode-specific image and synopsis from Kitsu with error handling"""
    try:
        url = f"{kitsu_api_url}/anime/{anime_id}/episodes?filter[number]={episode_number}"
        response = make_request_with_retry(url)
        if response:
            data = response.json()
            if 'data' in data and data['data']:
                ep = data['data'][0]['attributes']
                thumb = ep.get('thumbnail', {})
                return thumb.get('original') if thumb else None, ep.get('synopsis', None)
    except Exception as e:
        print(f"Episode image fetch error: {e}")
    return None, None

def extract_season_number(anime_name):
    match = re.search(r'season (\d+)', anime_name, re.IGNORECASE)
    return match.group(1).zfill(2) if match else "01"

def search_anilist_legacy(anime_name):
    """Legacy AniList search for fallback data"""
    query = '''
    query ($search: String) {
        Media (search: $search, type: ANIME) {
            id
            title { romaji english native }
            bannerImage
            coverImage { extraLarge }
            averageScore
            description
            status
        }
    }
    '''
    try:
        response = requests.post(
            anilist_api_url,
            json={'query': query, 'variables': {'search': anime_name}},
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and data['data']['Media']:
                m = data['data']['Media']
                return {
                    'id': m['id'],
                    'banner': m.get('bannerImage'),
                    'cover': m.get('coverImage', {}).get('extraLarge'),
                    'rating': m.get('averageScore'),
                    'description': m.get('description'),
                    'status': m.get('status', '').lower()
                }
    except Exception as e:
        print(f"AniList search error: {e}")
    return None

# Unified post formatter using new workflow
async def format_update_post(anime_name, episode_number):
    """Format update post with comprehensive error handling and ani.zip integration"""
    try:
        # 1. Get official name, aid, and poster URL
        official_name, anime_aid, poster_url = get_aid_for_anime(anime_name)
        if not official_name:
            return f"No anime found for '{anime_name}'.", DEFAULT_ANIME_IMAGE, None, None

        # 2. Get Anilist ID from AniList
        anilist_id = get_anilist_id(official_name)
        if anilist_id:
            # 3. Get Ani.zip data (PRIMARY SOURCE - this is the key improvement!)
            zip_data = fetch_ani_zip(anilist_id)
            if zip_data and 'episodes' in zip_data:
                ep_info = zip_data['episodes'].get(str(int(episode_number)))
                titles = zip_data.get('titles', {})
                anime_title = titles.get('en') or titles.get('x-jat') or official_name
                ep_title = (ep_info and ep_info.get('title', {}).get('en')) or f'Episode {int(episode_number)}'
                ep_summary = ep_info.get('overview') if ep_info else "No synopsis available."
                ep_image = (ep_info.get('image') if ep_info else None) or poster_url
                ep_rating = ep_info.get('rating', "N/A") if ep_info else "N/A"
                season_number = ep_info.get('seasonNumber', 1) if ep_info else 1
                season_bullet = season_bullets.get(str(season_number).zfill(2), "⓪")
                synopsis = truncate_synopsis(format_spoiler_text(ep_summary))
                
                # Validate image URL before using
                final_image = DEFAULT_ANIME_IMAGE
                if ep_image and validate_image_url(ep_image):
                    final_image = ep_image
                elif poster_url and validate_image_url(poster_url):
                    final_image = poster_url
                
                watch_url = f"https://aniflix.in/detail?aid={anime_aid}" if anime_aid else None
                download_url = f"https://hindi.aniflix.in/search?q={anime_title.replace(' ', '+')}"
                
                post_caption = (
                    f"⛩ **{anime_title}**\n"
                    f"✦ **{episode_number}** : {ep_title}\n"
                    f"┌───────────────────\n"
                    f"├ {season_bullet} 𝗦𝗲𝗮𝘀𝗼𝗻 : {str(season_number).zfill(2)}\n"
                    f"├ ⚅ 𝗘𝗽𝗶𝘀𝗼𝗱𝗲 : {episode_number}\n"
                    f"├ 𖦤 𝗔𝘂𝗱𝗶𝗼 : 𝗛𝗶𝗻𝗱𝗶 #𝗢𝗳𝗳𝗶𝗰𝗶𝗮𝗹\n"
                    f"├ ⌬ 𝗤𝘂𝗮𝗹𝗶𝘁𝘆 : 𝟭𝟬𝟴𝟬𝗽\n"
                    f"├ ✦ 𝗥𝗮𝘁𝗶𝗻𝗴 : {ep_rating}/10\n"
                    f"├───────────────────\n"
                    f"├ ⚆ **Spoiler:**\n"
                    f"├ ||{synopsis}||\n"
                    f"├───────────────────\n"
                    f"├ ✧ Powered By ‧ [𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/ANIFLIX_OFFICIAL) ✧\n"
                    f"├ ⌲ Share ‧ [𝗦𝗛𝗔𝗥𝗘 𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/share/url?url=%F0%9F%8E%89+Join+@Aniflix_Official+for+the+best+Hindi+Dubbed+Anime!+Don't+miss+out+on+your+favorites,+all+in+one+place!+%F0%9F%8E%AC%E2%9C%A8) ✧\n"
                    f"└───────────────────\n"
                )
                
                # Handle caption length limit
                while len(post_caption) > 1024:
                    synopsis = truncate_synopsis(synopsis, len(synopsis) - 50)
                    post_caption = (
                        f"> ⛩ **{anime_title}**\n"
                        f"✦ **{episode_number}** : {ep_title}\n"
                        f"┌───────────────────\n"
                        f"├ {season_bullet} 𝗦𝗲𝗮𝘀𝗼𝗻 : {str(season_number).zfill(2)}\n"
                        f"├ ⚅ 𝗘𝗽𝗶𝘀𝗼𝗱𝗲 : {episode_number}\n"
                        f"├ 𖦤 𝗔𝘂𝗱𝗶𝗼 : 𝗛𝗶𝗻𝗱𝗶 #𝗢𝗳𝗳𝗶𝗰𝗶𝗮𝗹\n"
                        f"├ ⌬ 𝗤𝘂𝗮𝗹𝗶𝘁𝘆 : 𝟭𝟬𝟴𝟬𝗽\n"
                        f"├ ✦ 𝗥𝗮𝘁𝗶𝗻𝗴 : {ep_rating}/10\n"
                        f"├───────────────────\n"
                        f"├ ⚆ **Spoiler:**\n"
                        f"||{synopsis}||\n"
                        f"├───────────────────\n"
                        f"├ ✧ Powered By ‧ [𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/ANIFLIX_OFFICIAL) ✧\n"
                        f"├ ⌲ Share ‧ [𝗦𝗛𝗔𝗥𝗘 𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/share/url?url=%F0%9F%8E%89+Join+@Aniflix_Official+for+the+best+Hindi+Dubbed+Anime!+Don't+miss+out+on+your+failures%2C+all+in+one+place!+%F0%9F%8E%AC%E2%9C%A8) ✧\n"
                        f"└───────────────────\n"
                    )
                
                return post_caption, final_image, watch_url, download_url

        # ---- FALLBACK: Legacy logic when ani.zip fails ----
        print(f"Using fallback logic for {official_name}")
        anime_id, poster_image = search_kitsu_anime(official_name)
        if not anime_id:
            return f"Failed to find anime '{official_name}' on Kitsu.", DEFAULT_ANIME_IMAGE, None, None
            
        kitsu_rating, anime_synopsis, airing_status, fallback_image = fetch_kitsu_details(anime_id)
        episode_image, episode_synopsis = fetch_episode_image(anime_id, episode_number)
        anilist_data = search_anilist_legacy(official_name)
        
        # Image validation for fallback
        final_image = DEFAULT_ANIME_IMAGE
        image_candidates = [episode_image, 
                           anilist_data and anilist_data.get('banner'), 
                           anilist_data and anilist_data.get('cover'), 
                           fallback_image, 
                           poster_image]
        
        for img_url in image_candidates:
            if img_url and validate_image_url(img_url):
                final_image = img_url
                break
        
        synopsis = episode_synopsis or (anime_synopsis if anime_synopsis != "No synopsis available." else "") or (anilist_data and anilist_data.get('description')) or "No synopsis available."
        rating = kitsu_rating
        if rating == "N/A" and anilist_data and anilist_data.get('rating'):
            rating = str(round(float(anilist_data['rating']) / 10, 2))
        
        # Clean synopsis
        if "Source:" in synopsis:
            sidx = synopsis.find("(Source:")
            eidx = synopsis.find(")", sidx)+1
            if sidx > 0 and eidx > sidx: 
                synopsis = synopsis.replace(synopsis[sidx:eidx], "").strip()
        
        synopsis = truncate_synopsis(format_spoiler_text(synopsis), 200)
        season_number = extract_season_number(official_name)
        season_bullet = season_bullets.get(season_number, "⓪")
        watch_url = f"https://aniflix.in/detail?aid={anime_aid}" if anime_aid else None
        download_url = f"https://hindi.aniflix.in/search?q={official_name.replace(' ', '+')}"
        
        post_caption = (
            f"> ⛩ **{official_name}**\n"
            f"✦ **{episode_number}** : Episode {int(episode_number)}\n"
            f"┌───────────────────\n"
            f"├ {season_bullet} 𝗦𝗲𝗮𝘀𝗼𝗻 : {season_number}\n"
            f"├ ⚅ 𝗘𝗽𝗶𝘀𝗼𝗱𝗲 : {episode_number}\n"
            f"├ 𖦤 𝗔𝘂𝗱𝗶𝗼 : 𝗛𝗶𝗻𝗱𝗶 #𝗢𝗳𝗳𝗶𝗰𝗶𝗮𝗹\n"
            f"├ ⌬ 𝗤𝘂𝗮𝗹𝗶𝘁𝘆 : 𝟭𝟬𝟴𝟬𝗽\n"
            f"├ ✦ 𝗥𝗮𝘁𝗶𝗻𝗴 : {rating}/10 ‧ 𝗜𝗠𝗗𝗯\n"
            f"├───────────────────\n"
            f"├ ⚆ **Spoiler:**\n"
            f"||{synopsis}||\n"
            f"├───────────────────\n"
            f"├ ✧ Powered By ‧ [𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/ANIFLIX_OFFICIAL) ✧\n"
            f"├ ⌲ Share ‧ [𝗦𝗛𝗔𝗥𝗘 𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/share/url?url=%F0%9F%8E%89+Join+@Aniflix_Official+for+the+best+Hindi+Dubbed+Anime!+Don't+miss+out+on+your+favorites,+all+in+one+place!+%F0%9F%8E%AC%E2%9C%A8) ✧\n"
            f"└───────────────────\n"
        )
        
        while len(post_caption) > 1024:
            synopsis = truncate_synopsis(synopsis, len(synopsis)-50)
            post_caption = (
                f"> ⛩ **{official_name}**\n"
                f"✦ **{episode_number}** : Episode {int(episode_number)}\n"
                f"┌───────────────────\n"
                f"├ {season_bullet} 𝗦𝗲𝗮𝘀𝗼𝗻 : {season_number}\n"
                f"├ ⚅ 𝗘𝗽𝗶𝘀𝗼𝗱𝗲 : {episode_number}\n"
                f"├ 𖦤 𝗔𝘂𝗱𝗶𝗼 : 𝗛𝗶𝗻𝗱𝗶 #𝗢𝗳𝗳𝗶𝗰𝗶𝗮𝗹\n"
                f"├ ⌬ 𝗤𝘂𝗮𝗹𝗶𝘁𝘆 : 𝟭𝟬𝟴𝟬𝗽\n"
                f"├ ✦ 𝗥𝗮𝘁𝗶𝗻𝗴 : {rating}/10 ‧ 𝗜𝗠𝗗𝗯\n"
                f"├───────────────────\n"
                f"├ ⚆ **Spoiler:**\n"
                f"||{synopsis}||\n"
                f"├───────────────────\n"
                f"├ ✧ Powered By ‧ [𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/ANIFLIX_OFFICIAL) ✧\n"
                f"├ ⌲ Share ‧ [𝗦𝗛𝗔𝗥𝗘 𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/share/url?url=%F0%9F%8E%89+Join+@Aniflix_Official+for+the+best+Hindi+Dubbed+Anime!+Don't+miss+out+on+your+favorites,+all+in+one+place!+%F0%9F%8E%AC%E2%9C%A8) ✧\n"
                f"└───────────────────\n"
            )
        
        return post_caption, final_image, watch_url, download_url
        
    except Exception as e:
        print(f"Error in format_update_post: {e}")
        # Return minimal fallback data with episode title
        return (
            f"⛩ **{anime_name}**\n"
            f"✦ **{episode_number}** : Episode {int(episode_number)}\n"
            f"┌───────────────────\n"
            f"├ ❶ 𝗦𝗲𝗮𝘀𝗼𝗻 : 01\n"
            f"├ ⚅ 𝗘𝗽𝗶𝘀𝗼𝗱𝗲 : {episode_number}\n"
            f"├ 𖦤 𝗔𝘂𝗱𝗶𝗼 : 𝗛𝗶𝗻𝗱𝗶 #𝗢𝗳𝗳𝗶𝗰𝗶𝗮𝗹\n"
            f"├ ⌬ 𝗤𝘂𝗮𝗹𝗶𝘁𝘆 : 𝟭𝟬𝟴𝟬𝗽\n"
            f"├ ✦ 𝗥𝗮𝘁𝗶𝗻𝗴 : N/A/10 ‧ 𝗜𝗠𝗗𝗯\n"
            f"├───────────────────\n"
            f"├ ⚆ **Spoiler:**\n"
            f"||No synopsis available.||\n"
            f"├───────────────────\n"
            f"├ ✧ Powered By ‧ [𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/ANIFLIX_OFFICIAL) ✧\n"
            f"├ ⌲ Share ‧ [𝗦𝗛𝗔𝗥𝗘 𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/share/url?url=%F0%9F%8E%89+Join+@Aniflix_Official+for+the+best+Hindi+Dubbed+Anime!+Don't+miss+out+on+your+favorites,+all+in+one+place!+%F0%9F%8E%AC%E2%9C%A8) ✧\n"
            f"└───────────────────\n",
            DEFAULT_ANIME_IMAGE,
            None,
            f"https://hindi.aniflix.in/search?q={anime_name.replace(' ', '+')}"
        )

# --------- Telegram Handlers --------

@app.on_message(filters.command("start"))
async def start_command(Client, message):
    start_text = (
        "**👋 Welcome to ANIFLIX Bot!**\n\n"
        "🔥 I can help you **find & watch anime episodes** easily.\n"
        "🎥 Use `/w` to get anime episodes.\n"
        "📥 Use `/d` to find download links.\n\n"
        "⚡ **How to use:**\n"
        "1️⃣ Send `/w` or `/d` command.\n"
        "2️⃣ Enter anime name.\n"
        "3️⃣ Enter episode number.\n\n"
        "Enjoy watching! 🚀"
    )
    
    buttons = [
        [InlineKeyboardButton("📢 Join ANIFLIX", url="https://t.me/ANIFLIX_OFFICIAL")],
        [InlineKeyboardButton("✪ C O M M E N T ✪", url="https://t.me/Aniflix_Anime_Requests")],
        [InlineKeyboardButton("😁 Click Me", url="https://t.me/share/url?url=%F0%9F%8E%89+Join+@Aniflix_Official+for+the+best+Hindi+Dubbed+Anime!+Don't+miss+out+on+your+favorites,+all+in+one+place!+%F0%9F%8E%AC%E2%9C%A8")]
    ]
    
    try:
        await message.reply_photo(
            "https://iili.io/39xn6H7.md.jpg",
            caption=start_text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        # Fallback to text message if image fails
        await message.reply_text(
            start_text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

@app.on_message(filters.command(["w", "d"]))
async def request_anime_name(client, message):
    user_inputs[message.from_user.id] = {"command": message.command[0]}
    await message.reply_text("Please send me the anime name:")

@app.on_callback_query(filters.regex("^suggest_"))
async def handle_suggestion_callback(client, callback_query: CallbackQuery):
    anime_name = callback_query.data.split("suggest_", 1)[1]
    user_id = callback_query.from_user.id
    if user_id in user_inputs:
        user_inputs[user_id]["anime_name"] = anime_name
        await callback_query.edit_message_text(
            f"✅ **Selected:** {anime_name}\n\nPlease send me the episode number:"
        )

@app.on_message(filters.text & ~filters.command(["w", "d", "start"]))
async def capture_input(client, message):
    user_id = message.from_user.id
    if user_id not in user_inputs:
        return
    user_data = user_inputs[user_id]
    anime_cache = await load_anime_cache()
    
    if "anime_name" not in user_data:
        anime_input = message.text.strip()
        exact_match = None
        for anime in anime_cache:
            if anime.lower() == anime_input.lower():
                exact_match = anime
                break
        
        if exact_match:
            user_data["anime_name"] = exact_match
            await message.reply_text("Please send me the episode number:")
        else:
            suggestions = get_anime_suggestions(anime_input, anime_cache)
            if suggestions:
                buttons = [
                    [InlineKeyboardButton(f"📺 {s}", callback_data=f"suggest_{s}")]
                    for s in suggestions[:5]
                ]
                await message.reply_text(
                    f"🤔 **Did you mean:**\n"
                    f"I couldn't find exact match for **'{anime_input}'**\n"
                    f"**Click on the correct anime:**",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            else:
                await message.reply_text(
                    f"❌ **Sorry!** I couldn't find any anime similar to **'{anime_input}'**\n\n"
                    "Please try again with a different name:"
                )
                
    elif "episode_number" not in user_data:
        try:
            episode_num = int(message.text.strip())
            user_data["episode_number"] = str(episode_num).zfill(2)
            await finalize_post(client, message, user_data)
        except ValueError:
            await message.reply_text(
                "❌ **Invalid episode number!**\n\n"
                "Please enter a valid number (e.g., 1, 12, 25):"
            )

async def finalize_post(client, message, user_data):
    anime_name = user_data["anime_name"]
    episode_number = user_data["episode_number"]
    command = user_data["command"]
    
    try:
        post_caption, episode_image, watch_url, download_url = await format_update_post(anime_name, episode_number)
        
        # Create buttons based on command
        buttons = []
        if command == "w" and watch_url:
            buttons.append([InlineKeyboardButton("✦ ＷＡＴＣＨ  ＮＯＷ ✦", url=watch_url)])
        else:
            buttons.append([InlineKeyboardButton("✦ D O W N L O A D ✦", url=download_url)])
        
        # Add comment button as requested
        buttons.append([InlineKeyboardButton("✪ C O M M E N T ✪", url="https://t.me/Aniflix_Anime_Requests")])

        # Try multiple approaches for image sending
        image_sent = False
        
        # First try with the fetched image
        if episode_image != DEFAULT_ANIME_IMAGE:
            try:
                await message.reply_photo(
                    episode_image, 
                    caption=post_caption, 
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                image_sent = True
            except Exception as photo_error:
                print(f"Primary photo send failed: {photo_error}")
        
        # If primary image failed, try with default placeholder
        if not image_sent:
            try:
                await message.reply_photo(
                    DEFAULT_ANIME_IMAGE, 
                    caption=post_caption, 
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                image_sent = True
            except Exception as placeholder_error:
                print(f"Placeholder photo send failed: {placeholder_error}")
        
        # Final fallback: send as text message
        if not image_sent:
            await message.reply_text(
                post_caption, 
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        # Clean up user data
        if message.from_user.id in user_inputs:
            del user_inputs[message.from_user.id]

    except Exception as e:
        print(f"Error in finalize_post: {e}")
        await message.reply_text(
            f"❌ **Error occurred!**\n\n"
            f"Something went wrong while processing your request.\n\n"
            "Please try again with `/w` or `/d` command.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✪ C O M M E N T ✪", url="https://t.me/Aniflix_Anime_Requests")]
            ])
        )

if __name__ == "__main__":
    # Start the health check server in a separate thread
    threading.Thread(target=run_health_check_server, daemon=True).start()
    app.run()
