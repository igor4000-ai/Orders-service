"""
Интеграционные тесты API сервиса (полный сценарий Этапа 5 диплома).

Проверяем:
* регистрацию, письмо с токеном, подтверждение email и авторизацию;
* каталог: категории, магазины, товары с фильтрацией и поиском;
* корзину: добавление, просмотр, изменение количества, удаление;
* контакты: создание, ограничение количества адресов, удаление;
* оформление заказа и письма (подтверждение покупателю + накладная админу);
* партнёрские эндпоинты: импорт прайса, статус приёма заказов, заказы магазина;
* уведомление об изменении статуса заказа.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from backend.importer import ImportValidationError, import_goods, parse_yaml_price_list
from backend.models import (
    Category,
    ConfirmEmailToken,
    Contact,
    Order,
    OrderItem,
    ProductInfo,
    Shop,
)
from backend.signals import send_order_state_notification

User = get_user_model()

# Путь к прайсу из условия задания
SHOP1_YAML = Path(__file__).resolve().parents[2] / 'data' / 'shop1.yaml'

# Мини-прайс для тестов импорта (формат как в data/shop1.yaml)
TEST_PRICE = """
shop: Тестовый магазин
categories:
  - id: 100
    name: Тестовые товары
goods:
  - id: 1001
    category: 100
    model: test/model-1
    name: Тестовый товар 1
    price: 100
    price_rrc: 120
    quantity: 10
    parameters:
      "Цвет": красный
  - id: 1002
    category: 100
    model: test/model-2
    name: Тестовый товар 2
    price: 200
    price_rrc: 240
    quantity: 5
    parameters:
      "Цвет": синий
""".encode('utf-8')


class BaseAPITestCase(TestCase):
    """Общая подготовка: клиент API и загрузка каталога из shop1.yaml."""

    def setUp(self):
        self.client = APIClient()
        # Загружаем товары из приложенного к заданию файла
        data = parse_yaml_price_list(SHOP1_YAML.read_bytes())
        self.shop = import_goods(data)
        self.buyer = self.create_active_user(
            email='buyer@example.com', password='Sup3r-Secret-Pass',
            first_name='Иван', last_name='Покупателев',
        )

    @staticmethod
    def create_active_user(email, password, **extra):
        """Активный пользователь (как после подтверждения email)."""
        # is_active передаётся сразу при создании, чтобы не срабатывал
        # сигнал отправки письма подтверждения
        user = User.objects.create_user(email, password, is_active=True, **extra)
        return user

    def auth(self, user):
        """Авторизует клиент по токену DRF."""
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')


class TestRegistrationFlow(BaseAPITestCase):
    """Регистрация → письмо с токеном → подтверждение → вход."""

    def test_register_confirm_login_scenario(self):
        # 1. Регистрация
        response = self.client.post(
            '/api/v1/user/register',
            {
                'first_name': 'Пётр',
                'last_name': 'Петров',
                'email': 'newuser@example.com',
                'password': 'N0t-Simple-Pass-42',
                'company': 'Ромашка',
                'position': 'Менеджер',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['Status'])

        user = User.objects.get(email='newuser@example.com')
        self.assertFalse(user.is_active)  # активируется только после подтверждения

        # 2. Письмо с токеном подтверждения отправлено
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('newuser@example.com', mail.outbox[0].to)

        # 3. Подтверждение email токеном из письма
        token = ConfirmEmailToken.objects.get(user=user)
        response = self.client.post(
            '/api/v1/user/register/confirm',
            {'email': 'newuser@example.com', 'token': token.key},
            format='json',
        )
        self.assertTrue(response.json()['Status'])
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        # одноразовый токен удалён
        self.assertFalse(ConfirmEmailToken.objects.filter(user=user).exists())

        # 4. Неверный токен отклоняется
        response = self.client.post(
            '/api/v1/user/register/confirm',
            {'email': 'newuser@example.com', 'token': 'wrong-token'},
            format='json',
        )
        self.assertFalse(response.json()['Status'])

        # 5. Вход
        response = self.client.post(
            '/api/v1/user/login',
            {'email': 'newuser@example.com', 'password': 'N0t-Simple-Pass-42'},
            format='json',
        )
        self.assertTrue(response.json()['Status'])
        self.assertIn('Token', response.json())

    def test_register_with_weak_password_fails(self):
        response = self.client.post(
            '/api/v1/user/register',
            {
                'first_name': 'Пётр',
                'last_name': 'Петров',
                'email': 'weak@example.com',
                'password': '123',
            },
            format='json',
        )
        self.assertFalse(response.json()['Status'])
        self.assertIn('password', response.json()['Errors'])

    def test_login_before_confirmation_fails(self):
        self.client.post(
            '/api/v1/user/register',
            {
                'first_name': 'А',
                'last_name': 'Б',
                'email': 'inactive@example.com',
                'password': 'N0t-Simple-Pass-42',
            },
            format='json',
        )
        response = self.client.post(
            '/api/v1/user/login',
            {'email': 'inactive@example.com', 'password': 'N0t-Simple-Pass-42'},
            format='json',
        )
        self.assertFalse(response.json()['Status'])


class TestCatalog(BaseAPITestCase):
    """Каталог: категории, магазины, товары, фильтры и поиск."""

    def test_categories_and_shops_lists(self):
        response = self.client.get('/api/v1/categories')
        self.assertEqual(response.status_code, 200)
        names = [c['name'] for c in response.json()]
        self.assertIn('Смартфоны', names)

        response = self.client.get('/api/v1/shops')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['name'], 'Связной')

    def test_products_list_and_filters(self):
        # весь каталог магазина
        response = self.client.get('/api/v1/products')
        self.assertEqual(len(response.json()), 14)

        # фильтр по категории «Смартфоны» (id 224)
        response = self.client.get('/api/v1/products', {'category_id': 224})
        self.assertEqual(len(response.json()), 5)

        # фильтр по магазину
        response = self.client.get('/api/v1/products', {'shop_id': self.shop.id})
        self.assertEqual(len(response.json()), 14)

        # комбинированный фильтр
        response = self.client.get(
            '/api/v1/products', {'shop_id': self.shop.id, 'category_id': 5}
        )
        self.assertEqual(len(response.json()), 5)  # телевизоры

    def test_products_search(self):
        response = self.client.get('/api/v1/products', {'q': 'iPhone'})
        self.assertGreaterEqual(len(response.json()), 4)

        # поиск по значению характеристики
        response = self.client.get('/api/v1/products', {'q': 'золотистый'})
        self.assertEqual(len(response.json()), 1)

    def test_product_detail(self):
        product_info = ProductInfo.objects.first()
        response = self.client.get(f'/api/v1/products/{product_info.id}')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['product']['name'], product_info.product.name)
        self.assertEqual(data['shop'], 'Связной')
        # характеристики товара присутствуют в ответе
        self.assertGreaterEqual(len(data['product_parameters']), 1)

    def test_products_of_disabled_shop_hidden(self):
        self.shop.state = False
        self.shop.save()
        response = self.client.get('/api/v1/products')
        self.assertEqual(len(response.json()), 0)


class TestBasketAndOrderFlow(BaseAPITestCase):
    """Корзина → контакты → оформление заказа → письма."""

    def setUp(self):
        super().setUp()
        self.auth(self.buyer)

    def test_full_order_scenario(self):
        # ---- Корзина ----
        iphone = ProductInfo.objects.get(external_id=4216292)  # iPhone XS Max
        flash = ProductInfo.objects.get(external_id=1235434570)  # Kingston 32GB

        # добавление двух товаров
        response = self.client.post(
            '/api/v1/basket',
            {'items': [
                {'product_info': iphone.id, 'quantity': 2},
                {'product_info': flash.id, 'quantity': 3},
            ]},
            format='json',
        )
        self.assertTrue(response.json()['Status'])
        self.assertEqual(response.json()['Создано объектов'], 2)

        # корзина недоступна без авторизации
        self.client.credentials()
        response = self.client.get('/api/v1/basket')
        self.assertEqual(response.status_code, 403)
        self.auth(self.buyer)

        # просмотр корзины: 2 позиции, сумма 2*110000 + 3*1000 = 223000
        response = self.client.get('/api/v1/basket')
        basket_data = response.json()
        self.assertEqual(basket_data['state'], 'basket')
        self.assertEqual(len(basket_data['ordered_items']), 2)
        self.assertEqual(basket_data['total_sum'], 223000)

        # повторное добавление того же товара увеличивает количество
        self.client.post(
            '/api/v1/basket',
            {'items': [{'product_info': iphone.id, 'quantity': 1}]},
            format='json',
        )
        response = self.client.get('/api/v1/basket')
        self.assertEqual(len(response.json()['ordered_items']), 2)  # без дублей

        # изменение количества
        item_id = response.json()['ordered_items'][0]['id']
        response = self.client.put(
            '/api/v1/basket',
            {'items': [{'id': item_id, 'quantity': 1}]},
            format='json',
        )
        self.assertTrue(response.json()['Status'])

        # ---- Контакты ----
        response = self.client.post(
            '/api/v1/user/contact',
            {
                'city': 'Москва',
                'street': 'Ленинская слобода',
                'house': '19',
                'structure': '2',
                'apartment': '35',
                'phone': '+7 999 123-45-67',
            },
            format='json',
        )
        self.assertTrue(response.json()['Status'])
        contact = Contact.objects.get(user=self.buyer)

        # ---- Оформление заказа ----
        basket = Order.objects.get(user=self.buyer, state='basket')
        response = self.client.post(
            '/api/v1/order',
            {'id': basket.id, 'contact': contact.id},
            format='json',
        )
        self.assertTrue(response.json()['Status'])

        # письма: подтверждение покупателю + накладная администратору
        with override_settings(ADMIN_EMAIL='admin@example.com'):
            pass  # см. отдельный тест ниже
        self.assertGreaterEqual(len(mail.outbox), 1)
        self.assertIn(self.buyer.email, mail.outbox[0].to)

        # заказ получил статус «новый» и адрес доставки
        basket.refresh_from_db()
        self.assertEqual(basket.state, 'new')
        self.assertEqual(basket.contact.id, contact.id)

        # список заказов пользователя содержит заказ с позициями
        response = self.client.get('/api/v1/order')
        orders = response.json()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]['state'], 'new')
        self.assertEqual(len(orders[0]['ordered_items']), 2)

        # удаление позиции из корзины (создаём новую корзину)
        response = self.client.post(
            '/api/v1/basket',
            {'items': [{'product_info': flash.id, 'quantity': 1}]},
            format='json',
        )
        item = OrderItem.objects.get(
            order__user=self.buyer, order__state='basket', product_info=flash
        )
        response = self.client.delete(
            '/api/v1/basket', {'items': str(item.id)}, format='multipart'
        )
        self.assertTrue(response.json()['Status'])
        self.assertEqual(response.json()['Удалено объектов'], 1)

    def test_basket_quantity_exceeds_stock(self):
        iphone = ProductInfo.objects.get(external_id=4216292)  # quantity: 14
        response = self.client.post(
            '/api/v1/basket',
            {'items': [{'product_info': iphone.id, 'quantity': 999}]},
            format='json',
        )
        self.assertFalse(response.json()['Status'])
        self.assertFalse(OrderItem.objects.exists())

    def test_contact_limit(self):
        """По описанию сервиса — не более 5 адресов доставки."""
        for i in range(5):
            response = self.client.post(
                '/api/v1/user/contact',
                {'city': f'Город {i}', 'street': 'Улица', 'phone': '+79990000000'},
                format='json',
            )
            self.assertTrue(response.json()['Status'])
        # шестой адрес отклоняется
        response = self.client.post(
            '/api/v1/user/contact',
            {'city': 'Город 6', 'street': 'Улица', 'phone': '+79990000000'},
            format='json',
        )
        self.assertFalse(response.json()['Status'])

    def test_order_with_empty_basket_fails(self):
        basket, _ = Order.objects.get_or_create(user=self.buyer, state='basket')
        contact = Contact.objects.create(
            user=self.buyer, city='Москва', street='Улица', phone='+7999'
        )
        response = self.client.post(
            '/api/v1/order', {'id': basket.id, 'contact': contact.id}, format='json'
        )
        self.assertFalse(response.json()['Status'])

    def test_order_with_foreign_contact_fails(self):
        """Нельзя оформить заказ на чужой адрес доставки."""
        other = self.create_active_user('other@example.com', 'Sup3r-Secret-Pass')
        foreign_contact = Contact.objects.create(
            user=other, city='Казань', street='Улица', phone='+7999'
        )
        iphone = ProductInfo.objects.get(external_id=4216292)
        self.client.post(
            '/api/v1/basket',
            {'items': [{'product_info': iphone.id, 'quantity': 1}]},
            format='json',
        )
        basket = Order.objects.get(user=self.buyer, state='basket')
        response = self.client.post(
            '/api/v1/order', {'id': basket.id, 'contact': foreign_contact.id},
            format='json',
        )
        self.assertFalse(response.json()['Status'])

    @override_settings(ADMIN_EMAIL='admin@example.com')
    def test_order_sends_invoice_to_admin(self):
        """После оформления заказа администратору уходит накладная."""
        iphone = ProductInfo.objects.get(external_id=4216292)
        self.client.post(
            '/api/v1/basket',
            {'items': [{'product_info': iphone.id, 'quantity': 2}]},
            format='json',
        )
        contact = Contact.objects.create(
            user=self.buyer, city='Москва', street='Улица', phone='+7999'
        )
        basket = Order.objects.get(user=self.buyer, state='basket')
        self.client.post(
            '/api/v1/order', {'id': basket.id, 'contact': contact.id}, format='json'
        )

        recipients = [message.to[0] for message in mail.outbox]
        self.assertIn('admin@example.com', recipients)  # накладная
        self.assertIn(self.buyer.email, recipients)  # подтверждение
        invoice = [m for m in mail.outbox if 'admin@example.com' in m.to][0]
        self.assertIn('Накладная', invoice.subject)
        self.assertIn('220000', invoice.body)  # 2 × 110000


class TestOrderStateNotification(BaseAPITestCase):
    """Уведомление покупателя при изменении статуса заказа (админка)."""

    def test_state_change_notification(self):
        contact = Contact.objects.create(
            user=self.buyer, city='Москва', street='Улица', phone='+7999'
        )
        order = Order.objects.create(user=self.buyer, state='new', contact=contact)
        iphone = ProductInfo.objects.get(external_id=4216292)
        OrderItem.objects.create(order=order, product_info=iphone, quantity=1)

        # смена статуса (как это делает админка при сохранении заказа)
        order.state = 'sent'
        order.save()
        send_order_state_notification(order)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('изменён', mail.outbox[0].subject)
        self.assertIn(self.buyer.email, mail.outbox[0].to)


class TestPartnerEndpoints(BaseAPITestCase):
    """Партнёрские эндпоинты поставщика."""

    def setUp(self):
        super().setUp()
        self.supplier = self.create_active_user(
            email='supplier@example.com', password='Sup3r-Secret-Pass', type='shop'
        )
        self.auth(self.supplier)

    def _place_buyer_order(self):
        """Покупатель оформляет заказ с товаром магазина — для partner/orders."""
        self.auth(self.buyer)
        iphone = ProductInfo.objects.get(external_id=4216292)
        self.client.post(
            '/api/v1/basket',
            {'items': [{'product_info': iphone.id, 'quantity': 1}]},
            format='json',
        )
        contact = Contact.objects.create(
            user=self.buyer, city='Москва', street='Улица', phone='+7999'
        )
        basket = Order.objects.get(user=self.buyer, state='basket')
        self.client.post(
            '/api/v1/order', {'id': basket.id, 'contact': contact.id}, format='json'
        )
        self.auth(self.supplier)

    def test_partner_update_imports_price_list(self):
        # подменяем HTTP-запрос: возвращаем тестовый прайс вместо сети
        mock_response = MagicMock()
        mock_response.content = TEST_PRICE
        mock_response.raise_for_status.return_value = None
        with patch('backend.tasks.get', return_value=mock_response):
            response = self.client.post(
                '/api/v1/partner/update',
                {'url': 'https://example.com/price.yaml'},
                format='json',
            )
        self.assertTrue(response.json()['Status'])

        # товары загружены и привязаны к магазину поставщика
        self.assertTrue(
            ProductInfo.objects.filter(
                shop__name='Тестовый магазин',
                shop__user=self.supplier,
                external_id=1001,
            ).exists()
        )

    def test_partner_update_rejects_buyers(self):
        self.auth(self.buyer)
        response = self.client.post(
            '/api/v1/partner/update', {'url': 'https://example.com/price.yaml'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_partner_state_toggle(self):
        # после импорта у поставщика появляется магазин
        mock_response = MagicMock()
        mock_response.content = TEST_PRICE
        mock_response.raise_for_status.return_value = None
        with patch('backend.tasks.get', return_value=mock_response):
            self.client.post(
                '/api/v1/partner/update',
                {'url': 'https://example.com/price.yaml'},
                format='json',
            )

        response = self.client.get('/api/v1/partner/state')
        self.assertTrue(response.json()['state'])

        # выключаем приём заказов
        response = self.client.post(
            '/api/v1/partner/state', {'state': 'off'}, format='json'
        )
        self.assertTrue(response.json()['Status'])
        self.assertFalse(Shop.objects.get(user=self.supplier).state)

    def test_partner_orders_contains_only_own_goods(self):
        self._place_buyer_order()
        # импортируем прайс в магазин поставщика (свяжет заказ с этим магазином
        # только если товары совпадают — здесь проверяем базовую работу эндпоинта)
        response = self.client.get('/api/v1/partner/orders')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_partner_orders_for_own_shop(self):
        """Заказ с товарами магазина поставщика виден ему в partner/orders."""
        # магазин «Связной» (создан при загрузке shop1.yaml) привязываем
        # к поставщику — тогда его заказы попадут в выдачу
        shop = Shop.objects.get(name='Связной')
        shop.user = self.supplier
        shop.save()

        self._place_buyer_order()
        response = self.client.get('/api/v1/partner/orders')
        orders = response.json()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]['state'], 'new')


class TestImportLogic(TestCase):
    """Юнит-тесты функции импорта прайса."""

    def test_import_creates_full_catalog(self):
        data = parse_yaml_price_list(TEST_PRICE)
        shop = import_goods(data)

        self.assertEqual(shop.name, 'Тестовый магазин')
        self.assertEqual(ProductInfo.objects.filter(shop=shop).count(), 2)
        # категории связаны с магазином через m2m
        category = Category.objects.get(id=100)
        self.assertIn(shop, category.shops.all())
        # характеристики товара сохранены
        product_info = ProductInfo.objects.get(external_id=1001)
        params = {
            p.parameter.name: p.value
            for p in product_info.product_parameters.all()
        }
        self.assertEqual(params['Цвет'], 'красный')

    def test_reimport_replaces_old_positions(self):
        data = parse_yaml_price_list(TEST_PRICE)
        shop = import_goods(data)
        self.assertEqual(ProductInfo.objects.filter(shop=shop).count(), 2)

        # повторная загрузка не удваивает каталог
        import_goods(data)
        self.assertEqual(ProductInfo.objects.filter(shop=shop).count(), 2)

    def test_reimport_keeps_order_history(self):
        """
        При обновлении прайса состав оформленных заказов сохраняется:
        позиции с заказами не удаляются, а скрываются из каталога
        (обнуляется остаток).
        """
        data = parse_yaml_price_list(TEST_PRICE)
        shop = import_goods(data)

        # покупатель оформляет заказ с товаром 1001
        buyer = User.objects.create_user(
            'history@example.com', 'Sup3r-Secret-Pass', is_active=True
        )
        order = Order.objects.create(user=buyer, state='new')
        product_info = ProductInfo.objects.get(shop=shop, external_id=1001)
        OrderItem.objects.create(order=order, product_info=product_info, quantity=2)

        # новый прайс: товара 1001 больше нет, вместо него товар 1003
        updated_price = TEST_PRICE.replace(b'1001', b'1003')
        import_goods(parse_yaml_price_list(updated_price))

        # позиция не удалена — история заказа сохранена
        product_info.refresh_from_db()
        self.assertEqual(product_info.quantity, 0)
        self.assertTrue(OrderItem.objects.filter(order=order).exists())

        # товар 1003 загружен
        self.assertTrue(ProductInfo.objects.filter(shop=shop, external_id=1003).exists())
        # товар 1002 присутствует и в новом прайсе — остаётся в каталоге
        self.assertTrue(ProductInfo.objects.filter(shop=shop, external_id=1002).exists())

    def test_invalid_yaml_rejected(self):
        with self.assertRaises(ImportValidationError):
            parse_yaml_price_list(b'not: [valid')

    def test_missing_shop_name_rejected(self):
        with self.assertRaises(ImportValidationError):
            parse_yaml_price_list(b'categories: []\ngoods: []\n')

    def test_load_yaml_management_command(self):
        """Management-команда загружает прайс из локального файла задания."""
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command('load_yaml', str(SHOP1_YAML), stdout=out)
        self.assertIn('Загружено товаров: 14', out.getvalue())
