"""
API views сервиса автоматизации закупок (Этапы 4-5 дипломного проекта).

Реализованы все эндпоинты базовой части:
* регистрация, подтверждение email, вход, восстановление пароля;
* данные учётной записи и контакты пользователя;
* каталог: категории, магазины, товары с фильтрацией и поиском;
* корзина: добавление, редактирование, удаление, просмотр;
* оформление и просмотр заказов;
* партнёрские (поставщикские) эндпоинты: обновление прайса, статус приёма
  заказов, список заказов с товарами магазина.

Полный список маршрутов — в backend/urls.py, живая документация — /api/docs/.
"""

import logging

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError
from django.db.models import Q, Sum, F
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from ujson import loads as load_json

from backend.models import (
    Category,
    ConfirmEmailToken,
    Contact,
    Order,
    OrderItem,
    ProductInfo,
    Shop,
)
from backend.serializers import (
    CategorySerializer,
    ContactSerializer,
    OrderItemSerializer,
    OrderSerializer,
    ProductInfoSerializer,
    ShopSerializer,
    UserSerializer,
)
from backend.signals import new_order
from backend.tasks import do_import, run_task

logger = logging.getLogger(__name__)


def parse_bool(value: str) -> bool:
    """
    Разбирает человекочитаемое булево значение из запроса
    ('true', 'false', 'on', 'off', '1', '0', 'yes', 'no').
    """
    return str(value).strip().lower() in ('true', 'on', '1', 'yes')


def login_required(function):
    """
    Декоратор для методов APIView: проверяет, что запрос авторизован.
    Сокращает дублирование одной и той же проверки в каждом методе.
    """

    def wrapper(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {'Status': False, 'Error': 'Требуется вход в систему'}, status=403
            )
        return function(self, request, *args, **kwargs)

    return wrapper


def shop_user_required(function):
    """
    Декоратор для партнёрских эндпоинтов: запрос должен быть от
    авторизованного пользователя типа «магазин».
    """

    def wrapper(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {'Status': False, 'Error': 'Требуется вход в систему'}, status=403
            )
        if request.user.type != 'shop':
            return JsonResponse(
                {'Status': False, 'Error': 'Только для пользователей типа «магазин»'},
                status=403,
            )
        return function(self, request, *args, **kwargs)

    return wrapper


class RegisterAccount(APIView):
    """
    Регистрация покупателя: POST /api/v1/user/register
    """

    @extend_schema(
        request=inline_serializer('RegisterRequest', fields={
            'first_name': serializers.CharField(),
            'last_name': serializers.CharField(),
            'email': serializers.EmailField(),
            'password': serializers.CharField(write_only=True),
            'company': serializers.CharField(required=False),
            'position': serializers.CharField(required=False),
        }),
    )
    def post(self, request, *args, **kwargs):
        # Обязательные поля — по спецификации: имя, фамилия, email, пароль.
        # Компания и должность — необязательные дополнительные сведения.
        required_fields = {'first_name', 'last_name', 'email', 'password'}
        if not required_fields.issubset(request.data):
            return JsonResponse(
                {'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}
            )

        # Проверка сложности пароля стандартными валидаторами Django
        try:
            validate_password(request.data['password'])
        except ValidationError as password_error:
            error_list = [item for item in password_error.messages]
            return JsonResponse(
                {'Status': False, 'Errors': {'password': error_list}}
            )

        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            user.set_password(request.data['password'])
            user.save()
            # is_active=False: письмо с токеном подтверждения уходит
            # автоматически (сигнал post_save, см. backend/signals.py)
            return JsonResponse({'Status': True})
        return JsonResponse({'Status': False, 'Errors': serializer.errors})


class ConfirmAccount(APIView):
    """
    Подтверждение email: POST /api/v1/user/register/confirm
    """

    @extend_schema(
        request=inline_serializer('ConfirmRequest', fields={
            'email': serializers.EmailField(),
            'token': serializers.CharField(),
        }),
    )
    def post(self, request, *args, **kwargs):
        if {'email', 'token'}.issubset(request.data):
            token = ConfirmEmailToken.objects.filter(
                user__email=request.data['email'], key=request.data['token']
            ).first()
            if token:
                # активируем пользователя и удаляем одноразовый токен
                token.user.is_active = True
                token.user.save()
                token.delete()
                return JsonResponse({'Status': True})
            return JsonResponse(
                {'Status': False, 'Errors': 'Неправильно указан токен или email'}
            )
        return JsonResponse(
            {'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}
        )


class LoginAccount(APIView):
    """
    Авторизация: POST /api/v1/user/login — возвращает токен DRF.
    """

    @extend_schema(
        request=inline_serializer('LoginRequest', fields={
            'email': serializers.EmailField(),
            'password': serializers.CharField(write_only=True),
        }),
    )
    def post(self, request, *args, **kwargs):
        if {'email', 'password'}.issubset(request.data):
            user = authenticate(
                request,
                username=request.data['email'],
                password=request.data['password'],
            )
            if user is not None:
                if user.is_active:
                    token, _ = Token.objects.get_or_create(user=user)
                    return JsonResponse({'Status': True, 'Token': token.key})
                return JsonResponse(
                    {'Status': False, 'Errors': 'Аккаунт не активирован: подтвердите email'}
                )
            return JsonResponse({'Status': False, 'Errors': 'Не удалось авторизовать'})
        return JsonResponse(
            {'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}
        )


class AccountDetails(APIView):
    """
    Данные учётной записи: GET/POST /api/v1/user/details
    """

    # для OpenAPI-схемы (на работу view не влияет)
    serializer_class = UserSerializer

    @login_required
    def get(self, request, *args, **kwargs):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    @login_required
    def post(self, request, *args, **kwargs):
        # Смена пароля (если передан) с проверкой сложности
        if 'password' in request.data:
            try:
                validate_password(request.data['password'])
            except ValidationError as password_error:
                return JsonResponse(
                    {'Status': False, 'Errors': {'password': password_error.messages}}
                )
            request.user.set_password(request.data['password'])

        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            # сохраняем и пароль, если он менялся
            request.user.save()
            return JsonResponse({'Status': True})
        return JsonResponse({'Status': False, 'Errors': serializer.errors})


class CategoryView(ListAPIView):
    """
    Список категорий: GET /api/v1/categories
    """

    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ShopView(ListAPIView):
    """
    Список активных магазинов: GET /api/v1/shops
    """

    queryset = Shop.objects.filter(state=True)
    serializer_class = ShopSerializer


class ProductInfoView(APIView):
    """
    Каталог товаров с фильтрацией и поиском: GET /api/v1/products

    Параметры строки запроса:
    * shop_id     — товары конкретного магазина;
    * category_id — товары категории;
    * q           — текстовый поиск по названию, модели, категории
                    и значениям характеристик.
    """

    serializer_class = ProductInfoSerializer  # для OpenAPI-схемы

    def get(self, request, *args, **kwargs):
        # В каталоге показываем только товары активных магазинов
        # и только с ненулевым остатком (позиции, снятые с продажи
        # при обновлении прайса, пропадают из выдачи)
        query = Q(shop__state=True) & Q(quantity__gt=0)
        shop_id = request.query_params.get('shop_id')
        category_id = request.query_params.get('category_id')
        search_text = request.query_params.get('q')

        if shop_id:
            query = query & Q(shop_id=shop_id)
        if category_id:
            query = query & Q(product__category_id=category_id)
        if search_text:
            query = query & (
                Q(product__name__icontains=search_text)
                | Q(model__icontains=search_text)
                | Q(product__category__name__icontains=search_text)
                | Q(product_parameters__value__icontains=search_text)
            )

        queryset = (
            ProductInfo.objects.filter(query)
            .select_related('shop', 'product__category')
            .prefetch_related('product_parameters__parameter')
            .distinct()
        )

        serializer = ProductInfoSerializer(queryset, many=True)
        return Response(serializer.data)


class ProductInfoDetailView(APIView):
    """
    Спецификация отдельного товара: GET /api/v1/products/<id>
    """

    serializer_class = ProductInfoSerializer  # для OpenAPI-схемы

    def get(self, request, pk, *args, **kwargs):
        product_info = (
            ProductInfo.objects.filter(pk=pk, shop__state=True)
            .select_related('shop', 'product__category')
            .prefetch_related('product_parameters__parameter')
            .first()
        )
        if product_info is None:
            return JsonResponse(
                {'Status': False, 'Errors': 'Товар не найден'}, status=404
            )
        serializer = ProductInfoSerializer(product_info)
        return Response(serializer.data)


class BasketView(APIView):
    """
    Корзина покупателя: GET/POST/PUT/DELETE /api/v1/basket

    Корзина реализована как заказ со статусом 'basket' — отдельная
    сущность не нужна. В одном заказе могут быть товары разных магазинов.
    """

    serializer_class = OrderSerializer  # для OpenAPI-схемы (GET-ответ)

    @login_required
    def get(self, request, *args, **kwargs):
        basket = self._get_user_basket(request)
        if basket is None:
            # корзина ещё не создана — возвращаем пустой список
            return Response([])
        serializer = OrderSerializer(basket)
        return Response(serializer.data)

    @login_required
    def post(self, request, *args, **kwargs):
        items = self._parse_items(request)
        if items is None:
            return JsonResponse(
                {'Status': False, 'Errors': 'Неверный формат запроса'}
            )

        basket, _ = Order.objects.get_or_create(user_id=request.user.id, state='basket')
        created_count = 0
        errors = []

        for order_item in items:
            product_info_id = order_item.get('product_info')
            quantity = order_item.get('quantity', 0)
            if not product_info_id or not isinstance(quantity, int) or quantity < 1:
                errors.append(f'Некорректная позиция: {order_item}')
                continue

            # Проверяем, что предложение существует и магазин принимает заказы
            product_info = ProductInfo.objects.select_related('shop').filter(
                pk=product_info_id
            ).first()
            if product_info is None:
                errors.append(f'Товар {product_info_id} не найден')
                continue
            if not product_info.shop.state:
                errors.append(
                    f'Магазин «{product_info.shop.name}» не принимает заказы'
                )
                continue
            if quantity > product_info.quantity:
                errors.append(
                    f'Товар {product_info_id}: доступно только {product_info.quantity} шт.'
                )
                continue

            # Если товар уже в корзине — увеличиваем количество
            existing = OrderItem.objects.filter(
                order=basket, product_info=product_info
            ).first()
            if existing:
                existing.quantity += quantity
                existing.save()
            else:
                OrderItem.objects.create(
                    order=basket, product_info=product_info, quantity=quantity
                )
            created_count += 1

        if created_count:
            return JsonResponse({'Status': True, 'Создано объектов': created_count,
                                 **({'Errors': errors} if errors else {})})
        return JsonResponse({'Status': False, 'Errors': errors or 'Пустой список товаров'})

    @login_required
    def put(self, request, *args, **kwargs):
        items = self._parse_items(request)
        if items is None:
            return JsonResponse(
                {'Status': False, 'Errors': 'Неверный формат запроса'}
            )

        basket, _ = Order.objects.get_or_create(user_id=request.user.id, state='basket')
        updated_count = 0
        for order_item in items:
            item_id = order_item.get('id')
            quantity = order_item.get('quantity')
            if isinstance(item_id, int) and isinstance(quantity, int) and quantity >= 1:
                updated_count += OrderItem.objects.filter(
                    order_id=basket.id, id=item_id
                ).update(quantity=quantity)
            else:
                logger.warning('Пропущена некорректная позиция корзины: %s', order_item)

        return JsonResponse({'Status': True, 'Обновлено объектов': updated_count})

    @login_required
    def delete(self, request, *args, **kwargs):
        items_string = request.data.get('items')
        if not items_string:
            return JsonResponse(
                {'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}
            )

        basket, _ = Order.objects.get_or_create(user_id=request.user.id, state='basket')
        query = Q()
        found_any = False
        for item_id in str(items_string).split(','):
            if item_id.strip().isdigit():
                query = query | Q(order_id=basket.id, id=item_id.strip())
                found_any = True

        if found_any:
            deleted_count = OrderItem.objects.filter(query).delete()[0]
            return JsonResponse({'Status': True, 'Удалено объектов': deleted_count})
        return JsonResponse(
            {'Status': False, 'Errors': 'Не указаны корректные идентификаторы позиций'}
        )

    @staticmethod
    def _parse_items(request):
        """
        Достаёт список позиций из параметра items.

        Поддерживаются два формата: JSON-тело запроса (items — список)
        и form-data/x-www-form-urlencoded (items — строка с JSON).
        Возвращает список либо None при ошибке разбора.
        """
        items = request.data.get('items')
        if isinstance(items, str):
            try:
                items = load_json(items)
            except ValueError:
                return None
        if isinstance(items, list):
            return items
        return None

    @staticmethod
    def _get_user_basket(request) -> Order:
        """
        Корзина пользователя с предзагрузкой связанных объектов и суммой.
        """
        return (
            Order.objects.filter(user_id=request.user.id, state='basket')
            .prefetch_related(
                'ordered_items__product_info__product__category',
                'ordered_items__product_info__product_parameters__parameter',
            )
            .annotate(total_sum=Sum(
                F('ordered_items__quantity') * F('ordered_items__product_info__price')
            ))
            .first()
        )


class PartnerUpdate(APIView):
    """
    Обновление прайса поставщиком: POST /api/v1/partner/update

    Аргумент: url — ссылка на YAML-файл прайса.
    Импорт выполняется Celery-задачей do_import (в фоне, если включён воркер).
    """

    @shop_user_required
    def post(self, request, *args, **kwargs):
        url = request.data.get('url')
        if not url:
            return JsonResponse(
                {'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}
            )

        # Валидация ссылки перед обращением к ней
        try:
            URLValidator()(url)
        except ValidationError as e:
            return JsonResponse({'Status': False, 'Errors': str(e.message)})

        result = run_task(do_import, url, request.user.id)
        # при синхронном выполнении (без Celery) вернём имя магазина сразу
        if isinstance(result, str):
            return JsonResponse({'Status': True, 'Загружено для магазина': result})
        return JsonResponse({'Status': True, 'Task': 'Импорт запущен в фоне'})


class PartnerState(APIView):
    """
    Статус приёма заказов магазином: GET/POST /api/v1/partner/state
    """

    serializer_class = ShopSerializer  # для OpenAPI-схемы

    @shop_user_required
    def get(self, request, *args, **kwargs):
        shop = request.user.shop  # OneToOne: у магазина есть владелец-пользователь
        serializer = ShopSerializer(shop)
        return Response(serializer.data)

    @shop_user_required
    def post(self, request, *args, **kwargs):
        state = request.data.get('state')
        if state is None:
            return JsonResponse(
                {'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}
            )
        if not Shop.objects.filter(user_id=request.user.id).exists():
            return JsonResponse(
                {'Status': False,
                 'Errors': 'У вас нет магазина: сначала загрузите прайс'},
                status=404,
            )
        Shop.objects.filter(user_id=request.user.id).update(state=parse_bool(state))
        return JsonResponse({'Status': True})


class PartnerOrders(APIView):
    """
    Заказы с товарами магазина поставщика: GET /api/v1/partner/orders
    """

    serializer_class = OrderSerializer  # для OpenAPI-схемы

    @shop_user_required
    def get(self, request, *args, **kwargs):
        orders = (
            Order.objects.filter(
                ordered_items__product_info__shop__user_id=request.user.id
            )
            .exclude(state='basket')
            .prefetch_related(
                'ordered_items__product_info__product__category',
                'ordered_items__product_info__product_parameters__parameter',
            )
            .select_related('contact')
            .annotate(
                total_sum=Sum(
                    F('ordered_items__quantity')
                    * F('ordered_items__product_info__price')
                )
            )
            .distinct()
        )
        serializer = OrderSerializer(orders, many=True)
        return Response(serializer.data)


class ContactView(APIView):
    """
    Контакты (адреса доставки) пользователя:
    GET/POST/PUT/DELETE /api/v1/user/contact

    По описанию сервиса у пользователя не более MAX_USER_ADDRESSES адресов
    (по умолчанию 5) и один телефон в каждом адресе.
    """

    serializer_class = ContactSerializer  # для OpenAPI-схемы

    @login_required
    def get(self, request, *args, **kwargs):
        contacts = Contact.objects.filter(user_id=request.user.id)
        serializer = ContactSerializer(contacts, many=True)
        return Response(serializer.data)

    @login_required
    def post(self, request, *args, **kwargs):
        if not {'city', 'street', 'phone'}.issubset(request.data):
            return JsonResponse(
                {'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}
            )

        # Ограничение на количество адресов доставки
        from django.conf import settings

        if Contact.objects.filter(user_id=request.user.id).count() >= settings.MAX_USER_ADDRESSES:
            return JsonResponse(
                {
                    'Status': False,
                    'Errors': f'Допускается не более {settings.MAX_USER_ADDRESSES} адресов доставки',
                }
            )

        data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
        data['user'] = request.user.id
        serializer = ContactSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return JsonResponse({'Status': True})
        return JsonResponse({'Status': False, 'Errors': serializer.errors})

    @login_required
    def put(self, request, *args, **kwargs):
        item_id = request.data.get('id')
        if not str(item_id or '').isdigit():
            return JsonResponse(
                {'Status': False, 'Errors': 'Не указан идентификатор контакта'}
            )
        contact = Contact.objects.filter(
            id=item_id, user_id=request.user.id
        ).first()
        if not contact:
            return JsonResponse(
                {'Status': False, 'Errors': 'Контакт не найден'}, status=404
            )

        data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
        data['user'] = request.user.id
        serializer = ContactSerializer(contact, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return JsonResponse({'Status': True})
        return JsonResponse({'Status': False, 'Errors': serializer.errors})

    @login_required
    def delete(self, request, *args, **kwargs):
        items_string = request.data.get('items')
        if not items_string:
            return JsonResponse(
                {'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}
            )
        query = Q()
        found_any = False
        for item_id in str(items_string).split(','):
            if item_id.strip().isdigit():
                query = query | Q(user_id=request.user.id, id=item_id.strip())
                found_any = True
        if found_any:
            deleted_count = Contact.objects.filter(query).delete()[0]
            return JsonResponse({'Status': True, 'Удалено объектов': deleted_count})
        return JsonResponse(
            {'Status': False, 'Errors': 'Не указаны корректные идентификаторы контактов'}
        )


class OrderView(APIView):
    """
    Заказы пользователя: GET/POST /api/v1/order

    GET  — список оформленных заказов (корзина исключается);
    POST — подтверждение заказа: аргументы id (корзины) и contact (адрес).
    """

    serializer_class = OrderSerializer  # для OpenAPI-схемы

    @login_required
    def get(self, request, *args, **kwargs):
        orders = (
            Order.objects.filter(user_id=request.user.id)
            .exclude(state='basket')
            .prefetch_related(
                'ordered_items__product_info__product__category',
                'ordered_items__product_info__product_parameters__parameter',
            )
            .select_related('contact')
            .annotate(
                total_sum=Sum(
                    F('ordered_items__quantity')
                    * F('ordered_items__product_info__price')
                )
            )
            .distinct()
        )
        serializer = OrderSerializer(orders, many=True)
        return Response(serializer.data)

    @login_required
    def post(self, request, *args, **kwargs):
        if not {'id', 'contact'}.issubset(request.data):
            return JsonResponse(
                {'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}
            )
        order_id, contact_id = request.data['id'], request.data['contact']
        if not str(order_id).isdigit() or not str(contact_id).isdigit():
            return JsonResponse(
                {'Status': False, 'Errors': 'Некорректные идентификаторы'}
            )

        # Заказ должен быть корзиной этого пользователя и не быть пустым
        order = Order.objects.filter(
            id=order_id, user_id=request.user.id, state='basket'
        ).first()
        if not order:
            return JsonResponse(
                {'Status': False, 'Errors': 'Корзина не найдена'}, status=404
            )
        if not order.ordered_items.exists():
            return JsonResponse({'Status': False, 'Errors': 'Корзина пуста'})

        # Адрес доставки должен принадлежать этому же пользователю
        contact = Contact.objects.filter(id=contact_id, user_id=request.user.id).first()
        if not contact:
            return JsonResponse(
                {'Status': False, 'Errors': 'Контакт не найден'}, status=404
            )

        try:
            # Оформление: статус «новый» + фиксация адреса доставки
            is_updated = Order.objects.filter(id=order.id).update(
                contact_id=contact.id, state='new'
            )
        except IntegrityError as error:
            logger.error('Ошибка оформления заказа: %s', error)
            return JsonResponse(
                {'Status': False, 'Errors': 'Неправильно указаны аргументы'}
            )

        if is_updated:
            # Письма (подтверждение покупателю + накладная администратору)
            # отправляются через сигнал new_order
            new_order.send(
                sender=self.__class__, user_id=request.user.id, order_id=order.id
            )
            return JsonResponse({'Status': True, 'Номер заказа': order.id})

        return JsonResponse({'Status': False, 'Errors': 'Не удалось оформить заказ'})
