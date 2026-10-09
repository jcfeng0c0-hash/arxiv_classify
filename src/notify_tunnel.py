"""Send the current public tunnel URL using the existing email configuration."""

import argparse
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
import re
import smtplib
import ssl
import os

ROOT = Path(__file__).resolve().parents[1]


def send_notification(url, sender, password, recipients):
    url = url.strip()
    if not re.fullmatch(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', url):
        raise ValueError('Invalid Cloudflare URL')
    recipients = list(dict.fromkeys(recipients))
    if not sender or not password or not recipients:
        raise ValueError('Missing email configuration')
    if any(not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', r) for r in recipients):
        raise ValueError('Invalid recipient')
    message = EmailMessage()
    message['From'] = sender
    message['To'] = ', '.join(recipients)
    message['Subject'] = f'Arxiv WebUI 3.0 访问地址 ({datetime.now():%Y-%m-%d %H:%M:%S})'
    message.set_content(
        f'Arxiv WebUI 已启动，公网访问地址：\n\n{url}\n\n'
        '本链接为临时 Cloudflare 隧道地址，停止服务后失效，重启后可能改变。\n'
        '请勿将访问链接转发给无关人员。\n'
    )
    with smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=20,
                          context=ssl.create_default_context()) as server:
        server.login(sender, password)
        refused = server.send_message(message, from_addr=sender, to_addrs=recipients)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


def main(argv=None):
    parser = argparse.ArgumentParser(description='将 Cloudflare 访问地址发送到现有收件邮箱')
    parser.add_argument('url', nargs='?', help='省略时读取项目的 .cloudflare_url.txt')
    args = parser.parse_args(argv)
    try:
        from .config import EMAIL_USER, EMAIL_PASS
        url = args.url or (ROOT / '.cloudflare_url.txt').read_text(encoding='utf-8').strip()
        recipients = [item.strip() for item in os.environ.get('EMAIL_RECIPIENTS', '').split(',')
                      if item.strip()]
        recipient_file = ROOT / 'email_list.txt'
        if not recipients and recipient_file.exists():
            recipients = [line.strip() for line in recipient_file.read_text(encoding='utf-8').splitlines()
                          if line.strip() and not line.strip().startswith('#')]
        send_notification(url, EMAIL_USER, EMAIL_PASS, recipients)
    except Exception as exc:
        # Never print credentials or SMTP response bodies.
        print(f'❌ 链接邮件发送失败（{type(exc).__name__}），请检查邮箱配置和网络；服务不受影响。')
        return 1
    print('✅ 访问链接邮件已提交给邮件服务器。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
