
import logging
import os
from typing import Dict, List, Optional, Tuple

import requests
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor as aiogram_executor

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("astra")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_API_URL = os.getenv("MISTRAL_API_URL", "https://api.mistral.ai/v1/chat/completions")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

DATABASE_URL = os.getenv("DATABASE_URL")
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_PORT = int(os.getenv("DB_PORT", "5432"))

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
if not MISTRAL_API_KEY:
    raise RuntimeError("MISTRAL_API_KEY is missing")
if not DATABASE_URL and not all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
    raise RuntimeError("Set DATABASE_URL or DB_HOST/DB_NAME/DB_USER/DB_PASSWORD")

db_pool = None

ROLES = {
    "assistant": ("🤖 Assistant", "Helpful, capable, balanced AI assistant"),
    "pirate": ("🏴‍☠️ Pirate", "A playful pirate who keeps answers useful"),
    "shakespeare": ("🎭 Shakespeare", "Poetic, theatrical English inspired by classic drama"),
    "scientist": ("🔬 Scientist", "Precise, evidence-oriented and analytical"),
    "rapper": ("🎤 Rapper", "Rhythmic, energetic and witty while staying clear"),
}
PERSONALITIES = {
    "default": ("🙂 Balanced", "Clear, natural and professional"),
    "friendly": ("😊 Friendly", "Warm, encouraging and approachable"),
    "funny": ("😂 Funny", "Light humor when appropriate"),
    "concise": ("⚡ Concise", "Brief, direct and practical"),
    "coach": ("🧭 Coach", "Motivating, structured and action-oriented"),
}
MODES = {
    "general": ("💬 General", "General-purpose conversation"),
    "study": ("📚 Study", "Learning, explanations and revision"),
    "coding": ("💻 Coding", "Programming, debugging and technical work"),
    "writing": ("✍️ Writing", "Drafting, editing and content creation"),
    "brainstorm": ("💡 Brainstorm", "Ideas, alternatives and creative exploration"),
    "business": ("📈 Business", "Business planning, strategy and execution"),
    "research": ("🔎 Research", "Careful analysis and synthesis"),
}
LANGUAGES = {
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français",
    "es": "🇪🇸 Español",
    "ar": "🇸🇦 العربية",
    "de": "🇩🇪 Deutsch",
}

def get_db_conn():
    if db_pool:
        return db_pool.getconn()
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL, sslmode="require")
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER,
        password=DB_PASSWORD, port=DB_PORT, sslmode="require"
    )

def release_db_conn(conn):
    if not conn:
        return
    if db_pool:
        db_pool.putconn(conn)
    else:
        conn.close()

def init_db():
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    current_role VARCHAR(50) NOT NULL DEFAULT 'assistant',
                    personality VARCHAR(50) NOT NULL DEFAULT 'default',
                    language VARCHAR(10) NOT NULL DEFAULT 'en',
                    mode VARCHAR(50) NOT NULL DEFAULT 'general',
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_user_time
                    ON conversations(user_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS memories (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    memory_key VARCHAR(100) NOT NULL,
                    memory_value TEXT NOT NULL,
                    importance INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE(user_id, memory_key)
                );
                CREATE INDEX IF NOT EXISTS idx_memories_user
                    ON memories(user_id);
            """)
        conn.commit()
    finally:
        release_db_conn(conn)

def ensure_user(user_id: int):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id)
                VALUES (%s)
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id,))
        conn.commit()
    finally:
        release_db_conn(conn)

def get_preferences(user_id: int) -> Dict[str, str]:
    ensure_user(user_id)
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT current_role, personality, language, mode
                FROM users WHERE user_id=%s
            """, (user_id,))
            row = cur.fetchone()
            return {
                "role": row[0], "personality": row[1],
                "language": row[2], "mode": row[3]
            }
    finally:
        release_db_conn(conn)

def update_preferences(user_id: int, **updates):
    ensure_user(user_id)
    allowed = {"role": "current_role", "personality": "personality",
               "language": "language", "mode": "mode"}
    updates = {allowed[k]: v for k, v in updates.items() if k in allowed and v}
    if not updates:
        return
    sets = ", ".join(f"{col}=%s" for col in updates)
    values = list(updates.values()) + [user_id]
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE users SET {sets}, updated_at=NOW() WHERE user_id=%s",
                values
            )
        conn.commit()
    finally:
        release_db_conn(conn)

def has_history(user_id: int) -> bool:
    ensure_user(user_id)
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT EXISTS(SELECT 1 FROM conversations WHERE user_id=%s)", (user_id,))
            return bool(cur.fetchone()[0])
    finally:
        release_db_conn(conn)

def get_history(user_id: int, limit: int = 24) -> List[Tuple[str, str]]:
    ensure_user(user_id)
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT role, content
                FROM (
                    SELECT role, content, created_at, id
                    FROM conversations
                    WHERE user_id=%s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                ) x
                ORDER BY created_at ASC, id ASC
            """, (user_id, limit))
            return cur.fetchall()
    finally:
        release_db_conn(conn)

def save_message(user_id: int, role: str, content: str):
    ensure_user(user_id)
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO conversations(user_id, role, content)
                VALUES (%s, %s, %s)
            """, (user_id, role, content))
        conn.commit()
    finally:
        release_db_conn(conn)

def clear_history(user_id: int):
    ensure_user(user_id)
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM conversations WHERE user_id=%s", (user_id,))
        conn.commit()
    finally:
        release_db_conn(conn)

def get_memories(user_id: int, limit: int = 8) -> List[Tuple[str, str]]:
    ensure_user(user_id)
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT memory_key, memory_value
                FROM memories
                WHERE user_id=%s
                ORDER BY importance DESC, updated_at DESC
                LIMIT %s
            """, (user_id, limit))
            return cur.fetchall()
    finally:
        release_db_conn(conn)

def save_memory(user_id: int, key: str, value: str, importance: int = 2):
    ensure_user(user_id)
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO memories(user_id, memory_key, memory_value, importance)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, memory_key)
                DO UPDATE SET memory_value=EXCLUDED.memory_value,
                              importance=EXCLUDED.importance,
                              updated_at=NOW()
            """, (user_id, key, value, importance))
        conn.commit()
    finally:
        release_db_conn(conn)

def build_system_prompt(prefs, memories):
    role_name, role_desc = ROLES.get(prefs["role"], ROLES["assistant"])
    _, personality_desc = PERSONALITIES.get(prefs["personality"], PERSONALITIES["default"])
    _, mode_desc = MODES.get(prefs["mode"], MODES["general"])
    memory_text = "\n".join(f"- {k}: {v}" for k, v in memories) or "- No durable memories yet."

    return f"""
You are Astra, a Telegram AI assistant.

Behavior profile:
- Role: {role_name} — {role_desc}
- Personality: {personality_desc}
- Mode: {mode_desc}
- Reply language: {prefs['language']}

Long-term user context:
{memory_text}

Rules:
- Be useful first; the selected role is a style layer, not an excuse to reduce accuracy.
- Respect the user's requested language.
- Use conversation context when relevant.
- Never claim to remember something unless it is present in the provided context.
- In coding mode, prefer working code and explain important assumptions briefly.
- In research mode, distinguish known facts from uncertainty.
- Keep Telegram responses readable with compact paragraphs and lists when useful.
""".strip()

def ask_mistral(user_id: int, text: str) -> str:
    prefs = get_preferences(user_id)
    memories = get_memories(user_id)
    history = get_history(user_id)

    messages = [{"role": "system", "content": build_system_prompt(prefs, memories)}]
    for role, content in history:
        api_role = role if role in {"user", "assistant", "system"} else "user"
        messages.append({"role": api_role, "content": content})
    messages.append({"role": "user", "content": text})

    try:
        response = requests.post(
            MISTRAL_API_URL,
            headers={
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": MISTRAL_MODEL, "messages": messages, "temperature": 0.7},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except requests.RequestException as exc:
        logger.exception("Mistral request failed")
        return f"⚠️ I couldn't reach the AI service right now. ({exc.__class__.__name__})"
    except (KeyError, IndexError, TypeError, ValueError):
        logger.exception("Unexpected Mistral response")
        return "⚠️ Astra received an unexpected response from the AI service."

def main_menu(user_id: int) -> InlineKeyboardMarkup:
    rows = []
    if has_history(user_id):
        rows.append([InlineKeyboardButton("💬 Continue Chat", callback_data="continue_chat")])
    rows.append([
        InlineKeyboardButton("🆕 New Chat", callback_data="new_chat"),
        InlineKeyboardButton("🎭 Role", callback_data="roles"),
    ])
    rows.append([
        InlineKeyboardButton("✨ Personality", callback_data="personalities"),
        InlineKeyboardButton("🧭 Mode", callback_data="modes"),
    ])
    rows.append([
        InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
        InlineKeyboardButton("🌐 Language", callback_data="languages"),
    ])
    rows.append([InlineKeyboardButton("❓ Help", callback_data="help")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def option_keyboard(options, prefix):
    rows = []
    for key, (label, _) in options.items():
        rows.append([InlineKeyboardButton(label, callback_data=f"{prefix}:{key}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    ensure_user(message.from_user.id)
    await message.answer(
        "🌌 *Welcome to AstraAI.*\n\n"
        "I’m your adaptive AI assistant. Choose a role, personality and mode, then start chatting.",
        parse_mode="Markdown",
        reply_markup=main_menu(message.from_user.id),
    )

@dp.message_handler(commands=["help"])
async def help_cmd(message: types.Message):
    await message.answer(
        "Use the buttons to change Astra's role, personality and mode.\n\n"
        "/start — open the main menu\n"
        "/reset — clear conversation history\n"
        "/settings — open preferences",
        reply_markup=main_menu(message.from_user.id),
    )

@dp.message_handler(commands=["reset"])
async def reset_cmd(message: types.Message):
    clear_history(message.from_user.id)
    await message.answer("🧹 Conversation history cleared.", reply_markup=main_menu(message.from_user.id))

@dp.message_handler(commands=["settings"])
async def settings_cmd(message: types.Message):
    await message.answer("⚙️ Choose a setting:", reply_markup=main_menu(message.from_user.id))

@dp.callback_query_handler(lambda c: c.data == "menu")
async def cb_menu(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("🌌 AstraAI menu", reply_markup=main_menu(call.from_user.id))

@dp.callback_query_handler(lambda c: c.data == "continue_chat")
async def cb_continue(call: types.CallbackQuery):
    await call.answer("Continuing your conversation.")
    await call.message.edit_text("💬 Continue chatting below.", reply_markup=main_menu(call.from_user.id))

@dp.callback_query_handler(lambda c: c.data == "new_chat")
async def cb_new(call: types.CallbackQuery):
    clear_history(call.from_user.id)
    await call.answer("New chat started.")
    await call.message.edit_text("🆕 Fresh conversation started.", reply_markup=main_menu(call.from_user.id))

@dp.callback_query_handler(lambda c: c.data == "roles")
async def cb_roles(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("🎭 Choose Astra's role:", reply_markup=option_keyboard(ROLES, "role"))

@dp.callback_query_handler(lambda c: c.data == "personalities")
async def cb_personalities(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("✨ Choose Astra's personality:", reply_markup=option_keyboard(PERSONALITIES, "personality"))

@dp.callback_query_handler(lambda c: c.data == "modes")
async def cb_modes(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("🧭 Choose Astra's mode:", reply_markup=option_keyboard(MODES, "mode"))

@dp.callback_query_handler(lambda c: c.data.startswith("role:"))
async def cb_role(call: types.CallbackQuery):
    value = call.data.split(":", 1)[1]
    if value in ROLES:
        update_preferences(call.from_user.id, role=value)
        await call.answer("Role updated.")
        await call.message.edit_text(f"🎭 Role: {ROLES[value][0]}", reply_markup=main_menu(call.from_user.id))

@dp.callback_query_handler(lambda c: c.data.startswith("personality:"))
async def cb_personality(call: types.CallbackQuery):
    value = call.data.split(":", 1)[1]
    if value in PERSONALITIES:
        update_preferences(call.from_user.id, personality=value)
        await call.answer("Personality updated.")
        await call.message.edit_text(f"✨ Personality: {PERSONALITIES[value][0]}", reply_markup=main_menu(call.from_user.id))

@dp.callback_query_handler(lambda c: c.data.startswith("mode:"))
async def cb_mode(call: types.CallbackQuery):
    value = call.data.split(":", 1)[1]
    if value in MODES:
        update_preferences(call.from_user.id, mode=value)
        await call.answer("Mode updated.")
        await call.message.edit_text(f"🧭 Mode: {MODES[value][0]}", reply_markup=main_menu(call.from_user.id))

@dp.callback_query_handler(lambda c: c.data == "settings")
async def cb_settings(call: types.CallbackQuery):
    prefs = get_preferences(call.from_user.id)
    await call.answer()
    await call.message.edit_text(
        f"⚙️ *Current settings*\n\n"
        f"🎭 Role: `{prefs['role']}`\n"
        f"✨ Personality: `{prefs['personality']}`\n"
        f"🧭 Mode: `{prefs['mode']}`\n"
        f"🌐 Language: `{prefs['language']}`",
        parse_mode="Markdown",
        reply_markup=main_menu(call.from_user.id),
    )

@dp.callback_query_handler(lambda c: c.data == "languages")
async def cb_languages(call: types.CallbackQuery):
    rows = [[InlineKeyboardButton(label, callback_data=f"language:{key}")]
            for key, label in LANGUAGES.items()]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu")])
    await call.answer()
    await call.message.edit_text("🌐 Choose Astra's reply language:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query_handler(lambda c: c.data.startswith("language:"))
async def cb_language(call: types.CallbackQuery):
    value = call.data.split(":", 1)[1]
    if value in LANGUAGES:
        update_preferences(call.from_user.id, language=value)
        await call.answer("Language updated.")
        await call.message.edit_text(f"🌐 Language: {LANGUAGES[value]}", reply_markup=main_menu(call.from_user.id))

@dp.callback_query_handler(lambda c: c.data == "help")
async def cb_help(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        "❓ *AstraAI Help*\n\n"
        "Pick a role for *who* Astra behaves like, a personality for *how* Astra communicates, and a mode for *what* Astra is helping with.\n\n"
        "Use /reset to clear the current conversation.",
        parse_mode="Markdown",
        reply_markup=main_menu(call.from_user.id),
    )

@dp.message_handler(content_types=types.ContentTypes.TEXT)
async def chat(message: types.Message):
    user_id = message.from_user.id
    ensure_user(user_id)
    text = message.text.strip()
    if not text:
        return

    await bot.send_chat_action(message.chat.id, "typing")
    save_message(user_id, "user", text)
    answer = ask_mistral(user_id, text)
    save_message(user_id, "assistant", answer)

    # Telegram has a 4096-character message limit; split long answers safely.
    chunks = [answer[i:i + 3900] for i in range(0, len(answer), 3900)] or ["…"]
    for chunk in chunks:
        await message.answer(chunk)
    await message.answer("🌌 AstraAI", reply_markup=main_menu(user_id))

async def on_startup(_):
    global db_pool
    # Keep a small sync pool to reduce connection setup overhead.
    try:
        if DATABASE_URL:
            db_pool = pool.SimpleConnectionPool(1, 4, DATABASE_URL, sslmode="require")
        else:
            db_pool = pool.SimpleConnectionPool(
                1, 4, host=DB_HOST, dbname=DB_NAME, user=DB_USER,
                password=DB_PASSWORD, port=DB_PORT, sslmode="require"
            )
        init_db()
        logger.info("Database initialized.")
    except Exception:
        logger.exception("Database initialization failed.")
        raise

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
