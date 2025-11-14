import sqlite3

# Создание базы данных и таблиц
def init_db():
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            birth_date TEXT,
            bonus_balance INTEGER DEFAULT 200,
            invited_by INTEGER DEFAULT NULL
        )
    """)

    # Таблица акций
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT
        )
    """)

    # Таблица для слова списания бонусов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bonus_word (
            id INTEGER PRIMARY KEY,
            word TEXT DEFAULT 'BB24'
        )
    """)

    # Таблица для сообщений пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            replied BOOLEAN DEFAULT FALSE
        )
    """)

    # Инициализация слова для списания бонусов
    cursor.execute("INSERT OR IGNORE INTO bonus_word (id, word) VALUES (1, 'BB24')")
    conn.commit()
    conn.close()

# Регистрация пользователя
def register_user(user_id, full_name, birth_date, invited_by=None):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (user_id, full_name, birth_date, invited_by) VALUES (?, ?, ?, ?)", 
                   (user_id, full_name, birth_date, invited_by))
    conn.commit()
    conn.close()

# Получение информации о пользователе
def get_user(user_id):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

# Начисление бонусов за приглашение
def add_bonus_for_invite(inviter_id, bonus_amount=200):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET bonus_balance = bonus_balance + ? WHERE user_id = ?", (bonus_amount, inviter_id))
    conn.commit()
    conn.close()

# Получение слова для списания бонусов
def get_bonus_word():
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT word FROM bonus_word WHERE id = 1")
    word = cursor.fetchone()[0]
    conn.close()
    return word

# Обновление слова для списания бонусов
def update_bonus_word(new_word):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE bonus_word SET word = ? WHERE id = 1", (new_word,))
    conn.commit()
    conn.close()

# Сохранение сообщения пользователя
def save_user_message(user_id, message):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO user_messages (user_id, message) VALUES (?, ?)", (user_id, message))
    conn.commit()
    conn.close()

# Получение непрочитанных сообщений
def get_unreplied_messages():
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_messages WHERE replied = FALSE")
    messages = cursor.fetchall()
    conn.close()
    return messages

# Отметка сообщения как отвеченного
def mark_message_as_replied(message_id):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE user_messages SET replied = TRUE WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()

# Получение всех пользователей
def get_all_users():
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    return users

# Добавление акции
def add_promotion(title, description):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO promotions (title, description) VALUES (?, ?)", (title, description))
    conn.commit()
    conn.close()

# Получение всех акций
def get_promotions():
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM promotions")
    promotions = cursor.fetchall()
    conn.close()
    return promotions

# Изменение количества бонусов у пользователя
def update_user_bonus(user_id, bonus_amount):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET bonus_balance = ? WHERE user_id = ?", (bonus_amount, user_id))
    conn.commit()
    conn.close()