import os
import telebot
import time
import threading
from docx import Document
import re

# Railway muhitidan tokenni olamiz
BOT_TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)

# Har bir foydalanuvchi uchun test jarayonini alohida nazorat qilish bazasi
user_sessions = {}

def read_docx(file_path):
    """Word faylini o'qib, matnga aylantiradi"""
    doc = Document(file_path)
    full_text = []
    for para in doc.paragraphs:
        if para.text.strip():
            full_text.append(para.text.strip())
    return "\n".join(full_text)

def parse_quiz_text(text):
    """? + = formatidagi matnni Telegram Poll formatiga parse qiladi"""
    # Savollarni '?' belgisi bilan boshlangan qatorlar bo'yicha ajratamiz
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
                # Savol matnini tozalash (agar bir nechta ? bo'lsa ham)
                question = line.lstrip('?').strip()
            elif line.startswith('+'):
                # To'g'ri javob indeksi saqlanadi
                ans = line.lstrip('+').strip()
                options.append(ans)
                correct_idx = len(options) - 1
            elif line.startswith('='):
                ans = line.lstrip('=').strip()
                options.append(ans)
                
        # Telegram qoidalari: variantlar soni 2 tadan 10 tagacha, savol va to'g'ri javob bo'lishi shart
        if question and len(options) >= 2 and correct_idx is not None:
            quizzes.append({
                'question': question[:300], # Telegram limiti 300 belgi
                'options': [opt[:100] for opt in options[:10]], # Maks 10 variant, har biri 100 belgi
                'correct_id': correct_idx
            })
            
    return quizzes

def run_quiz_timer(chat_id, user_id):
    """Taymer bo'yicha savollarni ketma-ket yuborish funksiyasi (Alohida oqimda ishlaydi)"""
    session = user_sessions.get(user_id)
    if not session:
        return
        
    quizzes = session['quizzes']
    current_index = session['current_index']
    
    # Agar savollar tugagan bo'lsa yoki foydalanuvchi testni to'xtatgan bo'lsa
    if current_index >= len(quizzes) or not session['is_active']:
        bot.send_message(chat_id, "🎉 Test yakunlandi! Barcha savollar yuborib bo'lindi.")
        user_sessions.pop(user_id, None)
        return

    quiz = quizzes[current_index]
    
    try:
        # Telegram Quiz rejimida poll yuborish
        bot.send_poll(
            chat_id=chat_id,
            question=quiz['question'],
            options=quiz['options'],
            type='quiz',
            correct_option_id=quiz['correct_id'],
            is_anonymous=False, # Kim qanday javob berganini ko'rish uchun
            open_period=30 # 30 soniyadan keyin test avtomatik yopiladi
        )
        
        # Keyingi savolga indeksni oshiramiz
        session['current_index'] += 1
        
        # 30 soniya kutish taymeri (guruh a'zolari o'ylab javob berishi uchun)
        # threading.Timer orqali bot boshqa foydalanuvchilarga ham javob bera oladi, qotib qolmaydi
        timer = threading.Timer(30.0, run_quiz_timer, args=[chat_id, user_id])
        session['timer_thread'] = timer
        timer.start()
        
    except Exception as e:
        print(f"Test yuborishda xatolik: {e}")
        bot.send_message(chat_id, "❌ Testni davom ettirishda xatolik yuz berdi. Keyingi savolga o'tilmoqda...")
        session['current_index'] += 1
        run_quiz_timer(chat_id, user_id)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "📌 **Quiz Maker Botiga xush kelibsiz!**\n\n"
                          "Menga savollari `?`, `+`, `=` formatida terilgan Word (.docx) faylini yuboring. "
                          "Men uni avtomatik ravishda har 30 soniyada tushadigan jonli Quizga aylantirib beraman!")

@bot.message_handler(commands=['stop'])
def stop_quiz(message):
    """Joriy ketayotgan testni majburiy to'xtatish buyrug'i"""
    user_id = message.from_user.id
    if user_id in user_sessions:
        user_sessions[user_id]['is_active'] = False
        if 'timer_thread' in user_sessions[user_id]:
            user_sessions[user_id]['timer_thread'].cancel()
        bot.reply_to(message, "🛑 Test majburiy to'xtatildi.")
        user_sessions.pop(user_id, None)
    else:
        bot.reply_to(message, "Hozirda hech qanday faol test jarayoni ketmayapti.")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Agar foydalanuvchida allaqachon test ketayotgan bo'lsa, yangisini qabul qilmaymiz
    if user_id in user_sessions and user_sessions[user_id]['is_active']:
        bot.reply_to(message, "⚠️ Sizda hozir faol test jarayoni ketmoqda. Uni to'xtatish uchun /stop buyrug'ini yuboring.")
        return

    if not message.document.file_name.endswith('.docx'):
        bot.reply_to(message, "❌ Xatolik! Iltimos, faqat Word (.docx) formatidagi fayl yuboring.")
        return

    try:
        # Faylni yuklab olish
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        file_name = message.document.file_name
        with open(file_name, 'wb') as tmp_file:
            tmp_file.write(downloaded_file)
            
        bot.reply_to(message, "📥 Fayl yuklab olindi. Savollar tahlil qilinmoqda...")
        
        # Word ichidagi matnni o'qish va formatlash
        raw_text = read_docx(file_name)
        quizzes = parse_quiz_text(raw_text)
        
        # Vaqtincha saqlangan faylni o'chirib tashlaymiz
        os.remove(file_name)
        
        if not quizzes:
            bot.send_message(chat_id, "❌ Fayl ichida mos keladigan savollar topilmadi. "
                                      "Formatni tekshiring:\n`?Savol`\n`+To'g'ri javob`\n`=Noto'g'ri`")
            return
            
        bot.send_message(chat_id, f"✅ Muvaffaqiyatli yuklandi! Jami **{len(quizzes)} ta** savol aniqlandi.\n"
                                  f"🚀 Test boshlandi! Har bir savol uchun 30 soniya vaqt beriladi.")
        
        # Yangi seans yaratamiz
        user_sessions[user_id] = {
            'quizzes': quizzes,
            'current_index': 0,
            'is_active': True
        }
        
        # Birinchi savolni yuborish bilan jarayonni start qilamiz
        run_quiz_timer(chat_id, user_id)
        
    except Exception as e:
        bot.reply_to(message, f"❌ Faylni o'qishda xatolik yuz berdi: {str(e)}")

if __name__ == "__main__":
    print("Bot Railway-da muvaffaqiyatli ishlamoqda...")
    bot.infinity_polling()
