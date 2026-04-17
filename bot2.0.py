import requests
import discord
from discord.ext import tasks
from bs4 import BeautifulSoup
from datetime import datetime
import asyncio
from flask import Flask
from threading import Thread

import os

# ─────────────────────────────────────────
#  CONFIGURATION — fill these in via Environment Variables
# ─────────────────────────────────────────
ERP_USER        = os.getenv("ERP_USER", "").strip()
ERP_PASSWORD    = os.getenv("ERP_PASSWORD", "").strip()
DISCORD_TOKEN   = os.getenv("DISCORD_TOKEN", "").strip()

try:
    _user_id_str = os.getenv("DISCORD_USER_ID", "").strip()
    DISCORD_USER_ID = int(_user_id_str) if _user_id_str else 0
except ValueError:
    DISCORD_USER_ID = 0

# Time to send the daily message (24hr format, IST)
SEND_HOUR   = 7
SEND_MINUTE = 0
# ─────────────────────────────────────────

BASE_URL        = "https://erp.psit.ac.in"
LOGIN_URL       = BASE_URL          # login form is on the homepage
TT_URL          = f"{BASE_URL}/Student/MyTimeTable"
ATTENDANCE_URL  = f"{BASE_URL}/Student/MyAttendanceDetail"

DAY_NAMES = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

def erp_login():
    """Create an authenticated ERP session. Returns (session, error_msg)."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/120 Safari/537.36",
    })

    # ── Step 1: Load homepage (this is where the login form lives) ──
    r = session.get(BASE_URL, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")

    # ── Step 2: Find the form's POST action URL ──
    form = soup.find("form")
    if form and form.get("action"):
        action = form["action"]
        # Make absolute if relative
        if action.startswith("/"):
            post_url = BASE_URL + action
        elif action.startswith("http"):
            post_url = action
        else:
            post_url = BASE_URL + "/" + action
    else:
        post_url = BASE_URL  # fallback: POST to homepage

    # ── Step 3: Build payload using field names from the actual form ──
    # Debug showed: name='username', name='password' (all lowercase)
    payload = {
        "username": ERP_USER,
        "password": ERP_PASSWORD,
    }

    # Include any hidden fields (e.g. CSRF tokens)
    for hidden in soup.find_all("input", {"type": "hidden"}):
        fname = hidden.get("name")
        fval  = hidden.get("value", "")
        if fname:
            payload[fname] = fval

    login_resp = session.post(post_url, data=payload, timeout=15, allow_redirects=True)
    final_url  = login_resp.url.lower()
    body_lower = login_resp.text.lower()

    logged_in = (
        "logout"    in body_lower or
        "dashboard" in final_url  or
        "student"   in final_url  or
        "home"      in final_url  or
        ("login"    not in final_url and login_resp.status_code == 200)
    )

    if logged_in:
        print(f"✅ ERP login succeeded → {login_resp.url}")
        return session, None

    return None, "❌ Login failed. Check your ERP credentials in the script."


# ─────────────────────────────────────────
#  Session Cache — avoids re-logging in every minute
# ─────────────────────────────────────────
_cached_session = None

def get_session():
    """
    Return a valid ERP session, reusing the cached one if still alive.
    Only calls erp_login() when the session has expired or doesn't exist.
    """
    global _cached_session
    if _cached_session is not None:
        try:
            check = _cached_session.get(f"{BASE_URL}/Student/", timeout=10)
            if "logout" in check.text.lower():
                return _cached_session, None   # still valid ✅
        except Exception:
            pass  # fall through to re-login
    # Session expired or never created — log in fresh
    _cached_session, err = erp_login()
    return _cached_session, err


def get_classes_for_day(session, day_offset=0):
    """
    Fetch timetable for a given day offset (0=today, 1=tomorrow).
    Returns (day_name, classes_list_or_str).
    classes_list is a list of dicts: {time_label, subject, start_time (datetime or None)}
    """
    tt_resp = session.get(TT_URL, timeout=15)
    tt_soup = BeautifulSoup(tt_resp.text, "html.parser")

    day_idx  = (datetime.now().weekday() + day_offset) % 7
    day_name = DAY_NAMES[day_idx]

    table = tt_soup.find("table")
    if not table:
        return day_name, "⚠️ Couldn't find timetable. ERP layout may have changed."

    rows    = table.find_all("tr")
    headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
    classes = []

    for row in rows[1:]:
        cols      = row.find_all(["td", "th"])
        row_label = cols[0].get_text(strip=True) if cols else ""
        if day_name.lower() in row_label.lower():
            for i, col in enumerate(cols[1:], start=1):
                subject = col.get_text(strip=True)
                if subject and subject not in ["-", "–", ""]:
                    time_label = headers[i] if i < len(headers) else f"Slot {i}"
                    start_time = parse_time(time_label)
                    classes.append({
                        "time_label": time_label,
                        "subject":    subject,
                        "start_time": start_time,
                    })
            break

    return day_name, classes


def parse_time(time_str):
    """
    Try to parse a time string like '9:00 AM', '09:00', '9:00-10:00' into a datetime.today() object.
    Returns a datetime or None if unparseable.
    """
    import re
    # Extract the first time occurrence e.g. "9:00 AM" or "09:00"
    match = re.search(r'(\d{1,2}:\d{2})\s*(AM|PM)?', time_str, re.IGNORECASE)
    if not match:
        return None
    time_part = match.group(1)
    ampm      = match.group(2)
    try:
        if ampm:
            t = datetime.strptime(f"{time_part} {ampm.upper()}", "%I:%M %p")
        else:
            t = datetime.strptime(time_part, "%H:%M")
        now = datetime.now()
        return now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    except ValueError:
        return None


def get_today_classes(session):
    return get_classes_for_day(session, day_offset=0)


def format_classes(classes):
    """Convert list of class dicts to display lines."""
    return [f"🕐 **{c['time_label']}** — {c['subject']}" for c in classes]



def calc_bunk_budget(attendance):
    """
    Given attendance dict {present, total, percent},
    return how many classes can be skipped while staying >= 75%.
    Also returns how many need to be attended to reach 75% if below.
    """
    if not isinstance(attendance, dict):
        return None
    try:
        present = int(attendance["present"])
        total   = int(attendance["total"])
    except (TypeError, ValueError):
        return None

    # Classes that can be bunked: solve (present / (total + x)) >= 0.75  →  x <= present/0.75 - total
    can_bunk = max(0, int(present / 0.75 - total))

    # Classes needed to reach 75% if below: solve (present + x) / (total + x) >= 0.75
    # → x >= (0.75*total - present) / 0.25
    need_attend = 0
    if present / total < 0.75:
        need_attend = max(0, int((0.75 * total - present) / 0.25) + 1)

    return {"can_bunk": can_bunk, "need_attend": need_attend, "present": present, "total": total}


def get_attendance(session):
    """
    Fetch overall attendance percentage from the ERP.
    Returns a dict: {present, total, percent} or an error string.
    """
    import re
    resp = session.get(ATTENDANCE_URL, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")

    full_text = soup.get_text(" ", strip=True).lower()
    percent_str = None
    
    # Look for "attendance % with pf : 80.65 %" in the raw text
    match_pct = re.search(r'attendance\s*%\s*with\s*pf\s*:\s*([\d\.]+)', full_text)
    if not match_pct:
        match_pct = re.search(r'attendance\s*%\s*without\s*pf\s*:\s*([\d\.]+)', full_text)

    if match_pct:
        percent_str = match_pct.group(1) + "%"
    else:
        return "⚠️ Couldn't find overall attendance percentage on the new layout."

    # Search for "Total Lecture" from the text
    present = None
    total = None
    
    tot_match = re.search(r'total lecture\s*:\s*(\d+)', full_text)
    
    if tot_match:
        try:
            total = int(tot_match.group(1))
            # The ERP gives percentage, so we calculate exact 'present' classes from it
            if percent_str:
                pct_val = float(percent_str.replace('%', ''))
                present = round(total * (pct_val / 100.0))
        except ValueError:
            pass

    return {"present": present, "total": total, "percent": percent_str}


def attendance_emoji(percent_str):
    """Return an emoji based on attendance percentage."""
    try:
        pct = float(percent_str.replace("%", ""))
        if pct >= 75:
            return "✅"
        elif pct >= 65:
            return "⚠️"
        else:
            return "🚨"
    except ValueError:
        return "❓"


# ─────────────────────────────────────────
#  Discord Bot
# ─────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True          # needed to read messages
client  = discord.Client(intents=intents)

COMMANDS_HELP = """
**📖 PSIT Bot Commands:**
`!today` — Today's classes
`!tomorrow` — Tomorrow's classes
`!attendance` — Your current overall attendance
`!bunk` — How many classes you can skip (or need to attend)
`!help` — Show this message

🔔 **Auto reminders are on** — you'll get a ping 2 mins before each class!
""".strip()

# Track which reminders have already been sent today (set of subjects)
reminders_sent = set()
reminders_date = None   # the date reminders_sent belongs to

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    daily_timetable.start()
    class_reminders.start()

@client.event
async def on_message(message):
    # Only respond to your own messages (DMs or server)
    if message.author.id != DISCORD_USER_ID:
        return
    if message.author.bot:
        return

    cmd = message.content.strip().lower()

    if cmd == "!help":
        await message.channel.send(COMMANDS_HELP)

    elif cmd in ("!today", "!tomorrow", "!attendance", "!bunk"):
        thinking = await message.channel.send("⏳ Fetching from ERP...")

        session, err = get_session()
        if err:
            await thinking.edit(content=err)
            return

        if cmd == "!today":
            day_name, classes = get_today_classes(session)
            if isinstance(classes, list) and classes:
                lines = "\n".join(format_classes(classes))
                reply = f"📅 **Classes for {day_name}:**\n{lines}"
            elif isinstance(classes, list):
                reply = f"🎉 No classes today ({day_name})! Free day!"
            else:
                reply = classes
            await thinking.edit(content=reply)

        elif cmd == "!tomorrow":
            day_name, classes = get_classes_for_day(session, day_offset=1)
            if isinstance(classes, list) and classes:
                lines = "\n".join(format_classes(classes))
                reply = f"📅 **Classes for {day_name}:**\n{lines}"
            elif isinstance(classes, list):
                reply = f"🎉 No classes tomorrow ({day_name})! Free day!"
            else:
                reply = classes
            await thinking.edit(content=reply)

        elif cmd == "!attendance":
            attendance = get_attendance(session)
            if isinstance(attendance, dict):
                emoji = attendance_emoji(attendance["percent"])
                if attendance["present"] and attendance["total"]:
                    reply = f"📊 **Overall Attendance:** {emoji} {attendance['percent']} ({attendance['present']}/{attendance['total']} classes)"
                else:
                    reply = f"📊 **Overall Attendance:** {emoji} {attendance['percent']}"
            else:
                reply = attendance
            await thinking.edit(content=reply)

        elif cmd == "!bunk":
            attendance = get_attendance(session)
            budget = calc_bunk_budget(attendance)
            if budget is None:
                await thinking.edit(content="⚠️ Couldn't calculate bunk budget.")
                return
            pct = float(attendance["percent"].replace("%", ""))
            emoji = attendance_emoji(attendance["percent"])
            if budget["can_bunk"] > 0:
                reply = (
                    f"📊 **Bunk Budget**\n"
                    f"Current: {emoji} {attendance['percent']} ({budget['present']}/{budget['total']})\n\n"
                    f"✅ You can skip **{budget['can_bunk']} more class(es)** and still stay at 75%."
                )
            else:
                reply = (
                    f"📊 **Bunk Budget**\n"
                    f"Current: {emoji} {attendance['percent']} ({budget['present']}/{budget['total']})\n\n"
                    f"🚨 You **cannot bunk any more classes!**\n"
                    f"Attend **{budget['need_attend']} consecutive class(es)** to get back to 75%."
                )
            await thinking.edit(content=reply)

@tasks.loop(minutes=1)
async def daily_timetable():
    now = datetime.now()
    if now.hour == SEND_HOUR and now.minute == SEND_MINUTE:
        await send_timetable()

@tasks.loop(minutes=1)
async def class_reminders():
    global reminders_sent, reminders_date
    now  = datetime.now()
    today = now.date()

    # Reset sent reminders each new day
    if reminders_date != today:
        reminders_sent = set()
        reminders_date = today

    # Only check during college hours (7 AM – 7 PM)
    if not (7 <= now.hour < 19):
        return

    session, err = get_session()
    if err:
        return

    _, classes = get_today_classes(session)
    if not isinstance(classes, list):
        return

    user = await client.fetch_user(DISCORD_USER_ID)
    if not user:
        return

    for cls in classes:
        start_time = cls["start_time"]
        if start_time is None:
            continue

        reminder_key = f"{cls['subject']}_{start_time.strftime('%H:%M')}"
        if reminder_key in reminders_sent:
            continue

        # Send reminder if we're within the 2-minute window before class
        minutes_until = (start_time - now).total_seconds() / 60
        if 0 <= minutes_until <= 2:
            await user.send(
                f"🔔 **Class Starting in ~2 minutes!**\n"
                f"📚 **{cls['subject']}** at **{cls['time_label']}**\n"
                f"_Don't be late!_"
            )
            reminders_sent.add(reminder_key)
            print(f"[{now.strftime('%H:%M')}] Sent reminder for {cls['subject']}")

async def send_timetable():
    user = await client.fetch_user(DISCORD_USER_ID)
    if user is None:
        print("❌ Could not find Discord user.")
        return

    # ── Reuse cached session (or login if expired) ──
    session, err = get_session()
    if err:
        await user.send(err)
        return

    day_name, classes = get_today_classes(session)
    attendance        = get_attendance(session)

    # ── Build timetable section ──
    if isinstance(classes, list) and classes:
        tt_lines = "\n".join(format_classes(classes))
        tt_section = f"📅 **Classes for {day_name}:**\n{tt_lines}"
    elif isinstance(classes, list):
        tt_section = f"🎉 **No classes today ({day_name})! Free day!**"
    else:
        tt_section = classes   # error string

    # ── Build attendance section ──
    if isinstance(attendance, dict):
        emoji = attendance_emoji(attendance["percent"])
        if attendance["present"] and attendance["total"]:
            att_section = f"📊 **Overall Attendance:** {emoji} {attendance['percent']} ({attendance['present']}/{attendance['total']} classes)"
        else:
            att_section = f"📊 **Overall Attendance:** {emoji} {attendance['percent']}"
    else:
        att_section = attendance   # error string

    msg = (
        f"☀️ **Good morning, {ERP_USER}!**\n\n"
        f"{tt_section}\n\n"
        f"─────────────────\n"
        f"{att_section}\n\n"
        f"_— PSIT Bot_"
    )

    await user.send(msg)
    print(f"[{datetime.now().strftime('%H:%M')}] Sent timetable + attendance to {user}")

# ── Dummy Web Server for Render Free Tier ──
app = Flask('')

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_server():
    import os
    port = int(os.environ.get('PORT', 8080))
    # Disable flask output logs to keep your terminal clean
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_server, daemon=True)
    t.start()

# Run bot
keep_alive()
client.run(DISCORD_TOKEN)
