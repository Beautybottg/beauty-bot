import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters
from telegram.constants import ParseMode

# ========== НАСТРОЙКИ ==========
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
raw_admins = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(id.strip()) for id in raw_admins.split(",") if id.strip()]

logging.basicConfig(level=logging.INFO)

# Состояния диалогов
(SELECT_SERVICE, SELECT_DATE, SELECT_TIME, ENTER_NAME, ENTER_PHONE, 
 ENTER_COMMENT, CONFIRMATION, ADMIN_EDIT_TIME, ADMIN_EDIT_COMMENT) = range(9)

# ========== РАБОТА С БАЗОЙ ДАННЫХ (PostgreSQL) ==========
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            service TEXT,
            date TEXT,
            time TEXT,
            name TEXT,
            phone TEXT,
            comment TEXT DEFAULT 'Нет',
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

def add_appointment(data: dict) -> int:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO appointments (user_id, service, date, time, name, phone, comment)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
    ''', (data['user_id'], data['service'], data['date'], data['time'], data['name'], data['phone'], data.get('comment', 'Нет')))
    app_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return app_id

def get_user_appointments(user_id: int):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM appointments WHERE user_id = %s ORDER BY date DESC, time DESC', (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_all_appointments():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM appointments ORDER BY created_at DESC LIMIT 20')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def update_app_field(app_id, field, value):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE appointments SET {field} = %s WHERE id = %s", (value, app_id))
    conn.commit()
    cur.close()
    conn.close()

# ========== ДАННЫЕ ==========
SERVICES = {
    "manicure": {"name": "💅 Маникюр", "price": "1500 руб"},
    "haircut": {"name": "💇 Стрижка", "price": "1200 руб"}
}
TIME_SLOTS = ["09:00", "12:00", "15:00", "18:00"]

# ========== ОБРАБОТЧИКИ КЛИЕНТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("📅 Записаться", callback_data="new_appointment")],
        [InlineKeyboardButton("📋 Мои записи", callback_data="my_appointments"), 
         InlineKeyboardButton("❌ Отмена", callback_data="list_cancel")],
        [InlineKeyboardButton("📞 Контакты", callback_data="contacts")]
    ]
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 Админ-панель", callback_data="admin_main")])
    
    text = f"Привет, {user.first_name}! Выберите действие:"
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message: await update.message.reply_text(text, reply_markup=reply_markup)
    else: await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    return ConversationHandler.END

async def contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "📍 **Наш адрес:** Москва, ул. Пушкина, д. 1\n📞 **Тел:** +7 (999) 123-45-67\n⏰ **Часы:** 10:00 - 20:00"
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def my_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    apps = get_user_appointments(update.effective_user.id)
    if not apps:
        await query.edit_message_text("У вас нет записей.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]))
        return
    text = "📋 **Ваши записи:**\n\n"
    for a in apps:
        status = "✅" if a['status'] == 'active' else "❌"
        text += f"{status} #{a['id']} - {a['service']}\n📅 {a['date']} в {a['time']}\n\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]), parse_mode=ParseMode.MARKDOWN)

# ========== АДМИН-ПАНЕЛЬ (УПРАВЛЕНИЕ) ==========
async def admin_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    apps = get_all_appointments()
    keyboard = []
    for a in apps:
        keyboard.append([InlineKeyboardButton(f"#{a['id']} {a['name']} - {a['date']}", callback_data=f"adm_manage_{a['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Выход", callback_data="back_to_menu")])
    await query.edit_message_text("👑 **Все записи (управление):**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def admin_manage_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    app_id = query.data.split("_")[-1]
    context.user_data['edit_id'] = app_id
    
    keyboard = [
        [InlineKeyboardButton("⏰ Изменить время", callback_data=f"adm_edit_time_{app_id}")],
        [InlineKeyboardButton("💬 Изменить коммент", callback_data=f"adm_edit_comm_{app_id}")],
        [InlineKeyboardButton("❌ Отменить запись", callback_data=f"adm_status_cancel_{app_id}")],
        [InlineKeyboardButton("🔙 Назад к списку", callback_data="admin_main")]
    ]
    await query.edit_message_text(f"Управление записью #{app_id}:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_edit_time_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("Введите новое время (например, 14:00):")
    return ADMIN_EDIT_TIME

async def admin_edit_time_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_time = update.message.text
    update_app_field(context.user_data['edit_id'], 'time', new_time)
    await update.message.reply_text(f"Время изменено на {new_time}!")
    return ConversationHandler.END

# ========== RENDER KEEP-ALIVE ==========
flask_app = Flask('')
@flask_app.route('/')
def home(): return "OK"
def run_flask(): flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

# ========== MAIN ==========
def main():
    init_db()
    Thread(target=run_flask, daemon=True).start()
    
    app = Application.builder().token(TOKEN).build()

    # Сюда нужно добавить ваш ConversationHandler записи (из прошлых сообщений)
    # И дополнительные обработчики:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, pattern="^back_to_menu$"))
    app.add_handler(CallbackQueryHandler(contacts, pattern="^contacts$"))
    app.add_handler(CallbackQueryHandler(my_appointments, pattern="^my_appointments$"))
    app.add_handler(CallbackQueryHandler(admin_main, pattern="^admin_main$"))
    app.add_handler(CallbackQueryHandler(admin_manage_app, pattern="^adm_manage_"))
    
    # Админский диалог редактирования
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_edit_time_start, pattern="^adm_edit_time_")],
        states={ADMIN_EDIT_TIME: [MessageHandler(filters.TEXT, admin_edit_time_save)]},
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(admin_conv)

    print("🤖 Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()