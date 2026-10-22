"""Отправка заказов поставщикам по e-mail (С-11). Без настроенного SMTP письмо кладётся в data/outbox."""
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from ..config import get_settings


def send(to: str, subject: str, body: str, attachment: bytes | None = None, filename: str = "") -> str:
    """Возвращает, куда ушло письмо: 'smtp' или путь к файлу в outbox."""
    s = get_settings()
    if s.smtp_host and to:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
        msg.set_content(body)
        if attachment:
            msg.add_attachment(attachment, maintype="application",
                               subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=filename)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            if s.smtp_tls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return "smtp"
    s.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = Path(s.outbox_dir) / f"{stamp}_{filename.rsplit('.', 1)[0] or 'letter'}"
    base.with_suffix(".txt").write_text(f"Кому: {to or '—'}\nТема: {subject}\n\n{body}", encoding="utf-8")
    if attachment:
        base.with_suffix(".xlsx").write_bytes(attachment)
    return str(base.with_suffix(".xlsx" if attachment else ".txt"))
