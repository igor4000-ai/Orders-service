"""
Сигналы приложения: email-уведомления о событиях сервиса.

Реализованы письма:
1. Подтверждение регистрации — одноразовый токен на email нового пользователя;
2. Подтверждение заказа покупателю + накладная администратору сервиса
   (для исполнения заказа);
3. Уведомление об изменении статуса заказа (вызывается из админки).

Все письма уходят через Celery-задачу send_email (см. backend/tasks.py):
при включённом воркере — в фоне, иначе — синхронно.
"""

import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import Signal, receiver
from django_rest_passwordreset.signals import reset_password_token_created

from backend.models import ConfirmEmailToken, Order, User
from backend.tasks import run_task, send_email

logger = logging.getLogger(__name__)

# Пользовательский сигнал: заказ оформлен (отправляется из OrderView)
new_order = Signal()


def order_text_description(order: Order) -> str:
    """
    Человекочитаемое описание заказа для писем: позиции, магазины,
    количество, цены, итоговая сумма и адрес доставки.
    """
    lines = [f'Заказ №{order.id} от {order.dt:%d.%m.%Y %H:%M}', '']
    total = 0
    for item in order.ordered_items.select_related(
        'product_info__product', 'product_info__shop'
    ):
        info = item.product_info
        position_sum = item.quantity * info.price
        total += position_sum
        lines.append(
            f'• {info.product.name} ({info.model}) — '
            f'магазин «{info.shop.name}», '
            f'{item.quantity} шт. × {info.price} руб. = {position_sum} руб.'
        )
    lines.append('')
    lines.append(f'Итого: {total} руб.')
    if order.contact:
        contact = order.contact
        lines.append(
            'Адрес доставки: '
            f'{contact.city}, ул. {contact.street}, д. {contact.house}'
            f'{" (корпус " + contact.structure + ")" if contact.structure else ""}'
            f'{" (стр. " + contact.building + ")" if contact.building else ""}'
            f'{" (кв. " + contact.apartment + ")" if contact.apartment else ""}'
            f', тел. {contact.phone}'
        )
    return '\n'.join(lines)


@receiver(reset_password_token_created)
def password_reset_token_created(sender, instance, reset_password_token, **kwargs):
    """
    Письмо со ссылкой/токеном сброса пароля (django-rest-passwordreset).
    """
    run_task(
        send_email,
        email=reset_password_token.user.email,
        subject=f'Восстановление пароля для {reset_password_token.user.email}',
        message=(
            f'Вы запросили восстановление пароля.\n\n'
            f'Токен для сброса пароля: {reset_password_token.key}\n\n'
            f'Подтвердите сброс запросом POST /api/v1/user/password_reset/confirm\n'
            f'с полями email, password и token.\n\n'
            f'Если вы не запрашивали восстановление — просто проигнорируйте письмо.'
        ),
    )


@receiver(post_save, sender=User)
def new_user_registered_signal(sender, instance: User, created: bool, **kwargs):
    """
    После регистрации создаём токен подтверждения email и отправляем письмо.

    Обрабатываются только новые неактивные пользователи: тех, кого создали
    вручную активными (например, суперпользователя), письмо не беспокоит.
    """
    if created and not instance.is_active:
        token, _ = ConfirmEmailToken.objects.get_or_create(user_id=instance.pk)
        run_task(
            send_email,
            email=instance.email,
            subject=f'Подтверждение регистрации на {instance.email}',
            message=(
                f'Здравствуйте, {instance.first_name or "уважаемый пользователь"}!\n\n'
                f'Вы зарегистрировались в сервисе автоматизации закупок.\n'
                f'Для подтверждения email отправьте POST-запрос на\n'
                f'/api/v1/user/register/confirm с полями:\n\n'
                f'  email: {instance.email}\n'
                f'  token: {token.key}\n\n'
                f'После подтверждения вы сможете войти в сервис.'
            ),
        )


@receiver(new_order)
def new_order_signal(sender, user_id: int, order_id: int, **kwargs):
    """
    Заказ подтверждён покупателем:
    * покупателю — письмо-подтверждение приёма заказа;
    * администратору сервиса (ADMIN_EMAIL) — накладная для исполнения заказа.
    """
    order = (
        Order.objects.filter(id=order_id)
        .select_related('user', 'contact')
        .prefetch_related('ordered_items__product_info__product__category')
        .first()
    )
    if order is None:
        logger.warning('Сигнал new_order: заказ %s не найден', order_id)
        return

    description = order_text_description(order)

    # 1. Подтверждение приёма заказа покупателю
    run_task(
        send_email,
        email=order.user.email,
        subject=f'Заказ №{order.id} принят',
        message=(
            f'Здравствуйте, {order.user.first_name or "уважаемый пользователь"}!\n\n'
            f'Ваш заказ принят в обработку.\n\n{description}\n\n'
            f'Статус заказа: {order.get_state_display()}.\n'
            f'О любых изменениях статуса мы сообщим дополнительным письмом.'
        ),
    )

    # 2. Накладная администратору — для исполнения заказа
    admin_email = getattr(settings, 'ADMIN_EMAIL', '')
    if admin_email:
        run_task(
            send_email,
            email=admin_email,
            subject=f'Накладная: заказ №{order.id} ({order.user.email})',
            message=(
                f'Новый заказ, требует исполнения.\n\n{description}\n\n'
                f'Покупатель: {order.user.get_full_name() or order.user.email}'
            ),
        )
    else:
        logger.info('ADMIN_EMAIL не задан — накладная администратору не отправлена')


def send_order_state_notification(order: Order) -> None:
    """
    Уведомление покупателю об изменении статуса заказа.

    Вызывается из админки Django (backend/admin.py) при сохранении заказа
    с новым статусом.
    """
    run_task(
        send_email,
        email=order.user.email,
        subject=f'Статус заказа №{order.id} изменён',
        message=(
            f'Здравствуйте, {order.user.first_name or "уважаемый пользователь"}!\n\n'
            f'Статус вашего заказа №{order.id} изменён на «{order.get_state_display()}».\n\n'
            f'{order_text_description(order)}'
        ),
    )
