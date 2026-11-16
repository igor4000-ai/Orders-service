"""
Модели данных сервиса автоматизации закупок (Этап 2 дипломного проекта).

Основные сущности:
* User        — пользователь (покупатель или сотрудник магазина-поставщика);
* Shop        — магазин (поставщик), загружающий прайс;
* Category    — категория товаров (связана с магазинами через m2m);
* Product     — товар (глобальная сущность каталога);
* ProductInfo — предложение товара конкретным магазином (цена, наличие);
* Parameter / ProductParameter — настраиваемые характеристики товара;
* Contact     — контактные данные пользователя (адрес доставки + телефон);
* Order / OrderItem — заказ и его позиции (корзина — это заказ со статусом
  'basket', отдельная таблица для корзины не нужна);
* ConfirmEmailToken — одноразовый токен подтверждения email при регистрации.
"""

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_rest_passwordreset.tokens import get_token_generator


# Возможные статусы заказа. Корзина хранится как заказ со статусом 'basket',
# поэтому первый элемент — именно она.
STATE_CHOICES = (
    ('basket', 'Статус корзины'),
    ('new', 'Новый'),
    ('confirmed', 'Подтвержден'),
    ('assembled', 'Собран'),
    ('sent', 'Отправлен'),
    ('delivered', 'Доставлен'),
    ('canceled', 'Отменен'),
)

# Типы пользователей сервиса: покупатель и магазин (поставщик)
USER_TYPE_CHOICES = (
    ('shop', 'Магазин'),
    ('buyer', 'Покупатель'),
)


class UserManager(BaseUserManager):
    """
    Менеджер пользователей: в проекте вход выполняется по email,
    поэтому создаём пользователей без username.
    """

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('Email обязателен для создания пользователя')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Суперпользователь должен иметь is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Суперпользователь должен иметь is_superuser=True.')

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Пользователь сервиса.

    Отличия от стандартной модели Django:
    * вход выполняется по email (USERNAME_FIELD);
    * поле username не используется и не является обязательным/уникальным;
    * новый пользователь неактивен до подтверждения email;
    * у пользователя есть тип — «покупатель» или «магазин».
    """

    REQUIRED_FIELDS = []
    objects = UserManager()
    USERNAME_FIELD = 'email'

    email = models.EmailField(_('email address'), unique=True)
    company = models.CharField(verbose_name='Компания', max_length=40, blank=True)
    position = models.CharField(verbose_name='Должность', max_length=40, blank=True)

    username_validator = UnicodeUsernameValidator()
    # username оставлен для совместимости со стандартной моделью,
    # но не участвует в аутентификации
    username = models.CharField(
        _('username'),
        max_length=150,
        blank=True,
        unique=False,
        help_text=_('Не используется: вход в сервис выполняется по email.'),
        validators=[username_validator],
    )

    is_active = models.BooleanField(
        _('active'),
        default=False,
        help_text=_('Пользователь неактивен, пока не подтвердит email.'),
    )
    type = models.CharField(
        verbose_name='Тип пользователя',
        choices=USER_TYPE_CHOICES,
        max_length=5,
        default='buyer',
    )

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.email})'

    class Meta:
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Список пользователей'
        ordering = ('email',)


class Shop(models.Model):
    """
    Магазин (поставщик).

    Прайс товаров загружается из файла по ссылке url (или по имени файла
    filename для локальных загрузок). Владелец-пользователь может
    включать и отключать приём заказов переключением state.
    """

    name = models.CharField(max_length=50, verbose_name='Название')
    url = models.URLField(verbose_name='Ссылка на прайс', null=True, blank=True)
    filename = models.CharField(
        verbose_name='Имя файла с прайсом (локальная загрузка)',
        max_length=100,
        null=True,
        blank=True,
    )
    user = models.OneToOneField(
        User,
        verbose_name='Пользователь (владелец магазина)',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )
    state = models.BooleanField(verbose_name='Приём заказов', default=True)

    class Meta:
        verbose_name = 'Магазин'
        verbose_name_plural = 'Список магазинов'
        ordering = ('-name',)

    def __str__(self):
        return self.name


class Category(models.Model):
    """
    Категория товаров. Вложенность категорий не предусмотрена.
    """

    name = models.CharField(max_length=40, verbose_name='Название')
    # категория offered by several shops — связь m2m
    shops = models.ManyToManyField(
        Shop,
        verbose_name='Магазины',
        related_name='categories',
        blank=True,
    )

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Список категорий'
        ordering = ('-name',)

    def __str__(self):
        return self.name


class Product(models.Model):
    """
    Товар каталога. Одна и та же позиция может поставляться разными
    магазинами — предложения хранятся в ProductInfo.
    """

    name = models.CharField(max_length=80, verbose_name='Название')
    category = models.ForeignKey(
        Category,
        verbose_name='Категория',
        related_name='products',
        blank=True,
        on_delete=models.CASCADE,
    )

    class Meta:
        verbose_name = 'Продукт'
        verbose_name_plural = 'Список продуктов'
        ordering = ('-name',)

    def __str__(self):
        return self.name


class ProductInfo(models.Model):
    """
    Предложение товара конкретным магазином: модель, внешний идентификатор,
    цена, рекомендуемая розничная цена и остаток.

    При повторной загрузке прайса все ProductInfo магазина пересоздаются.
    """

    model = models.CharField(max_length=80, verbose_name='Модель', blank=True)
    external_id = models.PositiveIntegerField(verbose_name='Внешний ИД')
    product = models.ForeignKey(
        Product,
        verbose_name='Продукт',
        related_name='product_infos',
        blank=True,
        on_delete=models.CASCADE,
    )
    shop = models.ForeignKey(
        Shop,
        verbose_name='Магазин',
        related_name='product_infos',
        blank=True,
        on_delete=models.CASCADE,
    )
    quantity = models.PositiveIntegerField(verbose_name='Количество')
    price = models.PositiveIntegerField(verbose_name='Цена')
    price_rrc = models.PositiveIntegerField(verbose_name='Рекомендуемая розничная цена')

    class Meta:
        verbose_name = 'Информация о продукте'
        verbose_name_plural = 'Информационный список о продуктах'
        constraints = [
            # один и тот же внешний ИД в рамках одного магазина встречается один раз
            models.UniqueConstraint(
                fields=['product', 'shop', 'external_id'], name='unique_product_info'
            ),
        ]

    def __str__(self):
        return f'{self.product.name} ({self.shop.name})'


class Parameter(models.Model):
    """
    Имя настраиваемой характеристики товара (например, «Цвет» или «Диагональ»).
    Благодаря связке Parameter/ProductParameter набор характеристик
    задаётся данными, а не схемой БД.
    """

    name = models.CharField(max_length=40, verbose_name='Название')

    class Meta:
        verbose_name = 'Имя параметра'
        verbose_name_plural = 'Список имен параметров'
        ordering = ('-name',)

    def __str__(self):
        return self.name


class ProductParameter(models.Model):
    """
    Значение характеристики для конкретного предложения товара.
    """

    product_info = models.ForeignKey(
        ProductInfo,
        verbose_name='Информация о продукте',
        related_name='product_parameters',
        blank=True,
        on_delete=models.CASCADE,
    )
    parameter = models.ForeignKey(
        Parameter,
        verbose_name='Параметр',
        related_name='product_parameters',
        blank=True,
        on_delete=models.CASCADE,
    )
    value = models.CharField(verbose_name='Значение', max_length=100)

    class Meta:
        verbose_name = 'Параметр'
        verbose_name_plural = 'Список параметров'
        constraints = [
            # у каждого предложения конкретная характеристика встречается один раз
            models.UniqueConstraint(
                fields=['product_info', 'parameter'], name='unique_product_parameter'
            ),
        ]

    def __str__(self):
        return f'{self.parameter.name}: {self.value}'


class Contact(models.Model):
    """
    Контакты пользователя: телефон и адрес доставки.
    Ограничение на количество адресов (не более MAX_USER_ADDRESSES)
    проверяется на уровне сериализатора.
    """

    user = models.ForeignKey(
        User,
        verbose_name='Пользователь',
        related_name='contacts',
        blank=True,
        on_delete=models.CASCADE,
    )

    city = models.CharField(max_length=50, verbose_name='Город')
    street = models.CharField(max_length=100, verbose_name='Улица')
    house = models.CharField(max_length=15, verbose_name='Дом', blank=True)
    structure = models.CharField(max_length=15, verbose_name='Корпус', blank=True)
    building = models.CharField(max_length=15, verbose_name='Строение', blank=True)
    apartment = models.CharField(max_length=15, verbose_name='Квартира', blank=True)
    phone = models.CharField(max_length=20, verbose_name='Телефон')

    class Meta:
        verbose_name = 'Контакты пользователя'
        verbose_name_plural = 'Список контактов пользователя'

    def __str__(self):
        return f'{self.city}, {self.street} {self.house} ({self.phone})'


class Order(models.Model):
    """
    Заказ пользователя. Пока заказ не подтверждён, он выполняет роль
    корзины (state='basket'). После подтверждения статус меняется
    администратором или сотрудником магазина.
    """

    user = models.ForeignKey(
        User,
        verbose_name='Пользователь',
        related_name='orders',
        blank=True,
        on_delete=models.CASCADE,
    )
    dt = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    state = models.CharField(
        verbose_name='Статус', choices=STATE_CHOICES, max_length=15
    )
    contact = models.ForeignKey(
        Contact,
        verbose_name='Контакт',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Список заказов'
        ordering = ('-dt',)

    def __str__(self):
        return f'Заказ №{self.id} от {self.dt:%d.%m.%Y %H:%M}'

    # Кэш значения суммы, если оно получено аннотацией queryset (.annotate(total_sum=...))
    _total_sum_cache = None

    @property
    def total_sum(self) -> int:
        """
        Сумма заказа: количество × цена по каждой позиции.

        Если queryset аннотировал total_sum (так делают API-представления
        для экономии запросов к БД) — используется аннотация, иначе сумма
        считается по позициям заказа.
        """
        if self._total_sum_cache is not None:
            return self._total_sum_cache
        return sum(
            item.quantity * item.product_info.price
            for item in self.ordered_items.all()
        )

    @total_sum.setter
    def total_sum(self, value: int) -> None:
        """Django вызывает setter при .annotate(total_sum=...) в queryset."""
        self._total_sum_cache = value


class OrderItem(models.Model):
    """
    Позиция заказа: конкретное предложение (ProductInfo) в определённом
    количестве. Благодаря этому в одном заказе могут быть товары разных
    магазинов, а цена фиксируется на момент оформления.
    """

    order = models.ForeignKey(
        Order,
        verbose_name='Заказ',
        related_name='ordered_items',
        blank=True,
        on_delete=models.CASCADE,
    )
    product_info = models.ForeignKey(
        ProductInfo,
        verbose_name='Информация о продукте',
        related_name='ordered_items',
        blank=True,
        on_delete=models.CASCADE,
    )
    quantity = models.PositiveIntegerField(verbose_name='Количество')

    class Meta:
        verbose_name = 'Заказанная позиция'
        verbose_name_plural = 'Список заказанных позиций'
        constraints = [
            # одна и та же позиция не может дважды попасть в заказ
            models.UniqueConstraint(
                fields=['order_id', 'product_info'], name='unique_order_item'
            ),
        ]

    def __str__(self):
        return f'{self.product_info} × {self.quantity}'


class ConfirmEmailToken(models.Model):
    """
    Одноразовый токен для подтверждения email при регистрации.
    Отправляется пользователю письмом, после успешного подтверждения удаляется.
    """

    @staticmethod
    def generate_key():
        """Генерирует псевдослучайный токен (os.urandom + binascii)."""
        return get_token_generator().generate_token()

    user = models.ForeignKey(
        User,
        related_name='confirm_email_tokens',
        on_delete=models.CASCADE,
        verbose_name='Пользователь',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время создания')
    key = models.CharField(_('Key'), max_length=64, db_index=True, unique=True)

    def save(self, *args, **kwargs):
        # токен создаётся автоматически при первом сохранении
        if not self.key:
            self.key = self.generate_key()
        return super(ConfirmEmailToken, self).save(*args, **kwargs)

    def __str__(self):
        return f'Токен подтверждения email для {self.user.email}'

    class Meta:
        verbose_name = 'Токен подтверждения Email'
        verbose_name_plural = 'Токены подтверждения Email'
