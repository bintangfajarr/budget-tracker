#!/bin/bash
# deploy.sh — Run this script on your Oracle VPS (Ubuntu 22.04) to set up Budget Tracker
set -e

echo "==> Updating packages..."
sudo apt update && sudo apt upgrade -y

echo "==> Installing dependencies..."
sudo apt install -y python3.11 python3.11-venv python3-pip postgresql postgresql-contrib nginx nodejs npm git

echo "==> Setting up PostgreSQL..."
sudo -u postgres psql <<EOF
CREATE USER budget_user WITH PASSWORD 'CHANGE_ME_STRONG_PASSWORD';
CREATE DATABASE budget_tracker OWNER budget_user;
GRANT ALL PRIVILEGES ON DATABASE budget_tracker TO budget_user;
EOF

echo "==> Cloning / updating project..."
if [ -d /opt/budget-tracker ]; then
  cd /opt/budget-tracker && git pull
else
  sudo git clone https://github.com/bintangfajarr/budget-tracker.git /opt/budget-tracker
  sudo chown -R ubuntu:ubuntu /opt/budget-tracker
fi

cd /opt/budget-tracker

echo "==> Setting up Python virtualenv..."
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install uvicorn

echo "==> Setting up .env (copy and edit manually if not exists)..."
if [ ! -f .env ]; then
  cp .env.example .env
  echo ">>> EDIT /opt/budget-tracker/.env with your credentials before continuing!"
  exit 1
fi

echo "==> Building frontend..."
cd dashboard/frontend
npm ci
npm run build
cd /opt/budget-tracker

echo "==> Installing systemd services..."
sudo cp deploy/budget-bot.service /etc/systemd/system/
sudo cp deploy/budget-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable budget-bot budget-api
sudo systemctl restart budget-bot budget-api

echo "==> Configuring Nginx..."
sudo tee /etc/nginx/sites-available/budget-tracker > /dev/null <<'NGINX'
server {
    listen 80;
    server_name _;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/budget-tracker /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx

echo ""
echo "==> Deployment selesai!"
echo "    Bot status : sudo systemctl status budget-bot"
echo "    API status : sudo systemctl status budget-api"
echo "    Dashboard  : http://$(curl -s ifconfig.me)"
