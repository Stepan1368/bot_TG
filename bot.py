import logging
import sqlite3
from datetime import datetime, time
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    CallbackQuery,
    Message
)
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError
from aiogram.filters import Filter
from config import (
    BOT_TOKEN, 
    ADMIN_ID, 
    DATABASE_NAME,
    BONUS_FOR_REGISTRATION,
    BONUS_FOR_REFERRAL,
    BIRTHDAY_BONUS,
    BIRTHDAY_MESSAGE,
    CHECK_BIRTHDAYS_TIME
)
import asyncio
import re
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Инициализация бота ---
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# --- Роутеры ---
user_router = Router()
admin_router = Router()

# --- Класс базы данных ---
class Database:
    def __init__(self, db_name: str = DATABASE_NAME):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self._init_tables()
        self._init_default_data()
    
    def _init_tables(self):
        with self.conn:
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE NOT NULL,
                    full_name TEXT NOT NULL,
                    birth_date TEXT NOT NULL,
                    bonus_balance INTEGER DEFAULT 0,
                    invited_by INTEGER,
                    registration_date TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_activity TEXT,
                    last_birthday_bonus_year INTEGER
                )
            ''')
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS promotions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS bonus_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    operation TEXT CHECK(operation IN ('add', 'subtract')),
                    description TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
            ''')
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS bonus_words (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    word TEXT UNIQUE NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
    
    def _init_default_data(self):
        """Добавляем стандартные бонусные слова при первом запуске"""
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM bonus_words")
            if cursor.fetchone()[0] == 0:
                default_words = ['ЗОЛОТОЙ КЛИЕНТ', 'ПРЕМИУМ', 'БОНУС', 'VIP']
                self.conn.executemany(
                    "INSERT INTO bonus_words (word) VALUES (?)",
                    [(word,) for word in default_words]
                )
    
    def add_user(self, user_id: int, full_name: str, birth_date: str, invited_by: int = None) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO users (user_id, full_name, birth_date, invited_by) VALUES (?, ?, ?, ?)",
                    (user_id, full_name, birth_date, invited_by)
                )
                self.add_bonus_transaction(user_id, BONUS_FOR_REGISTRATION, 'add', 'Регистрация')
                if invited_by:
                    self.add_bonus_transaction(invited_by, BONUS_FOR_REFERRAL, 'add', f'За приглашение {user_id}')
                return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False
    
    def get_user(self, user_id: int) -> tuple | None:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
    def update_user_activity(self, user_id: int):
        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE users SET last_activity = ? WHERE user_id = ?",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id)
                )
        except Exception as e:
            logger.error(f"Error updating activity: {e}")
    
    def add_bonus_transaction(self, user_id: int, amount: int, operation: str, description: str = "") -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO bonus_transactions (user_id, amount, operation, description) VALUES (?, ?, ?, ?)",
                    (user_id, amount, operation, description)
                )
                if operation == 'add':
                    self.conn.execute(
                        "UPDATE users SET bonus_balance = bonus_balance + ? WHERE user_id = ?",
                        (amount, user_id)
                    )
                else:
                    self.conn.execute(
                        "UPDATE users SET bonus_balance = bonus_balance - ? WHERE user_id = ?",
                        (amount, user_id)
                    )
                return True
        except Exception as e:
            logger.error(f"Error adding transaction: {e}")
            return False
    
    def get_user_bonus_balance(self, user_id: int) -> int:
        user = self.get_user(user_id)
        return user[4] if user else 0
    
    def get_all_users(self) -> list[tuple]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT user_id, full_name, bonus_balance FROM users")
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    def add_promotion(self, title: str, description: str) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO promotions (title, description) VALUES (?, ?)",
                    (title, description)
                )
                return True
        except Exception as e:
            logger.error(f"Error adding promotion: {e}")
            return False
    
    def get_active_promotions(self) -> list[tuple]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT title, description FROM promotions WHERE is_active = 1")
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting promotions: {e}")
            return []
    
    def get_all_promotions(self) -> list[tuple]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT id, title, description FROM promotions")
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting all promotions: {e}")
            return []

    def delete_promotion(self, promotion_id: int) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    "DELETE FROM promotions WHERE id = ?",
                    (promotion_id,)
                )
                return True
        except Exception as e:
            logger.error(f"Error deleting promotion: {e}")
            return False
    
    def get_todays_birthday_users(self) -> list[tuple]:
        try:
            today = datetime.now().strftime("%d.%m")
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT user_id, full_name, birth_date, last_birthday_bonus_year 
                FROM users 
                WHERE substr(birth_date, 1, 5) = ?
            ''', (today,))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting birthday users: {e}")
            return []

    def update_birthday_bonus(self, user_id: int, year: int) -> bool:
        try:
            with self.conn:
                self.conn.execute('''
                    UPDATE users 
                    SET last_birthday_bonus_year = ? 
                    WHERE user_id = ?
                ''', (year, user_id))
                return True
        except Exception as e:
            logger.error(f"Error updating birthday bonus: {e}")
            return False
    
    # Методы для работы с бонусными словами
    def add_bonus_word(self, word: str) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO bonus_words (word) VALUES (?)",
                    (word.upper(),)
                )
                return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logger.error(f"Error adding bonus word: {e}")
            return False
    
    def delete_bonus_word(self, word_id: int) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    "DELETE FROM bonus_words WHERE id = ?",
                    (word_id,)
                )
                return True
        except Exception as e:
            logger.error(f"Error deleting bonus word: {e}")
            return False
    
    def get_all_bonus_words(self) -> list[tuple]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT id, word FROM bonus_words ORDER BY word")
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting bonus words: {e}")
            return []
    
    def get_random_bonus_word(self) -> str:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT word FROM bonus_words WHERE is_active = 1 ORDER BY RANDOM() LIMIT 1")
            result = cursor.fetchone()
            return result[0] if result else "БОНУС"  # Дефолтное слово
        except Exception as e:
            logger.error(f"Error getting random bonus word: {e}")
            return "БОНУС"
    
    def update_bonus_word(self, word_id: int, new_word: str) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE bonus_words SET word = ? WHERE id = ?",
                    (new_word.upper(), word_id)
                )
                return True
        except Exception as e:
            logger.error(f"Error updating bonus word: {e}")
            return False
    
    def close(self):
        self.conn.close()

db = Database()

# --- Клавиатуры ---
def get_user_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Остатки бонусов")],
            [KeyboardButton(text="📢 Пригласить друга")],
            [KeyboardButton(text="🎁 Акции и бонусы")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие"
    )

def get_admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📢 Добавить акцию"),
             KeyboardButton(text="🗑️ Удалить акцию")],
            [KeyboardButton(text="🔑 Бонусные слова"),
             KeyboardButton(text="👥 Управление пользователями")],
            [KeyboardButton(text="📩 Рассылка")],
            [KeyboardButton(text="🔙 Выйти из админки")]
        ],
        resize_keyboard=True
    )

def get_back_to_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Назад в меню")]],
        resize_keyboard=True
    )

# --- Состояния ---
class UserStates(StatesGroup):
    waiting_full_name = State()
    waiting_birth_date = State()
    bonus_spend = State()

class AdminStates(StatesGroup):
    add_promotion_title = State()
    add_promotion_description = State()
    broadcast_message = State()
    manage_user_select = State()
    manage_user_action = State()
    delete_promotion = State()
    manage_bonus_words = State()
    add_bonus_word = State()
    edit_bonus_word_select = State()
    edit_bonus_word_new = State()
    delete_bonus_word = State()

# --- Фильтры ---
class IsAdmin(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id == ADMIN_ID

# --- Функции для работы с днями рождения ---
async def check_birthdays():
    try:
        today = datetime.now()
        users = db.get_todays_birthday_users()
        
        for user_id, full_name, birth_date, last_bonus_year in users:
            if last_bonus_year != today.year:
                if db.add_bonus_transaction(user_id, BIRTHDAY_BONUS, 'add', 'День рождения'):
                    db.update_birthday_bonus(user_id, today.year)
                    message = BIRTHDAY_MESSAGE.format(
                        name=full_name.split()[0],
                        bonus=BIRTHDAY_BONUS
                    )
                    try:
                        await bot.send_message(user_id, message)
                        logger.info(f"Birthday bonus sent to {user_id}")
                    except Exception as e:
                        logger.error(f"Error sending birthday message to {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error in birthday check: {e}")

async def check_user_birthday(user_id: int, full_name: str, birth_date: str):
    try:
        today = datetime.now()
        birth_day, birth_month = map(int, birth_date.split('.')[:2])
        
        if birth_day == today.day and birth_month == today.month:
            user_data = db.get_user(user_id)
            if user_data and user_data[8] != today.year:
                if db.add_bonus_transaction(user_id, BIRTHDAY_BONUS, 'add', 'День рождения'):
                    db.update_birthday_bonus(user_id, today.year)
                    message = BIRTHDAY_MESSAGE.format(
                        name=full_name.split()[0],
                        bonus=BIRTHDAY_BONUS
                    )
                    await bot.send_message(user_id, message)
    except Exception as e:
        logger.error(f"Error checking birthday for {user_id}: {e}")

# --- Пользовательские обработчики ---
@user_router.message(Command("start"))
async def user_start(message: Message, state: FSMContext, command: CommandObject):
    try:
        user_id = message.from_user.id
        db.update_user_activity(user_id)
        
        user = db.get_user(user_id)
        if not user:
            if command.args and command.args.startswith('ref_'):
                try:
                    referrer_id = int(command.args.split('_')[1])
                    if referrer_id != user_id:
                        await state.update_data(invited_by=referrer_id)
                except (ValueError, IndexError):
                    pass

            await message.answer(
                "👋 Добро пожаловать в наш бонусный клуб!\n"
                "Для регистрации введите ваше полное ФИО:"
            )
            await state.set_state(UserStates.waiting_full_name)
        else:
            await check_user_birthday(user_id, user[2], user[3])
            await message.answer(
                f"🎉 С возвращением, {user[2]}!\n"
                f"Ваш баланс: {user[4]} бонусов",
                reply_markup=get_user_menu()
            )
    except Exception as e:
        logger.error(f"Start error: {e}")
        await message.answer("⚠️ Произошла ошибка. Попробуйте позже.")

@user_router.message(UserStates.waiting_full_name)
async def process_full_name(message: Message, state: FSMContext):
    try:
        full_name = message.text.strip()
        if len(full_name.split()) < 2:
            await message.answer("❌ Введите полное ФИО (минимум 2 слова)")
            return

        await state.update_data(full_name=full_name)
        await message.answer(
            "📅 Теперь введите вашу дату рождения в формате ДД.ММ.ГГГГ:\n"
            "Пример: 15.05.1990"
        )
        await state.set_state(UserStates.waiting_birth_date)
    except Exception as e:
        logger.error(f"Full name error: {e}")
        await message.answer("⚠️ Ошибка обработки данных. Попробуйте снова.")

@user_router.message(UserStates.waiting_birth_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def process_birth_date(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        full_name = data.get('full_name')
        birth_date = message.text
        
        try:
            day, month, year = map(int, birth_date.split('.'))
            datetime(year=year, month=month, day=day)
        except ValueError:
            await message.answer("❌ Некорректная дата. Попробуйте снова.")
            return

        invited_by = data.get('invited_by')
        if db.add_user(message.from_user.id, full_name, birth_date, invited_by):
            await message.answer(
                f"✅ Регистрация завершена!\n"
                f"Добро пожаловать, {full_name}!\n"
                f"Ваш стартовый бонус: {BONUS_FOR_REGISTRATION} баллов",
                reply_markup=get_user_menu()
            )
            if invited_by:
                await message.answer(
                    f"🎁 Вы были приглашены пользователем. "
                    f"За это вы получили дополнительно {BONUS_FOR_REFERRAL} бонусов!"
                )
        else:
            await message.answer("⚠️ Ошибка регистрации. Возможно, вы уже зарегистрированы.")
        
        await state.clear()
    except Exception as e:
        logger.error(f"Birth date error: {e}")
        await message.answer("⚠️ Ошибка обработки данных. Попробуйте снова.")

@user_router.message(F.text == "💰 Остатки бонусов")
async def show_bonus_balance(message: Message):
    try:
        user_id = message.from_user.id
        balance = db.get_user_bonus_balance(user_id)
        await message.answer(
            f"💳 Ваш текущий баланс: {balance} бонусов\n"
            "Для списания бонусов используйте кнопку ниже:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="💸 Списать бонусы")],
                    [KeyboardButton(text="🔙 Назад в меню")]
                ],
                resize_keyboard=True
            )
        )
    except Exception as e:
        logger.error(f"Balance error: {e}")
        await message.answer("⚠️ Ошибка получения баланса. Попробуйте позже.")

@user_router.message(F.text == "💸 Списать бонусы")
async def start_bonus_spend(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        balance = db.get_user_bonus_balance(user_id)
        if balance <= 0:
            await message.answer("❌ У вас нет бонусов для списания.")
            return

        await message.answer(
            f"💰 Ваш баланс: {balance} бонусов\n"
            "Введите количество бонусов для списания:",
            reply_markup=get_back_to_menu_keyboard()
        )
        await state.set_state(UserStates.bonus_spend)
    except Exception as e:
        logger.error(f"Bonus spend error: {e}")
        await message.answer("⚠️ Ошибка. Попробуйте позже.")

@user_router.message(UserStates.bonus_spend, F.text.regexp(r'^\d+$'))
async def process_bonus_spend(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        amount = int(message.text)
        balance = db.get_user_bonus_balance(user_id)

        if amount <= 0:
            await message.answer("❌ Введите положительное число.")
            return
        
        if amount > balance:
            await message.answer(f"❌ Недостаточно бонусов. Ваш баланс: {balance}")
            return

        if db.add_bonus_transaction(user_id, amount, 'subtract', 'Списание бонусов'):
            bonus_word = db.get_random_bonus_word()
            await message.answer(
                f"✅ Успешно списано {amount} бонусов.\n"
                f"Новый баланс: {balance - amount}\n\n"
                f"Для использования бонусов назовите кассиру кодовое слово:\n"
                f"🔑 <b>{bonus_word}</b>",
                reply_markup=get_user_menu()
            )
        else:
            await message.answer("⚠️ Ошибка списания бонусов. Попробуйте позже.")
        
        await state.clear()
    except Exception as e:
        logger.error(f"Process bonus error: {e}")
        await message.answer("⚠️ Ошибка обработки запроса. Попробуйте снова.")

@user_router.message(F.text == "📢 Пригласить друга")
async def invite_friend(message: Message):
    try:
        user_id = message.from_user.id
        bot_username = (await bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        
        await message.answer(
            "👥 <b>Пригласите друзей и получайте бонусы!</b>\n\n"
            f"Ваша реферальная ссылка:\n<code>{ref_link}</code>\n\n"
            f"За каждого приглашенного друга вы получите {BONUS_FOR_REFERRAL} бонусов "
            "после его регистрации и первого списания бонусов.",
            reply_markup=get_user_menu()
        )
    except Exception as e:
        logger.error(f"Invite error: {e}")
        await message.answer("⚠️ Ошибка генерации ссылки. Попробуйте позже.")

@user_router.message(F.text == "🎁 Акции и бонусы")
async def show_promotions(message: Message):
    try:
        promotions = db.get_active_promotions()
        if not promotions:
            await message.answer("ℹ️ Сейчас нет активных акций.", reply_markup=get_user_menu())
            return

        response = ["<b>🎁 Актуальные акции и бонусы:</b>"]
        for idx, (title, desc) in enumerate(promotions, 1):
            response.append(f"\n<b>{idx}. {title}</b>\n{desc}")
        
        await message.answer("\n".join(response), reply_markup=get_user_menu())
    except Exception as e:
        logger.error(f"Promotions error: {e}")
        await message.answer("⚠️ Ошибка загрузки акций. Попробуйте позже.")

@user_router.message(F.text == "🔙 Назад в меню")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню:", reply_markup=get_user_menu())

# --- Админские обработчики ---
@admin_router.message(Command("admin"))
async def admin_panel(message: Message):
    try:
        if message.from_user.id != ADMIN_ID:
            return
        await message.answer(
            "👨‍💻 <b>Панель администратора</b>\n\n"
            "Выберите действие:",
            reply_markup=get_admin_menu()
        )
    except Exception as e:
        logger.error(f"Admin panel error: {e}")
        await message.answer("⚠️ Ошибка загрузки панели.")

@admin_router.message(F.text == "📢 Добавить акцию")
async def add_promotion_start(message: Message, state: FSMContext):
    try:
        if message.from_user.id != ADMIN_ID:
            return
        await message.answer(
            "📝 Введите название новой акции:",
            reply_markup=get_back_to_menu_keyboard()
        )
        await state.set_state(AdminStates.add_promotion_title)
    except Exception as e:
        logger.error(f"Add promotion error: {e}")
        await message.answer("⚠️ Ошибка. Попробуйте позже.")

@admin_router.message(AdminStates.add_promotion_title)
async def process_promotion_title(message: Message, state: FSMContext):
    try:
        if len(message.text) < 5:
            await message.answer("❌ Название слишком короткое. Минимум 5 символов.")
            return

        await state.update_data(title=message.text)
        await message.answer(
            "📝 Теперь введите описание акции:",
            reply_markup=get_back_to_menu_keyboard()
        )
        await state.set_state(AdminStates.add_promotion_description)
    except Exception as e:
        logger.error(f"Promotion title error: {e}")
        await message.answer("⚠️ Ошибка обработки. Попробуйте снова.")

@admin_router.message(AdminStates.add_promotion_description)
async def process_promotion_description(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        title = data.get('title')
        description = message.text

        if db.add_promotion(title, description):
            await message.answer(
                f"✅ Акция <b>'{title}'</b> успешно добавлена!",
                reply_markup=get_admin_menu()
            )
        else:
            await message.answer("⚠️ Ошибка сохранения акции.", reply_markup=get_admin_menu())
        
        await state.clear()
    except Exception as e:
        logger.error(f"Promotion desc error: {e}")
        await message.answer("⚠️ Ошибка обработки. Попробуйте снова.")

@admin_router.message(F.text == "🗑️ Удалить акцию")
async def delete_promotion_start(message: Message, state: FSMContext):
    try:
        if message.from_user.id != ADMIN_ID:
            return
        promotions = db.get_all_promotions()
        if not promotions:
            await message.answer("ℹ️ Нет активных акций для удаления.")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for promo_id, title, _ in promotions:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"❌ {title}",
                    callback_data=f"delete_promo_{promo_id}"
                )
            ])

        await message.answer(
            "🗑 <b>Выберите акцию для удаления:</b>",
            reply_markup=keyboard
        )
        await state.set_state(AdminStates.delete_promotion)
    except Exception as e:
        logger.error(f"Delete promotion error: {e}")
        await message.answer("⚠️ Ошибка загрузки списка акций.")

@admin_router.callback_query(F.data.startswith("delete_promo_"), AdminStates.delete_promotion)
async def process_delete_promotion(callback: CallbackQuery, state: FSMContext):
    try:
        promo_id = int(callback.data.split('_')[2])
        if db.delete_promotion(promo_id):
            await callback.message.edit_text(
                "✅ Акция успешно удалена!",
                reply_markup=get_admin_menu()
            )
        else:
            await callback.answer("❌ Ошибка при удалении акции")
        
        await state.clear()
    except Exception as e:
        logger.error(f"Process delete promotion error: {e}")
        await callback.answer("⚠️ Ошибка обработки запроса.")

@admin_router.message(F.text == "👥 Управление пользователями")
async def manage_users_start(message: Message, state: FSMContext):
    try:
        if message.from_user.id != ADMIN_ID:
            return
        users = db.get_all_users()
        if not users:
            await message.answer("ℹ️ Нет зарегистрированных пользователей.")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for user_id, full_name, balance in users:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"{full_name} ({balance} б.)",
                    callback_data=f"manage_user_{user_id}"
                )
            ])

        await message.answer(
            "👥 <b>Список пользователей:</b>\n"
            "Выберите пользователя для управления:",
            reply_markup=keyboard
        )
        await state.set_state(AdminStates.manage_user_select)
    except Exception as e:
        logger.error(f"Manage users error: {e}")
        await message.answer("⚠️ Ошибка загрузки списка пользователей.")

@admin_router.callback_query(F.data.startswith("manage_user_"), AdminStates.manage_user_select)
async def manage_user_selected(callback: CallbackQuery, state: FSMContext):
    try:
        user_id = int(callback.data.split('_')[2])
        user = db.get_user(user_id)
        if not user:
            await callback.answer("❌ Пользователь не найден")
            return

        await state.update_data(managed_user_id=user_id)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Начислить бонусы", callback_data="user_action_add"),
                InlineKeyboardButton(text="➖ Списать бонусы", callback_data="user_action_subtract")
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="user_action_back")]
        ])

        await callback.message.edit_text(
            f"👤 <b>Управление пользователем:</b>\n"
            f"ID: {user_id}\n"
            f"Имя: {user[2]}\n"
            f"Дата рождения: {user[3]}\n"
            f"Баланс: {user[4]} бонусов\n\n"
            "Выберите действие:",
            reply_markup=keyboard
        )
        await state.set_state(AdminStates.manage_user_action)
    except Exception as e:
        logger.error(f"User select error: {e}")
        await callback.answer("⚠️ Ошибка. Попробуйте снова.")

@admin_router.callback_query(F.data == "user_action_back", AdminStates.manage_user_action)
async def back_to_users_list(callback: CallbackQuery, state: FSMContext):
    await manage_users_start(callback.message, state)

@admin_router.callback_query(F.data.startswith("user_action_"), AdminStates.manage_user_action)
async def process_user_action(callback: CallbackQuery, state: FSMContext):
    try:
        action = callback.data.split('_')[2]
        if action == 'back':
            return

        data = await state.get_data()
        user_id = data.get('managed_user_id')
        
        if action in ('add', 'subtract'):
            await state.update_data(user_action=action)
            await callback.message.edit_text(
                f"Введите количество бонусов для {'начисления' if action == 'add' else 'списания'}:\n"
                f"Текущий баланс пользователя: {db.get_user_bonus_balance(user_id)}"
            )
            await state.set_state(AdminStates.manage_user_action)
        else:
            await callback.answer("❌ Неизвестное действие")
    except Exception as e:
        logger.error(f"User action error: {e}")
        await callback.answer("⚠️ Ошибка. Попробуйте снова.")

@admin_router.message(AdminStates.manage_user_action, F.text.regexp(r'^\d+$'))
async def process_bonus_amount(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        user_id = data.get('managed_user_id')
        action = data.get('user_action')
        amount = int(message.text)
        
        if amount <= 0:
            await message.answer("❌ Введите положительное число.")
            return

        operation = 'add' if action == 'add' else 'subtract'
        description = f"Админ {'начислил' if action == 'add' else 'списал'} бонусы"
        
        if db.add_bonus_transaction(user_id, amount, operation, description):
            await message.answer(
                f"✅ Успешно {'начислено' if action == 'add' else 'списано'} {amount} бонусов.\n"
                f"Новый баланс пользователя: {db.get_user_bonus_balance(user_id)}",
                reply_markup=get_admin_menu()
            )
        else:
            await message.answer("⚠️ Ошибка операции с бонусами.", reply_markup=get_admin_menu())
        
        await state.clear()
    except Exception as e:
        logger.error(f"Bonus amount error: {e}")
        await message.answer("⚠️ Ошибка обработки. Попробуйте снова.")

@admin_router.message(F.text == "📩 Рассылка")
async def start_broadcast(message: Message, state: FSMContext):
    try:
        if message.from_user.id != ADMIN_ID:
            return
        await message.answer(
            "✉️ <b>Создание рассылки</b>\n\n"
            "Введите сообщение для рассылки всем пользователям:",
            reply_markup=get_back_to_menu_keyboard()
        )
        await state.set_state(AdminStates.broadcast_message)
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        await message.answer("⚠️ Ошибка. Попробуйте позже.")

@admin_router.message(AdminStates.broadcast_message)
async def process_broadcast(message: Message, state: FSMContext):
    try:
        users = db.get_all_users()
        success = 0
        failed = 0
        
        for user in users:
            try:
                await bot.send_message(user[0], message.text)
                success += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.1)  # Задержка для избежания лимитов Telegram
        
        await message.answer(
            f"📊 <b>Результаты рассылки:</b>\n"
            f"• Успешно: {success}\n"
            f"• Не доставлено: {failed}",
            reply_markup=get_admin_menu()
        )
        await state.clear()
    except Exception as e:
        logger.error(f"Process broadcast error: {e}")
        await message.answer("⚠️ Ошибка рассылки. Попробуйте позже.")

@admin_router.message(F.text == "🔑 Бонусные слова")
async def manage_bonus_words(message: Message):
    try:
        if message.from_user.id != ADMIN_ID:
            return
        words = db.get_all_bonus_words()
        
        if not words:
            await message.answer("ℹ️ Нет сохраненных бонусных слов.", reply_markup=get_admin_menu())
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Добавить", callback_data="add_bonus_word"),
                InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_bonus_word"),
                InlineKeyboardButton(text="🗑️ Удалить", callback_data="delete_bonus_word")
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]
        ])
        
        words_list = "\n".join([f"{idx}. {word} (ID: {id})" for idx, (id, word) in enumerate(words, 1)])
        await message.answer(
            f"🔑 Текущие бонусные слова:\n{words_list}\n\n"
            "Выберите действие:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Manage bonus words error: {e}")
        await message.answer("⚠️ Ошибка загрузки бонусных слов.")

@admin_router.callback_query(F.data == "add_bonus_word")
async def add_bonus_word_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "✏️ Введите новое бонусное слово:",
        reply_markup=get_back_to_menu_keyboard()
    )
    await state.set_state(AdminStates.add_bonus_word)
    await callback.answer()

@admin_router.message(AdminStates.add_bonus_word)
async def process_add_bonus_word(message: Message, state: FSMContext):
    word = message.text.strip()
    
    if not word.isalpha():
        await message.answer("❌ Бонусное слово должно содержать только буквы. Попробуйте еще раз:")
        return
    
    if len(word) < 3:
        await message.answer("❌ Слишком короткое слово. Минимум 3 символа.")
        return
    
    if db.add_bonus_word(word):
        await message.answer(f"✅ Слово '{word.upper()}' успешно добавлено!", reply_markup=get_admin_menu())
    else:
        await message.answer(f"❌ Слово '{word.upper()}' уже существует!", reply_markup=get_admin_menu())
    
    await state.clear()

@admin_router.callback_query(F.data == "edit_bonus_word")
async def edit_bonus_word_start(callback: CallbackQuery, state: FSMContext):
    words = db.get_all_bonus_words()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✏️ {word}", callback_data=f"edit_word_{id}")]
        for id, word in words
    ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_edit")])
    
    await callback.message.edit_text(
        "Выберите слово для редактирования:",
        reply_markup=keyboard
    )
    await state.set_state(AdminStates.edit_bonus_word_select)
    await callback.answer()

@admin_router.callback_query(AdminStates.edit_bonus_word_select, F.data.startswith("edit_word_"))
async def select_word_to_edit(callback: CallbackQuery, state: FSMContext):
    word_id = int(callback.data.split('_')[2])
    await state.update_data(word_id=word_id)
    
    await callback.message.answer(
        "Введите новое значение для этого слова:",
        reply_markup=get_back_to_menu_keyboard()
    )
    await state.set_state(AdminStates.edit_bonus_word_new)
    await callback.answer()

@admin_router.message(AdminStates.edit_bonus_word_new)
async def process_edit_bonus_word(message: Message, state: FSMContext):
    data = await state.get_data()
    word_id = data.get('word_id')
    new_word = message.text.strip()
    
    if not new_word.isalpha():
        await message.answer("❌ Бонусное слово должно содержать только буквы. Попробуйте еще раз:")
        return
    
    if len(new_word) < 3:
        await message.answer("❌ Слишком короткое слово. Минимум 3 символа.")
        return
    
    if db.update_bonus_word(word_id, new_word):
        await message.answer(f"✅ Слово успешно изменено на '{new_word.upper()}'!", reply_markup=get_admin_menu())
    else:
        await message.answer("❌ Ошибка при изменении слова.", reply_markup=get_admin_menu())
    
    await state.clear()

@admin_router.callback_query(F.data == "delete_bonus_word")
async def delete_bonus_word_start(callback: CallbackQuery, state: FSMContext):
    words = db.get_all_bonus_words()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {word}", callback_data=f"del_word_{id}")]
        for id, word in words
    ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_delete")])
    
    await callback.message.edit_text(
        "Выберите слово для удаления:",
        reply_markup=keyboard
    )
    await state.set_state(AdminStates.delete_bonus_word)
    await callback.answer()

@admin_router.callback_query(AdminStates.delete_bonus_word, F.data.startswith("del_word_"))
async def process_delete_bonus_word(callback: CallbackQuery, state: FSMContext):
    word_id = int(callback.data.split('_')[2])
    
    if db.delete_bonus_word(word_id):
        await callback.message.edit_text("✅ Слово успешно удалено!")
    else:
        await callback.message.edit_text("❌ Ошибка при удалении слова")
    
    await state.clear()

@admin_router.callback_query(F.data.in_(["cancel_edit", "cancel_delete", "back_to_admin"]))
async def cancel_actions(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await admin_panel(callback.message)

@admin_router.message(F.text == "🔙 Выйти из админки")
async def exit_admin_panel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вышли из админ-панели.", reply_markup=get_user_menu())

# --- Обработчики ошибок ---
@dp.errors()
async def errors_handler(event, exception):
    if isinstance(exception, TelegramForbiddenError):
        logger.warning(f"User blocked bot: {event}")
        return True
    
    logger.error(f"Exception: {exception}", exc_info=True)
    return True

# --- Настройка роутеров ---
def setup_routers():
    admin_router.message.filter(IsAdmin())
    user_router.message.filter(~IsAdmin())
    
    dp.include_router(admin_router)
    dp.include_router(user_router)

# --- Запуск планировщика ---
def schedule_jobs():
    hour, minute = map(int, CHECK_BIRTHDAYS_TIME.split(':'))
    scheduler.add_job(
        check_birthdays,
        'cron',
        hour=hour,
        minute=minute,
        timezone='UTC'
    )
    scheduler.start()

# --- Запуск бота ---
async def on_startup():
    logger.info("Bot started")
    await bot.send_message(ADMIN_ID, "🤖 Бот запущен!")
    schedule_jobs()

async def on_shutdown():
    logger.info("Bot stopped")
    scheduler.shutdown()
    await bot.send_message(ADMIN_ID, "🛑 Бот остановлен!")
    db.close()

async def main():
    setup_routers()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

# В самом конце файла вместо всего блока запуска:
if __name__ == "__main__":
    import os
    
    setup_routers()
    
    async def main():
        await on_startup()
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)
        except Exception as e:
            logger.error(f"Polling error: {e}")
        finally:
            await on_shutdown()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")

