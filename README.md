# AstraAI 🌌

AstraAI is a Telegram AI assistant built around Mistral with persistent user preferences, conversation history, adaptive inline keyboards, configurable roles/personality/modes, and a foundation for long-term memory.

## Features

- Dynamic Telegram inline menu
- Role selection: Assistant, Pirate, Shakespeare, Scientist, Rapper
- Personality selection: Balanced, Friendly, Funny, Concise, Coach
- Mode selection: General, Study, Coding, Writing, Brainstorm, Business, Research
- Reply-language selection: English, French, Spanish, Arabic, German
- Neon/PostgreSQL persistence
- Recent conversation context sent to Mistral
- Long-term memory table ready for conservative memory extraction
- Render worker deployment configuration
- Telegram commands: `/start`, `/help`, `/settings`, `/reset`

## Environment variables

Required:

- `TELEGRAM_BOT_TOKEN`
- `MISTRAL_API_KEY`
- `DATABASE_URL`

Optional:

- `MISTRAL_API_URL`
- `MISTRAL_MODEL`

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

## Neon

Create a PostgreSQL database in Neon and set its connection string as `DATABASE_URL`. AstraAI creates its required tables automatically on startup. `schema.sql` is also included for manual initialization.

## Render

This repository includes both `Procfile` and `render.yaml`.

Create a Render Background Worker from the GitHub repository and provide:

- `TELEGRAM_BOT_TOKEN`
- `MISTRAL_API_KEY`
- `DATABASE_URL`

The worker runs `python bot.py`.

## Security

Never commit real `.env` files or API keys. Use Render Environment Variables for production secrets.
