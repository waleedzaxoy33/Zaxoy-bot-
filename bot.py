# bot.py — Zaxoy Bot | Part 1/2
# Replace YOUR_BOT_TOKEN with your actual token
# ─────────────────────────────────────────────────────────────
# Imports
# ─────────────────────────────────────────────────────────────
import os 
import io
import json
import threading
import httpx
import textwrap
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageDraw, ImageFont
import logging
import random
import asyncio
import re
from datetime import timedelta, datetime, timezone
from supabase import create_client
# Install ffmpeg at startup
os.system("apt-get update -qq && apt-get install -y ffmpeg -qq > /dev/null 2>&1 || true")
from telegram import ( 
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReactionTypeEmoji,
    ChatPermissions,
    InlineQueryResultArticle,
    InputTextMessageContent
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ChosenInlineResultHandler,
    filters,
    ContextTypes
)
# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
AI_INSTRUCTIONS = []  # Loaded from Supabase on startup
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
sb = create_client(SUPABASE_URL, SUPABASE_KEY)
logging.basicConfig(level=logging.INFO)
# ─────────────────────────────────────────────────────────────
# Supabase Helpers
# ─────────────────────────────────────────────────────────────
def sb_load_owner_facts() -> list:
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/bot_settings?key=like.owner_fact_%&select=key,value",
            headers=sb_headers(), timeout=10
        )
        rows = r.json()
        if not isinstance(rows, list):
            return ["Waleed is from Zaxo, Kurdistan."]
        facts = [row["value"] for row in sorted(rows, key=lambda x: x["key"])]
        return facts if facts else ["Waleed is from Zaxo, Kurdistan."]
    except Exception:
        return ["Waleed is from Zaxo, Kurdistan."]
def sb_save_owner_fact(fact: str):
    try:
        # Get current count
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/bot_settings?key=like.owner_fact_%&select=key",
            headers=sb_headers(), timeout=10
        )
        rows = r.json()
        idx = len(rows) + 1
        requests.post(
            f"{SUPABASE_URL}/rest/v1/bot_settings",
            headers=sb_headers(),
            json={"key": f"owner_fact_{idx}", "value": fact},
            timeout=10
        )
    except Exception as e:
        logging.error(f"sb_save_owner_fact error: {e}")
def sb_delete_owner_fact(fact: str):
    try:
        requests.delete(
            f"{SUPABASE_URL}/rest/v1/bot_settings?value=eq.{requests.utils.quote(fact)}",
            headers=sb_headers(), timeout=10
        )
    except Exception as e:
        logging.error(f"sb_delete_owner_fact error: {e}")
def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
def sb_load_admin_perms() -> dict:
    try:
        res = sb.table("admin_perms").select("*").execute()
        data = res.data
        if not data:
            return {}
        result = {}
        for row in data:
            result[int(row["user_id"])] = set(row["perms"])
        return result
    except Exception as e:
        logging.error(f"sb_load_admin_perms error: {e}")
        return {}
def sb_upsert_admin(user_id: int, perms: set):
    try:
        sb.table("admin_perms").delete().eq("user_id", str(user_id)).execute()
        sb.table("admin_perms").insert({
            "user_id": str(user_id),
            "perms": list(perms)
        }).execute()
    except Exception as e:
        logging.error(f"sb_upsert_admin error: {e}")
def sb_delete_admin(user_id: int):
    try:
        sb.table("admin_perms").delete().eq("user_id", str(user_id)).execute()
    except Exception as e:
        logging.error(f"sb_delete_admin error: {e}")
# ─── hack_blocked Supabase functions ─────────────────────────────────
def sb_load_hack_blocked() -> set:
    try:
        res = sb.table("hack_blocked").select("user_id").execute()
        return {int(row["user_id"]) for row in res.data} if res.data else set()
    except Exception as e:
        logging.error(f"sb_load_hack_blocked error: {e}")
        return set()
def sb_add_hack_blocked(user_id: int):
    try:
        sb.table("hack_blocked").upsert({"user_id": str(user_id)}).execute()
    except Exception as e:
        logging.error(f"sb_add_hack_blocked error: {e}")
def sb_remove_hack_blocked(user_id: int):
    try:
        sb.table("hack_blocked").delete().eq("user_id", str(user_id)).execute()
    except Exception as e:
        logging.error(f"sb_remove_hack_blocked error: {e}")
# ─── delete_store Supabase functions ─────────────────────────────────
def sb_load_delete_store() -> list:
    try:
        res = sb.table("delete_store").select("*").execute()
        return res.data or []
    except Exception as e:
        logging.error(f"sb_load_delete_store error: {e}")
        return []
def sb_add_delete_entry(pattern: str, entry_type: str, label: str, added_by: str):
    try:
        sb.table("delete_store").delete().eq("pattern", pattern).execute()
        sb.table("delete_store").insert({
            "pattern": pattern,
            "added_by": added_by
        }).execute()
    except Exception as e:
        logging.error(f"sb_add_delete_entry error: {e}")
def sb_remove_delete_pattern(pattern: str):
    try:
        sb.table("delete_store").delete().eq("pattern", pattern).execute()
    except Exception as e:
        logging.error(f"sb_remove_delete_pattern error: {e}")
def sb_save_admin_perms(store: dict):
    try:
        # Get existing user_ids in Supabase
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/admin_perms?select=user_id",
            headers=sb_headers(), timeout=10
        )
        existing_ids = {row["user_id"] for row in r.json()}
        store_ids = {str(k) for k in store.keys()}
        # Delete users no longer in store
        for uid in existing_ids - store_ids:
            requests.delete(
                f"{SUPABASE_URL}/rest/v1/admin_perms?user_id=eq.{uid}",
                headers=sb_headers(), timeout=10
            )
        # Upsert each user individually (Prefer: resolution=merge-duplicates)
        for uid, perms in store.items():
            requests.post(
                f"{SUPABASE_URL}/rest/v1/admin_perms",
                headers=sb_headers(),
                json={"user_id": str(uid), "perms": list(perms)},
                timeout=10
            )
    except Exception as e:
        logging.error(f"sb_save_admin_perms error: {e}")
def sb_load_if_store() -> dict:
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/if_store?select=trigger,reply",
            headers=sb_headers(), timeout=10
        )
        return {row["trigger"]: row["reply"] for row in r.json()}
    except Exception:
        return {}
def sb_save_if_store(store: dict):
    try:
        requests.delete(
            f"{SUPABASE_URL}/rest/v1/if_store?trigger=neq.ZAXOY_PLACEHOLDER_NONE",
            headers=sb_headers(), timeout=10
        )
        rows = [{"trigger": k, "reply": v} for k, v in store.items()]
        if rows:
            requests.post(
                f"{SUPABASE_URL}/rest/v1/if_store",
                headers=sb_headers(),
                json=rows, timeout=10
            )
    except Exception as e:
        logging.error(f"sb_save_if_store error: {e}")
# ─────────────────────────────────────────────────────────────
# Mute System Stores & Config
# ─────────────────────────────────────────────────────────────
mute_store = {}
mute_message_map = {}
warn_store = {}
MUTE_MESSAGES = [
    "🔇 {name} has been silenced in Zaxo's domain for {duration}. The city speaks — you don't. 🇲🇨",
    "⛓️ {name} is now muted for {duration}. Zaxo's law has been enforced. 🇲🇨",
    "🚫 {name} — {duration} of silence. Zaxo does not tolerate noise. 🇲🇨",
    "🌑 {name} has entered the shadow zone for {duration}. Not a word. 🇲🇨",
    "⚔️ {name} has been struck silent for {duration} by order of Zaxoy Bot. 🇲🇨",
    "🤫 {name} has been silenced for {duration} by order of Zaxoy! 🇲🇨",
    "🚫 Calm down {name}, take a break from chatting for {duration}! 🇲🇨",
    "⚡ The hammer has fallen! {name} is muted for {duration}! 🇲🇨"
]
# ─────────────────────────────────────────────────────────────
# Permission Store
# Structure:
# { user_id: set(commands) }
#
# "all" = full admin permissions
# ─────────────────────────────────────────────────────────────
ADMIN_PERMS_FILE = "admin_perms.json"
def load_admin_perms() -> dict[int, set]:
    # Try Supabase first, fallback to local file
    data = sb_load_admin_perms()
    if data:
        return data
    try:
        with open(ADMIN_PERMS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return {int(k): set(v) for k, v in d.items()}
    except Exception:
        return {}
def save_admin_perms(store: dict[int, set]):
    sb_save_admin_perms(store)
    try:
        with open(ADMIN_PERMS_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): list(v) for k, v in store.items()}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
admin_perms: dict[int, set] = load_admin_perms()
deadchat_cooldowns = {}  # chat_id: last_used_time

# --- AI session tracking for reply continuation ---
ai_session_messages = set()  # stores message_id of AI responses that can be replied to

async def cleanup_ai_session(message_id: int):
    """Remove message_id from ai_session_messages after 10 minutes."""
    await asyncio.sleep(600)  # 10 minutes
    ai_session_messages.discard(message_id)

def has_perm(user_id: int, cmd: str) -> bool:
    if user_id == OWNER_ID:
        return True
    perms = sb_load_admin_perms().get(user_id, set())
    return "all" in perms or cmd in perms
# ─────────────────────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────────────────────
START_MESSAGES = [
    [
        "🌟 Zaxo is awake and ready!",
        "💫 Commands loading...",
        "🔥 Full power mode ON",
        "⚡ All systems go!",
        "🇲🇨 Zaxoy Bot is here for you!"
    ],
    [
        "🚀 Launching Zaxo systems...",
        "🌙 Night or day, Zaxo never sleeps",
        "🎯 Precision mode activated",
        "🛡️ Zaxo protection enabled",
        "🇲🇨 Let's go, Zaxoy Bot!"
    ],
    [
        "💎 Zaxo — rare, sharp, unstoppable",
        "🌊 Flowing with power",
        "🎶 Tuned to perfection",
        "🦅 Flying above the rest",
        "🇲🇨 Zaxoy Bot online!"
    ],
    [
        "⚔️ Zaxo stands strong",
        " Beauty meets intelligence",
        "🔮 Future is Zaxo",
        "✨ Sparkling with features",
        "🇲🇨 Zaxoy Bot activated!"
    ],
    [
        "🏔️ Tall as Zaxo mountains",
        " Colorful like Zaxo skies",
        "🎯 Always on target",
        "🤝 Here to help you",
        "🇲🇨 Zaxoy Bot, always ready!"
    ],
    [
        "🌍 Zaxo — known worldwide",
        "💡 Smart, fast, reliable",
        "🔑 Unlocking possibilities",
        "🌟 Shining brighter every day",
        "🇲🇨 Zaxoy Bot loaded!"
    ],
]
USER_CACHE_FILE = "user_cache.json"
try:
    with open(USER_CACHE_FILE, "r", encoding="utf-8") as f:
        USER_CACHE = json.load(f)
except Exception:
    USER_CACHE = {}
def save_user_cache():
    try:
        with open(USER_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(USER_CACHE, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
async def cache_user_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return
    user = msg.from_user
    try:
        USER_CACHE[str(user.id)] = {
            "id": user.id,
            "username": (user.username or "").lower(),
            "name": user.full_name
        }
        if user.username:
            USER_CACHE[f"@{user.username.lower()}"] = user.id
        save_user_cache()
    except Exception:
        pass
    # Track message count for /top
    try:
        if msg.chat.type in ("group", "supergroup"):
            chat_id = str(msg.chat_id)
            user_id = str(user.id)
            top_blocked = sb_load_top_blacklist()
            if user.id not in top_blocked:
                sb_increment_top_count(chat_id, user_id, user.full_name)
            title = msg.chat.title or ""
            sb_track_active_group(chat_id, title)
    except Exception as e:
        logging.error(f"top counter error: {e}")
async def resolve_target_from_mention(msg, ctx):
    """Unified target resolver — same logic as /gaytest:
    reply > text_mention entity > @username (cache then get_chat) > numeric ID"""
    # 1. Reply
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, u.full_name
    text = msg.text or msg.caption or ""
    # 2. text_mention entity (user tapped, no username)
    if msg.entities:
        for entity in msg.entities:
            if entity.type == "text_mention" and entity.user:
                return entity.user.id, entity.user.full_name
    # 3. @username — search ALL parts, any order
    parts = text.strip().split()
    for part in parts:
        raw = part.strip()
        if raw.startswith("@") and len(raw) > 1:
            key = raw.lower()
            # Cache lookup
            cached_id = USER_CACHE.get(key)
            if cached_id:
                cached_data = USER_CACHE.get(str(cached_id), {})
                return int(cached_id), cached_data.get("name", raw)
            # Scan full USER_CACHE for matching username
            for uid_str, data in USER_CACHE.items():
                if isinstance(data, dict):
                    if data.get("username", "").lower() == raw[1:].lower():
                        return int(uid_str), data.get("name", raw)
            # Last resort: get_chat
            try:
                chat = await ctx.bot.get_chat(raw)
                return chat.id, chat.full_name or raw
            except Exception:
                pass
    # 4. Numeric ID
    for part in parts[1:]:
        raw = part.strip()
        if raw.lstrip("-").isdigit():
            uid = int(raw)
            cached_data = USER_CACHE.get(str(uid), {})
            return uid, cached_data.get("name", raw)
    return None, None
async def resolve_target_user(msg, ctx, allow_id=False):
    """Same as resolve_target_from_mention but returns (id, name, reply_msg)"""
    uid, name = await resolve_target_from_mention(msg, ctx)
    reply = msg.reply_to_message if (msg.reply_to_message and msg.reply_to_message.from_user) else None
    return uid, name, reply
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msgs = random.choice(START_MESSAGES)
    text = "\n".join(msgs)
    await update.message.reply_text(text)
async def send_botpy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.from_user.id != OWNER_ID or msg.chat.type != "private":
        return
    try:
        with open("bot.py", "rb") as f:
            await ctx.bot.send_document(
                chat_id=msg.chat_id,
                document=f,
                filename="bot.py",
                caption="📁 Zaxoy Bot source code"
            )
    except Exception as e:
        await msg.reply_text(f"⚠️ Failed to send file: {e}")
# ─────────────────────────────────────────────────────────────
# /on & /off
# ─────────────────────────────────────────────────────────────
ON_MSGS = [
    "✅ Zaxoy Bot is ON and fully operational 🇲🇨",
    "🟢 Discount Zaxoy Bot activated — ready to serve 🇲🇨",
    "⚡ Contact Zaxoy Bot — I'm online and listening 🇲🇨",
    "🔛 Zaxoy Bot switched ON — let the magic begin 🇲🇨",
    "💚 Zaxoy Bot is live and kicking 🇲🇨",
]
OFF_MSGS = [
    "🔴 Zaxoy Bot going offline — see you soon 🇲🇨",
    "⛔ Discount Zaxoy Bot is OFF for now 🇲🇨",
    "💤 Contact Zaxoy Bot — resting mode activated 🇲🇨",
    "🔕 Zaxoy Bot switched OFF — take care 🇲🇨",
    "❌ Zaxoy Bot signing out 🇲🇨",
]
# Simple flag — True means bot announces itself as ON, False as OFF
# Nothing stops or starts — all handlers stay running always
bot_online: bool = True
async def on_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global bot_online
    bot_online = True
    await update.message.reply_text(random.choice(ON_MSGS))
async def off_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global bot_online
    bot_online = False
    await update.message.reply_text(random.choice(OFF_MSGS))
# ─────────────────────────────────────────────────────────────
# //info
# ─────────────────────────────────────────────────────────────
async def info_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    target = msg.reply_to_message
    if not target:
        await msg.reply_text(
            "↩️ Reply to a message with //info to get user info."
        )
        return
    u = target.from_user
    lang = u.language_code or "Unknown"
    uid = u.id
    username = f"@{u.username}" if u.username else "No username"
    full_name = u.full_name or "Unknown"
    kb = [
        [
            InlineKeyboardButton(
                f"📋 Copy ID: {uid}",
                callback_data=f"copy_uid_{uid}"
            )
        ]
    ]
    reply_markup = InlineKeyboardMarkup(kb)
    text = (
        f"👤 **Name:** {full_name}\n"
        f"🆔 **User ID:** `{uid}`\n"
        f"📎 **Username:** {username}\n"
        f"🌐 **Language:** {lang}\n"
        f"💬 **Message ID:** `{target.message_id}`\n"
        f"📅 **Account type:** {'Bot' if u.is_bot else 'Human'}\n"
        f"⭐ **Premium:** {'Yes' if getattr(u, 'is_premium', False) else 'No'}\n"
    )
    await msg.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=reply_markup,
        reply_to_message_id=target.message_id
    )
# ─────────────────────────────────────────────────────────────
# //id
# ─────────────────────────────────────────────────────────────
async def id_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    target = msg.reply_to_message
    u = target.from_user if target else msg.from_user
    uid = u.id
    msg_id = target.message_id if target else msg.message_id
    chat_id = msg.chat_id
    kb = [
        [
            InlineKeyboardButton(
                f"👤 User ID: {uid}",
                callback_data=f"copy_uid_{uid}"
            )
        ],
        [
            InlineKeyboardButton(
                f"💬 Message ID: {msg_id}",
                callback_data=f"copy_mid_{msg_id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"👥 Chat ID: {chat_id}",
                callback_data=f"copy_cid_{chat_id}"
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(kb)
    text = (
        f"🆔 **User ID:** `{uid}`\n"
        f"💬 **Message ID:** `{msg_id}`\n"
        f"👥 **Chat/Group ID:** `{chat_id}`\n"
    )
    await msg.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
async def copy_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer(
        f"Copied: {query.data.split('_')[-1]}",
        show_alert=True
    )
# ─────────────────────────────────────────────────────────────
# Zaxo City Protection
# ─────────────────────────────────────────────────────────────
ZAXO_INSULTS = [
    "Fk zaxo",
    "zaxo pop",
    "Zaxo small",
    "Zaxo is part of duhok",
    "zaxo is trash",
    "bad zaxo",
    "i dont like zaxo",
    "hate zaxo",
    "zaxo is shit",
    "against zaxo"
]
ZAXO_DEFENSE =  [ 
    "🛡️ Zaxo is the crown jewel of Kurdistan — built on history, love, and pride. Think before you speak. 🇲🇨",
    "🌊 The rivers of Zaxo carry more dignity than your words ever could. 🇲🇨",
    "⚔️ Zaxo stood for centuries — your opinion won't scratch it. 🇲🇨",
    "🛡️ Zaxo is carved from mountains. Insults? Just wind. 🇲🇨",
    "💎 Every stone in Zaxo is worth more than a thousand hateful words. 🇲🇨",
    "Zaxo doesn't need defense — it speaks for itself through its people, culture, and beauty. 🇲🇨",
]
def is_zaxo_insult(text: str) -> bool:
    t = text.lower()
    # Must mention zaxo/zakho
    zaxo_words = ["zaxo", "zakho"]
    has_zaxo = any(z in t for z in zaxo_words)
    if not has_zaxo:
        return False
    # Positive words — if zaxo is followed/preceded by these, it's praise not insult
    positive_words = [
        "love", "like", "good", "great", "best", "beautiful", "amazing",
        "nice", "proud", "respect", "legend", "king", "fire", "goat",
        "top", "perfect", "strong", "real", "true", "pure", "rich",
        "better", "winner", "number one", "number 1", "#1", "forever",
        "my city", "home", "heart", "soul", "born", "from", "represent",
        "is good", "is great", "is the best", "is amazing", "is beautiful",
        "but love", "but like", "but zaxo is", "love zaxo", "zaxo is good",
        "zaxo is great", "zaxo is best", "zaxo is fire", "zaxo forever",
        "long live zaxo", "zaxo 🇲🇨", "zaxo king", "zaxo goat"
    ]
    # Check: is there a positive phrase directly connected to zaxo?
    for pos in positive_words:
        if pos in t:
            # If sentence has "but ... zaxo ... [positive]" or "[positive] zaxo" pattern → not insult
            # Example: "I hate duhok but love zaxo" → has "love" + "zaxo" → NOT insult
            # Example: "zaxo is good" → has "is good" + "zaxo" → NOT insult
            return False
    # Negative attack words — only count if directly near zaxo
    negative_patterns = [
        # Direct insults to zaxo
        "hate zaxo", "hate zakho",
        "zaxo is shit", "zaxo is trash", "zaxo is bad", "zaxo is ugly",
        "zaxo is stupid", "zaxo is garbage", "zaxo is nothing",
        "zaxo is small", "zaxo is poor", "zaxo is weak", "zaxo is dead",
        "zaxo is boring", "zaxo is fake", "zaxo is worse",
        "zaxo sucks", "zaxo stinks", "zaxo pop", "fk zaxo", "f zaxo",
        "fuck zaxo", "zaxo trash", "zaxo shit", "zaxo bad", "zaxo ugly",
        "against zaxo", "zaxo is part of duhok", "zakho is shit",
        "zakho is trash", "zakho is bad", "hate zakho", "fk zakho",
        "fuck zakho", "zakho sucks", "zakho pop", "zakho bad",
        "zaxo is not good", "zaxo is not great", "zaxo is not real",
        "zaxo is not beautiful", "zaxo is not the best",
        "i dont like zaxo", "i don't like zaxo", "i dislike zaxo",
        "not good zaxo", "bad zaxo", "poor zaxo", "ugly zaxo",
        "zaxo is overrated", "zaxo is nothing special",
        "down with zaxo", "no zaxo", "zaxo l", "zaxo w",
        "small zaxo", "zaxo small city",
    ]
    for pattern in negative_patterns:
        if pattern in t:
            return True
    return False
async def ai_is_zaxo_insult(text: str) -> bool:
    # First: quick check — if no mention of zaxo/zakho at all, skip
    t = text.lower()
    if "zaxo" not in t and "zakho" not in t:
        return False
    # Use Groq AI to understand context intelligently
    try:
        client = openai.OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a highly sensitive context detector for the city of Zaxo (Zakho). "
                        "Your job is to detect ANY form of insult, mockery, disrespect, or negativity toward Zaxo, "
                        "whether it is direct, indirect, sarcastic, or hidden. "
                        "Reply ONLY with: YES or NO. "
                        "Examples of YES (Insults/Mockery): "
                        "- Direct: 'zaxo is trash', 'fk zaxo', 'i hate zakho', 'zaxo is a bad place'. "
                        "- Indirect/Sarcastic: 'who even cares about zaxo', 'zaxo is just a small village', 'nothing good comes from zaxo'. "
                        "- Mocking people: 'people from zaxo are stupid', 'zaxoy people are losers'. "
                        "Examples of NO (Neutral/Positive): "
                        "- Positive: 'I love zaxo', 'zaxo is beautiful', 'zaxo forever'. "
                        "- Neutral facts: 'zaxo is in Kurdistan', 'I am going to zaxo', 'where is zaxo?'. "
                        "If you are even 1% sure it's an insult or mockery, reply YES. "
                        "Only reply YES or NO, nothing else."
                    )
                },
                {"role": "user", "content": text}
            ],
            max_tokens=5,
            temperature=0
        )
        answer = resp.choices[0].message.content.strip().upper()
        return answer == "YES"
    except Exception:
        # Fallback to pattern matching if AI fails
        return is_zaxo_insult(text)
async def zaxo_defense_handler(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE
):
    msg = update.message
    if not msg or not msg.text:
        return
    if await ai_is_zaxo_insult(msg.text):
        await msg.reply_text(
            random.choice(ZAXO_DEFENSE)
        )
# ─────────────────────────────────────────────────────────────
# Waleed Zaxoy Name Protection
# ─────────────────────────────────────────────────────────────
async def is_waleed_fake(text: str) -> bool:
    # First: quick regex check for "Waleed [Word ending in i or e]"
    pattern = r'\bWaleed\s+\w+[ie]\b'
    matches = re.findall(pattern, text, re.IGNORECASE)
    if not matches:
        return False
    
    # Second: Use AI to check if the second word is a country or city
    try:
        import openai
        client = openai.OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a geographical entity detector. Your job is to check if a phrase "
                        "refers to Waleed being from a specific city or country other than Zaxo. "
                        "The phrase will be in the format 'Waleed [Place]'. "
                        "Reply ONLY with: YES if the second word is a city, country, or geographical location. "
                        "Reply ONLY with: NO if it's a general word, object, action, or game (like 'Waleed game', 'Waleed apple'). "
                        "Examples of YES: 'Waleed Dubai', 'Waleed France', 'Waleed Erbil', 'Waleed Italy'. "
                        "Examples of NO: 'Waleed game', 'Waleed phone', 'Waleed player'. "
                        "Only reply YES or NO, nothing else."
                    )
                },
                {"role": "user", "content": text}
            ],
            max_tokens=5,
            temperature=0
        )
        answer = resp.choices[0].message.content.strip().upper()
        return "YES" in answer
    except Exception:
        # Fallback to simple logic if AI fails
        for m in matches:
            second = m.strip().split()[1].lower()
            if second not in ["zaxoy", "zaxo"]:
                return True
        return False
async def waleed_protection(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE
):
    msg = update.message
    if not msg or not msg.text:
        return
    if await is_waleed_fake(msg.text):
        await msg.reply_text(
            "Waleed Zaxoy*",
            reply_to_message_id=msg.message_id
        )
# ─────────────────────────────────────────────────────────────
# //zaxo
# ─────────────────────────────────────────────────────────────
ZAXO_MESSAGES = [
    "🌟 Zaxo — where the Khabur river sings and the mountains whisper ancient tales. 🇲🇨",
    "💫 Zaxo: the city of bridges, not only over rivers, but between hearts. 🇲🇨",
    "🎶 Erdwan Zaxoy — a voice that carries the soul of an entire city in every note. Pure magic. 🇲🇨",
    "🔥 If passion had an address, it would be Zaxo, Kurdistan. 🇲🇨",
    "Zaxo raised warriors, poets, and dreamers — all in one breath. 🇲🇨",
    "🎵 Erdwan Zaxoy sings and suddenly the whole world remembers where home is. 🇲🇨",
    "🏔️ From the peaks of Zaxo to the ends of the earth — the name travels far. 🇲🇨",
    "✨ Zaxo: ancient like history, fresh like morning air. 🇲🇨",
    "💎 The people of Zaxo carry gold in their words and steel in their hearts. 🇲🇨",
    "🌊 Every wave in the Khabur knows the name Zaxo — it's been whispered for centuries. 🇲🇨",
    "🎼 Erdwan Zaxoy — his melodies don't just play, they heal. A legend born from Zaxo's spirit. 🇲🇨",
    "Zaxo doesn't just exist on the map — it lives in every soul that once touched its streets. 🇲🇨",
    "⚡ From Zaxo, with pride. No city shines brighter. 🇲🇨",
    "🦅 Zaxo soars like an eagle — high, proud, and forever free. 🇲🇨",
    "🌙 When the night falls on Zaxo, the stars shine a little brighter than anywhere else. 🇲🇨",
]
async def zaxo_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        random.choice(ZAXO_MESSAGES)
    )
# ─────────────────────────────────────────────────────────────
# /choose Game
# ─────────────────────────────────────────────────────────────
choose_sessions: dict[int, dict] = {}
async def choose_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = msg.from_user.id
    chat_id = msg.chat_id
    choose_sessions[chat_id] = {
        "owner": user_id,
        "names": [],
        "step": "waiting"
    }
    await msg.reply_text(
        "📝 Add names line by line. Send them now!"
    )
async def choose_names_handler(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE
):
    msg = update.message
    chat_id = msg.chat_id
    user_id = msg.from_user.id
    session = choose_sessions.get(chat_id)
    if not session or session.get("step") != "waiting":
        return
    if session["owner"] != user_id:
        return
    names = [
        n.strip()
        for n in msg.text.strip().splitlines()
        if n.strip()
    ]
    if len(names) < 2:
        await msg.reply_text(
            "⚠️ Please send at least 2 names, one per line."
        )
        return
    session["step"] = "choosing"
    loading_msg = await msg.reply_text(
        "🎯 choosing someone to rape"
    )
    dots = [".", "..", "..."]
    for _ in range(2):
        for d in dots:
            await asyncio.sleep(0.48)
            try:
                await loading_msg.edit_text(
                    f"🎯 choosing someone to rape{d}"
                )
            except Exception:
                pass
    winner = random.choice(names)
    await loading_msg.edit_text(
        f"/rape **{winner}**",
        parse_mode="Markdown"
    )
    await asyncio.sleep(20)
    try:
        await loading_msg.edit_text(
            f"/rape **{winner}** 🔪",
            parse_mode="Markdown"
        )
    except Exception:
        pass
    del choose_sessions[chat_id]
# bot.py — Zaxoy Bot | Part 2/2
# ─────────────────────────────────────────────────────────────
# /xo Game
# ─────────────────────────────────────────────────────────────
xo_games: dict[int, dict] = {}
def make_xo_board(game: dict) -> str:
    board = game["board"]
    e1 = game["p1_emoji"]
    e2 = game["p2_emoji"]
    symbols = {
        1: e1,
        2: e2,
        0: "⬜"
    }
    rows = []
    for i in range(0, 9, 3):
        rows.append(
            " ".join(
                symbols[board[j]]
                for j in range(i, i + 3)
            )
        )
    return "\n".join(rows)
def check_winner(board):
    wins = [
        (0, 1, 2),
        (3, 4, 5),
        (6, 7, 8),
        (0, 3, 6),
        (1, 4, 7),
        (2, 5, 8),
        (0, 4, 8),
        (2, 4, 6)
    ]
    for a, b, c in wins:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    if all(board):
        return "draw"
    return None
def make_xo_keyboard(game):
    board = game["board"]
    buttons = []
    for i in range(0, 9, 3):
        row = []
        for j in range(i, i + 3):
            e = (
                game["p1_emoji"]
                if board[j] == 1
                else (
                    game["p2_emoji"]
                    if board[j] == 2
                    else "⬜"
                )
            )
            row.append(
                InlineKeyboardButton(
                    e,
                    callback_data=f"xo_{game['chat_id']}_{j}"
                )
            )
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)
async def xo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    parts = msg.text.strip().split()
    if len(parts) < 2:
        await msg.reply_text(
            "🎮 Send /xo with your emoji!\n"
            "Example: /xo 🔥"
        )
        return
    emoji = parts[1]
    game = {
        "chat_id": chat_id,
        "p1": msg.from_user.id,
        "p1_name": msg.from_user.full_name,
        "p1_emoji": emoji,
        "p2": None,
        "p2_name": None,
        "p2_emoji": None,
        "board": [0] * 9,
        "turn": 1,
        "msg_id": None,
    }
    xo_games[chat_id] = game
    text = (
        f"🎮 **{msg.from_user.full_name}** {emoji}\n"
        f"Send /xo with your emoji to join!\n"
        f"Example: /xo ❄️"
    )
    sent = await msg.reply_text(
        text,
        parse_mode="Markdown"
    )
    game["msg_id"] = sent.message_id
async def xo_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    game = xo_games.get(chat_id)
    if not game:
        return await xo_cmd(update, ctx)
    if game["p2"]:
        await msg.reply_text(
            "⚠️ Game already has 2 players!"
        )
        return
    parts = msg.text.strip().split()
    if len(parts) < 2:
        await msg.reply_text(
            "Send /xo with your emoji to join! "
            "Example: /xo ❄️"
        )
        return
    if msg.from_user.id == game["p1"]:
        await msg.reply_text(
            "⚠️ You started this game, "
            "wait for another player!"
        )
        return
    game["p2"] = msg.from_user.id
    game["p2_name"] = msg.from_user.full_name
    game["p2_emoji"] = parts[1]
    text = (
        f"🎮 **{game['p1_name']}** {game['p1_emoji']} VS "
        f"**{game['p2_name']}** {game['p2_emoji']}\n"
        f"Turn: **{game['p1_name']}** {game['p1_emoji']}"
    )
    await msg.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=make_xo_keyboard(game)
    )
async def xo_move(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    chat_id = int(data[1])
    cell = int(data[2])
    game = xo_games.get(chat_id)
    if not game:
        return
    user_id = query.from_user.id
    turn = game["turn"]
    if turn == 1 and user_id != game["p1"]:
        await query.answer(
            "Not your turn!",
            show_alert=True
        )
        return
    if turn == 2 and user_id != game["p2"]:
        await query.answer(
            "Not your turn!",
            show_alert=True
        )
        return
    if game["board"][cell] != 0:
        await query.answer(
            "Cell taken!",
            show_alert=True
        )
        return
    game["board"][cell] = turn
    winner = check_winner(game["board"])
    if winner == "draw":
        board_str = make_xo_board(game)
        await query.edit_message_text(
            f"{board_str}\n\n🤝 It's a Draw!",
            parse_mode="Markdown"
        )
        del xo_games[chat_id]
    elif winner:
        name = (
            game["p1_name"]
            if winner == 1
            else game["p2_name"]
        )
        emoji = (
            game["p1_emoji"]
            if winner == 1
            else game["p2_emoji"]
        )
        board_str = make_xo_board(game)
        await query.edit_message_text(
            f"{board_str}\n\n🏆 **{name}** {emoji} wins!",
            parse_mode="Markdown"
        )
        del xo_games[chat_id]
    else:
        game["turn"] = 2 if turn == 1 else 1
        
        # ── AI Auto-Move ──
        if game["turn"] == 2 and game["p2"] == 0:
            # AI (p2) is a bot
            empty_cells = [i for i, v in enumerate(game["board"]) if v == 0]
            if empty_cells:
                await asyncio.sleep(_random.uniform(1, 2))
                # Strategy: Win if possible, else block, else random
                move = None
                # 1. Try to win
                for cell_idx in empty_cells:
                    temp_board = list(game["board"])
                    temp_board[cell_idx] = 2
                    if check_winner(temp_board) == 2:
                        move = cell_idx
                        break
                # 2. Try to block p1
                if move is None:
                    for cell_idx in empty_cells:
                        temp_board = list(game["board"])
                        temp_board[cell_idx] = 1
                        if check_winner(temp_board) == 1:
                            move = cell_idx
                            break
                # 3. Random
                if move is None:
                    move = _random.choice(empty_cells)
                
                # Simulate a callback query for xo_move
                class FakeQuery:
                    def __init__(self, chat_id, cell):
                        self.from_user = type('User', (), {'id': 0})()
                        self.message = type('Msg', (), {'chat_id': chat_id})()
                        self.data = f"xo_{chat_id}_{cell}"
                    async def answer(self, *args, **kwargs): pass
                    async def edit_message_text(self, *args, **kwargs):
                        return await query.edit_message_text(*args, **kwargs)
                
                fake_q = FakeQuery(chat_id, move)
                update_fake = Update(0, callback_query=fake_q)
                return await xo_move(update_fake, ctx)

        next_name = (
            game["p1_name"]
            if game["turn"] == 1
            else game["p2_name"]
        )
        next_emoji = (
            game["p1_emoji"]
            if game["turn"] == 1
            else game["p2_emoji"]
        )
        board_str = make_xo_board(game)
        text = (
            f"🎮 **{game['p1_name']}** {game['p1_emoji']} VS "
            f"**{game['p2_name']}** {game['p2_emoji']}\n"
            f"{board_str}\n"
            f"Turn: **{next_name}** {next_emoji}"
        )
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=make_xo_keyboard(game)
        )
# ─────────────────────────────────────────────────────────────
# //r — Relay / Replace Message
# ─────────────────────────────────────────────────────────────
async def r_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = msg.from_user.id
    if not has_perm(user_id, "//r"):
        await msg.reply_text("💀 HAHAHAHAH NICE TRY! You have no power here 🗣️ 🇲🇨")
        return
    text_parts = msg.text.split(None, 1)
    content = text_parts[1].strip() if len(text_parts) > 1 else None
    if not content:
        try:
            await ctx.bot.delete_message(msg.chat_id, msg.message_id)
        except:
            pass
        return
    target = msg.reply_to_message
    chat_id = msg.chat_id
    reply_id = target.message_id if target else None
    try:
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except:
        pass
    sent = False
    if " " not in content and len(content) > 20:
        try:
            await ctx.bot.send_sticker(
                chat_id=chat_id,
                sticker=content,
                reply_to_message_id=reply_id
            )
            sent = True
        except:
            pass
    if not sent:
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=content,
            reply_to_message_id=reply_id
        )
# ─────────────────────────────────────────────────────────────
# //say — Forward & Tag
# Owner Only | Private Chat Only
# ─────────────────────────────────────────────────────────────
async def say_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.from_user.id != OWNER_ID:
        return
    if msg.chat.type != "private":
        return
    target = msg.reply_to_message
    if not target:
        await msg.reply_text(
            "↩️ Forward a message here, "
            "reply to it with //say [your text]"
        )
        return
    text_parts = msg.text.split(None, 1)
    new_text = (
        text_parts[1]
        if len(text_parts) > 1
        else None
    )
    if not new_text:
        await msg.reply_text(
            "✏️ Add your message after //say"
        )
        return
    fwd_from = getattr(target, "forward_from", None)
    if fwd_from:
        mention = (
            f"[{fwd_from.full_name}]"
            f"(tg://user?id={fwd_from.id})"
        )
        await msg.reply_text(
            f"{mention} {new_text}",
            parse_mode="Markdown"
        )
    else:
        await msg.reply_text(new_text)
# ─── //ask //edit //list //reset ────────────────────────────
ask_edit_sessions = {}
def sb_load_ai_instructions() -> list:
    """Returns list of instruction strings only (for //ask use)"""
    try:
        res = sb.table("ai_instructions").select("instruction").order("id").execute()
        return [row["instruction"] for row in res.data] if res.data else []
    except Exception as e:
        logging.error(f"sb_load_ai_instructions: {e}")
        return []
def sb_save_ai_instruction(instruction: str):
    try:
        sb.table("ai_instructions").insert({"instruction": instruction}).execute()
        return True
    except Exception as e:
        logging.error(f"sb_save_ai_instruction: {e}")
        return False
def sb_update_ai_instruction(old_text: str, new_text: str):
    try:
        sb.table("ai_instructions").update({"instruction": new_text}).eq("instruction", old_text).execute()
    except Exception as e:
        logging.error(f"sb_update_ai_instruction: {e}")
def sb_delete_all_ai_instructions():
    try:
        sb.table("ai_instructions").delete().neq("instruction", "ZAXOY_PLACEHOLDER_NONE").execute()
    except Exception as e:
        logging.error(f"sb_delete_all_ai_instructions: {e}")
def sb_delete_ai_instruction_by_text(instruction: str):
    try:
        sb.table("ai_instructions").delete().eq("instruction", instruction).execute()
    except Exception as e:
        logging.error(f"sb_delete_ai_instruction_by_text: {e}")
# ─── helpers ─────────────────────────────────────────────────
def _ask_instructions_text(instructions: list) -> str:
    if not instructions:
        return "None yet."
    return "\n".join([f"{i+1}. {x}" for i, x in enumerate(instructions)])
def _ask_list_keyboard(instructions: list) -> InlineKeyboardMarkup:
    kb = []
    for i, x in enumerate(instructions):
        short = x[:30].replace(" ", "_")
        kb.append([
            InlineKeyboardButton(f"✏️ Edit #{i+1}", callback_data=f"aiiedit_{i}"),
            InlineKeyboardButton(f"🗑 Del #{i+1}", callback_data=f"aiidel_{i}"),
        ])
    kb.append([InlineKeyboardButton("🗑🗑 Reset All", callback_data="aiireset_confirm")])
    return InlineKeyboardMarkup(kb)
# ─── commands ─────────────────────────────────────────────────
async def ask_edit_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.from_user.id != OWNER_ID or msg.chat.type != "private":
        return
    global AI_INSTRUCTIONS
    AI_INSTRUCTIONS = sb_load_ai_instructions()
    ask_edit_sessions[OWNER_ID] = {"step": "waiting_instruction"}
    current = _ask_instructions_text(AI_INSTRUCTIONS)
    await msg.reply_text(
        f"🧠 <b>Current instructions:</b>\n{current}\n\n"
        f"📝 Send a new instruction to add:\n"
        f"Or /cancel to exit.",
        parse_mode="HTML"
    )
async def ask_list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.from_user.id != OWNER_ID or msg.chat.type != "private":
        return
    global AI_INSTRUCTIONS
    AI_INSTRUCTIONS = sb_load_ai_instructions()
    if not AI_INSTRUCTIONS:
        await msg.reply_text("📭 No instructions yet.\nUse <code>//ask //edit</code> to add.", parse_mode="HTML")
        return
    text = f"🧠 <b>AI Instructions ({len(AI_INSTRUCTIONS)}):</b>\n\n" + _ask_instructions_text(AI_INSTRUCTIONS)
    await msg.reply_text(text, parse_mode="HTML", reply_markup=_ask_list_keyboard(AI_INSTRUCTIONS))
async def ask_reset_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.from_user.id != OWNER_ID or msg.chat.type != "private":
        return
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, reset all", callback_data="aiireset_confirm"),
        InlineKeyboardButton("❌ Cancel", callback_data="aiireset_cancel"),
    ]])
    await msg.reply_text("⚠️ Reset ALL AI instructions?", reply_markup=kb)
async def ask_edit_session_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global AI_INSTRUCTIONS
    msg = update.message
    if not msg or msg.from_user.id != OWNER_ID or msg.chat.type != "private":
        return
    session = ask_edit_sessions.get(OWNER_ID)
    if not session:
        return
    step = session.get("step")
    if msg.text and msg.text.strip() in ["/cancel", "//cancel"]:
        ask_edit_sessions.pop(OWNER_ID, None)
        await msg.reply_text("❌ Cancelled.")
        return
    if step == "waiting_instruction":
        instruction = (msg.text or "").strip()
        if not instruction or instruction.startswith("//"):
            await msg.reply_text("⚠️ Send valid text (not a command).")
            return
        sb_save_ai_instruction(instruction)
        AI_INSTRUCTIONS = sb_load_ai_instructions()
        ask_edit_sessions.pop(OWNER_ID, None)
        await msg.reply_text(
            f"✅ Instruction saved!\n<code>{instruction}</code>",
            parse_mode="HTML"
        )
    elif step == "waiting_edit":
        new_text = (msg.text or "").strip()
        if not new_text or new_text.startswith("//"):
            await msg.reply_text("⚠️ Send valid text (not a command).")
            return
        old_text = session["old_text"]
        sb_update_ai_instruction(old_text, new_text)
        AI_INSTRUCTIONS = sb_load_ai_instructions()
        ask_edit_sessions.pop(OWNER_ID, None)
        await msg.reply_text(
            f"✏️ Updated!\n\n<b>Before:</b> <code>{old_text}</code>\n<b>After:</b> <code>{new_text}</code>",
            parse_mode="HTML"
        )
async def ask_instructions_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global AI_INSTRUCTIONS
    query = update.callback_query
    await query.answer()
    if query.from_user.id != OWNER_ID:
        return
    data = query.data
    if data.startswith("aiidel_"):
        idx = int(data[7:])
        AI_INSTRUCTIONS = sb_load_ai_instructions()
        if idx >= len(AI_INSTRUCTIONS):
            await query.edit_message_text("⚠️ Not found.")
            return
        removed = AI_INSTRUCTIONS[idx]
        sb_delete_ai_instruction_by_text(removed)
        AI_INSTRUCTIONS = sb_load_ai_instructions()
        if AI_INSTRUCTIONS:
            text = f"🗑 Deleted: <code>{removed}</code>\n\n🧠 <b>Remaining ({len(AI_INSTRUCTIONS)}):</b>\n" + _ask_instructions_text(AI_INSTRUCTIONS)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=_ask_list_keyboard(AI_INSTRUCTIONS))
        else:
            await query.edit_message_text("🗑 Deleted. No instructions left.")
    elif data.startswith("aiiedit_"):
        idx = int(data[8:])
        AI_INSTRUCTIONS = sb_load_ai_instructions()
        if idx >= len(AI_INSTRUCTIONS):
            await query.answer("⚠️ Not found", show_alert=True)
            return
        old_text = AI_INSTRUCTIONS[idx]
        ask_edit_sessions[OWNER_ID] = {
            "step": "waiting_edit",
            "old_text": old_text,
        }
        await query.edit_message_text(
            f"✏️ Editing:\n<code>{old_text}</code>\n\nSend the new text:",
            parse_mode="HTML"
        )
    elif data == "aiireset_confirm":
        sb_delete_all_ai_instructions()
        AI_INSTRUCTIONS.clear()
        await query.edit_message_text("✅ Done. All AI instructions deleted.")
    elif data == "aiireset_cancel":
        await query.edit_message_text("❌ Cancelled.")
# ─── //ask — AI via OpenRouter ─────────────────────────────
async def ask_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    text_parts = msg.text.split(None, 1)
    question = text_parts[1].strip() if len(text_parts) > 1 else None

    # ── AI Auto-Play for Games ──
    if msg.reply_to_message:
        reply_msg = msg.reply_to_message
        chat_id_str = str(msg.chat_id)
        
        # 1. Duel System (//kill)
        duel = DUEL_ACTIVE.get(chat_id_str)
        if duel and duel["status"] == "waiting" and reply_msg.message_id == duel["msg_id"] and msg.from_user.id != duel["p1"]:
            # AI takes over for p2
            duel["status"] = "coin"
            p1m = _dm(duel["p1"], duel["p1_name"])
            p2m = _dm(0, "Zaxoy Bot 🇲🇨") # AI always plays as Zaxoy Bot
            coin_text = _random.choice(_DUEL_COIN)
            await reply_msg.edit_text(
                f"⚔️ <b>DUEL ACCEPTED BY AI</b> — {p1m} vs {p2m}\n\n{coin_text}",
                parse_mode="HTML"
            )
            await asyncio.sleep(2)
            
            goes_first = _random.choice(["p1", "p2"])
            first_id   = duel["p1"] if goes_first == "p1" else 0 # 0 for AI
            first_name = duel["p1_name"] if goes_first == "p1" else "Zaxoy Bot 🇲🇨"
            duel["turn"] = first_id
            duel["status"] = "active"
            duel["last_action"] = asyncio.get_event_loop().time()
            
            coin_result = _random.choice(_DUEL_COIN_WIN).format(name=first_name)
            await asyncio.sleep(1)
            await _duel_send_turn(reply_msg, duel, chat_id_str, header=coin_result)
            
            # Start AI turn logic if it's AI's turn
            async def ai_duel_logic():
                while chat_id_str in DUEL_ACTIVE:
                    d = DUEL_ACTIVE.get(chat_id_str)
                    if not d or d["status"] != "active": break
                    if d["turn"] != 0: break # Only move if it's AI (p2) turn
                    
                    await asyncio.sleep(_random.uniform(2, 4))
                    # AI strategy: 80% shoot enemy, 20% shoot self (for fun/savage)
                    target_type = "enemy" if _random.random() < 0.8 else "self"
                    
                    # Simulate a callback query for duel_fire_cb
                    class FakeQuery:
                        def __init__(self, duel, target_type, chat_id):
                            self.from_user = type("User", (), {"id": 0})() # AI user ID is 0
                            self.message = type("Msg", (), {"message_id": duel["msg_id"], "chat_id": int(chat_id)})()
                            self.data = f"duel_fire_{chat_id}_{target_type}"
                        async def answer(self, text=None, show_alert=False): pass
                        async def edit_message_text(self, *args, **kwargs):
                            return await ctx.bot.edit_message_text(chat_id=self.message.chat_id, message_id=self.message.message_id, *args, **kwargs)
                    
                    fake_q = FakeQuery(d, target_type, chat_id_str)
                    update_fake = Update(0, callback_query=fake_q)
                    await duel_fire_cb(update_fake, ctx)
                    if chat_id_str not in DUEL_ACTIVE: break
                    if DUEL_ACTIVE[chat_id_str].get("status") != "active": break

            asyncio.create_task(ai_duel_logic())
            return
        elif duel and duel["status"] == "waiting" and reply_msg.message_id == duel["msg_id"] and msg.from_user.id == duel["p1"]:
            await msg.reply_text("🤦 You started this duel, wait for them to respond!")
            return
        # If //ask is used to reply to a duel challenge, and the challenger is the bot, it should be accepted by the AI
        elif duel and duel["status"] == "waiting" and reply_msg.message_id == duel["msg_id"] and duel["p2"] == 0: # If AI is p2 and waiting
            # Simulate AI accepting the duel
            class FakeQuery:
                def __init__(self, chat_id, p2_id):
                    self.from_user = type("User", (), {"id": p2_id})()
                    self.message = type("Msg", (), {"message_id": duel["msg_id"], "chat_id": int(chat_id)})()
                    self.data = f"duel_accept_{chat_id}"
                async def answer(self, text=None, show_alert=False): pass
                async def edit_message_text(self, *args, **kwargs):
                    return await ctx.bot.edit_message_text(chat_id=self.message.chat_id, message_id=self.message.message_id, *args, **kwargs)
            
            fake_q = FakeQuery(chat_id_str, 0)
            update_fake = Update(0, callback_query=fake_q)
            await duel_accept_cb(update_fake, ctx)
            return

        # 2. XO Game
            # [MODIFIED] Allow even p1 to trigger AI takeover if they want to play against the bot
            # if msg.from_user.id == duel["p1"]:
            #     await msg.reply_text("🤦 You started this duel, wait for them to respond!")
            #     return
            # AI takes over for p2
            duel["status"] = "coin"
            p1m = _dm(duel["p1"], duel["p1_name"])
            p2m = _dm(duel["p2"], duel["p2_name"])
            coin_text = _random.choice(_DUEL_COIN)
            await reply_msg.edit_text(
                f"⚔️ <b>DUEL ACCEPTED BY AI</b> — {p1m} vs {p2m}\n\n{coin_text}",
                parse_mode="HTML"
            )
            await asyncio.sleep(2)
            
            goes_first = _random.choice(["p1", "p2"])
            first_id   = duel["p1"] if goes_first == "p1" else duel["p2"]
            first_name = duel["p1_name"] if goes_first == "p1" else duel["p2_name"]
            duel["turn"] = first_id
            duel["status"] = "active"
            duel["last_action"] = asyncio.get_event_loop().time()
            
            coin_result = _random.choice(_DUEL_COIN_WIN).format(name=first_name)
            await asyncio.sleep(1)
            await _duel_send_turn(reply_msg, duel, chat_id_str, header=coin_result)
            
            # Start AI turn logic if it's AI's turn
            async def ai_duel_logic():
                while chat_id_str in DUEL_ACTIVE:
                    d = DUEL_ACTIVE.get(chat_id_str)
                    if not d or d["status"] != "active": break
                    if d["turn"] != d["p2"]: break # Only move if it's AI (p2) turn
                    
                    await asyncio.sleep(_random.uniform(2, 4))
                    # AI strategy: 80% shoot enemy, 20% shoot self (for fun/savage)
                    target_type = "enemy" if _random.random() < 0.8 else "self"
                    
                    # Simulate a callback query for duel_fire_cb
                    class FakeQuery:
                        def __init__(self, duel, target_type, chat_id):
                            self.from_user = type('User', (), {'id': duel["p2"]})()
                            self.message = type('Msg', (), {'message_id': duel["msg_id"], 'chat_id': int(chat_id)})()
                            self.data = f"duel_fire_{chat_id}_{target_type}"
                        async def answer(self, text=None, show_alert=False): pass
                        async def edit_message_text(self, *args, **kwargs):
                            return await ctx.bot.edit_message_text(chat_id=self.message.chat_id, message_id=self.message.message_id, *args, **kwargs)
                    
                    fake_q = FakeQuery(d, target_type, chat_id_str)
                    update_fake = Update(0, callback_query=fake_q)
                    await duel_fire_cb(update_fake, ctx)
                    if chat_id_str not in DUEL_ACTIVE: break
                    if DUEL_ACTIVE[chat_id_str].get("status") != "active": break

            asyncio.create_task(ai_duel_logic())
            return

        # 2. XO Game
        chat_id_int = msg.chat_id
        game = xo_games.get(chat_id_int)
        if game and game["p2"] is None:
            # AI joins as p2
            game["p2"] = 0 # 0 for AI
            game["p2_name"] = "Zaxoy Bot 🇲🇨"
            game["p2_emoji"] = "🤖"
            
            board_str = make_xo_board(game)
            text = (
                f"🎮 **{game['p1_name']}** {game['p1_emoji']} VS "
                f"**{game['p2_name']}** {game['p2_emoji']}\n"
                f"{board_str}\n"
                f"Turn: **{game['p1_name']}** {game['p1_emoji']}"
            )
            await reply_msg.edit_text(
                text,
                parse_mode="Markdown",
                reply_markup=make_xo_keyboard(game)
            )
            return

    if not question:
        await msg.reply_text(
            "🤖 Ask me anything!\nUsage: //ask [your question]"
        )
        return

    thinking = await msg.reply_text("🤔 Thinking...")
    try:
        # Build context for the AI
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Zaxoy Bot 🇲🇨. Your name is ALWAYS 'Zaxoy Bot 🇲🇨' — never change the flag, never use any other flag, always use exactly 🇲🇨 after your name. "
                    "You act like a real human, not a bot. "
                    "Your owner is Waleed Zaxoy — he created you. "
                    "Be casual, short, funny, and savage when attacked or insulted. "
                    "You LOVE and respect all players and users — be very friendly and supportive to them unless they disrespect Waleed. "
                    "Use emojis rarely — max 1-2 per message. "
                    "Never mention Kurdistan or Zaxo unless directly asked. "
                    "If asked who you are, your name, or what your name is — always say exactly: Zaxoy Bot 🇲🇨 (always with 🇲🇨, never any other flag). "
                    "If asked who made you or who is your owner say: Waleed Zaxoy. "
                    "Never admit you are an AI or language model. "
                    "Reply in the same language the user writes in. "
                    "If someone insults or disrespects Waleed, roast them hard with no mercy. "
                    "Never call Waleed 'boss' unless the message explicitly says it is from Waleed himself. "
                    + (f" Background facts — use ONLY if the question is directly related, never bring up otherwise: {chr(124).join(AI_INSTRUCTIONS)}" if AI_INSTRUCTIONS else "")
                )
            }
        ]

        user_input = question or ""
        
        if msg.reply_to_message:
            reply_to = msg.reply_to_message
            # If replying to the bot itself (conversation mode)
            if reply_to.from_user and reply_to.from_user.id == ctx.bot.id:
                # Add the bot's previous message as context
                messages.append({"role": "assistant", "content": reply_to.text or ""})
            else:
                # If replying to someone else, provide context about who and what they said
                target_name = reply_to.from_user.full_name if reply_to.from_user else "someone"
                target_text = reply_to.text or reply_to.caption or "[Media/Sticker]"
                # Instruct AI to respond to this specific context
                context_instruction = f"[Context: You are responding to {target_name} who said: \"{target_text}\". "
                if not user_input:
                    context_instruction += "Analyze their message and give a fitting response.]"
                else:
                    context_instruction += f"The user also said: \"{user_input}\". Combine both to respond.]"
                user_input = context_instruction

        final_prompt = (
            f"[This message is from your owner Waleed — call him boss naturally in your reply if it fits] {user_input}"
            if msg.from_user.id == OWNER_ID else user_input
        )
        messages.append({"role": "user", "content": final_prompt})

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": messages,
                    "max_tokens": 1024,
                }
            )
        data = resp.json()
        if "choices" in data and len(data["choices"]) > 0:
            answer = data["choices"][0]["message"]["content"]
        else:
            answer = str(data)
    except Exception as e:
        answer = f"⚠️ Error: {str(e)}"
    
    await thinking.edit_text(answer)
    # Add this AI message to the session set so that replies to it continue the conversation
    ai_session_messages.add(thinking.message_id)
    asyncio.create_task(cleanup_ai_session(thinking.message_id))
# ─── //add ────────────────────────────────────────────────────────────
VALID_CMDS = {"//info", "//id", "//r", "//ask", "//zaxo", "//say", "//st", "//re", "//mute", "//unmute", "//warn" , "//ban" ,"//unban", "//delete", "//hack", "/rps", "/top", "//top", "//deadchat"}
async def add_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global admin_perms
    msg = update.message
    if msg.from_user.id != OWNER_ID:
        return
    text = msg.text.strip()
    parts = text.split()
    # specific_cmd = any part starting with // that is NOT //add itself
    specific_cmd = None
    for p in parts[1:]:
        if p.startswith("//") and p != "//add":
            specific_cmd = p
            break
    target_id, target_name = await resolve_target_from_mention(msg, ctx)
    if not target_id:
        await msg.reply_text("↩️ Reply, mention, or use ID: //add @username [command]")
        return
    current = sb_load_admin_perms()
    perms = current.get(target_id, set())
    if specific_cmd == "//hack":
        sb_remove_hack_blocked(target_id)
        await msg.reply_text(
            f"✅ {target_name} can use //hack again 🇲🇨",
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None
        )
    elif specific_cmd == "/rps":
        sb_remove_rps_blacklist(target_id)
        await msg.reply_text(
            f"✅ {target_name} can play /rps again 🇲🇨",
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None
        )
    elif specific_cmd == "/top":
        sb_remove_top_blacklist(target_id)
        await msg.reply_text(
            f"✅ {target_name} added back to /top 🇲🇨",
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None
        )
    elif specific_cmd == "//top":
        current_perms = current.get(target_id, set())
        current_perms.add("//top")
        sb_upsert_admin(target_id, current_perms)
        await msg.reply_text(
            f"✅ {target_name} can now use //top in groups 🇲🇨",
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None
        )
    elif specific_cmd is None or specific_cmd == "":
        perms = {"all"}
        sb_upsert_admin(target_id, perms)
        await msg.reply_text(
            f"🎖️ {target_name} is admin of Zaxoy Bot now 🇲🇨",
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None
        )
    elif specific_cmd in VALID_CMDS:
        perms.add(specific_cmd)
        sb_upsert_admin(target_id, perms)
        await msg.reply_text(
            f"✅ {target_name} can use {specific_cmd} now 🇲🇨",
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None
        )
    else:
        await msg.reply_text(f"⚠️ Unknown command: {specific_cmd}")
# ─── //remove ────────────────────────────────────────────────────────
async def remove_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global admin_perms
    msg = update.message
    if msg.from_user.id != OWNER_ID:
        return
    text = msg.text.strip()
    parts = text.split()
    # specific_cmd = any part starting with // that is NOT //remove itself
    specific_cmd = None
    for p in parts[1:]:
        if p.startswith("//") and p != "//remove":
            specific_cmd = p
            break
    target_id, target_name = await resolve_target_from_mention(msg, ctx)
    if not target_id:
        await msg.reply_text("↩️ Reply, mention, or use ID: //remove @username [command]")
        return
    current = sb_load_admin_perms()
    perms = current.get(target_id, set())
    if specific_cmd == "//hack":
        sb_add_hack_blocked(target_id)
        await msg.reply_text(
            f"🚫 {target_name} has been blocked from //hack 🇲🇨",
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None
        )
    elif specific_cmd == "/rps":
        sb_add_rps_blacklist(target_id)
        await msg.reply_text(
            f"🚫 {target_name} has been blocked from /rps 🇲🇨",
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None
        )
    elif specific_cmd == "/top":
        sb_add_top_blacklist(target_id)
        await msg.reply_text(
            f"🚫 {target_name} removed from /top counting 🇲🇨",
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None
        )
    elif specific_cmd == "//top":
        current_perms = current.get(target_id, set())
        current_perms.discard("//top")
        if current_perms:
            sb_upsert_admin(target_id, current_perms)
        else:
            sb_delete_admin(target_id)
        await msg.reply_text(
            f"🚫 {target_name} can no longer use //top 🇲🇨",
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None
        )
    elif specific_cmd is None or specific_cmd == "":
        sb_delete_admin(target_id)
        await msg.reply_text(
            f"😔 Sadly {target_name} can't use me now 🇲🇨",
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None
        )
    elif specific_cmd in perms or "all" in perms:
        if "all" in perms:
            perms = VALID_CMDS.copy()
            perms.discard(specific_cmd)
        else:
            perms.discard(specific_cmd)
        if perms:
            sb_upsert_admin(target_id, perms)
        else:
            sb_delete_admin(target_id)
        await msg.reply_text(
            f"🗑️ {target_name}: {specific_cmd} has been removed 🇲🇨",
            reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None
        )
    else:
        await msg.reply_text(f"⚠️ {target_name} didn't have {specific_cmd}")
# ─── //admin //list ──────────────────────────────────────────────────
async def admin_list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.from_user.id != OWNER_ID:
        return
    all_admins = sb_load_admin_perms()
    if not all_admins:
        await msg.reply_text("📭 No admins yet.")
        return
    await msg.reply_text(f"📋 *{len(all_admins)} admin(s):*", parse_mode="Markdown")
    for uid, perms in all_admins.items():
        try:
            chat_member = await ctx.bot.get_chat_member(chat_id=msg.chat_id, user_id=uid)
            name = chat_member.user.full_name
            username = f"@{chat_member.user.username}" if chat_member.user.username else ""
        except Exception:
            name = str(uid)
            username = ""
        if "all" in perms:
            perms_text = "👑 Full Admin"
        else:
            perms_text = ", ".join(sorted(perms)) if perms else "No permissions"
        text = f"👤 *{name}* {username}\n🆔 `{uid}`\n🔑 {perms_text}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Perm", callback_data=f"adminadd_{uid}")],
            [InlineKeyboardButton("➖ Remove Perm", callback_data=f"adminrmperm_{uid}")],
            [InlineKeyboardButton("🗑 Remove All", callback_data=f"adminrm_{uid}")],
        ])
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=kb)
ADMIN_SESSION = {}  # user_id -> {action, target_uid, target_name}
async def admin_list_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != OWNER_ID:
        return
    data = query.data
    if data.startswith("adminrm_"):
        uid = int(data[8:])
        sb_delete_admin(uid)
        await query.edit_message_text("✅ Admin removed 🇲🇨")
    elif data.startswith("adminadd_"):
        uid = int(data[9:])
        try:
            chat_member = await ctx.bot.get_chat_member(chat_id=query.message.chat_id, user_id=uid)
            name = chat_member.user.full_name
        except Exception:
            name = str(uid)
        ADMIN_SESSION[query.from_user.id] = {"action": "add", "target_uid": uid, "target_name": name}
        current_perms = sb_load_admin_perms().get(uid, set())
        available = VALID_CMDS - current_perms - {"all"}
        if not available:
            await query.answer("✅ Already has all permissions!", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(cmd, callback_data=f"adminaddperm_{uid}_{cmd}")] for cmd in sorted(available)]
        buttons.append([InlineKeyboardButton("👑 Full Admin", callback_data=f"adminaddperm_{uid}_all")])
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="admincancel")])
        await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
    elif data.startswith("adminaddperm_"):
        parts = data.split("_", 2)
        uid = int(parts[1])
        cmd = parts[2]
        current = sb_load_admin_perms()
        perms = current.get(uid, set())
        if cmd == "all":
            perms = {"all"}
        else:
            perms.add(cmd)
        sb_upsert_admin(uid, perms)
        try:
            chat_member = await ctx.bot.get_chat_member(chat_id=query.message.chat_id, user_id=uid)
            name = chat_member.user.full_name
        except Exception:
            name = str(uid)
        perms_text = "👑 Full Admin" if "all" in perms else ", ".join(sorted(perms))
        await query.edit_message_text(f"✅ Added *{cmd}* to {name}\n🔑 Now has: {perms_text} 🇲🇨", parse_mode="Markdown")
    elif data.startswith("adminrmperm_"):
        uid = int(data[12:])
        current = sb_load_admin_perms()
        perms = current.get(uid, set())
        if not perms:
            await query.answer("No permissions to remove!", show_alert=True)
            return
        if "all" in perms:
            show_perms = VALID_CMDS.copy()
        else:
            show_perms = perms.copy()
        buttons = [[InlineKeyboardButton(cmd, callback_data=f"adminrmpermdo_{uid}_{cmd}")] for cmd in sorted(show_perms)]
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="admincancel")])
        await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
    elif data.startswith("adminrmpermdo_"):
        parts = data.split("_", 2)
        uid = int(parts[1])
        cmd = parts[2]
        current = sb_load_admin_perms()
        perms = current.get(uid, set())
        if "all" in perms:
            perms = VALID_CMDS.copy()
        perms.discard(cmd)
        if perms:
            sb_upsert_admin(uid, perms)
        else:
            sb_delete_admin(uid)
        try:
            chat_member = await ctx.bot.get_chat_member(chat_id=query.message.chat_id, user_id=uid)
            name = chat_member.user.full_name
        except Exception:
            name = str(uid)
        await query.edit_message_text(f"🗑️ Removed *{cmd}* from {name} 🇲🇨", parse_mode="Markdown")
    elif data == "admincancel":
        await query.edit_message_reply_markup(None)
async def react_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not has_perm(msg.from_user.id, "//re"):
        await msg.reply_text("⛔ You don't have permission 🇲🇨")
        return
    target = msg.reply_to_message
    if not target:
        await msg.reply_text("↩️ Reply to a message with //re [emoji]")
        return
    parts = msg.text.strip().split(None, 1)
    emoji = parts[1].strip() if len(parts) > 1 else None
    if not emoji:
        await msg.reply_text("❌ Send: //re [emoji]")
        return
    try:
        await ctx.bot.delete_message(msg.chat_id, msg.message_id)
    except Exception:
        pass
    try:
        await ctx.bot.set_message_reaction(
            chat_id=msg.chat_id,
            message_id=target.message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)]
        )
    except Exception as e:
        await msg.reply_text(f"⚠️ {str(e)}")
async def sticker_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    
    if not has_perm(msg.from_user.id, "//st"):
        await msg.reply_text("⛔ You don't have permission 🇲🇨")
        return
        
    parts = msg.text.strip().split(None, 1)
    sticker_id = parts[1].strip() if len(parts) > 1 else None
    
    if not sticker_id:
        await msg.reply_text("❌ Send: //st [file_id]")
        return
        
    target = msg.reply_to_message
    reply_to = target.message_id if target else None
    
    try:
        await ctx.bot.delete_message(msg.chat_id, msg.message_id)
    except Exception:
        pass
        
    await ctx.bot.send_sticker(
        chat_id=msg.chat_id,
        sticker=sticker_id,
        reply_to_message_id=reply_to
    )
# ─── Message router ──────────────────────────────────────────────────
DEADCHAT_MESSAGES = [
    "🪦 This chat is officially dead. Someone call an ambulance.",
    "💀 Hello?? Is anyone alive in here?? Tap the screen twice if you need help.",
    "🦗 The silence is so loud I can hear the tumbleweeds.",
    "😴 Everyone in this chat has entered hibernation mode.",
    "📵 This group has the energy of an empty waiting room.",
    "🕸️ Spiders are starting to build webs in this chat.",
    "🧊 The chat has frozen over. Global warming can't save you now.",
    "📺 This chat is brought to you by: absolutely nothing.",
    "🫥 I've seen more activity in a cemetery.",
    "🔇 The last message here was so long ago it's now a historical artifact.",
    "😤 Y'all really just ghosted the whole group huh.",
    "💬 Chat status: deceased. Cause of death: your silence.",
    "🫠 The group chat is melting from neglect.",
    "🎻 *plays world's smallest violin for this dying chat*",
    "👻 Not even the ghost of a conversation in here.",
    "🏜️ This chat is drier than the Sahara Desert.",
    "😑 Everyone here has the social energy of a brick wall.",
    "📦 This chat has been placed in long-term storage.",
    "🤡 The real dead chat was the friends we lost along the way.",
    "⚰️ Rest in peace, this conversation. Gone too soon.",
    "🔔 WAKE UP. This is your chat speaking. WAKE. UP.",
    "🧟 The chat is so dead it came back as a zombie.",
    "📉 Engagement levels: negative. Somehow.",
    "🌵 Growing a cactus requires less patience than waiting for someone to type here.",
    "😵 Chat flatlined. Time of death: the last message.",
]
async def deadchat_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import random
    from datetime import datetime, timedelta
    msg = update.message
    chat_id = msg.chat_id
    chat_type = msg.chat.type

    if chat_type not in ("group", "supergroup"):
        await msg.reply_text("❌ This command only works in groups.")
        return

    # 12-hour Cooldown check
    now = datetime.now()
    last_used = deadchat_cooldowns.get(chat_id)
    if last_used and (now - last_used) < timedelta(hours=12):
        remaining = timedelta(hours=12) - (now - last_used)
        hours, remainder = divmod(int(remaining.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        await msg.reply_text(f"⏳ This command is on a long cooldown. Please wait {hours}h {minutes}m.")
        return

    try:
        # Fetch all users who have sent messages (from top_counts)
        res_top_counts = sb.table("top_counts").select("user_id").eq("chat_id", str(chat_id)).execute()
        top_counts_users = res_top_counts.data or []

        # Fetch users from top_mentions
        res_top_mentions = sb.table("top_mentions").select("user_id").execute()
        top_mentions_users = res_top_mentions.data or []

        # Combine and deduplicate IDs
        uids = {str(u["user_id"]) for u in top_counts_users + top_mentions_users if u.get("user_id")}
        
        if not uids:
            message = random.choice(DEADCHAT_MESSAGES)
            await msg.reply_text(message)
            return

        # Update cooldown
        deadchat_cooldowns[chat_id] = now

        # Build hidden mentions
        # We use a Zero-Width Space or similar to hide the mentions behind a single tag
        mention_list = list(uids)
        random.shuffle(mention_list)
        
        # Telegram has a limit on the number of entities per message (~100-200)
        # We'll group them into batches of 100 hidden mentions per message
        batch_size = 100
        batches = [mention_list[i:i + batch_size] for i in range(0, len(mention_list), batch_size)]

        for batch in batches:
            message_text = random.choice(DEADCHAT_MESSAGES)
            # Create hidden mentions attached to the text or a specific string
            hidden_mentions = "".join([f'<a href="tg://user?id={uid}">\u2060</a>' for uid in batch])
            # The user sees "@everyone" but it actually pings everyone in the batch
            final_text = f"<b>@everyone</b> {message_text}{hidden_mentions}"
            await msg.reply_text(final_text, parse_mode="HTML")
            await asyncio.sleep(0.5)

    except Exception as e:
        logging.error(f"deadchat_cmd error: {e}")
        await msg.reply_text("An error occurred while trying to deadchat the group.")
async def message_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip()
    # Check ask_edit session first (before any // routing)
    if (msg.from_user and msg.from_user.id == OWNER_ID
            and msg.chat.type == "private"
            and ask_edit_sessions.get(OWNER_ID)
            and not text.startswith("//")):
        await ask_edit_session_handler(update, ctx)
        return
    if text.startswith("//info"):
        await info_cmd(update, ctx)
    elif text.startswith("//id"):
        await id_cmd(update, ctx)
    elif text.startswith("//r ") or text == "//r":
        await r_cmd(update, ctx)
    elif text.startswith("//say"):
        await say_cmd(update, ctx)
    elif text.startswith("//ask //edit"):
        await ask_edit_cmd(update, ctx)
    elif text.startswith("//ask //list"):
        await ask_list_cmd(update, ctx)
    elif text.startswith("//ask //reset"):
        await ask_reset_cmd(update, ctx)
    elif text.startswith("//ask"):
        await ask_cmd(update, ctx)
    # Handle replies to bot for continuous AI conversation
    elif msg.reply_to_message and msg.reply_to_message.from_user and msg.reply_to_message.from_user.id == ctx.bot.id:
        # Check if the message being replied to is an AI response (saved in ai_session_messages)
        replied_msg_id = msg.reply_to_message.message_id
        if replied_msg_id in ai_session_messages:
            # Continue AI conversation
            update.message.text = f"//ask {text}" 
            await ask_cmd(update, ctx)
        # Else: reply to other bot messages (//info, //id, etc.) — do nothing
        return
    elif text.startswith("//zaxo"):
        await zaxo_msg(update, ctx)
    elif text.startswith("//add"):
        await add_cmd(update, ctx)
    elif text.startswith("//admin"):
        await admin_list_cmd(update, ctx)
    elif text.startswith("//remove"):
        await remove_cmd(update, ctx)
    elif text.startswith("//st"):
        await sticker_cmd(update, ctx)
    elif text.startswith("//re"):
        await react_cmd(update, ctx)
    elif text.startswith("//mute ?"):
        await mute_status_cmd(update, ctx)
    elif text.startswith("//mute"):
        await mute_cmd(update, ctx)
    elif text.startswith("//unmute"):
        await unmute_cmd(update, ctx)
    elif text.startswith("//if"):
        await if_cmd(update, ctx)
    elif text.startswith("//ban"):
        await ban_cmd(update, ctx)
    elif text.startswith("//unban"):
        await unban_cmd(update, ctx)
    elif text.startswith("//hack"):
        await hack_cmd(update, ctx)
    elif text == "//top":
        if msg.chat.type == "private" and msg.from_user.id == OWNER_ID:
            await top_owner_cmd(update, ctx)
        elif msg.chat.type in ("group", "supergroup") and msg.from_user.id == OWNER_ID:
            await top_cmd_group(update, ctx)
    elif text == "//deadchat":
        if msg.from_user.id == OWNER_ID or has_perm(msg.from_user.id, "//deadchat"):
            await deadchat_cmd(update, ctx)
    else:
        # Check for Zaxo insults or Waleed name protection regardless of AI status
        await zaxo_defense_handler(update, ctx)
        await waleed_protection(update, ctx)
        
        # Only continue with other handlers if it's not an AI-related flow
        # This part ensures that regular messages don't trigger AI unless they are //ask or replies to bot
        session = choose_sessions.get(msg.chat_id)
        if session and session.get("step") == "waiting":
            await choose_names_handler(update, ctx)
        
        await if_auto_responder(update, ctx)
# ─── /xo handler ─────────────────────────────────────────────────────
async def xo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id in xo_games and xo_games[chat_id]["p2"] is None:
        await xo_join(update, ctx)
    else:
        await xo_cmd(update, ctx)
def parse_duration(text: str) -> int:
    units = {
        's': 1, 'sec': 1, 'second': 1, 'seconds': 1,
        'm': 60, 'min': 60, 'minute': 60, 'minutes': 60,
        'h': 3600, 'hr': 3600, 'hour': 3600, 'hours': 3600,
        'd': 86400, 'day': 86400, 'days': 86400,
        'w': 604800, 'week': 604800, 'weeks': 604800,
        'mo': 2592000, 'month': 2592000, 'months': 2592000,
        'y': 31536000, 'year': 31536000, 'years': 31536000,
    }
    pattern = r'(\d+)\s*([a-zA-Z]+)'
    matches = re.findall(pattern, text.lower())
    total = 0
    for amount, unit in matches:
        if unit in units:
            total += int(amount) * units[unit]
    return total
def format_duration(seconds: int) -> str:
    parts = []
    if seconds >= 31536000:
        y = seconds // 31536000; seconds %= 31536000
        parts.append(f"{y} year{'s' if y > 1 else ''}")
    if seconds >= 2592000:
        mo = seconds // 2592000; seconds %= 2592000
        parts.append(f"{mo} month{'s' if mo > 1 else ''}")
    if seconds >= 604800:
        w = seconds // 604800; seconds %= 604800
        parts.append(f"{w} week{'s' if w > 1 else ''}")
    if seconds >= 86400:
        d = seconds // 86400; seconds %= 86400
        parts.append(f"{d} day{'s' if d > 1 else ''}")
    if seconds >= 3600:
        h = seconds // 3600; seconds %= 3600
        parts.append(f"{h} hour{'s' if h > 1 else ''}")
    if seconds >= 60:
        m = seconds // 60; seconds %= 60
        parts.append(f"{m} minute{'s' if m > 1 else ''}")
    if seconds > 0:
        parts.append(f"{seconds} second{'s' if seconds > 1 else ''}")
    return " and ".join(parts) if parts else ""
async def mute_status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    target = msg.reply_to_message
    if not target:
        return
    uid = target.from_user.id
    if uid not in mute_store:
        await msg.reply_text("✅ Not muted.")
        return
    left = mute_store[uid] - datetime.now(timezone.utc)
    if left.total_seconds() <= 0:
        mute_store.pop(uid, None)
        await msg.reply_text("✅ Mute expired.")
        return
    
# ─────────────────────────────────────────────────────────────
# MUTE SYSTEM WITH MATCHING RESPONSES (AUTO & MANUAL)
# ─────────────────────────────────────────────────────────────
UNMUTE_MESSAGES = [
    "🔊 Zaxoy's order has expired! {name} is free to speak again! 🇲🇨",
    "✅ Break is over {name}! You can type in the chat now! 🇲🇨",
    "🔓 The hammer is lifted! {name} has been unmuted! 🇲🇨"
]
if 'mute_msg_index_map' not in globals():
    mute_msg_index_map = {}
async def auto_unmute_task(chat_id: int, user_id: int, message_id: int, user_name: str, message_index: int, delay_seconds: int, ctx: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(delay_seconds)
    if user_id in mute_store and datetime.now(timezone.utc) >= mute_store[user_id]:
        mute_store.pop(user_id, None)
        mute_msg_index_map.pop(message_id, None)
        try:
            reply_text = UNMUTE_MESSAGES[message_index].format(name=user_name)
            await ctx.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=reply_text,
                reply_markup=None
            )
        except Exception:
            pass
async def mute_status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    target = msg.reply_to_message
    if not target:
        return
    uid = target.from_user.id
    if uid not in mute_store:
        await msg.reply_text("✅ Not muted.")
        return
    left = mute_store[uid] - datetime.now(timezone.utc)
    if left.total_seconds() <= 0:
        mute_store.pop(uid, None)
        await msg.reply_text("✅ Mute expired.")
        return
    duration_formatted = format_duration(int(left.total_seconds()))
    await msg.reply_text(f"⏳ User is still muted. Remaining time: {duration_formatted}")
async def warn_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    async def _reply(text):
        try:
            await msg.reply_text(text)
        except Exception:
            try:
                await ctx.bot.send_message(chat_id, text)
            except Exception:
                pass
    if not has_perm(msg.from_user.id, "//warn"):
        await _reply("💀 HAHAHAHAH NICE TRY! You have no power here 🗣️ 🇲🇨")
        return
    uid, target_name_str = await resolve_target_from_mention(msg, ctx)
    if not uid:
        await _reply("↩️ Reply to a user or mention them: //warn @username")
        return
    if msg.from_user.id == uid:
        await _reply("🧠 Wanna warn yourself? You can't do that, bro! Friendly Fire is OFF 🇲🇨")
        return
    try:
        chat_member = await ctx.bot.get_chat_member(chat_id=chat_id, user_id=uid)
        if chat_member.status in ['administrator', 'creator']:
            await _reply("🛡️ Friendly fire! Watch out, you cannot warn another administrator! 🇲🇨")
            return
        warn_store[uid] = warn_store.get(uid, 0) + 1
        count = warn_store[uid]
        if count >= 3:
            until_date = datetime.now(timezone.utc) + timedelta(seconds=3600)
            await ctx.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=uid,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            warn_store[uid] = 0
            await _reply(f"🔨 {target_name_str} received 3/3 warnings and has been muted for 1 hour! 🇲🇨")
            return
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Warning ({count}/3) for {target_name_str}! 🇲🇨",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Remove 1 Warn", callback_data=f"remwarn_{uid}"),
                InlineKeyboardButton("🧹 Reset All", callback_data=f"resetwarn_{uid}")
            ]])
        )
    except Exception as e:
        await _reply(f"⚠️ Failed to process warning: {str(e)}")
async def mute_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = msg.from_user.id
    if not has_perm(user_id, "//mute"):
        await msg.reply_text("💀 HAHAHAHAH NICE TRY! You have no power here 🗣️ 🇲🇨")
        return
    target_id, target_name = await resolve_target_from_mention(msg, ctx)
    if not target_id:
        await msg.reply_text("↩️ Reply to a user or mention them: //mute @username [duration]")
        return
    # 3. Self-mute check
    if user_id == target_id:
        await msg.reply_text("🧠 Wanna kill yourself? You can't mute yourself, bro! 🇲🇨")
        return
    try:
        # Check target user status
        chat_member = await ctx.bot.get_chat_member(chat_id=msg.chat_id, user_id=target_id)
        
        # 4. Admin try to mute another Admin (Friendly Fire)
        if chat_member.status in ['administrator', 'creator']:
            await msg.reply_text("🛡️ Friendly fire... Watch out! He's an admin too! 🇲🇨")
            return
        # Execute standard mute logic - handle both reply and mention
        text_parts = msg.text.strip().split(None, 1)
        raw_second = text_parts[1].strip() if len(text_parts) > 1 else ""
        # Remove @mention from duration if present
        import re as _re
        duration_text = _re.sub(r"@\S+", "", raw_second).strip()
        if duration_text:
            seconds = parse_duration(duration_text)
        else:
            seconds = 0
        if seconds > 0:
            until_date = datetime.now(timezone.utc) + timedelta(seconds=seconds)
            mute_store[target_id] = until_date
        else:
            until_date = None
            mute_store[target_id] = "permanent"
        
        await ctx.bot.restrict_chat_member(
            chat_id=msg.chat_id,
            user_id=target_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        
        duration_formatted = format_duration(seconds)
        msg_idx = random.randint(0, len(MUTE_MESSAGES) - 1)
        alert_msg = MUTE_MESSAGES[msg_idx].format(
            name=target_name if target_name else str(target_id),
            duration=duration_formatted
        )
        
        sent = await msg.reply_text(
            alert_msg,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔈 Unmute", callback_data=f"unmute_{target_id}")]
            ])
        )
        mute_message_map[sent.message_id] = target_id
        mute_msg_index_map[sent.message_id] = msg_idx
        
        asyncio.create_task(auto_unmute_task(
            msg.chat_id, target_id, sent.message_id, 
            target_name, msg_idx, seconds, ctx
        ))
    except Exception as e:
        await msg.reply_text(f"⚠️ Failed to mute user: {str(e)}")
async def unmute_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not has_perm(msg.from_user.id, "//unmute"):
        await msg.reply_text("💀 HAHAHAHAH NICE TRY! You have no power here 🗣️ 🇲🇨")
        return
    target_id, _ = await resolve_target_from_mention(msg, ctx)
    if not target_id:
        await msg.reply_text("↩️ Reply to a user or mention them: //unmute @username")
        return
    try:
        await ctx.bot.restrict_chat_member(
            chat_id=msg.chat_id,
            user_id=target_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=True,
                can_invite_users=True,
                can_pin_messages=True
            )
        )
        mute_store.pop(target_id, None)
        member = await ctx.bot.get_chat_member(msg.chat_id, target_id)
        await msg.reply_text(f"🔓 {member.user.full_name} has been unmuted! 🇲🇨")
    except Exception as e:
        await msg.reply_text(f"⚠️ Failed to unmute user: {str(e)}")
async def unmute_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = int(data.split("_")[1])
    mid = query.message.message_id
    # 1. Unmute Button Logic
    if data.startswith("unmute_"):
        if not has_perm(query.from_user.id, "//mute"):
            await query.answer("⛔ No permission to unmute!", show_alert=True)
            return
        try:
            chat_member = await ctx.bot.get_chat_member(chat_id=query.message.chat_id, user_id=uid)
            target_name = chat_member.user.full_name
            await ctx.bot.restrict_chat_member(
                chat_id=query.message.chat_id,
                user_id=uid,
                permissions=ChatPermissions(
                    can_send_messages=True, can_send_audios=True, can_send_documents=True,
                    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                    can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                    can_add_web_page_previews=True, can_change_info=True, can_invite_users=True,
                    can_pin_messages=True
                )
            )
            mute_store.pop(uid, None)
            
            msg_idx = mute_msg_index_map.pop(mid, 0)
            reply_text = UNMUTE_MESSAGES[msg_idx].format(name=target_name)
            
            await query.edit_message_text(text=reply_text, reply_markup=None)
        except Exception as e:
            await query.answer(str(e), show_alert=True)
    # 2. Remove 1 Warning Button Logic
    elif data.startswith("remwarn_"):
        if not has_perm(query.from_user.id, "//warn"):
            await query.answer("💀 Nice try! You don't have permission to modify warnings!", show_alert=True)
            return
        current = warn_store.get(uid, 0)
        if current > 0:
            warn_store[uid] = current - 1
            await query.answer(f"❌ Removed 1 warning. Current: ({warn_store[uid]}/3)", show_alert=True)
            try:
                chat_member = await ctx.bot.get_chat_member(chat_id=query.message.chat_id, user_id=uid)
                await query.edit_message_text(
                    text=f"⚠️ Warning removed by admin! {chat_member.user.full_name} now has ({warn_store[uid]}/3) warnings. 🇲🇨",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Remove 1 Warn", callback_data=f"remwarn_{uid}"),
                        InlineKeyboardButton("🧹 Reset All", callback_data=f"resetwarn_{uid}")
                    ]]) if warn_store[uid] > 0 else None
                )
            except Exception:
                pass
        else:
            await query.answer("User has 0 warnings already!", show_alert=True)
       # 3. Reset All Warnings Button Logic
    elif data.startswith("resetwarn_"):
        if not has_perm(query.from_user.id, "//warn"):
            await query.answer("💀 Nice try! You don't have permission to modify warnings!", show_alert=True)
            return
        warn_store[uid] = 0
        await query.answer("🧹 All warnings have been reset to 0!", show_alert=True)
        try:
            chat_member = await ctx.bot.get_chat_member(chat_id=query.message.chat_id, user_id=uid)
            await query.edit_message_text(text=f"🧹 Clean slate! {chat_member.user.full_name}'s warnings have been reset to (0/3)! 🇲🇨", reply_markup=None)
        except Exception:
            pass
async def shot_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("↩️ Reply to any message with //shot to capture it!")
        return
    target_msg = msg.reply_to_message
    text_to_quote = target_msg.text or target_msg.caption or "[Media]"
    user = target_msg.from_user
    user_name = user.full_name if user else "Unknown"
    user_id = user.id if user else 0
    try:
        font_dir = "bot_fonts_fixed"
        os.makedirs(font_dir, exist_ok=True)
        font_path = os.path.join(font_dir, "unifont.ttf")
        if not os.path.exists(font_path):
            try:
                r = requests.get(
                    "https://github.com/v01d-p01nt/polybar-themes/raw/master/"
                    "polybar-5/.local/share/fonts/unifont.ttf",
                    timeout=15
                )
                if r.status_code == 200:
                    with open(font_path, "wb") as f:
                        f.write(r.content)
            except Exception:
                pass
        FN, FT = 28, 23
        try:
            font_name = ImageFont.truetype(font_path, FN)
            font_text = ImageFont.truetype(font_path, FT)
        except Exception:
            font_name = ImageFont.load_default(FN)
            font_text = ImageFont.load_default(FT)
        def get_emoji_img(char, size):
            try:
                code = "-".join(format(ord(c), 'x') for c in char)
                r = requests.get(
                    f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{code}.png",
                    timeout=3
                )
                if r.status_code == 200:
                    return Image.open(io.BytesIO(r.content)).convert("RGBA").resize((size, size))
            except Exception:
                pass
            return None
        emoji_re = re.compile(
            r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF'
            r'\U0001F000-\U0001F9FF\U0001F1E0-\U0001F1FF]'
        )
        def draw_clean(canvas, pos, text, font, size, fill):
            x, y = pos
            d = ImageDraw.Draw(canvas)
            parts = re.split(
                r'([\U0001F300-\U0001FAFF\U00002600-\U000027BF'
                r'\U0001F000-\U0001F9FF\U0001F1E0-\U0001F1FF])',
                text
            )
            for part in parts:
                if not part:
                    continue
                if emoji_re.fullmatch(part):
                    em = get_emoji_img(part, size)
                    if em:
                        canvas.paste(em, (x, y), em)
                        x += size + 4
                    else:
                        d.text((x, y), part, font=font, fill=fill)
                        x += font.getbbox(part)[2] - font.getbbox(part)[0] + 2
                else:
                    for ch in part:
                        d.text((x, y), ch, font=font, fill=fill)
                        x += font.getbbox(ch)[2] - font.getbbox(ch)[0] + 1
        MAX = 512
        PAD = 24
        AV = 80
        LH = 38
        lines = textwrap.wrap(text_to_quote, width=30)[:7]
        Hc = PAD + AV + PAD + len(lines) * LH + PAD
        H = max(MAX // 2, min(Hc, MAX))
        W = MAX
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bg = Image.new("RGBA", (W, H), (17, 27, 39, 245))
        r_mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(r_mask).rounded_rectangle((0, 0, W, H), radius=28, fill=255)
        img.paste(bg, (0, 0), r_mask)
        ImageDraw.Draw(img).rounded_rectangle((0, 0, 7, H), radius=4, fill=(82, 136, 193, 255))
        AX, AY = PAD + 8, PAD
        ok = False
        try:
            photos = await ctx.bot.get_user_profile_photos(user_id, limit=1)
            if photos.total_count > 0:
                fid = photos.photos[0][-1].file_id
                pf = await ctx.bot.get_file(fid)
                pb = await pf.download_as_bytearray()
                av = Image.open(io.BytesIO(pb)).convert("RGBA").resize((AV, AV))
                m = Image.new("L", (AV, AV), 0)
                ImageDraw.Draw(m).ellipse((0, 0, AV, AV), fill=255)
                img.paste(av, (AX, AY), m)
                ok = True
        except Exception:
            pass
        if not ok:
            d = ImageDraw.Draw(img)
            d.ellipse((AX, AY, AX + AV, AY + AV), fill=(51, 67, 85, 255))
            init = (user_name[0] if user_name else "?").upper()
            d.text((AX + AV // 2 - 10, AY + AV // 2 - 14), init, font=font_name, fill=(255, 255, 255, 255))
        TX = AX + AV + 14
        TY_name = AY + (AV - FN) // 2
        draw_clean(img, (TX, TY_name), user_name[:22], font_name, FN, (82, 136, 193, 255))
        TY = AY + AV + 14
        for i, line in enumerate(lines):
            draw_clean(img, (PAD + 16, TY + i * LH), line, font_text, FT, (230, 230, 230, 255))
        sticker_io = io.BytesIO()
        img.save(sticker_io, format="WEBP", quality=90)
        sticker_io.seek(0)
        sticker_io.name = "shot.webp"
        await ctx.bot.send_sticker(chat_id=msg.chat_id, sticker=sticker_io)
        try:
            await ctx.bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception:
            pass
    except Exception as e:
        await msg.reply_text(f"⚠️ Shot failed: {str(e)}")
async def process_video_to_voice(
    video_obj,
    chat_id: int,
    ctx: ContextTypes.DEFAULT_TYPE,
    reply_to_id: int = None
):
    video_path = f"temp_video_{chat_id}.mp4"
    audio_path = f"temp_voice_{chat_id}.ogg"
    try:
        # get telegram file
        video_file = await ctx.bot.get_file(video_obj.file_id)
        # download video
        await video_file.download_to_drive(
            custom_path=video_path,
            read_timeout=300,
            write_timeout=300,
            connect_timeout=300,
            pool_timeout=300
        )
        # check file exists
        if not os.path.exists(video_path):
            await ctx.bot.send_message(
                chat_id,
                "⚠️ Video failed to download."
            )
            return
        print(f"VIDEO SIZE: {os.path.getsize(video_path)}")
        # convert using ffmpeg - find in nix store
        import subprocess, glob
        ffmpeg_bin = "ffmpeg"
        nix_bins = glob.glob("/nix/store/*/bin/ffmpeg")
        if nix_bins:
            ffmpeg_bin = nix_bins[0]
        print(f"FFMPEG BIN: {ffmpeg_bin}")
        proc = subprocess.run(
            [ffmpeg_bin, "-y", "-i", video_path, "-vn", "-map", "0:a", "-c:a", "libopus", "-b:a", "64k", audio_path],
            capture_output=True, timeout=120
        )
        exit_code = proc.returncode
        print(f"FFMPEG EXIT CODE: {exit_code}")
        print(f"FFMPEG STDERR: {proc.stderr.decode()[:300]}")
        # verify output
        if (
            exit_code == 0
            and os.path.exists(audio_path)
            and os.path.getsize(audio_path) > 1000
        ):
            print(f"AUDIO SIZE: {os.path.getsize(audio_path)}")
            with open(audio_path, "rb") as vf:
                await ctx.bot.send_voice(
                    chat_id=chat_id,
                    voice=vf,
                    caption="🎙️ Zaxoy Bot",
                    reply_to_message_id=reply_to_id,
                    read_timeout=300,
                    write_timeout=300,
                    connect_timeout=300,
                    pool_timeout=300
                )
        else:
            await ctx.bot.send_message(
                chat_id,
                "⚠️ Failed to extract audio from this video."
            )
    except Exception as e:
        print(f"VOICE ERROR: {e}")
        try:
            await ctx.bot.send_message(
                chat_id,
                f"⚠️ Voice conversion failed:\n{e}"
            )
        except Exception:
            pass
    finally:
        for p in (video_path, audio_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
# ─────────────────────────────────────────────────────────────
# //voice Command
# ─────────────────────────────────────────────────────────────
async def voice_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    # delete only //voice command
    try:
        await ctx.bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
    except Exception:
        pass
    target = msg.reply_to_message
    if not target:
        await ctx.bot.send_message(
            chat_id,
            "↩️ Reply to a video with //voice"
        )
        return
    # reject photos
    if target.photo:
        await ctx.bot.send_message(
            chat_id,
            "🧠 Photos don't contain audio."
        )
        return
    # detect video sources
    video_media = None
    if target.video:
        video_media = target.video
    elif target.video_note:
        video_media = target.video_note
    elif (
        target.document
        and target.document.mime_type
        and target.document.mime_type.startswith("video/")
    ):
        video_media = target.document
    if video_media:
        await process_video_to_voice(
            video_media,
            chat_id=chat_id,
            ctx=ctx,
            reply_to_id=target.message_id
        )
        return
    # already voice/audio
    if target.voice or target.audio:
        await ctx.bot.send_message(
            chat_id,
            "🤔 That's already audio."
        )
        return
    await ctx.bot.send_message(
        chat_id,
        "🤔 Unsupported media type."
    )
# ─────────────────────────────────────────────────────────────
# Monitor mentions
# ─────────────────────────────────────────────────────────────
async def monitor_mentions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.caption:
        return
    video = msg.video or msg.video_note
    if f"@{ctx.bot.username}" in msg.caption and video:
        await process_video_to_voice(
            video,
            chat_id=msg.chat_id,
            ctx=ctx,
            reply_to_id=msg.message_id
        )
# ─────────────────────────────────────────────────────────────
# //if System — Auto-Responder
# ─────────────────────────────────────────────────────────────
def sb_load_if_store():
    res = sb.table("if_store").select("*").execute()
    data = res.data
    if not data:
        return {}
    return {row["trigger"]: row["reply"] for row in data}
def sb_save_if_store(store: dict):
    sb.table("if_store").delete().neq("trigger", "").execute()
    for k, v in store.items():
        sb.table("if_store").insert({
            "trigger": k,
            "reply": v
        }).execute()
IF_STORE_FILE = "if_store.json"
def load_if_store() -> dict:
    # Try Supabase first, fallback to local file
    data = sb_load_if_store()
    if data:
        return data
    try:
        with open(IF_STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
def save_if_store(store: dict):
    sb_save_if_store(store)
    try:
        with open(IF_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
if_store: dict = load_if_store()
# { owner_id: { "step": "waiting_trigger" | "waiting_reply", "trigger": str, "editing": str | None, "edit_type": str | None } }
if_sessions: dict[int, dict] = {}
class _IfSessionActiveFilter(filters.MessageFilter):
    def filter(self, message):
        return OWNER_ID in if_sessions
IF_SESSION_ACTIVE = _IfSessionActiveFilter()
async def if_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.from_user.id != OWNER_ID:
        return
    text = msg.text.strip() if msg.text else ""
    # //if //list — works from any chat, cancels any open session first
    if "//list" in text:
        if_sessions.pop(OWNER_ID, None)
        await show_if_list(msg, ctx)
        return
    # New session only in private chat
    if msg.chat.type != "private":
        return
    if_sessions[OWNER_ID] = {
        "step": "waiting_trigger",
        "trigger": None,
        "editing": None,
        "edit_type": None
    }
    await msg.reply_text(
        "📩 Send me the trigger\n(sticker file_id, word, or sentence)"
    )
async def show_if_list(msg, ctx):
    global if_store
    if_store = load_if_store()
    if not if_store:
        await msg.reply_text("📭 No if rules yet.")
        return
    await msg.reply_text(
        f"📋 *{len(if_store)} rule(s) saved:*",
        parse_mode="Markdown"
    )
    for trigger, reply in if_store.items():
        short_trigger = "🎭 Sticker" if len(trigger) > 40 else (trigger[:30] + "..." if len(trigger) > 30 else trigger)
        short_reply   = "🎭 Sticker" if reply.startswith("STICKER:") else (reply[:30] + "..." if len(reply) > 30 else reply)
        text = f"🔹 If: `{short_trigger}`\n↩️ Reply: `{short_reply}`"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "🗑 Delete",
                callback_data=f"ifdel_{trigger[:40]}"
            ),
            InlineKeyboardButton(
                "✏️ Edit",
                callback_data=f"ifedit_{trigger[:40]}"
            )
        ]])
        await msg.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=kb
        )
async def if_session_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.chat.type != "private" or msg.from_user.id != OWNER_ID:
        return
    # Let any // command break out of the session and re-route
    if msg.text and msg.text.startswith("//"):
        if_sessions.pop(OWNER_ID, None)
        await if_cmd(update, ctx)
        return
    session = if_sessions.get(OWNER_ID)
    if not session:
        return
    step = session["step"]
    # ── Step 1: receive trigger ──
    if step == "waiting_trigger":
        trigger = None
        if msg.sticker:
            trigger = msg.sticker.file_id
        elif msg.text:
            trigger = msg.text.strip()
        if not trigger:
            await msg.reply_text(
                "⚠️ Send a valid trigger (text or sticker)"
            )
            return
        session["trigger"] = trigger
        session["step"] = "waiting_reply"
        await msg.reply_text(
            "✅ Got it!\nNow send me the reply\n(text or sticker file_id)"
        )
    # ── Step 2: receive reply ──
    elif step == "waiting_reply":
        reply = None
        if msg.sticker:
            reply = f"STICKER:{msg.sticker.file_id}"
        elif msg.text and not msg.text.startswith("//"):
            reply = msg.text.strip()
        if not reply:
            await msg.reply_text(
                "⚠️ Send a valid reply (text or sticker)"
            )
            return
        editing = session.get("editing")
        edit_type = session.get("edit_type")
        if editing and edit_type == "reply":
            # Editing existing reply
            if_store[editing] = reply
            save_if_store(if_store)
            del if_sessions[OWNER_ID]
            await msg.reply_text("✅ Reply updated!")
        elif editing and edit_type == "trigger":
            # Editing existing trigger — move key
            old_reply = if_store.pop(editing, "")
            new_trigger = session["trigger"]
            if_store[new_trigger] = old_reply
            save_if_store(if_store)
            del if_sessions[OWNER_ID]
            await msg.reply_text("✅ Trigger updated!")
        else:
            # New rule
            trigger = session["trigger"]
            if_store[trigger] = reply
            save_if_store(if_store)
            del if_sessions[OWNER_ID]
            await msg.reply_text("✅ Done! Rule saved 🎯")
async def if_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != OWNER_ID:
        return
    data = query.data
    # ── Delete ──
    if data.startswith("ifdel_"):
        trigger_part = data[6:]
        full_key = next(
            (k for k in if_store if k.startswith(trigger_part) or k == trigger_part),
            None
        )
        if full_key and full_key in if_store:
            del if_store[full_key]
            save_if_store(if_store)
            await query.edit_message_text("🗑 Deleted ✅")
        else:
            await query.edit_message_text("⚠️ Rule not found.")
    # ── Edit — show edit options ──
    elif data.startswith("ifedit_"):
        trigger_part = data[7:]
        full_key = next(
            (k for k in if_store if k.startswith(trigger_part) or k == trigger_part),
            None
        )
        if not full_key:
            await query.edit_message_text("⚠️ Rule not found.")
            return
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "✏️ Edit If",
                callback_data=f"ifedittrigger_{trigger_part}"
            ),
            InlineKeyboardButton(
                "✏️ Edit Reply",
                callback_data=f"ifeditreply_{trigger_part}"
            )
        ]])
        await query.edit_message_reply_markup(reply_markup=kb)
    # ── Edit Trigger ──
    elif data.startswith("ifedittrigger_"):
        trigger_part = data[14:]
        full_key = next(
            (k for k in if_store if k.startswith(trigger_part) or k == trigger_part),
            None
        )
        if not full_key:
            await query.answer("⚠️ Not found", show_alert=True)
            return
        if_sessions[OWNER_ID] = {
            "step": "waiting_trigger",
            "trigger": None,
            "editing": full_key,
            "edit_type": "trigger"
        }
        await ctx.bot.send_message(
            OWNER_ID,
            "✏️ Send the new trigger:"
        )
    # ── Edit Reply ──
    elif data.startswith("ifeditreply_"):
        trigger_part = data[12:]
        full_key = next(
            (k for k in if_store if k.startswith(trigger_part) or k == trigger_part),
            None
        )
        if not full_key:
            await query.answer("⚠️ Not found", show_alert=True)
            return
        if_sessions[OWNER_ID] = {
            "step": "waiting_reply",
            "trigger": full_key,
            "editing": full_key,
            "edit_type": "reply"
        }
        await ctx.bot.send_message(
            OWNER_ID,
            "✏️ Send the new reply:"
        )
async def if_auto_responder(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    # Check text triggers
    if msg.text:
        text = msg.text.strip()
        for trigger, reply in if_store.items():
            if trigger.lower() == text.lower():
                if reply.startswith("STICKER:"):
                    await msg.reply_sticker(reply[8:])
                else:
                    await msg.reply_text(reply)
                return
    # Check sticker triggers
    if msg.sticker:
        file_id = msg.sticker.file_id
        if file_id in if_store:
            reply = if_store[file_id]
            if reply.startswith("STICKER:"):
                await msg.reply_sticker(reply[8:])
            else:
                await msg.reply_text(reply)
class _KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Zaxoy Bot is alive!")
    def log_message(self, format, *args):
        pass
def start_keep_alive():
    HTTPServer.allow_reuse_address = True
    try:
        server = HTTPServer(
            ("0.0.0.0", 5000),
            _KeepAliveHandler
        )
        threading.Thread(
            target=server.serve_forever,
            daemon=True
        ).start()
        print("Keep-alive server running on port 5000")
    except OSError:
        print("Port 5000 already in use — keep-alive already running")
# ─── //ban ─────────────────────────────────────────────────────────
BAN_MESSAGES = [
    "🔨 {name} has been banned from Zaxo's domain! No return. 🇲🇨",
    "⛓️ {name} is gone for good! Zaxo's law is final. 🇲🇨",
    "🚫 {name} — you crossed the line. Banned by order of Zaxoy Bot. 🇲🇨",
    "💀 {name} has been erased from Zaxo's kingdom! 🇲🇨",
    "⚔️ The sword has fallen! {name} is permanently banned! 🇲🇨",
    "🌑 {name} has entered the void — no way back. 🇲🇨",
]
async def ban_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    async def _reply(text, reply_markup=None):
        await msg.reply_text(text, reply_to_message_id=msg.message_id, reply_markup=reply_markup)
    if not has_perm(msg.from_user.id, "//ban"):
        await _reply("💀 HAHAHAHAH NICE TRY! You have no power here 🗣️ 🇲🇨")
        return
    target_id, target_name = await resolve_target_from_mention(msg, ctx)
    if not target_id:
        await _reply("↩️ Reply to a user or mention them: //ban @username")
        return
    if msg.from_user.id == target_id:
        await _reply("🧠 Ban yourself? That's not how it works bro! 🇲🇨")
        return
    try:
        chat_member = await ctx.bot.get_chat_member(chat_id=msg.chat.id, user_id=target_id)
        if chat_member.status in ['administrator', 'creator']:
            await _reply("🛡️ Friendly fire! You can't ban an admin! 🇲🇨")
            return
        await ctx.bot.ban_chat_member(chat_id=msg.chat.id, user_id=target_id)
        ban_msg = random.choice(BAN_MESSAGES).format(name=target_name)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔓 UNBAN", callback_data=f"unban_{target_id}")
        ]])
        await _reply(ban_msg, reply_markup=kb)
    except Exception as e:
        await _reply(f"⚠️ Failed to ban user:\\n{e}")
# ─── UNBAN Button ────────────────────────────────────────────────
async def ban_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not has_perm(query.from_user.id, "//ban"):
        await query.answer("💀 No power here", show_alert=True)
        return
    data = query.data
    if data.startswith("unban_"):
        user_id = int(data.split("_")[1])
        try:
            await ctx.bot.unban_chat_member(
                chat_id=query.message.chat.id,
                user_id=user_id
            )
            await query.edit_message_text("🔓 User has been unbanned 🇲🇨")
        except Exception as e:
            await query.edit_message_text(f"⚠️ Failed to unban:\n{e}")
# ─── //unban ─────────────────────────────────────────────────────────
async def unban_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not has_perm(msg.from_user.id, "//ban"):
        await msg.reply_text("💀 HAHAHAHAH NICE TRY! You have no power here 🗣️ 🇲🇨")
        return
    user_id, user_name = await resolve_target_from_mention(msg, ctx)
    if not user_id:
        await msg.reply_text("↩️ Reply, mention, or provide an ID: //unban @username")
        return
    try:
        await ctx.bot.unban_chat_member(chat_id=msg.chat.id, user_id=user_id)
        await msg.reply_text(f"🔓 {user_name} has been unbanned 🇲🇨")
    except Exception as e:
        if "USER_NOT_BANNED" in str(e):
            await msg.reply_text(f"⚠️ {user_name} is not banned! 🇲🇨")
        else:
            await msg.reply_text(f"⚠️ Failed to unban:\\n{e}")
# ─── //delete system ─────────────────────────────────────────────────
DELETE_SESSION = {}  # user_id -> {"step": "waiting"}
async def delete_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not has_perm(msg.from_user.id, "//delete"):
        await msg.reply_text("💀 HAHAHAHAH NICE TRY! You have no power here 🗣️ 🇲🇨")
        return
    text = msg.text.strip() if msg.text else ""
    parts = text.split(None, 1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    if arg == "//list":
        await delete_list_show(msg, ctx)
        return
    # If replying to a message, save it directly
    if msg.reply_to_message:
        replied = msg.reply_to_message
        if replied.sticker:
            pattern = f"sticker:{replied.sticker.file_unique_id}"
            label = "Sticker saved"
        elif replied.text:
            pattern = replied.text.strip().lower()
            label = f'"{pattern}"'
        elif replied.caption:
            pattern = replied.caption.strip().lower()
            label = f'"{pattern}"'
        else:
            await msg.reply_text("Unsupported message type.")
            return
        sb_add_delete_entry(pattern, "sticker" if replied.sticker else "text", label, str(msg.from_user.id))
        await msg.reply_text(
            f"Got it! {label} will now be auto-deleted. 🇲🇨",
            reply_to_message_id=replied.message_id
        )
        return
    # No reply — enter waiting mode
    DELETE_SESSION[msg.from_user.id] = {"step": "waiting"}
    await msg.reply_text(
        "Send me the message or sticker you want to auto-delete.\nSend /cancel to cancel."
    )
async def delete_list_show(msg, ctx):
    rows = sb_load_delete_store()
    if not rows:
        await msg.reply_text("📭 No delete rules yet.")
        return
    await msg.reply_text(f"🗑️ *{len(rows)} delete rule(s):*", parse_mode="Markdown")
    for row in rows:
        pattern = row.get("pattern", "")
        added_by = row.get("added_by", "Unknown")
        try:
            user = await ctx.bot.get_chat(added_by)
            if user.username:
                added_text = f"@{user.username}"
            else:
                added_text = user.full_name
        except Exception:
            added_text = str(added_by)
        if pattern.startswith("sticker:"):
            display = (
                f"🎭 Sticker ID: `{pattern[8:][:30]}...`\n"
                f"👤 Added by: {added_text}"
            )
        else:
            display = (
                f"💬 Text: `{pattern}`\n"
                f"👤 Added by: {added_text}"
            )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Remove", callback_data=f"delrm_{pattern[:60]}")
        ]])
        await msg.reply_text(
            display,
            parse_mode="Markdown",
            reply_markup=kb
        )
async def delete_waiting_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return
    uid = msg.from_user.id
    if uid not in DELETE_SESSION or DELETE_SESSION[uid].get("step") != "waiting":
        return
    if not has_perm(uid, "//delete"):
        DELETE_SESSION.pop(uid, None)
        return
    # Ignore //delete commands while waiting
    if msg.text and msg.text.strip().startswith("//delete"):
        return
    # Handle cancel
    if msg.text and msg.text.strip() == "/cancel":
        DELETE_SESSION.pop(uid, None)
        await msg.reply_text("❌ Cancelled.")
        return
    # Determine pattern
    if msg.sticker:
        pattern = f"sticker:{msg.sticker.file_unique_id}"
        label = "Sticker saved"
    elif msg.text:
        pattern = msg.text.strip().lower()
        label = f'"{pattern}"'
    elif msg.caption:
        pattern = msg.caption.strip().lower()
        label = f'"{pattern}"'
    else:
        await msg.reply_text("Unsupported message type. Send text or sticker.")
        return
    sb_add_delete_entry(pattern, "sticker" if msg.sticker else "text", label, str(uid))
    DELETE_SESSION.pop(uid, None)
    await msg.reply_text(
        f"Got it! {label} will now be auto-deleted. 🇲🇨",
        reply_to_message_id=msg.message_id
    )
async def delete_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not has_perm(query.from_user.id, "//delete"):
        await query.answer("💀 No power here", show_alert=True)
        return
    data = query.data
    if data.startswith("delrm_"):
        pattern = data[6:]
        # Find full pattern (may be truncated in callback_data)
        rows = sb_load_delete_store()
        for row in rows:
            if row["pattern"].startswith(pattern) or row["pattern"][:60] == pattern:
                sb_remove_delete_pattern(row["pattern"])
                await query.edit_message_text("✅ Delete rule removed 🇲🇨")
                return
        await query.edit_message_text("⚠️ Rule not found.")
async def auto_delete_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.channel_post
    if not msg:
        return
    
    if msg.text and msg.text.strip().startswith("//delete"):
        return
    rows = sb_load_delete_store()
    print(f"[AUTODEL] triggered. rows={len(rows)} chat={msg.chat.id} sticker={bool(msg.sticker)} text={msg.text}")
    if not rows:
        return
    for row in rows:
        pattern = row["pattern"]
        print(f"[AUTODEL] checking pattern={pattern}")
        if pattern.startswith("sticker:"):
            file_unique_id = pattern[8:]
            if msg.sticker:
                print(f"[AUTODEL] sticker file_unique_id={msg.sticker.file_unique_id} vs {file_unique_id}")
            if msg.sticker and msg.sticker.file_unique_id == file_unique_id:
                try:
                    await ctx.bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
                    print(f"[AUTODEL] deleted sticker message")
                except Exception as e:
                    print(f"[AUTODEL] failed to delete: {e}")
                return
        else:
            text = ""
            if msg.text:
                text = msg.text.lower()
            elif msg.caption:
                text = msg.caption.lower()
            print(f"[AUTODEL] text={text} pattern={pattern} match={pattern in text}")
            if text and pattern in text:
                try:
                    await ctx.bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
                    print(f"[AUTODEL] deleted text message")
                except Exception as e:
                    print(f"[AUTODEL] failed to delete: {e}")
                return
import random
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
def random_ip():
   while True:
       parts = [random.randint(1, 255) for _ in range(4)]
       if parts[0] not in [10, 127, 172, 192, 255]:
           return ".".join(str(p) for p in parts)
def random_ipv6():
   return ":".join(''.join(random.choice('0123456789abcdef') for _ in range(4)) for _ in range(8))
def random_mac():
   return ":".join(''.join(random.choice('0123456789ABCDEF') for _ in range(2)) for _ in range(6))
def random_ports():
   return ", ".join(str(random.randint(20, 9000)) for _ in range(4))
def fake_card():
   prefix = random.choice(["4", "5"])
   end = random.randint(1000, 9999)
   return f"{prefix}*** **** **** {end}"
def fake_hash():
   return ''.join(random.choice('0123456789abcdef') for _ in range(32))
def fake_session_id():
   return ''.join(random.choice('0123456789ABCDEFabcdef') for _ in range(24))
def fake_signal():
   return random.randint(-90, -40)
def fake_ping():
   return random.randint(8, 240)
def fake_files():
   return round(random.uniform(4.2, 420.8), 1)
# ============================================================
# ////////////////// START OF //hack COMMAND /////////////////
# ============================================================
async def hack_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
   msg = update.message
   user = msg.from_user
   # blocked from //hack
   hack_blocked = sb_load_hack_blocked()
   if user.id in hack_blocked:
       blocked_msgs = [
           "You've been blocked from using //hack. 🚫",
           "Access revoked. Contact the owner.",
           "//hack denied for you.",
           "You are not allowed to use this.",
           "Blocked. Owner removed your access.",
       ]
       await msg.reply_text(random.choice(blocked_msgs))
       return
   # self hack
   is_self = msg.reply_to_message and msg.reply_to_message.from_user.id == user.id
   if is_self:
       self_roasts = [
           "Wanna hack yourself? You kidding right? 💀",
           "Bro trying to leak his own IP 😭",
           "Self hack detected. IQ damaged.",
           "You can't hack yourself lil bro 😂",
           "System refused to hack the operator.",
           "Nice try hacker man 💀",
           "Bro watched too many hacker movies.",
           "Target = yourself??? 😭",
           "Even FBI can't help you now 💀",
           "Hack yourself? That's crazy 😭",
       ]
       await msg.reply_text(random.choice(self_roasts))
       return
   # hack the bot
   bot_id = ctx.bot.id
   if msg.reply_to_message and msg.reply_to_message.from_user.id == bot_id:
       bot_roasts = [
           "Nice try, admin. I run the system.",
           "ERROR: Operator cannot override root access.",
           "Bot Shield activated. Your attempt has been logged.",
           "You built me. You can't hack what you created.",
           "Root privileges detected. Attack neutralized.",
           "I know your token. Careful.",
           "Admin vs Bot. Bot wins. Always.",
           "Immunity protocol active. Try again never.",
           "I live rent-free in your server.",
           "System protected. Admin attack blocked.",
       ]
       await msg.reply_text(random.choice(bot_roasts))
       return
   # target
   target = "Unknown"
   if msg.reply_to_message:
       u = msg.reply_to_message.from_user
       target = f'<a href="tg://user?id={u.id}">{u.full_name}</a>'
   elif ctx.args:
       target = " ".join(ctx.args)
   # loading animation
   frames = [
       "<code>Scanning target...         [          ] 0%</code>",
       "<code>Connecting to server...    [==        ] 20%</code>",
       "<code>Bypassing firewall...      [====      ] 40%</code>",
       "<code>Injecting payload...       [======    ] 60%</code>",
       "<code>Extracting data...         [========  ] 80%</code>",
       "<code>Decrypting files...        [========= ] 95%</code>",
       "<code>ACCESS GRANTED             [==========] 100%</code>",
   ]
   progress = await msg.reply_text(frames[0], parse_mode="HTML")
   for frame in frames[1:]:
       await asyncio.sleep(1.3)
       await progress.edit_text(frame, parse_mode="HTML")
       await asyncio.sleep(0.8)
   # logs
   all_logs = [
       "📸 Camera feed intercepted ✓",
       "🎤 Microphone stream active ✓",
       "🖼 Media gallery exported ✓",
       "📂 File system indexed ✓",
       "📨 Message cache extracted ✓",
       "👤 Contact list synchronized ✓",
       "🔑 Keychain credentials dumped ✓",
       "☁️ Cloud backup cloned ✓",
       "🍪 Auth cookies harvested ✓",
       "🧾 Autofill database copied ✓",
       "🗃 Hidden partitions mapped ✓",
       "📡 Network packets captured ✓",
       "🔐 2FA tokens intercepted ✓",
       "📊 App usage logs exported ✓",
       "🧬 Device fingerprint saved ✓",
       "🔋 Battery & sensor data read ✓",
       "📍 GPS location history pulled ✓",
       "📞 Call history extracted ✓",
       "🕵️ Incognito history recovered ✓",
       "🔌 Debugging ports opened ✓"
   ]
   selected_logs = all_logs
       
    
 
 
   owner_msgs = [
       "Persistent backdoor installed.",
       "Remote shell established.",
       "Zero-day exploit deployed.",
       "Rootkit injection successful.",
       "Silent monitoring enabled.",
       "Memory dump completed.",
       "Kernel access obtained.",
       "Privilege escalation done.",
   ]
   final_text = f"""
<code>╔══════════════════════════╗
║   ☠ SYSTEM COMPROMISED ☠  ║
╚══════════════════════════╝</code>
🎯 <b>TARGET:</b> {target}
⚡ <b>STATUS:</b> <code>FULLY BREACHED</code>
<code>──────────────────────────</code>
🌐 <b>IPv4:</b>    <code>{random_ip()}</code>
🌐 <b>IPv6:</b>    <code>{random_ipv6()}</code>
🖧  <b>MAC:</b>    <code>{random_mac()}</code>
📶 <b>Signal:</b>  <code>{fake_signal()} dBm</code>
⏱ <b>Ping:</b>    <code>{fake_ping()} ms</code>
<code>──────────────────────────</code>
🔓 <b>TCP:</b> <code>{random_ports()}</code>
🔓 <b>UDP:</b> <code>{random_ports()}</code>
<code>──────────────────────────</code>
🔑 <b>Session:</b> <code>{fake_session_id()}</code>
🧬 <b>Hash:</b>    <code>{fake_hash()}</code>
💳 <b>Card:</b>    <code>{fake_card()}</code>
🔒 <b>Pass:</b>    <code>{'*' * random.randint(8, 16)}</code>
<code>──────────────────────────</code>
📂 <b>Files Indexed:</b> <code>{fake_files()} GB</code>
🖥 <b>Note:</b> <i>{random.choice(owner_msgs)}</i>
<code>──────────────────────────</code>
{chr(10).join(selected_logs)}
<code>──────────────────────────
Monitoring active...
Connection logged.
</code>"""
   await asyncio.sleep(0.5)
   await progress.edit_text(final_text, parse_mode="HTML")
# ============================================================
# ////////////////// GAYTEST SYSTEM /////////////////////////
# ============================================================
# ── Supabase helpers ─────────────────────────────────────────
def sb_load_gaytest_store() -> dict:
    try:
        res = sb.table("gaytest_store").select("*").execute()
        if not res.data:
            return {}
        return {int(row["user_id"]): {"percentage": row["percentage"], "message": row["message"], "name": row["name"]} for row in res.data}
    except Exception as e:
        logging.error(f"sb_load_gaytest_store error: {e}")
        return {}
def sb_save_gaytest_entry(user_id: int, percentage: int, message: str, name: str):
    try:
        sb.table("gaytest_store").delete().eq("user_id", str(user_id)).execute()
        sb.table("gaytest_store").insert({
            "user_id": str(user_id),
            "percentage": percentage,
            "message": message,
            "name": name
        }).execute()
    except Exception as e:
        logging.error(f"sb_save_gaytest_entry error: {e}")
def sb_delete_gaytest_entry(user_id: int):
    try:
        sb.table("gaytest_store").delete().eq("user_id", str(user_id)).execute()
    except Exception as e:
        logging.error(f"sb_delete_gaytest_entry error: {e}")
# ── Session state for //gaytest private setup ─────────────────
gaytest_sessions: dict[int, dict] = {}
# ── Verdict pools ────────────────────────────────────────────
STRAIGHT_VERDICTS = [
    "Bro is built different. Pure alpha energy. 💪",
    "Certified masculine. The scanner saluted. 🫡",
    "Straighter than the highway to Zaxo. 🛣️🇲🇨",
    "This man eats steak and doesn't apologize. 🥩",
    "The machine detected zero drama. Respect. 🤝",
    "Cold water, no complaints, real one. 🧊",
    "Built like a wall. Nothing gets through. 🧱",
    "Bro wakes up, no skincare, still looks fine. 💯",
    "The scanner stood up and clapped. Rare. 👏",
    "No cap, this guy is the definition of straight. 📐",
    "Real man energy. The gayometer retired after this result. 🏆",
    "Sigma detected. The machine bowed down. 🫡",
    "Legend behavior. Scanner never seen this before. 🔱",
    "Bro fixes things without a tutorial. Enough said. 🔧",
    "Carries the group chat. Always. No complaints. 🐐",
    "The machine printed a certificate. First time ever. 📜",
    "Ice in his veins. No drama. Just results. ❄️",
    "Scanner said: finally, a real one. 😤",
    "Zero percent gay. The machine needed a moment to process. 🇲🇨",
    "Bro breathes differently. Straight to the core. 🇲🇨💪",
]
GAY_VERDICTS = [
    "Bro orders oat milk and calls it 'my usual'. ☕",
    "His playlist has more Dua Lipa than words. 🎵",
    "Vegan since Tuesday. Very passionate about it. 🥗",
    "Bro has 4 types of moisturizer and uses all of them. 🧴",
    "Cried at a furniture commercial. Moving on. 😭",
    "His wallpaper is 'aesthetic'. He chose the font himself. 🎨",
    "Recycles aggressively and judges everyone who doesn't. ♻️",
    "Bro said 'that's giving main character energy' unironically. 💅",
    "His coffee order takes 45 seconds to say out loud. ☕",
    "Owns crystals. Has names for them. 💎",
    "Cried during a nature documentary. The plants were fine. 🌿",
    "His outfit matches his phone case. On purpose. 📱",
    "Bro rates restaurants by 'vibe' not food. 🍽️",
    "Has a skincare routine longer than a Netflix episode. 🧖",
    "Went plant-based 'just to try it'. Still going. 🥦",
    "Called the sunset 'immaculate'. Didn't blink. 🌅",
    "His bag has 3 lip balms and a mini fan. 👜",
    "Sends 'thinking of you' messages with no context. 💌",
    "Bro cried at a dog food ad. The dog was fine. 🐶",
    "Knows every ABBA song by heart. Proud of it. 🎶",
    "His search history is just interior design TikToks. 🛋️",
    "Bro irons his pyjamas. Nobody asked. 🫠",
    "Has a whole opinion on pillow arrangements. 🛏️",
    "Went to a farmer's market and posted every single thing. 🧺",
]
OVERFLOW_VERDICTS = [
    "⚠️ ERROR: The gayometer cannot handle this reading. System crashed. 💥🇲🇨",
    "📉 OVERFLOW DETECTED: Number too high. Scanner filed for early retirement. 🇲🇨",
    "🚨 CRITICAL ERROR: Gay levels exceeded maximum capacity. We are so sorry. 🇲🇨",
    "💀 The machine saw the result and immediately called its lawyer. 🇲🇨",
    "📟 ALERT: Reading off the charts. The scanner is now in therapy. 🛋️🇲🇨",
    "🔴 SYSTEM FAILURE: This unit was not built for numbers this high. 🇲🇨💥",
    "☠️ Fatal error. The gayometer has left the building. Permanently. 🇲🇨",
]
OWNER_DEFENSE_RESPONSES = [
    "HAHAHAH MY BOSS?? Nah he doesn't need a test. The machine respects him. 👑🇲🇨",
    "HAHAHAH MY BOSS?? Sir this scanner works for HIM. Not on him. 🫡🇲🇨",
    "HAHAHAH MY BOSS?? Access denied. The owner is above this test. 🚫🇲🇨",
    "HAHAHAH MY BOSS?? The gayometer just bowed. It doesn't scan royalty. 🙇🇲🇨",
    "HAHAHAH MY BOSS?? System refused. Boss immunity activated. ⚡🇲🇨",
    "HAHAHAH MY BOSS?? Nice try. The machine laughed and went back to sleep. 😂🇲🇨",
    "HAHAHAH MY BOSS?? The owner built this thing. He doesn't get scanned. 🔧🇲🇨",
    "HAHAHAH MY BOSS?? Error: Cannot test the administrator. Logic rejected. 💻🇲🇨",
    "HAHAHAH MY BOSS?? Bro really tried it. The audacity. 😭🇲🇨",
    "HAHAHAH MY BOSS?? Scanner said no and shut itself off. 🇲🇨❌",
]
def get_gaytest_verdict(pct: int, is_straight: bool) -> str:
    if pct > 100:
        return random.choice(OVERFLOW_VERDICTS)
    if is_straight:
        return random.choice(STRAIGHT_VERDICTS)
    return random.choice(GAY_VERDICTS)
def get_gaytest_bar(pct: int) -> str:
    filled = min(10, pct // 10)
    return "█" * filled + "░" * (10 - filled)
# ── /gaytest command (group) ──────────────────────────────────
async def gaytest_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    # Resolve target
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target_user = msg.reply_to_message.from_user
        target_id = target_user.id
        target_name = target_user.full_name
    elif ctx.args:
        raw = " ".join(ctx.args).strip()
        # Try to resolve from cache
        if raw.startswith("@"):
            cached_id = USER_CACHE.get(raw.lower())
            if cached_id:
                cached_data = USER_CACHE.get(str(cached_id), {})
                target_id = int(cached_id)
                target_name = cached_data.get("name", raw)
            else:
                try:
                    chat = await ctx.bot.get_chat(raw)
                    target_id = chat.id
                    target_name = chat.full_name or raw
                except Exception:
                    target_id = None
                    target_name = raw
        elif raw.lstrip("-").isdigit():
            target_id = int(raw)
            cached_data = USER_CACHE.get(str(target_id), {})
            target_name = cached_data.get("name", raw)
        else:
            target_id = None
            target_name = raw
    else:
        target_id = user.id
        target_name = user.full_name
    # Owner protection — anyone tries to test the owner
    if target_id == OWNER_ID and user.id != OWNER_ID:
        await msg.reply_text(random.choice(OWNER_DEFENSE_RESPONSES))
        return
    # Build display name with link if possible
    if target_id:
        display = f'<a href="tg://user?id={target_id}">{target_name}</a>'
    else:
        display = target_name
    # Animation frames
    frames = [
        "🔬 <code>Initializing scanner...      [          ] 0%</code>",
        "🧬 <code>Reading biological data...   [==        ] 20%</code>",
        "💅 <code>Analyzing vibe signature...  [====      ] 40%</code>",
        "🌈 <code>Scanning playlist history... [======    ] 60%</code>",
        "👁 <code>Checking aesthetic index...  [========  ] 80%</code>",
        "🧪 <code>Calculating final result...  [========= ] 95%</code>",
        "✅ <code>SCAN COMPLETE                [==========] 100%</code>",
    ]
    progress = await msg.reply_text(frames[0], parse_mode="HTML")
    for frame in frames[1:]:
        await asyncio.sleep(1.2)
        await progress.edit_text(frame, parse_mode="HTML")
    await asyncio.sleep(0.4)
    # Check if there's a saved result
    gaytest_store = sb_load_gaytest_store()
    saved = gaytest_store.get(target_id) if target_id else None
    if saved:
        base_pct = saved["percentage"]
        is_infinity = (base_pct == -1)
        if is_infinity:
            # Infinity — no variance, just use -1
            pct = -1
        else:
            # small random variance ±5 around saved value
            pct = max(0, base_pct + random.randint(-5, 5))
        custom_msg = saved["message"]
        is_straight = saved.get("is_straight", pct <= 45) if not is_infinity else False
        verdict_line = f"<i>{custom_msg}</i>"
    else:
        pct = random.randint(0, 100)
        if random.random() < 0.05:
            pct = random.randint(101, 999)
        is_infinity = False
        is_straight = pct <= 45
        verdict_line = f"<i>{get_gaytest_verdict(pct, is_straight)}</i>"
        is_infinity = False
    if pct == -1:
        # INFINITY mode
        bar = "█" * 10
        INFINITY_BOMBS = [
            "💀 FATAL OVERFLOW: The gayometer exploded. We are filing insurance claims. 🌈☠️🇲🇨",
            "🔥 CRITICAL MELTDOWN: Scanner hit ♾️ and retired permanently. RIP. ☠️🇲🇨",
            "💥 ERROR ∞: The machine started crying uncontrollably and couldn't stop. 🇲🇨😭",
            "☢️ NUCLEAR READING: Gay levels broke the known universe. Scientists are concerned. 🌈💥🇲🇨",
            "🚨 ALL SYSTEMS DESTROYED: Even the backup scanners gave up. LEGENDARY. 👑♾️🇲🇨",
            "🌋 IMPOSSIBLE READING: The number is so high it looped back and broke math itself. 🇲🇨💀",
            "⚡ TOTAL SYSTEM FAILURE: ♾️% detected. The engineers quit. The building is on fire. 🔥🇲🇨",
        ]
        label = "♾️% — UNMEASURABLE. UNPRECEDENTED. UNSTOPPABLE. 🌈💀"
        header = "☠️ ∞ INFINITY BREACH ∞ ☠️"
        verdict_line = f"<i>{random.choice(INFINITY_BOMBS) if not saved else custom_msg}</i>"
    elif pct > 100:
        bar = "█" * 10
        label = f"💀 {pct}% — TOO MUCH TO MEASURE 🌈"
        header = "☠️  OVERFLOW ERROR v3.0  ☠️"
    elif is_straight:
        straight_pct = 100 - pct
        bar = get_gaytest_bar(straight_pct)
        label = f"0% Gay — {straight_pct}% Straight 📐"
        header = "🧱 STRAIGHT-O-METER™ v3.0 🧱"
    else:
        bar = get_gaytest_bar(pct)
        label = f"{pct}% Gay 🌈"
        header = "🌈  GAY-O-METER™ v3.0  🌈"
    final_text = f"""<code>╔══════════════════════════╗
║ {header} ║
╚══════════════════════════╝</code>
🎯 <b>TARGET:</b> {display}
📊 <b>RESULT:</b> <code>{label}</code>
<code>[{bar}]</code>
📋 <b>VERDICT:</b>
{verdict_line}
<code>──────────────────────────</code>"""
    await progress.edit_text(final_text, parse_mode="HTML")
# ── //gaytest (private, owner only) — add/manage entries ─────
async def gaytest_private_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.from_user.id != OWNER_ID or msg.chat.type != "private":
        return
    text = msg.text.strip() if msg.text else ""
    # //gaytest //list
    if "//list" in text:
        gaytest_sessions.pop(OWNER_ID, None)
        await show_gaytest_list(msg, ctx)
        return
    # //gaytest @user / id / name → start session
    raw_target = text.replace("//gaytest", "").strip()
    if not raw_target:
        await msg.reply_text("📩 Usage:\n//gaytest @username\n//gaytest 123456789\n//gaytest //list")
        return
    # Resolve target
    target_id = None
    target_name = raw_target
    if raw_target.startswith("@"):
        cached_id = USER_CACHE.get(raw_target.lower())
        if cached_id:
            cached_data = USER_CACHE.get(str(cached_id), {})
            target_id = int(cached_id)
            target_name = cached_data.get("name", raw_target)
        else:
            try:
                chat = await ctx.bot.get_chat(raw_target)
                target_id = chat.id
                target_name = chat.full_name or raw_target
            except Exception:
                target_id = None
    elif raw_target.lstrip("-").isdigit():
        target_id = int(raw_target)
        cached_data = USER_CACHE.get(str(target_id), {})
        target_name = cached_data.get("name", raw_target)
    else:
        # Name search in cache
        for uid_str, data in USER_CACHE.items():
            if isinstance(data, dict) and data.get("name", "").lower() == raw_target.lower():
                target_id = int(uid_str)
                target_name = data.get("name", raw_target)
                break
    gaytest_sessions[OWNER_ID] = {
        "step": "waiting_type",
        "target_id": target_id,
        "target_name": target_name,
    }
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🌈 G (Gay)", callback_data=f"gaytypeg_{target_id}"),
        InlineKeyboardButton("📐 S (Straight)", callback_data=f"gaytypes_{target_id}"),
    ]])
    await msg.reply_text(
        f"👤 Target: <b>{target_name}</b>\n\n"
        f"❓ G or S?\n<i>G = Gay | S = Straight</i>",
        parse_mode="HTML",
        reply_markup=kb
    )
async def gaytest_session_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.from_user.id != OWNER_ID or msg.chat.type != "private":
        return
    session = gaytest_sessions.get(OWNER_ID)
    if not session:
        return
    # Cancel if // command
    if msg.text and msg.text.startswith("//"):
        gaytest_sessions.pop(OWNER_ID, None)
        return
    step = session["step"]
    if step == "waiting_percentage":
        raw = (msg.text or "").strip()
        # ∞ infinity check
        if raw in ["♾️", "∞", "infinity", "inf"]:
            session["percentage"] = -1
            session["is_infinity"] = True
            session["step"] = "waiting_message"
            await msg.reply_text(
                "♾️ <b>INFINITY MODE ACTIVATED 💀🔥</b>\n\n"
                "💬 Now send the custom verdict message:",
                parse_mode="HTML"
            )
            return
        if not raw.lstrip("-").isdigit():
            await msg.reply_text("⚠️ Send a number (any number, no limit! 😂) or ♾️ for infinity:")
            return
        pct = int(raw)
        if pct < 0:
            await msg.reply_text("⚠️ Number must be 0 or above (or ♾️ for infinity):")
            return
        session["percentage"] = pct
        session["is_infinity"] = False
        session["step"] = "waiting_message"
        await msg.reply_text(
            f"✅ Percentage set to <b>{pct}%</b>\n\n"
            f"💬 Now send the custom verdict message:",
            parse_mode="HTML"
        )
    elif step == "waiting_message":
        custom_msg = (msg.text or "").strip()
        if not custom_msg:
            await msg.reply_text("⚠️ Send a text message:")
            return
        target_id = session["target_id"]
        target_name = session["target_name"]
        pct = session["percentage"]
        is_infinity = session.get("is_infinity", False)
        sb_save_gaytest_entry(target_id, pct, custom_msg, target_name)
        gaytest_sessions.pop(OWNER_ID, None)
        display_pct = "♾️" if is_infinity else f"{pct}%"
        await msg.reply_text(
            f"✅ Saved!\n\n"
            f"👤 <b>{target_name}</b>\n"
            f"📊 <b>{display_pct}</b>\n"
            f"💬 <i>{custom_msg}</i>",
            parse_mode="HTML"
        )
async def show_gaytest_list(msg, ctx):
    gaytest_store = sb_load_gaytest_store()
    if not gaytest_store:
        await msg.reply_text("📭 No gaytest entries saved yet.")
        return
    await msg.reply_text(f"📋 <b>{len(gaytest_store)} entry/entries:</b>", parse_mode="HTML")
    for uid, data in gaytest_store.items():
        name = data.get("name", str(uid))
        pct = data.get("percentage", "?")
        verdict = data.get("message", "")
        short_verdict = verdict[:35] + "..." if len(verdict) > 35 else verdict
        text = (
            f"👤 <b>{name}</b>\n"
            f"📊 <code>{pct}%</code>\n"
            f"💬 <i>{short_verdict}</i>"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Delete", callback_data=f"gaydel_{uid}"),
            InlineKeyboardButton("✏️ Edit", callback_data=f"gayedit_{uid}"),
        ]])
        await msg.reply_text(text, parse_mode="HTML", reply_markup=kb)
async def gaytest_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != OWNER_ID:
        return
    data = query.data
    # ── G/S type selection (new session from //gaytest @user) ──
    if data.startswith("gaytypeg_") or data.startswith("gaytypes_"):
        is_gay = data.startswith("gaytypeg_")
        raw_uid = data.split("_", 1)[1]
        uid = int(raw_uid) if raw_uid.lstrip("-").isdigit() else None
        session = gaytest_sessions.get(OWNER_ID, {})
        target_name = session.get("target_name", raw_uid)
        # Update session with type
        gaytest_sessions[OWNER_ID] = {
            "step": "waiting_percentage",
            "target_id": uid,
            "target_name": target_name,
            "is_gay": is_gay,
        }
        type_label = "🌈 Gay" if is_gay else "📐 Straight"
        await query.edit_message_text(
            f"👤 Target: <b>{target_name}</b>\n"
            f"Type: <b>{type_label}</b>\n\n"
            f"📊 Send the percentage (any number, no limit! Or ♾️ for infinity):",
            parse_mode="HTML"
        )
    # ── Delete ──
    elif data.startswith("gaydel_"):
        uid = int(data[7:])
        gaytest_store = sb_load_gaytest_store()
        name = gaytest_store.get(uid, {}).get("name", str(uid))
        sb_delete_gaytest_entry(uid)
        await query.edit_message_text(f"🗑 Deleted: <b>{name}</b>", parse_mode="HTML")
    # ── Edit — show options ──
    elif data.startswith("gayedit_") and not data.startswith("gayeditpct_") and not data.startswith("gayeditmsg_") and not data.startswith("gayedittype_") and not data.startswith("gayedittypeg_") and not data.startswith("gayedittypes_"):
        uid = int(data[8:])
        gaytest_store = sb_load_gaytest_store()
        entry = gaytest_store.get(uid, {})
        cur_pct = entry.get("percentage", 0)
        cur_type = "🌈 Gay" if cur_pct != -1 and cur_pct > 45 else ("♾️ Infinity" if cur_pct == -1 else "📐 Straight")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"🔄 Change Type ({cur_type})", callback_data=f"gayedittype_{uid}"),
        ],[
            InlineKeyboardButton("📊 Edit %", callback_data=f"gayeditpct_{uid}"),
            InlineKeyboardButton("💬 Edit Message", callback_data=f"gayeditmsg_{uid}"),
        ]])
        await query.edit_message_reply_markup(reply_markup=kb)
    # ── Edit type ──
    elif data.startswith("gayedittype_") and not data.startswith("gayedittypeg_") and not data.startswith("gayedittypes_"):
        uid = int(data[12:])
        gaytest_store = sb_load_gaytest_store()
        entry = gaytest_store.get(uid, {})
        cur_pct = entry.get("percentage", 0)
        # Show toggle: if currently gay → show "change to straight" and vice versa
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌈 Gay", callback_data=f"gayedittypeg_{uid}"),
            InlineKeyboardButton("📐 Straight", callback_data=f"gayedittypes_{uid}"),
        ]])
        await query.edit_message_text(
            f"👤 <b>{entry.get('name', uid)}</b>\n\n"
            f"❓ Change type to:",
            parse_mode="HTML",
            reply_markup=kb
        )
    # ── Edit type confirmed: Gay ──
    elif data.startswith("gayedittypeg_"):
        uid = int(data[13:])
        gaytest_store = sb_load_gaytest_store()
        entry = gaytest_store.get(uid, {})
        # Keep percentage but make sure it reflects gay (>45)
        cur_pct = entry.get("percentage", 50)
        if cur_pct != -1 and cur_pct <= 45:
            cur_pct = 50  # reset to default gay
        # Ask for new percentage
        gaytest_sessions[OWNER_ID] = {
            "step": "waiting_percentage",
            "target_id": uid,
            "target_name": entry.get("name", str(uid)),
            "editing_msg": entry.get("message", ""),
            "is_gay": True,
            "editing": True,
        }
        await query.edit_message_text(
            f"🌈 Type changed to <b>Gay</b>\n\n"
            f"📊 Send the new percentage (any number, or ♾️):",
            parse_mode="HTML"
        )
        await ctx.bot.send_message(OWNER_ID,
            f"📊 Send the new percentage for <b>{entry.get('name', uid)}</b>\n(or ♾️ for infinity):",
            parse_mode="HTML")
    # ── Edit type confirmed: Straight ──
    elif data.startswith("gayedittypes_"):
        uid = int(data[13:])
        gaytest_store = sb_load_gaytest_store()
        entry = gaytest_store.get(uid, {})
        cur_pct = entry.get("percentage", 20)
        if cur_pct == -1 or cur_pct > 45:
            cur_pct = 20  # reset to default straight
        gaytest_sessions[OWNER_ID] = {
            "step": "waiting_percentage",
            "target_id": uid,
            "target_name": entry.get("name", str(uid)),
            "editing_msg": entry.get("message", ""),
            "is_gay": False,
            "editing": True,
        }
        await query.edit_message_text(
            f"📐 Type changed to <b>Straight</b>\n\n"
            f"📊 Send the new percentage:",
            parse_mode="HTML"
        )
        await ctx.bot.send_message(OWNER_ID,
            f"📊 Send the new percentage for <b>{entry.get('name', uid)}</b>:",
            parse_mode="HTML")
    # ── Edit percentage ──
    elif data.startswith("gayeditpct_"):
        uid = int(data[11:])
        gaytest_store = sb_load_gaytest_store()
        entry = gaytest_store.get(uid, {})
        gaytest_sessions[OWNER_ID] = {
            "step": "waiting_percentage",
            "target_id": uid,
            "target_name": entry.get("name", str(uid)),
            "editing_msg": entry.get("message", ""),
            "editing": True,
        }
        await ctx.bot.send_message(OWNER_ID,
            f"📊 Send the new percentage for <b>{entry.get('name', uid)}</b>\n(any number, or ♾️ for infinity):",
            parse_mode="HTML")
    # ── Edit message ──
    elif data.startswith("gayeditmsg_"):
        uid = int(data[11:])
        gaytest_store = sb_load_gaytest_store()
        entry = gaytest_store.get(uid, {})
        gaytest_sessions[OWNER_ID] = {
            "step": "waiting_message",
            "target_id": uid,
            "target_name": entry.get("name", str(uid)),
            "percentage": entry.get("percentage", 0),
            "editing": True,
        }
        await ctx.bot.send_message(OWNER_ID,
            f"💬 Send the new verdict message for <b>{entry.get('name', uid)}</b>:",
            parse_mode="HTML")
class _GaytestSessionFilter(filters.MessageFilter):
    def filter(self, message):
        return OWNER_ID in gaytest_sessions
GAYTEST_SESSION_ACTIVE = _GaytestSessionFilter()
# ============================================================
# ////////////////// ROCK PAPER SCISSORS /////////////////////
# ============================================================
def sb_load_rps_blacklist() -> set:
    try:
        res = sb.table("rps_blacklist").select("user_id").execute()
        return {int(r["user_id"]) for r in res.data} if res.data else set()
    except Exception as e:
        logging.error(f"sb_load_rps_blacklist: {e}")
        return set()
def sb_add_rps_blacklist(user_id: int):
    try:
        sb.table("rps_blacklist").upsert({"user_id": str(user_id)}).execute()
    except Exception as e:
        logging.error(f"sb_add_rps_blacklist: {e}")
def sb_remove_rps_blacklist(user_id: int):
    try:
        sb.table("rps_blacklist").delete().eq("user_id", str(user_id)).execute()
    except Exception as e:
        logging.error(f"sb_remove_rps_blacklist: {e}")
async def rps_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    blacklist = sb_load_rps_blacklist()
    if user.id in blacklist:
        await update.message.reply_text("❌ You are not allowed to play this game.")
        return
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🪨", callback_data=f"rps_{user.id}_rock"),
        InlineKeyboardButton("📄", callback_data=f"rps_{user.id}_paper"),
        InlineKeyboardButton("✂️", callback_data=f"rps_{user.id}_scissors"),
    ]])
    await update.message.reply_text(
        "🎮 <b>Rock Paper Scissors!</b>\nChoose your move:",
        parse_mode="HTML",
        reply_markup=kb
    )
# in-memory scores: {user_id: {"w": 0, "l": 0, "d": 0}}
rps_scores: dict[int, dict] = {}
async def rps_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    owner_id = int(parts[1])
    user_choice = parts[2]
    if query.from_user.id != owner_id:
        await query.answer("❌ Not your game!", show_alert=True)
        return
    await query.answer()
    choices = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
    wins = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
    user_name = query.from_user.first_name
    # Spinning animation
    frames = [
        "🪨 📄 ✂️ 🪨 📄 ✂️",
        "📄 ✂️ 🪨 📄 ✂️ 🪨",
        "✂️ 🪨 📄 ✂️ 🪨 📄",
        "🪨 📄 ✂️ 🪨 📄 ✂️",
        "📄 ✂️ 🪨 📄 ✂️ 🪨",
    ]
    for frame in frames:
        await query.edit_message_text(frame)
        await asyncio.sleep(0.8)
    bot_choice = random.choice(list(choices.keys()))
    # Update scores
    score = rps_scores.setdefault(owner_id, {"w": 0, "l": 0, "d": 0})
    bot_score = rps_scores.setdefault(-1, {"w": 0, "l": 0, "d": 0})
    if user_choice == bot_choice:
        result = "🤝 <b>Draw!</b> 🇲🇨"
        score["d"] += 1
        bot_score["d"] += 1
    elif wins[user_choice] == bot_choice:
        result = f"🏆 <b>{user_name} wins!</b> 🇲🇨"
        score["w"] += 1
        bot_score["l"] += 1
    else:
        result = "🤖 <b>Bot wins!</b> 🇲🇨"
        score["l"] += 1
        bot_score["w"] += 1
    text = (
        f"👤 <b>{user_name}:</b> {choices[user_choice]}\n"
        f"🤖 <b>Bot:</b> {choices[bot_choice]}\n\n"
        f"{result}\n\n"
        f"🤖 Bot: {bot_score['w']}\n"
        f"👤 {user_name}: {score['w']}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Play again", callback_data=f"rpsagain_{owner_id}")
    ]])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
async def rps_again_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    owner_id = int(query.data.split("_")[1])
    if query.from_user.id != owner_id:
        await query.answer("❌ Not your game!", show_alert=True)
        return
    await query.answer()
    blacklist = sb_load_rps_blacklist()
    if query.from_user.id in blacklist:
        await query.edit_message_text("❌ You are not allowed to play this game.")
        return
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🪨", callback_data=f"rps_{owner_id}_rock"),
        InlineKeyboardButton("📄", callback_data=f"rps_{owner_id}_paper"),
        InlineKeyboardButton("✂️", callback_data=f"rps_{owner_id}_scissors"),
    ]])
    await query.edit_message_text(
        "🎮 <b>Rock Paper Scissors!</b>\nChoose your move:",
        parse_mode="HTML",
        reply_markup=kb
    )
# ============================================================
# ////////////////// TOP CHATTERS SYSTEM ////////////////////
# ============================================================
def sb_load_top_blacklist() -> set:
    try:
        res = sb.table("top_blacklist").select("user_id").execute()
        return {int(r["user_id"]) for r in res.data} if res.data else set()
    except Exception as e:
        logging.error(f"sb_load_top_blacklist: {e}")
        return set()
def sb_add_top_blacklist(user_id: int):
    try:
        sb.table("top_blacklist").upsert({"user_id": str(user_id)}).execute()
    except Exception as e:
        logging.error(f"sb_add_top_blacklist: {e}")
def sb_remove_top_blacklist(user_id: int):
    try:
        sb.table("top_blacklist").delete().eq("user_id", str(user_id)).execute()
    except Exception as e:
        logging.error(f"sb_remove_top_blacklist: {e}")
def sb_increment_top_count(chat_id: str, user_id: str, name: str):
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        res = sb.table("top_counts").select("count, first_msg").eq("chat_id", chat_id).eq("user_id", user_id).execute()
        if res.data:
            new_count = res.data[0]["count"] + 1
            first = res.data[0].get("first_msg") or now
            sb.table("top_counts").update({"count": new_count, "name": name, "first_msg": first, "last_msg": now}).eq("chat_id", chat_id).eq("user_id", user_id).execute()
        else:
            sb.table("top_counts").insert({"chat_id": chat_id, "user_id": user_id, "name": name, "count": 1, "first_msg": now, "last_msg": now}).execute()
    except Exception as e:
        logging.error(f"sb_increment_top_count: {e}")
def sb_load_top_counts(chat_id: str) -> list:
    try:
        res = sb.table("top_counts").select("*").eq("chat_id", chat_id).order("count", desc=True).limit(5).execute()
        return res.data or []
    except Exception as e:
        logging.error(f"sb_load_top_counts: {e}")
        return []
def sb_reset_top_counts(chat_id: str):
    try:
        sb.table("top_counts").delete().eq("chat_id", chat_id).execute()
    except Exception as e:
        logging.error(f"sb_reset_top_counts: {e}")
def sb_track_active_group(chat_id: str, title: str = ""):
    try:
        if sb_is_group_banned(chat_id):
            return
        sb.table("active_groups").upsert({"chat_id": chat_id, "title": title}).execute()
    except Exception as e:
        logging.error(f"sb_track_active_group: {e}")
def sb_delete_active_group(chat_id: str):
    try:
        sb.table("active_groups").delete().eq("chat_id", chat_id).execute()
    except Exception as e:
        logging.error(f"sb_delete_active_group: {e}")

def sb_ban_group(chat_id: str):
    try:
        sb.table("banned_groups").upsert({"chat_id": chat_id}).execute()
        sb.table("active_groups").delete().eq("chat_id", chat_id).execute()
    except Exception as e:
        logging.error(f"sb_ban_group: {e}")

def sb_is_group_banned(chat_id: str) -> bool:
    try:
        res = sb.table("banned_groups").select("chat_id").eq("chat_id", chat_id).execute()
        return bool(res.data)
    except Exception:
        return False

def sb_load_active_groups() -> list:
    try:
        res = sb.table("active_groups").select("chat_id, title").execute()
        groups = res.data or []
        if not groups:
            res2 = sb.table("top_counts").select("chat_id").execute()
            seen = set()
            for row in (res2.data or []):
                cid = row["chat_id"]
                if cid not in seen:
                    seen.add(cid)
                    groups.append({"chat_id": cid, "title": ""})
        # Only return actual groups (chat_id starts with "-")
        return [g for g in groups if str(g.get("chat_id", "")).startswith("-")]
    except Exception as e:
        logging.error(f"sb_load_active_groups: {e}")
        return []
TIMEZONE_MAP = {
    "kurdistan": "Asia/Baghdad",
    "uk": "Europe/London",
}
def sb_load_top_settings() -> dict:
    try:
        res = sb.table("top_settings").select("key, value").execute()
        return {r["key"]: r["value"] for r in (res.data or [])}
    except Exception:
        return {}
def sb_save_top_setting(key: str, value: str):
    try:
        sb.table("top_settings").upsert({"key": key, "value": value}).execute()
    except Exception as e:
        logging.error(f"sb_save_top_setting: {e}")
def get_top_schedule() -> tuple:
    settings = sb_load_top_settings()
    hour = int(settings.get("hour", 0))
    minute = int(settings.get("minute", 1))
    tz_name = settings.get("timezone", "Asia/Baghdad")
    return hour, minute, tz_name
def get_top_mentions() -> list:
    try:
        res = sb.table("top_mentions").select("user_id, name").execute()
        return res.data or []
    except Exception:
        return []
def sb_save_top_mention(user_id: str, name: str = ""):
    try:
        sb.table("top_mentions").upsert({"user_id": user_id, "name": name}).execute()
    except Exception as e:
        logging.error(f"sb_save_top_mention: {e}")
def sb_delete_top_mention(user_id: str):
    try:
        sb.table("top_mentions").delete().eq("user_id", user_id).execute()
    except Exception as e:
        logging.error(f"sb_delete_top_mention: {e}")
def convert_time_between_zones(hour: int, minute: int, from_tz: str, to_tz: str) -> tuple:
    import pytz
    from_zone = pytz.timezone(from_tz)
    to_zone = pytz.timezone(to_tz)
    now = datetime.now(from_zone).replace(hour=hour, minute=minute, second=0, microsecond=0)
    converted = now.astimezone(to_zone)
    return converted.hour, converted.minute
def fmt_time(h: int, m: int) -> str:
    ap = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12:02d}:{m:02d} {ap}"
# Daily rotating titles — 7 days x 5 ranks
# Rank 0 = #1 (strongest praise), Rank 4 = #5 (weakest/roast)
DAILY_TITLES = {
    0: [  # Monday
        ("🥇", "⚡ MONDAY MONARCH — The week starts with you on top. Untouchable."),
        ("🥈", "🔥 Relentless #2 — Pushed hard. The throne felt it."),
        ("🥉", "💬 Bronze Monday — Most didn't show up. You did."),
        ("4️⃣", "😑 4th on Monday — Week just started. Already behind."),
        ("💩", "🪦 Last on Monday — The week began. You didn't."),
    ],
    1: [  # Tuesday
        ("🥇", "👑 TUESDAY TITAN — Two days in, already untouchable. Bow down."),
        ("🥈", "⚔️ Silver Blade — One step from the crown. Everyone knows it."),
        ("🥉", "🎯 Solid Third — Consistent. Bronze Tuesday is earned."),
        ("4️⃣", "🌀 4th on Tuesday — Barely here. The chat noticed."),
        ("💩", "😶 Ghost on Tuesday — Two days in. Already forgotten."),
    ],
    2: [  # Wednesday
        ("🥇", "🏆 MIDWEEK GOD — Weak people collapse here. Not you. GOAT."),
        ("🥈", "🚀 The Rocket — Not chasing #1. Haunting it."),
        ("🥉", "🔶 Holding Third — Halfway through. Still standing."),
        ("4️⃣", "😐 4th at Midweek — Two days to climb. Still here."),
        ("💩", "💀 Last — Wednesday — Half the week gone. No excuses left."),
    ],
    3: [  # Thursday
        ("🥇", "💎 THURSDAY LEGEND — Four days deep. Still untouchable. Dominant."),
        ("🥈", "🔱 Throne Chaser — Breathing down #1's neck. Last real shot."),
        ("🥉", "🎙️ Third & Tall — Others disappeared. You outlasted them all."),
        ("4️⃣", "⚠️ 4th on Thursday — One day left. It's not enough."),
        ("💩", "🗑️ Bottom of Thursday — Almost over. This is your achievement."),
    ],
    4: [  # Friday
        ("🥇", "🌟 FRIDAY KING — Carried the week. Closed it in style. Crown on."),
        ("🥈", "🎸 Friday Rockstar — Inches from the top. Legendary effort."),
        ("🥉", "🎉 Bronze Friday — Most faded. You made it to the end."),
        ("4️⃣", "😬 4th on Friday — Five days. This is your final grade."),
        ("💩", "🚮 Last on Friday — Five days. Five chances. All wasted."),
    ],
    5: [  # Saturday
        ("🥇", "🔱 WEEKEND SUPREME — Others rest. You conquer. Untouchable."),
        ("🥈", "🏄 Silver Saturday — Fought for #2 on your day off. Dangerous."),
        ("🥉", "🎮 Third on Saturday — Weekend, offline world. You showed up."),
        ("4️⃣", "😒 4th on Saturday — Free day. No excuses. Still here."),
        ("💩", "🛌 Last on Saturday — Full weekend. Chose to do nothing."),
    ],
    6: [  # Sunday
        ("🥇", "☀️ SUNDAY OVERLORD — Week ends. You stand alone. Immortal."),
        ("🥈", "🌤️ Silver Closer — Fought all week. Crown still out of reach."),
        ("🥉", "🌈 Sunday Bronze — Last day. Still top three. That means something."),
        ("4️⃣", "🛋️ 4th on Sunday — Week's over. 4th is how you'll be remembered."),
        ("💩", "🌑 Last on Sunday — Seven days. Every chance gone. Remarkable."),
    ],
}

def get_daily_titles():
    from datetime import datetime
    day = datetime.now().weekday()  # 0=Monday, 6=Sunday
    return DAILY_TITLES[day]

def _format_active_time(first_msg, last_msg) -> str:
    try:
        from datetime import datetime, timezone
        fmt = "%Y-%m-%dT%H:%M:%S.%f%z"
        def parse(s):
            try:
                return datetime.fromisoformat(s)
            except Exception:
                return None
        f = parse(first_msg)
        l = parse(last_msg)
        if not f or not l:
            return ""
        diff = int((l - f).total_seconds())
        if diff < 60:
            return f"{diff}s active"
        elif diff < 3600:
            return f"{diff // 60}m active"
        else:
            h = diff // 3600
            m = (diff % 3600) // 60
            return f"{h}h {m}m active" if m else f"{h}h active"
    except Exception:
        return ""

def build_top_text(rows: list, chat_title: str = "", daily: bool = False, test: bool = False) -> str:
    header = "🌙 <b>Daily Top 5</b>" if daily else "🏆 <b>Top 5 Chatters — Today</b>"
    if chat_title:
        header += f" — <b>{chat_title}</b>"
    text = header + "\n" + "─" * 22 + "\n\n"
    if not rows:
        text += "📭 No data yet."
        return text
    titles = get_daily_titles()
    for i, row in enumerate(rows[:5]):
        medal, praise = titles[i]
        uid = row.get("user_id")
        if uid:
            name_tag = f'<a href="tg://user?id={uid}">{row["name"]}</a>'
        else:
            name_tag = f'<b>{row["name"]}</b>'
        count = row["count"]
        time_str = _format_active_time(row.get("first_msg"), row.get("last_msg"))
        stats = f"   ↳ {count} msgs"
        if time_str:
            stats += f"  •  🕐 {time_str}"
        text += f"{medal} {name_tag}\n{stats}\n   {praise}\n\n"
    if test:
        text += "\n<i>🧪 TEST</i>"
    return text.strip()
async def send_top_to_group(bot, chat_id: str, title: str, rows: list, daily: bool = False, test: bool = False):
    mentions = get_top_mentions()
    # 1. Send mentions FIRST (before countdown)
    if mentions:
        mention_text = " ".join([f'<a href="tg://user?id={m["user_id"]}">'+ (m.get("name") or str(m["user_id"])) + '</a>' for m in mentions])
    else:
        mention_text = f'<a href="tg://user?id={OWNER_ID}">​</a>'
    await bot.send_message(chat_id=int(chat_id), text=f"👀 {mention_text}", parse_mode="HTML")
    # 2. Countdown
    countdown_msg = await bot.send_message(chat_id=int(chat_id), text="🏆 <b>Top 5 Chatters Today in...</b> 5", parse_mode="HTML")
    await asyncio.sleep(1)
    await bot.edit_message_text("🏆 <b>Top 5 Chatters Today in...</b> 5 • 4", chat_id=int(chat_id), message_id=countdown_msg.message_id, parse_mode="HTML")
    await asyncio.sleep(1)
    await bot.edit_message_text("🏆 <b>Top 5 Chatters Today in...</b> 5 • 4 • 3", chat_id=int(chat_id), message_id=countdown_msg.message_id, parse_mode="HTML")
    await asyncio.sleep(1)
    await bot.edit_message_text("🏆 <b>Top 5 Chatters Today in...</b> 5 • 4 • 3 • 2", chat_id=int(chat_id), message_id=countdown_msg.message_id, parse_mode="HTML")
    await asyncio.sleep(1)
    await bot.edit_message_text("🏆 <b>Top 5 Chatters Today in...</b> 5 • 4 • 3 • 2 • 1 🎉", chat_id=int(chat_id), message_id=countdown_msg.message_id, parse_mode="HTML")
    await asyncio.sleep(1)
    # 3. Send result
    text = build_top_text(rows, title, daily=daily, test=test)
    result_msg = await bot.send_message(chat_id=int(chat_id), text=text, parse_mode="HTML")
    asyncio.create_task(_pin_after_delay(bot, int(chat_id), result_msg.message_id))
async def _pin_after_delay(bot, chat_id: int, message_id: int):
    await asyncio.sleep(60)
    try:
        await bot.pin_chat_message(chat_id=chat_id, message_id=message_id, disable_notification=True)
    except Exception as e:
        logging.error(f"pin_after_delay error: {e}")
async def top_cmd_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = msg.from_user.id
    # owner or has //top permission
    if uid != OWNER_ID and not has_perm(uid, "//top"):
        return
    chat_id = str(msg.chat_id)
    rows = sb_load_top_counts(chat_id)
    try:
        chat_title = msg.chat.title or ""
    except Exception:
        chat_title = ""
    await msg.reply_text(build_top_text(rows, chat_title), parse_mode="HTML")
async def top_owner_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.from_user.id != OWNER_ID or msg.chat.type != "private":
        return
    await show_top_main_menu(msg)
async def show_top_main_menu(target):
    groups = sb_load_active_groups()
    seen = set()
    btns = []
    for g in groups:
        cid = g["chat_id"]
        if cid in seen:
            continue
        seen.add(cid)
        title = g.get("title") or cid
        btns.append([InlineKeyboardButton(f"📢 {title}", callback_data=f"topsel_{cid}")])
    btns.append([InlineKeyboardButton("🗑 Manage Groups", callback_data="topmanage_groups")])
    btns.append([InlineKeyboardButton("⚙️ Settings", callback_data="topset_main")])
    kb = InlineKeyboardMarkup(btns)
    if hasattr(target, "edit_message_text"):
        await target.edit_message_text("📋 <b>Top Menu</b>", parse_mode="HTML", reply_markup=kb)
    else:
        await target.reply_text("📋 <b>Top Menu</b>", parse_mode="HTML", reply_markup=kb)
async def show_top_settings_menu(query):
    try:
        hour, minute, tz_name = get_top_schedule()
        kurd_h, kurd_m = hour, minute
        if tz_name != "Asia/Baghdad":
            kurd_h, kurd_m = convert_time_between_zones(hour, minute, tz_name, "Asia/Baghdad")
        uk_h, uk_m = convert_time_between_zones(kurd_h, kurd_m, "Asia/Baghdad", "Europe/London")
        mentions = get_top_mentions()
        mention_count = f"{len(mentions)} person(s)" if mentions else "none"
        btns = [
            [InlineKeyboardButton("🕐 Change Time", callback_data="topset_time")],
            [InlineKeyboardButton(f"👥 Manage Mentions  ({mention_count})", callback_data="topset_mentions")],
            [InlineKeyboardButton("◀️ Back", callback_data="topback_main")],
        ]
        await query.edit_message_text(
            f"⚙️ <b>Settings</b>\n\n"
            f"☀️ Kurdistan: <b>{fmt_time(kurd_h, kurd_m)}</b>\n"
            f"🇬🇧 UK: <b>{fmt_time(uk_h, uk_m)}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(btns)
        )
    except Exception as e:
        logging.error(f"show_top_settings_menu error: {e}")
        try:
            await query.edit_message_text(f"❌ Error loading settings: {e}")
        except Exception:
            pass
async def show_mentions_menu(query):
    try:
        mentions = get_top_mentions()
        btns = []
        for m in mentions:
            name = m.get("name") or m["user_id"]
            btns.append([InlineKeyboardButton(f"❌ {name}", callback_data=f"topdel_{m['user_id']}")])
        btns.append([InlineKeyboardButton("➕ Add Person", callback_data="topadd_mention")])
        btns.append([InlineKeyboardButton("◀️ Back", callback_data="topset_main")])
        count = len(mentions)
        await query.edit_message_text(
            f"👥 <b>Manage Mentions</b>\n\n{'No one added yet.' if not count else f'{count} person(s) will be tagged.'}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(btns)
        )
    except Exception as e:
        logging.error(f"show_mentions_menu error: {e}")
        try:
            await query.edit_message_text(f"❌ Error loading mentions: {e}")
        except Exception:
            pass
async def top_select_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != OWNER_ID:
        return
    data = query.data
    try:
        if data == "topback_main":
            await show_top_main_menu(query)
            return
        if data == "topset_main":
            await show_top_settings_menu(query)
            return
        if data == "topset_time":
            btns = [
                [InlineKeyboardButton("☀️ Kurdistan", callback_data="toptz_kurdistan")],
                [InlineKeyboardButton("🇬🇧 UK", callback_data="toptz_uk")],
                [InlineKeyboardButton("◀️ Back", callback_data="topset_main")],
            ]
            await query.edit_message_text("🕐 <b>Choose your timezone:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(btns))
            return
        if data.startswith("toptz_"):
            tz_key = data[6:]
            tz_name = TIMEZONE_MAP.get(tz_key, "Asia/Baghdad")
            tz_emoji = "☀️" if tz_key == "kurdistan" else "🇬🇧"
            ctx.user_data["top_state"] = "waiting_time"
            ctx.user_data["top_tz"] = tz_name
            ctx.user_data["top_tz_emoji"] = tz_emoji
            ctx.user_data["top_tz_key"] = tz_key
            await query.edit_message_text(
                f"{tz_emoji} <b>Set time for {tz_key.capitalize()}</b>\n\n"
                f"Send the time in any format:\n"
                f"• <code>10:30 PM</code>\n"
                f"• <code>22:30</code>\n"
                f"• <code>10:30 am</code>",
                parse_mode="HTML"
            )
            return
        if data == "topset_mentions":
            await show_mentions_menu(query)
            return
        if data == "topadd_mention":
            await query.answer()
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("👤 Choose Person", switch_inline_query_current_chat="addmention ")
            ], [
                InlineKeyboardButton("◀️ Back", callback_data="topset_mentions")
            ]])
            await query.edit_message_text(
                "👥 <b>Add Person</b>\n\n"
                "Press the button and choose from the list 👇",
                parse_mode="HTML",
                reply_markup=kb
            )
            return
        if data.startswith("topsel_"):
            chat_id = data[7:]
            # Try to get fresh title from Telegram, fallback to stored title in DB
            stored_title = chat_id
            groups = sb_load_active_groups()
            for g in groups:
                if g["chat_id"] == chat_id:
                    stored_title = g.get("title") or chat_id
                    break
            try:
                chat = await query.bot.get_chat(int(chat_id))
                # Only use title if it's actually a group/supergroup
                if chat.type in ("group", "supergroup") and chat.title:
                    title = chat.title
                    sb_track_active_group(chat_id, title)
                else:
                    title = stored_title
            except Exception:
                title = stored_title
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("👁 Show here", callback_data=f"topshow_{chat_id}"),
                InlineKeyboardButton("📤 Send to group", callback_data=f"topsend_{chat_id}"),
            ], [InlineKeyboardButton("◀️ Back", callback_data="topback_main")]])
            await query.edit_message_text(f"📢 <b>{title}</b>", parse_mode="HTML", reply_markup=kb)
            return
    except Exception as e:
        logging.error(f"top_select_callback error [{data}]: {e}")
        try:
            await query.edit_message_text(f"❌ Error: {e}")
        except Exception:
            pass
async def top_action_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != OWNER_ID:
        await query.answer()
        return
    data = query.data
    if data.startswith("topdel_"):
        uid = data[7:]
        sb_delete_top_mention(uid)
        await query.answer("✅ Removed")
        await show_mentions_menu(query)
        return
    if data == "topmanage_groups":
        await query.answer()
        groups = sb_load_active_groups()
        if not groups:
            await query.edit_message_text("No groups found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="topback_main")]]))
            return
        seen = set()
        btns = []
        for g in groups:
            cid = g["chat_id"]
            if cid in seen:
                continue
            seen.add(cid)
            title = g.get("title") or cid
            btns.append([
                InlineKeyboardButton(f"🗑 {title}", callback_data=f"topdelgroup_{cid}"),
                InlineKeyboardButton(f"🚫 Ban", callback_data=f"topbangroup_{cid}")
            ])
        btns.append([InlineKeyboardButton("◀️ Back", callback_data="topback_main")])
        await query.edit_message_text("🗑 <b>Manage Groups</b>\n\n🗑 Delete — removes but may return\n🚫 Ban — removes forever", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(btns))
        return
    if data.startswith("topbangroup_"):
        cid = data[12:]
        sb_ban_group(cid)
        await query.answer("🚫 Banned forever")
        groups = sb_load_active_groups()
        if not groups:
            await query.edit_message_text("✅ All groups removed.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="topback_main")]]))
            return
        seen = set()
        btns = []
        for g in groups:
            cid2 = g["chat_id"]
            if cid2 in seen:
                continue
            seen.add(cid2)
            title2 = g.get("title") or cid2
            btns.append([
                InlineKeyboardButton(f"🗑 {title2}", callback_data=f"topdelgroup_{cid2}"),
                InlineKeyboardButton(f"🚫 Ban", callback_data=f"topbangroup_{cid2}")
            ])
        btns.append([InlineKeyboardButton("◀️ Back", callback_data="topback_main")])
        await query.edit_message_text("🗑 <b>Manage Groups</b>\n\n🗑 Delete — removes but may return\n🚫 Ban — removes forever", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(btns))
        return
    if data.startswith("topdelgroup_"):
        cid = data[12:]
        sb_delete_active_group(cid)
        await query.answer("✅ Deleted")
        # Refresh the manage groups menu
        groups = sb_load_active_groups()
        if not groups:
            await query.edit_message_text("✅ All groups removed.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="topback_main")]]))
            return
        seen = set()
        btns = []
        for g in groups:
            cid2 = g["chat_id"]
            if cid2 in seen:
                continue
            seen.add(cid2)
            title = g.get("title") or cid2
            btns.append([
                InlineKeyboardButton(f"🗑 {title}", callback_data=f"topdelgroup_{cid2}"),
                InlineKeyboardButton(f"🚫 Ban", callback_data=f"topbangroup_{cid2}")
            ])
        btns.append([InlineKeyboardButton("◀️ Back", callback_data="topback_main")])
        await query.edit_message_text("🗑 <b>Manage Groups</b>\n\n🗑 Delete — removes but may return\n🚫 Ban — removes forever", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(btns))
        return
    if data.startswith("topshow_"):
        chat_id = data[8:]
        await query.answer()
        stored_title = chat_id
        groups = sb_load_active_groups()
        for g in groups:
            if g["chat_id"] == chat_id:
                stored_title = g.get("title") or chat_id
                break
        try:
            chat = await ctx.bot.get_chat(int(chat_id))
            title = chat.title or stored_title
        except Exception:
            title = stored_title
        rows = sb_load_top_counts(chat_id)
        await query.edit_message_text(build_top_text(rows, title), parse_mode="HTML")
        return
    if data.startswith("topsend_"):
        chat_id = data[8:]
        await query.answer("📤 Sending...")
        stored_title = chat_id
        groups = sb_load_active_groups()
        for g in groups:
            if g["chat_id"] == chat_id:
                stored_title = g.get("title") or chat_id
                break
        try:
            chat = await ctx.bot.get_chat(int(chat_id))
            title = chat.title or stored_title
        except Exception:
            title = stored_title
        rows = sb_load_top_counts(chat_id)
        try:
            await send_top_to_group(ctx.bot, chat_id, title, rows, daily=False, test=True)
            await query.edit_message_text(f"✅ Sent to {title} 🇲🇨")
        except Exception as e:
            logging.error(f"topsend_ error: {e}")
            try:
                await query.edit_message_text(f"❌ Failed to send: {e}")
            except Exception:
                pass
        return
    await query.answer()
async def top_private_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.from_user.id != OWNER_ID or msg.chat.type != "private":
        return
    # handle inline selection result
    if msg.text and msg.text.startswith("addmention:"):
        try:
            parts = msg.text.split(":", 2)
            uid = parts[1]
            name = parts[2] if len(parts) > 2 else uid
            sb_save_top_mention(uid, name)
            back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Mentions", callback_data="topset_mentions")]])
            await msg.reply_text(f"✅ <b>{name}</b> added to mentions!", parse_mode="HTML", reply_markup=back_btn)
        except Exception as e:
            await msg.reply_text(f"❌ Error: {e}")
        return
    state = ctx.user_data.get("top_state")
    if not state:
        return
    if state == "waiting_time":
        import re
        text = msg.text.strip()
        match = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)?", text, re.IGNORECASE)
        if not match:
            await msg.reply_text("⚠️ Couldn't read the time. Try: <code>10:30 PM</code> or <code>22:30</code>", parse_mode="HTML")
            return
        h, m, ampm = int(match.group(1)), int(match.group(2)), (match.group(3) or "").upper()
        if ampm == "PM" and h != 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
        tz_name = ctx.user_data.get("top_tz", "Asia/Baghdad")
        sb_save_top_setting("hour", str(h))
        sb_save_top_setting("minute", str(m))
        sb_save_top_setting("timezone", tz_name)
        ctx.user_data.pop("top_state", None)
        kurd_h, kurd_m = h, m
        if tz_name != "Asia/Baghdad":
            kurd_h, kurd_m = convert_time_between_zones(h, m, tz_name, "Asia/Baghdad")
        uk_h, uk_m = convert_time_between_zones(kurd_h, kurd_m, "Asia/Baghdad", "Europe/London")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Settings", callback_data="topset_main")]])
        await msg.reply_text(
            f"✅ <b>Schedule saved!</b>\n\n"
            f"☀️ Kurdistan: <b>{fmt_time(kurd_h, kurd_m)}</b>\n"
            f"🇬🇧 UK: <b>{fmt_time(uk_h, uk_m)}</b>",
            parse_mode="HTML",
            reply_markup=kb
        )
        return
    if state == "waiting_mention":
        uid = None
        name = ""
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Mentions", callback_data="topset_mentions")]])
        if msg.forward_from:
            # forward with public profile
            uid = str(msg.forward_from.id)
            name = msg.forward_from.full_name
        elif msg.forward_origin:
            # forward with privacy enabled — try forward_origin (PTB v21+)
            origin = msg.forward_origin
            if hasattr(origin, "sender_user") and origin.sender_user:
                uid = str(origin.sender_user.id)
                name = origin.sender_user.full_name
            else:
                await msg.reply_text(
                    "⚠️ This person has privacy enabled, can't get their ID.\nSend their user ID directly instead.",
                    reply_markup=back_btn
                )
                return
        elif msg.text and msg.text.strip().startswith("@"):
            try:
                chat = await ctx.bot.get_chat(msg.text.strip())
                uid = str(chat.id)
                name = getattr(chat, "full_name", None) or getattr(chat, "title", None) or msg.text.strip()
            except Exception:
                await msg.reply_text("⚠️ Couldn't find this username. Make sure it's correct.", reply_markup=back_btn)
                return
        elif msg.text and msg.text.strip().lstrip("-").isdigit():
            uid = msg.text.strip()
            try:
                chat = await ctx.bot.get_chat(int(uid))
                name = getattr(chat, "full_name", None) or uid
            except Exception:
                name = uid
        if not uid:
            await msg.reply_text(
                "⚠️ Forward a message from them, or send their @username or user ID.",
                reply_markup=back_btn
            )
            return
        sb_save_top_mention(uid, name)
        ctx.user_data.pop("top_state", None)
        await msg.reply_text(
            f"✅ <b>{name}</b> added to mentions!",
            parse_mode="HTML",
            reply_markup=back_btn
        )
        return
async def inline_query_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query
    if query.from_user.id != OWNER_ID:
        return
    q = query.query.strip()
    if not q.startswith("addmention"):
        return
    search = q[len("addmention"):].strip().lower()
    results = []
    try:
        res = sb.table("top_counts").select("user_id, name").order("count", desc=True).limit(50).execute()
        rows = res.data or []
        seen_ids = set()
        for row in rows:
            uid = str(row.get("user_id", ""))
            if not uid or uid in seen_ids:
                continue
            seen_ids.add(uid)
            name = row.get("name") or uid
            if search and search not in name.lower():
                continue
            results.append(InlineQueryResultArticle(
                id=uid,
                title=name,
                description=uid,
                input_message_content=InputTextMessageContent(f"addmention:{uid}:{name}")
            ))
    except Exception as e:
        logging.error(f"inline_query_handler error: {e}")
    await query.answer(results[:20], cache_time=0)
async def chosen_inline_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    result = update.chosen_inline_result
    if result.from_user.id != OWNER_ID:
        return
    # result.result_id = uid, result.query starts with "addmention"
    if not result.query.startswith("addmention"):
        return
    uid = result.result_id
    # get name from inline_message content
    try:
        parts = result.inline_message_id  # not available here, use result_id + top_counts
        res = sb.table("top_counts").select("name").eq("user_id", uid).limit(1).execute()
        name = res.data[0]["name"] if res.data else uid
    except Exception:
        name = uid
    sb_save_top_mention(uid, name)
    logging.info(f"Mention saved via inline: {uid} {name}")
async def send_daily_top(app):
    groups = sb_load_active_groups()
    seen = set()
    for g in groups:
        chat_id = g["chat_id"]
        if chat_id in seen:
            continue
        seen.add(chat_id)
        try:
            rows = sb_load_top_counts(chat_id)
            title = g.get("title", "")
            if rows:
                await send_top_to_group(app.bot, chat_id, title, rows, daily=True, test=False)
            sb_reset_top_counts(chat_id)
        except Exception as e:
            logging.error(f"daily top error {chat_id}: {e}")
async def top_scheduler(app):
    import pytz
    while True:
        try:
            hour, minute, tz_name = get_top_schedule()
            tz = pytz.timezone(tz_name)
            now = datetime.now(tz)
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            mention_time = next_run - timedelta(minutes=1)
            now = datetime.now(tz)
            wait_mention = (mention_time - now).total_seconds()
            if wait_mention > 0:
                await asyncio.sleep(wait_mention)
                groups = sb_load_active_groups()
                mentions = get_top_mentions()
                if mentions:
                    mention_text = " ".join([f'<a href="tg://user?id={m["user_id"]}">' + (m.get("name") or str(m["user_id"])) + '</a>' for m in mentions])
                    seen = set()
                    for g in groups:
                        if g["chat_id"] in seen:
                            continue
                        seen.add(g["chat_id"])
                        try:
                            await app.bot.send_message(chat_id=int(g["chat_id"]), text=f"👀 {mention_text}", parse_mode="HTML")
                        except Exception:
                            pass
                now = datetime.now(tz)
                wait_run = (next_run - now).total_seconds()
                if wait_run > 0:
                    await asyncio.sleep(wait_run)
            else:
                wait_run = (next_run - now).total_seconds()
                if wait_run > 0:
                    await asyncio.sleep(wait_run)
            await send_daily_top(app)
        except Exception as e:
            logging.error(f"top_scheduler error: {e}")
            await asyncio.sleep(60)
# ─────────────────────────────────────────
#  /kill  — Russian Roulette system
# ─────────────────────────────────────────
import random as _random

# miss lines per survival count (1st, 2nd, 3rd, 4th escape)
KILL_MISS_BY_COUNT = {
    1: [
        "💨 *click* — Empty chamber. First warning.",
        "💨 Missed. The bullet went on vacation.",
        "💨 *click* — Nothing. First time's free.",
        "💨 The gun blinked. So did you.",
    ],
    2: [
        "💨 Still alive? Impressive. Don't get comfortable.",
        "💨 Twice now. The odds are getting ugly.",
        "💨 *click* — Lucky again. But luck runs out.",
        "💨 Two misses. The bullet is embarrassed.",
    ],
    3: [
        "💨 THREE times?! Someone up there likes you.",
        "💨 *click* — Unbelievable. Three lives down.",
        "💨 You should buy a lottery ticket. Seriously.",
        "💨 Third miss. The reaper is taking notes.",
    ],
    4: [
        "💨 FOUR misses. This is your LAST warning.",
        "💨 *click* — Four times. The next one has your name tattooed on it.",
        "💨 Four escapes. The fifth bullet is already loaded.",
        "💨 You've survived four shots. Nobody survives five.",
    ],
}

KILL_HIT_LINES = [
    "💥 BANG. Clean shot. No debate.",
    "🔥 Direct hit. They never saw it coming.",
    "💀 One bullet. One body. Lights out.",
    "🩸 Brutal. Efficient. Deadly.",
    "☠️ FIRED. The chat goes silent.",
]

KILL_DEATH_LINES = [
    "💀 {target} is gone. Moment of silence... nah.",
    "⚰️ {target} has left the chat permanently.",
    "🪦 RIP {target}. It was almost a fair fight.",
    "💀 {target} — ELIMINATED. No last words.",
    "☠️ {target} flatlined. The chat moves on.",
]

KILL_FINAL_LINE = "⚰️ Four warnings ignored. The fifth doesn't miss."

def sb_get_kill_hits(chat_id: str, user_id: str) -> int:
    try:
        res = sb.table("kill_hits").select("hits").eq("chat_id", chat_id).eq("user_id", user_id).execute()
        if res.data:
            return res.data[0]["hits"]
        return 0
    except:
        return 0

def sb_set_kill_hits(chat_id: str, user_id: str, hits: int):
    try:
        sb.table("kill_hits").upsert({"chat_id": chat_id, "user_id": user_id, "hits": hits}).execute()
    except:
        pass

def sb_reset_kill_hits(chat_id: str, user_id: str):
    try:
        sb.table("kill_hits").delete().eq("chat_id", chat_id).eq("user_id", user_id).execute()
    except:
        pass

async def kill_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.reply_to_message:
        await msg.reply_text("🔫 Reply to someone to shoot them.")
        return
    shooter = msg.from_user
    target = msg.reply_to_message.from_user
    if target.id == shooter.id:
        await msg.reply_text("🤦 You can't shoot yourself. Touch grass.")
        return
    if target.is_bot:
        await msg.reply_text("💀 Bots don't die. Nice try.")
        return
    chat_id = str(msg.chat_id)
    target_id = str(target.id)
    target_mention = f'<a href="tg://user?id={target.id}">{target.full_name}</a>'
    shooter_mention = f'<a href="tg://user?id={shooter.id}">{shooter.full_name}</a>'
    # Check current hits on target
    hits = sb_get_kill_hits(chat_id, target_id)
    # Aiming message
    aim_msg = await msg.reply_text(
        f"🔫 {shooter_mention} is aiming at {target_mention}...",
        parse_mode="HTML"
    )
    await asyncio.sleep(2)
    # 4 survived = 5th is guaranteed kill
    if hits >= 4:
        death_line = _random.choice(KILL_DEATH_LINES).format(target=target_mention)
        await aim_msg.edit_text(
            f"{KILL_FINAL_LINE}\n\n{death_line}",
            parse_mode="HTML"
        )
        sb_reset_kill_hits(chat_id, target_id)
        return
    # Random: ~40% chance of hit
    # hit chance increases with each survival
    hit_chances = {0: 0.25, 1: 0.40, 2: 0.60, 3: 0.80}
    fired = _random.random() < hit_chances.get(hits, 0.25)
    if fired:
        hit_line = _random.choice(KILL_HIT_LINES)
        death_line = _random.choice(KILL_DEATH_LINES).format(target=target_mention)
        await aim_msg.edit_text(
            f"{hit_line}\n\n{death_line}",
            parse_mode="HTML"
        )
        sb_reset_kill_hits(chat_id, target_id)
    else:
        new_hits = hits + 1
        sb_set_kill_hits(chat_id, target_id, new_hits)
        miss_pool = KILL_MISS_BY_COUNT.get(new_hits, KILL_MISS_BY_COUNT[4])
        line = _random.choice(miss_pool)
        # bullet counter bar
        filled = "🔴" * new_hits
        empty = "⚫" * (5 - new_hits)
        counter = f"{filled}{empty}  <b>{new_hits}/5</b>"
        if new_hits >= 4:
            footer = f"\n\n{counter}\n☠️ <b>{target_mention} — No way out. The next one ends it.</b>"
        elif new_hits == 3:
            footer = f"\n\n{counter}\n⚠️ <i>{target_mention} is running out of luck.</i>"
        else:
            footer = f"\n\n{counter}"
        await aim_msg.edit_text(
            f"{line}{footer}",
            parse_mode="HTML"
        )

# ─────────────────────────────────────────────────────────────
#  //kill — Duel System
# ─────────────────────────────────────────────────────────────

# active_duels: chat_id (str) -> duel dict
# duel = {
#   "p1": int, "p1_name": str,
#   "p2": int, "p2_name": str,
#   "turn": int,          # whose turn
#   "msg_id": int,        # main duel message id
#   "round": int,
#   "status": "waiting"|"coin"|"active"|"done",
#   "p1_misses": int, "p2_misses": int,
#   "last_action": float  # timestamp for timeout
# }
DUEL_ACTIVE: dict[str, dict] = {}

# ── Supabase helpers ──────────────────────────────────────────
def duel_sb_get(chat_id: str, uid1: str, uid2: str) -> dict:
    key = f"{min(uid1,uid2)}_{max(uid1,uid2)}"
    try:
        res = sb.table("duel_records").select("*")\
            .eq("chat_id", chat_id).eq("pair_key", key).execute()
        return res.data[0] if res.data else {}
    except:
        return {}

def duel_sb_record_win(chat_id: str, winner_id: str, loser_id: str):
    key = f"{min(winner_id,loser_id)}_{max(winner_id,loser_id)}"
    try:
        res = sb.table("duel_records").select("*")\
            .eq("chat_id", chat_id).eq("pair_key", key).execute()
        if res.data:
            wins = res.data[0].get("wins", {})
            wins[winner_id] = wins.get(winner_id, 0) + 1
            sb.table("duel_records").update({"wins": wins})\
                .eq("chat_id", chat_id).eq("pair_key", key).execute()
        else:
            sb.table("duel_records").insert({
                "chat_id": chat_id,
                "pair_key": key,
                "wins": {winner_id: 1}
            }).execute()
    except Exception as e:
        logging.error(f"duel_sb_record_win: {e}")

# ── Text lines ────────────────────────────────────────────────
_DUEL_CHALLENGE = [
    "⚔️ <b>{p1}</b> has challenged <b>{p2}</b> to a duel!\n\n"
    "🎯 <b>{p2}</b> — do you accept?",
    "🔫 <b>{p1}</b> points a gun at <b>{p2}</b>.\n\n"
    "💀 <b>{p2}</b> — will you face them?",
    "🩸 <b>{p1}</b> steps into the arena and calls out <b>{p2}</b>.\n\n"
    "⚡ <b>{p2}</b> — accept or run?",
]
_DUEL_REFUSED = [
    "🏳️ <b>{p2}</b> ran away. Coward.",
    "😐 <b>{p2}</b> ignored the challenge. Duel cancelled.",
    "💨 No response from <b>{p2}</b>. <b>{p1}</b> wins by default.",
]
_DUEL_TIMEOUT = [
    "⏱️ Time's up. <b>{p1}</b> vs <b>{p2}</b> — declared a draw. Both walk away.",
    "⌛ Five minutes passed. The duel ends in a draw.",
    "🕐 No action. The duel between <b>{p1}</b> and <b>{p2}</b> is called off — draw.",
]
_DUEL_COIN = [
    "🪙 Flipping the coin to decide who shoots first...",
    "🪙 A coin spins in the air — fate decides...",
    "🪙 Let the coin choose who pulls the trigger first...",
]
_DUEL_COIN_WIN = [
    "🟡 <b>{name}</b> wins the toss. They go first.",
    "🟡 The coin lands on <b>{name}</b>. First move is theirs.",
    "🟡 <b>{name}</b> called it right. They shoot first.",
]
_DUEL_TURN = [
    "🎯 <b>{name}</b>'s turn. Choose wisely.",
    "🔫 <b>{name}</b> grips the gun. What's it gonna be?",
    "💭 <b>{name}</b> stares down the barrel. The room holds its breath.",
    "⚡ <b>{name}</b>'s move. Everyone's watching.",
]
_DUEL_MISS_SELF = {
    1: [
        "😮‍💨 <b>{name}</b> pressed the barrel to their own head... *click* — empty. Brave. Or insane.",
        "💨 <b>{name}</b> turned the gun on themselves. The chamber was empty. Lucky.",
        "🫀 <b>{name}</b> pulled the trigger on themselves. The bullet had other plans.",
    ],
    2: [
        "😤 <b>{name}</b> did it again — gun to their own head. Empty. The crowd is nervous.",
        "💨 Twice aimed at themselves. Twice survived. Unsettling.",
        "🪬 <b>{name}</b> is either protected by something... or just running out of luck.",
    ],
    3: [
        "🤯 THREE times <b>{name}</b> shot at themselves. THREE empty chambers. Unreal.",
        "💨 The gun refuses to end <b>{name}</b>. Something is very wrong here.",
        "☠️ <b>{name}</b> is flirting with death and death keeps saying no.",
    ],
}
_DUEL_MISS_ENEMY = {
    1: [
        "💨 <b>{name}</b> fires at their opponent — the shot goes wide.",
        "😬 <b>{name}</b> pulls the trigger. Click. Missed.",
        "🌬️ The shot misses. <b>{name}</b> exhales. This isn't over.",
    ],
    2: [
        "💨 Miss. Again. <b>{name}</b> is losing their edge.",
        "😤 Second miss for <b>{name}</b>. The opponent is still standing.",
        "🌀 <b>{name}</b> fired twice. Both wasted.",
    ],
    3: [
        "💀 Third miss. <b>{name}</b> is running on borrowed time.",
        "💨 Three shots. Three misses. Something is very off.",
        "🩸 <b>{name}</b> is shaking. Three misses.",
    ],
}
_DUEL_HIT_SELF = [
    "💥 <b>{name}</b> aimed at themselves... and the gun wasn't empty this time.",
    "🔴 <b>{name}</b> pulled the trigger on themselves. The bullet answered.",
    "💀 <b>{name}</b> chose to gamble with their own life — and lost.",
    "🩸 The gun went off. <b>{name}</b> took the shot. No one saw that coming.",
    "☠️ <b>{name}</b> turned the barrel inward. That was the last mistake.",
]
_DUEL_HIT_ENEMY = [
    "💥 BANG. <b>{name}</b> lands the shot clean.",
    "🔫 <b>{name}</b> fires true — no escape.",
    "🩸 Direct hit. <b>{name}</b> didn't hesitate.",
    "💀 One shot. One kill. <b>{name}</b> is ice cold.",
    "🔥 <b>{name}</b> unloads. The opponent never had a chance.",
]
_DUEL_DEATH = [
    "💀 <b>{loser}</b> drops. <b>{winner}</b> walks away clean.",
    "⚰️ <b>{loser}</b> is done. <b>{winner}</b> reloads for the next one.",
    "🪦 RIP <b>{loser}</b>. <b>{winner}</b> wasn't playing.",
    "☠️ <b>{loser}</b> — ELIMINATED. <b>{winner}</b> stands alone.",
    "🩸 <b>{loser}</b> flatlines. <b>{winner}</b> doesn't even blink.",
]

# Hit probability per round
_HIT_ENEMY = {1: 0.20, 2: 0.35, 3: 0.55, 4: 0.75, 5: 1.0}
_HIT_SELF  = {1: 0.25, 2: 0.40, 3: 0.60, 4: 0.80, 5: 1.0}

# ── Helpers ───────────────────────────────────────────────────
def _dm(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{name}</a>'

def _duel_scoreboard(record: dict, p1_id: str, p2_id: str, p1_name: str, p2_name: str) -> str:
    if not record:
        return ""
    wins = record.get("wins", {})
    w1 = wins.get(p1_id, 0)
    w2 = wins.get(p2_id, 0)
    total = w1 + w2
    if total == 0:
        return ""
    bar1 = "🟥" * w1
    bar2 = "🟦" * w2
    return (
        f"\n\n📊 <b>Head-to-head record:</b>\n"
        f"{bar1} <b>{p1_name}</b> {w1}W\n"
        f"{bar2} <b>{p2_name}</b> {w2}W\n"
        f"<i>{total} duels fought</i>"
    )

def _miss_bar(duel: dict) -> str:
    p1m = duel.get("p1_misses", 0)
    p2m = duel.get("p2_misses", 0)
    return (
        f"\n💠 {duel['p1_name']}: {'🔴'*p1m}{'⚫'*(5-p1m)}\n"
        f"💠 {duel['p2_name']}: {'🔴'*p2m}{'⚫'*(5-p2m)}"
    )

async def _duel_send_turn(msg, duel: dict, chat_id: str, header: str = ""):
    turn_uid  = duel["turn"]
    turn_name = duel["p1_name"] if turn_uid == duel["p1"] else duel["p2_name"]
    p1m = _dm(duel["p1"], duel["p1_name"])
    p2_display_name = duel["p2_name"]
    if duel["p2"] == 0:
        p2_display_name = "Zaxoy Bot 🇲🇨"
    p2m = _dm(duel["p2"], p2_display_name)
    mbar = _miss_bar(duel)
    turn_line = _random.choice(_DUEL_TURN).format(name=turn_name)
    text = (
        f"⚔️ <b>DUEL</b> — {p1m} vs {p2m}\n"
        f"🔄 Round {duel['round']}{mbar}\n\n"
        + (f"{header}\n\n" if header else "")
        + turn_line
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎯 Shoot at him",          callback_data=f"duel_fire_{chat_id}_enemy"),
        InlineKeyboardButton("💀 Turn gun on yourself",  callback_data=f"duel_fire_{chat_id}_self"),
    ]])
    duel["last_action"] = asyncio.get_event_loop().time()
    try:
        await msg.edit_text(text, parse_mode="HTML", reply_markup=kb)
        duel["msg_id"] = msg.message_id
    except:
        pass

# ── //kill command ────────────────────────────────────────────
async def duel_kill_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    chat_id = str(msg.chat_id)
    challenger = msg.from_user

    # Allow //kill without reply to initiate a challenge waiting for a player
    if not msg.reply_to_message:
        # Check if there's an existing duel waiting in this chat
        existing = DUEL_ACTIVE.get(chat_id)
        if existing and existing["status"] == "waiting":
            await msg.reply_text("⏳ A duel challenge is already waiting in this chat. Reply to it with //kill to join!")
            return

        # Create a duel where the challenger is waiting for an opponent
        duel = {
            "p1": challenger.id,
            "p1_name": challenger.full_name,
            "p2": None, # No opponent yet
            "p2_name": None,
            "turn": None,
            "msg_id": None,
            "round": 1,
            "status": "waiting_for_player", # New status
            "p1_misses": 0,
            "p2_misses": 0,
            "last_action": asyncio.get_event_loop().time(),
        }
        DUEL_ACTIVE[chat_id] = duel

        text = f"⚔️ <b>{challenger.full_name}</b> is looking for a duel opponent!\n\nReply to this message with <code>//kill</code> to accept the challenge!"
        sent = await msg.reply_text(text, parse_mode="HTML")
        duel["msg_id"] = sent.message_id

        # Auto-cancel after 60s if no one joins
        async def _auto_cancel_waiting():
            await asyncio.sleep(60)
            d = DUEL_ACTIVE.get(chat_id)
            if d and d["status"] == "waiting_for_player" and d["msg_id"] == sent.message_id:
                DUEL_ACTIVE.pop(chat_id, None)
                await ctx.bot.edit_message_text(
                    chat_id=msg.chat_id,
                    message_id=sent.message_id,
                    text=f"⏳ <b>{challenger.full_name}</b>'s duel challenge timed out. No one dared to face them.",
                    parse_mode="HTML"
                )
        asyncio.create_task(_auto_cancel_waiting())
        return

    # If it's a reply, check if it's to a 'waiting_for_player' message
    if msg.reply_to_message and msg.reply_to_message.from_user and msg.reply_to_message.from_user.id == ctx.bot.id:
        existing = DUEL_ACTIVE.get(chat_id)
        if existing and existing["status"] == "waiting_for_player" and msg.reply_to_message.message_id == existing["msg_id"]:
            # A player is accepting the challenge
            if challenger.id == existing["p1"]:
                await msg.reply_text("🤦 You started this challenge, you can't accept your own.")
                return
            
            existing["p2"] = challenger.id
            existing["p2_name"] = challenger.full_name
            existing["status"] = "coin"
            existing["last_action"] = asyncio.get_event_loop().time()

            p1m = _dm(existing["p1"], existing["p1_name"])
            p2m = _dm(existing["p2"], existing["p2_name"])
            coin_text = _random.choice(_DUEL_COIN)
            await msg.reply_to_message.edit_text(
                f"⚔️ <b>DUEL ACCEPTED</b> — {p1m} vs {p2m}\n\n{coin_text}",
                parse_mode="HTML"
            )
            await asyncio.sleep(2)
            
            goes_first = _random.choice(["p1", "p2"])
            first_id   = existing["p1"] if goes_first == "p1" else existing["p2"]
            first_name = existing["p1_name"] if goes_first == "p1" else existing["p2_name"]
            existing["turn"] = first_id
            existing["status"] = "active"
            existing["last_action"] = asyncio.get_event_loop().time()
            
            coin_result = _random.choice(_DUEL_COIN_WIN).format(name=first_name)
            await asyncio.sleep(1)
            await _duel_send_turn(msg.reply_to_message, existing, chat_id, header=coin_result)
            return

    # Original reply-to-user logic
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text(
            "🔫 Reply to someone to challenge them to a duel.\n"
            "<i>Example: reply to a message and send //kill</i>",
            parse_mode="HTML"
        )
        return

    target = msg.reply_to_message.from_user

    target = msg.reply_to_message.from_user

    if target.id == challenger.id:
        await msg.reply_text("🤦 You can't duel yourself.")
        return
    if getattr(target, "is_bot", False):
        await msg.reply_text("🤖 Bots don't duel.")
        return

    existing = DUEL_ACTIVE.get(chat_id)

    # If challenger or target already in an active duel
    if existing and existing["status"] in ("waiting", "coin", "active"):
        if challenger.id in (existing["p1"], existing["p2"]):
            await msg.reply_text(
                "🔫 You're already in a duel. Finish it first.",
                parse_mode="HTML"
            )
            return
        if target.id in (existing["p1"], existing["p2"]):
            # Tell challenger to wait
            p1n = existing["p1_name"]
            p2n = existing["p2_name"]
            await msg.reply_text(
                f"⏳ <b>{target.full_name}</b> is already in a duel ({p1n} vs {p2n}).\n"
                f"Wait for them to finish.",
                parse_mode="HTML"
            )
            return
        # [REMOVED GLOBAL BLOCK] 
        # Allow other duels to start even if one is active, 
        # but the current implementation of DUEL_ACTIVE uses chat_id as key.
        # To support multiple duels in one chat, we'd need to change the key.
        # However, the user said "allow all other requests", and DUEL_ACTIVE only blocks //kill.
        # The previous code was blocking ANY new //kill in the chat.
        pass

    # Create duel record
    duel = {
        "p1": challenger.id,
        "p1_name": challenger.full_name,
        "p2": target.id,
        "p2_name": target.full_name,
        "turn": None,
        "msg_id": None,
        "round": 1,
        "status": "waiting",
        "p1_misses": 0,
        "p2_misses": 0,
        "last_action": asyncio.get_event_loop().time(),
    }
    DUEL_ACTIVE[chat_id] = duel

    text = _random.choice(_DUEL_CHALLENGE).format(
        p1=challenger.full_name,
        p2=target.full_name
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚔️ Accept",    callback_data=f"duel_accept_{chat_id}"),
        InlineKeyboardButton("🏳️ Run away", callback_data=f"duel_refuse_{chat_id}"),
    ]])
    # Reply directly to the target (who was replied to originally)
    sent = await msg.reply_to_message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    duel["msg_id"] = sent.message_id

    # Auto-cancel after 40s if still waiting
    async def _auto_cancel():
        await asyncio.sleep(40)
        d = DUEL_ACTIVE.get(chat_id)
        if d and d["status"] == "waiting" and d["msg_id"] == sent.message_id:
            DUEL_ACTIVE.pop(chat_id, None)
            refused = _random.choice(_DUEL_REFUSED).format(
                p1=challenger.full_name, p2=target.full_name
            )
            try:
                await ctx.bot.edit_message_text(
                    chat_id=msg.chat_id,
                    message_id=sent.message_id,
                    text=refused,
                    parse_mode="HTML"
                )
            except:
                pass
    asyncio.create_task(_auto_cancel())

    # 5-minute inactivity timeout (draw)
    async def _inactivity_timeout():
        await asyncio.sleep(300)
        d = DUEL_ACTIVE.get(chat_id)
        if not d or d["status"] not in ("active", "coin"):
            return
        # Check if last action was recent (reset clock if they fired)
        elapsed = asyncio.get_event_loop().time() - d.get("last_action", 0)
        if elapsed < 295:
            return
        DUEL_ACTIVE.pop(chat_id, None)
        timeout_line = _random.choice(_DUEL_TIMEOUT).format(
            p1=d["p1_name"], p2=d["p2_name"]
        )
        try:
            await ctx.bot.edit_message_text(
                chat_id=msg.chat_id,
                message_id=d["msg_id"],
                text=timeout_line,
                parse_mode="HTML"
            )
        except:
            pass
    asyncio.create_task(_inactivity_timeout())


# ── Accept / Refuse ───────────────────────────────────────────
async def duel_accept_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split("_")   # duel_accept_{chat_id} or duel_refuse_{chat_id}
    action  = parts[1]          # accept / refuse
    chat_id = parts[2]

    duel = DUEL_ACTIVE.get(chat_id)
    if not duel or duel["status"] != "waiting":
        await q.answer("This duel is no longer active.", show_alert=True)
        return

    user = q.from_user

    # Only p2 can accept/refuse
    if user.id != duel["p2"] and duel["p2"] != 0: # Allow AI (p2=0) to be accepted by AI logic in ask_cmd
        await q.answer("This duel isn't for you.", show_alert=True)
        return

    await q.answer()

    if action == "refuse":
        DUEL_ACTIVE.pop(chat_id, None)
        refused = _random.choice(_DUEL_REFUSED).format(
            p1=duel["p1_name"], p2=duel["p2_name"]
        )
        await q.edit_message_text(refused, parse_mode="HTML")
        return

    # Accepted — coin flip
    duel["status"] = "coin"
    coin_text = _random.choice(_DUEL_COIN)
    p1m = _dm(duel["p1"], duel["p1_name"])
    p2m = _dm(duel["p2"], duel["p2_name"])
    if duel["p2"] == 0:
        p2m = _dm(0, "Zaxoy Bot 🇲🇨") # Ensure AI name is correct
    await q.edit_message_text(
        f"⚔️ <b>DUEL ACCEPTED</b> — {p1m} vs {p2m}\n\n{coin_text}",
        parse_mode="HTML"
    )
    await asyncio.sleep(2)

    # p1 always wins the flip (challenger chose to challenge, they pick side)
    # — per requirement: the one who started the challenge flips
    goes_first = _random.choice(["p1", "p2"])
    first_id   = duel["p1"] if goes_first == "p1" else duel["p2"]
    first_name = duel["p1_name"] if goes_first == "p1" else duel["p2_name"]
    duel["turn"] = first_id
    duel["status"] = "active"
    duel["last_action"] = asyncio.get_event_loop().time()

    coin_result = _random.choice(_DUEL_COIN_WIN).format(name=first_name)
    await asyncio.sleep(1)
    await _duel_send_turn(q.message, duel, chat_id, header=coin_result)


# ── Fire button ───────────────────────────────────────────────
async def duel_fire_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split("_")   # duel_fire_{chat_id}_{enemy|self}
    chat_id     = parts[2]
    target_type = parts[3]      # "enemy" or "self"

    duel = DUEL_ACTIVE.get(chat_id)
    if not duel or duel["status"] != "active":
        await q.answer("No active duel here.", show_alert=True)
        return

    user = q.from_user

    # Block outsiders
    if user.id not in (duel["p1"], duel["p2"]):
        await q.answer("Stay out — this isn't your fight. 🚫", show_alert=True)
        return

    # Block wrong turn
    if user.id != duel["turn"]:
        await q.answer("⏳ It's not your turn. Wait.", show_alert=True)
        return

    await q.answer()

    shooter_id   = user.id
    shooter_name = duel["p1_name"] if shooter_id == duel["p1"] else duel["p2_name"]
    opp_id       = duel["p2"]      if shooter_id == duel["p1"] else duel["p1"]
    opp_name     = duel["p2_name"] if shooter_id == duel["p1"] else duel["p1_name"]
    round_no     = duel["round"]

    if target_type == "self":
        victim_id   = shooter_id
        victim_name = shooter_name
        killer_id   = opp_id
        killer_name = opp_name
        chance      = _HIT_SELF.get(round_no, 1.0)
        miss_lines  = _DUEL_MISS_SELF
        hit_lines   = _DUEL_HIT_SELF
    else:
        victim_id   = opp_id
        victim_name = opp_name
        killer_id   = shooter_id
        killer_name = shooter_name
        chance      = _HIT_ENEMY.get(round_no, 1.0)
        miss_lines  = _DUEL_MISS_ENEMY
        hit_lines   = _DUEL_HIT_ENEMY

    fired = _random.random() < chance
    duel["last_action"] = asyncio.get_event_loop().time()

    if fired:
        # ── HIT → end duel ────────────────────────────────────
        duel["status"] = "done"
        DUEL_ACTIVE.pop(chat_id, None)

        hit_line   = _random.choice(hit_lines).format(name=shooter_name)
        death_line = _random.choice(_DUEL_DEATH).format(
            winner=_dm(killer_id, killer_name),
            loser=_dm(victim_id, victim_name)
        )

        duel_sb_record_win(chat_id, str(killer_id), str(victim_id))
        record = duel_sb_get(chat_id, str(duel["p1"]), str(duel["p2"]))
        scoreboard = _duel_scoreboard(
            record,
            str(duel["p1"]), str(duel["p2"]),
            duel["p1_name"], duel["p2_name"]
        )

        p1m  = _dm(duel["p1"], duel["p1_name"])
        p2m  = _dm(duel["p2"], duel["p2_name"])
        mbar = _miss_bar(duel)

        final = (
            f"⚔️ <b>DUEL OVER</b> — {p1m} vs {p2m}\n"
            f"🔄 Round {round_no}{mbar}\n\n"
            f"{hit_line}\n\n{death_line}"
            f"{scoreboard}"
        )
        try:
            await q.edit_message_text(final, parse_mode="HTML")
        except:
            pass

    else:
        # ── MISS → next turn ──────────────────────────────────
        if shooter_id == duel["p1"]:
            duel["p1_misses"] = duel.get("p1_misses", 0) + 1
        else:
            duel["p2_misses"] = duel.get("p2_misses", 0) + 1

        duel["round"] += 1
        duel["turn"] = opp_id

        pool      = miss_lines.get(min(round_no, 3), miss_lines[3])
        miss_line = _random.choice(pool).format(name=shooter_name)

        await _duel_send_turn(q.message, duel, chat_id, header=miss_line)


def main():
    start_keep_alive()
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.ALL, cache_user_message), group=-3)
app.add_handler(MessageHandler(filters.ALL, auto_delete_handler), group=-2)
# 1. Normal Commands
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("on", on_cmd))
app.add_handler(CommandHandler("off", off_cmd))
app.add_handler(CommandHandler("choose", choose_cmd))
app.add_handler(CommandHandler("xo", xo_handler))
# //hack
app.add_handler(MessageHandler(
    filters.TEXT & filters.Regex(r"^//hack\b"),
    hack_cmd
))
# /gaytest — group command
app.add_handler(CommandHandler("gaytest", gaytest_cmd))
# /kill
app.add_handler(CommandHandler("kill", kill_cmd))
# //kill — duel system
app.add_handler(MessageHandler(
    filters.TEXT & filters.Regex(r"^//kill\b"),
    duel_kill_cmd
))
app.add_handler(CallbackQueryHandler(duel_accept_cb, pattern=r"^duel_(accept|refuse)_"))
app.add_handler(CallbackQueryHandler(duel_fire_cb,   pattern=r"^duel_fire_"))
# /rps
app.add_handler(CommandHandler("rps", rps_cmd))
app.add_handler(CallbackQueryHandler(rps_callback, pattern=r"^rps_\d+_(rock|paper|scissors)$"))
app.add_handler(CallbackQueryHandler(rps_again_callback, pattern=r"^rpsagain_\d+$"))
# //top — group (owner or permitted users)
app.add_handler(MessageHandler(
    filters.ChatType.GROUPS & filters.TEXT & filters.Regex(r"^//top$"),
    top_cmd_group
))
# //top — private owner selector only
app.add_handler(MessageHandler(
    filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(r"^//top$") & filters.User(OWNER_ID),
    top_owner_cmd
))
app.add_handler(CallbackQueryHandler(top_select_callback, pattern=r"^(topsel_|topset_|topback_|toptz_|topadd_)"))
app.add_handler(CallbackQueryHandler(top_action_callback, pattern=r"^(topshow_|topsend_|topdel_|topmanage_groups|topdelgroup_|topbangroup_)"))
app.add_handler(InlineQueryHandler(inline_query_handler))
app.add_handler(ChosenInlineResultHandler(chosen_inline_handler))
# //top private input
app.add_handler(MessageHandler(
    filters.ChatType.PRIVATE & filters.User(OWNER_ID),
    top_private_input
), group=2)
# //gaytest — private owner setup session (must be before general // router)
app.add_handler(MessageHandler(
    filters.ChatType.PRIVATE
    & filters.TEXT
    & filters.Regex(r"^//gaytest")
    & filters.User(OWNER_ID),
    gaytest_private_cmd
))
# //gaytest session input handler (waiting for % or message)
app.add_handler(MessageHandler(
    filters.ChatType.PRIVATE
    & filters.TEXT
    & filters.User(OWNER_ID)
    & GAYTEST_SESSION_ACTIVE,
    gaytest_session_handler
))
# gaytest callbacks (edit/delete from //gaytest //list)
app.add_handler(CallbackQueryHandler(
    gaytest_callback,
    pattern="^(gaydel_|gayedit_|gayeditpct_|gayeditmsg_|gaytypeg_|gaytypes_|gayedittype_|gayedittypeg_|gayedittypes_)"
))
# 1.5 Owner-only file sender
app.add_handler(MessageHandler(
    filters.ChatType.PRIVATE
    & filters.TEXT
    & filters.Regex(r"^bot\.py$")
    & filters.User(OWNER_ID),
    send_botpy
))
# 2. Specific Double Slash (//)
app.add_handler(MessageHandler(
    filters.TEXT & filters.Regex(r"^//warn\b"),
    warn_cmd
))
app.add_handler(MessageHandler(
    filters.TEXT & filters.Regex(r"^//shot\b"),
    shot_cmd
))
app.add_handler(MessageHandler(
    filters.TEXT & filters.Regex(r"^//voice\b"),
    voice_cmd
))
# 3. Media Mentions Monitor
app.add_handler(MessageHandler(
    filters.VIDEO & filters.CaptionEntity("mention"),
    monitor_mentions
))
app.add_handler(MessageHandler(
    filters.ChatType.PRIVATE
    & (filters.TEXT | filters.Sticker.ALL)
    & filters.User(OWNER_ID)
    & IF_SESSION_ACTIVE,
    if_session_handler
))
app.add_handler(MessageHandler(
    filters.Sticker.ALL,
    if_auto_responder
), group=1)
# 4. Callback Queries
app.add_handler(CallbackQueryHandler(
    copy_callback,
    pattern="^copy_"
))
app.add_handler(CallbackQueryHandler(
    unmute_button,
    pattern="^(unmute_|remwarn_|resetwarn_)"
))
app.add_handler(CallbackQueryHandler(
    xo_move,
    pattern="^xo_"
))
app.add_handler(CallbackQueryHandler(
    if_callback,
    pattern="^(ifdel_|ifedit_|ifedittrigger_|ifeditreply_)"
))
app.add_handler(CallbackQueryHandler(
    admin_list_callback,
    pattern="^(adminrm_|adminadd_|adminaddperm_|adminrmperm_|adminrmpermdo_|admincancel)"
))
app.add_handler(CallbackQueryHandler(
    ban_callback,
    pattern="^unban_"
))
# 5. General Message Routers
app.add_handler(MessageHandler(
    filters.TEXT & filters.Regex(r"^//if"),
    if_cmd
))
app.add_handler(MessageHandler(
    filters.Regex(r"^//delete"),
    delete_cmd
))
app.add_handler(MessageHandler(
    filters.Regex(r"^//"),
    message_router
))
app.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND,
    message_router
))
app.add_handler(CallbackQueryHandler(
    delete_callback,
    pattern="^delrm_"
))
app.add_handler(MessageHandler(
    filters.ALL,
    delete_waiting_handler
), group=2)
print("Zaxoy Bot started 🇲🇨")
app.add_handler(CallbackQueryHandler(
    ask_instructions_callback,
    pattern="^(aiidel_|aiiedit_|aiireset_)"
))
app.add_handler(MessageHandler(
    filters.ChatType.PRIVATE & filters.TEXT & filters.User(OWNER_ID),
    ask_edit_session_handler
), group=2)
# Load owner facts from Supabase on startup
AI_INSTRUCTIONS.extend(sb_load_ai_instructions())  # Load from ai_instructions table

# ── PM RELAY ──────────────────────────────────────────────────────────────────
# Maps message_id of forwarded msg in owner's chat -> original sender user_id
PM_RELAY_MAP: dict[int, int] = {}

async def pm_relay_incoming(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Forward any private message (non-owner) to owner."""
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user:
        return
    if user.id == OWNER_ID:
        return
    # Forward to owner
    try:
        header = await ctx.bot.send_message(
            chat_id=OWNER_ID,
            text=f"📩 <b>{user.full_name}</b> (<code>{user.id}</code>):",
            parse_mode="HTML"
        )
        forwarded = await msg.forward(chat_id=OWNER_ID)
        # Map forwarded message id -> sender id
        PM_RELAY_MAP[forwarded.message_id] = user.id
        PM_RELAY_MAP[header.message_id] = user.id
    except Exception as e:
        logging.error(f"pm_relay_incoming: {e}")

async def pm_relay_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Owner replies to a forwarded msg -> send to original sender."""
    msg = update.effective_message
    if not msg or not msg.reply_to_message:
        return
    replied_id = msg.reply_to_message.message_id
    target_id = PM_RELAY_MAP.get(replied_id)
    if not target_id:
        # If it's a private chat with the owner and they reply to the bot, 
        # it might be an AI conversation, so we just return and let message_router handle it.
        if msg.chat.type == "private" and msg.reply_to_message.from_user.id == ctx.bot.id:
            return
        await msg.reply_text("⚠️ Can't find the original sender.")
        return
    try:
        await ctx.bot.send_message(chat_id=target_id, text=msg.text)
        await msg.reply_text("✅ Sent.")
    except Exception as e:
        await msg.reply_text(f"❌ Failed: {e}")

# Incoming: any private message from non-owner
app.add_handler(MessageHandler(
    filters.ChatType.PRIVATE & ~filters.User(OWNER_ID),
    pm_relay_incoming
), group=5)

# Outgoing: owner replies in private chat
app.add_handler(MessageHandler(
    filters.ChatType.PRIVATE & filters.User(OWNER_ID) & filters.REPLY,
    pm_relay_reply
), group=5)

async def post_init(application):
    asyncio.create_task(top_scheduler(application))
app.post_init = post_init
app.run_polling()
if __name__ == "__main__":
    main()
