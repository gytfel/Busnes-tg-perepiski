#!/usr/bin/env bash
#
# Установка бота Busnes-tg-perepiski на VPS (Debian/Ubuntu) как systemd-сервис.
# Запуск:  sudo bash install.sh
#
set -euo pipefail

SERVICE_NAME="busnes-tg-perepiski"
# Каталог проекта = каталог, где лежит этот скрипт.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/.env"
PY="$VENV_DIR/bin/python"

# Пользователь, от имени которого будет работать сервис.
RUN_USER="${SUDO_USER:-$(id -un)}"

say() { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
err() { printf '\n\033[1;31mОшибка:\033[0m %s\n' "$1" >&2; exit 1; }

# --- 0. Проверки ------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    err "Запустите через sudo:  sudo bash install.sh"
fi
command -v apt-get >/dev/null 2>&1 || err "Скрипт рассчитан на Debian/Ubuntu (apt)."

# --- 1. Системные пакеты ----------------------------------------------------
say "Устанавливаю системные пакеты (python3, venv, pip, git)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git >/dev/null

# --- 2. Виртуальное окружение и зависимости --------------------------------
say "Создаю виртуальное окружение и ставлю зависимости…"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r "$PROJECT_DIR/requirements.txt"

# --- 3. Файл .env -----------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
    say "Настройка .env"
    read -r -p "Введите BOT_TOKEN (от @BotFather): " BOT_TOKEN
    [ -n "$BOT_TOKEN" ] || err "BOT_TOKEN не может быть пустым."
    read -r -p "ARCHIVE_CHAT_ID (ID архив-канала, Enter чтобы пропустить): " ARCHIVE_CHAT_ID

    {
        echo "BOT_TOKEN=$BOT_TOKEN"
        echo "DB_PATH=$PROJECT_DIR/messages.db"
        echo "NOTIFY_OWN_DELETIONS=true"
        [ -n "$ARCHIVE_CHAT_ID" ] && echo "ARCHIVE_CHAT_ID=$ARCHIVE_CHAT_ID"
    } > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    chown "$RUN_USER":"$RUN_USER" "$ENV_FILE"
else
    say ".env уже существует — оставляю без изменений."
fi

# Права на каталог, чтобы сервис мог писать базу.
chown -R "$RUN_USER":"$RUN_USER" "$PROJECT_DIR"

# --- 4. systemd-сервис ------------------------------------------------------
say "Создаю systemd-сервис /etc/systemd/system/$SERVICE_NAME.service"
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<UNIT
[Unit]
Description=Busnes-tg-perepiski Telegram Business bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$PY -m app.bot
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

# --- 5. Запуск --------------------------------------------------------------
say "Запускаю сервис…"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
systemctl restart "$SERVICE_NAME"

sleep 2
systemctl --no-pager --lines=10 status "$SERVICE_NAME" || true

cat <<DONE

✅ Установлено. Полезные команды:
   Логи:         journalctl -u $SERVICE_NAME -f
   Статус:       systemctl status $SERVICE_NAME
   Перезапуск:   systemctl restart $SERVICE_NAME
   Остановить:   systemctl stop $SERVICE_NAME

Дальше: в Telegram подключите бота в
Settings → Telegram Business → Chatbots → выберите «Все чаты».
DONE
