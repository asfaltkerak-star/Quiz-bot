import os
import telebot
from docx import Document
from pypdf import PdfReader
import re

# Tokenni Render serverining yashirin xotirasidan o'qiymiz
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

def convert_to_quiz_format(raw_text):
    text = re.sub(r'\|The following table:|==+|\+\+\+\+', '', raw_text)
    blocks = re.split(r'\n(?=\d+[\.\)])', text.strip())
    final_output = []
    for block in blocks:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 2:
            continue
        question = lines[0]
        quiz_block = f"?{question}\n"
        for line in lines[1:]:
            cleaned_line = line.strip('"').strip("'")
            if cleaned_line.startswith('#'):
                actual_answer = cleaned_line.replace('#', '', 1).strip()
                quiz_block += f"+{actual_answer}\n"
            else:
                quiz_block += f"={cleaned_line}\n"
        final_output.append(quiz_block)
    return "\n".join(final_output)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Salom! Menga testlar bor bo'lgan Word (.docx) yoki PDF (.pdf) faylini yuboring. Men uni @QuizBot formatiga o'tkazib beraman!")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_name = message.document.file_name
        file_ext = os.path.splitext(file_name)[1].lower()

        with open(file_name, 'wb') as new_file:
            new_file.write(downloaded_file)

        bot.reply_to(message, "Fayl qabul qilindi, tahlil qilinmoqda...")

        raw_text = ""
        if file_ext == '.docx':
            raw_text = read_docx(file_name)
        elif file_ext == '.pdf':
            raw_text = read_pdf(file_name)
        else:
            bot.reply_to(message, "Format xato! Faqat .docx yoki .pdf yuboring.")
            os.remove(file_name)
            return

        formatted_quiz = convert_to_quiz_format(raw_text)
        output_file_name = "tayyor_quiz_format.txt"
        with open(output_file_name, "w", encoding="utf-8") as out_file:
            out_file.write(formatted_quiz)

        with open(output_file_name, "rb") as out_file:
            bot.send_document(message.chat.id, out_file, caption="Mana, @QuizBot uchun tayyor fayl!")

        os.remove(file_name)
        os.remove(output_file_name)
    except Exception as e:
        bot.reply_to(message, f"Xatolik yuz berdi: {str(e)}")

print("Bot ishlamoqda...")
bot.infinity_polling()