"""SMTP email delivery for the local job agent."""

import smtplib
from email.message import EmailMessage


def send_email_notification(subject: str, body_text: str, body_html: str, settings: dict) -> dict:
    smtp_host = str(settings.get("smtp_host") or "").strip()
    from_address = str(settings.get("from_address") or "").strip()
    to_addresses = [
        str(value).strip() for value in settings.get("to_addresses", []) if str(value).strip()
    ]
    if not smtp_host or not from_address or not to_addresses:
        raise ValueError("Email notifier is missing smtp_host, from_address, or to_addresses")

    smtp_port = int(settings.get("smtp_port", 587) or 587)
    smtp_username = str(settings.get("smtp_username") or "").strip()
    smtp_password = str(settings.get("smtp_password") or "").strip()
    use_tls = bool(settings.get("use_tls", True))

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = ", ".join(to_addresses)
    message.set_content(body_text)
    if body_html:
        message.add_alternative(f"<html><body>{body_html}</body></html>", subtype="html")

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        if use_tls:
            server.starttls()
            server.ehlo()
        if smtp_username:
            server.login(smtp_username, smtp_password)
        server.send_message(message)

    return {
        "channel": "email",
        "sent": True,
        "recipients": to_addresses,
    }
