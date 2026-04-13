import os
import logging
import sqlite3
import io
from typing import List, Tuple

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
import qrcode
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# ================= CONFIGURATION =================
# Load environment variables from .env file
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
WATERMARK_TEXT = os.getenv('WATERMARK_TEXT', '@qrbegi_bot')
DB_NAME = 'bot_data.db'

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("CRITICAL ERROR: BOT_TOKEN or ADMIN_ID is missing in the .env file!")

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

# ================= DATABASE HANDLING =================
def execute_query(query: str, params: tuple = (), fetch_one=False, fetch_all=False):
    """Helper function to execute database queries safely."""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            if fetch_one:
                return cursor.fetchone()
            if fetch_all:
                return cursor.fetchall()
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return None

def init_db():
    """Initialize database tables."""
    execute_query('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)')
    execute_query('CREATE TABLE IF NOT EXISTS channels (channel_id TEXT PRIMARY KEY, url TEXT)')
    logger.info("Database initialized successfully.")

# ================= HELPER FUNCTIONS =================
def add_user(user_id: int):
    execute_query('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))

def get_all_users() -> List[int]:
    users = execute_query('SELECT user_id FROM users', fetch_all=True)
    return [u[0] for u in users] if users else []

def get_channels() -> List[Tuple[str, str]]:
    channels = execute_query('SELECT channel_id, url FROM channels', fetch_all=True)
    return channels if channels else []

def check_subscription(user_id: int) -> bool:
    channels = get_channels()
    if not channels:
        return True
    
    for channel_id, _ in channels:
        try:
            status = bot.get_chat_member(channel_id, user_id).status
            if status in ['left', 'kicked']:
                return False
        except Exception as e:
            logger.warning(f"Could not check subscription for {channel_id}: {e}")
            return False
    return True

def generate_qr_with_watermark(data: str) -> io.BytesIO:
    """Generates a QR code image with a custom text watermark."""
    qr = qrcode.QRCode(version=2, box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert('RGB')

    width, height = img.size
    new_height = height + 40
    new_img = Image.new('RGB', (width, new_height), 'white')
    new_img.paste(img, (0, 0))

    draw = ImageDraw.Draw(new_img)
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except IOError:
        font = ImageFont.load_default()

    text_bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    x = (width - text_width) / 2
    y = height + 5

    draw.text((x, y), WATERMARK_TEXT, fill="black", font=font)

    bio = io.BytesIO()
    bio.name = 'qr_code.png'
    new_img.save(bio, 'PNG')
    bio.seek(0)
    return bio

def ask_for_subscription(chat_id: int):
    channels = get_channels()
    markup = InlineKeyboardMarkup()
    for _, url in channels:
        markup.add(InlineKeyboardButton("Kanalga o'tish", url=url))
    
    markup.add(InlineKeyboardButton("✅ Obuna bo'ldim", callback_data="check_sub"))
    bot.send_message(chat_id, "⚠️ Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart!", reply_markup=markup)

# ================= USER HANDLERS =================
@bot.message_handler(commands=['start'])
def send_welcome(message: Message):
    add_user(message.chat.id)
    if not check_subscription(message.from_user.id):
        ask_for_subscription(message.chat.id)
        return
    
    bot.send_message(message.chat.id, "👋 Assalomu alaykum! Menga har qanday link yoki matn yuboring, men uni QR kodga aylantirib beraman.")

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def callback_check(call: CallbackQuery):
    if check_subscription(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ Obunangiz tasdiqlandi!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "Menga link yoki matn yuboring, men uni QR kodga aylantirib beraman.")
    else:
        bot.answer_callback_query(call.id, "❌ Hali hamma kanallarga obuna bo'lmadingiz!", show_alert=True)

# ================= ADMIN HANDLERS =================
@bot.message_handler(commands=['admin'])
def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    text = (
        "👨‍💻 *Admin Panel*\n\n"
        "📊 `/stats` - Foydalanuvchilar statistikasi\n"
        "➕ `/addchannel @username https://t.me/kanal` - Kanal qo'shish\n"
        "➖ `/delchannel @username` - Kanalni o'chirish\n"
        "📋 `/channels` - Majburiy kanallar ro'yxati\n"
        "📢 `/broadcast xabar` - Barchaga reklama yuborish\n"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def bot_stats(message: Message):
    if message.from_user.id == ADMIN_ID:
        users = get_all_users()
        bot.send_message(message.chat.id, f"📊 Botdagi jami foydalanuvchilar: {len(users)} ta")

@bot.message_handler(commands=['addchannel'])
def add_channel(message: Message):
    if message.from_user.id == ADMIN_ID:
        try:
            parts = message.text.split(maxsplit=2)
            channel_id, url = parts[1], parts[2]
            execute_query('INSERT OR REPLACE INTO channels (channel_id, url) VALUES (?, ?)', (channel_id, url))
            bot.send_message(message.chat.id, f"✅ Kanal qo'shildi: {channel_id}\n*Bot ushbu kanalda admin ekanligiga ishonch hosil qiling!*", parse_mode="Markdown")
        except Exception:
            bot.send_message(message.chat.id, "Xato! Format: `/addchannel @username https://t.me/username`", parse_mode="Markdown")

@bot.message_handler(commands=['delchannel'])
def del_channel(message: Message):
    if message.from_user.id == ADMIN_ID:
        try:
            channel_id = message.text.split()[1]
            execute_query('DELETE FROM channels WHERE channel_id = ?', (channel_id,))
            bot.send_message(message.chat.id, f"🗑 Kanal o'chirildi: {channel_id}")
        except Exception:
            bot.send_message(message.chat.id, "Xato! Format: `/delchannel @username`", parse_mode="Markdown")

@bot.message_handler(commands=['channels'])
def list_channels(message: Message):
    if message.from_user.id == ADMIN_ID:
        channels = get_channels()
        if not channels:
            return bot.send_message(message.chat.id, "Majburiy kanallar yo'q.")
        text = "📋 *Majburiy kanallar ro'yxati:*\n\n"
        for ch_id, ch_url in channels:
            text += f"ID: {ch_id} | URL: {ch_url}\n"
        bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['broadcast'])
def broadcast_message(message: Message):
    if message.from_user.id == ADMIN_ID:
        try:
            text = message.text.split(maxsplit=1)[1]
            users = get_all_users()
            sent = 0
            for user in users:
                try:
                    bot.send_message(user, text)
                    sent += 1
                except Exception:
                    pass
            bot.send_message(message.chat.id, f"✅ Xabar {sent} ta foydalanuvchiga yuborildi.")
        except IndexError:
            bot.send_message(message.chat.id, "Foydalanish: `/broadcast xabar matni`", parse_mode="Markdown")

# ================= CORE LOGIC =================
@bot.message_handler(content_types=['text'])
def handle_text(message: Message):
    add_user(message.chat.id)
    
    if not check_subscription(message.from_user.id):
        ask_for_subscription(message.chat.id)
        return

    msg = bot.send_message(message.chat.id, "⏳ QR kod yaratilmoqda...")
    
    try:
        qr_image = generate_qr_with_watermark(message.text)
        bot.send_photo(
            chat_id=message.chat.id, 
            photo=qr_image, 
            caption=f"✅ QR kod tayyor!\n🤖 {WATERMARK_TEXT}"
        )
        bot.delete_message(message.chat.id, msg.message_id)
    except Exception as e:
        logger.error(f"Error generating QR: {e}")
        bot.edit_message_text("❌ QR kod yaratishda xatolik yuz berdi.", message.chat.id, msg.message_id)

# ================= STARTUP =================
if __name__ == '__main__':
    init_db()
    logger.info("Bot is polling...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
