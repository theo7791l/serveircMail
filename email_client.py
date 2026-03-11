import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from config import settings
from typing import List, Dict, Any
import re

def decode_str(s):
    if not s:
        return ""
    parts = decode_header(s)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)

class EmailClient:
    def _imap(self):
        mail = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
        mail.login(settings.EMAIL_ADDRESS, settings.EMAIL_PASSWORD)
        return mail

    def get_folders(self) -> List[str]:
        try:
            mail = self._imap()
            status, folders = mail.list()
            mail.logout()
            result = []
            for f in folders:
                decoded = f.decode() if isinstance(f, bytes) else f
                parts = decoded.split('"')
                name = parts[-1].strip().strip('"') if len(parts) > 1 else decoded
                result.append(name)
            return result
        except Exception as e:
            return ["INBOX"]

    def get_mails(self, folder: str = "INBOX", page: int = 1, per_page: int = 20) -> Dict:
        try:
            mail = self._imap()
            mail.select(folder)
            status, data = mail.search(None, "ALL")
            mail.logout()
            uids = data[0].split() if data[0] else []
            uids = [int(u) for u in uids]
            uids.sort(reverse=True)
            total = len(uids)
            start = (page - 1) * per_page
            end = start + per_page
            page_uids = uids[start:end]

            mail = self._imap()
            mail.select(folder)
            mails = []
            for uid in page_uids:
                try:
                    status, msg_data = mail.fetch(str(uid), "(RFC822.HEADER FLAGS)")
                    if not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
                    if not raw:
                        continue
                    msg = email.message_from_bytes(raw)
                    flags = msg_data[0][0].decode() if isinstance(msg_data[0][0], bytes) else ""
                    seen = "\\Seen" in flags
                    mails.append({
                        "uid": uid,
                        "from": decode_str(msg.get("From", "")),
                        "to": decode_str(msg.get("To", "")),
                        "subject": decode_str(msg.get("Subject", "(Sans sujet)")),
                        "date": msg.get("Date", ""),
                        "seen": seen
                    })
                except Exception:
                    continue
            mail.logout()
            return {
                "mails": mails,
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": max(1, -(-total // per_page))
            }
        except Exception as e:
            return {"mails": [], "total": 0, "page": page, "per_page": per_page, "pages": 1, "error": str(e)}

    def get_mail(self, uid: int, folder: str = "INBOX") -> Dict:
        try:
            mail = self._imap()
            mail.select(folder)
            status, msg_data = mail.fetch(str(uid), "(RFC822)")
            if not msg_data or not msg_data[0]:
                mail.logout()
                return {"error": "Mail introuvable"}
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            mail.store(str(uid), "+FLAGS", "\\Seen")
            mail.logout()

            body_text = ""
            body_html = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ct = part.get_content_type()
                    if ct == "text/plain" and not body_text:
                        body_text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                    elif ct == "text/html" and not body_html:
                        body_html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

            return {
                "uid": uid,
                "from": decode_str(msg.get("From", "")),
                "to": decode_str(msg.get("To", "")),
                "subject": decode_str(msg.get("Subject", "(Sans sujet)")),
                "date": msg.get("Date", ""),
                "body_text": body_text,
                "body_html": body_html
            }
        except Exception as e:
            return {"error": str(e)}

    def send_mail(self, to: str, subject: str, body: str, html: bool = False) -> Dict:
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = settings.EMAIL_ADDRESS
            msg["To"] = to
            msg["Subject"] = subject
            if html:
                msg.attach(MIMEText(body, "html", "utf-8"))
            else:
                msg.attach(MIMEText(body, "plain", "utf-8"))
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.login(settings.EMAIL_ADDRESS, settings.EMAIL_PASSWORD)
                server.sendmail(settings.EMAIL_ADDRESS, to, msg.as_string())
            return {"success": True, "message": "Mail envoyé avec succès"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def mark_read(self, uid: int, folder: str = "INBOX") -> Dict:
        try:
            mail = self._imap()
            mail.select(folder)
            mail.store(str(uid), "+FLAGS", "\\Seen")
            mail.logout()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_mail(self, uid: int, folder: str = "INBOX") -> Dict:
        try:
            mail = self._imap()
            mail.select(folder)
            mail.store(str(uid), "+FLAGS", "\\Deleted")
            mail.expunge()
            mail.logout()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_stats(self) -> Dict:
        try:
            mail = self._imap()
            mail.select("INBOX")
            _, all_data = mail.search(None, "ALL")
            _, unseen_data = mail.search(None, "UNSEEN")
            mail.logout()
            total = len(all_data[0].split()) if all_data[0] else 0
            unseen = len(unseen_data[0].split()) if unseen_data[0] else 0
            return {
                "total": total,
                "unseen": unseen,
                "seen": total - unseen
            }
        except Exception as e:
            return {"total": 0, "unseen": 0, "seen": 0, "error": str(e)}
