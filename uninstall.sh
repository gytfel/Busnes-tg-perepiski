#!/usr/bin/env bash
#
# Удаление бота Busnes-tg-perepiski с сервера (systemd).
# Запуск:  sudo bash uninstall.sh
#
set -euo pipefail

SERVICE_NAME="busnes-tg-perepiski"
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
err() { printf '\n\033[1;31mОшибка:\033[0m %s\n' "$1" >&2; exit 1; }

if [ "$(id -u)" -ne 0 ]; then
    err "Запустите через sudo:  sudo bash uninstall.sh"
fi

# --- 1. Остановить и отключить сервис ---------------------------------------
say "Останавливаю и отключаю сервис $SERVICE_NAME…"
systemctl stop "$SERVICE_NAME" 2>/dev/null || true
systemctl disable "$SERVICE_NAME" 2>/dev/null || true

# --- 2. Удалить unit-файл ---------------------------------------------------
if [ -f "$UNIT_FILE" ]; then
    rm -f "$UNIT_FILE"
    systemctl daemon-reload
    systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true
    say "Сервис удалён ($UNIT_FILE)."
else
    say "Unit-файл не найден — возможно, сервис уже удалён."
fi

# --- 3. Спросить про данные -------------------------------------------------
echo
read -r -p "Удалить также базу переписки, .env и окружение из $PROJECT_DIR? [y/N]: " ANS
if [[ "${ANS,,}" == "y" || "${ANS,,}" == "yes" || "${ANS,,}" == "да" ]]; then
    rm -rf "$PROJECT_DIR/.venv"
    rm -f "$PROJECT_DIR"/*.db "$PROJECT_DIR"/*.db-journal "$PROJECT_DIR"/*.sqlite* 2>/dev/null || true
    rm -f "$PROJECT_DIR/.env"
    say "Удалены: .venv, база (*.db), .env."
    echo "Каталог проекта оставлен (код). Полностью убрать: rm -rf \"$PROJECT_DIR\""
else
    say "Данные оставлены. Удалён только сервис автозапуска."
    echo "Файлы на месте в $PROJECT_DIR (код, .env, база)."
fi

cat <<DONE

✅ Готово. Бот больше не запускается автоматически.

Проверить, что сервиса нет:
   systemctl status $SERVICE_NAME   (должно быть: could not be found / not found)

Отдельно: отключить бота в Telegram (чтобы перестал ловить сообщения) —
Settings → Telegram Business → Chatbots → убрать бота.
DONE
