from dotenv import load_dotenv
import os
load_dotenv()

class Settings:
    # SMTP Resend
    SMTP_HOST: str = "smtp.resend.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = "resend"
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")

    MAIL_DOMAIN: str = os.getenv("MAIL_DOMAIN", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "changeme_please")

settings = Settings()
