from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from config import *
from random import choice
import requests
import re

app = Client("ANIFLIX_POST_BOT", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

kitsu_api_url = "https://kitsu.io/api/edge"
anime_api_url = "https://raw.githubusercontent.com/OtakuFlix/ADATA/refs/heads/main/anime_data.txt"
user_inputs = {}

season_bullets = {
    "01": "❶", "02": "❷", "03": "❸", "04": "❹", "05": "❺",
    "06": "❻", "07": "❼", "08": "❽", "09": "❾", "10": "❿",
    "11": "⓫", "12": "⓬", "13": "⓭", "14": "⓮", "15": "⓯",
    "16": "⓰", "17": "⓱", "18": "⓲", "19": "⓳", "20": "⓴"
}

@app.on_message(filters.command("start"))
async def start_command(Client, message):
    start_text = (
        "**👋 Welcome to ANIFLIX Bot!**\n\n"
        "🔥 I can help you **find & watch anime episodes** easily.\n"
        "🎥 Use /w to get anime episodes.\n"
        "📥 Use /d to find download links.\n\n"
        "⚡ **How to use:**\n"
        "1️⃣ Send /w or /d command.\n"
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
    response = requests.get(anime_api_url).json()
    for anime in response:
        if anime["name"].lower() == anime_name.lower():
            return anime["aid"]
    return None

def search_anime(anime_name):
    url = f"{kitsu_api_url}/anime?filter[text]={anime_name}"
    response = requests.get(url).json()
    if 'data' in response and response['data']:
        return response['data'][0]['id'], response['data'][0]['attributes'].get('posterImage', {}).get('original')
    return None, None

def fetch_kitsu_details(anime_id):
    url = f"{kitsu_api_url}/anime/{anime_id}"
    response = requests.get(url).json()
    if 'data' in response:
        anime_data = response['data']['attributes']
        rating = anime_data.get('averageRating', 'N/A')
        if rating != 'N/A' and float(rating) > 10:
            rating = str(round(float(rating) / 10, 2))
        synopsis = anime_data.get('synopsis', 'No synopsis available.')
        return rating, synopsis, anime_data.get('status', '').lower(), anime_data.get('posterImage', {}).get('original')
    return "N/A", "No synopsis available", "finished", None

def fetch_episode_image(anime_id, episode_number):
    url = f"{kitsu_api_url}/anime/{anime_id}/episodes?filter[number]={episode_number}"
    response = requests.get(url).json()
    if 'data' in response and response['data']:
        episode_data = response['data'][0]['attributes']
        thumbnail = episode_data.get('thumbnail', {})
        return thumbnail.get('original') if thumbnail else None, episode_data.get('synopsis', None)
    return None, None

def extract_season_number(anime_name):
    match = re.search(r'season (\d+)', anime_name, re.IGNORECASE)
    return match.group(1).zfill(2) if match else "01"

async def format_update_post(anime_name, episode_number):
    anime_id, poster_image = search_anime(anime_name)
    if not anime_id:
        return f"Failed to find anime '{anime_name}' on Kitsu.", None, None, None

    kitsu_rating, anime_synopsis, airing_status, fallback_image = fetch_kitsu_details(anime_id)
    episode_image, episode_synopsis = fetch_episode_image(anime_id, episode_number)
    episode_image = episode_image or fallback_image or poster_image

    if episode_synopsis and "Source:" in episode_synopsis:
        source_start = episode_synopsis.find("(Source:")
        source_end = episode_synopsis.find(")", source_start) + 1
        episode_synopsis = episode_synopsis.replace(episode_synopsis[source_start:source_end], "").strip()

    synopsis_text = (
        f"├ ⚆ **Spoiler:**\n"
        f">|| {episode_synopsis or anime_synopsis} ||"
    )

    anime_aid = fetch_anime_aid(anime_name)
    watch_url = f"https://aniflix.in/detail?aid={anime_aid}" if anime_aid else None
    download_url = f"https://hindi.aniflix.in/search?q={anime_name.replace(' ', '+')}"

    season_number = extract_season_number(anime_name)
    season_bullet = season_bullets.get(season_number, "⓪")

    post_caption = (
        f"> ⛩ **{anime_name}**\n"
        f"┌───────────────────\n"
        f"├ {season_bullet} 𝗦𝗲𝗮𝘀𝗼𝗻 : {season_number}\n"
        f"├ ⚅ 𝗘𝗽𝗶𝘀𝗼𝗱𝗲 : {episode_number}\n"
        f"├ 𖦤 𝗔𝘂𝗱𝗶𝗼 : 𝗛𝗶𝗻𝗱𝗶 #𝗢𝗳𝗳𝗶𝗰𝗶𝗮𝗹\n"
        f"├ ⌬ 𝗤𝘂𝗮𝗹𝗶𝘁𝘆 : 𝟭𝟬𝟴𝟬𝗽\n"
        f"├ ✦ 𝗥𝗮𝘁𝗶𝗻𝗴 : {kitsu_rating}/10 ‧ 𝗜𝗠𝗗𝗯\n"
        f"├───────────────────\n"
        f"{synopsis_text}\n"
        f"├───────────────────\n"
        f"├ ✧ Powered By ‧ [𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/ANIFLIX_OFFICIAL) ✧\n"
        f"├ ⌲ Share ‧ [𝗦𝗛𝗔𝗥𝗘 𝗔𝗡𝗜𝗙𝗟𝗜𝗫](https://t.me/share/url?url=%F0%9F%8E%89+Join+@Aniflix_Official+for+the+best+Hindi+Dubbed+Anime!+Don't+miss+out+on+your+favorites,+all+in+one+place!+%F0%9F%8E%AC%E2%9C%A8) ✧\n"
        f"└───────────────────\n"
    )

    # Ensure the caption length does not exceed the limit
    if len(post_caption) > 1024:
        post_caption = post_caption[:500] + "..."

    return post_caption, episode_image, watch_url, download_url

@app.on_message(filters.command("w") | filters.command("d"))
async def request_anime_name(client, message):
    user_inputs[message.from_user.id] = {"command": message.command[0]}
    await message.reply_text("Please send me the anime name:")

@app.on_message(filters.text & ~filters.command(["w", "d"]))
async def capture_input(client, message):
    user_id = message.from_user.id
    if user_id not in user_inputs:
        return
    
    user_data = user_inputs[user_id]
    if "anime_name" not in user_data:
        user_data["anime_name"] = message.text
        await message.reply_text("Please send me the episode number:")
    elif "episode_number" not in user_data:
        user_data["episode_number"] = message.text.zfill(2)
        await finalize_post(client, message, user_data)

async def finalize_post(client, message, user_data):
    anime_name = user_data["anime_name"]
    episode_number = user_data["episode_number"]
    command = user_data["command"]

    post_caption, episode_image, watch_url, download_url = await format_update_post(anime_name, episode_number)

    buttons = []

    if watch_url:  
        buttons.append([InlineKeyboardButton("✦ ＷＡＴＣＨ  ＮＯＷ ✦", url=watch_url)])
    
    if command == "d":
        buttons.append([InlineKeyboardButton("✦ D O W N L O A D ✦", url=download_url)])

    await message.reply_photo(episode_image, caption=post_caption, reply_markup=InlineKeyboardMarkup(buttons))

app.run()
