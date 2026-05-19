import os
import telebot
from telebot import types
from docx import Document
import re
import uuid

# Railway yoki muhit o'zgaruvchilaridan tokenni olamiz
BOT_TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)

# Test ma'lumotlarini server xotirasida saqlash uchun baza
# (Katta loyihalarda buni ma'lumotlar bazasiga ulash tavsiya etiladi)
quizzes_db = {}

def read_docx(file_path):
    """Word (.docx) faylini o'qib matnga aylantiradi"""
    doc = Document(file_path)
    full_text = []
    for para in doc.paragraphs:
        if para.text.strip():
            full_text.append(para.text.strip())
    return "\n".join(full_text)

def parse_quiz_text(text):
    """? + = formatidagi matnni parse qiladi va struktura holatiga keltiradi"""
    blocks = re.split(r'\n(?=\?)', text.strip())
    quizzes = []
    
    for block in blocks:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 2:
            continue
            
        question = ""
        options = []
        correct_idx = None
        
        for line in lines:
            if line.startswith('?'):
                question = line.lstrip('?').strip()
            elif line.startswith('+'):
                ans = line.lstrip('+').strip()
                options.append(ans)
                correct_idx = len(options) - 1
            elif line.startswith('='):
                ans = line.lstrip('=').strip()
                options.append(ans)
                
        if question and len(options) >= 2 and correct_idx is not None:
            quizzes.append({
                'id': str(uuid.uuid4()), # Har bir savol uchun unikal ID
                'question': question[:300],
                'options': [opt[:100] for opt in options[:10]],
                'correct_id': correct_idx
            })
            
    return quizzes

@bot.message_handler(commands=['start'])
def send_welcome(message):
    # Agar foydalanuvchi "Testni boshlash" tugmasini bosib kelgan bo'lsa (deep linking)
    if "start_quiz_" in message.text:
        quiz_pack_id = message.text.split("start_quiz_")[1]
        if quiz_pack_id in quizzes_db:
            pack = quizzes_db[quiz_pack_id]
            bot.send_message(message.chat.id, f"🚀 **{pack['title']}** testi boshlandi!\nJami savollar soni: {len(pack['questions'])}")
            # Birinchi savolni yuborish
            send_quiz_question(message.chat.id, quiz_pack_id, 0)
        else:
            bot.reply_to(message, "❌ Afsuski, bu test topilmadi yoki o'chib ketgan.")
        return

    bot.reply_to(message, "📌 **Quiz Pack Maker Botiga xush kelibsiz!**\n\n"
                          "Menga savollari `?`, `+`, `=` formatida bo'lgan Word (.docx) faylini yuboring. "
                          "Men sizga hamma savollarni bitta paketga yig'ib, chiroyli havola qilib beraman!")

def send_quiz_question(chat_id, pack_id, q_index):
    """Savollarni ketma-ket Quiz rejimida yuborish va taymerni boshqarish"""
    pack = quizzes_db.get(pack_id)
    if not pack or q_index >= len(pack['questions']):
        bot.send_message(chat_id, "🎉 **Test yakunlandi!** Ishtirokingiz uchun rahmat.")
        return

    quiz = pack['questions'][q_index]
    
    # Poll jo'natiladi
    poll_msg = bot.send_poll(
        chat_id=chat_id,
        question=quiz['question'],
        options=quiz['options'],
        type='quiz',
        correct_option_id=quiz['correct_id'],
        is_anonymous=False,
        open_period=30 # Har bir savol uchun 30 soniya
    )
    
    # 30 soniyadan keyin keyingi savolni yuborish uchun threading ishlatamiz
    import threading
    threading.Timer(30.0, send_quiz_question, args=[chat_id, pack_id, q_index + 1]).start()

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    if not message.document.file_name.endswith('.docx'):
        bot.reply_to(message, "❌ Iltimos, faqat Word (.docx) formatidagi fayl yuboring.")
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        file_name = message.document.file_name
        with open(file_name, 'wb') as tmp_file:
            tmp_file.write(downloaded_file)
            
        bot.reply_to(message, "📥 Fayl yuklandi, tahlil qilinmoqda...")
        
        raw_text = read_docx(file_name)
        quizzes = parse_quiz_text(raw_text)
        os.remove(file_name)
        
        if not quizzes:
            bot.reply_to(message, "❌ Fayl ichida to'g'ri formatdagi savollar topilmadi.")
            return
            
        # Yangi test paketi yaratiladi va bazaga qo'shiladi
        pack_id = str(uuid.uuid4())[:8] # Qisqa ID
        test_title = os.path.splitext(message.document.file_name)[0]
        
        quizzes_db[pack_id] = {
            'title': test_title,
            'questions': quizzes
        }
        
        # Chiroyli menyu tugmalarini yaratamiz (Xuddi rasmdagidek)
        bot_username = bot.get_me().username
        start_url = f"https://t.me/{bot_username}?start=start_quiz_{pack_id}"
        share_url = f"https://t.me/share/url?url=https://t.me/{bot_username}?start=start_quiz_{pack_id}&text=Ushbu testni yechib ko'ring! 🎯"

        markup = types.InlineKeyboardMarkup()
        btn_start = types.InlineKeyboardButton("🚀 Testni boshlash", url=start_url)
        btn_group = types.InlineKeyboardButton("👥 Guruhda boshlash", url=f"https://t.me/{bot_username}?startgroup=start_quiz_{pack_id}")
        btn_share = types.InlineKeyboardButton("📩 Ulashish", url=share_url)
        
        markup.add(btn_start)
        markup.add(btn_group)
        markup.add(btn_share)
        
        response_text = (
            f"🚀 **{test_title}**\n\n"
            f"Ushbu testni yechib ko'ring!\n"
            f"📊 Savollar soni: {len(quizzes)}\n"
            f"🔀 Aralashtirish: Ha ✅\n"
            f"⏱ Vaqt: 30 sec"
        )
        
        bot.send_message(message.chat.id, response_text, reply_markup=markup)
        
    except Exception as e:
        bot.reply_to(message, f"❌ Xatolik yuz berdi: {str(e)}")

if __name__ == "__main__":
    print("Havolali Quiz bot ishga tushdi...")
    bot.infinity_polling()
