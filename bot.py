import logging
import datetime
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
CHOOSING_ACTION, ADDING_MEDICATION, SETTING_TIME, SETTING_DURATION, CONFIRM_DELETE = range(5)

# Путь к файлу с данными
DATA_FILE = "medications_data.json"

# Функция для загрузки данных
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                return {}
    return {}

# Функция для сохранения данных
def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=4)

# Начальная команда
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    
    # Инициализация данных пользователя, если их нет
    if user_id not in data:
        data[user_id] = {
            "medications": {},
            "progress": {}
        }
        save_data(data)
    
    # Создание клавиатуры с основными опциями
    keyboard = [
        ["Добавить лекарство"],
        ["Посмотреть прогресс"],
        ["Посмотреть список лекарств"],
        ["Очистить список лекарств"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "Привет! Я бот для напоминаний о приёме лекарств. Выберите действие:",
        reply_markup=reply_markup
    )
    
    return CHOOSING_ACTION

# Обработка выбора действия
async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    
    if choice == "Добавить лекарство":
        await update.message.reply_text("Введите название лекарства:")
        return ADDING_MEDICATION
    
    elif choice == "Посмотреть прогресс":
        await show_progress(update, context)
        return CHOOSING_ACTION
    
    elif choice == "Посмотреть список лекарств":
        await show_medications(update, context)
        return CHOOSING_ACTION
    
    elif choice == "Очистить список лекарств":
        await update.message.reply_text(
            "Вы уверены, что хотите очистить список лекарств? "
            "Для подтверждения отправьте текст 'Удалить лекарства'"
        )
        return CONFIRM_DELETE
    
    else:
        await update.message.reply_text("Пожалуйста, выберите действие из списка.")
        return CHOOSING_ACTION

# Обработка ввода названия лекарства
async def add_medication(update: Update, context: ContextTypes.DEFAULT_TYPE):
    medication_name = update.message.text
    context.user_data["current_medication"] = medication_name
    
    await update.message.reply_text(
        f"Лекарство '{medication_name}' будет добавлено. "
        "Теперь укажите время приёма в формате ЧЧ:ММ (например, 08:30):"
    )
    
    return SETTING_TIME

# Обработка ввода времени
async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_str = update.message.text
    
    # Проверка формата времени
    try:
        time_obj = datetime.datetime.strptime(time_str, "%H:%M").time()
        context.user_data["medication_time"] = time_str
        
        await update.message.reply_text(
            f"Время приёма установлено на {time_str}. "
            "Теперь укажите продолжительность курса в днях (введите число):"
        )
        
        return SETTING_DURATION
    
    except ValueError:
        await update.message.reply_text(
            "Неверный формат времени. Пожалуйста, введите время в формате ЧЧ:ММ (например, 08:30):"
        )
        return SETTING_TIME

# Обработка ввода продолжительности курса
async def set_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        duration = int(update.message.text)
        if duration <= 0:
            await update.message.reply_text("Продолжительность должна быть положительным числом. Попробуйте снова:")
            return SETTING_DURATION
            
        # Получаем сохраненные данные о лекарстве
        medication_name = context.user_data["current_medication"]
        medication_time = context.user_data["medication_time"]
        
        # Загружаем данные пользователя
        user_id = str(update.effective_user.id)
        data = load_data()
        
        # Добавляем новое лекарство
        start_date = datetime.datetime.now().strftime("%Y-%m-%d")
        data[user_id]["medications"][medication_name] = {
            "time": medication_time,
            "duration": duration,
            "start_date": start_date
        }
        
        # Инициализируем прогресс
        if medication_name not in data[user_id]["progress"]:
            data[user_id]["progress"][medication_name] = {
                "taken": 0,
                "skipped": 0
            }
        
        save_data(data)
        
        # Очищаем данные текущего лекарства
        context.user_data.clear()
        
        await update.message.reply_text(
            f"Лекарство '{medication_name}' успешно добавлено!\n"
            f"Время приёма: {medication_time}\n"
            f"Продолжительность курса: {duration} дней\n"
            f"Вы будете получать напоминания в указанное время."
        )
        
        # Обновляем расписание напоминаний
        update_reminders(context.application)
        
        return CHOOSING_ACTION
        
    except ValueError:
        await update.message.reply_text(
            "Неверный формат. Пожалуйста, введите число дней курса:"
        )
        return SETTING_DURATION

# Функция для отображения прогресса
async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    
    if user_id not in data or not data[user_id]["progress"]:
        await update.message.reply_text("У вас пока нет данных о прогрессе приёма лекарств.")
        return
    
    progress_text = "Ваш прогресс по приёму лекарств:\n\n"
    
    for med_name, progress in data[user_id]["progress"].items():
        if med_name in data[user_id]["medications"]:
            duration = data[user_id]["medications"][med_name]["duration"]
            taken = progress["taken"]
            skipped = progress["skipped"]
            #total = taken + skipped
            percent = (taken / duration * 100) if duration > 0 else 0
            
            progress_text += f"*{med_name}*\n"
            progress_text += f"✅ Принято: {taken}/{duration} ({percent:.1f}%)\n"
            progress_text += f"❌ Пропущено: {skipped}\n\n"
    
    await update.message.reply_text(progress_text, parse_mode="Markdown")

# Функция для отображения списка лекарств
async def show_medications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    
    if user_id not in data or not data[user_id]["medications"]:
        await update.message.reply_text("У вас пока нет добавленных лекарств.")
        return
    
    meds_text = "Ваш список лекарств:\n\n"
    
    for med_name, med_info in data[user_id]["medications"].items():
        start_date = datetime.datetime.strptime(med_info["start_date"], "%Y-%m-%d")
        end_date = start_date + datetime.timedelta(days=med_info["duration"])
        days_left = (end_date - datetime.datetime.now()).days + 1
        
        meds_text += f"*{med_name}*\n"
        meds_text += f"⏰ Время приёма: {med_info['time']}\n"
        meds_text += f"📅 Начало курса: {med_info['start_date']}\n"
        meds_text += f"🗓 Окончание курса: {end_date.strftime('%Y-%m-%d')}\n"
        meds_text += f"⏳ Осталось дней: {max(0, days_left)}\n\n"
    
    await update.message.reply_text(meds_text, parse_mode="Markdown")

# Обработка подтверждения удаления списка лекарств
async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    confirmation_text = update.message.text
    
    if confirmation_text == "Удалить лекарства":
        user_id = str(update.effective_user.id)
        data = load_data()
        
        if user_id in data:
            data[user_id]["medications"] = {}
            data[user_id]["progress"] = {}
            save_data(data)
        
        await update.message.reply_text("Список лекарств успешно очищен.")
    else:
        await update.message.reply_text("Операция отменена.")
    
    return CHOOSING_ACTION

# Функция для отправки напоминаний
async def send_reminder(context: ContextTypes.DEFAULT_TYPE, user_id=None, med_name=None):
    # Если функция вызвана из job_queue
    if hasattr(context, 'job') and context.job:
        job = context.job
        user_id, med_name = job.data
    
    # Проверяем, что лекарство все еще активно
    data = load_data()
    if user_id not in data or med_name not in data[user_id]["medications"]:
        return
        
    # Проверяем не закончился ли курс
    med_info = data[user_id]["medications"][med_name]
    start_date = datetime.datetime.strptime(med_info["start_date"], "%Y-%m-%d")
    end_date = start_date + datetime.timedelta(days=med_info["duration"])
    
    if datetime.datetime.now() > end_date:
        return
    
    # Создаем inline кнопки для ответа
    keyboard = [
        [
            InlineKeyboardButton("✅ Принял", callback_data=f"taken_{med_name}"),
            InlineKeyboardButton("❌ Пропустил", callback_data=f"skipped_{med_name}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=user_id,
        text=f"⏰ Пора принять лекарство: *{med_name}*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Обработка нажатий на inline кнопки
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action, med_name = query.data.split("_", 1)
    user_id = str(query.from_user.id)
    data = load_data()
    
    if user_id in data and med_name in data[user_id]["progress"]:
        if action == "taken":
            data[user_id]["progress"][med_name]["taken"] += 1
            response_text = f"✅ Отлично! Отмечено, что вы приняли {med_name}."
        else:  # skipped
            data[user_id]["progress"][med_name]["skipped"] += 1
            response_text = f"❌ Отмечено, что вы пропустили прием {med_name}."
        
        save_data(data)
        await query.edit_message_text(text=response_text)
    else:
        await query.edit_message_text(text="Произошла ошибка при обновлении прогресса.")

# Функция для запуска периодических задач напоминаний
def schedule_reminders(application):
    data = load_data()
    now = datetime.datetime.now()
    
    for user_id, user_data in data.items():
        for med_name, med_info in user_data["medications"].items():
            # Разбираем время приема
            hour, minute = map(int, med_info["time"].split(":"))
            
            # Вычисляем следующее время напоминания
            reminder_time = datetime.datetime.now().replace(hour=hour, minute=minute, second=0)
            if reminder_time < now:
                reminder_time = reminder_time + datetime.timedelta(days=1)
            
            # Проверяем, не закончился ли курс
            start_date = datetime.datetime.strptime(med_info["start_date"], "%Y-%m-%d")
            end_date = start_date + datetime.timedelta(days=med_info["duration"])
            
            if now <= end_date:
                # Планируем задачу напоминания
                # Сначала удаляем существующую задачу, если она есть
                job_name = f"reminder_{user_id}_{med_name}"
                current_jobs = application.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
                
                # Теперь планируем новую задачу
                first_time = (reminder_time - now).total_seconds()
                application.job_queue.run_repeating(
                    send_reminder,
                    interval=86400,  # 24 часа в секундах
                    first=first_time,
                    data=(user_id, med_name),
                    name=job_name
                )

def cancel_all_reminders(application):
    """Отменяет все задачи напоминаний."""
    jobs = application.job_queue.jobs()
    for job in jobs:
        if job.name and job.name.startswith("reminder_"):
            job.schedule_removal()

def update_reminders(application):
    """Обновляет все задачи напоминаний."""
    cancel_all_reminders(application)
    schedule_reminders(application)

# Функция для проверки и отправки напоминаний
async def check_and_send_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет все лекарства и отправляет напоминания, если наступило время"""
    data = load_data()
    now = datetime.datetime.now()
    current_time = now.strftime("%H:%M")
    
    for user_id, user_data in data.items():
        for med_name, med_info in user_data["medications"].items():
            # Если текущее время совпадает с временем приема (с точностью до минуты)
            if med_info["time"] == current_time:
                # Проверяем, не закончился ли курс
                start_date = datetime.datetime.strptime(med_info["start_date"], "%Y-%m-%d")
                end_date = start_date + datetime.timedelta(days=med_info["duration"])
                
                if now <= end_date:
                    # Отправляем напоминание
                    await send_reminder(context, user_id=user_id, med_name=med_name)
                    logger.info(f"Отправлено напоминание пользователю {user_id} о приеме {med_name}")

# Основная функция
def main():
    # Токен вашего бота (получите его у @BotFather в Telegram)
    TOKEN = "8098518856:AAEf4Y1vZLoQq8S_hW2Gd1OxscIVf2TxXgw"
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчик разговора
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_choice)],
            ADDING_MEDICATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_medication)],
            SETTING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_time)],
            SETTING_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_duration)],
            CONFIRM_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    
    application.add_handler(conv_handler)
    
    # Добавляем обработчик inline кнопок
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Запланировать периодическую проверку времени для отправки напоминаний
    # Проверка каждую минуту
    application.job_queue.run_repeating(
        check_and_send_reminders, 
        interval=60,  # Каждую минуту (60 секунд)
        first=1  # Начать через 1 секунду после запуска
    )
    
    # Также запускаем стандартный планировщик напоминаний для резервной стратегии
    application.job_queue.run_once(
        lambda context: schedule_reminders(application),
        when=5  # Запустить через 5 секунд после старта бота
    )
    
    logger.info("Бот запущен и готов к работе!")
    
    # Запускаем бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()