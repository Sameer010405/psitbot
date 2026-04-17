import requests
import discord
from discord.ext import tasks
from bs4 import BeautifulSoup
from datetime import datetime
import asyncio
from flask import Flask
from threading import Thread
import os
import re

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

# Time to send the daily morning message (24hr format, IST)
SEND_HOUR   = 7
SEND_MINUTE = 0

# ERP is contacted ONLY at these two times each day
CACHE_REFRESH_TIMES = [
    (7, 0),   # 7:00 AM — morning fetch
    (19, 0),  # 7:00 PM — evening fetch (updated attendance)
]

# ─────────────────────────────────────────

BASE_URL       = "https://erp.psit.ac.in"
TT_URL         = f"{BASE_URL}/Student/MyTimeTable"
ATTENDANCE_URL = f"{BASE_URL}/Student/MyAttendanceDetail"

DAY_NAMES = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

# ─────────────────────────────────────────
#  DAILY CACHE
#  Populated at 7 AM and 7 PM. All commands read from here — no live ERP calls.
# ─────────────────────────────────────────

class DailyCache:
    def __init__(self):
        self.reset()

    def reset(self):
        self.date             = None
        self.today_name       = None
        self.today_classes    = None   # list of dicts or error string
        self.tomorrow_name    = None
        self.tomorrow_classes = None
        self.attendance       = None   # dict {present, total, percent} or error string
        self.bunk_budget      = None
        self.last_refresh     = None   # datetime
        self.error            = None

    def is_stale(self):
        return self.date != datetime.now().date() or self.today_classes is None

cache = DailyCache()

# ─────────────────────────────────────────
#  ERP LOGIN & SCRAPING
# ─────────────────────────────────────────

def erp_login():
    """Create an authenticated ERP session. Returns (session, error_msg)."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/120 Safari/537.36",
    })

    # ── Step 1: Load homepage (this is where the login form lives) ──
    r    = session.get(BASE_URL, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")

    # ── Step 2: Find the form's POST action URL ──
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

    # ── Step 3: Build payload using field names from the actual form ──
    payload = {
        "username": ERP_USER,
        "password": ERP_PASSWORD,
    }
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
        ("login" not in final_url and login_resp.status_code == 200)
    )

    if logged_in:
        print(f"✅ ERP login succeeded → {login_resp.url}")
        return session, None

    return None, "❌ Login failed. Check your ERP credentials in the script."


def _scrape_classes_for_day(session, day_offset=0):
    """Scrape timetable page. Returns (day_name, classes_list_or_str)."""
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


def _scrape_attendance(session):
    """Scrape attendance page. Returns dict {present, total, percent} or error string."""
    resp      = session.get(ATTENDANCE_URL, timeout=15)
    soup      = BeautifulSoup(resp.text, "html.parser")
    full_text = soup.get_text(" ", strip=True).lower()

    match_pct = re.search(r'attendance\s*%\s*with\s*pf\s*:\s*([\d\.]+)', full_text)
    if not match_pct:
        match_pct = re.search(r'attendance\s*%\s*without\s*pf\s*:\s*([\d\.]+)', full_text)

    if not match_pct:
        return "⚠️ Couldn't find overall attendance percentage on the new layout."

    percent_str = match_pct.group(1) + "%"
    present = total = None

    tot_match = re.search(r'total lecture\s*:\s*(\d+)', full_text)
    if tot_match:
        try:
            total   = int(tot_match.group(1))
            pct_val = float(percent_str.replace('%', ''))
            present = round(total * (pct_val / 100.0))
        except ValueError:
            pass

    return {"present": present, "total": total, "percent": percent_str}


def refresh_cache():
    """
    The ONLY function that contacts the ERP.
    Logs in once, scrapes everything, stores in global cache.
    Returns error string or None on success.
    """
    global cache
    print(f"[{datetime.now().strftime('%H:%M')}] 🔄 Refreshing cache from ERP…")

    session, err = erp_login()
    if err:
        cache.error = err
        return err

    today_name,    today_classes    = _scrape_classes_for_day(session, day_offset=0)
    tomorrow_name, tomorrow_classes = _scrape_classes_for_day(session, day_offset=1)
    attendance                      = _scrape_attendance(session)
    bunk_budget                     = calc_bunk_budget(attendance)

    cache.date             = datetime.now().date()
    cache.today_name       = today_name
    cache.today_classes    = today_classes
    cache.tomorrow_name    = tomorrow_name
    cache.tomorrow_classes = tomorrow_classes
    cache.attendance       = attendance
    cache.bunk_budget      = bunk_budget
    cache.last_refresh     = datetime.now()
    cache.error            = None

    print(f"[{datetime.now().strftime('%H:%M')}] ✅ Cache refreshed — "
          f"{len(today_classes) if isinstance(today_classes, list) else 0} classes today, "
          f"attendance={attendance.get('percent') if isinstance(attendance, dict) else 'N/A'}")
    return None

# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def parse_time(time_str):
    """Parse '9:00 AM', '09:00', '9:00-10:00' into a datetime. Returns None if unparseable."""
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


def format_classes(classes):
    """Convert list of class dicts to display lines."""
    return [f"🕐 **{c['time_label']}** — {c['subject']}" for c in classes]


def calc_bunk_budget(attendance):
    """Return bunk budget dict, or None if attendance data is invalid."""
    if not isinstance(attendance, dict):
        return None
    try:
        present = int(attendance["present"])
        total   = int(attendance["total"])
    except (TypeError, ValueError):
        return None

    can_bunk    = max(0, int(present / 0.75 - total))
    need_attend = 0
    if present / total < 0.75:
        need_attend = max(0, int((0.75 * total - present) / 0.25) + 1)

    return {"can_bunk": can_bunk, "need_attend": need_attend, "present": present, "total": total}


def attendance_emoji(percent_str):
    """Return an emoji based on attendance percentage."""
    try:
        pct = float(percent_str.replace("%", ""))
        if pct >= 75:   return "✅"
        elif pct >= 65: return "⚠️"
        else:           return "🚨"
    except ValueError:
        return "❓"

# ─────────────────────────────────────────
#  Discord Bot
# ─────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
client  = discord.Client(intents=intents)

COMMANDS_HELP = """
**📖 PSIT Bot Commands:**
`!today`      — Today's classes
`!tomorrow`   — Tomorrow's classes
`!attendance` — Your current overall attendance
`!bunk`       — How many classes you can skip (or need to attend)
`!refresh`    — Force a manual ERP fetch right now
`!cache`      — Show when data was last fetched
`!help`       — Show this message

🔔 **Auto reminders are on** — you'll get a ping 2 mins before each class!
📦 **ERP is only contacted at 7 AM and 7 PM** to save logins.
""".strip()

reminders_sent = set()
reminders_date = None


@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    cache_refresh_loop.start()
    daily_timetable.start()
    class_reminders.start()


@client.event
async def on_message(message):
    if message.author.id != DISCORD_USER_ID or message.author.bot:
        return

    cmd = message.content.strip().lower()

    # ── !help ──
    if cmd == "!help":
        await message.channel.send(COMMANDS_HELP)
        return

    # ── !cache ──
    if cmd == "!cache":
        last = cache.last_refresh.strftime("%I:%M %p on %b %d") if cache.last_refresh else "never"
        await message.channel.send(
            f"📦 Cache last updated: **{last}**\n"
            f"Next auto-refresh at **7:00 AM** or **7:00 PM**."
        )
        return

    # ── !refresh ──
    if cmd == "!refresh":
        thinking = await message.channel.send("🔄 Logging into ERP and refreshing cache…")
        err = await asyncio.get_event_loop().run_in_executor(None, refresh_cache)
        if err:
            await thinking.edit(content=f"❌ Refresh failed: {err}")
        else:
            await thinking.edit(content=f"✅ Done! Data is fresh as of {cache.last_refresh.strftime('%I:%M %p')}.")
        return

    # ── Data commands — all read from cache ──
    if cmd in ("!today", "!tomorrow", "!attendance", "!bunk"):
        if cache.is_stale():
            await message.channel.send(
                "⚠️ No data cached yet for today. Use `!refresh` to fetch from ERP now."
            )
            return

        if cmd == "!today":
            classes  = cache.today_classes
            day_name = cache.today_name
            if isinstance(classes, list) and classes:
                lines = "\n".join(format_classes(classes))
                reply = f"📅 **Classes for {day_name}:**\n{lines}"
            elif isinstance(classes, list):
                reply = f"🎉 No classes today ({day_name})! Free day!"
            else:
                reply = classes
            await message.channel.send(reply)

        elif cmd == "!tomorrow":
            classes  = cache.tomorrow_classes
            day_name = cache.tomorrow_name
            if isinstance(classes, list) and classes:
                lines = "\n".join(format_classes(classes))
                reply = f"📅 **Classes for {day_name}:**\n{lines}"
            elif isinstance(classes, list):
                reply = f"🎉 No classes tomorrow ({day_name})! Free day!"
            else:
                reply = classes
            await message.channel.send(reply)

        elif cmd == "!attendance":
            attendance = cache.attendance
            if isinstance(attendance, dict):
                emoji = attendance_emoji(attendance["percent"])
                if attendance["present"] and attendance["total"]:
                    reply = (f"📊 **Overall Attendance:** {emoji} {attendance['percent']} "
                             f"({attendance['present']}/{attendance['total']} classes)")
                else:
                    reply = f"📊 **Overall Attendance:** {emoji} {attendance['percent']}"
            else:
                reply = attendance
            ts = cache.last_refresh.strftime("%I:%M %p") if cache.last_refresh else "unknown"
            await message.channel.send(reply + f"\n_— cached at {ts}_")

        elif cmd == "!bunk":
            budget     = cache.bunk_budget
            attendance = cache.attendance
            if budget is None:
                await message.channel.send("⚠️ Couldn't calculate bunk budget from cached data.")
                return
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
            ts = cache.last_refresh.strftime("%I:%M %p") if cache.last_refresh else "unknown"
            await message.channel.send(reply + f"\n_— cached at {ts}_")


@tasks.loop(minutes=1)
async def cache_refresh_loop():
    """Fires at 7:00 AM and 7:00 PM — the only two times ERP is contacted."""
    now = datetime.now()
    for hour, minute in CACHE_REFRESH_TIMES:
        if now.hour == hour and now.minute == minute:
            err = await asyncio.get_event_loop().run_in_executor(None, refresh_cache)
            if err:
                try:
                    user = await client.fetch_user(DISCORD_USER_ID)
                    await user.send(f"⚠️ Scheduled ERP refresh at {hour:02d}:{minute:02d} failed:\n{err}")
                except Exception:
                    pass


@tasks.loop(minutes=1)
async def daily_timetable():
    """Send the morning summary DM at 7:00 AM."""
    now = datetime.now()
    if now.hour != SEND_HOUR or now.minute != SEND_MINUTE:
        return

    # Cache refreshes at the same time — wait up to 30s for it to populate
    for _ in range(30):
        if not cache.is_stale():
            break
        await asyncio.sleep(1)

    user = await client.fetch_user(DISCORD_USER_ID)
    if not user:
        return

    classes    = cache.today_classes
    day_name   = cache.today_name
    attendance = cache.attendance

    if isinstance(classes, list) and classes:
        tt_lines   = "\n".join(format_classes(classes))
        tt_section = f"📅 **Classes for {day_name}:**\n{tt_lines}"
    elif isinstance(classes, list):
        tt_section = f"🎉 **No classes today ({day_name})! Free day!**"
    else:
        tt_section = str(classes)

    if isinstance(attendance, dict):
        emoji = attendance_emoji(attendance["percent"])
        if attendance["present"] and attendance["total"]:
            att_section = (f"📊 **Overall Attendance:** {emoji} {attendance['percent']} "
                           f"({attendance['present']}/{attendance['total']} classes)")
        else:
            att_section = f"📊 **Overall Attendance:** {emoji} {attendance['percent']}"
    else:
        att_section = str(attendance)

    msg = (
        f"☀️ **Good morning, {ERP_USER}!**\n\n"
        f"{tt_section}\n\n"
        f"─────────────────\n"
        f"{att_section}\n\n"
        f"_— PSIT Bot_"
    )
    await user.send(msg)
    print(f"[{now.strftime('%H:%M')}] Sent morning message to {user}")


@tasks.loop(minutes=1)
async def class_reminders():
    """Ping 2 minutes before each class, using cached timetable only."""
    global reminders_sent, reminders_date

    now   = datetime.now()
    today = now.date()

    if reminders_date != today:
        reminders_sent = set()
        reminders_date = today

    if not (7 <= now.hour < 19):
        return

    # Read from cache — no ERP call
    if cache.is_stale() or not isinstance(cache.today_classes, list):
        return

    user = await client.fetch_user(DISCORD_USER_ID)
    if not user:
        return

    for cls in cache.today_classes:
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


# ── Dummy Web Server for Render Free Tier ──
app = Flask('')

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_server, daemon=True)
    t.start()

# Run bot
keep_alive()
client.run(DISCORD_TOKEN)
