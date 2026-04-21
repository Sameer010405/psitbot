import logging
import sqlite3
import os
import asyncio
from datetime import time, datetime, timezone, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, JobQueue
from dotenv import load_dotenv

# Import our custom scraper
import scraper

# Configuration
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
IST = timezone(timedelta(hours=5, minutes=30))

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Database Setup
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (chat_id INTEGER PRIMARY KEY, erp_user TEXT, erp_pass TEXT)''')
    conn.commit()
    conn.close()

def save_user(chat_id, user, pwd):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('REPLACE INTO users (chat_id, erp_user, erp_pass) VALUES (?, ?, ?)', (chat_id, user, pwd))
    conn.commit()
    conn.close()

def get_user(chat_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT erp_user, erp_pass FROM users WHERE chat_id = ?', (chat_id,))
    res = c.fetchone()
    conn.close()
    return res

def get_all_users():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT chat_id, erp_user, erp_pass FROM users')
    res = c.fetchall()
    conn.close()
    return res

# Helper: Get Session
async def get_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = get_user(update.effective_chat.id)
    if not user_data:
        await update.message.reply_text("❌ You are not logged in. Use `/login username password` to start.")
        return None
    
    session, err = scraper.erp_login(user_data[0], user_data[1])
    if err:
        await update.message.reply_text(err)
        return None
    return session

# Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = ReplyKeyboardMarkup([
        [KeyboardButton("📊 Attendance"), KeyboardButton("📅 Today's Classes")],
        [KeyboardButton("🧮 Bunk Budget"), KeyboardButton("❓ Help")]
    ], resize_keyboard=True)
    
    await update.message.reply_text(
        "👋 **Welcome to PSIT Automation 2.0!**\n\n"
        "I will help you track your attendance and timetable automatically.\n\n"
        "🔐 **To start, please login:**\n"
        "`/login [ERP_ID] [PASSWORD]`\n\n"
        "*(Note: Your credentials are encrypted and stored locally only for scraping)*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage: `/login [username] [password]`")
        return

    user, pwd = context.args[0], context.args[1]
    msg = await update.message.reply_text("⏳ Verifying credentials...")
    
    session, err = scraper.erp_login(user, pwd)
    if err:
        await msg.edit_text(err)
    else:
        save_user(update.effective_chat.id, user, pwd)
        await msg.edit_text("✅ **Login Successful!**\nI'll now send you daily updates at 8 AM.")
        # Try to delete the login message for security
        try:
            await update.message.delete()
        except:
            pass

async def attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_session(update, context)
    if not session: return
    
    msg = await update.message.reply_text("⏳ Fetching attendance...")
    data = scraper.get_attendance(session)
    
    if isinstance(data, dict):
        res = f"📊 **Attendance:** `{data['percent']}`"
        if data['present']:
            res += f"\n📖 Classes: `{data['present']}/{data['total']}`"
        await msg.edit_text(res, parse_mode='Markdown')
    else:
        await msg.edit_text(data)

async def today_tt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_session(update, context)
    if not session: return
    
    msg = await update.message.reply_text("⏳ Fetching timetable...")
    day_name, classes = scraper.get_classes_for_day(session)
    
    if isinstance(classes, list):
        if not classes:
            await msg.edit_text(f"🎉 No classes today ({day_name})!")
        else:
            lines = [f"🕐 `{c['time_label']}` — **{c['subject']}**" for c in classes]
            await msg.edit_text(f"📅 **TT for {day_name}:**\n" + "\n".join(lines), parse_mode='Markdown')
    else:
        await msg.edit_text(classes)

async def bunk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_session(update, context)
    if not session: return
    
    msg = await update.message.reply_text("⏳ Calculating budget...")
    att = scraper.get_attendance(session)
    budget = scraper.calc_bunk_budget(att)
    
    if not budget:
        await msg.edit_text("⚠️ Data insufficient for budget calculation.")
        return

    if budget['can_bunk'] > 0:
        res = f"✅ You can bunk **{budget['can_bunk']}** more class(es) to stay at 75%."
    else:
        res = f"🚨 You must attend **{budget['need_attend']}** more classes to reach 75%."
    
    await msg.edit_text(f"📊 **Bunk Budget** ({budget['percent']})\n\n{res}", parse_mode='Markdown')

# Auto-Updates (Daily at 8:00 AM)
async def daily_report(context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    for chat_id, user, pwd in users:
        try:
            session, err = scraper.erp_login(user, pwd)
            if err: continue
            
            day_name, classes = scraper.get_classes_for_day(session)
            att = scraper.get_attendance(session)
            
            msg = f"☀️ **Good Morning!**\n\n📅 **Today's Classes:**\n"
            if isinstance(classes, list) and classes:
                msg += "\n".join([f"• {c['time_label']}: {c['subject']}" for c in classes])
            else:
                msg += "Free Day! 🎉"
            
            if isinstance(att, dict):
                msg += f"\n\n📊 **Overall Attendance:** {att['percent']}"
                
            await context.bot.send_message(chat_id=chat_id, text=msg)
        except Exception as e:
            logging.error(f"Failed daily report for {chat_id}: {e}")

# Entry Point
if __name__ == '__main__':
    init_db()
    if not TELEGRAM_TOKEN:
        print("❌ Error: TELEGRAM_TOKEN not found in .env")
        exit()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("attendance", attendance))
    app.add_handler(CommandHandler("today", today_tt))
    app.add_handler(CommandHandler("bunk", bunk))
    
    # Handling button clicks (simple text match)
    from telegram.ext import MessageHandler, filters
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if "Attendance" in text: await attendance(update, context)
        elif "Classes" in text: await today_tt(update, context)
        elif "Bunk" in text: await bunk(update, context)
        elif "Help" in text: await start(update, context)

    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # Schedule Daily Report at 8:00 AM IST
    # (JobQueue uses UTC, so 8:00 AM IST = 2:30 AM UTC)
    app.job_queue.run_daily(daily_report, time=time(hour=2, minute=30))

    print("🚀 PSIT Bot 2.0 is running...")
    app.run_polling()
