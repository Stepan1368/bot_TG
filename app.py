from flask import Flask, request
import asyncio
import threading
from bot import main as bot_main

app = Flask(__name__)

# Запускаем бота в отдельном потоке
def run_bot():
    asyncio.run(bot_main())

@app.route('/')
def home():
    return "Bot is running"

@app.route('/health')
def health():
    return "OK"

if __name__ == '__main__':
    # Запускаем бота в фоне
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask сервер
    app.run(host='0.0.0.0', port=10000)
