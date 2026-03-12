from dotenv import load_dotenv
import os
load_dotenv()

class Settings:
    IMAP_HOST: str = os.getenv("IMAP_HOST", "")
    IMAP_PORT: int = int(os.getenv("IMAP_PORT", 993))
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", 587))
    EMAIL_PASSWORD: str = os.getenv("EMAIL_PASSWORD", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "changeme_please")

settings = Settings()
