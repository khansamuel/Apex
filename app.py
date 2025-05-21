from flask import Flask, request, render_template_string, jsonify, redirect, url_for
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
import os
import sqlite3
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
import uuid
import pdfplumber

# Load environment variables
load_dotenv()

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Twilio credentials
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
from_whatsapp = os.getenv("TWILIO_PHONE_NUMBER")
caregiver_number = os.getenv("ATTENDANT_PHONE_NUMBER")

# Email credentials
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "khansamuel58@gmail.com")

# Initialize Twilio client
client = Client(account_sid, auth_token)

# Load DialoGPT model & tokenizer
tokenizer = AutoTokenizer.from_pretrained("microsoft/DialoGPT-medium")
model = AutoModelForCausalLM.from_pretrained("microsoft/DialoGPT-medium")

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
    "apex": "💬 Message from Mel🌻 has been sent",
    "sam": " Your request has been sent😁",
    "emergency": "🚑 Emergency alert from patient",
    "distress": "😖 Pain report from patient"
}

# Generate AI reply using DialoGPT
def generate_reply(user_input, chat_history_ids=None):
    new_input_ids = tokenizer.encode(user_input + tokenizer.eos_token, return_tensors='pt')
    bot_input = torch.cat([chat_history_ids, new_input_ids], dim=-1) if chat_history_ids is not None else new_input_ids
    chat_history_ids = model.generate(bot_input, max_length=1000, pad_token_id=tokenizer.eos_token_id)
    reply = tokenizer.decode(chat_history_ids[:, bot_input.shape[-1]:][0], skip_special_tokens=True)
    return reply, chat_history_ids

# Extract text from PDF


ALLOWED_EXTENSIONS = {'.pdf'}

def allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS

# Extract text from PDF
def extract_text_from_pdf(path):
    text = ''
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text
    except Exception as e:
        print(f"PDF extraction error: {e}")
    return text

# Webhook for WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From")
    print(f"Incoming message from {sender}: {incoming_msg}")

    resp = MessagingResponse()
    lowered = incoming_msg.lower()
    triggered = [key for key in KEYWORD_RESPONSES if key in lowered]

    if triggered:
        keyword = triggered[0]
        alert_msg = f"{KEYWORD_RESPONSES[keyword]} ({sender})"

        try:
            client.messages.create(body=alert_msg, from_=from_whatsapp, to=caregiver_number)
        except Exception as e:
            print(f"WhatsApp send failed: {e}")

        send_email_alert("Patient Alert Notification", alert_msg)
        log_alert(sender, keyword)
        resp.message(f" Mel🌻 We have sent a notification message💬: '{keyword}'. Hang tight!")
    else:
        if incoming_msg.startswith("/analyze "):
            file_id = incoming_msg.split(maxsplit=1)[1]
            path = os.path.join(UPLOAD_FOLDER, file_id)

            if os.path.exists(path):
                document_text = extract_text_from_pdf(path)
                if document_text:
                    summary_input = f"Summarize: {document_text[:1000]}"
                    reply, _ = generate_reply(summary_input)
                    resp.message(reply)
                else:
                    resp.message("Sorry, couldn't extract text from the PDF.")
            else:
                resp.message("File not found. Please upload again.")
        else:
            reply, _ = generate_reply(incoming_msg)
            resp.message(reply)

    return str(resp)

# Document upload endpoint
@app.route("/upload", methods=["POST"])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Unsupported file type. Only PDFs allowed.'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    file_id = f"{uuid.uuid4()}{ext}"
    path = os.path.join(UPLOAD_FOLDER, file_id)

    try:
        file.save(path)
        return jsonify({'file_id': file_id}), 200
    except Exception as e:
        print(f"File save error: {e}")
        return jsonify({'error': 'File upload failed'}), 500




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

# Init and run
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
