# ✉️ serveircMail

> Un client webmail ultra-moderne, animé et magnifique — conçu pour tourner dans un container Python Pterodactyl avec un seul port exposé.

![Python](https://img.shields.io/badge/Python-3.11+-6C63FF?style=for-the-badge&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-3EC6E0?style=for-the-badge&logo=fastapi)
![License](https://img.shields.io/badge/License-MIT-FF6584?style=for-the-badge)

---

## ✨ Fonctionnalités

- 📥 Boîte de réception avec pagination et recherche en temps réel
- 📖 Lecture de mails (HTML + texte brut)
- ✏️ Rédaction avec éditeur riche (gras, italique, listes, mode HTML)
- 📤 Envoi via SMTP
- 🔁 Réponse rapide
- 🗑️ Suppression de mails
- 📁 Navigation entre dossiers (INBOX, Envoyés, Corbeille...)
- 📊 Stats non-lus en direct
- 🎨 UI ultra-animée, particules, glows, gradients
- ⌨️ Raccourcis clavier (`N` = nouveau mail, `Echap` = inbox)
- 🔒 Authentification par mot de passe
- 🌐 Compatible domaine perso (`vous@youtube.serveirc.com`)

---

## 🚀 Installation (Container Pterodactyl Python)

### 1. Cloner le projet
```bash
git clone https://github.com/theo7791l/serveircMail.git
cd serveircMail
```

### 2. Configurer les variables d'environnement
```bash
cp .env.example .env
nano .env
```

Remplir les valeurs dans `.env` :
```env
IMAP_HOST=imap.votreprovider.com
IMAP_PORT=993
SMTP_HOST=smtp.votreprovider.com
SMTP_PORT=587
EMAIL_ADDRESS=vous@youtube.serveirc.com
EMAIL_PASSWORD=votre_mot_de_passe
SECRET_KEY=cle_secrete_tres_longue_et_aleatoire
SITE_NAME=serveircMail
```

### 3. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 4. Lancer le serveur
```bash
PORT=7435 python main.py
```

Ou via Pterodactyl, configurez la variable `PORT=7435` et l'entrypoint `python main.py`.

---

## ⚙️ Configuration Pterodactyl

| Variable | Valeur |
|---|---|
| `PY_FILE` | `main.py` |
| `PORT` | `7435` |

Dans `.env` ou dans les variables d'environnement du container.

---

## 🌐 Configurer son domaine perso

Pour avoir une adresse `vous@youtube.serveirc.com` :
1. Choisir un provider mail supportant les custom domains (Proton Mail, Fastmail, mailbox.org, ForwardEmail...)
2. Ajouter leurs enregistrements **MX** dans la zone DNS de `youtube.serveirc.com`
3. Ajouter **SPF**, **DKIM**, **DMARC** recommandés
4. Créer l'adresse dans le panel du provider
5. Utiliser ses identifiants IMAP/SMTP dans le `.env`

---

## 📁 Structure du projet

```
serveircMail/
├── main.py             # FastAPI app + routes
├── email_client.py     # Logique IMAP/SMTP
├── config.py           # Paramètres (via .env)
├── requirements.txt
├── .env.example
├── templates/
│   ├── base.html       # Layout HTML + fonts
│   ├── login.html
│   ├── inbox.html
│   ├── read.html
│   └── compose.html
└── static/
    ├── css/
    │   ├── style.css       # UI complète
    │   └── animations.css  # Keyframes & effets
    └── js/
        └── main.js         # Particles, ripple, raccourcis
```

---

## 🎨 Stack technique

- **Backend** : FastAPI + Uvicorn
- **Email** : imaplib (IMAP) + smtplib (SMTP)
- **Templates** : Jinja2
- **Style** : CSS custom (dark UI, gradients, animations)
- **JS** : Vanilla JS (particles, ripple, raccourcis clavier)
- **Fonts** : Inter + Space Grotesk

---

*Made with 💜 by theo7791l*
