"""Экранные клавиатуры бота (кнопки вместо команд)."""
from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Тексты кнопок главного меню (по ним же ловим нажатия).
BTN_STATUS = "📊 Статус"
BTN_SEARCH = "🔍 Поиск"
BTN_EXPORT = "📦 Экспорт"
BTN_EXPORT_CLEAR = "🧹 Экспорт и очистка"
BTN_HELP = "ℹ️ Помощь"
BTN_CANCEL = "❌ Отмена"


def main_menu() -> ReplyKeyboardMarkup:
    """Постоянная клавиатура снизу с основными действиями."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_SEARCH)],
            [KeyboardButton(text=BTN_EXPORT), KeyboardButton(text=BTN_EXPORT_CLEAR)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие…",
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    """Клавиатура во время ввода поискового запроса."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
        input_field_placeholder="Введите текст для поиска…",
    )
