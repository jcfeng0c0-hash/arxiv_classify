import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
import os
from datetime import datetime

def send_email_with_attachment(sender_email, password, receiver_email, attachment_path):
    """
    发送带有附件的邮件
    :param sender_email: 发件人邮箱
    :param password: 发件人邮箱密码
    :param receiver_email: 收件人邮箱地址，可以是单个或多个
    :param attachment_path: 附件的文件路径
    """
    # 获取当天日期
    current_date = datetime.now().strftime("%Y-%m-%d")

    # 创建MIME对象
    message = MIMEMultipart()
    message['From'] = Header(f"<{sender_email}>")
    recipients = receiver_email if isinstance(receiver_email, list) else [receiver_email]
    message['To'] = ', '.join(recipients)

    # 邮件主题
    subject = f'Arxiv Daily, ({current_date})'
    message['Subject'] = Header(subject, 'utf-8')

    # 邮件正文
    text = f"论文分类结果({current_date})：\n\n"
    body = MIMEText(text, 'plain', 'utf-8')
    message.attach(body)

    # 附件处理（支持单个或多个附件）
    if attachment_path:
        # 确保是列表格式
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

    # 创建SMTP对象并发送邮件
    try:
        with smtplib.SMTP_SSL(host='smtp.qq.com', port=465, timeout=20) as server:
            server.login(sender_email, password)
            server.sendmail(sender_email, recipients, message.as_string())
        print("邮件发送成功")
    except Exception as e:
        print("邮件发送失败:", type(e).__name__)
