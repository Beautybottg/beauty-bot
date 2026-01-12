#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from threading import Thread

# Сторонние библиотеки
from flask import Flask
from dotenv import load_dotenv
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup, 
    KeyboardButton
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    ContextTypes,
    ConversationHandler,
    filters
)
from telegram.constants import ParseMode

# ========== НАСТРОЙКИ ==========
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
# Обработка ADMIN_IDS, чтобы не падало, если переменная пустая
raw_admins = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(id.strip()) for id in raw_admins.split(",") if id.strip()]

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния
SELECT_SERVICE, SELECT_DATE, SELECT_TIME, ENTER_NAME, ENTER_PHONE, ENTER_COMMENT, CONFIRMATION = range(7)
CANCEL_APPOINTMENT = 8

# ========== БАЗА ДАННЫХ ==========
DB_FILE = "appointments.json"

def load_appointments() -> Dict:
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"appointments": {}, "counters": {"next_id": 1}}

def save_appointments(data: Dict):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_appointment(appointment: Dict) -> int:
    data = load_appointments()
    appointment_id = data["counters"]["next_id"]
    appointment["created_at"] = datetime.now().isoformat()
    appointment["status"] = "active"
    data["appointments"][str(appointment_id)] = appointment
    data["counters"]["next_id"] += 1
    save_appointments(data)
    return appointment_id

def get_user_appointments(user_id: int) -> List[Tuple[int, Dict]]:
    data = load_appointments()
    user_appointments = []
    for app_id, appointment in data["appointments"].items():
        if str(user_id) == str(appointment.get("user_id")):
            user_appointments.append((int(app_id), appointment))
    user_appointments.sort(key=lambda x: x[1].get("date", ""))
    return user_appointments

def cancel_appointment(appointment_id: int, cancelled_by: str = "client") -> bool:
    data = load_appointments()
    if str(appointment_id) in data["appointments"]:
        appointment = data["appointments"][str(appointment_id)]
        appointment["status"] = "cancelled"
        appointment["cancelled_at"] = datetime.now().isoformat()
        appointment["cancelled_by"] = cancelled_by
        save_appointments(data)
        return True
    return False

def get_appointment(appointment_id: int) -> Optional[Dict]:
    data = load_appointments()
    return data["appointments"].get(str(appointment_id))

# ========== ДАННЫЕ УСЛУГ ==========
SERVICES = {
    "manicure": {"name": "💅 Маникюр", "price": "1500-2500 руб", "duration": "60-90 мин", "description": "Классический, аппаратный, покрытие гель-лаком"},
    "pedicure": {"name": "🦶 Педикюр", "price": "2000-3000 руб", "duration": "90-120 мин", "description": "Аппаратный, европейский, мужской"},
    "eyelash": {"name": "👁️ Наращивание ресниц", "price": "2500-4000 руб", "duration": "120-180 мин", "description": "Классика, 2D, 3D"},
    "brows": {"name": "✏️ Оформление бровей", "price": "800-1500 руб", "duration": "30-60 мин", "description": "Коррекция, ламинирование"},
    "facial": {"name": "🌸 Чистка лица", "price": "1800-3500 руб", "duration": "60-90 мин", "description": "Ультразвуковая, механическая"},
    "haircut": {"name": "💇 Стрижка", "price": "1200-2500 руб", "duration": "60 мин", "description": "Женская, мужская"},
    "makeup": {"name": "💄 Макияж", "price": "2000-4000 руб", "duration": "60-90 мин", "description": "Дневной, вечерний"}
}

TIME_SLOTS = ["09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00", "19:30"]

# ========== ХЕНДЛЕРЫ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = f"✨ *Добро пожаловать, {user.first_name}!* ✨\n\nВыберите действие:"
    keyboard = [
        [InlineKeyboardButton("📅 Записаться", callback_data="new_appointment")],
        [InlineKeyboardButton("📋 Мои записи", callback_data="my_appointments")],
        [InlineKeyboardButton("❌ Отменить запись", callback_data="cancel_appointment")],
        [InlineKeyboardButton("📞 Контакты", callback_data="contacts")]
    ]
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 Админ-панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

async def new_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    keyboard = []
    row = []
    for s_id, s in SERVICES.items():
        row.append(InlineKeyboardButton(s["name"], callback_data=f"service_{s_id}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])
    await query.edit_message_text("🎨 *Выберите услугу:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    return SELECT_SERVICE

async def select_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_id = query.data.replace("service_", "")
    context.user_data["service"] = SERVICES[service_id]
    context.user_data["service_id"] = service_id
    keyboard = []
    today = datetime.now()
    for i in range(7):
        date = today + timedelta(days=i)
        d_str = date.strftime("%d.%m.%Y")
        keyboard.append([InlineKeyboardButton(d_str, callback_data=f"date_{date.strftime('%Y-%m-%d')}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="new_appointment")])
    await query.edit_message_text("📅 *Выберите дату:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    return SELECT_DATE

async def select_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["date"] = query.data.replace("date_", "")
    keyboard = []
    row = []
    for t in TIME_SLOTS:
        row.append(InlineKeyboardButton(t, callback_data=f"time_{t}"))
        if len(row) == 4: keyboard.append(row); row = []
    if row: keyboard.append(row)
    await query.edit_message_text("⏰ *Выберите время:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    return SELECT_TIME

async def select_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["time"] = query.data.replace("time_", "")
    await query.edit_message_text("📝 *Введите ваше имя:*")
    return ENTER_NAME

async def enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    keyboard = [[KeyboardButton("📱 Поделиться контактом", request_contact=True)]]
    await update.message.reply_text("📞 *Введите номер телефона или нажмите кнопку:*", 
                                   reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
                                   parse_mode=ParseMode.MARKDOWN)
    return ENTER_PHONE

async def enter_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.contact.phone_number if update.message.contact else update.message.text
    context.user_data["phone"] = phone
    await update.message.reply_text("💬 *Комментарий (или /skip):*", parse_mode=ParseMode.MARKDOWN)
    return ENTER_COMMENT

async def enter_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    context.user_data["comment"] = "Нет" if text == "/skip" else text
    data = context.user_data
    conf_text = f"✅ *ПРОВЕРЬТЕ ДАННЫЕ:*\n\nУслуга: {data['service']['name']}\nДата: {data['date']}\nВремя: {data['time']}\nИмя: {data['name']}\nТелефон: {data['phone']}"
    keyboard = [[InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_appointment")],
                [InlineKeyboardButton("❌ Отменить", callback_data="cancel")]]
    await update.message.reply_text(conf_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    return CONFIRMATION

async def confirm_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data
    app_id = add_appointment({
        "user_id": update.effective_user.id,
        "service": data["service"]["name"],
        "date": data["date"],
        "time": data["time"],
        "name": data["name"],
        "phone": data["phone"]
    })
    await query.edit_message_text(f"🎉 *Запись #{app_id} создана!*")
    # Уведомление админам
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, f"🔔 Новая запись #{app_id}!")
        except: pass
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    msg = "Запись отменена."
    if update.message: await update.message.reply_text(msg)
    else: await update.callback_query.edit_message_text(msg)
    return ConversationHandler.END

# ========== RENDER KEEP-ALIVE (FLASK) ==========
flask_app = Flask('')

@flask_app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# ========== MAIN ==========
def main():
    if not TOKEN:
        print("Ошибка: TELEGRAM_TOKEN не найден!")
        return

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(new_appointment, pattern="^new_appointment$")],
        states={
            SELECT_SERVICE: [CallbackQueryHandler(select_service, pattern="^service_"), CallbackQueryHandler(start, pattern="^back_to_menu$")],
            SELECT_DATE: [CallbackQueryHandler(select_date, pattern="^date_"), CallbackQueryHandler(new_appointment, pattern="^new_appointment$")],
            SELECT_TIME: [CallbackQueryHandler(select_time, pattern="^time_")],
            ENTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name)],
            ENTER_PHONE: [MessageHandler(filters.TEXT | filters.CONTACT, enter_phone)],
            ENTER_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_comment), CommandHandler("skip", enter_comment)],
            CONFIRMATION: [CallbackQueryHandler(confirm_appointment, pattern="^confirm_appointment$"), CallbackQueryHandler(cancel_conversation, pattern="^cancel$")]
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation), CommandHandler("start", start)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(start, pattern="^back_to_menu$"))

    # Сначала запускаем Flask, затем бота
    keep_alive()
    print("🤖 Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()