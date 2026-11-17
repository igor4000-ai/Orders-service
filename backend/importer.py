"""
Импорт товаров из YAML-файла прайса (Этап 3 дипломного проекта).

Формат входного файла (см. data/shop1.yaml):

    shop: Связной
    categories:
      - id: 224
        name: Смартфоны
    goods:
      - id: 4216292                # внешний идентификатор
        category: 224
        model: apple/iphone/xs-max
        name: Смартфон Apple iPhone XS Max 512GB (золотистый)
        price: 110000
        price_rrc: 116990
        quantity: 14
        parameters:
          "Цвет": золотистый

Одна и та же функция import_goods() используется тремя способами:
1) эндпоинтом POST /api/v1/partner/update — поставщик передаёт url прайса;
2) Celery-задачей do_import (backend/tasks.py) — тот же импорт в фоне;
3) management-командой load_yaml — загрузка локального файла или url
   из командной строки (python manage.py load_yaml data/shop1.yaml).

Импорт выполняется в транзакции: при ошибке в данных частичная
загрузка откатывается, старые данные магазина не теряются.

Важная деталь реализации: позиции, на которые ссылаются оформленные
заказы, не удаляются при обновлении прайса (иначе каскадное удаление
стерло бы историю заказов) — они сохраняются с нулевым остатком
и пропадают из каталога.
"""

import logging

from django.db import transaction
from yaml import load as load_yaml
from yaml import Loader

from backend.models import (
    Category,
    Parameter,
    Product,
    ProductInfo,
    ProductParameter,
    Shop,
)

logger = logging.getLogger(__name__)

# Поля товара в прайсе, которые обязаны присутствовать
REQUIRED_GOOD_FIELDS = ('id', 'category', 'name', 'price', 'price_rrc', 'quantity')


class ImportValidationError(Exception):
    """Ошибка входных данных прайса: файл не соответствует формату."""


def parse_yaml_price_list(stream: bytes) -> dict:
    """
    Разбирает содержимое YAML-прайса и проверяет структуру.

    :param stream: содержимое файла (байты)
    :return: словарь с ключами shop, categories, goods
    :raises ImportValidationError: если структура некорректна
    """
    try:
        data = load_yaml(stream, Loader=Loader)
    except Exception as exc:  # некорректный YAML
        raise ImportValidationError(f'Не удалось разобрать YAML-файл: {exc}')

    if not isinstance(data, dict) or not data.get('shop'):
        raise ImportValidationError('В прайсе не указано название магазина (поле shop)')

    for key in ('categories', 'goods'):
        if not isinstance(data.get(key), list):
            raise ImportValidationError(f'В прайсе отсутствует или некорректно поле {key}')

    return data


def import_goods(data: dict, shop_user_id: int = None) -> Shop:
    """
    Загружает товары из разобранного прайса в базу данных.

    Логика:
    * магазин создаётся (или берётся существующий) по названию из прайса;
    * категории связываются с магазином через m2m;
    * предложения магазина (ProductInfo) обновляются по внешнему ИД:
      существующие позиции обновляются, новые создаются, пропавшие
      удаляются (кроме позиций с заказами — они сохраняют историю);
    * характеристики сохраняются через Parameter/ProductParameter,
      что даёт «настраиваемые поля» товаров без изменения схемы БД.

    :param data: словарь из parse_yaml_price_list()
    :param shop_user_id: id пользователя-поставщика (если импорт выполняется
        по запросу авторизованного магазина)
    :return: объект Shop, для которого загружен прайс
    :raises ImportValidationError: при ошибках в данных товаров
    """
    with transaction.atomic():
        # Магазин: если прайс загружает авторизованный поставщик —
        # привязываем магазин к нему
        shop, created = Shop.objects.get_or_create(
            name=data['shop'], defaults={'user_id': shop_user_id}
        )
        if shop_user_id and shop.user_id != shop_user_id:
            # магазин с таким названием уже принадлежит другому поставщику
            raise ImportValidationError(
                f'Магазин «{shop.name}» уже связан с другим пользователем'
            )
        logger.info('Импорт прайса: магазин %s (создан: %s)', shop.name, created)

        # Категории: берём по внешнему id из прайса и связываем с магазином
        for category in data['categories']:
            category_object, _ = Category.objects.get_or_create(
                id=category['id'], defaults={'name': category['name']}
            )
            category_object.shops.add(shop.id)

        for item in data['goods']:
            missing = [field for field in REQUIRED_GOOD_FIELDS if field not in item]
            if missing:
                raise ImportValidationError(
                    f'У товара {item.get("name", "?")} не хватает полей: {", ".join(missing)}'
                )

            product, _ = Product.objects.get_or_create(
                name=item['name'], category_id=item['category']
            )

            # Позиция каталога обновляется на месте, если уже существует:
            # так не нарушается уникальный индекс (product, shop, external_id)
            # и сохраняется связь с уже оформленными заказами
            product_info, _ = ProductInfo.objects.update_or_create(
                product=product,
                shop=shop,
                external_id=item['id'],
                defaults={
                    'model': item.get('model', ''),
                    'price': item['price'],
                    'price_rrc': item['price_rrc'],
                    'quantity': item['quantity'],
                },
            )

            # Характеристики товара (настраиваемые поля) пересоздаются
            ProductParameter.objects.filter(product_info=product_info).delete()
            for name, value in item.get('parameters', {}).items():
                parameter_object, _ = Parameter.objects.get_or_create(name=name)
                ProductParameter.objects.create(
                    product_info_id=product_info.id,
                    parameter_id=parameter_object.id,
                    value=value,
                )

        # Позиции, которых больше нет в прайсе:
        # * без заказов — удаляем из каталога;
        # * с заказами — сохраняем для истории заказов, обнуляя остаток
        #   (каскадное удаление стёрло бы состав оформленных заказов).
        new_external_ids = [item['id'] for item in data['goods']]
        stale = ProductInfo.objects.filter(shop_id=shop.id).exclude(
            external_id__in=new_external_ids
        )
        stale.filter(ordered_items__isnull=True).delete()
        stale.filter(ordered_items__isnull=False).update(quantity=0)

    logger.info(
        'Импорт прайса магазина %s завершён: загружено %d товаров',
        shop.name,
        len(data['goods']),
    )
    return shop
