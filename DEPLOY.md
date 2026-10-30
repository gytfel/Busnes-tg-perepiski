# Установка, управление и удаление на сервере

Полная инструкция по боту **Busnes-tg-perepiski** на VPS (Ubuntu 22.04/24.04
или Debian 12, с systemd). Имя сервиса: **`busnes-tg-perepiski`**.

> ⚠️ Бот работает только с аккаунтом, который сам его подключил, и обрабатывает
> вашу собственную переписку. Нужен **Telegram Premium** (без него раздел
> Telegram Business недоступен).

---

## 1. Подготовка: создать бота

1. Открой [@BotFather](https://t.me/BotFather) → `/newbot` → задай имя и username.
2. Скопируй **токен**.
3. Там же: **Bot Settings → Secretary Mode (Business Mode) → включить** —
   без этого Telegram не даст подключить бота к Business (ошибка «не поддерживает
   режим секретаря»).

## 2. Установка (в одну команду)

На свежем сервере по SSH:

```bash
# git (если нет) и клонирование
apt-get update && apt-get install -y git
git clone https://github.com/gytfel/Busnes-tg-perepiski.git
cd Busnes-tg-perepiski
git checkout claude/happy-heisenberg-9eptwv   # пока код в этой ветке

# установщик: поставит зависимости, спросит токен, настроит автозапуск
sudo bash install.sh
```

`install.sh` сам: ставит `python3/venv/pip/git`, создаёт окружение `.venv`,
ставит зависимости, спрашивает `BOT_TOKEN` (и по желанию `ARCHIVE_CHAT_ID`),
пишет `.env`, создаёт и запускает systemd-сервис с автозапуском.

## 3. Подключить в Telegram

**Settings → Telegram Business → Chatbots** → впиши username бота →
выбери **«Все личные чаты, кроме…»** (это «все чаты сразу»). Бот пришлёт
подтверждение в личку. Отправь боту **/start**, чтобы появились кнопки.

---

## 4. Управление с сервера (команды)

Все команды — от root (или через `sudo`). Имя сервиса — `busnes-tg-perepiski`.

| Задача | Команда |
|---|---|
| Статус | `systemctl status busnes-tg-perepiski` |
| Запустить | `systemctl start busnes-tg-perepiski` |
| Остановить | `systemctl stop busnes-tg-perepiski` |
| Перезапустить | `systemctl restart busnes-tg-perepiski` |
| Логи в реальном времени | `journalctl -u busnes-tg-perepiski -f` |
| Последние 100 строк логов | `journalctl -u busnes-tg-perepiski -n 100 --no-pager` |
| Автозапуск вкл/выкл | `systemctl enable/disable busnes-tg-perepiski` |
| Расход памяти/CPU | `systemctl status busnes-tg-perepiski` (строка `Memory:`) |

## 5. Обновление до новой версии

```bash
cd Busnes-tg-perepiski
git pull origin claude/happy-heisenberg-9eptwv
.venv/bin/pip install -q -r requirements.txt   # если менялись зависимости
systemctl restart busnes-tg-perepiski
```

## 6. Изменить настройки (`.env`)

```bash
cd Busnes-tg-perepiski
nano .env            # поправить значения
```

Большинство параметров применяются **на лету** (бот перечитывает `.env` раз в
~30 секунд) — перезапуск не нужен. Исключение: `BOT_TOKEN` и `DB_PATH` —
для них нужен `systemctl restart busnes-tg-perepiski`.

### Переменные `.env`

| Переменная | По умолч. | Что делает |
|---|---|---|
| `BOT_TOKEN` | — | Токен от @BotFather (обязательно; смена — только с рестартом) |
| `OWNER_ID` | авто | Явный ID владельца; обычно не нужен |
| `DB_PATH` | `messages.db` | Файл базы (смена — только с рестартом) |
| `NOTIFY_OWN_DELETIONS` | `true` | Уведомлять о своих же удалениях |
| `ARCHIVE_CHAT_ID` | — | Канал/группа-архив для дубля удалённых/изменённых |
| `EXPORT_MEDIA_MB` | `25` | Сколько МБ медиа встраивать в экспорт (0–35) |
| `PURGE_AFTER_EXPORT` | `false` | Чистить базу после каждого обычного экспорта |
| `AUTO_EXPORT_MB` | `0` | Авто-выгрузка при размере базы (МБ); 0 — выкл |
| `AUTO_EXPORT_CHECK_SEC` | `300` | Как часто проверять размер базы (сек, мин 30) |
| `BULK_DELETE_THRESHOLD` | `5` | Со скольких удалённых за раз это «вся переписка» |

## 7. Удаление

**В одну команду:**

```bash
cd Busnes-tg-perepiski
sudo bash uninstall.sh
```

Скрипт остановит и отключит сервис, удалит unit-файл и **спросит**, удалять ли
базу, `.env` и окружение. Код в каталоге остаётся — убрать полностью:
`rm -rf Busnes-tg-perepiski`.

**Вручную (то же самое):**

```bash
sudo systemctl stop busnes-tg-perepiski
sudo systemctl disable busnes-tg-perepiski
sudo rm /etc/systemd/system/busnes-tg-perepiski.service
sudo systemctl daemon-reload
# по желанию удалить данные:
rm -rf Busnes-tg-perepiski/.venv Busnes-tg-perepiski/*.db Busnes-tg-perepiski/.env
```

И в Telegram: **Settings → Telegram Business → Chatbots** → убрать бота, чтобы
он перестал ловить сообщения.

---

## 8. Кнопки/команды в самом боте

Управление из чата с ботом (кнопки снизу, команды — запасной вариант):

| Кнопка | Команда | Что делает |
|---|---|---|
| 📊 Статус | `/status` | Подключения и число сохранённых сообщений |
| 🔍 Поиск | `/search <текст>` | Поиск по сохранённой переписке |
| 📦 Экспорт | `/export` | HTML-файл со встроенными фото/видео/голосовыми |
| 🧹 Экспорт и очистка | `/export_clear` | Выгрузить и полностью стереть базу |
| ℹ️ Помощь | `/help` | Справка |

---

## 9. Если что-то не так

- **Бота убивает по памяти (`oom-kill` в логах) на слабом VPS** — снизь
  `EXPORT_MEDIA_MB` (например, до 10). Медиа в экспорте кодируется потоково,
  но очень большие вложения всё равно тяжелы.
- **Нет места на диске** — включи авто-выгрузку (`AUTO_EXPORT_MB`) или
  нажми «🧹 Экспорт и очистка».
- **Бот не отвечает после подключения** — проверь, что сервис `active (running)`
  (`systemctl status …`) и что в BotFather включён Secretary/Business Mode.
- **«не поддерживает режим секретаря»** — включи Secretary/Business Mode в
  @BotFather (Bot Settings).
- **Логи** всегда: `journalctl -u busnes-tg-perepiski -f`.
