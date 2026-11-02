#!/usr/bin/env bash
#
# Почему бот пускает без оплаты? Проверяет всё по порядку и называет причину.
# Токенов и ключей в выводе нет — его можно присылать скриншотом.
#
# Запуск (в папке бота):  bash check_paywall.sh ID_ДРУГОГО_АККАУНТА
#
set -uo pipefail

SERVICE_NAME="busnes-tg-perepiski"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
PLATESH_DIR="${PLATESH_DIR:-/opt/platesh}"
USER_ID="${1:-}"
PROBLEMS=0

ok()   { printf '  ✅ %s\n' "$1"; }
bad()  { printf '  ❌ %s\n' "$1"; PROBLEMS=$((PROBLEMS + 1)); }
info() { printf '  • %s\n' "$1"; }
env_value() { grep -m1 "^$1=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d "\r\"' "; }

if [ -n "$USER_ID" ] && ! [[ "$USER_ID" =~ ^[0-9]+$ ]]; then
    echo "ID — это число. Узнать ID аккаунта: напиши с него @userinfobot"; exit 1
fi

echo "1. Код бота ($PROJECT_DIR)"
info "версия: $(git -C "$PROJECT_DIR" log -1 --format='%h от %cd' --date=short 2>/dev/null || echo '?'), ветка $(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
if grep -q "install_paywall" "$PROJECT_DIR/app/bot.py" 2>/dev/null; then
    ok "в коде есть платный доступ"
else
    bad "в этом коде нет платного доступа: скачан вариант бота без оплаты. Нужна ветка claude/platesh-paywall"
fi

echo "2. Служба бота"
if [ "$(systemctl show -p LoadState --value "$SERVICE_NAME" 2>/dev/null)" != "loaded" ]; then
    bad "служба $SERVICE_NAME не установлена: cd $PROJECT_DIR && bash install.sh"
else
    UNIT_DIR="$(systemctl show -p WorkingDirectory --value "$SERVICE_NAME" 2>/dev/null)"
    if [ "$(readlink -f "${UNIT_DIR:-/nonexistent}")" = "$(readlink -f "$PROJECT_DIR")" ]; then
        ok "служба запускает бота из этой папки"
    else
        bad "служба запускает бота из другой папки: ${UNIT_DIR:-?}. Переустанови: cd $PROJECT_DIR && bash install.sh"
    fi
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "бот работает"
    else
        bad "бот не запущен: systemctl start $SERVICE_NAME"
    fi
    PID="$(systemctl show -p MainPID --value "$SERVICE_NAME" 2>/dev/null)"
    if [ "${PID:-0}" != "0" ] && [ -r "/proc/$PID/environ" ]; then
        if tr '\0' '\n' < "/proc/$PID/environ" | grep -q '^PLATESH_URL=.'; then
            ok "бот получил настройки Platesh"
        else
            bad "бот запущен без настроек Platesh — он бесплатный для всех: cd $PROJECT_DIR && bash connect_platesh.sh"
        fi
    fi

    SINCE="$(systemctl show -p ActiveEnterTimestamp --value "$SERVICE_NAME" 2>/dev/null)"
    LOG="$(journalctl -u "$SERVICE_NAME" --since "${SINCE:-1 hour ago}" --no-pager 2>/dev/null)"
    STATUS="$(printf '%s\n' "$LOG" | grep -E "Платный доступ|PLATESH_URL не задан" | tail -n 1)"
    case "$STATUS" in
        *"включён"*) ok "в журнале с последнего запуска: платный доступ включён" ;;
        "") info "в журнале с последнего запуска нет строки про платный доступ" ;;
        *) MSG="${STATUS##*| }"; bad "в журнале: ${MSG%.}. Исправь: cd $PROJECT_DIR && bash connect_platesh.sh" ;;
    esac
    CONFLICTS="$(journalctl -u "$SERVICE_NAME" --since "10 min ago" --no-pager 2>/dev/null | grep -c Conflict)"
    if [ "${CONFLICTS:-0}" -gt 0 ]; then
        bad "за 10 минут $CONFLICTS ошибок Conflict: этот же бот работает где-то ещё (старый сервер, компьютер). Там он может быть бесплатным. Останови его там или замени токен в @BotFather"
    else
        ok "другой копии бота нет (за 10 минут нет ошибок Conflict)"
    fi
fi

echo "3. Platesh"
if systemctl is-active --quiet platesh; then
    ok "Platesh работает"
else
    bad "Platesh не запущен: systemctl start platesh   (журнал: journalctl -u platesh -n 30)"
fi
ADMINS="$(env_value PLATESH_ADMINS)"
OWNER="$(env_value OWNER_ID)"
info "без оплаты пользуются: ${ADMINS:-никто}${OWNER:+ и владелец $OWNER (OWNER_ID)}"

if [ -n "$USER_ID" ]; then
    echo "4. Аккаунт $USER_ID"
    EXEMPT=0
    if [[ ",$ADMINS," == *",$USER_ID,"* ]]; then
        bad "$USER_ID записан как админ Platesh (PLATESH_ADMINS): ему оплата не нужна. Убери его из admins в $PLATESH_DIR/config.yaml и выполни: systemctl restart platesh && cd $PROJECT_DIR && bash connect_platesh.sh"
        EXEMPT=1
    fi
    if [ "$OWNER" = "$USER_ID" ]; then
        bad "$USER_ID записан как владелец (OWNER_ID в $ENV_FILE): ему оплата не нужна"
        EXEMPT=1
    fi
    if [ -x "$PLATESH_DIR/run.sh" ]; then
        ACCESS="$(cd "$PLATESH_DIR" && ./run.sh access "$USER_ID" 2>&1)"
        printf '%s\n' "$ACCESS" | sed 's/^/    /'
        if printf '%s\n' "$ACCESS" | grep -q "✅"; then
            info "у $USER_ID есть оплаченная подписка — поэтому бот его пускает, так и должно быть"
            info "чтобы проверить оплату заново: cd $PLATESH_DIR && ./run.sh revoke $USER_ID, подожди минуту и напиши /start"
        elif [ "$EXEMPT" = 0 ]; then
            ok "подписки нет: бот должен предложить оплату"
        fi
    fi
fi

echo
if [ "$PROBLEMS" = 0 ]; then
    echo "Ошибок не найдено."
    [ -n "$USER_ID" ] || echo "Чтобы проверить конкретный аккаунт: bash check_paywall.sh ID (ID — напиши с него @userinfobot)"
else
    echo "Найдено проблем: $PROBLEMS — исправь те, что с ❌ (сверху вниз)."
fi
