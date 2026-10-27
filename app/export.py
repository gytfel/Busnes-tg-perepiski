"""Экспорт переписки в самодостаточный HTML со встроенными медиа.

Медиа (фото, видео, голосовые, кружки, аудио, анимации, стикеры-картинки)
скачиваются из Telegram и вшиваются в HTML через data:URI (base64), поэтому
экспортный файл можно открыть в браузере и сразу смотреть/слушать вложения.

Устойчивость:
- HTML пишется потоково во временный файл на диске (а не собирается целиком в
  память) — чтобы не словить OOM на маленьком сервере.
- Бюджет считается по фактическому размеру ВЫХОДНОГО файла (с учётом base64 и
  текста), плюс жёсткий потолок MAX_FILE_BYTES < лимита отправки Telegram 50 МБ.
- Флуд-лимиты Telegram (429 retry_after) при скачивании повторяются, а не
  трактуются как потеря файла.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter

from app.utils import esc

logger = logging.getLogger(__name__)

# Жёсткий потолок размера готового файла (запас под лимит отправки ботом 50 МБ).
MAX_FILE_BYTES = 48 * 1024 * 1024
# Запас под футер/хвост.
RESERVE_BYTES = 256 * 1024
# Небольшая пауза между скачиваниями, чтобы реже упираться во флуд-лимит.
DOWNLOAD_PAUSE = 0.03
# Сколько раз повторять скачивание при флуд-лимите (429).
RETRY_ATTEMPTS = 5
# Размер чанка для потокового base64 (кратен 3, чтобы не было паддинга в середине).
CHUNK_BYTES = 48 * 1024

EXT_MIME: dict[str, str] = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif",
    "oga": "audio/ogg", "ogg": "audio/ogg", "opus": "audio/ogg",
    "mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav",
    "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
}

FALLBACK_MIME: dict[str, str] = {
    "photo": "image/jpeg", "voice": "audio/ogg", "audio": "audio/mpeg",
    "video": "video/mp4", "video_note": "video/mp4",
    "animation": "video/mp4", "sticker": "image/webp",
}

EMBEDDABLE = set(FALLBACK_MIME)


@dataclass(slots=True)
class ExportStats:
    total: int = 0            # сообщений с медиа
    embedded: int = 0         # встроено медиа
    skipped_size: int = 0     # не влезло в бюджет/потолок
    too_big: int = 0          # больше лимита getFile (~20 МБ)
    failed: int = 0           # иная ошибка скачивания
    media_bytes: int = 0      # сырой объём встроенных медиа
    file_bytes: int = 0       # итоговый размер HTML-файла
    truncated_msgs: int = 0   # сообщений не попало из-за потолка размера
    notes: list[str] = field(default_factory=list)


def _mime_for(file_path: str, media_type: str) -> str | None:
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    if ext == "tgs":  # анимационный стикер (lottie) — в браузере не играется
        return None
    if ext in EXT_MIME:
        return EXT_MIME[ext]
    return FALLBACK_MIME.get(media_type)


def _media_tags(mime: str, media_type: str) -> tuple[str, str]:
    """HTML-обёртка медиа как (открытие с началом data:URI, закрытие).

    Base64 пишется между ними потоково — чтобы не держать его копии в памяти.
    """
    head = f'data:{mime};base64,'
    if mime.startswith("image/"):
        return f'<img class="media" loading="lazy" src="{head}', '">'
    if mime.startswith("audio/"):
        return f'<audio class="media" controls preload="none" src="{head}', '"></audio>'
    if mime.startswith("video/"):
        cls = "media round" if media_type == "video_note" else "media"
        return f'<video class="{cls}" controls preload="none" src="{head}', '"></video>'
    return f'<a class="media dl" download href="{head}', '">⬇️ скачать вложение</a>'


async def _download(bot: Bot, file_id: str):
    """Скачивает файл по file_id с повторами при флуд-лимите (429).

    Возвращает (поток BytesIO, путь) — поток, чтобы кодировать base64 чанками
    и не копировать весь файл в память лишний раз.
    """
    await asyncio.sleep(DOWNLOAD_PAUSE)
    for attempt in range(RETRY_ATTEMPTS):
        try:
            tg_file = await bot.get_file(file_id)
            path = tg_file.file_path or ""
            buf = await bot.download_file(path)
            return buf, path
        except TelegramRetryAfter as exc:
            if attempt == RETRY_ATTEMPTS - 1:
                raise
            logger.info("Флуд-лимит, пауза %s c", exc.retry_after)
            await asyncio.sleep(exc.retry_after + 1)
    raise RuntimeError("unreachable")


async def build_export(
    bot: Bot, messages: list, media_budget_bytes: int
) -> tuple[str, ExportStats]:
    """Пишет HTML-экспорт во временный файл. Возвращает (путь, статистика).

    Вызывающий обязан удалить файл после отправки.
    """
    stats = ExportStats()
    generated = datetime.now(tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    ceiling = MAX_FILE_BYTES - RESERVE_BYTES

    fd, path = tempfile.mkstemp(suffix=".html", prefix="export_")
    total = 0
    current_chat: str | None = None

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:

            def write(chunk: str) -> int:
                nonlocal total
                fh.write(chunk)
                n = len(chunk.encode("utf-8"))
                total += n
                return n

            write(_head(generated, len(messages)))

            for idx, m in enumerate(messages):
                # Защита от переполнения даже на одном тексте.
                if total >= ceiling:
                    stats.truncated_msgs = len(messages) - idx
                    break

                chat_title = m.chat_title or "—"
                if chat_title != current_chat:
                    current_chat = chat_title
                    write(f"<h2>💬 {esc(chat_title)}</h2>")

                cls = "msg out" if m.outgoing else "msg"
                who = "Вы" if m.outgoing else (m.from_name or "собеседник")
                write(f"<div class='{cls}'>")
                write(f"<div class='meta'>{esc(who)} · {_fmt_ts(m.date)}</div>")
                fwd = getattr(m, "forward_from", None)
                if fwd:
                    write(f"<div class='fwd'>↪️ переслано от {esc(fwd)}</div>")
                if m.text:
                    write(esc(m.text).replace("\n", "<br>"))

                if m.media_type and m.file_id:
                    stats.total += 1
                    await _embed_one(
                        bot, m, media_budget_bytes, ceiling, total, stats, write
                    )

                if not m.text and not m.media_type:
                    write("<span class='empty'>(пустое сообщение)</span>")
                write("</div>")

            _collect_notes(stats)
            write(_footer(stats))
    except Exception:
        # Не оставляем недописанный файл на диске.
        try:
            os.remove(path)
        except OSError:
            pass
        raise

    stats.file_bytes = total
    return path, stats


async def _embed_one(
    bot: Bot, m, media_budget: int, ceiling: int, total: int,
    stats: ExportStats, write,
) -> None:
    """Пишет одно медиа через write(): встроенный плеер или подпись-заглушка.

    Base64 кодируется ЧАНКАМИ и пишется напрямую в файл — чтобы не держать в
    памяти ни полную копию файла, ни полную строку base64 (это и давало OOM).
    """
    att = lambda note="": write(  # noqa: E731
        f"<div class='att'>[вложение: {esc(m.media_type)}{note}]</div>")

    if m.media_type not in EMBEDDABLE:
        return att()
    if stats.media_bytes >= media_budget:
        stats.skipped_size += 1
        return att(" — не вошло по размеру")

    try:
        buf, file_path = await _download(bot, m.file_id)
    except Exception as exc:
        text = str(exc).lower()
        if "too big" in text or "file is too big" in text:
            stats.too_big += 1
            return att(" — слишком большое")
        logger.warning("Не удалось скачать %s: %s", m.media_type, exc)
        stats.failed += 1
        return att(" — ошибка скачивания")

    # Размер файла без копирования содержимого.
    buf.seek(0, 2)
    raw_len = buf.tell()
    buf.seek(0)

    if stats.media_bytes + raw_len > media_budget:
        stats.skipped_size += 1
        return att(" — не вошло по размеру")

    mime = _mime_for(file_path, m.media_type)
    if mime is None:
        return att()

    opening, closing = _media_tags(mime, m.media_type)
    # Точный размер тега: префикс + base64(raw_len) + суффикс.
    b64_len = (raw_len + 2) // 3 * 4
    projected = len(opening.encode("utf-8")) + b64_len + len(closing.encode("utf-8"))
    if total + projected > ceiling:
        stats.skipped_size += 1
        return att(" — не вошло по размеру")

    write(opening)
    while True:
        chunk = buf.read(CHUNK_BYTES)  # кратно 3 → чистый base64 без паддинга
        if not chunk:
            break
        write(base64.b64encode(chunk).decode("ascii"))
    write(closing)

    stats.media_bytes += raw_len
    stats.embedded += 1


def _collect_notes(stats: ExportStats) -> None:
    if stats.skipped_size:
        stats.notes.append(
            f"{stats.skipped_size} вложений не вошли по размеру (лимит экспорта)."
        )
    if stats.too_big:
        stats.notes.append(
            f"{stats.too_big} вложений больше ~20 МБ — Telegram не отдаёт их боту."
        )
    if stats.failed:
        stats.notes.append(f"{stats.failed} вложений не удалось скачать.")
    if stats.truncated_msgs:
        stats.notes.append(
            f"{stats.truncated_msgs} сообщений не попали в файл — упёрлись в потолок "
            "размера. Экспортируйте чаще или уменьшите EXPORT_MEDIA_MB."
        )


def _fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "—"


def _head(generated: str, count: int) -> str:
    parts = [
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Экспорт переписки</title><style>",
        "body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;",
        "background:#0e1621;color:#e6edf3;padding:16px;}",
        "h1{font-size:20px;} h2{font-size:16px;margin:24px 0 8px;color:#6ab7ff;",
        "border-bottom:1px solid #22303c;padding-bottom:4px;}",
        ".msg{padding:8px 12px;margin:6px 0;border-radius:10px;background:#17212b;",
        "max-width:680px;} .msg.out{background:#2b5278;margin-left:auto;}",
        ".meta{font-size:12px;color:#8a98a5;margin-bottom:4px;}",
        ".att{font-size:12px;color:#f0b232;margin-top:4px;}",
        ".fwd{font-size:12px;color:#6ab7ff;margin-bottom:4px;}",
        ".empty{color:#8a98a5;font-style:italic;}",
        ".media{display:block;margin-top:6px;max-width:320px;border-radius:10px;}",
        "audio.media{width:280px;} video.media{max-height:360px;}",
        ".media.round{width:220px;height:220px;border-radius:50%;object-fit:cover;}",
        ".media.dl{color:#6ab7ff;} .notes{color:#f0b232;font-size:13px;}",
        "</style></head><body>",
        f"<h1>Экспорт переписки</h1><p class='meta'>Сформировано: {generated}. "
        f"Сообщений: {count}.</p>",
    ]
    if count == 0:
        parts.append("<p class='empty'>Нет сохранённых сообщений.</p>")
    return "".join(parts)


def _footer(stats: ExportStats) -> str:
    notes_html = ""
    if stats.notes:
        items = "".join(f"<li>{esc(n)}</li>" for n in stats.notes)
        notes_html = f"<ul class='notes'>{items}</ul>"
    summary = (
        f"<p class='meta'>Встроено медиа: {stats.embedded} "
        f"({stats.media_bytes // (1024 * 1024)} МБ).</p>"
    )
    return summary + notes_html + "</body></html>"
