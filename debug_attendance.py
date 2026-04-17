import requests
from bs4 import BeautifulSoup
import re

import os
ERP_USER     = os.getenv("ERP_USER", "")
ERP_PASSWORD = os.getenv("ERP_PASSWORD", "")
BASE_URL     = "https://erp.psit.ac.in"
ATTENDANCE_URL = f"{BASE_URL}/Student/MyAttendanceDetail"
DASHBOARD_URL = f"{BASE_URL}/Student/"

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0"})
s.get(BASE_URL)
r = s.post(f"{BASE_URL}/Erp/Auth", data={"username": ERP_USER, "password": ERP_PASSWORD})

# Check dashboard for any attendance summary
dash = s.get(DASHBOARD_URL)
dash_soup = BeautifulSoup(dash.text, 'html.parser')
print("--- DASHBOARD TEXT (Looking for Attendance) ---")
for text in dash_soup.stripped_strings:
    if 'attend' in text.lower() or '%' in text or 'lectures' in text.lower() or '/' in text:
        print(text)

print("\n--- ATTENDANCE PAGE SUMMARY ---")
att = s.get(ATTENDANCE_URL)
att_soup = BeautifulSoup(att.text, 'html.parser')

# Print all elements that look like a number
for text in att_soup.stripped_strings:
    if 'total' in text.lower() or 'present' in text.lower() or 'absent' in text.lower() or '%' in text:
        print(text)
