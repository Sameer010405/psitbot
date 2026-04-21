import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

# Timezone: Indian Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))
BASE_URL = "https://erp.psit.ac.in"
TT_URL = f"{BASE_URL}/Student/MyTimeTable"
ATTENDANCE_URL = f"{BASE_URL}/Student/MyAttendanceDetail"
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def erp_login(username, password):
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
        "username": username,
        "password": password,
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
        return session, None

    return None, "❌ Login failed. Check your credentials."

def get_classes_for_day(session, day_offset=0):
    try:
        tt_resp = session.get(TT_URL, timeout=15)
        tt_resp.raise_for_status()
    except requests.RequestException as e:
        return "Unknown", f"⚠️ Could not fetch timetable: {e}"

    tt_soup = BeautifulSoup(tt_resp.text, "html.parser")
    day_idx  = (datetime.now(IST).weekday() + day_offset) % 7
    day_name = DAY_NAMES[day_idx]

    table = tt_soup.find("table")
    if not table:
        return day_name, "⚠️ Couldn't find timetable table."

    rows = table.find_all("tr")
    if not rows:
        return day_name, "⚠️ Timetable table is empty."

    headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
    day_col = None
    for i, h in enumerate(headers):
        if day_name.lower() in h.lower():
            day_col = i
            break

    classes = []
    if day_col is not None:
        for row in rows[1:]:
            cols = row.find_all(["td", "th"])
            if day_col >= len(cols): continue
            subject = cols[day_col].get_text(strip=True)
            time_label = cols[0].get_text(strip=True) if cols else f"Slot {len(classes)+1}"
            if subject and subject not in ["-", "–", "—", "", "N/A"]:
                classes.append({"time_label": time_label, "subject": subject, "start_time": parse_time(time_label)})
        return day_name, classes

    # Fallback to row-based
    for row in rows[1:]:
        cols = row.find_all(["td", "th"])
        row_label = cols[0].get_text(strip=True) if cols else ""
        if day_name.lower() in row_label.lower():
            for i, col in enumerate(cols[1:], start=1):
                subject = col.get_text(strip=True)
                if subject and subject not in ["-", "–", "—", "", "N/A"]:
                    time_label = headers[i] if i < len(headers) else f"Slot {i}"
                    classes.append({"time_label": time_label, "subject": subject, "start_time": parse_time(time_label)})
            return day_name, classes

    return day_name, f"⚠️ Could not find '{day_name}' in the timetable."

def parse_time(time_str):
    if not time_str: return None
    match = re.search(r'(\d{1,2}:\d{2})\s*(AM|PM)?', time_str, re.IGNORECASE)
    if not match: return None
    time_part, ampm = match.group(1), match.group(2)
    try:
        if ampm: t = datetime.strptime(f"{time_part} {ampm.upper()}", "%I:%M %p")
        else: t = datetime.strptime(time_part, "%H:%M")
        return datetime.now(IST).replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    except: return None

def get_attendance(session):
    try:
        resp = session.get(ATTENDANCE_URL, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        return f"⚠️ Could not fetch attendance: {e}"

    soup = BeautifulSoup(resp.text, "html.parser")
    full_text = soup.get_text(" ", strip=True).lower()
    percent_val = None

    patterns = [
        r'attendance\s*%\s*with\s*pf\s*[:\-]\s*([\d.]+)',
        r'attendance\s*%\s*without\s*pf\s*[:\-]\s*([\d.]+)',
        r'overall\s+attendance\s*[:\-]\s*([\d.]+)\s*%'
    ]
    for p in patterns:
        m = re.search(p, full_text)
        if m: 
            percent_val = float(m.group(1))
            break

    if percent_val is None:
        for m in re.finditer(r'([\d]{2,3}\.?\d*)\s*%', full_text):
            if "attendance" in full_text[max(0, m.start()-120):m.end()+40]:
                percent_val = float(m.group(1))
                break

    if percent_val is None: return "⚠️ Attendance not found."

    total_lectures = None
    m_total = re.search(r'total\s+lecture\s*[:\-]?\s*(\d+)', full_text)
    if m_total:
        total_lectures = int(m_total.group(1))
        present = round(total_lectures * (percent_val / 100.0))
        return {"present": present, "total": total_lectures, "percent": f"{percent_val:.2f}%"}
    
    return {"present": None, "total": None, "percent": f"{percent_val:.2f}%"}

def calc_bunk_budget(attendance):
    if not isinstance(attendance, dict) or not attendance.get("present"): return None
    p, t = int(attendance["present"]), int(attendance["total"])
    can_bunk = max(0, int(p / 0.75 - t))
    need_attend = max(0, int((0.75 * t - p) / 0.25) + 1) if p/t < 0.75 else 0
    return {"can_bunk": can_bunk, "need_attend": need_attend, "percent": attendance['percent']}
