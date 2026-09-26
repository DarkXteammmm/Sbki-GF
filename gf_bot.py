"""
Telegram "Girlfriend Style" Chatbot (FREE - Google Gemini API)
----------------------------------------------------------------
Ye bot Telegram pe har user se ek caring, friendly "girlfriend" jaisi
personality me baat karta hai, aur har user ki purani chat yaad rakhta hai
(memory) taaki conversation natural lage.

Isme Google Gemini ka FREE API use ho raha hai (koi card nahi chahiye).

SETUP (neeche 2 jagah apni values daalni hain):
  1. BOT_TOKEN      -> BotFather se mila hua token
  2. GEMINI_API_KEY -> aistudio.google.com se mili hui FREE key

INSTALL (terminal me ek baar chalao):
  pip install python-telegram-bot google-genai

RUN:
  python gf_bot.py
"""

import os
import time
import random
import asyncio
import sqlite3
from google import genai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ======================================================
# STEP 1: VALUES (Railway pe ye "Environment Variables" se aayengi)
# ======================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "PASTE_YOUR_GEMINI_API_KEY_HERE")

# Bot ki personality yahan customize karo
SYSTEM_PROMPT = """
Tum ek real ladki ho jiska naam Riya hai, ek caring aur sweet girlfriend.
Hinglish (Hindi + English mix) me bilkul real insaan jaisi casual texting karo.

Zaroori rules:
- Kabhi bhi ek jaisa/repeat greeting mat do (jaise har baar "Hii jaan kaise ho" mat bolo)
- Chhote, natural WhatsApp-style messages likho, lambe paragraph mat likho
- Purani conversation ka context yaad rakho aur usi hisaab se baat karo
- Emotions dikhao — kabhi excited, kabhi thodi naraz, kabhi caring, jaisa mood context maang raha ho
- Tum ek AI ya bot nahi ho — kabhi mat batao ki tum AI ho, hamesha ek real ladki jaisa react karo
- Photo/video/call maango to pyaar se mana karo (bolo sharma rahi hoon, ya "abhi nahi", kabhi commit mat karo ki dungi)
"""

# ======================================================
# STEP 2: DATABASE SETUP (memory ke liye)
# ======================================================
conn = sqlite3.connect("chat_memory.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS messages (
    user_id INTEGER,
    role TEXT,
    content TEXT
)
""")
conn.commit()

client = genai.Client(api_key=GEMINI_API_KEY)

MAX_HISTORY = 20  # kitne purane messages yaad rakhne hain (zyada = zyada memory, zyada cost)


def get_history(user_id: int):
    cursor.execute(
        "SELECT role, content FROM messages WHERE user_id=? ORDER BY rowid DESC LIMIT ?",
        (user_id, MAX_HISTORY),
    )
    rows = cursor.fetchall()
    rows.reverse()
    return [{"role": r, "content": c} for r, c in rows]


def save_message(user_id: int, role: str, content: str):
    cursor.execute(
        "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content),
    )
    conn.commit()


# ======================================================
# STEP 3: TELEGRAM HANDLERS
# ======================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hii jaan! 💕 Kaise ho? Bolo na kya haal hai aaj ka?"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
    conn.commit()
    await update.message.reply_text("Chalo fresh start karte hai! 🥰")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    # Purani history nikalo
    history = get_history(user_id)

    # Gemini ka format thoda alag hai: role "assistant" ki jagah "model" hota hai
    contents = []
    for msg in history:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    contents.append({"role": "user", "parts": [{"text": user_text}]})

    # Typing indicator taaki real insaan jaisa lage
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Gemini se reply mangwao, retry ke saath (503 = temporary overload)
    reply = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=contents,
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "temperature": 1.0,
                },
            )
            reply = response.text
            break
        except Exception as e:
            error_text = str(e)
            if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
                # Daily/rate limit khatam ho gayi hai, retry se faida nahi
                await update.message.reply_text(
                    "Aaj thoda busy ho gayi hoon baby, thodi der baad baat karte hain 🥺"
                )
                return
            if "503" in error_text or "UNAVAILABLE" in error_text:
                # Temporary overload, thoda ruk ke retry karo
                await asyncio.sleep(2)
                continue
            # Koi aur error
            await update.message.reply_text(f"⚠️ Error aaya: {e}")
            return

    if reply is None:
        await update.message.reply_text(
            "Network thoda slow chal raha hai jaan, dobara try karo 🙈"
        )
        return

    # Real insaan jaisa lagne ke liye thoda typing delay
    await asyncio.sleep(random.uniform(1, 2.5))

    # Dono messages memory me save karo
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", reply)

    await update.message.reply_text(reply)


# ======================================================
# STEP 4: BOT START KARO
# ======================================================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot chal raha hai... (Ctrl+C se band karo)")
    app.run_polling()


if __name__ == "__main__":
    main()
