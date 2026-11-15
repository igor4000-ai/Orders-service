"""
Приложение Celery проекта «orders».

Здесь создаётся инстанс Celery, подключается брокер сообщений и
автоматически регистрируются задачи из всех приложений Django
(наши задачи описаны в backend/tasks.py: send_email и do_import).
"""

import os

from celery import Celery

# Настройки Django читаются из переменной окружения DJANGO_SETTINGS_MODULE,
# чтобы воркер Celery работал с теми же настройками, что и веб-приложение
# (это позволяет менять параметры через docker-compose без правки кода).
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'orders.settings')

app = Celery('orders')

# Все настройки с префиксом CELERY_ берутся из settings.py проекта
app.config_from_object('django.conf:settings', namespace='CELERY')

# Автоматически обнаруживать tasks.py во всех установленных приложениях
app.autodiscover_tasks()
