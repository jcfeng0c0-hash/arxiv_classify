import os
import re
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

# 定义 IMAP 主机名
IMAP_HOST = 'imap.qq.com'

def connect_and_login(email_user: str, email_pass: str):
    """
    连接到 IMAP 并登录。
    返回 (mail, status)：
    mail 是 imaplib.IMAP4_SSL 实例
    status 是字符串 'OK' 或 'NO'
    """
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        status, _ = mail.login(email_user, email_pass)
        return mail, status
    except Exception as e:
        print(f"登录失败: {e}")
        return None, 'NO'

def fetch_latest_email(mail, folder_name: str = 'INBOX'):
    """
    选择指定文件夹，获取当天最新一封邮件。
    返回 (msg, subject, from_, date_str)：
      - msg: email.message.Message 对象（如果找不到或发生错误，则返回 None）
      - subject, from_, date_str 对应邮件信息
    """
    # 选择邮箱文件夹
    status, _ = mail.select(folder_name)
    if status != 'OK':
        print(f"无法选择文件夹: {folder_name}")
        return None, None, None, None

    # 获取当天与下一天
    today = datetime.today().strftime('%d-%b-%Y')
    next_day = (datetime.today() + timedelta(days=1)).strftime('%d-%b-%Y')

    # 根据时间搜索邮件
    status, response = mail.search(None, f'(SENTSINCE {today} SENTBEFORE {next_day})')
    if status != 'OK':
        print(f"搜索邮件失败: {status}")
        return None, None, None, None

    ids = response[0].split()
    if not ids:
        print("今天没有找到任何邮件。")
        return None, None, None, None

    # 获取最新邮件ID并取邮件
    latest_mail_id = ids[-1]
    status, data = mail.fetch(latest_mail_id, '(RFC822)')
    if status != 'OK':
        print(f"获取邮件内容失败: {status}")
        return None, None, None, None

    msg = email.message_from_bytes(data[0][1])

    # 解析邮件 Subject
    raw_subject = msg['subject']
    subject, encoding = decode_header(raw_subject)[0] if raw_subject else ("No Subject", None)
    if isinstance(subject, bytes):
        subject = subject.decode(encoding or 'utf-8')

    # 解析 From
    raw_from = msg.get('from')
    from_, encoding = decode_header(raw_from)[0] if raw_from else ("Unknown", None)
    if isinstance(from_, bytes):
        from_ = from_.decode(encoding or 'utf-8')

    date_str = msg.get('date', "Unknown Date")

    return msg, subject, from_, date_str

def get_email_text_body(msg):
    """
    获取邮件的 text/plain 部分作为字符串返回。如果是 multipart，则遍历所有 part。
    """
    if not msg:
        return ""

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition", "").startswith("attachment"):
                body = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
                break  # 如果只要第一段正文，可以 break；要全部的话可以拼接
    else:
        body = msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='ignore')
    return body

def save_email_as_xml(subject, from_, date_str, body, output_dir='./downloads'):
    """
    将邮件信息保存为XML文件。
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 创建根元素
    root = ET.Element("email")
    ET.SubElement(root, "subject").text = subject
    ET.SubElement(root, "from").text = from_
    ET.SubElement(root, "date").text = date_str
    ET.SubElement(root, "body").text = body

    # 处理文件名中的非法字符
    def sanitize_filename(filename):
        return re.sub(r'[\\/*?:"<>|]', '_', filename)

    subject_for_filename = sanitize_filename(subject)
    today_str = datetime.today().strftime('%Y%m%d')  # YYYYMMDD
    xml_filename = os.path.join(output_dir, f"{subject_for_filename}_{today_str}")

    # 写入XML
    tree = ET.ElementTree(root)
    tree.write(xml_filename+'.xml', encoding="utf-8", xml_declaration=True)

    return xml_filename

def close_connection(mail):
    """
    关闭IMAP连接
    """
    try:
        mail.close()
        mail.logout()
    except:
        pass