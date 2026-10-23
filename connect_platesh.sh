#!/usr/bin/env bash
#
# Подключает этого бота к Platesh (оплата Telegram Stars и CryptoBot), установленному
# на этом же сервере. Сам находит бота в настройках Platesh по токену, записывает
# PLATESH_* в .env (старые строки PLATESH_* заменяет) и перезапускает бота.
# Сами строки выдаёт Platesh: python -m platesh bot-env.
#
# Запуск (в папке бота):  sudo bash connect_platesh.sh
#
set -euo pipefail

SERVICE_NAME="busnes-tg-perepiski"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
PLATESH_DIR="${PLATESH_DIR:-/opt/platesh}"
PLATESH_INSTALL="curl -fsSL https://raw.githubusercontent.com/gytfel/Platesh/refs/heads/claude/beautiful-johnson-i6jquz/install.sh | bash"

say() { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
err() { printf '\n\033[1;31mОшибка:\033[0m %s\n' "$1" >&2; exit 1; }

[ -f "$ENV_FILE" ] || err "нет $ENV_FILE — сначала установи бота: sudo bash install.sh"
if [ ! -f "$PLATESH_DIR/config.yaml" ] || [ ! -x "$PLATESH_DIR/.venv/bin/python" ]; then
    err "Platesh не найден в $PLATESH_DIR. Сначала установи его:
    $PLATESH_INSTALL
На вопрос «У бота есть свой код?» ответь «д», путь к файлу бота не указывай.
Потом запусти этот скрипт ещё раз."
fi

BOT_TOKEN="$(grep -m1 '^BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2- | tr -d "\r\"' ")"
[ -n "$BOT_TOKEN" ] || err "в $ENV_FILE нет BOT_TOKEN"

say "Ищу этого бота в настройках Platesh…"
ERR_FILE="$(mktemp)"
trap 'rm -f "$ERR_FILE"' EXIT
if ! LINES="$(cd "$PLATESH_DIR" && PLATESH_BOT_TOKEN="$BOT_TOKEN" .venv/bin/python -m platesh bot-env -c config.yaml 2>"$ERR_FILE")"; then
    REASON="$(tail -n 5 "$ERR_FILE")"
    if [ -z "$REASON" ] || printf '%s' "$REASON" | grep -q "invalid choice"; then
        REASON="Platesh старой версии — обнови его той же командой установки:
    $PLATESH_INSTALL"
    fi
    err "$REASON"
fi
NAME="$(printf '%s\n' "$LINES" | sed -n 's/^PLATESH_BOT=//p')"
ADMINS="$(printf '%s\n' "$LINES" | sed -n 's/^PLATESH_ADMINS=//p')"
say "Нашёл: бот «$NAME» в Platesh, без оплаты пользуются: ${ADMINS:-никто}"

say "Записываю настройки в .env бота (старый сохранён как .env.bak)…"
OWNER="$(stat -c '%U:%G' "$ENV_FILE")"
cp -p "$ENV_FILE" "$ENV_FILE.bak"
sed -i '/^PLATESH_/d' "$ENV_FILE"
# Файл мог заканчиваться без перевода строки — тогда новая строка склеилась бы с последней.
if [ -s "$ENV_FILE" ] && [ -n "$(tail -c1 "$ENV_FILE")" ]; then echo >> "$ENV_FILE"; fi
printf '%s\n' "$LINES" >> "$ENV_FILE"
chmod 600 "$ENV_FILE"
chown "$OWNER" "$ENV_FILE"

if [ "${SKIP_RESTART:-}" = "1" ]; then
    say "Готово (бот не перезапускался)."
    exit 0
fi

systemctl is-active --quiet platesh \
    || err "служба Platesh не запущена. Запусти: systemctl start platesh   (журнал: journalctl -u platesh -n 30)"

# Служба должна запускать бота из этой папки и читать этот .env — иначе записанное до бота не дойдёт.
REINSTALL="cd $PROJECT_DIR && sudo bash install.sh && sudo bash connect_platesh.sh"
[ "$(systemctl show -p LoadState --value "$SERVICE_NAME" 2>/dev/null)" = "loaded" ] \
    || err "служба $SERVICE_NAME не установлена. Установи её:
    $REINSTALL"
UNIT_DIR="$(systemctl show -p WorkingDirectory --value "$SERVICE_NAME" 2>/dev/null || true)"
UNIT_ENV="$(systemctl show -p EnvironmentFiles --value "$SERVICE_NAME" 2>/dev/null | awk '{print $1}' || true)"
if [ "$(readlink -f "${UNIT_DIR:-/nonexistent}")" != "$(readlink -f "$PROJECT_DIR")" ] \
    || [ "$(readlink -f "${UNIT_ENV:-/nonexistent}")" != "$(readlink -f "$ENV_FILE")" ]; then
    err "служба $SERVICE_NAME запускает другую копию бота:
    папка ${UNIT_DIR:-не указана}, настройки ${UNIT_ENV:-не указаны}
а этот скрипт записал настройки в $ENV_FILE. Переустанови службу из этой папки одной командой:
    $REINSTALL"
fi

say "Перезапускаю бота (на слабом сервере это может занять пару минут)…"
SINCE="$(date '+%Y-%m-%d %H:%M:%S')"
systemctl daemon-reload
systemctl restart "$SERVICE_NAME"
# Ждём, пока бот загрузится и напишет в журнал, включилась ли оплата.
for _ in $(seq 1 60); do
    LOG="$(journalctl -u "$SERVICE_NAME" --since "$SINCE" --no-pager 2>/dev/null || true)"
    if printf '%s' "$LOG" | grep -q "Платный доступ через Platesh включён"; then
        say "✅ Готово: платный доступ включён."
        echo "   Проверь с другого аккаунта: напиши боту /start — должны появиться кнопки оплаты."
        echo "   Журнал бота:  journalctl -u $SERVICE_NAME -f"
        exit 0
    fi
    if printf '%s' "$LOG" | grep -qE "Платный доступ настроен не полностью|PLATESH_URL не задан|Traceback"; then
        break
    fi
    sleep 2
done
journalctl -u "$SERVICE_NAME" --since "$SINCE" -n 25 --no-pager || true

# Что на самом деле получил бот и как выглядит .env — без токенов и ключей, можно присылать скриншотом.
echo
echo "--- Проверка (токенов и ключей здесь нет) ---"
PID="$(systemctl show -p MainPID --value "$SERVICE_NAME" 2>/dev/null || echo 0)"
if [ "${PID:-0}" != "0" ] && [ -r "/proc/$PID/environ" ]; then
    if tr '\0' '\n' < "/proc/$PID/environ" | grep -q '^PLATESH_URL=.'; then
        echo "Бот получил PLATESH_URL из .env."
    else
        echo "Бот НЕ получил PLATESH_URL: служба не смогла прочитать эти строки из $ENV_FILE (см. пометки ниже)."
    fi
fi
echo "Строки $ENV_FILE (значения скрыты):"
awk -v sq="'" '
{
    line = $0; cr = ""
    if (sub(/\r$/, "", line)) cr = " [перевод строки Windows]"
    if (line ~ /^[ \t]*(#|$)/) next
    eq = index(line, "=")
    if (!eq) { printf "  %d: (нет «=») ← строка не читается%s\n", NR, cr; next }
    key = substr(line, 1, eq - 1); val = substr(line, eq + 1)
    shown = (val == "") ? "(пусто)" : "…"
    if (key ~ /^PLATESH_(URL|BOT|ADMINS|PRODUCTS)$/) shown = val
    note = ""
    if (key !~ /^[A-Za-z_][A-Za-z0-9_]*$/) note = note " ← неправильное имя"
    q = substr(val, 1, 1)
    if ((q == "\"" || q == sq) && index(substr(val, 2), q) == 0) note = note " ← кавычка не закрыта: строки ниже не прочитаются"
    if (val ~ /\\$/) note = note " ← \\ в конце: склеится со следующей строкой"
    printf "  %d: %s=%s%s%s\n", NR, key, shown, cr, note
}' "$ENV_FILE"
err "бот не подтвердил подключение к Platesh — пришли скриншот всего, что выше"
