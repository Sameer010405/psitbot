import requests
import discord
from discord.ext import tasks
from bs4 import BeautifulSoup
from datetime import datetime
import asyncio
import os
import re
from dotenv import load_dotenv

# Load environment variables from .env file automatically (useful for local testing)
load_dotenv()

# ─────────────────────────────────────────
# CONFIGURATION — fill these in via Environment Variables / GitHub Secrets
# ─────────────────────────────────────────
ERP_USER      = os.getenv("ERP_USER", "").strip()
ERP_PASSWORD  = os.getenv("ERP_PASSWORD", "").strip()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

print("--- STARTUP DEBUG ---")
print(f"ERP_USER is loaded: {'YES' if ERP_USER else 'NO'} (length: {len(ERP_USER)})")
print(f"ERP_PASSWORD is loaded: {'YES' if ERP_PASSWORD else 'NO'} (length: {len(ERP_PASSWORD)})")
print(f"DISCORD_TOKEN is loaded: {'YES' if DISCORD_TOKEN else 'NO'} (length: {len(DISCORD_TOKEN)})")
print("---------------------")

try:
    _user_id_str = os.getenv("DISCORD_USER_ID", "").strip()
    DISCORD_USER_ID = int(_user_id_str) if _user_id_str else 0
except ValueError:
    DISCORD_USER_ID = 0

# Time to send the daily message (24hr format, IST)
SEND_HOUR   = 7
SEND_MINUTE = 0

# ─────────────────────────────────────────
BASE_URL       = "https://erp.psit.ac.in"
LOGIN_URL      = BASE_URL
TT_URL         = f"{BASE_URL}/Student/MyTimeTable"
ATTENDANCE_URL = f"{BASE_URL}/Student/MyAttendanceDetail"

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ─────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────

def erp_login():
    """Create an authenticated ERP session. Returns (session, error_msg)."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        ),
    })

    try:
        r = session.get(BASE_URL, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        return None, f"❌ Could not reach ERP: {e}"

    soup = BeautifulSoup(r.text, "html.parser")

    form = soup.find("form")
    if form and form.get("action"):
        action = form["action"]
        if action.startswith("/"):
            post_url = BASE_URL + action
        elif action.startswith("http"):
            post_url = action
        else:
            post_url = BASE_URL + "/" + action
    else:
        post_url = BASE_URL

    payload = {
        "username": ERP_USER,
        "password": ERP_PASSWORD,
    }
    for hidden in soup.find_all("input", {"type": "hidden"}):
        fname = hidden.get("name")
        fval  = hidden.get("value", "")
        if fname:
            payload[fname] = fval

    try:
        login_resp = session.post(post_url, data=payload, timeout=15, allow_redirects=True)
    except requests.RequestException as e:
        return None, f"❌ Login request failed: {e}"

    final_url  = login_resp.url.lower()
    body       = login_resp.text
    body_lower = body.lower()

    logged_in = (
        "logout" in body_lower
        or "/logout" in body_lower
        or "dashboard" in final_url
        or ("student" in final_url and "login" not in final_url)
    )

    if "invalid" in body_lower or "incorrect" in body_lower or "failed" in body_lower:
        logged_in = False

    if logged_in:
        print(f"✅ ERP login succeeded → {login_resp.url}")
        return session, None

    print(f"❌ Login failed. Final URL: {login_resp.url}")
    print(f"--- FAILED LOGIN BODY (First 500 chars) ---\n{body[:500]}\n-----------------------------------------")
    return None, "❌ Login failed. Check ERP_USER and ERP_PASSWORD variables."

# ─────────────────────────────────────────
# Session Cache
# ─────────────────────────────────────────

_cached_session = None

def get_session():
    """Return a valid ERP session, reusing the cached one if still alive."""
    global _cached_session

    if _cached_session is not None:
        try:
            check = _cached_session.get(f"{BASE_URL}/Student/", timeout=10)
            if "logout" in check.text.lower():
                return _cached_session, None   
        except Exception:
            pass  

    _cached_session, err = erp_login()
    return _cached_session, err

# ─────────────────────────────────────────
# TIME TABLE
# ─────────────────────────────────────────

def get_classes_for_day(session, day_offset=0):
    try:
        tt_resp = session.get(TT_URL, timeout=15)
        tt_resp.raise_for_status()
    except requests.RequestException as e:
        return "Unknown", f"⚠️ Could not fetch timetable: {e}"

    tt_soup = BeautifulSoup(tt_resp.text, "html.parser")

    day_idx  = (datetime.now().weekday() + day_offset) % 7
    day_name = DAY_NAMES[day_idx]

    table = tt_soup.find("table")
    if not table:
        return day_name, "⚠️ Couldn't find timetable table. ERP layout may have changed."

    rows = table.find_all("tr")
    if not rows:
        return day_name, "⚠️ Timetable table is empty."

    headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]

    day_col = None
    for i, h in enumerate(headers):
        if day_name.lower() in h.lower():
            day_col = i
            break

    if day_col is not None:
        classes = []
        for row in rows[1:]:
            cols = row.find_all(["td", "th"])
            if day_col >= len(cols):
                continue
            subject = cols[day_col].get_text(strip=True)
            time_label = cols[0].get_text(strip=True) if cols else f"Slot {len(classes)+1}"
            if subject and subject not in ["-", "–", "—", "", "N/A"]:
                start_time = parse_time(time_label)
                classes.append({
                    "time_label": time_label,
                    "subject":    subject,
                    "start_time": start_time,
                })
        return day_name, classes

    classes = []
    for row in rows[1:]:
        cols = row.find_all(["td", "th"])
        row_label = cols[0].get_text(strip=True) if cols else ""
        if day_name.lower() in row_label.lower():
            for i, col in enumerate(cols[1:], start=1):
                subject = col.get_text(strip=True)
                if subject and subject not in ["-", "–", "—", "", "N/A"]:
                    time_label = headers[i] if i < len(headers) else f"Slot {i}"
                    start_time = parse_time(time_label)
                    classes.append({
                        "time_label": time_label,
                        "subject":    subject,
                        "start_time": start_time,
                    })
            return day_name, classes

    header_str = " | ".join(headers[:10])
    return day_name, (
        f"⚠️ Could not find '{day_name}' in the timetable.\n"
        f"Table headers found: `{header_str}`\n"
        f"Please check TT_URL or report this to the developer."
    )

def parse_time(time_str):
    if not time_str:
        return None

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
    return [f"🕐 **{c['time_label']}** — {c['subject']}" for c in classes]

# ─────────────────────────────────────────
# ATTENDANCE
# ─────────────────────────────────────────

def get_attendance(session):
    try:
        resp = session.get(ATTENDANCE_URL, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        return f"⚠️ Could not fetch attendance: {e}"

    soup      = BeautifulSoup(resp.text, "html.parser")
    full_text = soup.get_text(" ", strip=True)
    text_low  = full_text.lower()

    percent_val = None

    m = re.search(r'attendance\s*%\s*with\s*pf\s*[:\-]\s*([\d.]+)', text_low)
    if m: percent_val = float(m.group(1))

    if percent_val is None:
        m = re.search(r'attendance\s*%\s*without\s*pf\s*[:\-]\s*([\d.]+)', text_low)
        if m: percent_val = float(m.group(1))

    if percent_val is None:
        m = re.search(r'overall\s+attendance\s*[:\-]\s*([\d.]+)\s*%', text_low)
        if m: percent_val = float(m.group(1))

    if percent_val is None:
        for m in re.finditer(r'([\d]{2,3}\.?\d*)\s*%', full_text):
            idx = m.start()
            surrounding = full_text[max(0, idx-120):idx+40].lower()
            if "attendance" in surrounding:
                percent_val = float(m.group(1))
                break

    if percent_val is None:
        return "⚠️ Couldn't find attendance percentage. ERP layout may have changed."

    percent_str = f"{percent_val:.2f}%"

    present = None
    total   = None

    m_total = re.search(r'total\s+lecture\s*[:\-]?\s*(\d+)', text_low)
    if m_total:
        total = int(m_total.group(1))
        present = round(total * (percent_val / 100.0))
    else:
        m_pt = re.search(r'present\s*[:\-]?\s*(\d+)\s*[/\\|]\s*(\d+)', text_low)
        if m_pt:
            present = int(m_pt.group(1))
            total   = int(m_pt.group(2))

    return {"present": present, "total": total, "percent": percent_str}

def attendance_emoji(percent_str):
    try:
        pct = float(str(percent_str).replace("%", ""))
        if pct >= 75: return "✅"
        elif pct >= 65: return "⚠️"
        else: return "🚨"
    except (ValueError, AttributeError):
        return "❓"

# ─────────────────────────────────────────
# BUNK BUDGET
# ─────────────────────────────────────────

def calc_bunk_budget(attendance):
    if not isinstance(attendance, dict):
        return None
    try:
        present = int(attendance["present"])
        total   = int(attendance["total"])
    except (TypeError, ValueError, KeyError):
        return None

    can_bunk    = max(0, int(present / 0.75 - total))
    need_attend = 0
    if total > 0 and present / total < 0.75:
        need_attend = max(0, int((0.75 * total - present) / 0.25) + 1)

    return {
        "can_bunk":    can_bunk,
        "need_attend": need_attend,
        "present":     present,
        "total":       total,
    }

# ─────────────────────────────────────────
# Discord Bot
# ─────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

COMMANDS_HELP = """
**📖 PSIT Bot Commands:**
`!today`      — Today's classes
`!tomorrow`   — Tomorrow's classes
`!attendance` — Your current overall attendance
`!bunk`       — How many classes you can skip (or need to attend)
`!help`       — Show this message

🔔 **Auto reminders are on** — you'll get a ping 2 mins before each class!
""".strip()

reminders_sent = set()
reminders_date = None
last_sent_date = None 

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    daily_timetable.start()
    class_reminders.start()

@client.event
async def on_message(message):
    if message.author.id != DISCORD_USER_ID:
        return
    if message.author.bot:
        return

    cmd = message.content.strip().lower()

    if cmd == "!help":
        await message.channel.send(COMMANDS_HELP)
        return

    if cmd not in ("!today", "!tomorrow", "!attendance", "!bunk"):
        return

    thinking = await message.channel.send("⏳ Fetching from ERP...")
    
    session, err = await asyncio.to_thread(get_session)
    if err:
        await thinking.edit(content=err)
        return

    if cmd == "!today":
        day_name, classes = await asyncio.to_thread(get_today_classes, session)
        if isinstance(classes, list) and classes:
            lines = "\n".join(format_classes(classes))
            reply = f"📅 **Classes for {day_name}:**\n{lines}"
        elif isinstance(classes, list):
            reply = f"🎉 No classes today ({day_name})! Free day!"
        else:
            reply = classes
        await thinking.edit(content=reply)

    elif cmd == "!tomorrow":
        day_name, classes = await asyncio.to_thread(get_classes_for_day, session, 1)
        if isinstance(classes, list) and classes:
            lines = "\n".join(format_classes(classes))
            reply = f"📅 **Classes for {day_name}:**\n{lines}"
        elif isinstance(classes, list):
            reply = f"🎉 No classes tomorrow ({day_name})! Free day!"
        else:
            reply = classes
        await thinking.edit(content=reply)

    elif cmd == "!attendance":
        attendance = await asyncio.to_thread(get_attendance, session)
        if isinstance(attendance, dict):
            emoji = attendance_emoji(attendance["percent"])
            if attendance["present"] and attendance["total"]:
                reply = (
                    f"📊 **Overall Attendance:** {emoji} {attendance['percent']} "
                    f"({attendance['present']}/{attendance['total']} classes)"
                )
            else:
                reply = f"📊 **Overall Attendance:** {emoji} {attendance['percent']}"
        else:
            reply = attendance
        await thinking.edit(content=reply)

    elif cmd == "!bunk":
        attendance = await asyncio.to_thread(get_attendance, session)
        budget = calc_bunk_budget(attendance)
        if budget is None:
            await thinking.edit(
                content="⚠️ Couldn't calculate bunk budget (missing present/total data)."
            )
            return
        emoji = attendance_emoji(attendance["percent"])
        if budget["can_bunk"] > 0:
            reply = (
                f"📊 **Bunk Budget**\n"
                f"Current: {emoji} {attendance['percent']} "
                f"({budget['present']}/{budget['total']})\n\n"
                f"✅ You can skip **{budget['can_bunk']} more class(es)** and still stay at 75%."
            )
        else:
            reply = (
                f"📊 **Bunk Budget**\n"
                f"Current: {emoji} {attendance['percent']} "
                f"({budget['present']}/{budget['total']})\n\n"
                f"🚨 You **cannot bunk any more classes!**\n"
                f"Attend **{budget['need_attend']} consecutive class(es)** to get back to 75%."
            )
        await thinking.edit(content=reply)

@tasks.loop(minutes=1)
async def daily_timetable():
    global last_sent_date
    now = datetime.now()
    if now.hour == SEND_HOUR and now.minute == SEND_MINUTE and last_sent_date != now.date():
        await send_timetable()
        last_sent_date = now.date()

@tasks.loop(minutes=1)
async def class_reminders():
    global reminders_sent, reminders_date

    now   = datetime.now()
    today = now.date()

    if reminders_date != today:
        reminders_sent = set()
        reminders_date = today

    if not (7 <= now.hour < 19):
        return

    session, err = await asyncio.to_thread(get_session)
    if err:
        return

    _, classes = await asyncio.to_thread(get_today_classes, session)
    if not isinstance(classes, list):
        return

    try:
        user = await client.fetch_user(DISCORD_USER_ID)
    except discord.NotFound:
        return

    for cls in classes:
        start_time = cls["start_time"]
        if start_time is None:
            continue

        reminder_key = f"{cls['subject']}_{start_time.strftime('%H:%M')}"
        if reminder_key in reminders_sent:
            continue

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
    try:
        user = await client.fetch_user(DISCORD_USER_ID)
    except discord.NotFound:
        print("❌ Could not find Discord user.")
        return

    session, err = await asyncio.to_thread(get_session)
    if err:
        await user.send(err)
        return

    day_name, classes = await asyncio.to_thread(get_today_classes, session)
    attendance        = await asyncio.to_thread(get_attendance, session)

    if isinstance(classes, list) and classes:
        tt_lines   = "\n".join(format_classes(classes))
        tt_section = f"📅 **Classes for {day_name}:**\n{tt_lines}"
    elif isinstance(classes, list):
        tt_section = f"🎉 **No classes today ({day_name})! Free day!**"
    else:
        tt_section = classes

    if isinstance(attendance, dict):
        emoji = attendance_emoji(attendance["percent"])
        if attendance["present"] and attendance["total"]:
            att_section = (
                f"📊 **Overall Attendance:** {emoji} {attendance['percent']} "
                f"({attendance['present']}/{attendance['total']} classes)"
            )
        else:
            att_section = f"📊 **Overall Attendance:** {emoji} {attendance['percent']}"
    else:
        att_section = attendance

    msg = (
        f"☀️ **Good morning, {ERP_USER}!**\n\n"
        f"{tt_section}\n\n"
        f"─────────────────\n"
        f"{att_section}\n\n"
        f"_— PSIT Bot_"
    )
    await user.send(msg)
    print(f"[{datetime.now().strftime('%H:%M')}] Sent timetable + attendance to {user}")

# ─────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────

client.run(DISCORD_TOKEN)
