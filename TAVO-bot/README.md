# Togetherly-бот для пари (Telegram Mini App)

1. @BotFather → /newbot → скопіюй токен.
2. Потрібен HTTPS-домен (Railway / Render / VPS + Caddy, або `cloudflared tunnel --url http://localhost:8080` для тесту).
3. `cp .env.example .env`, заповни BOT_TOKEN і BASE_URL.
4. `pip install -r requirements.txt`
5. `export $(cat .env | xargs) && python app.py`
6. У @BotFather: /mybots → твій бот → Bot Settings → Menu Button (вже ставиться кодом) і /setdomain = твій домен.
