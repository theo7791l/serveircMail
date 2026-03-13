"""Groq AI client for Awlor mail assistant."""
import os
import json
from typing import Optional

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

SYSTEM_PROMPT = """Tu es Awlor AI, l'assistant intelligent intégré à la boîte mail Awlor.
Tu es capable de :
- Résumer des mails et des conversations
- Rédiger des réponses professionnelles ou décontractées
- Détecter le spam et les tentatives de phishing
- Traduire des mails dans n'importe quelle langue
- Générer des mails complets depuis une instruction simple
- Trier et catégoriser les mails
- Suggérer des règles de tri automatique
- Analyser le ton d'un mail
- Extraire les actions à faire depuis un mail

Réponds toujours en français sauf si on te demande explicitement une autre langue.
Sois concis, professionnel et utile.
Quand tu génères un mail, utilise le format :
OBJET: [sujet]
CORPS: [contenu du mail]"""


def get_client() -> Optional[object]:
    if not GROQ_AVAILABLE:
        return None
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return None
    try:
        return Groq(api_key=api_key)
    except Exception:
        return None


def chat(messages: list, model: str = "llama-3.3-70b-versatile") -> dict:
    """Send messages to Groq and return response."""
    client = get_client()
    if not client:
        return {"error": "Groq API non disponible. Vérifie la clé GROQ_API_KEY dans les paramètres.", "content": None}
    try:
        full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        completion = client.chat.completions.create(
            model=model,
            messages=full_messages,
            max_tokens=2048,
            temperature=0.7,
        )
        return {"content": completion.choices[0].message.content, "error": None}
    except Exception as e:
        return {"error": str(e), "content": None}


def summarize_mail(subject: str, body: str, sender: str) -> dict:
    msg = f"Résume ce mail en 2-3 phrases clés et liste les actions à faire (s'il y en a) :\n\nDe: {sender}\nObjet: {subject}\n\n{body[:3000]}"
    return chat([{"role": "user", "content": msg}])


def generate_reply(subject: str, body: str, sender: str, instruction: str = "réponse professionnelle") -> dict:
    msg = f"Génère une {instruction} à ce mail :\n\nDe: {sender}\nObjet: {subject}\n\n{body[:2000]}"
    return chat([{"role": "user", "content": msg}])


def detect_spam(subject: str, body: str, sender: str) -> dict:
    msg = f"Analyse ce mail et dis-moi s'il s'agit de spam, phishing ou d'un mail légitime. Donne un score de confiance de 0 à 100 et une explication courte.\n\nDe: {sender}\nObjet: {subject}\n\n{body[:1500]}"
    return chat([{"role": "user", "content": msg}])


def translate_mail(subject: str, body: str, target_lang: str = "français") -> dict:
    msg = f"Traduis ce mail en {target_lang} :\n\nObjet: {subject}\n\n{body[:2000]}"
    return chat([{"role": "user", "content": msg}])


def suggest_rules(mails_summary: list) -> dict:
    summary = json.dumps(mails_summary[:20], ensure_ascii=False)
    msg = f"Voici un résumé des derniers mails reçus. Suggère des règles de tri automatique pertinentes (expéditeur → dossier, sujet → label, etc.) :\n\n{summary}"
    return chat([{"role": "user", "content": msg}])


def extract_actions(subject: str, body: str) -> dict:
    msg = f"Extrait toutes les actions à faire, deadlines et informations importantes de ce mail :\n\nObjet: {subject}\n\n{body[:2000]}"
    return chat([{"role": "user", "content": msg}])
