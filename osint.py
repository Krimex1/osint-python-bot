import asyncio
import logging
import re
import json
import sqlite3
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import requests
import phonenumbers
from phonenumbers import geocoder, carrier, timezone
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BufferedInputFile
from aiogram.exceptions import TelegramBadRequest
import secrets
import string
import hashlib
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from io import BytesIO
from bs4 import BeautifulSoup

# =========================
# НАСТРОЙКИ
# =========================
BOT_TOKEN = ""
DB_PATH = "osint_bot.db"
ADMIN_ID = 

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

bot_instance = None

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
}

# =========================
# СОЦИАЛЬНЫЕ СЕТИ (50+)
# =========================
SOCIAL_SITES = {
    "Twitter/X": "https://twitter.com/{}", "Instagram": "https://instagram.com/{}", "Facebook": "https://facebook.com/{}",
    "TikTok": "https://tiktok.com/@{}", "YouTube": "https://youtube.com/@{}", "LinkedIn": "https://linkedin.com/in/{}",
    "Reddit": "https://reddit.com/user/{}", "Pinterest": "https://pinterest.com/{}", "Tumblr": "https://{}.tumblr.com",
    "Medium": "https://medium.com/@{}", "Snapchat": "https://snapchat.com/add/{}", "GitHub": "https://github.com/{}",
    "GitLab": "https://gitlab.com/{}", "Behance": "https://behance.net/{}", "Dribbble": "https://dribbble.com/{}",
    "DeviantArt": "https://deviantart.com/{}", "CodePen": "https://codepen.io/{}", "HackerRank": "https://hackerrank.com/{}",
    "Kaggle": "https://kaggle.com/{}", "Telegram": "https://t.me/{}", "VK": "https://vk.com/{}",
    "Одноклассники": "https://ok.ru/{}", "Twitch": "https://twitch.tv/{}", "Habr": "https://habr.com/ru/users/{}",
    "Pikabu": "https://pikabu.ru/@{}", "Quora": "https://quora.com/profile/{}", "Spotify": "https://open.spotify.com/user/{}",
    "SoundCloud": "https://soundcloud.com/{}", "Vimeo": "https://vimeo.com/{}", "Steam": "https://steamcommunity.com/id/{}",
    "PlayStation": "https://psnprofiles.com/{}", "Roblox": "https://roblox.com/users/{}/profile",
    "Patreon": "https://patreon.com/{}", "Substack": "https://{}.substack.com", "AboutMe": "https://about.me/{}",
    "Flickr": "https://flickr.com/people/{}", "Goodreads": "https://goodreads.com/{}", "Last.fm": "https://last.fm/user/{}",
    "Bandcamp": "https://{}.bandcamp.com", "Etsy": "https://etsy.com/shop/{}", "Fiverr": "https://fiverr.com/{}",
    "Cash.app": "https://cash.app/${}", "Venmo": "https://venmo.com/{}", "Ko-fi": "https://ko-fi.com/{}",
    "Linktree": "https://linktr.ee/{}", "Carrd": "https://{}.carrd.co"
}

# =========================
# БАЗА ДАННЫХ
# =========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, is_premium INTEGER DEFAULT 0, premium_until TEXT,
        total_searches INTEGER DEFAULT 0, registered_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    
    cur.execute("""CREATE TABLE IF NOT EXISTS sub_codes (
        code TEXT PRIMARY KEY, is_used INTEGER DEFAULT 0, used_by INTEGER, used_at TEXT)""")
    
    cur.execute("""CREATE TABLE IF NOT EXISTS search_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, query TEXT, query_type TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (user_id))""")
    
    cur.execute("""CREATE TABLE IF NOT EXISTS search_cache (
        query TEXT, query_type TEXT, result TEXT, cached_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (query, query_type))""")
    
    cur.execute("""CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, query TEXT, query_type TEXT,
        note TEXT, added_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (user_id))""")
    
    cur.execute("""CREATE TABLE IF NOT EXISTS local_data (
        query TEXT, 
        query_type TEXT, 
        data TEXT, 
        added_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (query, query_type)
    )""")
    
    conn.commit()
    
    cur.execute("SELECT COUNT(*) FROM sub_codes")
    if cur.fetchone()[0] == 0:
        codes = generate_codes(50)
        cur.executemany("INSERT INTO sub_codes (code, is_used) VALUES (?, 0)", [(c,) for c in codes])
        conn.commit()
        logger.info("✅ Сгенерировано 50 кодов")
    
    conn.close()

def generate_codes(n: int, length: int = 16) -> list[str]:
    alphabet = string.ascii_uppercase + string.digits
    codes = set()
    while len(codes) < n:
        codes.add("".join(secrets.choice(alphabet) for _ in range(length)))
    return list(codes)

def generate_and_store_codes(n: int) -> list[str]:
    codes = generate_codes(n)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executemany("INSERT OR IGNORE INTO sub_codes (code, is_used) VALUES (?, 0)", [(c,) for c in codes])
    conn.commit()
    conn.close()
    return codes

def get_or_create_user(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, is_premium, premium_until, total_searches FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        cur.execute("SELECT user_id, is_premium, premium_until, total_searches FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
    conn.close()
    return row

def update_user_usage(user_id: int, *, search_inc: int = 0, add_premium_days: int = 0):
    row = get_or_create_user(user_id)
    _, is_premium, premium_until, total_searches = row
    total_searches += search_inc
    
    if add_premium_days > 0:
        if premium_until:
            try:
                current_until = datetime.fromisoformat(premium_until).date()
                new_until = current_until + timedelta(days=add_premium_days) if current_until >= date.today() else date.today() + timedelta(days=add_premium_days)
            except:
                new_until = date.today() + timedelta(days=add_premium_days)
        else:
            new_until = date.today() + timedelta(days=add_premium_days)
        premium_until = new_until.isoformat()
        is_premium = 1
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_premium = ?, premium_until = ?, total_searches = ? WHERE user_id = ?",
                (is_premium, premium_until, total_searches, user_id))
    conn.commit()
    conn.close()

def get_user_status(user_id: int):
    row = get_or_create_user(user_id)
    _, is_premium, premium_until, total_searches = row
    
    if is_premium and premium_until:
        try:
            until_date = datetime.fromisoformat(premium_until).date()
            if until_date < date.today():
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute("UPDATE users SET is_premium = 0, premium_until = NULL WHERE user_id = ?", (user_id,))
                conn.commit()
                conn.close()
                is_premium = 0
                premium_until = None
        except:
            pass
    
    return bool(is_premium), total_searches, premium_until

def activate_code(user_id: int, code: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT code, is_used, used_by FROM sub_codes WHERE code = ?", (code,))
    row = cur.fetchone()
    
    if row is None:
        conn.close()
        return "❌ Код не найден"
    
    _, is_used, used_by = row
    if is_used:
        conn.close()
        return f"❌ Код использован (user {used_by})"
    
    cur.execute("UPDATE sub_codes SET is_used = 1, used_by = ?, used_at = ? WHERE code = ?",
                (user_id, datetime.utcnow().isoformat(), code))
    conn.commit()
    conn.close()
    
    update_user_usage(user_id, add_premium_days=30)
    return "✅ Премиум активирован на 30 дней!"

def add_to_history(user_id: int, query: str, query_type: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO search_history (user_id, query, query_type) VALUES (?, ?, ?)", (user_id, query, query_type))
    cur.execute("""DELETE FROM search_history WHERE user_id = ? AND id NOT IN (
        SELECT id FROM search_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 50)""", (user_id, user_id))
    conn.commit()
    conn.close()

def get_user_history(user_id: int, limit: int = 10):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT query, query_type, timestamp FROM search_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?", (user_id, limit))
    history = cur.fetchall()
    conn.close()
    return history

def clear_user_history(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM search_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_cached_result(query: str, query_type: str, max_age_hours: int = 24):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT result, cached_at FROM search_cache WHERE query = ? AND query_type = ?", (query, query_type))
    row = cur.fetchone()
    conn.close()
    
    if row:
        result, cached_at = row
        try:
            if datetime.now() - datetime.fromisoformat(cached_at) < timedelta(hours=max_age_hours):
                return result
        except:
            pass
    return None

def cache_result(query: str, query_type: str, result: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO search_cache (query, query_type, result, cached_at) VALUES (?, ?, ?, ?)",
                (query, query_type, result, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def add_to_favorites(user_id: int, query: str, query_type: str, note: str = ""):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO favorites (user_id, query, query_type, note) VALUES (?, ?, ?, ?)", (user_id, query, query_type, note))
    conn.commit()
    conn.close()

def get_favorites(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, query, query_type, note, added_at FROM favorites WHERE user_id = ? ORDER BY added_at DESC", (user_id,))
    favorites = cur.fetchall()
    conn.close()
    return favorites

def get_bot_stats():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
    premium_users = cur.fetchone()[0]
    
    cur.execute("SELECT SUM(total_searches) FROM users")
    total_searches = cur.fetchone()[0] or 0
    
    cur.execute("SELECT COUNT(*) FROM search_history WHERE date(timestamp) = date('now')")
    searches_today = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM sub_codes WHERE is_used = 0")
    unused_codes = cur.fetchone()[0]
    
    conn.close()
    
    return {
        "total_users": total_users, "premium_users": premium_users,
        "total_searches": total_searches, "searches_today": searches_today, "unused_codes": unused_codes
    }

# =========================
# КНОПКИ
# =========================
def get_main_keyboard(is_premium: bool, user_id: int = None) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🔍 Начать поиск", callback_data="start_search")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="my_status"),
         InlineKeyboardButton(text="📜 История", callback_data="show_history")],
        [InlineKeyboardButton(text="⭐ Избранное", callback_data="show_favorites"),
         InlineKeyboardButton(text="🛠 Инструменты", callback_data="tools_menu")],
        [InlineKeyboardButton(text="ℹ️ Справка", callback_data="help")]
    ]
    
    if not is_premium:
        buttons.append([InlineKeyboardButton(text="💎 Купить премиум", callback_data="activate")])
    
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_search_type_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📧 Email", callback_data="search_email")],
        [InlineKeyboardButton(text="👤 Username", callback_data="search_username")],
        [InlineKeyboardButton(text="👥 Имя Фамилия", callback_data="search_full_name")],
        [InlineKeyboardButton(text="📱 Телефон", callback_data="search_phone")],
        [InlineKeyboardButton(text="🆔 Telegram ID", callback_data="search_telegram_id")],
        [InlineKeyboardButton(text="🛰 IP-адрес", callback_data="search_ip")],
        [InlineKeyboardButton(text="🌐 Домен", callback_data="search_domain")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_tools_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🎲 Генератор Username", callback_data="tool_username_gen")],
        [InlineKeyboardButton(text="📞 Конвертер телефонов", callback_data="tool_phone_conv")],
        [InlineKeyboardButton(text="🔐 Генератор Dorks", callback_data="tool_dorks_gen")],
        [InlineKeyboardButton(text="📧 Проверка Gravatar", callback_data="tool_gravatar")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🔑 Генерировать коды", callback_data="admin_generate")],
        [InlineKeyboardButton(text="➕ Выдать премиум", callback_data="admin_addtime")],
        [InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_result_keyboard(user_id: int, query: str, query_type: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="⭐ В избранное", callback_data=f"fav_add_{query_type}_{query[:30]}"),
         InlineKeyboardButton(text="📥 Экспорт TXT", callback_data=f"export_{query_type}_{query[:30]}")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# =========================
# РЕГУЛЯРКИ
# =========================
EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
DOMAIN_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})+$")
IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
PHONE_RE = re.compile(r"^[\+]?[\d\s\-\(\)]+$")
TELEGRAM_ID_RE = re.compile(r"^\d{5,15}$")

def is_email(q: str) -> bool:
    return bool(EMAIL_RE.match(q.strip()))

def is_domain(q: str) -> bool:
    return bool(DOMAIN_RE.match(q.strip()))

def is_ip(q: str) -> bool:
    return bool(IP_RE.match(q.strip()))

def is_phone(q: str) -> bool:
    return bool(PHONE_RE.match(q.strip()))

def is_telegram_id(q: str) -> bool:
    return bool(TELEGRAM_ID_RE.match(q.strip()))

def is_full_name(query: str) -> bool:
    parts = query.split()
    if len(parts) == 2:
        if all(part.replace('-', '').isalpha() for part in parts):
            return True
    return False

# =========================
# УМНЫЕ АЛГОРИТМЫ
# =========================
def generate_username_variants(username: str) -> list[str]:
    variants = [username.lower()]
    
    if '.' not in username:
        variants.append(username.lower().replace('_', '.'))
    
    if '_' not in username:
        variants.append(username.lower().replace('.', '_'))
    
    clean = re.sub(r'[^a-z0-9]', '', username.lower())
    if clean and clean not in variants:
        variants.append(clean)
    
    for num in ['123', '1', '01', '2024', '2025', '99', '88']:
        variant = username.lower() + num
        if variant not in variants:
            variants.append(variant)
    
    no_digits = re.sub(r'\d+', '', username.lower())
    if no_digits and no_digits not in variants:
        variants.append(no_digits)
    
    return list(dict.fromkeys(variants))[:20]

def get_gravatar_info(email: str) -> dict:
    email_hash = hashlib.md5(email.lower().strip().encode()).hexdigest()
    gravatar_url = f"https://gravatar.com/avatar/{email_hash}?d=404&s=200"
    
    try:
        response = requests.head(gravatar_url, timeout=5)
        if response.status_code == 200:
            return {
                "exists": True,
                "avatar_url": f"https://gravatar.com/avatar/{email_hash}?s=200",
                "profile_url": f"https://gravatar.com/{email_hash}.json"
            }
    except:
        pass
    
    return {"exists": False}

def analyze_telegram_id_pattern(tg_id: int) -> dict:
    info = {"is_bot": tg_id > 1000000000, "estimated_registration": "Неизвестно", "account_age": "Неизвестно"}
    
    if tg_id < 10000:
        info["estimated_registration"], info["account_age"] = "2013-2014", "11+ лет"
    elif tg_id < 100000:
        info["estimated_registration"], info["account_age"] = "2014-2015", "9-10 лет"
    elif tg_id < 1000000:
        info["estimated_registration"], info["account_age"] = "2015-2016", "8-9 лет"
    elif tg_id < 10000000:
        info["estimated_registration"], info["account_age"] = "2016-2017", "7-8 лет"
    elif tg_id < 100000000:
        info["estimated_registration"], info["account_age"] = "2017-2018", "6-7 лет"
    elif tg_id < 500000000:
        info["estimated_registration"], info["account_age"] = "2018-2020", "4-6 лет"
    elif tg_id < 1000000000:
        info["estimated_registration"], info["account_age"] = "2020-2022", "2-4 года"
    else:
        info["estimated_registration"], info["account_age"] = "2022-2025", "0-2 года"
    
    return info

def generate_google_dorks(query: str, query_type: str) -> list[str]:
    dorks = []
    
    if query_type == "email":
        dorks = [
            f'"{query}" password OR pass', f'"{query}" site:github.com',
            f'"{query}" site:pastebin.com', f'"{query}" filetype:pdf',
            f'"{query}" intext:"registered"', f'site:linkedin.com "{query}"'
        ]
    elif query_type == "username":
        dorks = [
            f'"{query}" profile', f'inurl:"{query}"',
            f'"{query}" site:github.com', f'"{query}" social'
        ]
    elif query_type == "phone":
        dorks = [
            f'"{query}"', f'"{query}" site:vk.com',
            f'"{query}" whatsapp OR telegram'
        ]
    elif query_type == "full_name":
        dorks = [
            f'"{query}" site:vk.com', f'"{query}" site:linkedin.com',
            f'"{query}" site:facebook.com', f'"{query}" email'
        ]
    
    return dorks

def predict_gender_by_name(name: str) -> str:
    name = name.lower().strip()
    
    male_endings = ['й', 'н', 'р', 'т', 'в', 'л', 'к', 'м', 'д', 'ий', 'ей']
    female_endings = ['а', 'я', 'ия', 'ья', 'на', 'ина']
    
    male_names = ['john', 'michael', 'david', 'james', 'robert', 'alex']
    female_names = ['mary', 'jennifer', 'linda', 'elizabeth', 'susan', 'sarah']
    
    if name in male_names:
        return "Мужской (95%)"
    elif name in female_names:
        return "Женский (95%)"
    
    for ending in female_endings:
        if name.endswith(ending):
            return "Женский (75%)"
    
    for ending in male_endings:
        if name.endswith(ending):
            return "Мужской (70%)"
    
    return "Не определён"

def estimate_age_by_username(username: str) -> str:
    year_match = re.search(r'(19|20)(\d{2})', username)
    if year_match:
        year = int(year_match.group(0))
        age = datetime.now().year - year
        if 0 < age < 100:
            return f"~{age} лет (год: {year})"
    
    if re.search(r'(00|01|02|03|04|05)', username):
        return "18-25 лет"
    elif re.search(r'(90|91|92|93|94|95)', username):
        return "28-35 лет"
    
    return "Не определён"

# =========================
# WEB SCRAPING
# =========================
def scrape_github_profile(username: str) -> dict:
    try:
        url = f"https://github.com/{username}"
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        if response.status_code != 200:
            return {"exists": False}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        data = {"exists": True, "url": url}
        
        name_elem = soup.find('span', {'class': 'p-name'})
        if name_elem:
            data['name'] = name_elem.text.strip()
        
        bio_elem = soup.find('div', {'class': 'p-note'})
        if bio_elem:
            data['bio'] = bio_elem.text.strip()
        
        return data
    except:
        return {"exists": False}

def scrape_vk_profile(username: str) -> dict:
    try:
        url = f"https://m.vk.com/{username}"
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        if response.status_code != 200:
            return {"exists": False}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        data = {"exists": True, "url": url}
        
        name_elem = soup.find('div', {'class': 'profile_name'})
        if name_elem:
            data['name'] = name_elem.text.strip()
        
        return data
    except:
        return {"exists": False}

def check_wayback_machine(domain: str) -> dict:
    try:
        url = f"https://archive.org/wayback/available?url={domain}"
        response = requests.get(url, headers=HEADERS, timeout=10)
        data = response.json()
        
        if data.get('archived_snapshots'):
            closest = data['archived_snapshots'].get('closest', {})
            return {"exists": True, "url": closest.get('url'), "timestamp": closest.get('timestamp')}
        
        return {"exists": False}
    except:
        return {"exists": False}

def check_breach_databases(email: str) -> list:
    return [
        {"service": "HaveIBeenPwned", "url": f"https://haveibeenpwned.com/account/{email}", "note": "Проверка утечек"},
        {"service": "DeHashed", "url": f"https://dehashed.com/search?query={email}", "note": "Требует регистрацию"},
        {"service": "LeakCheck", "url": "https://leakcheck.io/", "note": "Введите email"}
    ]

# =========================
# ПРОВЕРКА СОЦСЕТЕЙ
# =========================
def check_username_on_site(username: str, site_name: str, url_template: str):
    url = url_template.format(username)
    try:
        r = requests.head(url, headers=HEADERS, timeout=5, allow_redirects=True)
        return (True, url) if r.status_code == 200 else (False, url)
    except:
        return (None, url)

# =========================
# ФУНКЦИИ АНАЛИЗА
# =========================
async def analyze_username(username: str) -> str:
    cached = get_cached_result(username, "username", max_age_hours=48)
    if cached:
        return cached + "\n\n💾 Из кэша (<48ч)"
    
    result = [
        f"👤 АНАЛИЗ USERNAME",
        "═"*50,
        "",
        f"🔤 Username: {username}",
        f"📏 Длина: {len(username)} символов",
        "",
        "🤖 ML АНАЛИЗ:",
        f"  📅 Возраст: {estimate_age_by_username(username)}",
        "",
        "═"*50,
        "",
        "🔍 ПРОВЕРКА В 45+ СОЦИАЛЬНЫХ СЕТЯХ:",
        "",
        "⏳ Сканирование..."
    ]
    
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(check_username_on_site, username, n, u): n for n, u in SOCIAL_SITES.items()}
        
        found = []
        for future in futures:
            site_name = futures[future]
            exists, url = future.result()
            if exists:
                found.append(f"  ✅ {site_name}: {url}")
        
        if found:
            result.append("")
            result.append(f"🎯 НАЙДЕНО ({len(found)} платформ):")
            result.append("")
            result.extend(found)
        else:
            result.append("")
            result.append("❌ Профили не найдены")
    
    result.extend([
        "",
        "═"*50,
        "",
        "🌐 ДОПОЛНИТЕЛЬНО:",
        f"  • Namechk: https://namechk.com/?s={username}",
        f"  • Instant Username: https://instantusername.com/#/?q={username}",
        "",
        "💡 Проверьте варианты с точками, подчёркиваниями и цифрами"
    ])
    
    final_result = "\n".join(result)
    cache_result(username, "username", final_result)
    return final_result

async def analyze_full_name(full_name: str) -> str:
    parts = full_name.split()
    first_name, last_name = parts[0], parts[1] if len(parts) > 1 else ""
    
    result = [
        f"👥 ПОИСК ПО ИМЕНИ И ФАМИЛИИ",
        "═"*50,
        "",
        f"📝 Полное имя: {full_name}",
        f"👤 Имя: {first_name}",
        f"📋 Фамилия: {last_name}",
        "",
        f"🤖 Пол: {predict_gender_by_name(first_name)}",
        "",
        "═"*50,
        "",
        "🔍 ПОИСК В СОЦСЕТЯХ:",
        "",
        f"📱 VK: https://vk.com/search?c[section]=people&c[q]={quote(full_name)}",
        f"📘 Facebook: https://www.facebook.com/search/people/?q={quote(full_name)}",
        f"💼 LinkedIn: https://www.linkedin.com/search/results/people/?keywords={quote(full_name)}",
        f"🟠 OK.ru: https://ok.ru/search?st.query={quote(full_name)}&st.mode=Users",
        "",
        "═"*50,
        "",
        "🔎 GOOGLE DORKS:",
        ""
    ]
    
    dorks = generate_google_dorks(full_name, "full_name")
    for dork in dorks:
        result.append(f"  • {dork}")
    
    result.extend([
        "",
        "═"*50,
        "",
        "📧 ВОЗМОЖНЫЕ EMAIL:",
        f"  • {first_name.lower()}.{last_name.lower()}@gmail.com",
        f"  • {first_name.lower()}{last_name.lower()}@mail.ru",
        "",
        "💡 Проверьте Gravatar для каждого email"
    ])
    
    return "\n".join(result)

def analyze_email(email: str) -> str:
    if not is_email(email):
        return "❌ Неверный формат email"
    
    local, domain = email.split("@")
    
    result = [
        f"📧 АНАЛИЗ EMAIL",
        "═"*50,
        "",
        f"📮 Email: {email}",
        f"📝 Локальная часть: {local}",
        f"🌐 Домен: {domain}",
        ""
    ]
    
    gravatar = get_gravatar_info(email)
    if gravatar["exists"]:
        result.extend([
            "✅ GRAVATAR НАЙДЕН:",
            f"  🖼 Аватар: {gravatar['avatar_url']}",
            f"  👤 Профиль: {gravatar['profile_url']}",
            "",
            "═"*50,
            ""
        ])
    
    result.extend([
        "🔍 ПРОВЕРКА НА УТЕЧКИ:",
        ""
    ])
    
    breaches = check_breach_databases(email)
    for breach in breaches:
        result.append(f"  • {breach['service']}: {breach['url']}")
    
    result.extend([
        "",
        "═"*50,
        "",
        "🔎 GOOGLE DORKS:",
        ""
    ])
    
    dorks = generate_google_dorks(email, "email")
    for dork in dorks:
        result.append(f"  • {dork}")
    
    return "\n".join(result)

def analyze_phone_number(phone: str) -> str:
    try:
        try:
            pn = phonenumbers.parse(phone, None)
        except:
            clean = re.sub(r'[^\d]', '', phone)
            if clean.startswith('8') and len(clean) == 11:
                clean = '7' + clean[1:]
            pn = phonenumbers.parse(f"+{clean}", None)
        
        if not phonenumbers.is_valid_number(pn):
            return "❌ Неверный формат\n💡 Пример: +79123456789"
        
        e164 = phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)
        country = geocoder.description_for_number(pn, "ru") or "N/A"
        operator = carrier.name_for_number(pn, "ru") or "N/A"
        clean_phone = re.sub(r'[^\d]', '', e164)
        
        result = [
            f"📱 АНАЛИЗ ТЕЛЕФОНА",
            "═"*50,
            "",
            f"📞 Номер: {phone}",
            f"✅ Валидный",
            f"🌍 Страна: {country}",
            f"📡 Оператор: {operator}",
            "",
            "═"*50,
            "",
            "🔗 МЕССЕНДЖЕРЫ:",
            f"  📱 Telegram: https://t.me/+{clean_phone}",
            f"  💬 WhatsApp: https://wa.me/{clean_phone}",
            f"  📞 Viber: viber://chat?number={clean_phone}",
            "",
            "═"*50,
            "",
            "🔍 ПОИСК VK:",
            f"  • https://vk.com/search?c[section]=people&c[q]={quote(phone)}",
            "",
            "🌐 OSINT СЕРВИСЫ:",
            "  • GetContact - определение имени",
            "  • Truecaller - база номеров",
            "  • Eyecon - определитель"
        ]
        
        return "\n".join(result)
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

async def analyze_telegram_id(tg_id: str) -> str:
    try:
        telegram_id = int(tg_id)
        
        result = [
            f"🆔 АНАЛИЗ TELEGRAM ID",
            "═"*50,
            "",
            f"📱 ID: {telegram_id}",
            ""
        ]
        
        patterns = analyze_telegram_id_pattern(telegram_id)
        result.extend([
            "📊 АНАЛИЗ:",
            f"  🤖 Тип: {'Бот' if patterns['is_bot'] else 'Пользователь'}",
            f"  📅 Регистрация: {patterns['estimated_registration']}",
            f"  ⏳ Возраст: {patterns['account_age']}",
            "",
            "═"*50,
            ""
        ])
        
        try:
            chat = await bot_instance.get_chat(telegram_id)
            
            result.append("✅ ИНФОРМАЦИЯ ДОСТУПНА:")
            
            if chat.first_name:
                result.append(f"  👤 Имя: {chat.first_name}")
            
            if chat.last_name:
                result.append(f"  📝 Фамилия: {chat.last_name}")
            
            if chat.username:
                result.append(f"  @️ Username: @{chat.username}")
                result.append(f"  🔗 https://t.me/{chat.username}")
        except:
            result.extend([
                "❌ ИНФОРМАЦИЯ НЕДОСТУПНА",
                "",
                "Причины:",
                "  • Пользователь скрыл профиль",
                "  • ID не существует"
            ])
        
        result.extend([
            "",
            "═"*50,
            "",
            "🔗 ССЫЛКИ:",
            f"  • tg://user?id={telegram_id}",
            "",
            "🔧 БОТЫ ДЛЯ ПРОВЕРКИ:",
            "  • @userinfobot",
            "  • @getidsbot"
        ])
        
        return "\n".join(result)
    except:
        return "❌ Неверный формат ID"

def analyze_ip_address(ip: str) -> str:
    try:
        r = requests.get(f"https://ipwho.is/{ip}", timeout=10)
        data = r.json()
        
        if not data.get('success', True):
            return f"❌ Ошибка: {data.get('message', 'N/A')}"
        
        result = [
            f"🛰 АНАЛИЗ IP",
            "═"*50,
            "",
            f"🌐 IP: {ip}",
            "",
            "🌍 ГЕОГРАФИЯ:",
            f"  • Страна: {data.get('country', 'N/A')}",
            f"  • Регион: {data.get('region', 'N/A')}",
            f"  • Город: {data.get('city', 'N/A')}",
            "",
            "📍 КООРДИНАТЫ:",
            f"  • Широта: {data.get('latitude', 'N/A')}",
            f"  • Долгота: {data.get('longitude', 'N/A')}",
        ]
        
        if data.get('latitude') and data.get('longitude'):
            lat, lon = data.get('latitude'), data.get('longitude')
            result.append(f"  • Карта: https://maps.google.com/?q={lat},{lon}")
        
        if data.get('connection'):
            conn = data['connection']
            result.extend([
                "",
                "🌐 ПРОВАЙДЕР:",
                f"  • ISP: {conn.get('isp', 'N/A')}",
                f"  • ASN: {conn.get('asn', 'N/A')}"
            ])
        
        result.extend([
            "",
            "═"*50,
            "",
            "🔧 ИНСТРУМЕНТЫ:",
            f"  • Shodan: https://shodan.io/host/{ip}",
            f"  • VirusTotal: https://virustotal.com/gui/ip-address/{ip}"
        ])
        
        return "\n".join(result)
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

def analyze_domain(domain: str) -> str:
    result = [
        f"🌐 АНАЛИЗ ДОМЕНА",
        "═"*50,
        "",
        f"📋 Домен: {domain}",
        ""
    ]
    
    wayback = check_wayback_machine(domain)
    if wayback.get('exists'):
        result.extend([
            "📚 WAYBACK MACHINE:",
            f"  • Архив: {wayback['url']}",
            "",
            "═"*50,
            ""
        ])
    
    result.extend([
        "🔧 WHOIS:",
        f"  • who.is: https://who.is/whois/{domain}",
        f"  • whois.com: https://www.whois.com/whois/{domain}",
        "",
        "🔎 ПРОВЕРКИ:",
        f"  • DNS: https://mxtoolbox.com/SuperTool.aspx?action=a:{domain}",
        f"  • SSL: https://crt.sh/?q={domain}",
        f"  • История: https://web.archive.org/web/*/{domain}"
    ])
    
    return "\n".join(result)

# =========================
# ИНСТРУМЕНТЫ
# =========================
async def tool_username_generator(message: Message, username: str = None):
    if not username:
        await message.answer("🎲 ГЕНЕРАТОР USERNAME\n\nИспользуйте: /tool_username <username>")
        return
    
    variants = generate_username_variants(username)
    
    text = f"🎲 ВАРИАНТЫ USERNAME\n\nБазовый: {username}\n\n🔤 ВАРИАНТЫ:\n\n"
    for i, variant in enumerate(variants, 1):
        text += f"{i}. {variant}\n"
    
    await message.answer(text)

async def tool_phone_converter(message: Message, phone: str = None):
    if not phone:
        await message.answer("📞 КОНВЕРТЕР\n\nИспользуйте: /tool_phone +79123456789")
        return
    
    try:
        pn = phonenumbers.parse(phone, None)
        e164 = phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)
        national = phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.NATIONAL)
        clean = re.sub(r'[^\d]', '', e164)
        
        text = f"""📞 ФОРМАТЫ

Исходный: {phone}

• E.164: {e164}
• Национальный: {national}

🔗 МЕССЕНДЖЕРЫ:
• Telegram: https://t.me/+{clean}
• WhatsApp: https://wa.me/{clean}"""
        
        await message.answer(text)
    except:
        await message.answer("❌ Неверный формат")

async def tool_dorks_generator(message: Message, query: str = None):
    if not query:
        await message.answer("🔐 ГЕНЕРАТОР DORKS\n\nИспользуйте: /tool_dorks user@mail.com")
        return
    
    if is_email(query):
        query_type = "email"
    elif is_phone(query):
        query_type = "phone"
    else:
        query_type = "username"
    
    dorks = generate_google_dorks(query, query_type)
    
    text = f"🔐 GOOGLE DORKS\n\nЗапрос: {query}\n\n🔎 DORKS:\n\n"
    for i, dork in enumerate(dorks, 1):
        text += f"{i}. {dork}\n\n"
    
    await message.answer(text)

async def tool_gravatar_checker(message: Message, email: str = None):
    if not email:
        await message.answer("📧 ПРОВЕРКА GRAVATAR\n\nИспользуйте: /tool_gravatar user@mail.com")
        return
    
    if not is_email(email):
        await message.answer("❌ Неверный формат")
        return
    
    gravatar = get_gravatar_info(email)
    
    if gravatar.get('exists'):
        text = f"✅ GRAVATAR НАЙДЕН!\n\n📧 {email}\n\n🖼 {gravatar['avatar_url']}\n👤 {gravatar['profile_url']}"
    else:
        text = f"❌ НЕ НАЙДЕН\n\n📧 {email}"
    
    await message.answer(text)

# =========================
# ЭКСПОРТ
# =========================
def export_to_txt(query: str, result: str) -> BytesIO:
    content = f"""OSINT БОТ - МАКСИМАЛЬНЫЙ ПОИСК
{'='*60}

Запрос: {query}
Дата: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}

{'='*60}

{result}

{'='*60}
OSINT Bot - Maximum Edition
"""
    
    buffer = BytesIO()
    buffer.write(content.encode('utf-8'))
    buffer.seek(0)
    return buffer

# =========================
# КОМАНДЫ
# =========================
async def cmd_start(message: Message):
    user_id = message.from_user.id
    is_premium, total_searches, _ = get_user_status(user_id)
    
    text = f"""🔥 OSINT БОТ - МАКСИМАЛЬНАЯ ВЕРСИЯ

╔════════════════════════╗
║  ПРОФЕССИОНАЛЬНЫЙ OSINT  ║
╚════════════════════════╝

{'💎 ПРЕМИУМ-АККАУНТ ✅' if is_premium else '🆓 БЕСПЛАТНЫЙ АККАУНТ'}

📊 Статистика:
├ 🔍 Поисков выполнено: {total_searches}
{'├ ♾️ Безлимитный доступ' if is_premium else '└ ⚠️ 1 бесплатный поиск'}

╔════════════════════════╗
║     ВОЗМОЖНОСТИ          ║
╚════════════════════════╝

🌐 45+ социальных сетей
🤖 ML анализ (пол, возраст)
🔍 Web Scraping (GitHub, VK)
📚 Wayback Machine
📊 Google Dorks генератор
💾 Кэширование результатов
📥 Экспорт в TXT
⭐ Избранное + История

⚡ Скорость: 15-30 сек
🎯 Точность: Максимальная

Используйте /menu для начала!"""
    
    await message.answer(text, reply_markup=get_main_keyboard(is_premium, user_id))

async def cmd_menu(message: Message):
    user_id = message.from_user.id
    is_premium, total_searches, _ = get_user_status(user_id)
    
    text = f"""📋 ГЛАВНОЕ МЕНЮ

╔════════════════════════╗
{'║  💎 ПРЕМИУМ-АККАУНТ     ║' if is_premium else '║  🆓 БЕСПЛАТНЫЙ АККАУНТ   ║'}
╚════════════════════════╝

📊 Поисков выполнено: {total_searches}

Выберите действие:"""
    
    await message.answer(text, reply_markup=get_main_keyboard(is_premium, user_id))

async def cmd_my(message: Message):
    user_id = message.from_user.id
    is_premium, total_searches, premium_until = get_user_status(user_id)
    
    text = f"""👤 ЛИЧНЫЙ КАБИНЕТ

╔════════════════════════╗
║     МОЙ ПРОФИЛЬ          ║
╚════════════════════════╝

📋 Статус: {'💎 Премиум ✅' if is_premium else '🆓 Бесплатный'}
🔍 Бесплатный: {'✅ Доступен' if total_searches == 0 else '❌ Использован'}
📊 Всего поисков: {total_searches}"""
    
    if is_premium and premium_until:
        try:
            until = datetime.fromisoformat(premium_until).date()
            days = (until - date.today()).days
            text += f"\n\n📅 Премиум до: {until.strftime('%d.%m.%Y')}\n⏰ Осталось дней: {days}"
        except:
            pass
    
    await message.answer(text, reply_markup=get_main_keyboard(is_premium, user_id))

async def cmd_activate(message: Message, command: CommandObject):
    code = (command.args or "").strip().upper()
    if not code:
        await message.answer("💡 Использование:\n/activate КОД")
        return
    
    result = activate_code(message.from_user.id, code)
    is_premium, _, _ = get_user_status(message.from_user.id)
    
    await message.answer(result, reply_markup=get_main_keyboard(is_premium, message.from_user.id))

async def cmd_code(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет доступа")
        return
    
    args = (command.args or "").strip().split()
    if len(args) != 2 or args[0] != "generate":
        await message.answer("💻 Использование:\n/code generate <число>")
        return
    
    try:
        count = max(1, min(int(args[1]), 500))
    except:
        await message.answer("❌ Число от 1 до 500")
        return
    
    codes = generate_and_store_codes(count)
    
    # ИСПРАВЛЕНИЕ: убираем markdown форматирование
    text = f"✅ Сгенерировано {count} кодов:\n\n"
    
    if len(codes) > 10:
        # Отправляем по частям БЕЗ markdown
        for i in range(0, len(codes), 10):
            chunk_codes = codes[i:i+10]
            chunk_text = "\n".join(chunk_codes)
            await message.answer(f"Коды {i+1}-{i+len(chunk_codes)}:\n\n{chunk_text}")
    else:
        # Все коды сразу
        all_codes = "\n".join(codes)
        await message.answer(text + all_codes)

async def cmd_addtime(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет доступа")
        return
    
    args = (command.args or "").strip().split()
    if len(args) != 2:
        await message.answer("💻 Использование:\n/addtime <user_id> <дней>")
        return
    
    try:
        uid, days = int(args[0]), max(1, min(int(args[1]), 365))
    except:
        await message.answer("❌ Неверные параметры")
        return
    
    update_user_usage(uid, add_premium_days=days)
    await message.answer(f"✅ Пользователю {uid} добавлено {days} дней премиума")

async def cmd_osint(message: Message, command: CommandObject):
    user_id = message.from_user.id
    is_premium, total_searches, _ = get_user_status(user_id)
    
    if not is_premium and total_searches >= 1:
        await message.answer(
            "⚠️ Бесплатный поиск использован!\n\n💎 Активируйте премиум для продолжения",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 Узнать про премиум", callback_data="activate")]
            ])
        )
        return
    
    query = (command.args or "").strip()
    if not query:
        await message.answer(
            "📝 ИСПОЛЬЗОВАНИЕ:\n\n"
            "/osint <запрос>\n\n"
            "📋 Примеры:\n"
            "• /osint john@gmail.com\n"
            "• /osint username123\n"
            "• /osint Иван Иванов\n"
            "• /osint +79123456789\n"
            "• /osint 123456789\n"
            "• /osint 8.8.8.8\n"
            "• /osint example.com"
        )
        return
    
    update_user_usage(user_id, search_inc=1)
    
    # Определяем тип
    if is_full_name(query):
        query_type = "full_name"
    elif is_telegram_id(query):
        query_type = "telegram_id"
    elif is_email(query):
        query_type = "email"
    elif is_ip(query):
        query_type = "ip"
    elif is_domain(query):
        query_type = "domain"
    elif is_phone(query):
        query_type = "phone"
    else:
        query_type = "username"
    
    add_to_history(user_id, query, query_type)
    
    # ИСПРАВЛЕНИЕ: убираем parse_mode из processing message
    processing = await message.answer(
        f"🔍 УГЛУБЛЁННЫЙ ПОИСК...\n\n"
        f"📋 Запрос: {query}\n"
        f"🎯 Тип: {query_type}\n\n"
        f"⏳ Это займёт 15-30 сек\n\n"
        f"🌐 Web Scraping активен\n"
        f"🤖 ML анализ включён\n"
        f"📊 Проверка 45+ платформ"
    )
    
    try:       
    	conn = sqlite3.connect(DB_PATH)
    	cur = conn.cursor()
    # Ищем точное совпадение
    	cur.execute("SELECT data FROM local_data WHERE query = ? AND query_type = ?", (query.lower(), query_type))
    	local_row = cur.fetchone()
    	conn.close()

    	if local_row:
        	result = local_row[0] + "\n\n💾 РЕЗУЛЬТАТ ИЗ ЛОКАЛЬНОЙ БАЗЫ"
        # Отправляем сразу, минуя долгий поиск
        	try: await processing.delete() 
        	except: pass
        	await message.answer(result, reply_markup=get_result_keyboard(user_id, query, query_type))
    except Exception as e:
        logger.error(f"Local DB search error: {e}")
        # Выполняем поиск
        if query_type == "full_name":
            result = await analyze_full_name(query)
        elif query_type == "username":
   	 	    result = await analyze_username_with_selenium(query) 
        elif query_type == "telegram_id":
            result = await analyze_telegram_id(query)
        elif query_type == "email":
            result = analyze_email(query)
        elif query_type == "ip":
            result = analyze_ip_address(query)
        elif query_type == "domain":
            result = analyze_domain(query)
        elif query_type == "phone":
            result = analyze_phone_number(query)
        else:
            result = await analyze_username(query)
        
        try:
            await processing.delete()
        except:
            pass
        
        is_premium_now, total_now, _ = get_user_status(user_id)
        if not is_premium_now and total_now >= 1:
            result += "\n\n" + "="*50 + "\n\n⚠️ Бесплатный поиск использован!\n💎 Активируйте премиум"
        
        # Отправляем результат
        if len(result) > 4000:
            parts = [result[i:i+4000] for i in range(0, len(result), 4000)]
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    await message.answer(part, reply_markup=get_result_keyboard(user_id, query, query_type))
                else:
                    await message.answer(part)
        else:
            await message.answer(result, reply_markup=get_result_keyboard(user_id, query, query_type))
            
    except Exception as e:
        logger.error(f"Error in cmd_osint: {e}")
        await message.answer(f"❌ Ошибка выполнения: {str(e)}")

async def cmd_tool_username(message: Message, command: CommandObject):
    await tool_username_generator(message, (command.args or "").strip())

async def cmd_tool_phone(message: Message, command: CommandObject):
    await tool_phone_converter(message, (command.args or "").strip())

async def cmd_tool_dorks(message: Message, command: CommandObject):
    await tool_dorks_generator(message, (command.args or "").strip())

async def cmd_tool_gravatar(message: Message, command: CommandObject):
    await tool_gravatar_checker(message, (command.args or "").strip())
    
async def cmd_export_db(message: Message):
    # Проверка прав администратора
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет доступа")
        return

    status_msg = await message.answer("⏳ Формирование выгрузки базы данных...")

    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        text_output = []
        text_output.append(f"📅 ДАТА ЭКСПОРТА: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        text_output.append(f"👤 ЗАПРОС ОТ: {message.from_user.id}")
        text_output.append("=" * 60)

        # Получаем список всех таблиц
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cur.fetchall()

        for table in tables:
            table_name = table[0]
            # Пропускаем системные таблицы sqlite, если они попадутся
            if table_name.startswith('sqlite_'):
                continue
                
            text_output.append(f"\n\n📂 ТАБЛИЦА: {table_name.upper()}")
            text_output.append("-" * 60)
            
            # Получаем названия колонок
            cur.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in cur.fetchall()]
            text_output.append(" | ".join(columns))
            text_output.append("-" * 30)
            
            # Получаем данные
            cur.execute(f"SELECT * FROM {table_name}")
            rows = cur.fetchall()
            
            if not rows:
                text_output.append("(пусто)")
            
            for row in rows:
                # Преобразуем данные в строку, убираем переносы строк для чистоты txt
                clean_row = [str(val).replace('\n', ' ').replace('\r', '') for val in row]
                text_output.append(" | ".join(clean_row))
            
            text_output.append(f"\n📊 Всего записей: {len(rows)}")

        conn.close()

        # Создаем файл в памяти
        final_text = "\n".join(text_output)
        file_bytes = BytesIO(final_text.encode('utf-8'))
        
        filename = f"db_dump_{datetime.now().strftime('%d%m%Y_%H%M')}.txt"
        document = BufferedInputFile(file_bytes.read(), filename=filename)

        await message.answer_document(document, caption="✅ **Полный дамп базы данных**")
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Export DB error: {e}")
        await status_msg.edit_text(f"❌ Ошибка при экспорте: {e}")
        
async def cmd_add_db(message: Message, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет доступа")
        return

    if not message.document or not (message.document.file_name.endswith('.json') or message.document.file_name.endswith('.txt')):
        await message.answer("❌ Отправьте файл .json или .txt")
        return

    status_msg = await message.answer("⏳ Анализ файла...")

    try:
        file_id = message.document.file_id
        file = await bot.get_file(file_id)
        file_io = await bot.download_file(file.file_path)
        content = file_io.read().decode('utf-8', errors='ignore')
        
        data = []
        
        # 1. Пробуем JSON
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                data = parsed
        except: pass

        # 2. Если не JSON, читаем построчно
        if not data:
            lines = content.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line or line.startswith("==="): continue # пропускаем заголовки
                
                # --- СПЕЦИАЛЬНЫЙ ФОРМАТ ИЗ СКРИНШОТА ---
                # ID: 123456 | @Username | Баланс: 0
                if line.startswith("ID:") and "|" in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 2:
                        user_id = parts[0].replace("ID:", "").strip()
                        username = parts[1]
                        extra_info = " | ".join(parts[2:]) if len(parts) > 2 else ""
                        
                        # Сохраняем в универсальном формате
                        data.append({
                            "telegram_id": user_id,
                            "username": username,
                            "info": extra_info,
                            "raw_source": line
                        })
                        continue
                # ---------------------------------------

                # Пробуем JSON line
                try:
                    if line.endswith(','): line = line[:-1]
                    data.append(json.loads(line))
                    continue
                except: pass
                
                # Пробуем стандартный log:pass
                added_txt = False
                for delimiter in [':', ';', '|']:
                    if delimiter in line:
                        parts = line.split(delimiter, 1)
                        if len(parts) == 2:
                            p1, p2 = parts[0].strip(), parts[1].strip()
                            if len(p1) < 3: continue
                            
                            k = "username"
                            if "@" in p1: k = "email"
                            elif p1.isdigit(): k = "phone"
                            
                            data.append({k: p1, "data": p2, "raw_source": line})
                            added_txt = True
                            break
                
                if not added_txt and len(line) > 3:
                    data.append({"username": line, "raw_data": "Text import"})

        if not data:
            await status_msg.edit_text("❌ Формат не распознан.")
            return

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        count = 0
        
        await status_msg.edit_text(f"📥 Импорт {len(data)} строк...")

        for item in data:
            # Красивый вывод
            res_lines = []
            if "telegram_id" in item: res_lines.append(f"🆔 ID: {item['telegram_id']}")
            if "username" in item: res_lines.append(f"👤 User: {item['username']}")
            if "info" in item: res_lines.append(f"💰 Info: {item['info']}")
            
            # Добавляем остальные поля, если есть
            for k,v in item.items():
                if k not in ["telegram_id", "username", "info", "raw_source"]:
                    res_lines.append(f"{k}: {v}")
            
            # Если совсем пусто, берем сырую строку
            if not res_lines: res_lines.append(item.get("raw_source", ""))
            
            result_text = "📂 ЛОКАЛЬНАЯ БАЗА:\n" + "\n".join(res_lines)

            # ИНДЕКСАЦИЯ (чтобы искалось и по ID, и по нику)
            keys = []
            
            # 1. Добавляем ID
            if item.get("telegram_id"):
                keys.append((str(item["telegram_id"]), "telegram_id"))
            
            # 2. Добавляем Username (без @ и с @)
            if item.get("username") and item["username"] != "@Unknown":
                u = item["username"]
                keys.append((u.lower(), "username"))
                if u.startswith("@"):
                    keys.append((u[1:].lower(), "username"))

            # 3. Остальные стандартные поля
            possible = ['email', 'phone', 'mobile', 'ip']
            for k, v in item.items():
                if k in possible and v:
                    keys.append((str(v), k if k!='mobile' else 'phone'))

            for q_val, q_type in keys:
                try:
                    cur.execute(
                        "INSERT OR REPLACE INTO local_data (query, query_type, data) VALUES (?, ?, ?)",
                        (q_val, q_type, result_text)
                    )
                    count += 1
                except: pass

        conn.commit()
        conn.close()
        
        await status_msg.edit_text(f"✅ **Готово!**\n📥 Записей: {len(data)}\n🔑 Индексов: {count}")

    except Exception as e:
        logger.error(f"Add DB error: {e}")
        await status_msg.edit_text(f"❌ Ошибка: {e}")
# =========================
# CALLBACKS
# =========================
async def callback_start_search(callback: CallbackQuery):
    text = """🔍 ВЫБЕРИТЕ ТИП ПОИСКА

╔════════════════════════╗
║    ТИПЫ OSINT-ПОИСКА     ║
╚════════════════════════╝

Выберите категорию:"""
    
    try:
        await callback.message.edit_text(text, reply_markup=get_search_type_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_show_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    history = get_user_history(user_id, limit=10)
    
    if not history:
        text = "📜 ИСТОРИЯ ПОИСКОВ\n\n❌ История пуста"
    else:
        text = "📜 ИСТОРИЯ ПОИСКОВ\n\n╔════════════════════════╗\n\n"
        
        for query, qtype, timestamp in history:
            try:
                dt = datetime.fromisoformat(timestamp)
                time_str = dt.strftime('%d.%m %H:%M')
            except:
                time_str = "N/A"
            
            type_emoji = {
                "email": "📧", "username": "👤", "phone": "📱", "full_name": "👥",
                "telegram_id": "🆔", "ip": "🛰", "domain": "🌐"
            }.get(qtype, "🔍")
            
            text += f"{type_emoji} {query}\n⏰ {time_str}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Очистить историю", callback_data="clear_history")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_clear_history(callback: CallbackQuery):
    clear_user_history(callback.from_user.id)
    await callback.answer("✅ История очищена!", show_alert=True)
    await callback_show_history(callback)

async def callback_show_favorites(callback: CallbackQuery):
    user_id = callback.from_user.id
    favorites = get_favorites(user_id)
    
    if not favorites:
        text = "⭐ ИЗБРАННОЕ\n\n❌ Пусто"
    else:
        text = "⭐ ИЗБРАННОЕ\n\n╔════════════════════════╗\n\n"
        
        for fav_id, query, qtype, note, added_at in favorites[:10]:
            type_emoji = {
                "email": "📧", "username": "👤", "phone": "📱", "full_name": "👥",
                "telegram_id": "🆔", "ip": "🛰", "domain": "🌐"
            }.get(qtype, "🔍")
            
            text += f"{type_emoji} {query}\n"
            if note:
                text += f"📝 {note}\n"
            text += "\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_tools_menu(callback: CallbackQuery):
    text = """🛠 OSINT ИНСТРУМЕНТЫ

╔════════════════════════╗
║    ПОЛЕЗНЫЕ УТИЛИТЫ      ║
╚════════════════════════╝

Выберите инструмент:"""
    
    try:
        await callback.message.edit_text(text, reply_markup=get_tools_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_search_type(callback: CallbackQuery):
    search_types = {
        "search_email": "📧 ПОИСК ПО EMAIL\n\nИспользуйте:\n/osint user@example.com",
        "search_username": "👤 ПОИСК ПО USERNAME\n\nИспользуйте:\n/osint username123",
        "search_full_name": "👥 ПОИСК ПО ИМЕНИ\n\nИспользуйте:\n/osint Иван Иванов",
        "search_phone": "📱 ПОИСК ПО ТЕЛЕФОНУ\n\nИспользуйте:\n/osint +79123456789",
        "search_telegram_id": "🆔 ПОИСК ПО TELEGRAM ID\n\nИспользуйте:\n/osint 123456789",
        "search_ip": "🛰 ПОИСК ПО IP\n\nИспользуйте:\n/osint 8.8.8.8",
        "search_domain": "🌐 ПОИСК ПО ДОМЕНУ\n\nИспользуйте:\n/osint example.com"
    }
    
    text = search_types.get(callback.data, "❓ Неизвестный тип")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к выбору", callback_data="start_search")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_my_status(callback: CallbackQuery):
    user_id = callback.from_user.id
    is_premium, total_searches, premium_until = get_user_status(user_id)
    
    text = f"""👤 МОЯ СТАТИСТИКА

╔════════════════════════╗
║     МОЙ ПРОФИЛЬ          ║
╚════════════════════════╝

📋 Статус: {'💎 Премиум ✅' if is_premium else '🆓 Бесплатный'}
🔍 Бесплатный: {'✅ Доступен' if total_searches == 0 else '❌ Использован'}
📊 Всего поисков: {total_searches}"""
    
    if is_premium and premium_until:
        try:
            until = datetime.fromisoformat(premium_until).date()
            days = (until - date.today()).days
            text += f"\n\n📅 Премиум до: {until.strftime('%d.%m.%Y')}\n⏰ Осталось: {days}д"
        except:
            pass
    
    try:
        await callback.message.edit_text(text, reply_markup=get_main_keyboard(is_premium, user_id))
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_help(callback: CallbackQuery):
    text = """📚 СПРАВКА И ИНСТРУКЦИЯ

╔════════════════════════╗
║        КОМАНДЫ           ║
╚════════════════════════╝

🔍 ОСНОВНЫЕ:
├ /menu - главное меню
├ /osint <запрос> - поиск
├ /my - мой профиль
└ /activate <код> - премиум

╔════════════════════════╗
║      ТИПЫ ПОИСКА         ║
╚════════════════════════╝

📧 Email - утечки, Gravatar
👤 Username - 45+ соцсетей
👥 Имя Фамилия - соцсети
📱 Телефон - мессенджеры
🆔 Telegram ID - инфо
🛰 IP - геолокация
🌐 Домен - WHOIS

╔════════════════════════╗
║       ФИЧИ БОТА          ║
╚════════════════════════╝

🌐 Web Scraping (GitHub, VK)
🤖 ML анализ (пол, возраст)
💾 Кэширование (48ч)
📥 Экспорт в TXT
⭐ Избранное
📜 История (50 записей)
🔐 Google Dorks

💎 ПРЕМИУМ: 30 дней безлимита"""
    
    user_id = callback.from_user.id
    is_premium, _, _ = get_user_status(user_id)
    
    try:
        await callback.message.edit_text(text, reply_markup=get_main_keyboard(is_premium, user_id))
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_activate(callback: CallbackQuery):
    text = """💎 ПРЕМИУМ-ПОДПИСКА

╔════════════════════════╗
║    ЧТО ВХОДИТ В ПРЕМИУМ  ║
╚════════════════════════╝

♾️ Безлимитные OSINT-поиски
📅 Срок действия: 30 дней
⚡ Приоритетная обработка
🎁 Все функции бота
🔒 Техническая поддержка

╔════════════════════════╗
║     КАК АКТИВИРОВАТЬ     ║
╚════════════════════════╝

1️⃣ Получите код у администратора
2️⃣ Используйте команду:

/activate ВАШ_КОД

Пример:
/activate ABC123DEF456

╔════════════════════════╗
║    ПОЛУЧИТЬ КОД          ║
╚════════════════════════╝

📩 Свяжитесь с администратором
для получения кода активации"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_to_main")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_back_to_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    is_premium, total_searches, _ = get_user_status(user_id)
    
    text = f"""📋 ГЛАВНОЕ МЕНЮ

╔════════════════════════╗
{'║  💎 ПРЕМИУМ-АККАУНТ     ║' if is_premium else '║  🆓 БЕСПЛАТНЫЙ АККАУНТ   ║'}
╚════════════════════════╝

📊 Поисков выполнено: {total_searches}

Выберите действие:"""
    
    try:
        await callback.message.edit_text(text, reply_markup=get_main_keyboard(is_premium, user_id))
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_admin_panel(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    text = """⚙️ ПАНЕЛЬ АДМИНИСТРАТОРА

╔════════════════════════╗
║     УПРАВЛЕНИЕ БОТОМ     ║
╚════════════════════════╝

Выберите действие:"""
    
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    stats = get_bot_stats()
    
    text = f"""📊 СТАТИСТИКА БОТА

╔════════════════════════╗
║     ОБЩАЯ СТАТИСТИКА     ║
╚════════════════════════╝

👥 Всего пользователей: {stats['total_users']}
💎 Премиум-пользователей: {stats['premium_users']}
🔍 Всего поисков: {stats['total_searches']}
📊 Поисков сегодня: {stats['searches_today']}
🔑 Свободных кодов: {stats['unused_codes']}"""
    
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_admin_generate(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    text = """🔑 ГЕНЕРАЦИЯ КОДОВ

Команда:
/code generate <количество>

Пример:
/code generate 20

Лимиты: от 1 до 500 кодов"""
    
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_admin_addtime(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    text = """➕ ВЫДАЧА ПРЕМИУМ-ДОСТУПА

Команда:
/addtime <user_id> <дней>

Пример:
/addtime 123456789 30

Лимиты: от 1 до 365 дней"""
    
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_tool_username_gen(callback: CallbackQuery):
    text = """🎲 ГЕНЕРАТОР USERNAME

Команда:
/tool_username <базовый_username>

Пример:
/tool_username john_doe

Получите 20+ вариантов username"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к инструментам", callback_data="tools_menu")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_tool_phone_conv(callback: CallbackQuery):
    text = """📞 КОНВЕРТЕР ТЕЛЕФОНОВ

Команда:
/tool_phone <номер>

Пример:
/tool_phone +79123456789

Получите все форматы номера
и ссылки для мессенджеров"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к инструментам", callback_data="tools_menu")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_tool_dorks_gen(callback: CallbackQuery):
    text = """🔐 ГЕНЕРАТОР GOOGLE DORKS

Команда:
/tool_dorks <запрос>

Примеры:
/tool_dorks user@example.com
/tool_dorks username123
/tool_dorks +79123456789

Получите готовые Google Dorks"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к инструментам", callback_data="tools_menu")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_tool_gravatar(callback: CallbackQuery):
    text = """📧 ПРОВЕРКА GRAVATAR

Команда:
/tool_gravatar <email>

Пример:
/tool_gravatar user@example.com

Проверка наличия аватара
в системе Gravatar"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к инструментам", callback_data="tools_menu")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass
    await callback.answer()

async def callback_export(callback: CallbackQuery):
    try:
        _, query_type, query = callback.data.split("_", 2)
        
        result = get_cached_result(query, query_type)
        
        if not result:
            await callback.answer("❌ Результат не найден в кэше", show_alert=True)
            return
        
        file_buffer = export_to_txt(query, result)
        filename = f"osint_{query_type}_{query[:20]}.txt"
        
        await callback.message.answer_document(
            document=BufferedInputFile(file_buffer.read(), filename=filename),
            caption=f"📥 Экспорт результатов для: {query}"
        )
        
        await callback.answer("✅ Файл отправлен!")
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)

async def callback_fav_add(callback: CallbackQuery):
    try:
        parts = callback.data.split("_", 3)
        if len(parts) == 4:
            _, _, query_type, query = parts
            add_to_favorites(callback.from_user.id, query, query_type)
            await callback.answer("⭐ Добавлено в избранное!", show_alert=True)
        else:
            await callback.answer("❌ Ошибка формата", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)

# =========================
# ЗАПУСК
# =========================
async def main():
    global bot_instance
    
    init_db()
    bot_instance = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Команды
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_menu, Command("menu"))
    dp.message.register(cmd_my, Command("my"))
    dp.message.register(cmd_activate, Command("activate"))
    dp.message.register(cmd_code, Command("code"))
    dp.message.register(cmd_addtime, Command("addtime"))
    dp.message.register(cmd_osint, Command("osint"))
    dp.message.register(cmd_tool_username, Command("tool_username"))
    dp.message.register(cmd_tool_phone, Command("tool_phone"))
    dp.message.register(cmd_tool_dorks, Command("tool_dorks"))
    dp.message.register(cmd_tool_gravatar, Command("tool_gravatar"))
    dp.message.register(cmd_export_db, Command("exportdb"))
    dp.message.register(cmd_add_db, Command("addb"))

    
    # Callbacks
    dp.callback_query.register(callback_start_search, F.data == "start_search")
    dp.callback_query.register(callback_show_history, F.data == "show_history")
    dp.callback_query.register(callback_clear_history, F.data == "clear_history")
    dp.callback_query.register(callback_show_favorites, F.data == "show_favorites")
    dp.callback_query.register(callback_tools_menu, F.data == "tools_menu")
    dp.callback_query.register(callback_search_type, F.data.in_([
        "search_email", "search_username", "search_phone", "search_full_name",
        "search_telegram_id", "search_ip", "search_domain"
    ]))
    dp.callback_query.register(callback_my_status, F.data == "my_status")
    dp.callback_query.register(callback_help, F.data == "help")
    dp.callback_query.register(callback_activate, F.data == "activate")
    dp.callback_query.register(callback_back_to_main, F.data == "back_to_main")
    dp.callback_query.register(callback_admin_panel, F.data == "admin_panel")
    dp.callback_query.register(callback_admin_stats, F.data == "admin_stats")
    dp.callback_query.register(callback_admin_generate, F.data == "admin_generate")
    dp.callback_query.register(callback_admin_addtime, F.data == "admin_addtime")
    dp.callback_query.register(callback_tool_username_gen, F.data == "tool_username_gen")
    dp.callback_query.register(callback_tool_phone_conv, F.data == "tool_phone_conv")
    dp.callback_query.register(callback_tool_dorks_gen, F.data == "tool_dorks_gen")
    dp.callback_query.register(callback_tool_gravatar, F.data == "tool_gravatar")
    dp.callback_query.register(callback_export, F.data.startswith("export_"))
    dp.callback_query.register(callback_fav_add, F.data.startswith("fav_add_"))
    
    logger.info("╔════════════════════════════════════╗")
    logger.info("║   OSINT БОТ ЗАПУЩЕН (MAX VERSION)  ║")
    logger.info("╚════════════════════════════════════╝")
    logger.info("✅ Web Scraping активен")
    logger.info("✅ ML анализ включён")
    logger.info("✅ 45+ платформ")
    logger.info("✅ Google Dorks генератор")
    logger.info("✅ Wayback Machine")
    logger.info("✅ Красивый интерфейс")
    
    await dp.start_polling(bot_instance)

if __name__ == "__main__":
    asyncio.run(main())
