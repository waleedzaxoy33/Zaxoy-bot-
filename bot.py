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
    ChatPermissions
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────

BOT_TOKEN = "8502998355:AAHt5Er-xzPxBBl6m6hfPBlvN_R8M4j0Vis"

OWNER_ID = int(os.environ.get("OWNER_ID", "7735152814"))

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────────────────────────
# Supabase Helpers
# ─────────────────────────────────────────────────────────────

def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

def sb_load_admin_perms() -> dict:
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/admin_perms?select=user_id,perms",
            headers=sb_headers(), timeout=10
        )
        result = {}
        for row in r.json():
            result[int(row["user_id"])] = set(row["perms"])
        return result
    except Exception:
        return {}

def sb_save_admin_perms(store: dict):
    try:
        requests.delete(
            f"{SUPABASE_URL}/rest/v1/admin_perms?user_id=neq.0",
            headers=sb_headers(), timeout=10
        )
        rows = [{"user_id": str(k), "perms": list(v)} for k, v in store.items()]
        if rows:
            requests.post(
                f"{SUPABASE_URL}/rest/v1/admin_perms",
                headers=sb_headers(),
                json=rows, timeout=10
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
    "🔇 {name} has been silenced in Zaxo's domain for {duration}. The city speaks — you don't. 🇵🇱",
    "⛓️ {name} is now muted for {duration}. Zaxo's law has been enforced. 🇵🇱",
    "🚫 {name} — {duration} of silence. Zaxo does not tolerate noise. 🇵🇱",
    "🌑 {name} has entered the shadow zone for {duration}. Not a word. 🇵🇱",
    "⚔️ {name} has been struck silent for {duration} by order of Zaxoy Bot. 🇵🇱",
    "🤫 {name} has been silenced for {duration} by order of Zaxoy! 🇵🇱",
    "🚫 Calm down {name}, take a break from chatting for {duration}! 🇵🇱",
    "⚡ The hammer has fallen! {name} is muted for {duration}! 🇵🇱"
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


def has_perm(user_id: int, cmd: str) -> bool:
    if user_id == OWNER_ID:
        return True

    perms = admin_perms.get(user_id, set())

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
        "🇵🇱 Zaxoy Bot is here for you!"
    ],

    [
        "🚀 Launching Zaxo systems...",
        "🌙 Night or day, Zaxo never sleeps",
        "🎯 Precision mode activated",
        "🛡️ Zaxo protection enabled",
        "🇵🇱 Let's go, Zaxoy Bot!"
    ],

    [
        "💎 Zaxo — rare, sharp, unstoppable",
        "🌊 Flowing with power",
        "🎶 Tuned to perfection",
        "🦅 Flying above the rest",
        "🇵🇱 Zaxoy Bot online!"
    ],

    [
        "⚔️ Zaxo stands strong",
        " Beauty meets intelligence",
        "🔮 Future is Zaxo",
        "✨ Sparkling with features",
        "🇵🇱 Zaxoy Bot activated!"
    ],

    [
        "🏔️ Tall as Zaxo mountains",
        " Colorful like Zaxo skies",
        "🎯 Always on target",
        "🤝 Here to help you",
        "🇵🇱 Zaxoy Bot, always ready!"
    ],

    [
        "🌍 Zaxo — known worldwide",
        "💡 Smart, fast, reliable",
        "🔑 Unlocking possibilities",
        "🌟 Shining brighter every day",
        "🇵🇱 Zaxoy Bot loaded!"
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

async def resolve_target_from_mention(msg, ctx):
    """Extract target from reply or @username only"""

    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, u.full_name

    text_msg = msg.text or msg.caption or ""

    username_match = re.search(r'@(\w{3,})', text_msg)
    if not username_match:
        return None, None

    username = f"@{username_match.group(1)}".lower()

    cached_user_id = USER_CACHE.get(username)

    if cached_user_id:
        cached_data = USER_CACHE.get(str(cached_user_id), {})
        return int(cached_user_id), cached_data.get("name", username)

    try:
        chat = await ctx.bot.get_chat(username)
        return chat.id, chat.full_name or username
    except Exception:
        return None, None

async def resolve_target_user(msg, ctx, allow_id=False):
    reply = msg.reply_to_message
    if reply and reply.from_user:
        return reply.from_user.id, reply.from_user.full_name, reply

    if msg.entities:
        for entity in msg.entities:
            if entity.type == 'text_mention' and entity.user:
                return entity.user.id, entity.user.full_name, None

            if entity.type == 'mention':
                username = msg.text[entity.offset + 1: entity.offset + entity.length]
                try:
                    chat = await ctx.bot.get_chat(f'@{username}')
                    return chat.id, chat.full_name or username, None
                except Exception:
                    continue

    parts = msg.text.strip().split()
    if len(parts) > 1:
        for part in parts[1:]:
            clean_part = part.strip()

            if clean_part.startswith("@"):
                cached_user_id = USER_CACHE.get(clean_part.lower())

                if cached_user_id:
                    cached_data = USER_CACHE.get(str(cached_user_id), {})
                    return int(cached_user_id), cached_data.get("name", clean_part), None

            if allow_id and clean_part.lstrip("-").isdigit():
                cached_data = USER_CACHE.get(str(int(clean_part)), {})
                return int(clean_part), cached_data.get("name", clean_part), None

    return None, None, None

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
    "✅ Zaxoy Bot is ON and fully operational 🇵🇱",
    "🟢 Discount Zaxoy Bot activated — ready to serve 🇵🇱",
    "⚡ Contact Zaxoy Bot — I'm online and listening 🇵🇱",
    "🔛 Zaxoy Bot switched ON — let the magic begin 🇵🇱",
    "💚 Zaxoy Bot is live and kicking 🇵🇱",
]

OFF_MSGS = [
    "🔴 Zaxoy Bot going offline — see you soon 🇵🇱",
    "⛔ Discount Zaxoy Bot is OFF for now 🇵🇱",
    "💤 Contact Zaxoy Bot — resting mode activated 🇵🇱",
    "🔕 Zaxoy Bot switched OFF — take care 🇵🇱",
    "❌ Zaxoy Bot signing out 🇵🇱",
]


async def on_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(ON_MSGS))


async def off_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    "🛡️ Zaxo is the crown jewel of Kurdistan — built on history, love, and pride. Think before you speak. 🇵🇱",

    "🌊 The rivers of Zaxo carry more dignity than your words ever could. 🇵🇱",

    "⚔️ Zaxo stood for centuries — your opinion won't scratch it. 🇵🇱",

    "🛡️ Zaxo is carved from mountains. Insults? Just wind. 🇵🇱",

    "💎 Every stone in Zaxo is worth more than a thousand hateful words. 🇵🇱",

    "Zaxo doesn't need defense — it speaks for itself through its people, culture, and beauty. 🇵🇱",
]


def is_zaxo_insult(text: str) -> bool:

    t = text.lower()

    negative = [
        "Part of duhok",
        "shit",
        "trash",
        "hate",
        "bad",
        "ugly",
        "stupid",
        "against",
        "L",
        "part of duhok",
        "small city"
    ]

    has_zaxo = any(
        z in t
        for z in ["zaxo", "zakho"]
    )

    has_neg = any(
        n in t
        for n in negative
    )

    return has_zaxo and has_neg


async def zaxo_defense_handler(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE
):

    msg = update.message

    if not msg or not msg.text:
        return

    if is_zaxo_insult(msg.text):
        await msg.reply_text(
            random.choice(ZAXO_DEFENSE)
        )


# ─────────────────────────────────────────────────────────────
# Waleed Zaxoy Name Protection
# ─────────────────────────────────────────────────────────────

def is_waleed_fake(text: str) -> bool:

    pattern = r'\bWaleed\s+\w+[ie]\b'

    matches = re.findall(
        pattern,
        text,
        re.IGNORECASE
    )

    for m in matches:

        parts = m.strip().split()

        if len(parts) >= 2:

            second = parts[1].lower()

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

    if is_waleed_fake(msg.text):

        await msg.reply_text(
            "Waleed Zaxoy*",
            reply_to_message_id=msg.message_id
        )


# ─────────────────────────────────────────────────────────────
# //zaxo
# ─────────────────────────────────────────────────────────────

ZAXO_MESSAGES = [
    "🌟 Zaxo — where the Khabur river sings and the mountains whisper ancient tales. 🇵🇱",

    "💫 Zaxo: the city of bridges, not only over rivers, but between hearts. 🇵🇱",

    "🎶 Erdwan Zaxoy — a voice that carries the soul of an entire city in every note. Pure magic. 🇵🇱",

    "🔥 If passion had an address, it would be Zaxo, Kurdistan. 🇵🇱",

    "Zaxo raised warriors, poets, and dreamers — all in one breath. 🇵🇱",

    "🎵 Erdwan Zaxoy sings and suddenly the whole world remembers where home is. 🇵🇱",

    "🏔️ From the peaks of Zaxo to the ends of the earth — the name travels far. 🇵🇱",

    "✨ Zaxo: ancient like history, fresh like morning air. 🇵🇱",

    "💎 The people of Zaxo carry gold in their words and steel in their hearts. 🇵🇱",

    "🌊 Every wave in the Khabur knows the name Zaxo — it's been whispered for centuries. 🇵🇱",

    "🎼 Erdwan Zaxoy — his melodies don't just play, they heal. A legend born from Zaxo's spirit. 🇵🇱",

    "Zaxo doesn't just exist on the map — it lives in every soul that once touched its streets. 🇵🇱",

    "⚡ From Zaxo, with pride. No city shines brighter. 🇵🇱",

    "🦅 Zaxo soars like an eagle — high, proud, and forever free. 🇵🇱",

    "🌙 When the night falls on Zaxo, the stars shine a little brighter than anywhere else. 🇵🇱",
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


# ─────────────────────────────────────────────────────────────
# ─── //ask — AI via OpenRouter ─────────────────────────────

async def ask_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text_parts = msg.text.split(None, 1)

    question = text_parts[1].strip() if len(text_parts) > 1 else None

    if not question:
        await msg.reply_text(
            "🤖 Ask me anything!\nUsage: //ask [your question]"
        )
        return

    thinking = await msg.reply_text("🤔 Thinking...")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://t.me/",
                    "X-Title": "ZaxoyBot",
                },
                json={
                    "model": "google/gemma-2-9b-it:free",
                    "messages": [
                        {"role": "user", "content": question}
                    ],
                    "max_tokens": 1000,
                }
            )

        data = resp.json()

        if "choices" in data and len(data["choices"]) > 0:
            answer = data["choices"][0]["message"]["content"]
        else:
            answer = str(data)

    except Exception as e:
        answer = f"⚠️ Error: {str(e)}"

    await thinking.edit_text(f"🤖 {answer}")

# ─── //add ────────────────────────────────────────────────────────────
VALID_CMDS = {"//info", "//id", "//r", "//ask", "//zaxo", "//say", "//st", "//re", "//mute", "//unmute", "//warn" , "//ban" ,"//unban"}

async def add_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global admin_perms
    msg = update.message
    if msg.from_user.id != OWNER_ID:
        return

    target = msg.reply_to_message
    parts = msg.text.strip().split(None, 1)
    specific_cmd = parts[1].strip() if len(parts) > 1 else None
    target_id = None
    target_name = None

    if target:
        u = target.from_user
        target_id = u.id
        target_name = u.full_name
    elif msg.entities:
        for entity in msg.entities:
            if entity.type == "mention":
                username = msg.text[entity.offset+1:entity.offset+entity.length]
                try:
                    chat = await ctx.bot.get_chat(f"@{username}")
                    target_id = chat.id
                    target_name = chat.full_name
                    specific_cmd = None
                except Exception:
                    await msg.reply_text(f"⚠️ User @{username} not found.")
                    return
    else:
        await msg.reply_text("↩️ Reply, mention, or use ID: //add @username [command]")
        return

    if not target_id:
        return

    admin_perms = load_admin_perms()

    if target_id not in admin_perms:
        admin_perms[target_id] = set()

    if specific_cmd is None or specific_cmd == "":
        admin_perms[target_id] = {"all"}
        save_admin_perms(admin_perms)
        await msg.reply_text(
            f"🎖️ {target_name} is admin of Zaxoy Bot now 🇵🇱",
            reply_to_message_id=target.message_id if target else None
        )
    elif specific_cmd in VALID_CMDS:
        admin_perms[target_id].add(specific_cmd)
        save_admin_perms(admin_perms)
        await msg.reply_text(
            f"✅ {target_name} can use {specific_cmd} now 🇵🇱",
            reply_to_message_id=target.message_id if target else None
        )
    else:
        await msg.reply_text(f"⚠️ Unknown command: {specific_cmd}")


# ─── //remove ────────────────────────────────────────────────────────
async def remove_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global admin_perms
    msg = update.message
    if msg.from_user.id != OWNER_ID:
        return
    target = msg.reply_to_message
    parts = msg.text.strip().split(None, 1)
    specific_cmd = parts[1].strip() if len(parts) > 1 else None

    target_id = None
    target_name = None

    if target:
        target_id = target.from_user.id
        target_name = target.from_user.full_name
    elif msg.entities:
        for entity in msg.entities:
            if entity.type == "mention":
                username = msg.text[entity.offset+1:entity.offset+entity.length]
                try:
                    chat = await ctx.bot.get_chat(f"@{username}")
                    target_id = chat.id
                    target_name = chat.full_name
                    specific_cmd = None
                except Exception:
                    await msg.reply_text(f"⚠️ User @{username} not found.")
                    return
    else:
        await msg.reply_text("↩️ Reply, mention, or use ID: //remove @username [command]")
        return

    admin_perms = load_admin_perms()
    perms = admin_perms.get(target_id, set())

    if specific_cmd is None or specific_cmd == "":
        admin_perms.pop(target_id, None)
        save_admin_perms(admin_perms)
        await msg.reply_text(
            f"😔 Sadly {target_name} can't use me now 🇵🇱",
            reply_to_message_id=target.message_id if target else None
        )
    elif specific_cmd in perms or "all" in perms:
        if "all" in perms:
            perms = VALID_CMDS.copy()
            perms.discard(specific_cmd)
        else:
            perms.discard(specific_cmd)

        if perms:
            admin_perms[target_id] = perms
        else:
            admin_perms.pop(target_id, None)

        save_admin_perms(admin_perms)
        await msg.reply_text(
            f"🗑️ {target_name}: {specific_cmd} has been removed 🇵🇱",
            reply_to_message_id=target.message_id if target else None
        )
    else:
        await msg.reply_text(f"⚠️ {target_name} didn't have {specific_cmd}")


# ─── //admin //list ──────────────────────────────────────────────────
async def admin_list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    
    if msg.from_user.id != OWNER_ID:
        return

    # Refresh from Supabase
    global admin_perms
    admin_perms = load_admin_perms()

    if not admin_perms:
        await msg.reply_text("📭 No admins yet.")
        return

    await msg.reply_text(f"📋 *{len(admin_perms)} admin(s):*", parse_mode="Markdown")

    for uid, perms in admin_perms.items():
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

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Remove All", callback_data=f"adminrm_{uid}"),
        ]])

        await msg.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def admin_list_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != OWNER_ID:
        return

    data = query.data

    if data.startswith("adminrm_"):
        uid = int(data[8:])
        admin_perms.pop(uid, None)
        save_admin_perms(admin_perms)
        await query.edit_message_text("✅ Admin removed 🇵🇱")


async def react_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not has_perm(msg.from_user.id, "//re"):
        await msg.reply_text("⛔ You don't have permission 🇵🇱")
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
        await msg.reply_text("⛔ You don't have permission 🇵🇱")
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
async def message_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip()

    if text.startswith("//info"):
        await info_cmd(update, ctx)
    elif text.startswith("//id"):
        await id_cmd(update, ctx)
    elif text.startswith("//r ") or text == "//r":
        await r_cmd(update, ctx)
    elif text.startswith("//say"):
        await say_cmd(update, ctx)
    elif text.startswith("//ask"):
        await ask_cmd(update, ctx)
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


    else:
        await zaxo_defense_handler(update, ctx)

        await waleed_protection(update, ctx)
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
    "🔊 Zaxoy's order has expired! {name} is free to speak again! 🇵🇱",
    "✅ Break is over {name}! You can type in the chat now! 🇵🇱",
    "🔓 The hammer is lifted! {name} has been unmuted! 🇵🇱"
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
        await _reply("💀 HAHAHAHAH NICE TRY! You have no power here 🗣️ 🇵🇱")
        return

    target = msg.reply_to_message
    uid = None
    target_name_str = None

    if target:
        uid = target.from_user.id
        target_name_str = target.from_user.full_name
    else:
        mention_id, mention_name = await resolve_target_from_mention(msg, ctx)
        if mention_id:
            uid = mention_id
            target_name_str = mention_name
        else:
            await _reply("↩️ Reply to a user or mention them: //warn @username")
            return

    if msg.from_user.id == uid:
        await _reply("🧠 Wanna warn yourself? You can't do that, bro! Friendly Fire is OFF 🇵🇱")
        return

    try:
        chat_member = await ctx.bot.get_chat_member(chat_id=chat_id, user_id=uid)

        if chat_member.status in ['administrator', 'creator']:
            await _reply("🛡️ Friendly fire! Watch out, you cannot warn another administrator! 🇵🇱")
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
            await _reply(f"🔨 {target_name_str} received 3/3 warnings and has been muted for 1 hour! 🇵🇱")
            return

        await ctx.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Warning ({count}/3) for {target_name_str}! 🇵🇱",
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
        await msg.reply_text("💀 HAHAHAHAH NICE TRY! You have no power here 🗣️ 🇵🇱")
        return

    target = msg.reply_to_message
    target_id = None
    target_name = None

    if target:
        target_id = target.from_user.id
        target_name = target.from_user.full_name
    else:
        mention_id, mention_name = await resolve_target_from_mention(msg, ctx)
        if mention_id:
            target_id = mention_id
            target_name = mention_name
        else:
            await msg.reply_text("↩️ Reply to a user or mention them: //mute @username [duration]")
            return


    # 3. Self-mute check
    if user_id == target_id:
        await msg.reply_text("🧠 Wanna kill yourself? You can't mute yourself, bro! 🇵🇱")
        return

    try:
        # Check target user status
        chat_member = await ctx.bot.get_chat_member(chat_id=msg.chat_id, user_id=target_id)
        
        # 4. Admin try to mute another Admin (Friendly Fire)
        if chat_member.status in ['administrator', 'creator']:
            await msg.reply_text("🛡️ Friendly fire... Watch out! He's an admin too! 🇵🇱")
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
        await msg.reply_text("💀 HAHAHAHAH NICE TRY! You have no power here 🗣️ 🇵🇱")
        return

    target = msg.reply_to_message
    target_id = None

    if target and target.from_user:
        target_id = target.from_user.id
    else:
        mention_id, mention_name = await resolve_target_from_mention(msg, ctx)
        if mention_id:
            target_id = mention_id
        else:
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
        await msg.reply_text(f"🔓 {member.user.full_name} has been unmuted! 🇵🇱")

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
                    text=f"⚠️ Warning removed by admin! {chat_member.user.full_name} now has ({warn_store[uid]}/3) warnings. 🇵🇱",
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
            await query.edit_message_text(text=f"🧹 Clean slate! {chat_member.user.full_name}'s warnings have been reset to (0/3)! 🇵🇱", reply_markup=None)
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
            await msg.delete()
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
        await msg.delete()
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
    "🔨 {name} has been banned from Zaxo's domain! No return. 🇵🇱",
    "⛓️ {name} is gone for good! Zaxo's law is final. 🇵🇱",
    "🚫 {name} — you crossed the line. Banned by order of Zaxoy Bot. 🇵🇱",
    "💀 {name} has been erased from Zaxo's kingdom! 🇵🇱",
    "⚔️ The sword has fallen! {name} is permanently banned! 🇵🇱",
    "🌑 {name} has entered the void — no way back. 🇵🇱",
]

async def ban_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    async def _reply(text, reply_markup=None):
        await msg.reply_text(text, reply_to_message_id=msg.message_id, reply_markup=reply_markup)

    if not has_perm(msg.from_user.id, "//ban"):
        await _reply("💀 HAHAHAHAH NICE TRY! You have no power here 🗣️ 🇵🇱")
        return

    target_id, target_name, _ = await resolve_target_user(msg, ctx)

    if not target_id:
        await _reply("↩️ Reply to a user or mention them: //ban @username")
        return

    if msg.from_user.id == target_id:
        await _reply("🧠 Ban yourself? That's not how it works bro! 🇵🇱")
        return

    try:
        chat_member = await ctx.bot.get_chat_member(chat_id=msg.chat.id, user_id=target_id)

        if chat_member.status in ['administrator', 'creator']:
            await _reply("🛡️ Friendly fire! You can't ban an admin! 🇵🇱")
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
            await query.edit_message_text("🔓 User has been unbanned 🇵🇱")
        except Exception as e:
            await query.edit_message_text(f"⚠️ Failed to unban:\n{e}")


# ─── //unban ─────────────────────────────────────────────────────────
async def unban_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if not has_perm(msg.from_user.id, "//ban"):
        await msg.reply_text("💀 HAHAHAHAH NICE TRY! You have no power here 🗣️ 🇵🇱")
        return

    user_id, user_name, _ = await resolve_target_user(msg, ctx)

    if not user_id:
        await msg.reply_text("↩️ Reply, mention, or provide an ID: //unban @username")
        return

    try:
        await ctx.bot.unban_chat_member(chat_id=msg.chat.id, user_id=user_id)
        await msg.reply_text(f"🔓 {user_name} has been unbanned 🇵🇱")
    except Exception as e:
        if "USER_NOT_BANNED" in str(e):
            await msg.reply_text(f"⚠️ {user_name} is not banned! 🇵🇱")
        else:
            await msg.reply_text(f"⚠️ Failed to unban:\\n{e}")


def main():

    start_keep_alive()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.ALL, cache_user_message), group=-1)

    # 1. Normal Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("on", on_cmd))
    app.add_handler(CommandHandler("off", off_cmd))
    app.add_handler(CommandHandler("choose", choose_cmd))
    app.add_handler(CommandHandler("xo", xo_handler))

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
    ))

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
        pattern="^adminrm_"
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
        filters.Regex(r"^//"),
        message_router
    ))

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        message_router
    ))

    print("Zaxoy Bot started 🇵🇱")

    app.run_polling()


if __name__ == "__main__":
    main()
