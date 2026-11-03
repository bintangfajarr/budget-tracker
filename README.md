# Budget Tracker — Telegram Bot + Web Dashboard

Bot Telegram personal untuk mencatat keuangan secara otomatis dari notifikasi email **Bank Jago**, dilengkapi input manual, kategorisasi otomatis, laporan ringkasan, monitoring budget, dan **dashboard web** berbasis React.

---

## Fitur

| Fitur | Keterangan |
|---|---|
| **Auto-import Email** | Polling notifikasi email Jago via Gmail IMAP setiap N menit |
| **Input Manual** | Catat transaksi via Telegram dengan guided conversation |
| **Auto-kategorisasi** | Keyword matching untuk 10+ kategori (Makanan, Transport, dll) |
| **Ringkasan** | Laporan harian / mingguan / bulanan via `/hari`, `/minggu`, `/ringkasan` |
| **Budget Monitoring** | Set budget per kategori, pantau progress via `/budget` |
| **Notifikasi Real-time** | Push notif ke Telegram setiap ada transaksi baru dari email |
| **Dashboard Web** | React + FastAPI: grafik tren, pie chart, tabel transaksi, budget tracker |
| **Multi-user ready** | Whitelist user Telegram via `ALLOWED_USER_IDS` |

---

## Arsitektur

```
Email Jago ──IMAP──► email_poller.py ──► database.py (PostgreSQL)
                                    │
                                    └──► Telegram notif

Telegram User ──► bot.py ──► database.py

Browser ──► React SPA ──► FastAPI (api.py) ──► database.py
```

---

## Prasyarat Setup

Sebelum deploy, kamu perlu menyiapkan beberapa hal berikut:

### 1. Telegram Bot Token

1. Buka Telegram, cari **@BotFather**
2. Ketik `/newbot`, ikuti instruksi
3. Salin token yang diberikan (format: `123456789:ABC-abc...`)
4. Dapatkan Telegram User ID kamu lewat **@userinfobot** (ketik `/start`)

### 2. Gmail App Password

> **Penting:** Jangan gunakan password Gmail biasa. Gunakan App Password.

1. Aktifkan **2-Factor Authentication** di akun Google kamu
   - Buka: https://myaccount.google.com/security
2. Aktifkan **IMAP** di Gmail:
   - Gmail → Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP
3. Buat App Password:
   - Buka: https://myaccount.google.com/apppasswords
   - Pilih app: **Mail**, device: **Other** (tulis "BudgetBot")
   - Salin 16-digit password yang muncul (contoh: `abcd efgh ijkl mnop`)

### 3. Email Jago

- Pastikan notifikasi transaksi Jago **dikirim ke Gmail** yang kamu setup
- Cek di Jago app: Settings → Notifikasi → aktifkan notifikasi email

### 4. Oracle VPS (Free Tier)

- Buat akun di https://www.oracle.com/cloud/free/
- Buat instance **VM.Standard.A1.Flex** (ARM, 4 OCPU, 24 GB RAM — semua gratis)
- OS: **Ubuntu 22.04**
- Buka port di Security List: `22` (SSH), `80` (HTTP), `443` (HTTPS opsional)

---

## Setup & Deploy

### Clone repository

```bash
git clone https://github.com/bintangfajarr/budget-tracker.git
cd budget-tracker
```

### Konfigurasi `.env`

```bash
cp .env.example .env
nano .env
```

Isi semua nilai:

```env
TELEGRAM_BOT_TOKEN=123456789:ABC-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ALLOWED_USER_IDS=123456789          # Telegram user ID kamu

GMAIL_ADDRESS=kamu@gmail.com
GMAIL_APP_PASSWORD=abcd efgh ijkl mnop   # App Password 16 digit

DATABASE_URL=postgresql://budget_user:GANTI_PASSWORD@localhost:5432/budget_tracker

EMAIL_POLL_INTERVAL=5               # Cek email setiap 5 menit
```

### Deploy ke VPS (satu perintah)

SSH ke VPS, lalu jalankan:

```bash
bash deploy/deploy.sh
```

Script ini otomatis:
- Install Python 3.11, PostgreSQL, Node.js, Nginx
- Buat database & user PostgreSQL
- Setup Python virtualenv & install dependencies
- Build frontend React
- Install & enable systemd services
- Konfigurasi Nginx sebagai reverse proxy

### Verifikasi

```bash
# Status bot Telegram
sudo systemctl status budget-bot

# Status API dashboard
sudo systemctl status budget-api

# Lihat log bot
sudo journalctl -u budget-bot -f

# Lihat log API
sudo journalctl -u budget-api -f
```

Dashboard tersedia di: `http://IP_VPS_KAMU`

---

## Perintah Telegram Bot

| Perintah | Fungsi |
|---|---|
| `/start` | Mulai bot & lihat menu |
| `/tambah` | Catat transaksi manual (guided) |
| `/ringkasan` | Ringkasan pengeluaran bulan ini |
| `/minggu` | Ringkasan pengeluaran minggu ini |
| `/hari` | Ringkasan pengeluaran hari ini |
| `/riwayat` | 10 transaksi terakhir |
| `/budget` | Status budget vs pengeluaran |
| `/setbudget` | Set budget per kategori |
| `/kategori` | Daftar semua kategori |
| `/bantuan` | Bantuan |
| `/batal` | Batalkan percakapan yang sedang berjalan |

---

## Kategori Transaksi

**Pengeluaran:**
- 🍜 Makanan & Minuman
- 🚗 Transport
- 🛍️ Belanja
- 💡 Tagihan & Utilitas
- 🎮 Hiburan
- 🏥 Kesehatan
- 📚 Pendidikan
- 💹 Tabungan & Investasi
- 📌 Lain-lain

**Pemasukan:**
- 💵 Gaji & Pemasukan
- 📥 Transfer Masuk

Kategorisasi dilakukan **otomatis** berdasarkan keyword merchant/deskripsi. Bisa juga dipilih manual saat input via Telegram atau diubah di dashboard.

---

## Development Lokal

### Backend (Python)

```bash
# Install dependencies
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install uvicorn

# Setup database PostgreSQL lokal, lalu:
cp .env.example .env
# Edit .env sesuai konfigurasi lokal

# Jalankan bot
python main.py

# Jalankan API dashboard (terminal terpisah)
uvicorn api:app --reload --port 8000
```

### Frontend (React)

```bash
cd dashboard/frontend
npm install
npm run dev      # Development server di http://localhost:5173
npm run build    # Build production ke dist/
```

---

## Struktur Folder

```
budget-tracker/
├── main.py                 # Entry point bot + scheduler
├── api.py                  # FastAPI REST API + serve frontend
├── requirements.txt
├── .env.example
├── src/
│   ├── handlers/bot.py     # Telegram bot commands & conversations
│   ├── models/database.py  # PostgreSQL schema & query helpers
│   ├── parsers/jago.py     # Gmail IMAP + Jago email parser
│   └── services/
│       ├── categorizer.py  # Auto-kategorisasi keyword
│       ├── email_poller.py # Background email polling (APScheduler)
│       └── formatter.py    # Format pesan & laporan
├── dashboard/frontend/     # React + TypeScript + Tailwind
└── deploy/
    ├── deploy.sh           # Script deploy VPS
    ├── budget-bot.service  # systemd unit (bot)
    └── budget-api.service  # systemd unit (API)
```

---

## Troubleshooting

**Bot tidak menerima pesan dari email Jago**
- Pastikan notifikasi email Jago aktif dan dikirim ke Gmail yang dikonfigurasi
- Cek log: `sudo journalctl -u budget-bot -f`
- Pastikan IMAP Gmail aktif dan App Password benar

**Error `IMAP authentication failed`**
- Pastikan menggunakan **App Password**, bukan password Gmail biasa
- Verifikasi 2FA aktif di akun Google

**Dashboard tidak bisa diakses**
- Cek port 80 terbuka di Oracle Security List
- Cek Nginx: `sudo nginx -t && sudo systemctl status nginx`
- Cek API: `sudo systemctl status budget-api`

**Database connection error**
- Verifikasi PostgreSQL running: `sudo systemctl status postgresql`
- Cek `DATABASE_URL` di `.env` sudah benar
