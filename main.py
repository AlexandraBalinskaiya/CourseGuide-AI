from dotenv import load_dotenv
from pathlib import Path
import os
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
import openai
import mysql.connector
import json
import random
from datetime import datetime, timedelta
import time
import threading

# Завантажуємо змінні середовища
env_path = Path('.') / 'new.env'
load_dotenv(dotenv_path=env_path)

# Ініціалізація бота
token = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(token)

# Ініціалізація OpenAI
openai_api_key = os.getenv('OPENAI_API_KEY')
openai.api_key = openai_api_key

# Підключення до бази даних
def get_db_connection():
    connection = mysql.connector.connect(
        host='127.0.0.1',
        user='root',
        passwd='ghjgecr33333',
        database='educational_materials'
    )
    return connection

def make_keyboard(for_chat=False):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    if not for_chat:
        markup.row(KeyboardButton("Навчальні матеріали"), KeyboardButton("Пройти квіз"))
        markup.row(KeyboardButton("Переглянути історію"), KeyboardButton("Додати нагадування"))
        markup.row(KeyboardButton("Почати діалог"))
    else:
        markup.row(KeyboardButton("Назад"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = make_keyboard()
    bot.send_message(message.chat.id, "Привіт! Я CourseGuide AI. Оберіть опцію:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "Навчальні матеріали")
def topic_list(message):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT topic FROM educational_materials;")
    topics = cur.fetchall()
    markup = InlineKeyboardMarkup()
    for topic in topics:
        markup.add(InlineKeyboardButton(topic[0], callback_data='topic_' + topic[0]))
    bot.send_message(message.chat.id, "Оберіть тему:", reply_markup=markup)
    cur.close()
    conn.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith('topic_'))
def query_topic(call):
    topic_name = call.data[len('topic_'):]
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT description, links FROM educational_materials WHERE topic = %s", (topic_name,))
    result = cur.fetchone()
    if result:
        description, links = result
        reply_text = f"{description}\nДодатково читати: {links}"
    else:
        reply_text = "Тема не знайдена."
    bot.send_message(call.message.chat.id, reply_text)
    cur.close()
    conn.close()

@bot.message_handler(func=lambda message: message.text == "Почати діалог")
def enter_chat_mode(message):
    bot.send_message(message.chat.id, "Ви в режимі діалогу з AI. Напишіть своє питання або натисніть 'Назад', щоб вийти.", reply_markup=make_keyboard(for_chat=True))
    bot.register_next_step_handler_by_chat_id(message.chat.id, handle_chat)

def handle_chat(message):
    if message.text == "Назад":
        send_welcome(message)
        return
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": message.text}],
            max_tokens=4000
        )
        answer = response.choices[0].message['content']
        # Форматуємо код за допомогою розмітки Markdown
        formatted_answer = format_code(answer)
        bot.send_message(message.chat.id, formatted_answer, parse_mode="Markdown")
        bot.register_next_step_handler_by_chat_id(message.chat.id, handle_chat)
    except Exception as e:
        bot.send_message(message.chat.id, f"Вибачте, сталася помилка: {str(e)}")
        send_welcome(message)

def format_code(answer):
    lines = answer.split('\n')
    formatted_lines = []
    in_code_block = False
    for line in lines:
        if line.strip().startswith("```"):
            if not in_code_block:
                formatted_lines.append("```")
                in_code_block = True
            else:
                formatted_lines.append("```")
                in_code_block = False
        else:
            formatted_lines.append(line)
    return "\n".join(formatted_lines)

# Зберігаємо стан квізу для кожного користувача
quiz_data = {}

@bot.message_handler(func=lambda message: message.text == "Пройти квіз")
def start_quiz(message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM quiz_questions ORDER BY RAND();")
    questions = cur.fetchall()
    quiz_data[user_id] = {
        "questions": questions,
        "current": 0,
        "correct": 0,
        "answers": []
    }
    send_next_question(message.chat.id, user_id)
    cur.close()
    conn.close()

def send_next_question(chat_id, user_id):
    question_info = quiz_data[user_id]["questions"][quiz_data[user_id]["current"]]
    question = question_info[1]  # Індекс, де зберігається питання
    answers = json.loads(question_info[2])  # Десеріалізуємо JSON в список
    correct = question_info[3]  # Індекс правильної відповіді

    # Рандомізуємо відповіді
    answer_keys = list(range(len(answers)))
    random.shuffle(answer_keys)
    markup = InlineKeyboardMarkup()
    for key in answer_keys:
        markup.add(InlineKeyboardButton(answers[key], callback_data=f"quiz_{user_id}_{key}"))
    bot.send_message(chat_id, question, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('quiz_'))
def handle_answer(call):
    _, user_id, answer_idx = call.data.split('_')
    user_id = int(user_id)
    answer_idx = int(answer_idx)
    question_info = quiz_data[user_id]["questions"][quiz_data[user_id]["current"]]
    correct_answer = question_info[3]
    answers = json.loads(question_info[2])  # Десеріалізуємо JSON

    if answer_idx == correct_answer:
        quiz_data[user_id]["correct"] += 1
        response = "Правильно!"
    else:
        correct_response = answers[correct_answer]
        response = f"Неправильно! Правильна відповідь: {correct_response}"

    bot.answer_callback_query(call.id, response)
    quiz_data[user_id]["answers"].append(answer_idx)
    quiz_data[user_id]["current"] += 1

    if quiz_data[user_id]["current"] < len(quiz_data[user_id]["questions"]):
        send_next_question(call.message.chat.id, user_id)
    else:
        score = quiz_data[user_id]["correct"]
        total = len(quiz_data[user_id]["questions"])
        percentage = round((score / total) * 100)  # Округлення до цілого числа
        bot.send_message(call.message.chat.id, f"Квіз завершено! Ваш результат: {score}/{total} ({percentage}%)")

        # Зберігаємо результат у базу даних
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO quiz_attempts (user_id, questions, answers, score, total) VALUES (%s, %s, %s, %s, %s)",
            (user_id, json.dumps([q[1] for q in quiz_data[user_id]["questions"]]), json.dumps(quiz_data[user_id]["answers"]), score, total)
        )
        conn.commit()
        cur.close()
        conn.close()

        send_welcome(call.message)

@bot.message_handler(func=lambda message: message.text == "Переглянути історію")
def view_history(message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT quiz_date, score, total FROM quiz_attempts WHERE user_id = %s ORDER BY quiz_date DESC", (user_id,))
    attempts = cur.fetchall()
    if attempts:
        history = "\n".join([f"{quiz_date}: {score}/{total} ({round((score/total)*100)}%)" for quiz_date, score, total in attempts])
        bot.send_message(message.chat.id, f"Історія ваших спроб:\n{history}")
    else:
        bot.send_message(message.chat.id, "У вас ще немає спроб пройти квіз.")
    cur.close()
    conn.close()

@bot.message_handler(func=lambda message: message.text == "Додати нагадування")
def add_reminder(message):
    bot.send_message(message.chat.id, "Введіть дату та час нагадування у форматі РРРР-ММ-ДД ГГ:ХХ:")
    bot.register_next_step_handler(message, process_reminder_time)

def process_reminder_time(message):
    try:
        reminder_time = datetime.strptime(message.text, '%Y-%m-%d %H:%M')
        bot.send_message(message.chat.id, "Введіть примітку:")
        bot.register_next_step_handler(message, lambda msg: save_reminder(msg, reminder_time))
    except ValueError:
        bot.send_message(message.chat.id, "Неправильний формат дати. Спробуйте ще раз.")
        bot.register_next_step_handler(message, process_reminder_time)

def save_reminder(message, reminder_time):
    user_id = message.from_user.id
    note = message.text
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reminders (user_id, reminder_time, note) VALUES (%s, %s, %s)",
        (user_id, reminder_time, note)
    )
    conn.commit()
    cur.close()
    conn.close()
    bot.send_message(message.chat.id, f"Нагадування збережено на {reminder_time} з приміткою: {note}")

def send_reminders():
    while True:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, user_id, note FROM reminders WHERE reminder_time <= NOW() AND is_sent = FALSE")
        reminders = cur.fetchall()
        for reminder in reminders:
            reminder_id, user_id, note = reminder
            bot.send_message(user_id, f"Нагадування: {note}")
            cur.execute("UPDATE reminders SET is_sent = TRUE WHERE id = %s", (reminder_id,))
        conn.commit()
        cur.close()
        conn.close()
        time.sleep(60)

# Запускаємо потік для перевірки нагадувань
reminder_thread = threading.Thread(target=send_reminders, daemon=True)
reminder_thread.start()

bot.polling()

