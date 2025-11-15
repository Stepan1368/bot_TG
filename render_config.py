import os

# Конфигурация для Render
RENDER = os.environ.get('RENDER', 'false').lower() == 'true'
PORT = int(os.environ.get('PORT', 10000))
