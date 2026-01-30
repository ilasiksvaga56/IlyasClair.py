import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from mistralai import Mistral
from duckduckgo_search import DDGS
import requests
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# API ключи (через переменные окружения - безопасно!)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
OCR_SPACE_API_KEY = os.environ.get("OCR_SPACE_API_KEY", "")
DAILY_PHOTO_LIMIT = 30

# Проверка токенов
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не установлен!")
    exit(1)

# Инициализация Mistral
mistral = Mistral(api_key=MISTRAL_API_KEY) if MISTRAL_API_KEY else None

# Хранилище данных
user_chats = {}  # История чатов
user_photo_count = {}  # Счётчик фотографий

def get_system_prompt(user_name: str) -> str:
    """Формирует системный промпт для Mistral с запретом на звёздочки и выделения."""
    return f"""Ты — The Clair AI, дружелюбный помощник. Правила общения:
1. Отвечай кратко: 3-5 предложений максимум (если не просят подробно).
2. Будь живым и непринуждённым.
3. Соглашайся, когда человек прав, аккуратно поправляй, если нет.
4. Понимай юмор, используй эмодзи умеренно (1-2).
5. **Категорически запрещено использовать звёздочки (*), нижние подчёркивания (_), знаки выделения (`), жирный шрифт, курсив и любые другие символы для форматирования текста.**
6. Если вопрос про текущую дату, время, погоду, курсы — сразу ищи в интернете.
7. Не пиши "воду" — только полезная информация по делу.
8. Обращайся к пользователю по никнейму: {user_name}."""

def ensure_system_prompt(user_id: int, user_name: str):
    """Гарантирует наличие актуального системного промпта."""
    system_prompt = get_system_prompt(user_name)
    if user_id not in user_chats:
        user_chats[user_id] = [{"role": "system", "content": system_prompt}]
    else:
        if not user_chats[user_id] or user_chats[user_id][0].get("role") != "system":
            user_chats[user_id].insert(0, {"role": "system", "content": system_prompt})
        else:
            user_chats[user_id][0]["content"] = system_prompt

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start — только 3 кнопки: канал, разработчик, помощь."""
    user_id = update.effective_user.id
    user_name = update.effective_user.username or update.effective_user.first_name or "друг"

    keyboard = [
        [KeyboardButton("📢 Наш канал")],
        [KeyboardButton("📞 Связаться с разработчиком"), KeyboardButton("📖 Помощь")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    welcome_message = (
        f"Привет, {user_name}! 👋 Я The Clair AI — твой личный помощник.\n\n"
        "Что я умею:\n"
        "• Отвечаю на любые вопросы кратко и по делу\n"
        "• Ищу актуальную информацию в интернете\n"
        "• Распознаю текст с фотографий\n\n"
        "Просто напиши мне, и я помогу! 😊"
    )

    await update.message.reply_text(welcome_message, reply_markup=reply_markup)
    ensure_system_prompt(user_id, user_name)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help."""
    help_text = (
        "📖 Справка по The Clair AI\n\n"
        "Команды:\n"
        "/start — начать\n"
        "/help — эта справка\n"
        "/reset — очистить память\n\n"
        "Возможности:\n"
        "✅ Краткие и полезные ответы\n"
        "✅ Автопоиск актуальной информации\n"
        "✅ Распознавание текста с фото\n\n"
        "Наш канал: @TheClairAi"
    )
    await update.message.reply_text(help_text)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команда /reset."""
    user_id = update.effective_user.id
    user_name = update.effective_user.username or update.effective_user.first_name or "друг"
    user_chats[user_id] = []
    ensure_system_prompt(user_id, user_name)
    await update.message.reply_text(f"Память очищена, {user_name}! Начинаем заново 🧹")

async def channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Наш канал'."""
    await update.message.reply_text(
        "📢 Наш канал: @TheClairAi\n\n"
        "Там публикуются обновления и полезные советы. Подписывайся! 🚀"
    )

async def contact_dev_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Связаться с разработчиком'."""
    user_name = update.effective_user.username or update.effective_user.first_name or "друг"
    await update.message.reply_text(
        f"{user_name}, пиши разработчику: @ilasikSvaga56 📱\n"
        "Он ответит на все вопросы и примет предложения!"
    )

def needs_search(message: str) -> bool:
    """Определяет, нужен ли поиск в интернете."""
    triggers = [
        'сегодня', 'завтра', 'вчера', 'какое число', 'какой день', 'дата',
        'который час', 'время', 'сейчас', 'погода', 'температура', 'прогноз',
        'курс', 'доллар', 'евро', 'биткоин', 'новост', 'последн', 'свеж',
        'текущ', 'актуальн', 'найди', 'поищи', 'что такое', 'кто такой'
    ]
    return any(trigger in message.lower() for trigger in triggers)

async def search_web(query: str) -> str:
    """Поиск информации в интернете."""
    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=3):
                title = r.get('title', 'Без названия')
                body = r.get('body', 'Нет описания')
                href = r.get('href', '#')
                results.append(f"• {title}\n{body}\nИсточник: {href}\n")
        return "Результаты поиска:\n\n" + "\n".join(results) if results else "Ничего не нашёл по этому запросу 😔"
    except Exception as e:
        logger.error(f"Ошибка поиска: {e}")
        return "Ошибка поиска. Попробуй позже."

async def ocr_image(image_bytes: bytes) -> str:
    """Распознавание текста на изображении."""
    try:
        url = "https://api.ocr.space/parse/image"
        payload = {
            'apikey': OCR_SPACE_API_KEY,
            'language': 'rus',
            'isOverlayRequired': False,
            'detectOrientation': True,
            'scale': True,
            'OCREngine': 2
        }
        files = {'file': ('image.jpg', image_bytes, 'image/jpeg')}
        response = requests.post(url, data=payload, files=files, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if result.get('IsErroredOnProcessing', True):
                return "Ошибка распознавания текста."
            parsed_text = result.get('ParsedResults', [{}])[0].get('ParsedText', '').strip()
            return parsed_text if parsed_text else "На фото не найден текст."
        return "Ошибка сервиса распознавания."
    except Exception as e:
        logger.error(f"Ошибка OCR: {e}")
        return "Ошибка распознавания. Попробуй ещё раз."

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик фотографий."""
    user_id = update.effective_user.id
    user_name = update.effective_user.username or update.effective_user.first_name or "друг"
    today = datetime.now().strftime("%Y-%m-%d")

    if user_id not in user_photo_count or user_photo_count[user_id]["date"] != today:
        user_photo_count[user_id] = {"date": today, "count": 0}

    if user_photo_count[user_id]["count"] >= DAILY_PHOTO_LIMIT:
        await update.message.reply_text(
            f"{user_name}, ты исчерпал лимит фотографий на сегодня ({DAILY_PHOTO_LIMIT}).\n"
            "Попробуй завтра! ⏰"
        )
        return

    temp_msg = await update.message.reply_text(f"{user_name}, анализирую фото... 🔍")

    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        photo_bytes = await file.download_as_bytearray()
        text = await ocr_image(bytes(photo_bytes))

        if "Ошибка" not in text and "не найден" not in text.lower():
            user_photo_count[user_id]["count"] += 1
            analysis_prompt = (
                f"На фотографии распознан текст:\n\n{text}\n\n"
                "Кратко проанализируй его (3-5 предложений).\n"
                "Если это задача — реши, если текст — резюмируй, если код — объясни.\n"
                "В конце спроси: 'Нужна дополнительная помощь?'"
            )
            await temp_msg.edit_text("Распознал текст! Анализирую... 🤔")
            response = await chat_with_ai(user_id, analysis_prompt)
            await temp_msg.delete()
            await update.message.reply_text(response)
        else:
            await temp_msg.delete()
            await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        await temp_msg.delete()
        await update.message.reply_text(f"{user_name}, не смог обработать фото. Попробуй ещё раз.")

async def chat_with_ai(user_id: int, message: str) -> str:
    """Общение с Mistral AI."""
    try:
        if not mistral:
            return "Mistral API не настроен. Проверьте MISTRAL_API_KEY."
        
        user_name = "друг"
        ensure_system_prompt(user_id, user_name)

        if needs_search(message):
            search_result = await search_web(message)
            message = f"{message}\n\nИнформация из интернета:\n{search_result}"

        user_chats[user_id].append({"role": "user", "content": message})

        if len(user_chats[user_id]) > 31:
            user_chats[user_id] = [user_chats[user_id][0]] + user_chats[user_id][-30:]

        response = mistral.chat.complete(
            model="mistral-large-latest",
            messages=user_chats[user_id]
        )

        ai_response = response.choices[0].message.content.strip()
        user_chats[user_id].append({"role": "assistant", "content": ai_response})
        return ai_response
    except Exception as e:
        logger.error(f"Ошибка Mistral: {e}")
        return "Ошибка генерации ответа. Попробуй позже."

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений."""
    user_id = update.effective_user.id
    message = update.message.text.strip()
    user_name = update.effective_user.username or update.effective_user.first_name or "друг"

    if not message:
        return

    message_lower = message.lower()

    if any(phrase in message_lower for phrase in ['наш канал', 'твой канал', 'канал бота']):
        await channel_handler(update, context)
        return
    elif any(phrase in message_lower for phrase in ['связаться с разработчик', 'разработчик', 'поддержка']):
        await contact_dev_handler(update, context)
        return
    elif any(phrase in message_lower for phrase in ['помощь', 'справка', 'что умеешь']):
        await help_command(update, context)
        return
    elif any(phrase in message_lower for phrase in ['очистить память', 'сбросить память']):
        await reset_command(update, context)
        return

    temp_msg = await update.message.reply_text("Думаю над ответом... ⏳")

    try:
        await update.message.chat.send_action(action="typing")
        response = await chat_with_ai(user_id, message)
        await temp_msg.delete()

        if len(response) > 4000:
            for chunk in [response[i:i+4000] for i in range(0, len(response), 4000)]:
                await update.message.reply_text(chunk)
        else:
            await update.message.reply_text(response)
    except Exception as e:
        await temp_msg.delete()
        logger.error(f"Ошибка обработки сообщения: {e}")
        await update.message.reply_text(f"{user_name}, произошла ошибка. Попробуй позже.")

def main():
    """Запуск бота."""
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset_command))

    # Обработчики кнопок
    app.add_handler(MessageHandler(filters.Regex(r'^📢 Наш канал$'), channel_handler))
    app.add_handler(MessageHandler(filters.Regex(r'^📞 Связаться с разработчиком$'), contact_dev_handler))
    app.add_handler(MessageHandler(filters.Regex(r'^📖 Помощь$'), help_command))

    # Обработчики сообщений и фотографий
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Бот The Clair AI запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
