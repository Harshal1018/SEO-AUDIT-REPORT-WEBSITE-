from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import requests
from bs4 import BeautifulSoup
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os
from datetime import datetime
import traceback
import logging

app = Flask(__name__)
CORS(app)  # Enable CORS

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize SQLite database
def init_db():
    try:
        conn = sqlite3.connect('audit.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            title TEXT,
            meta_desc TEXT,
            h1_count INTEGER,
            img_alt_missing INTEGER,
            broken_links INTEGER,
            timestamp TEXT
        )''')
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}")

# Perform SEO audit
def perform_seo_audit(url):
    try:
        logger.info(f"Fetching URL: {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Title
        title_tag = soup.find('title')
        title = title_tag.text if title_tag else "No title found"
        title_length = len(title)
        title_issue = "Title too long" if title_length > 60 else "Title OK"

        # Meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        meta_desc_content = meta_desc['content'] if meta_desc and meta_desc.get('content') else "No meta description"
        meta_desc_issue = "Missing meta description" if meta_desc_content == "No meta description" else "Meta description OK"

        # Headings
        h1_tags = soup.find_all('h1')
        h1_count = len(h1_tags)
        h1_issue = "Multiple or missing H1" if h1_count != 1 else "H1 OK"

        # Image alt tags
        images = soup.find_all('img')
        img_alt_missing = sum(1 for img in images if not img.get('alt'))
        img_alt_issue = f"{img_alt_missing} images missing alt text" if img_alt_missing > 0 else "All images have alt text"

        # Broken links
        broken_links = 0
        links = soup.find_all('a', href=True)
        for link in links:
            href = link['href']
            if href.startswith('http'):
                try:
                    link_response = requests.head(href, timeout=5)
                    if link_response.status_code >= 400:
                        broken_links += 1
                except requests.RequestException:
                    broken_links += 1

        return {
            'title': title,
            'title_issue': title_issue,
            'meta_desc': meta_desc_content,
            'meta_desc_issue': meta_desc_issue,
            'h1_count': h1_count,
            'h1_issue': h1_issue,
            'img_alt_missing': img_alt_missing,
            'img_alt_issue': img_alt_issue,
            'broken_links': broken_links,
            'broken_links_issue': f"{broken_links} broken links found" if broken_links > 0 else "No broken links"
        }
    except requests.RequestException as e:
        logger.error(f"Failed to fetch URL: {str(e)}")
        return {'error': f"Failed to fetch URL: {str(e)}"}

# Generate PDF report
def generate_pdf_report(audit_data, url):
    try:
        os.makedirs('reports', exist_ok=True)
        filename = f"reports/audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        doc = SimpleDocTemplate(filename, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph(f"SEO Audit Report for {url}", styles['Title']))
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
        story.append(Spacer(1, 12))

        for key, value in audit_data.items():
            if key.endswith('_issue'):
                story.append(Paragraph(f"{key.replace('_issue', '').title()}: {value}", styles['Normal']))
                story.append(Spacer(1, 6))

        doc.build(story)
        logger.info(f"PDF generated: {filename}")
        return filename
    except Exception as e:
        logger.error(f"Failed to generate PDF: {str(e)}")
        return {'error': f"Failed to generate PDF: {str(e)}"}

# Send email with report
def send_email(to_email, url, pdf_path):
    # Configure your email credentials
    sender_email = "neelspatel3677@gmail.com"  # Replace with your email
    sender_password = "idao hwjn davj hmbi"        # Replace with your app-specific password

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = f"SEO Audit Report for {url}"

    body = "Please find attached the SEO audit report."
    msg.attach(MIMEText(body, 'plain'))

    try:
        with open(pdf_path, 'rb') as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f"attachment; filename= {os.path.basename(pdf_path)}")
        msg.attach(part)

        server = smtplib.SMTP('neelspatel3677@gmail.com', 587)  # Update for your email provider
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        logger.info(f"Email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Email sending failed: {str(e)}")
        return False

# API to trigger audit
@app.route('/audit', methods=['POST'])
def audit():
    try:
        data = request.get_json()
        url = data.get('url')
        email = data.get('email')
        logger.info(f"Audit requested for URL: {url}, Email: {email}")

        if not url or not email:
            logger.error("Missing URL or email")
            return jsonify({'error': 'URL and email are required'}), 400

        audit_data = perform_seo_audit(url)
        if 'error' in audit_data:
            logger.error(f"Audit failed: {audit_data['error']}")
            return jsonify(audit_data), 500

        # Save to database
        conn = sqlite3.connect('audit.db')
        c = conn.cursor()
        c.execute('''INSERT INTO audits (url, title, meta_desc, h1_count, img_alt_missing, broken_links, timestamp)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (url, audit_data['title'], audit_data['meta_desc'], audit_data['h1_count'],
                   audit_data['img_alt_missing'], audit_data['broken_links'], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        logger.info("Audit data saved to database")

        # Generate and send report
        pdf_path = generate_pdf_report(audit_data, url)
        if isinstance(pdf_path, dict) and 'error' in pdf_path:
            logger.error(f"PDF generation failed: {pdf_path['error']}")
            return jsonify(pdf_path), 500

        email_sent = send_email(email, url, pdf_path)
        logger.info(f"Email sent status: {email_sent}")

        return jsonify({
            'audit': audit_data,
            'report_path': pdf_path,
            'email_sent': email_sent
        })
    except Exception as e:
        logger.error(f"Audit failed: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': f"Audit failed: {str(e)}"}), 500

# API to get audit results
@app.route('/results', methods=['GET'])
def get_results():
    try:
        conn = sqlite3.connect('audit.db')
        c = conn.cursor()
        c.execute('SELECT * FROM audits ORDER BY timestamp DESC')
        rows = c.fetchall()
        conn.close()

        results = []
        for row in rows:
            results.append({
                'id': row[0],
                'url': row[1],
                'title': row[2],
                'meta_desc': row[3],
                'h1_count': row[4],
                'img_alt_missing': row[5],
                'broken_links': row[6],
                'timestamp': row[7]
            })
        logger.info("Fetched audit results")
        return jsonify(results)
    except Exception as e:
        logger.error(f"Failed to fetch results: {str(e)}")
        return jsonify({'error': f"Failed to fetch results: {str(e)}"}), 500

if __name__ == '__main__':
    try:
        init_db()
        app.run(debug=True, port=5000)
    except Exception as e:
        logger.error(f"Server failed to start: {str(e)}\n{traceback.format_exc()}")