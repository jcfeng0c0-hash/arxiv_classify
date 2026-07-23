import os
import re
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

# IMAP hostname
IMAP_HOST = 'imap.qq.com'

def connect_and_login(email_user: str, email_pass: str):
    """
    Connect to IMAP and log in.
    Returns (mail, status):
      mail  : imaplib.IMAP4_SSL instance
      status: 'OK' or 'NO'
    """
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        status, _ = mail.login(email_user, email_pass)
        return mail, status
    except Exception as e:
        print(f"Login failed: {e}")
        return None, 'NO'

def fetch_latest_email(mail, folder_name: str = 'INBOX'):
    """
    Select the specified folder and fetch the latest email of the current day.
    Returns (msg, subject, from_, date_str):
      - msg: email.message.Message object (None if not found or on error)
      - subject, from_, date_str: corresponding email information
    """
    # Select the mailbox folder
    status, _ = mail.select(folder_name)
    if status != 'OK':
        print(f"Cannot select folder: {folder_name}")
        return None, None, None, None

    # Get today and the next day
    today = datetime.today().strftime('%d-%b-%Y')
    next_day = (datetime.today() + timedelta(days=1)).strftime('%d-%b-%Y')

    # Search emails by date
    status, response = mail.search(None, f'(SENTSINCE {today} SENTBEFORE {next_day})')
    if status != 'OK':
        print(f"Email search failed: {status}")
        return None, None, None, None

    ids = response[0].split()
    if not ids:
        print("No emails found for today.")
        return None, None, None, None

    # Fetch the latest email
    latest_mail_id = ids[-1]
    status, data = mail.fetch(latest_mail_id, '(RFC822)')
    if status != 'OK':
        print(f"Failed to fetch email content: {status}")
        return None, None, None, None

    msg = email.message_from_bytes(data[0][1])

    # Parse the email Subject
    raw_subject = msg['subject']
    subject, encoding = decode_header(raw_subject)[0] if raw_subject else ("No Subject", None)
    if isinstance(subject, bytes):
        subject = subject.decode(encoding or 'utf-8')

    # Parse From
    raw_from = msg.get('from')
    from_, encoding = decode_header(raw_from)[0] if raw_from else ("Unknown", None)
    if isinstance(from_, bytes):
        from_ = from_.decode(encoding or 'utf-8')

    date_str = msg.get('date', "Unknown Date")

    return msg, subject, from_, date_str

def get_email_text_body(msg):
    """
    Return the text/plain part of the email as a string. For multipart messages, walk all parts.
    """
    if not msg:
        return ""

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition", "").startswith("attachment"):
                body = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
                break  # Break if only the first text part is needed; concatenate if all parts are needed
    else:
        body = msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='ignore')
    return body

def save_email_as_xml(subject, from_, date_str, body, output_dir='./downloads'):
    """
    Save email information as an XML file.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Create root element
    root = ET.Element("email")
    ET.SubElement(root, "subject").text = subject
    ET.SubElement(root, "from").text = from_
    ET.SubElement(root, "date").text = date_str
    ET.SubElement(root, "body").text = body

    # Sanitize illegal characters from the filename
    def sanitize_filename(filename):
        return re.sub(r'[\\/*?:"<>|]', '_', filename)

    subject_for_filename = sanitize_filename(subject)
    today_str = datetime.today().strftime('%Y%m%d')  # YYYYMMDD
    xml_filename = os.path.join(output_dir, f"{subject_for_filename}_{today_str}")

    # Write XML
    tree = ET.ElementTree(root)
    tree.write(xml_filename+'.xml', encoding="utf-8", xml_declaration=True)

    return xml_filename

def close_connection(mail):
    """
    Close the IMAP connection.
    """
    try:
        mail.close()
        mail.logout()
    except:
        pass
