#!/usr/bin/env bash
# Подготовка чистого сервера Ubuntu 22.04/24.04 с видеокартой NVIDIA.
# Запуск от root: bash server-setup.sh pulse.example.ru
set -euo pipefail

DOMAIN="${1:?Укажите домен: bash server-setup.sh pulse.example.ru}"
DIR=/opt/pulse

if ! command -v nvidia-smi >/dev/null || ! nvidia-smi >/dev/null; then
  echo "Драйвер NVIDIA не найден. Выберите у провайдера образ Ubuntu с драйверами NVIDIA." >&2
  exit 1
fi

timedatectl set-timezone Europe/Moscow
apt-get update
apt-get install -y ca-certificates curl gnupg make rsync ufw openssl

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

# Зеркало Docker Hub: из РФ прямой доступ бывает нестабильным
mkdir -p /etc/docker
if [ ! -s /etc/docker/daemon.json ]; then
  echo '{"registry-mirrors": ["https://mirror.gcr.io"]}' > /etc/docker/daemon.json
fi

if ! command -v nvidia-ctk >/dev/null; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update
  apt-get install -y nvidia-container-toolkit
fi
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443
ufw --force enable

mkdir -p "$DIR"
if [ ! -f "$DIR/.env" ]; then
  cat > "$DIR/.env" <<ENV
DOMAIN=$DOMAIN
APP_ENV=prod
SECRET_KEY=$(openssl rand -hex 32)
POSTGRES_PASSWORD=$(openssl rand -hex 16)
DEMO_MODE=true
DEMO_PASSWORD=pulse-$(openssl rand -hex 4)

OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:3b-instruct
LLM_ENABLED=true
ENV
  chmod 600 "$DIR/.env"
fi

# Каждую ночь в 4:00 по Москве — свежие демо-данные
echo "0 4 * * * root cd $DIR && make prod-demo >> /var/log/pulse-demo.log 2>&1" > /etc/cron.d/pulse-demo

echo "Сервер готов. Демо-пароль: $(grep ^DEMO_PASSWORD "$DIR/.env" | cut -d= -f2)"
echo "Дальше с ноутбука: make deploy HOST=root@<IP сервера>"
