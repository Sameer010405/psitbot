# PSIT Automation 2.0 (Telegram Edition)

This is a multi-user Telegram bot that scrapes the PSIT ERP to provide automated attendance tracking and timetable reminders.

## 🌟 Features
- **Multi-User Support**: Multiple students can log in and use the bot simultaneously.
- **Persistent Sessions**: Login once, stay logged in (uses SQLite database).
- **Daily Reminders**: Automatically sends the timetable and attendance status at 8:00 AM IST.
- **Interactive UI**: Custom keyboard buttons for easy access (no typing needed!).
- **Bunk Budget**: Instantly calculate how many classes you can afford to skip.

## 🚀 Getting Started

1. **Get a Telegram Token**:
   - Message [@BotFather](https://t.me/botfather) on Telegram.
   - Use `/newbot` to create your bot and get the **API Token**.

2. **Setup Environment**:
   - Create a `.env` file in this folder:
     ```env
     TELEGRAM_TOKEN=your_token_here
     ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the Bot**:
   ```bash
   python bot.py
   ```

## 🛠 Project Structure
- `bot.py`: The Telegram interface and database management.
- `scraper.py`: The logic for logging into the ERP and extracting data.
- `users.db`: (Auto-generated) Stores user IDs and credentials securely.
- `requirements.txt`: List of required Python libraries.

## 🔐 Security Note
Credentials are stored in a local SQLite database (`users.db`). If deploying to a public server, ensure this file is not accessible to others.
