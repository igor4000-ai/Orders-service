# Импортируем приложение Celery, чтобы декоратор @shared_task
# был доступен сразу при старте Django-проекта.
from .celery import app as celery_app

__all__ = ('celery_app',)
