"""Экспорт переписки в самодостаточный HTML со встроенными медиа.

Медиа (фото, видео, голосовые, кружки, аудио, анимации, стикеры-картинки)
скачиваются из Telegram и вшиваются в HTML через data:URI (base64), поэтому
экспортный файл можно открыть в браузере и сразу смотреть/слушать вложения —
без интернета и без Telegram.

Ограничения:
- Облачный Bot API не отдаёт файлы больше ~20 МБ (getFile) — такие вложения
  останутся подписью.
- На один экспорт есть суммарный лимит встраиваемых медиа (budget), чтобы
  итоговый файл влез в лимит отправки Telegram (≤50 МБ) и память сервера.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from aiogram import Bot

from app.utils import esc

logger = logging.getLogger(__name__)

# Расширение файла (из Telegram file_path) -> MIME.
EXT_MIME: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "oga": "audio/ogg",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "wav": "audio/wav",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
}

# Запасной MIME по типу медиа, если расширение неизвестно.
FALLBACK_MIME: dict[str, str] = {
    "photo": "image/jpeg",
    "voice": "audio/ogg",
    "audio": "audio/mpeg",
    "video": "video/mp4",
    "video_note": "video/mp4",
    "animation": "video/mp4",
    "sticker": "image/webp",
}

# Типы, которые имеет смысл скачивать и встраивать.
EMBEDDABLE = set(FALLBACK_MIME)


@dataclass(slots=True)
class ExportStats:
    total: int = 0
    embedded: int = 0
    skipped_size: int = 0  # не влезло в бюджет
    too_big: int = 0       # больше лимита getFile (~20 МБ)
    failed: int = 0        # иная ошибка скачивания
    bytes_used: int = 0
    notes: list[str] = field(default_factory=list)


def _mime_for(file_path: str, media_type: str) -> str | None:
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    if ext == "tgs":  # анимационный стикер (lottie) — в браузере не играется
        return None
    if ext in EXT_MIME:
        return EXT_MIME[ext]
    return FALLBACK_MIME.get(media_type)


def _render_media(mime: str, b64: str, media_type: str) -> str:
    src = f"data:{mime};base64,{b64}"
    if mime.startswith("image/"):
        return f'<img class="media" loading="lazy" src="{src}">'
    if mime.startswith("audio/"):
        return f'<audio class="media" controls preload="none" src="{src}"></audio>'
    if mime.startswith("video/"):
        cls = "media round" if media_type == "video_note" else "media"
        return f'<video class="{cls}" controls preload="none" src="{src}"></video>'
    return f'<a class="media dl" download href="{src}">⬇️ скачать вложение</a>'


async def _download(bot: Bot, file_id: str) -> tuple[bytes, str]:
    """Скачивает файл по file_id. Возвращает (bytes, file_path)."""
    tg_file = await bot.get_file(file_id)
    path = tg_file.file_path or ""
    buf = await bot.download_file(path)
    data = buf.read() if hasattr(buf, "read") else bytes(buf)
    return data, path


async def build_export(
    bot: Bot, messages: list, budget_bytes: int
) -> tuple[str, ExportStats]:
    """Собирает HTML-экспорт со встроенными медиа. Возвращает (html, stats)."""
    stats = ExportStats()
    generated = datetime.now(tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

    body: list[str] = []
    current_chat: str | None = None

    for m in messages:
        chat_title = m.chat_title or "—"
        if chat_title != current_chat:
            current_chat = chat_title
            body.append(f"<h2>💬 {esc(chat_title)}</h2>")

        cls = "msg out" if m.outgoing else "msg"
        who = "Вы" if m.outgoing else (m.from_name or "собеседник")
        body.append(f"<div class='{cls}'>")
        body.append(f"<div class='meta'>{esc(who)} · {_fmt_ts(m.date)}</div>")
        if m.text:
            body.append(esc(m.text).replace("\n", "<br>"))

        if m.media_type and m.file_id:
            stats.total += 1
            rendered = await _embed_one(bot, m, budget_bytes, stats)
            body.append(rendered)

        if not m.text and not m.media_type:
            body.append("<span class='empty'>(пустое сообщение)</span>")
        body.append("</div>")

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

    return _wrap_html(body, generated, len(messages), stats), stats


async def _embed_one(bot: Bot, m, budget_bytes: int, stats: ExportStats) -> str:
    """Возвращает HTML для одного медиа: встроенный плеер или подпись-заглушка."""
    placeholder = f"<div class='att'>[вложение: {esc(m.media_type)}]</div>"

    if m.media_type not in EMBEDDABLE:
        return placeholder
    if stats.bytes_used >= budget_bytes:
        stats.skipped_size += 1
        return f"<div class='att'>[вложение: {esc(m.media_type)} — не вошло по размеру]</div>"

    try:
        data, path = await _download(bot, m.file_id)
    except Exception as exc:  # файл слишком большой или иная ошибка
        text = str(exc).lower()
        if "too big" in text or "file is too big" in text:
            stats.too_big += 1
            return f"<div class='att'>[вложение: {esc(m.media_type)} — слишком большое]</div>"
        logger.warning("Не удалось скачать %s: %s", m.media_type, exc)
        stats.failed += 1
        return f"<div class='att'>[вложение: {esc(m.media_type)} — ошибка скачивания]</div>"

    if stats.bytes_used + len(data) > budget_bytes:
        stats.skipped_size += 1
        return f"<div class='att'>[вложение: {esc(m.media_type)} — не вошло по размеру]</div>"

    mime = _mime_for(path, m.media_type)
    if mime is None:
        return placeholder

    b64 = base64.b64encode(data).decode("ascii")
    stats.bytes_used += len(data)
    stats.embedded += 1
    return _render_media(mime, b64, m.media_type)


def _fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "—"


def _wrap_html(body: list[str], generated: str, count: int, stats: ExportStats) -> str:
    notes_html = ""
    if stats.notes:
        items = "".join(f"<li>{esc(n)}</li>" for n in stats.notes)
        notes_html = f"<ul class='notes'>{items}</ul>"

    head = [
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
        ".empty{color:#8a98a5;font-style:italic;}",
        ".media{display:block;margin-top:6px;max-width:320px;border-radius:10px;}",
        "audio.media{width:280px;} video.media{max-height:360px;}",
        ".media.round{width:220px;height:220px;border-radius:50%;object-fit:cover;}",
        ".media.dl{color:#6ab7ff;} .notes{color:#f0b232;font-size:13px;}",
        "</style></head><body>",
        f"<h1>Экспорт переписки</h1><p class='meta'>Сформировано: {generated}. "
        f"Сообщений: {count}. Встроено медиа: {stats.embedded} "
        f"({stats.bytes_used // (1024*1024)} МБ).</p>",
        notes_html,
    ]
    if count == 0:
        head.append("<p class='empty'>Нет сохранённых сообщений.</p>")
    return "".join(head) + "".join(body) + "</body></html>"
