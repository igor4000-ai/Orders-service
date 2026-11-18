"""
Сериализаторы приложения backend: преобразование моделей в JSON и обратно
для всех эндпоинтов REST API.
"""

from rest_framework import serializers

from backend.models import (
    Category,
    Contact,
    Order,
    OrderItem,
    Product,
    ProductInfo,
    ProductParameter,
    Shop,
    User,
)


class ContactSerializer(serializers.ModelSerializer):
    """
    Адрес доставки и телефон пользователя.
    Поле user доступно только на запись: клиент не может указать чужой id.
    """

    class Meta:
        model = Contact
        fields = (
            'id', 'city', 'street', 'house', 'structure',
            'building', 'apartment', 'phone', 'user',
        )
        read_only_fields = ('id',)
        extra_kwargs = {'user': {'write_only': True}}


class UserSerializer(serializers.ModelSerializer):
    """
    Данные учётной записи. Контакты пользователя — только для чтения.
    """

    contacts = ContactSerializer(read_only=True, many=True)

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'email', 'company', 'position', 'contacts')
        read_only_fields = ('id',)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ('id', 'name',)
        read_only_fields = ('id',)


class ShopSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shop
        fields = ('id', 'name', 'url', 'state',)
        read_only_fields = ('id',)


class ProductSerializer(serializers.ModelSerializer):
    category = serializers.StringRelatedField()

    class Meta:
        model = Product
        fields = ('name', 'category',)


class ProductParameterSerializer(serializers.ModelSerializer):
    parameter = serializers.StringRelatedField()

    class Meta:
        model = ProductParameter
        fields = ('parameter', 'value',)


class ProductInfoSerializer(serializers.ModelSerializer):
    """
    Предложение товара: JSON-поля каталога по описанию сервиса —
    наименование, модель (описание), поставщик, характеристики,
    цена, рекомендуемая цена, количество.
    """

    product = ProductSerializer(read_only=True)
    product_parameters = ProductParameterSerializer(read_only=True, many=True)
    shop = serializers.StringRelatedField()

    class Meta:
        model = ProductInfo
        fields = (
            'id', 'model', 'product', 'shop', 'quantity',
            'price', 'price_rrc', 'product_parameters',
        )
        read_only_fields = ('id',)


class OrderItemSerializer(serializers.ModelSerializer):
    """
    Позиция заказа. Используется при добавлении товаров в корзину:
    клиент передаёт product_info и quantity.
    """

    class Meta:
        model = OrderItem
        fields = ('id', 'product_info', 'quantity', 'order',)
        read_only_fields = ('id',)
        extra_kwargs = {'order': {'write_only': True}}


class OrderItemCreateSerializer(OrderItemSerializer):
    """
    Позиция заказа с развёрнутой информацией о товаре (для чтения корзины/заказов).
    """

    product_info = ProductInfoSerializer(read_only=True)


class OrderSerializer(serializers.ModelSerializer):
    """
    Заказ с позициями, адресом доставки и суммой.
    """

    ordered_items = OrderItemCreateSerializer(read_only=True, many=True)
    total_sum = serializers.IntegerField()
    contact = ContactSerializer(read_only=True)

    class Meta:
        model = Order
        fields = ('id', 'ordered_items', 'state', 'dt', 'total_sum', 'contact',)
        read_only_fields = ('id',)
