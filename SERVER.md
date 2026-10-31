# Архиватор на сервере: установка, управление, удаление

Здесь собрана полная инструкция для VPS-сервера: бот-архиватор переписки для Telegram Business вместе с платным доступом через [Platesh](https://github.com/gytfel/Platesh) (оплата Telegram Stars и CryptoBot). Команды можно копировать целиком.

Всё ставится в две папки:

| Что | Папка | Служба |
|---|---|---|
| Архиватор (этот бот) | `/opt/archiver` | `busnes-tg-perepiski` |
| Platesh (приём оплат) | `/opt/platesh` | `platesh` |

Подробности про Platesh (цены, монеты, команды доступа) — в [его инструкции SERVER.md](https://github.com/gytfel/Platesh/blob/claude/beautiful-johnson-i6jquz/SERVER.md).

**Содержание**

1. [Что нужно](#1-что-нужно)
2. [Установка с нуля](#2-установка-с-нуля)
3. [Каждый день: статус, журнал, перезапуск](#3-каждый-день-статус-журнал-перезапуск)
4. [Цены и доступы](#4-цены-и-доступы)
5. [Настройки бота (.env)](#5-настройки-бота-env)
6. [Обновление](#6-обновление)
7. [Сделать бесплатным или снова платным](#7-сделать-бесплатным-или-снова-платным)
8. [Резервная копия и перенос](#8-резервная-копия-и-перенос)
9. [Удаление](#9-удаление)
10. [Если что-то не работает](#10-если-что-то-не-работает)

---

## 1. Что нужно

- **VPS** с Ubuntu 22.04/24.04 или Debian 12, сервер за границей (там Telegram не блокируется). Хватит 1 ядра и 1 ГБ памяти.
- **Доступ root.** Подключение из Windows: PowerShell → `ssh root@IP-АДРЕС`. Пароль при вводе не виден, это нормально.
- **Бот** от @BotFather. Его токен — это `BOT_TOKEN`.
- **Telegram Premium** у владельца: без него раздел Telegram Business недоступен.
- Для оплаты криптой: токен приложения CryptoBot (@CryptoBot → Crypto Pay → Create App).

> Не присылай никому скриншоты с токенами. Если токен засветился, замени его (Platesh SERVER.md, раздел 8).

## 2. Установка с нуля

Выполняй по шагам, каждый блок целиком.

**Шаг 1. Platesh** (приём оплат):

```bash
curl -fsSL https://raw.githubusercontent.com/gytfel/Platesh/refs/heads/claude/beautiful-johnson-i6jquz/install.sh | bash
```

Мастер задаст вопросы. Главное для архиватора:

- Токен бота — **тот же**, что будет у архиватора.
- «У бота есть свой код?» — **д**.
- «Путь к .py-файлу бота» — просто **Enter**: архиватор работает своей службой.
- Цены в Stars и в долларах, срок подписки в днях (`30`).
- Монеты для крипты — например `TON, USDT`.

**Шаг 2. Архиватор:**

```bash
apt-get update && apt-get install -y git
git clone -b claude/platesh-paywall https://github.com/gytfel/Busnes-tg-perepiski.git /opt/archiver
cd /opt/archiver && bash install.sh
```

`install.sh` поставит зависимости, спросит `BOT_TOKEN` (тот же токен) и `ARCHIVE_CHAT_ID` (Enter — пропустить). Потом создаст службу `busnes-tg-perepiski`, которая сама запускается после перезагрузки.

**Шаг 3. Подключить оплату:**

```bash
cd /opt/archiver && bash connect_platesh.sh
```

Скрипт найдёт бота в Platesh, запишет настройки `PLATESH_*` в `.env` и перезапустит бота. В конце должно быть **«✅ Готово: платный доступ включён»**. Если что-то не так, скрипт покажет блок «Проверка». Токенов в нём нет, его можно присылать скриншотом.

**Шаг 4. Подключить к Telegram Business.** В Telegram: Настройки → Telegram Business → Чат-боты → впиши username бота → доступ «Все чаты».

**Шаг 5. Проверить.** С другого аккаунта напиши боту `/start`. Должно прийти «🔒 Бот ограничен» с кнопкой подписки. Твой аккаунт (ID из мастера Platesh) пользуется ботом без оплаты.

## 3. Каждый день: статус, журнал, перезапуск

| Команда | Что делает |
|---|---|
| `systemctl status busnes-tg-perepiski` | Работает ли бот (зелёное `active (running)`, выход — `q`) |
| `journalctl -u busnes-tg-perepiski -f` | Журнал бота в реальном времени (выход — Ctrl+C) |
| `journalctl -u busnes-tg-perepiski -n 50 --no-pager` | Последние 50 строк журнала |
| `systemctl restart busnes-tg-perepiski` | Перезапустить (после правки `.env`) |
| `systemctl stop busnes-tg-perepiski` | Остановить |
| `systemctl start busnes-tg-perepiski` | Запустить |
| `systemctl restart platesh busnes-tg-perepiski` | Перезапустить оба |
| `systemctl status platesh` | Работает ли Platesh |
| `journalctl -u platesh -f` | Журнал Platesh (оплаты, ошибки CryptoBot) |

## 4. Цены и доступы

Цены, монеты и доступы хранятся в Platesh. Команды выполняются в папке `/opt/platesh`:

| Команда | Что делает |
|---|---|
| `./run.sh payments` | Последние оплаты: дата, ID, сумма, номер счёта |
| `./run.sh access ID` | Есть ли у пользователя подписка и до какого числа |
| `./run.sh grant ID 30` | Выдать или продлить подписку на 30 дней (без числа — на срок товара) |
| `./run.sh revoke ID` | Закрыть подписку |
| `./run.sh refund НОМЕР_СЧЁТА` | Вернуть Stars и закрыть подписку |
| `./run.sh check` | Проверить токены, CryptoBot и какие монеты он принимает |

Пример:

```bash
cd /opt/platesh && ./run.sh grant 123456789 30
```

Смена цены в Stars, цены в долларах и монет: [Platesh SERVER.md, раздел 5](https://github.com/gytfel/Platesh/blob/claude/beautiful-johnson-i6jquz/SERVER.md#5-цены-монеты-товары). Перезапускать нужно только Platesh: бот подхватит новые цены сам, в течение 5 минут.

## 5. Настройки бота (.env)

Открыть: `nano /opt/archiver/.env`. Сохранить: `Ctrl+O`, `Enter`. Выйти: `Ctrl+X`. Потом `systemctl restart busnes-tg-perepiski`.

| Строка | Что это |
|---|---|
| `BOT_TOKEN` | токен бота от @BotFather (тот же, что в Platesh) |
| `OWNER_ID` | твой Telegram ID: ты пользуешься ботом без оплаты. Необязательно |
| `ARCHIVE_CHAT_ID` | канал или группа, куда дублировать удалённые и изменённые сообщения. Необязательно |
| `DB_PATH` | где лежит база переписки (по умолчанию `/opt/archiver/messages.db`) |
| `NOTIFY_OWN_DELETIONS` | уведомлять о сообщениях, которые ты удалил сам (`true`/`false`) |
| `EXPORT_MEDIA_MB` | сколько МБ медиа класть в один экспорт (0–35, по умолчанию 25) |
| `PURGE_AFTER_EXPORT` | очищать базу после каждого экспорта (`true`/`false`) |
| `PAYSUPPORT_TEXT` | ответ на `/paysupport` (куда писать по вопросам оплаты) |
| `PLATESH_URL`, `PLATESH_KEY`, `PLATESH_BOT`, `PLATESH_ADMINS` | связь с Platesh. **Не правь руками**: их пишет `connect_platesh.sh` |
| `PLATESH_PRODUCTS` | какие товары Platesh открывают бота (по умолчанию — любой оплаченный) |

Посмотреть, какие строки есть, не показывая значения:

```bash
cut -d= -f1 /opt/archiver/.env
```

## 6. Обновление

**Архиватор:**

```bash
cd /opt/archiver && git pull && .venv/bin/pip install -q -r requirements.txt && systemctl restart busnes-tg-perepiski
```

**Platesh:**

```bash
cd /opt/platesh && ./run.sh update
```

Если Platesh ставился раньше 31.10.2026, первое обновление делается по-другому: команда в [Platesh SERVER.md, раздел 7](https://github.com/gytfel/Platesh/blob/claude/beautiful-johnson-i6jquz/SERVER.md#7-обновление).

## 7. Сделать бесплатным или снова платным

**Бесплатно для всех.** Команда убирает связь с Platesh. Platesh при этом продолжает работать, а оплаты и подписки в нём сохраняются:

```bash
sed -i '/^PLATESH_/d' /opt/archiver/.env && systemctl restart busnes-tg-perepiski
```

**Снова платно:**

```bash
cd /opt/archiver && bash connect_platesh.sh
```

## 8. Резервная копия и перенос

Что важно сохранить: переписку (`/opt/archiver/messages.db`), токен (`/opt/archiver/.env`) и всё из Platesh (кто оплатил и до какого числа).

**Копия обоих ботов одним файлом:**

```bash
cd /opt && tar czf /root/backup-$(date +%F).tgz --ignore-failed-read archiver/.env archiver/messages.db* platesh/config.yaml platesh/.env platesh/data
```

**Скачать её на компьютер.** Выполни в PowerShell на компьютере:

```bash
scp root@IP-АДРЕС:/root/backup-*.tgz .
```

**Перенос на другой сервер** (настройки, оплаты и переписка переезжают, код скачивается заново): [README Platesh, раздел «Перенос на другой сервер»](https://github.com/gytfel/Platesh/blob/claude/beautiful-johnson-i6jquz/README.md#перенос-на-другой-сервер).

## 9. Удаление

Сначала отключи бота в Telegram: Настройки → Telegram Business → Чат-боты → удалить бота.

**Удалить архиватор.** Первая строка сохраняет переписку и `.env` в `/root`:

```bash
cd /opt && tar czf /root/archiver-backup-$(date +%F).tgz --ignore-failed-read archiver/.env archiver/messages.db*
systemctl disable --now busnes-tg-perepiski
rm -f /etc/systemd/system/busnes-tg-perepiski.service && systemctl daemon-reload
rm -rf /opt/archiver
```

**Удалить и Platesh**, если он больше не нужен:

```bash
cd /opt && tar czf /root/platesh-backup-$(date +%F).tgz --ignore-failed-read platesh/config.yaml platesh/.env platesh/data
systemctl disable --now platesh
rm -f /etc/systemd/system/platesh.service && systemctl daemon-reload
rm -rf /opt/platesh
```

Копии останутся в `/root`. Если они не нужны: `rm /root/archiver-backup-*.tgz /root/platesh-backup-*.tgz`.

## 10. Если что-то не работает

Сначала посмотри журнал: `journalctl -u busnes-tg-perepiski -n 50 --no-pager`.

| Что видно | Что делать |
|---|---|
| Бот вообще не отвечает | Журнал бота. Если в нём `Conflict: terminated by other getUpdates request`, этот же бот запущен где-то ещё (на компьютере или старом сервере). Останови его там |
| `PLATESH_URL не задан — платный доступ выключен` | Оплата не подключена: `cd /opt/archiver && bash connect_platesh.sh` |
| `Платный доступ настроен не полностью` | То же: `cd /opt/archiver && bash connect_platesh.sh` |
| «Сервис оплаты временно недоступен» | Platesh не работает: `systemctl status platesh`, потом `systemctl restart platesh` |
| «Оплата в … сейчас недоступна» | CryptoBot не принимает эту монету: `cd /opt/platesh && ./run.sh check`, потом убери монету ([Platesh SERVER.md, раздел 5](https://github.com/gytfel/Platesh/blob/claude/beautiful-johnson-i6jquz/SERVER.md#5-цены-монеты-товары)) |
| Оплатил, а доступа нет | `cd /opt/platesh && ./run.sh payments ID` и `./run.sh access ID`. Если оплата есть, а доступа нет: `./run.sh grant ID` |
| Переписка не сохраняется | Бот подключён в Telegram Business? У владельца есть подписка, или его ID в `OWNER_ID`? |
| `No space left on device` | Место кончилось: `df -h /`. Освободить: `journalctl --vacuum-size=100M && apt-get clean`. Если растёт `messages.db`, сделай «🧹 Экспорт и очистка» в боте |
| Сервер тормозит, команды зависают | Мало памяти: `free -h`. Файл подкачки — [Platesh SERVER.md, раздел 11](https://github.com/gytfel/Platesh/blob/claude/beautiful-johnson-i6jquz/SERVER.md#11-если-что-то-не-работает) |
