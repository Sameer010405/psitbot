# 🤖 PSIT Timetable Discord Bot — Setup Guide

## What this bot does
**Bot 2.0** (`bot2.0.py`) logs into your PSIT ERP and:
- Sends you today's timetable + attendance every morning at 7 AM
- Pings you **2 minutes before each class** starts
- Responds to commands: `!today`, `!tomorrow`, `!attendance`, `!bunk`, `!help`
- Caches the ERP session (no repeated logins every minute)

---

## Step 1 — Install Python
Download Python 3.10+ from https://python.org if you don't have it.

---

## Step 2 — Install dependencies
Open a terminal/command prompt in this folder and run:
```
pip install -r requirements.txt
```

---

## Step 3 — Create a Discord Bot

1. Go to https://discord.com/developers/applications
2. Click **New Application** → give it a name (e.g. "PSIT Bot")
3. Go to **Bot** (left sidebar) → click **Add Bot**
4. Under **Token** → click **Reset Token** → copy it
5. Save it as `DISCORD_TOKEN` in bot.py

**Enable DM permissions:**
- Under Bot → scroll down to **Privileged Gateway Intents**
- Turn on **Message Content Intent**

**Invite bot to your server (needed to DM you):**
- Go to **OAuth2 → URL Generator**
- Scopes: `bot`
- Bot Permissions: `Send Messages`
- Copy the URL, open it, and add the bot to any server you're in

---

## Step 4 — Get your Discord User ID

1. Open Discord → Settings → Advanced → Enable **Developer Mode**
2. Right-click your own username anywhere → **Copy User ID**
3. Paste it as `DISCORD_USER_ID` in bot.py (as a number, no quotes)

---

## Step 5 — Fill in bot.py

Open `bot.py` and fill in the top section:
```python
ERP_USER        = "YOUR_ERP_ROLL_NUMBER"
ERP_PASSWORD    = "YOUR_ERP_PASSWORD"
DISCORD_TOKEN   = "YOUR_DISCORD_BOT_TOKEN"
DISCORD_USER_ID = 123456789012345678
```

Change `SEND_HOUR` and `SEND_MINUTE` if you want it at a different time.

---

## Step 6 — Run the bot
```
python bot2.0.py
```
Keep this terminal open (or run it in the background).
You'll see: `✅ Logged in as PSIT Bot#1234`

---

## Step 7 — Run 24/7 on Termux (Android)

Termux lets you run the bot on your Android phone so it stays alive without a PC.

### Install Termux
- Download **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/) (NOT Play Store — that version is outdated)

### Setup inside Termux
```bash
# Update packages
pkg update && pkg upgrade -y

# Install Python
pkg install python -y

# Install pip dependencies
pip install requests discord.py beautifulsoup4
```

### Transfer your bot file
Easiest way — copy the contents of `bot2.0.py` and create the file in Termux:
```bash
nano ~/bot2.0.py
# Paste your bot2.0.py contents, then Ctrl+X → Y → Enter to save
```

### Run it and keep it alive (won't die when Termux is backgrounded)
```bash
nohup python ~/bot2.0.py &
```
- `nohup` = keeps running after you close the session
- `&` = runs in the background
- Output is saved to `~/nohup.out` — check it with: `cat ~/nohup.out`

### Stop the bot
```bash
pkill -f bot2.0.py
```

### Auto-start on phone reboot (Termux:Boot)
1. Install **Termux:Boot** from F-Droid
2. Open Termux:Boot once to activate it
3. Create the auto-start script:
```bash
mkdir -p ~/.termux/boot
nano ~/.termux/boot/start_bot.sh
```
4. Paste this inside:
```bash
#!/data/data/com.termux/files/usr/bin/bash
nohup python ~/bot2.0.py &
```
5. Make it executable:
```bash
chmod +x ~/.termux/boot/start_bot.sh
```
Now the bot will auto-start every time your phone reboots. ✅

### Keep screen on tip
Go to **Android Settings → Battery** and set Termux to **Unrestricted** so it doesn't get killed in the background.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Login failed" | Double-check roll number & password in bot.py |
| "Couldn't find timetable" | ERP layout may have changed — open an issue |
| Bot doesn't DM me | Make sure you share a server with the bot |
| Nothing happens at 7 AM | Make sure the script is still running |
