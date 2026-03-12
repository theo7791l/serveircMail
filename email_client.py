import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from typing import List, Dict

def decode_str(s):
    if not s: return ""
    parts = decode_header(s)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)

class EmailClient:
    def __init__(self, imap_host="", imap_port=993, smtp_host="", smtp_port=587, email_address="", email_password=""):
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.email_address = email_address
        self.email_password = email_password

    def _imap(self):
        mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        mail.login(self.email_address, self.email_password)
        return mail

    def get_folders(self):
        if not self.imap_host: return ["INBOX"]
        try:
            mail = self._imap()
            _, folders = mail.list()
            mail.logout()
            result = []
            for f in folders:
                decoded = f.decode() if isinstance(f, bytes) else f
                parts = decoded.split('"')
                name = parts[-1].strip().strip('"') if len(parts) > 1 else decoded
                result.append(name)
            return result
        except: return ["INBOX"]

    def get_mails(self, folder="INBOX", page=1, per_page=20):
        if not self.imap_host: return {"mails": [], "total": 0, "page": page, "per_page": per_page, "pages": 1}
        try:
            mail = self._imap()
            mail.select(folder)
            _, data = mail.search(None, "ALL")
            uids = sorted([int(u) for u in (data[0].split() if data[0] else [])], reverse=True)
            total = len(uids)
            page_uids = uids[(page-1)*per_page : page*per_page]
            mails = []
            for uid in page_uids:
                try:
                    _, msg_data = mail.fetch(str(uid), "(RFC822.HEADER FLAGS)")
                    if not msg_data or not msg_data[0]: continue
                    raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
                    if not raw: continue
                    msg = email.message_from_bytes(raw)
                    flags = msg_data[0][0].decode() if isinstance(msg_data[0][0], bytes) else ""
                    mails.append({"uid": uid, "from": decode_str(msg.get("From","")),
                        "to": decode_str(msg.get("To","")), "subject": decode_str(msg.get("Subject","(Sans sujet)")),
                        "date": msg.get("Date",""), "seen": "\\Seen" in flags})
                except: continue
            mail.logout()
            return {"mails": mails, "total": total, "page": page, "per_page": per_page, "pages": max(1,-(-total//per_page))}
        except Exception as e:
            return {"mails": [], "total": 0, "page": page, "per_page": per_page, "pages": 1, "error": str(e)}

    def get_mail(self, uid, folder="INBOX"):
        if not self.imap_host: return {"error": "IMAP non configuré"}
        try:
            mail = self._imap()
            mail.select(folder)
            _, msg_data = mail.fetch(str(uid), "(RFC822)")
            if not msg_data or not msg_data[0]: mail.logout(); return {"error": "Mail introuvable"}
            msg = email.message_from_bytes(msg_data[0][1])
            mail.store(str(uid), "+FLAGS", "\\Seen")
            mail.logout()
            body_text, body_html = "", ""
            if msg.is_multipart():
                for part in msg.walk():
                    ct = part.get_content_type()
                    if ct == "text/plain" and not body_text:
                        body_text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                    elif ct == "text/html" and not body_html:
                        body_html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
            else:
                p = msg.get_payload(decode=True)
                if p: body_text = p.decode(msg.get_content_charset() or "utf-8", errors="replace")
            return {"uid": uid, "from": decode_str(msg.get("From","")), "to": decode_str(msg.get("To","")),
                "subject": decode_str(msg.get("Subject","(Sans sujet)")), "date": msg.get("Date",""),
                "body_text": body_text, "body_html": body_html}
        except Exception as e: return {"error": str(e)}

    def send_mail(self, to, subject, body, html=False):
        if not self.smtp_host: return {"success": False, "error": "SMTP non configuré"}
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.email_address
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as s:
                s.ehlo(); s.starttls(); s.login(self.email_address, self.email_password)
                s.sendmail(self.email_address, to, msg.as_string())
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def mark_read(self, uid, folder="INBOX"):
        if not self.imap_host: return {"success": False}
        try:
            mail = self._imap(); mail.select(folder)
            mail.store(str(uid), "+FLAGS", "\\Seen"); mail.logout()
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def delete_mail(self, uid, folder="INBOX"):
        if not self.imap_host: return {"success": False}
        try:
            mail = self._imap(); mail.select(folder)
            mail.store(str(uid), "+FLAGS", "\\Deleted"); mail.expunge(); mail.logout()
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def get_stats(self):
        if not self.imap_host: return {"total": 0, "unseen": 0, "seen": 0}
        try:
            mail = self._imap(); mail.select("INBOX")
            _, all_d = mail.search(None, "ALL")
            _, unseen_d = mail.search(None, "UNSEEN")
            mail.logout()
            total = len(all_d[0].split()) if all_d[0] else 0
            unseen = len(unseen_d[0].split()) if unseen_d[0] else 0
            return {"total": total, "unseen": unseen, "seen": total - unseen}
        except Exception as e: return {"total": 0, "unseen": 0, "seen": 0, "error": str(e)}
