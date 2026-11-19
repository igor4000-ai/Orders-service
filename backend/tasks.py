"""
Celery-задачи проекта (продвинутая часть, Этап 7 диплома).

«Медленные» операции — отправка писем и импорт прайса по сети — вынесены
в задачи Celery, чтобы HTTP-запросы API не ждали их завершения.

Задачи:
* send_email(email, subject, message, ...) — универсальная отправка письма;
* do_import(url, user_id)                   — загрузка прайса по ссылке.

Функция run_task() — обёртка над задачами: если Celery включена
(настройка USE_CELERY=True, например в docker-compose), задача отправляется
воркеру через брокер, иначе выполняется синхронно. Благодаря этому проект
работает и с воркером, и без него (при обычном локальном запуске).
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from requests import get

from backend.importer import ImportValidationError, import_goods, parse_yaml_price_list

logger = logging.getLogger(__name__)


@shared_task
def send_email(
    email: str,
    subject: str,
    message: str,
    html_message: str = None,
    from_email: str = None,
) -> str:
    """
    Отправляет письмо на указанный адрес.

    Выделена в задачу Celery, потому что SMTP-обмен может занимать секунды —
    API не должен ждать завершения отправки.

    :param email: адрес получателя
    :param subject: тема письма
    :param message: текст письма
    :param html_message: необязательная HTML-версия письма
    :param from_email: адрес отправителя (по умолчанию DEFAULT_FROM_EMAIL)
    :return: адрес получателя — удобно для логирования/отладки
    """
    msg = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=[email],
    )
    if html_message:
        msg.attach_alternative(html_message, 'text/html')
    msg.send()
    logger.info('Отправлено письмо на %s: «%s»', email, subject)
    return email


@shared_task(bind=True)
def do_import(self, url: str, user_id: int = None) -> str:
    """
    Загружает прайс магазина из YAML-файла по ссылке и обновляет каталог.

    Выполняется в фоне (воркером Celery), т.к. включает скачивание файла
    по сети и запись большого объёма товаров в БД.

    Запускается:
    * эндпоинтом POST /api/v1/partner/update (поставщик обновляет прайс);
    * из админки Django (кнопка «Импортировать прайс» на странице магазина);
    * management-командой load_yaml --url <ссылка>.

    :param url: ссылка на YAML-файл прайса
    :param user_id: id пользователя-поставщика (не обязателен)
    :return: имя магазина, для которого загружен прайс
    """
    logger.info('Задача %s: импорт прайса из %s', self.request.id, url)

    response = get(url)
    response.raise_for_status()  # ошибка сети/404 упадёт в лог воркера

    data = parse_yaml_price_list(response.content)
    shop = import_goods(data, shop_user_id=user_id)

    logger.info('Задача %s выполнена: магазин %s', self.request.id, shop.name)
    return shop.name


def run_task(task, *args, **kwargs):
    """
    Запускает задачу Celery с учётом настроек проекта.

    USE_CELERY=True  -> task.delay(...)  (асинхронно, через брокер)
    USE_CELERY=False -> task(...)        (синхронно, без брокера)

    Используется из views/signals: один и тот же код работает
    и в окружении с воркером, и при локальном запуске без Redis.
    """
    if getattr(settings, 'USE_CELERY', False):
        return task.delay(*args, **kwargs)
    return task(*args, **kwargs)
