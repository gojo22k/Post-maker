from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from config import *
from random import choice
import requests
import re
import json
from difflib import SequenceMatcher
import threading
from fastapi import FastAPI
import uvicorn
from datetime import datetime

# --------------------- FastAPI Health App ---------------------
health_app = FastAPI()
start_time = datetime.now()

@health_app.get("/")
def health_check():
    return {"status": "ok", "message": "ANIFLIX bot is live on port 10000 🚀"}

@health_app.get("/uptime")
def get_uptime():
    uptime = datetime.now() - start_time
    return {"uptime": str(uptime)}

def run_health_check():
    uvicorn.run(health_app, host="0.0.0.0", port=10000)

# --------------------- Pyrogram Bot ---------------------
app = Client("ANIFLIX_POST_BOT", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --------------------- Your Bot Logic Below ---------------------
kitsu_api_url = "https://kitsu.io/api/edge"
anilist_api_url = "https://graphql.anilist.co"
anime_api_url = "https://raw.githubusercontent.com/OtakuFlix/ADATA/refs/heads/main/anime_data.txt"
user_inputs = {}

season_bullets = {
    "01": "❶", "02": "❷", "03": "❸", "04": "❹", "05": "❺",
    "06": "❻", "07": "❼", "08": "❽", "09": "❾", "10": "❿",
    "11": "⓫", "12": "⓬", "13": "⓭", "14": "⓮", "15": "⓯",
    "16": "⓰", "17": "⓱", "18": "⓲", "19": "⓳", "20": "⓴"
}

# Cache for anime suggestions
anime_cache = []

async def load_anime_cache():
    """Load anime list for suggestions"""
    try:
        response = requests.get(anime_api_url)
        if response.status_code == 200:
            data = response.json()
            return [anime["name"] for anime in data]
    except:
        pass
    return []

def similarity(a, b):
    """Calculate similarity between two strings"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def get_anime_suggestions(input_name, anime_list, limit=5):
    """Get closest anime name suggestions"""
    suggestions = []
    for anime in anime_list:
        sim = similarity(input_name, anime)
        if sim > 0.4:  # Threshold for similarity
            suggestions.append((anime, sim))
    
    # Sort by similarity and return top matches
    suggestions.sort(key=lambda x: x[1], reverse=True)
    return [anime for anime, _ in suggestions[:limit]]

def truncate_synopsis(synopsis, max_length=200):
    """Truncate synopsis to fit within character limits"""
    if not synopsis or synopsis == "No synopsis available.":
        return "No synopsis available."
    
    if len(synopsis) <= max_length:
        return synopsis
    
    # Find the last complete sentence within the limit
    truncated = synopsis[:max_length]
    last_period = truncated.rfind('.')
    last_space = truncated.rfind(' ')
    
    if last_period > max_length - 50:  # If period is close to limit
        return synopsis[:last_period + 1]
    elif last_space > 0:
        return synopsis[:last_space] + "..."
    else:
        return synopsis[:max_length] + "..."

def search_anilist(anime_name):
    """Search anime on AniList and get banner/cover image"""
    query = '''
    query ($search: String) {
        Media (search: $search, type: ANIME) {
            id
            title {
                romaji
                english
                native
            }
            bannerImage
            coverImage {
                extraLarge
                large
                medium
            }
            averageScore
            description
            status
        }
    }
    '''
    
    variables = {
        'search': anime_name
    }
    
    try:
        response = requests.post(
            anilist_api_url,
            json={'query': query, 'variables': variables},
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and data['data']['Media']:
                media = data['data']['Media']
                return {
                    'id': media['id'],
                    'banner': media.get('bannerImage'),
                    'cover': media.get('coverImage', {}).get('extraLarge'),
                    'rating': media.get('averageScore'),
                    'description': media.get('description'),
                    'status': media.get('status', '').lower()
                }
    except Exception as e:
        print(f"AniList search error: {e}")
    
    return None

@app.on_message(filters.command("start"))
async def start_command(Client, message):
    global anime_cache
    if not anime_cache:
        anime_cache = await load_anime_cache()
    
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
        [InlineKeyboardButton("😁 Click Me", url="https://t.me/share/url?url=%F0%9F%8E%89+Join+@Aniflix_Official+for+the+best+Hindi+Dubbed+Anime!+Don't+miss+out+on+your+favorites,+all+in+one+place!+%F0%9F%8E%AC%E2%9C%A8")]
    ]

    await message.reply_photo(
        "https://iili.io/39xn6H7.md.jpg",
        caption=start_text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

def fetch_anime_aid(anime_name):
    try:
        response = requests.get(anime_api_url)
        if response.status_code == 200:
            data = response.json()
            for anime in data:
                if anime["name"].lower() == anime_name.lower():
                    return anime["aid"]
    except:
        pass
    return None

def search_anime(anime_name):
    try:
        url = f"{kitsu_api_url}/anime?filter[text]={anime_name}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and data['data']:
                return data['data'][0]['id'], data['data'][0]['attributes'].get('posterImage', {}).get('original')
    except:
        pass
    return None, None

def fetch_kitsu_details(anime_id):
    try:
        url = f"{kitsu_api_url}/anime/{anime_id}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if 'data' in data:
                anime_data = data['data']['attributes']
                rating = anime_data.get('averageRating', 'N/A')
                if rating != 'N/A' and float(rating) > 10:
                    rating = str(round(float(rating) / 10, 2))
                synopsis = anime_data.get('synopsis', 'No synopsis available.')
                return rating, synopsis, anime_data.get('status', '').lower(), anime_data.get('posterImage', {}).get('original')
    except:
        pass
    return "N/A", "No synopsis available", "finished", None

def fetch_episode_image(anime_id, episode_number):
    """Fetch episode-specific image and synopsis from Kitsu"""
    try:
        url = f"{kitsu_api_url}/anime/{anime_id}/episodes?filter[number]={episode_number}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and data['data']:
                episode_data = data['data'][0]['attributes']
                thumbnail = episode_data.get('thumbnail', {})
                episode_image = thumbnail.get('original') if thumbnail else None
                episode_synopsis = episode_data.get('synopsis', None)
                return episode_image, episode_synopsis
    except:
        pass
    return None, None

def extract_season_number(anime_name):
    match = re.search(r'season (\d+)', anime_name, re.IGNORECASE)
    return match.group(1).zfill(2) if match else "01"

def clean_html_tags(text):
    """Remove HTML tags from text and handle special characters"""
    if not text:
        return text
    
    # Remove HTML tags
    clean = re.compile('<.*?>')
    text = re.sub(clean, '', text)
    
    # Handle common HTML entities
    text = text.replace('&quot;', '"')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&nbsp;', ' ')
    text = text.replace('<br>', '\n')
    text = text.replace('<br/>', '\n')
    text = text.replace('<br />', '\n')
    
    return text.strip()

def format_spoiler_text(text):
    """Format spoiler text to avoid deployment issues"""
    if not text or text == "No synopsis available.":
        return "No synopsis available."
    
    # Clean HTML tags first
    text = clean_html_tags(text)
    
    # Escape markdown characters that might cause issues
    text = text.replace('|', '\\|')
    text = text.replace('*', '\\*')
    text = text.replace('_', '\\_')
    text = text.replace('`', '\\`')
    text = text.replace('[', '\\[')
    text = text.replace(']', '\\]')
    text = text.replace('(', '\\(')
    text = text.replace(')', '\\)')
    
    return text

async def format_update_post(anime_name, episode_number):
    # Get Kitsu data first
    anime_id, poster_image = search_anime(anime_name)
    if not anime_id:
        return f"Failed to find anime '{anime_name}' on Kitsu.", None, None, None

    kitsu_rating, anime_synopsis, airing_status, fallback_image = fetch_kitsu_details(anime_id)
    episode_image, episode_synopsis = fetch_episode_image(anime_id, episode_number)
    
    # Get AniList data for better images and backup data
    anilist_data = search_anilist(anime_name)
    
    # Image priority: Episode image > AniList banner > AniList cover > Kitsu poster
    final_image = None
    if episode_image:
        final_image = episode_image
    elif anilist_data and anilist_data.get('banner'):
        final_image = anilist_data['banner']
    elif anilist_data and anilist_data.get('cover'):
        final_image = anilist_data['cover']
    else:
        final_image = fallback_image or poster_image
    
    # Synopsis priority: Episode synopsis > Kitsu synopsis > AniList description
    synopsis = None
    if episode_synopsis:
        synopsis = episode_synopsis
    elif anime_synopsis and anime_synopsis != "No synopsis available.":
        synopsis = anime_synopsis
    elif anilist_data and anilist_data.get('description'):
        synopsis = anilist_data['description']
    else:
        synopsis = "No synopsis available."
    
    # Rating priority: Kitsu > AniList
    rating = kitsu_rating
    if rating == "N/A" and anilist_data and anilist_data.get('rating'):
        rating = str(round(float(anilist_data['rating']) / 10, 2))
    
    # Clean synopsis
    if synopsis and "Source:" in synopsis:
        source_start = synopsis.find("(Source:")
        source_end = synopsis.find(")", source_start) + 1
        if source_end > source_start:
            synopsis = synopsis.replace(synopsis[source_start:source_end], "").strip()

    # Clean and format synopsis for spoiler
    synopsis = format_spoiler_text(synopsis)
    synopsis = truncate_synopsis(synopsis, 200)

    anime_aid = fetch_anime_aid(anime_name)
    watch_url = f"https://aniflix.in/detail?aid={anime_aid}" if anime_aid else None
    download_url = f"https://hindi.aniflix.in/search?q={anime_name.replace(' ', '+')}"

    season_number = extract_season_number(anime_name)
    season_bullet = season_bullets.get(season_number, "⓪")

    # Fixed caption format with proper spoiler handling
    post_caption = (
        f"> ⛩ **{anime_name}**\n"
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

    # Ensure the caption length does not exceed the limit
    while len(post_caption) > 1024:
        # Reduce synopsis length further
        synopsis = truncate_synopsis(synopsis, len(synopsis) - 50)
        synopsis = format_spoiler_text(synopsis)
        post_caption = (
            f"> ⛩ **{anime_name}**\n"
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

@app.on_message(filters.command("w") | filters.command("d"))
async def request_anime_name(client, message):
    global anime_cache
    if not anime_cache:
        anime_cache = await load_anime_cache()
    
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
    
    global anime_cache
    user_data = user_inputs[user_id]
    
    if "anime_name" not in user_data:
        anime_input = message.text.strip()
        
        # Check for exact match first
        exact_match = None
        for anime in anime_cache:
            if anime.lower() == anime_input.lower():
                exact_match = anime
                break
        
        if exact_match:
            user_data["anime_name"] = exact_match
            await message.reply_text("Please send me the episode number:")
        else:
            # Get suggestions for similar names
            suggestions = get_anime_suggestions(anime_input, anime_cache)
            
            if suggestions:
                buttons = []
                for suggestion in suggestions[:5]:  # Limit to 5 suggestions
                    buttons.append([InlineKeyboardButton(
                        f"📺 {suggestion}", 
                        callback_data=f"suggest_{suggestion}"
                    )])
                
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

        # Only one button based on command
        if command == "w" and watch_url:
            button = InlineKeyboardButton("✦ ＷＡＴＣＨ  ＮＯＷ ✦", url=watch_url)
        elif command == "d":
            button = InlineKeyboardButton("✦ D O W N L O A D ✦", url=download_url)
        else:
            button = InlineKeyboardButton("✦ D O W N L O A D ✦", url=download_url)

        await message.reply_photo(
            episode_image, 
            caption=post_caption, 
            reply_markup=InlineKeyboardMarkup([[button]])
        )

        # Clean up user data
        if message.from_user.id in user_inputs:
            del user_inputs[message.from_user.id]

    except Exception as e:
        await message.reply_text(
            f"❌ **Error occurred!**\n\n"
            f"Something went wrong: {str(e)[:100]}...\n\n"
            "Please try again with `/w` or `/d` command."
        )

# --------------------- Run Both Apps ---------------------
def run_telebot():
    app.run()

if __name__ == "__main__":
    t1 = threading.Thread(target=run_telebot)
    t2 = threading.Thread(target=run_health_check)
    t1.start()
    t2.start()
