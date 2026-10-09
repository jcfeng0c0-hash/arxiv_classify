from unittest.mock import patch

import pytest

from src.notify_tunnel import send_notification


def test_sends_plain_url_with_existing_smtp():
    with patch('src.notify_tunnel.smtplib.SMTP_SSL') as smtp:
        server = smtp.return_value.__enter__.return_value
        server.send_message.return_value = {}
        send_notification('https://example-test.trycloudflare.com',
                          'sender@qq.com', 'secret', ['user@qq.com', 'user@qq.com'])
        server.login.assert_called_once_with('sender@qq.com', 'secret')
        message = server.send_message.call_args.args[0]
        assert 'https://example-test.trycloudflare.com' in message.get_content()
        assert 'secret' not in message.as_string()
        assert server.send_message.call_args.kwargs['to_addrs'] == ['user@qq.com']
        assert smtp.call_args.kwargs['timeout'] == 20


@pytest.mark.parametrize('url,recipients', [
    ('https://evil.example', ['user@qq.com']),
    ('https://test.trycloudflare.com/path', ['user@qq.com']),
    ('https://test.trycloudflare.com', []),
    ('https://test.trycloudflare.com', ['bad\nrecipient@qq.com']),
])
def test_invalid_inputs_never_connect(url, recipients):
    with patch('src.notify_tunnel.smtplib.SMTP_SSL') as smtp:
        with pytest.raises(ValueError):
            send_notification(url, 'sender@qq.com', 'secret', recipients)
        smtp.assert_not_called()


def test_partial_recipient_failure_is_not_success():
    with patch('src.notify_tunnel.smtplib.SMTP_SSL') as smtp:
        smtp.return_value.__enter__.return_value.send_message.return_value = {'user@qq.com': (550, b'no')}
        with pytest.raises(Exception):
            send_notification('https://test.trycloudflare.com', 'sender@qq.com', 'secret', ['user@qq.com'])
