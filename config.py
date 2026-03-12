from dotenv import load_dotenv
import os
load_dotenv()

class Settings:
    # IMAP (reception)
    IMAP_HOST: str = os.getenv("IMAP_HOST", "imap.gmail.com")
    IMAP_PORT: int = int(os.getenv("IMAP_PORT", 993))
    IMAP_USER: str = os.getenv("IMAP_USER", "")
    EMAIL_PASSWORD: str = os.getenv("EMAIL_PASSWORD", "")

    # SMTP (envoi via Mailtrap)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "live.smtp.mailtrap.io")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER: str = os.getenv("SMTP_USER", "api")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")

    SECRET_KEY: str = os.getenv("SECRET_KEY", "changeme_please")

settings = Settings()
