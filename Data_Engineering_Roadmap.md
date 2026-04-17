# From Discord Bot to Data Engineering Pipeline

Your PSIT Discord Bot is already a solid software engineering project, but it also heavily touches on the core concepts of **Data Engineering**. 

Data Engineering is essentially about building automated pipelines that move and prepare data. The core workflow of Data Engineering is called **ETL**:
1. **E**xtract
2. **T**ransform
3. **L**oad

Here is how your project currently fits into this pipeline, and how you can expand it to create a standout, resume-worthy Data Engineering project.

---

## 1. Extract (Data Ingestion)
**What it is:** Pulling data from various sources (APIs, databases, websites) into your system.
**What you are doing:** You are currently acting as an extraction pipeline. Using Python libraries (`requests` and `BeautifulSoup`), your bot logs into the ERP system, mimics human behavior, and pulls hidden internal data (timetables & attendance) directly from the raw HTML of the PSIT website.

## 2. Transform (Data Cleaning)
**What it is:** Raw data is almost always messy. Transformation involves cleaning the data, changing its format, or doing calculations on it before saving it.
**What you are doing:** The text returned by the ERP is unstructured (e.g., `"Attendance % with PF : 80.65 %"`). You are using Regular Expressions (`regex`) and logic to parse, clean, and convert that messy text into usable numeric integers and precise strings. You also run calculations (like finding the "Bunk Budget").

## 3. Orchestration / Automation
**What it is:** Data engineers don't run scripts manually; they schedule them to run automatically using tools like Airflow, Cron, or Cloud Schedulers.
**What you are doing:** Using GitHub Actions (via cron jobs) and cloud-hosting platforms like Render to keep your scripts running 24/7 without manual intervention.

---

## How to Expand This Project into "True" Data Engineering

If you want to put this project on a resume specifically tailored for a Data Engineering role, you need to add the third step of the ETL pipeline: **Load (Saving the Data).**

Here are the exact next steps you can take to upgrade this project in the future:

### Step 1: Add a Database (The "Load" Phase)
Instead of just sending a Discord message and forgetting the data, your bot should save the extracted information into a structured database. 
* **Tool to learn:** SQLite or PostgreSQL.
* **Goal:** Every day at 11:00 PM, the bot scrapes your attendance and inserts a new row into an `attendance_history` SQL table. 

### Step 2: Build a Timeseries
Once you have an SQL database collecting data every single day, you will start building a historical timeline. You will have a record of exactly what your attendance percentage was on April 1st, April 15th, etc., and how many classes you attended that week.

### Step 3: Data Visualization (The Final Polish)
Connect your newly created database to a visualization or BI (Business Intelligence) tool.
* **Tools to learn:** Grafana, Metabase, or Python's `matplotlib`/`pandas`.
* **Goal:** Create a live graph showing the trajectory of your attendance over the entire semester. 

Building a system that automatically scrapes data, processes it, saves it to a PostgreSQL database, and visualizes it on a live dashboard is the exact definition of an end-to-end Data Engineering pipeline!
