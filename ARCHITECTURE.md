src/
├── handlers/
│   └── bot.py          # Telegram bot handlers & conversations
├── models/
│   └── database.py     # PostgreSQL schema, queries, helpers
├── parsers/
│   └── jago.py         # Gmail IMAP fetcher & Jago email parser
└── services/
    ├── categorizer.py  # Auto-categorization via keyword rules
    ├── email_poller.py # APScheduler background email polling
    └── formatter.py    # Currency & message formatting helpers

dashboard/
└── frontend/           # React + TypeScript + Tailwind dashboard
    └── src/
        ├── pages/
        │   ├── Dashboard.tsx
        │   ├── Transactions.tsx
        │   └── Budget.tsx
        ├── App.tsx
        ├── api.ts
        └── utils.ts

deploy/
├── budget-bot.service  # systemd unit — Telegram bot
├── budget-api.service  # systemd unit — FastAPI dashboard
└── deploy.sh           # One-shot VPS setup script

api.py                  # FastAPI REST backend
main.py                 # Entry point (bot + scheduler)
requirements.txt
.env.example
