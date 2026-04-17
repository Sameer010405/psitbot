import requests
from bs4 import BeautifulSoup

import os
ERP_USER     = os.getenv("ERP_USER", "")
ERP_PASSWORD = os.getenv("ERP_PASSWORD", "")

BASE_URL  = "https://erp.psit.ac.in"
LOGIN_URL = f"{BASE_URL}/Erp/Login"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/120 Safari/537.36"
})

print("── Step 1: GET homepage ──")
r = session.get(BASE_URL, timeout=15)
print(f"Status: {r.status_code}  |  Final URL: {r.url}")

soup = BeautifulSoup(r.text, "html.parser")

# ── Find the form and its action URL ──
form = soup.find("form")
if form:
    print(f"Form action: {form.get('action', '(none)')}")
    print(f"Form method: {form.get('method', '(none)')}")
    # Resolve post URL
    action = form.get("action", "")
    if action.startswith("/"):
        post_url = "https://erp.psit.ac.in" + action
    elif action.startswith("http"):
        post_url = action
    else:
        post_url = "https://erp.psit.ac.in"
else:
    print("⚠️  No form found on page!")
    post_url = "https://erp.psit.ac.in"

print(f"Will POST to: {post_url}")

# Also print ALL input fields so we can see what the form expects
print("\n── All <input> fields on login page ──")
for inp in soup.find_all("input"):
    print(f"  name={inp.get('name')!r:35}  type={inp.get('type')!r}  value={inp.get('value', '')[:30]!r}")

# Build payload with correct lowercase fields + all hidden fields
payload = {
    "username": ERP_USER,
    "password": ERP_PASSWORD,
}
for hidden in soup.find_all("input", {"type": "hidden"}):
    fname = hidden.get("name")
    fval  = hidden.get("value", "")
    if fname:
        payload[fname] = fval

print(f"\n── Step 2: POST login ──")
print(f"Sending to:          {post_url}")
print(f"Sending payload keys: {list(payload.keys())}")

resp = session.post(post_url, data=payload, timeout=15, allow_redirects=True)
print(f"Status: {resp.status_code}  |  Final URL: {resp.url}")

# Check what words are in the page
text_lower = resp.text.lower()
print(f"\n'logout'    in response: {'logout' in text_lower}")
print(f"'dashboard' in response: {'dashboard' in text_lower}")
print(f"'dashboard' in URL:      {'dashboard' in resp.url.lower()}")
print(f"'login'     in URL:      {'login' in resp.url.lower()}")
print(f"'invalid'   in response: {'invalid' in text_lower}")
print(f"'incorrect' in response: {'incorrect' in text_lower}")
print(f"'wrong'     in response: {'wrong' in text_lower}")

print("\n── First 800 chars of response body ──")
print(resp.text[:800])
