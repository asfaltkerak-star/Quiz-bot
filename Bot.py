import os
import telebot
from telebot import types
from docx import Document
import re
import uuid
import threading

# Railway muhitidan tokenni olamiz
BOT_TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)

# Ma'lumotlarni saqlash xotirasi
quizzes_db = {}       # Barcha test paketlari: {pack_id: {title, creator_id, questions}}
active_sessions = {}   # Jonli ketayotgan testlar taymeri uchun
user_states = {}       # Foydalanuvchi qadamlarini kuzatish: {user_id: {state, file_data, file_name}}

def read_docx(file_path):
    """Word (.docx) faylini o'qib matnga aylantiradi"""
    doc = Document(file_path)
    full_text = []
    for para in doc.paragraphs:
        if para.text.strip():
            full_text.append(para.text.strip())
    return "\n".join(full_text)

def parse_quiz_text(text):
    """? + = formatidagi matnni parse qiladi"""
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
                'question': question[:300],
                'options': [opt[:100] for opt in options[:10]],
                'correct_id': correct_idx
            })
            
    return quizzes

def get_main_keyboard():
    """Doimiy pastki bosh menyu tugmalari"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    btn_upload = types.KeyboardButton("📂 Word yuklash")
    btn_my_quizzes = types.KeyboardButton("📚 Mening testlarim")
    markup.add(btn_upload, btn_my_quizzes)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Deep linking - Foydalanuvchi "Testni boshlash" tugmasini bosib kelganda
    if "start_quiz_" in message.text:
        quiz_pack_id = message.text.split("start_quiz_")[1]
        
        if quiz_pack_id in quizzes_db:
            pack = quizzes_db[quiz_pack_id]
            
            # Agar eski taymer bo'lsa to'xtatamiz
            if chat_id in active_sessions:
                if active_sessions[chat_id]['timer']:
                    active_sessions[chat_id]['timer'].cancel()
            
            active_sessions[chat_id] = {
                'pack_id': quiz_pack_id,
                'current_index': 0,
                'timer': None,
                'is_active': True
            }
            
            bot.send_message(chat_id, f"🚀 **{pack['title']}** testi boshlandi!\nJami savollar soni: {len(pack['questions'])}", reply_markup=get_main_keyboard())
            send_quiz_question(chat_id, 0)
        else:
            bot.send_message(chat_id, "❌ Afsuski, bu test topilmadi yoki o'chib ketgan.", reply_markup=get_main_keyboard())
        return

    # Oddiy start bosilganda pastki menyuni majburan ko'rsatamiz
    bot.send_message(chat_id, 
                     "📌 **Quiz Pack Maker Botiga xush kelibsiz!**\n\n"
                     "Menga Word faylingizni yuboring yoki quyidagi menyudan foydalaning:", 
                     reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "📂 Word yuklash")
def ask_for_file(message):
    bot.send_message(message.chat.id, "📑 Iltimos, menga `?`, `+`, `=` formatida terilgan Word (.docx) faylini yuboring.", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "📚 Mening testlarim")
def show_my_quizzes(message):
    user_id = message.from_user.id
    my_quizzes = [pid for pid, pdata in quizzes_db.items() if pdata['creator_id'] == user_id]
    
    if not my_quizzes:
        bot.send_message(message.chat.id, "ℹ️ Sizda hali tuzilgan testlar yo'q. Word fayl yuborib birinchi testingizni yarating!", reply_markup=get_main_keyboard())
        return
        
    bot.send_message(message.chat.id, f"📚 **Siz yaratgan testlar ro'yxati ({len(my_quizzes)} ta):**", reply_markup=get_main_keyboard())
    
    bot_username = bot.get_me().username
    for pid in my_quizzes:
        pack = quizzes_db[pid]
        start_url = f"https://t.me/{bot_username}?start=start_quiz_{pid}"
        
        inline_markup = types.InlineKeyboardMarkup()
        inline_markup.add(types.InlineKeyboardButton("🔗 Havolani ochish / Ulashish", url=start_url))
        
        bot.send_message(
            message.chat.id,
            f"📝 **Test nomi:** {pack['title']}\n"
            f"📊 Savollar soni: {len(pack['questions'])} ta\n"
            f"🆔 ID: `{pid}`",
            reply_markup=inline_markup
        )

def send_quiz_question(chat_id, q_index):
    """Savollarni Quiz rejimida navbatma-navbat yuborish"""
    session = active_sessions.get(chat_id)
    if not session or not session['is_active']:
        return

    pack = quizzes_db.get(session['pack_id'])
    if not pack or q_index >= len(pack['questions']):
        bot.send_message(chat_id, "🎉 **Test yakunlandi!** Ishtirokingiz uchun rahmat.", reply_markup=get_main_keyboard())
        active_sessions.pop(chat_id, None)
        return

    quiz = pack['questions'][q_index]
    session['current_index'] = q_index
    
    try:
        markup = types.InlineKeyboardMarkup()
        btn_stop = types.InlineKeyboardButton("🛑 Testni tugatish", callback_data=f"stop_quiz_{chat_id}")
        markup.add(btn_stop)

        bot.send_poll(
            chat_id=chat_id,
            question=quiz['question'],
            options=quiz['options'],
            type='quiz',
            correct_option_id=quiz['correct_id'],
            is_anonymous=False,
            open_period=30,
            reply_markup=markup
        )
        
        t = threading.Timer(30.0, send_quiz_question, args=[chat_id, q_index + 1])
        session['timer'] = t
        t.start()
        
    except Exception as e:
        print(f"Xatolik: {e}")
        session['timer'] = threading.Timer(2.0, send_quiz_question, args=[chat_id, q_index + 1])
        session['timer'].start()

@bot.callback_query_handler(func=lambda call: call.data.startswith('stop_quiz_'))
def handle_stop_button(call):
    chat_id = int(call.data.split('stop_quiz_')[1])
    session = active_sessions.get(chat_id)
    if session:
        session['is_active'] = False
        if session['timer']:
            session['timer'].cancel()
        active_sessions.pop(chat_id, None)
        bot.answer_callback_query(call.id, "Test to'xtatildi!")
        bot.send_message(chat_id, "🛑 **Test jarayoni foydalanuvchi tomonidan muddatidan oldin yakunlandi.**", reply_markup=get_main_keyboard())
    else:
        bot.answer_callback_query(call.id, "Bu test allaqachon yakunlangan.")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    user_id = message.from_user.id
    
    if not message.document.file_name.endswith('.docx'):
        bot.reply_to(message, "❌ Iltimos, faqat Word (.docx) formatidagi fayl yuboring.", reply_markup=get_main_keyboard())
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # State (holat) o'rnatiladi
        user_states[user_id] = {
            'state': 'AWAITING_QUIZ_TITLE',
            'file_data': downloaded_file,
            'file_name': message.document.file_name
        }
        
        bot.reply_to(message, "📥 Fayl qabul qilindi!\n\n✍️ **Endi ushbu test uchun ixtiyoriy nom (sarlavha) kiriting:**", reply_markup=get_main_keyboard())
        
    except Exception as e:
        bot.reply_to(message, f"❌ Faylni yuklashda xatolik: {str(e)}", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get('state') == 'AWAITING_QUIZ_TITLE')
def handle_quiz_title(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    quiz_title = message.text.strip()
    
    state_data = user_states.get(user_id)
    if not state_data:
        return
    
    try:
        local_file_name = f"{user_id}_{state_data['file_name']}"
        with open(local_file_name, 'wb') as tmp_file:
            tmp_file.write(state_data['file_data'])
            
        raw_text = read_docx(local_file_name)
        quizzes = parse_quiz_text(raw_text)
        os.remove(local_file_name)
        
        if not quizzes:
            bot.send_message(chat_id, "❌ Fayl ichida to'g'ri formatdagi savollar topilmadi. Qaytdan fayl yuklab ko'ring.", reply_markup=get_main_keyboard())
            user_states.pop(user_id, None)
            return
            
        pack_id = str(uuid.uuid4())[:8]
        
        quizzes_db[pack_id] = {
            'title': quiz_title,
            'creator_id': user_id,
            'questions': quizzes
        }
        
        bot_username = bot.get_me().username
        start_url = f"https://t.me/{bot_username}?start=start_quiz_{pack_id}"
        share_url = f"https://t.me/share/url?url=https://t.me/{bot_username}?start=start_quiz_{pack_id}&text=Ushbu testni yechib ko'ring! 🎯"

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🚀 Testni boshlash", url=start_url))
        markup.add(types.InlineKeyboardButton("👥 Guruhda boshlash", url=f"https://t.me/{bot_username}?startgroup=start_quiz_{pack_id}"))
        markup.add(types.InlineKeyboardButton("📩 Ulashish", url=share_url))
        
        response_text = (
            f"🚀 **{quiz_title}**\n\n"
            f"Ushbu testni yechib ko'ring!\n"
            f"📊 Savollar soni: {len(quizzes)} ta\n"
            f"🔀 Aralashtirish: Ha ✅\n"
            f"⏱ Vaqt: 30 sec"
        )
        
        bot.send_message(chat_id, response_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")
        user_states.pop(user_id, None)
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ Xatolik yuz berdi: {str(e)}", reply_markup=get_main_keyboard())
        user_states.pop(user_id, None)

if __name__ == "__main__":
    print("Menyuli mukammal Quiz bot ishlamoqda...")
    bot.infinity_polling()
