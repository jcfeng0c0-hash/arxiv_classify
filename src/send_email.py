import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
import base64
import os
from datetime import datetime

# Email domain
mail_domain = '@qq.com'

def send_email_with_attachment(sender_email, password, receiver_email, attachment_path):
    """
    Send an email with attachments.
    :param sender_email: Sender email address.
    :param password: Sender email password (authorization code for QQ Mail).
    :param receiver_email: Receiver email address(es); can be a single address or a list.
    :param attachment_path: Path(s) to the attachment(s).
    """
    # Get today's date
    current_date = datetime.now().strftime("%Y-%m-%d")

    # Create MIME message
    message = MIMEMultipart()
    message['From'] = Header(f"<{sender_email}>")
    message['To'] = Header(f"<{receiver_email}>")

    # Email subject
    subject = f'Arxiv Daily, ({current_date})'
    message['Subject'] = Header(subject, 'utf-8')

    # Email body
    text = f"Paper classification results ({current_date}):\n\n"
    body = MIMEText(text, 'plain', 'utf-8')
    message.attach(body)

    # Attachment handling (supports single or multiple attachments)
    if attachment_path:
        # Ensure it is a list
        if not isinstance(attachment_path, list):
            attachment_path = [attachment_path]
        for path in attachment_path:
            if os.path.exists(path):
                filename = os.path.basename(path)
                with open(path, 'rb') as f:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename={filename}')
                    message.attach(part)

    # Create SMTP object and send the email
    try:
        server = smtplib.SMTP_SSL(host='smtp.qq.com', port=465)  # Use SSL encryption
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, message.as_string())
        print("Email sent successfully")
    except Exception as e:
        print("Email sending failed:", e)
    finally:
        server.quit()
