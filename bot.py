from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from config import *
import requests
from difflib import SequenceMatcher
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

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

app = Client(
    "ANIFLIX_POST_BOT",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

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

async def load_anime_cache():
    try:
        resp = requests.get(anime_api_url)
        if resp.status_code == 200:
            return [anime["name"] for anime in resp.json()]
    except: pass
    return []

def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def get_anime_suggestions(input_name, anime_list, limit=5):
    return [
        anime for anime, _ in sorted(
            [(anime, similarity(input_name, anime)) for anime in anime_list if similarity(input_name, anime) > 0.4],
            key=lambda x: x[1], reverse=True
        )[:limit]
    ]

def clean_html_tags(text):
    if not text: return text
    text = re.sub('<.*?>', '', text)
    for a, b in [('&quot;', '"'), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&nbsp;', ' '), ('<br>', '\n'), ('<br/>', '\n'), ('<br />', '\n')]:
        text = text.replace(a, b)
    return text.strip()

def format_spoiler_text(text):
    if not text or text == "No synopsis available.": return "No synopsis available."
    text = clean_html_tags(text)
    for ch in '|*_`[]()':
        text = text.replace(ch, f"\\{ch}")
    return text

def truncate_synopsis(synopsis, max_length=200):
    if not synopsis or synopsis == "No synopsis available.": return "No synopsis available."
    if len(synopsis) <= max_length: return synopsis
    truncated = synopsis[:max_length]
    for sep in ['.', ' ']:
        idx = truncated.rfind(sep)
        if idx > max_length - 50: return synopsis[:idx+1] if sep=='.' else synopsis[:idx]+"..."
    return synopsis[:max_length]+"..."

# Step 1: Get correct name/aid from your database
def get_aid_for_anime(anime_name):
    try:
        resp = requests.get(anime_api_url)
        if resp.status_code == 200:
            for anime in resp.json():
                if anime["name"].lower() == anime_name.lower():
                    return anime["name"], anime.get("aid")
    except Exception as e:
        print("AID fetch error:", e)
    return None, None

# Step 2: Get anilist id from anilist search
def get_anilist_id(anime_name):
    query = '''
    query ($search: String) { Media (search: $search, type: ANIME) { id } }
    '''
    try:
        resp = requests.post(
            anilist_api_url,
            json={'query': query, 'variables': {'search': anime_name}},
            headers={'Content-Type': 'application/json'}
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('data') and data['data'].get('Media'):
                return data['data']['Media']['id']
    except Exception as e:
        print("AniList ID error:", e)
    return None

# Step 3: Get AniZip Data (primary source)
def fetch_ani_zip(anilist_id):
    try:
        r = requests.get(f"https://api.ani.zip/mappings?anilist_id={anilist_id}", timeout=4)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print("Ani.zip error:", e)
    return None

def search_kitsu_anime(anime_name):
    try:
        url = f"{kitsu_api_url}/anime?filter[text]={anime_name}"
        resp = requests.get(url)
        if resp.status_code == 200:
            data = resp.json()
            if 'data' in data and data['data']:
                return data['data'][0]['id'], data['data'][0]['attributes'].get('posterImage', {}).get('original')
    except: pass
    return None, None

def fetch_kitsu_details(anime_id):
    try:
        url = f"{kitsu_api_url}/anime/{anime_id}"
        resp = requests.get(url)
        if resp.status_code == 200:
            data = resp.json()
            if 'data' in data:
                d = data['data']['attributes']
                rating = d.get('averageRating', 'N/A')
                if rating != 'N/A' and float(rating) > 10:
                    rating = str(round(float(rating) / 10, 2))
                synopsis = d.get('synopsis', 'No synopsis available.')
                return rating, synopsis, d.get('status', '').lower(), d.get('posterImage', {}).get('original')
    except: pass
    return "N/A", "No synopsis available", "finished", None

def fetch_episode_image(anime_id, episode_number):
    try:
        url = f"{kitsu_api_url}/anime/{anime_id}/episodes?filter[number]={episode_number}"
        resp = requests.get(url)
        if resp.status_code == 200:
            data = resp.json()
            if 'data' in data and data['data']:
                ep = data['data'][0]['attributes']
                thumb = ep.get('thumbnail', {})
                return thumb.get('original') if thumb else None, ep.get('synopsis', None)
    except: pass
    return None, None

def extract_season_number(anime_name):
    match = re.search(r'season (\d+)', anime_name, re.IGNORECASE)
    return match.group(1).zfill(2) if match else "01"

def search_anilist_legacy(anime_name):
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
        resp = requests.post(
            anilist_api_url,
            json={'query': query, 'variables': {'search': anime_name}},
            headers={'Content-Type': 'application/json'}
        )
        if resp.status_code == 200:
            data = resp.json()
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
    # 1. Get official name + aid
    official_name, anime_aid = get_aid_for_anime(anime_name)
    if not official_name:
        return f"No anime found for '{anime_name}'.", None, None, None

    # 2. Get Anilist ID from AniList
    anilist_id = get_anilist_id(official_name)
    if anilist_id:
        # 3. Get Ani.zip data
        zip_data = fetch_ani_zip(anilist_id)
        if zip_data and 'episodes' in zip_data:
            ep_info = zip_data['episodes'].get(str(int(episode_number)))
            titles = zip_data.get('titles', {})
            anime_title = titles.get('en') or titles.get('x-jat') or official_name
            ep_title = (ep_info and ep_info.get('title', {}).get('en')) or ''
            ep_summary = ep_info.get('overview') if ep_info else "No synopsis available."
            ep_image = ep_info.get('image') if ep_info else None
            ep_rating = ep_info.get('rating', "N/A") if ep_info else "N/A"
            season_number = ep_info.get('seasonNumber', 1) if ep_info else 1
            season_bullet = season_bullets.get(str(season_number).zfill(2), "⓪")
            synopsis = truncate_synopsis(format_spoiler_text(ep_summary))
            watch_url = f"https://aniflix.in/detail?aid={anime_aid}" if anime_aid else None
            download_url = f"https://hindi.aniflix.in/search?q={anime_title.replace(' ', '+')}"
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
                f"├ ⌲ Share ‧ [𝗦𝗛𝗔𝗥𝗘 𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/share/url?url=%F0%9F%8E%89+Join+@Aniflix_Official+for+the+best+Hindi+Dubbed+Anime!+Don't+miss+out+on+your+favorites,+all+in+one+place!+%F0%9F%8E%AC%E2%9C%A8) ✧\n"
                f"└───────────────────\n"
            )
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
                    f"├ ⌲ Share ‧ [𝗦𝗛𝗔𝗥𝗘 𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/share/url?url=%F0%9F%8E%89+Join+@Aniflix_Official+for+the+best+Hindi+Dubbed+Anime!+Don't+miss+out+on+your+favorites,+all+in+one+place!+%F0%9F%8E%AC%E2%9C%A8) ✧\n"
                    f"└───────────────────\n"
                )
            return post_caption, ep_image, watch_url, download_url

    # ---- fallback: legacy logic ----
    anime_id, poster_image = search_kitsu_anime(official_name)
    if not anime_id:
        return f"Failed to find anime '{official_name}' on Kitsu.", None, None, None
    kitsu_rating, anime_synopsis, airing_status, fallback_image = fetch_kitsu_details(anime_id)
    episode_image, episode_synopsis = fetch_episode_image(anime_id, episode_number)
    anilist_data = search_anilist_legacy(official_name)
    final_image = episode_image or (anilist_data and anilist_data.get('banner')) or (anilist_data and anilist_data.get('cover')) or fallback_image or poster_image
    synopsis = episode_synopsis or (anime_synopsis if anime_synopsis != "No synopsis available." else "") or (anilist_data and anilist_data.get('description')) or "No synopsis available."
    rating = kitsu_rating
    if rating == "N/A" and anilist_data and anilist_data.get('rating'):
        rating = str(round(float(anilist_data['rating']) / 10, 2))
    if "Source:" in synopsis:
        sidx = synopsis.find("(Source:")
        eidx = synopsis.find(")", sidx)+1
        if sidx > 0 and eidx > sidx: synopsis = synopsis.replace(synopsis[sidx:eidx], "").strip()
    synopsis = truncate_synopsis(format_spoiler_text(synopsis), 200)
    season_number = extract_season_number(official_name)
    season_bullet = season_bullets.get(season_number, "⓪")
    watch_url = f"https://aniflix.in/detail?aid={anime_aid}" if anime_aid else None
    download_url = f"https://hindi.aniflix.in/search?q={official_name.replace(' ', '+')}"
    post_caption = (
        f"> ⛩ **{official_name}**\n"
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
        [InlineKeyboardButton("😁 Click Me", url="https://t.me/share/url?url=%F0%9F%8E%89+Join+@Aniflix_Official+for+the+best+Hindi+Dubbed+Anime!+Don't+miss+out+on+your+favorites,+all+in+one+place!+%F0%9F%8E%AC%E2%9C%A8")]
    ]
    await message.reply_photo(
        "https://iili.io/39xn6H7.md.jpg",
        caption=start_text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_message(filters.command(["w", "d"]))
async def request_anime_name(client, message):
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
        if command == "w" and watch_url:
            button = InlineKeyboardButton("✦ ＷＡＴＣＨ  ＮＯＷ ✦", url=watch_url)
        else:
            button = InlineKeyboardButton("✦ D O W N L O A D ✦", url=download_url)
        await message.reply_photo(
            episode_image, 
            caption=post_caption, 
            reply_markup=InlineKeyboardMarkup([[button]])
        )
        if message.from_user.id in user_inputs:
            del user_inputs[message.from_user.id]
    except Exception as e:
        await message.reply_text(
            f"❌ **Error occurred!**\n\n"
            f"Something went wrong: {str(e)[:100]}...\n\n"
            "Please try again with `/w` or `/d` command."
        )

if __name__ == "__main__":
    threading.Thread(target=run_health_check_server, daemon=True).start()
    app.run()
