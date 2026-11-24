#!/usr/bin/env bash
# Подготовка сервера-посредника (Ubuntu 22.04/24.04, без видеокарты).
# Запуск от root: bash edge-setup.sh pulse.example.ru "ssh-ed25519 AAAA... pulse-tunnel"
set -euo pipefail

DOMAIN="${1:?Укажите домен}"
TUNNEL_KEY="${2:?Укажите открытый ключ туннеля (~/.ssh/pulse_tunnel.pub на ноутбуке)}"
HERE="$(cd "$(dirname "$0")" && pwd)"

timedatectl set-timezone Europe/Moscow
apt-get update
apt-get install -y ufw curl gnupg
# В Ubuntu 24.04 Caddy есть в репозитории, для 22.04 подключаем официальный
if [ -z "$(apt-cache policy caddy | awk '/Candidate:/ {print $2}' | grep -v none)" ]; then
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
fi
apt-get install -y caddy

# Пользователь только для туннеля: без оболочки, может открыть лишь 127.0.0.1:8000
id tunnel >/dev/null 2>&1 || useradd -m -s /usr/sbin/nologin tunnel
install -d -m 700 -o tunnel -g tunnel /home/tunnel/.ssh
echo "restrict,port-forwarding,permitlisten=\"127.0.0.1:8000\",command=\"/bin/false\" $TUNNEL_KEY" \
  > /home/tunnel/.ssh/authorized_keys
chown tunnel:tunnel /home/tunnel/.ssh/authorized_keys
chmod 600 /home/tunnel/.ssh/authorized_keys

# Порт туннеля освобождается сразу после обрыва связи; пользователю tunnel —
# только обратный проброс, без доступа к портам сервера и без терминала
cat > /etc/ssh/sshd_config.d/pulse-tunnel.conf <<CONF
ClientAliveInterval 15
ClientAliveCountMax 3

Match User tunnel
    AllowTcpForwarding remote
    PermitOpen none
    PermitListen 127.0.0.1:8000
    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
    ForceCommand /bin/false
CONF
sshd -t
systemctl reload ssh 2>/dev/null || systemctl reload sshd

install -m 644 "$HERE/Caddyfile" /etc/caddy/Caddyfile
mkdir -p /etc/caddy/tls.d
mkdir -p /etc/systemd/system/caddy.service.d
printf '[Service]\nEnvironment=DOMAIN=%s\n' "$DOMAIN" > /etc/systemd/system/caddy.service.d/domain.conf
systemctl daemon-reload
systemctl enable caddy
systemctl restart caddy

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443
ufw --force enable

echo "Готово: https://$DOMAIN. Дальше на ноутбуке: make tunnel-install EDGE=<IP сервера>"
