"""
Management-команда создания демонстрационных данных.

Создаёт:
* суперпользователя (доступ к админке Django);
* пользователя-поставщика «Связной» (тип shop);
* покупателя (тип buyer).

Пароли по умолчанию — демонстрационные. В реальном окружении задайте
собственные значения через аргументы команды.

Запуск:
    python manage.py create_demo_data
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from backend.models import Shop

User = get_user_model()

# Демонстрационные учётные данные (задокументированы в README)
DEMO_ADMIN = {'email': 'admin@example.com', 'password': 'admin'}
DEMO_SUPPLIER = {'email': 'svyaznoy@example.com', 'password': 'supplier123'}
DEMO_BUYER = {'email': 'buyer@example.com', 'password': 'buyer123'}


class Command(BaseCommand):
    help = 'Создание демонстрационных пользователей (админ, поставщик, покупатель)'

    def handle(self, *args, **options):
        # 1. Администратор — доступ к админке Django
        admin, created = User.objects.get_or_create(
            email=DEMO_ADMIN['email'],
            defaults={
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
                'first_name': 'Администратор',
                'last_name': 'Сервиса',
            },
        )
        if created:
            admin.set_password(DEMO_ADMIN['password'])
            admin.save()
        self.stdout.write(
            f'Администратор: {DEMO_ADMIN["email"]} '
            f'(пароль: {DEMO_ADMIN["password"] if created else "не изменён"})'
        )

        # 2. Поставщик — владелец магазина «Связной»
        supplier, created = User.objects.get_or_create(
            email=DEMO_SUPPLIER['email'],
            defaults={
                'type': 'shop',
                'is_active': True,
                'first_name': 'Сергей',
                'last_name': 'Поставкин',
                'company': 'Связной',
                'position': 'Менеджер по прайсам',
            },
        )
        if created:
            supplier.set_password(DEMO_SUPPLIER['password'])
            supplier.save()
        self.stdout.write(
            f'Поставщик: {DEMO_SUPPLIER["email"]} '
            f'(пароль: {DEMO_SUPPLIER["password"] if created else "не изменён"})'
        )

        # 3. Покупатель
        buyer, created = User.objects.get_or_create(
            email=DEMO_BUYER['email'],
            defaults={
                'type': 'buyer',
                'is_active': True,
                'first_name': 'Иван',
                'last_name': 'Покупателев',
            },
        )
        if created:
            buyer.set_password(DEMO_BUYER['password'])
            buyer.save()
        self.stdout.write(
            f'Покупатель: {DEMO_BUYER["email"]} '
            f'(пароль: {DEMO_BUYER["password"] if created else "не изменён"})'
        )

        # 4. Привязываем магазин «Связной» (если загружен) к поставщику
        # и задаём ссылку на прайс для импорта из админки
        shop = Shop.objects.filter(name='Связной').first()
        if shop:
            shop.user = supplier
            shop.url = (
                'https://raw.githubusercontent.com/netology-code/'
                'python-final-diplom/master/data/shop1.yaml'
            )
            shop.save()
            self.stdout.write(f'Магазин «Связной» привязан к поставщику, url прайса задан')

        self.stdout.write(self.style.SUCCESS('Демонстрационные данные готовы'))
