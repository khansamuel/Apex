from flask import Flask, request, render_template_string
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
import os
import sqlite3
from datetime import datetime
import smtplib
from email.mime.text import MIMEText

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Twilio credentials
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
from_whatsapp = os.getenv("TWILIO_PHONE_NUMBER")
caregiver_number = os.getenv("ATTENDANT_PHONE_NUMBER")

# Email credentials (make sure to set these in your .env file)
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "khansamuel58@gmail.com")

# Twilio client
client = Client(account_sid, auth_token)

# SQLite init
def init_db():
    conn = sqlite3.connect('alerts.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            keyword TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# Log alert to DB
def log_alert(sender, keyword):
    conn = sqlite3.connect('alerts.db')
    c = conn.cursor()
    c.execute("INSERT INTO alerts (sender, keyword, timestamp) VALUES (?, ?, ?)",
              (sender, keyword, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

# Email fallback
def send_email_alert(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_RECEIVER

    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, EMAIL_RECEIVER, msg.as_string())
        print("Email alert sent successfully.")
    except Exception as e:
        print(f"Email alert failed: {e}")

# Supported keywords
KEYWORD_RESPONSES = {
    "apex": "🚨 Help alert from patient",
    "sam": "💊 Medication request from patient",
    "emergency": "🚑 Emergency alert from patient",
    "distress": "😖 Pain report from patient"
}

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From")
    resp = MessagingResponse()

    if incoming_msg in KEYWORD_RESPONSES:
        # Respond to patient
        resp.message(f"✅ '{incoming_msg}' message received. Sam has been notified.")

        # Notify caregiver via WhatsApp
        alert_msg = f"{KEYWORD_RESPONSES[incoming_msg]} ({sender})"
        try:
            client.messages.create(
                body=alert_msg,
                from_=from_whatsapp,
                to=caregiver_number
            )
        except Exception as e:
            print(f"WhatsApp send failed: {e}")

        # Fallback to email
        send_email_alert("Patient Alert Notification", alert_msg)

        # Log the alert
        log_alert(sender, incoming_msg)

    else:
        resp.message("🤖 I didn't recognize that. Try 'apex', 'emergency', 'sam', or 'distress'.")

    return str(resp)

# Dashboard view
@app.route("/dashboard")
def dashboard():
    conn = sqlite3.connect('alerts.db')
    c = conn.cursor()
    c.execute("SELECT sender, keyword, timestamp FROM alerts ORDER BY timestamp DESC")
    rows = c.fetchall()
    conn.close()

    html = '''
    <!DOCTYPE html>
    <html>
    <head><title>Alert Dashboard</title></head>
    <body>
        <h2>Patient Alert Logs</h2>
        <table border="1">
            <tr><th>Sender</th><th>Keyword</th><th>Timestamp</th></tr>
            {% for row in rows %}
            <tr>
                <td>{{ row[0] }}</td>
                <td>{{ row[1] }}</td>
                <td>{{ row[2] }}</td>
            </tr>
            {% endfor %}
        </table>
    </body>
    </html>
    '''
    return render_template_string(html, rows=rows)

# Debug info
print("SID:", account_sid)
print("From:", from_whatsapp)
print("To:", caregiver_number)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
