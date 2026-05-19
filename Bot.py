import os
import telebot
from docx import Document
from pypdf import PdfReader
import tempfile
import time

BOT_TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)


def read_docx(file_path):
    doc = Document(file_path)
    full_text = []
    for para in doc.paragraphs:
        if para.text.strip():
            full_text.append(para.text.strip())
    return "\n".join(full_text)


def read_pdf(file_path):
    reader = PdfReader(file_path)
    full_text = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            full_text.append(text)
    return "\n".join(full_text)


def parse_questions(text):
    """
    Formatni tahlil qiladi:
    ?Savol matni
    +To'g'ri javob
    =Noto'g'ri javob
    =Noto'g'ri javob
    """
    questions = []
    current_question = None
    current_answers = []
    correct_index = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith('?'):
            # Oldingi savolni saqlash
            if current_question and current_answers and correct_index is not None:
                questions.append({
                    'question': current_question,
                    'answers': current_answers,
                    'correct': correct_index
                })
            # Yangi savol boshlash
            current_question = line[1:].strip()
            current_answers = []
            correct_index = None

        elif line.startswith('+'):
            answer = line[1:].strip()
            correct_index = len(current_answers)
            current_answers.append(answer)

        elif line.startswith('='):
            answer = line[1:].strip()
            current_answers.append(answer)

    # Oxirgi savolni qo'shish
    if current_question and current_answers and correct_index is not None:
        questions.append({
            'question': current_question,
            'answers': current_answers,
            'correct': correct_index
        })

    return questions


def send_quiz_polls(chat_id, questions):
    """Har bir savolni Telegram quiz poll sifatida yuboradi"""
    sent = 0
    skipped = 0

    for i, q in enumerate(questions):
        question_text = q['question']
        answers = q['answers']
        correct_index = q['correct']

        # Telegram cheklovi: savol max 300 belgi, javob max 100 belgi
        if len(question_text) > 300:
            question_text = question_text[:297] + "..."

        answers = [a[:100] for a in answers]

        # Telegram: 2-10 ta javob bo'lishi kerak
        if len(answers) < 2 or len(answers) > 10:
            skipped += 1
            continue

        if correct_index >= len(answers):
            skipped += 1
            continue

        try:
            bot.send_poll(
                chat_id=chat_id,
                question=question_text,
                options=answers,
                type='quiz',
                correct_option_id=correct_index,
                is_anonymous=False
            )
            sent += 1
            # Telegram rate limit uchun kichik pauza
            time.sleep(0.5)
        except Exception as e:
            print(f"Poll yuborishda xato (savol {i+1}): {e}")
            skipped += 1

    return sent, skipped


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message,
        "Salom! Menga testlar bor .docx yoki .pdf faylini yuboring.\n"
        "Men har bir savolni Telegram Quiz sifatida yuboraman!"
    )


@bot.message_handler(content_types=['document'])
def handle_docs(message):
    file_name = None
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        original_name = message.document.file_name
        file_ext = os.path.splitext(original_name)[1].lower()

        if file_ext not in ['.docx', '.pdf']:
            bot.reply_to(message, "❌ Format xato! Faqat .docx yoki .pdf yuboring.")
            return

        # Vaqtincha fayl yaratish
        with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp:
            tmp.write(downloaded_file)
            file_name = tmp.name

        bot.reply_to(message, "📄 Fayl qabul qilindi, savollar tahlil qilinmoqda...")

        # Matn o'qish
        if file_ext == '.docx':
            raw_text = read_docx(file_name)
        else:
            raw_text = read_pdf(file_name)

        # Savollarni ajratib olish
        questions = parse_questions(raw_text)

        if not questions:
            bot.reply_to(
                message,
                "⚠️ Savollar topilmadi. Fayl formati to'g'rimi?\n"
                "Format: ? savol, + to'g'ri javob, = noto'g'ri javob"
            )
            return

        bot.reply_to(message, f"✅ {len(questions)} ta savol topildi. Yuborilmoqda...")

        # Quiz polllarni yuborish
        sent, skipped = send_quiz_polls(message.chat.id, questions)

        result_msg = f"🎉 Tayyor! {sent} ta quiz yuborildi."
        if skipped > 0:
            result_msg += f"\n⚠️ {skipped} ta savol o'tkazib yuborildi (format xato yoki limit)."
        bot.send_message(message.chat.id, result_msg)

    except Exception as e:
        bot.reply_to(message, f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        if file_name and os.path.exists(file_name):
            os.remove(file_name)


print("Bot ishlamoqda...")
bot.infinity_polling()
