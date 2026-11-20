"""
Админка Django (продвинутая часть, Этап 6 и Этап 7 дипломного проекта).

Что реализовано:
* раздел заказов: просмотр состава, смена статуса и автоматическое
  email-уведомление покупателя при изменении статуса (Этап 6);
* раздел магазинов: страница запуска Celery-задачи do_import — импорт
  прайса по ссылке прямо из админки (Этап 7), плюс групповое действие;
* разделы для остальных сущностей каталога.
"""

import logging

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from backend.models import (
    Category,
    ConfirmEmailToken,
    Contact,
    Order,
    OrderItem,
    Parameter,
    Product,
    ProductInfo,
    ProductParameter,
    Shop,
    User,
)
from backend.signals import send_order_state_notification
from backend.tasks import do_import, run_task

logger = logging.getLogger(__name__)


class OrderItemInline(admin.TabularInline):
    """
    Позиции заказа внутри страницы заказа. Только чтение: состав меняет
    покупатель через API, администратор управляет статусом.
    """

    model = OrderItem
    extra = 0
    readonly_fields = ('product_info', 'quantity')
    can_delete = False


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Пользователи сервиса: вход по email, поле «тип пользователя»."""

    model = User
    fieldsets = (
        (None, {'fields': ('email', 'password', 'type')}),
        ('Личные данные', {'fields': ('first_name', 'last_name', 'company', 'position')}),
        ('Права доступа', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Важные даты', {'fields': ('last_login', 'date_joined')}),
    )
    list_display = ('email', 'first_name', 'last_name', 'type', 'is_active', 'is_staff')
    list_filter = ('type', 'is_active', 'is_staff')
    search_fields = ('email', 'first_name', 'last_name')


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    """
    Магазины: просмотр + запуск импорта прайса (Celery-задача do_import).

    Импорт доступен двумя способами:
    * кнопка «Импортировать прайс» на странице магазина (кастомный view);
    * групповое действие в списке магазинов.
    """

    list_display = ('name', 'url', 'state', 'user', 'import_link')
    list_filter = ('state',)
    search_fields = ('name',)

    @admin.display(description='Импорт прайса')
    def import_link(self, obj):
        """Ссылка на страницу запуска задачи do_import для магазина."""
        url = reverse('admin:backend_shop_import', args=[obj.pk])
        return format_html('<a href="{}">Запустить импорт</a>', url)

    def get_urls(self):
        """Кастомный URL <id>/import/ — view запуска задачи do_import из админки."""
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:shop_id>/import/',
                self.admin_site.admin_view(self.import_view),
                name='backend_shop_import',
            ),
        ]
        return custom_urls + urls

    def import_view(self, request, shop_id):
        """
        View запуска Celery-задачи do_import из админки (Этап 7).

        GET  — страница с информацией о магазине и кнопкой запуска;
        POST — запуск задачи импорта прайса по ссылке shop.url.
        """
        shop = self.get_object(request, shop_id)
        if shop is None:
            self.message_user(request, 'Магазин не найден', level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:backend_shop_changelist'))

        if request.method == 'POST':
            if not shop.url:
                self.message_user(
                    request,
                    f'У магазина «{shop.name}» не задана ссылка на прайс (поле url)',
                    level=messages.ERROR,
                )
            else:
                result = run_task(do_import, shop.url, shop.user_id)
                if isinstance(result, str):
                    # Celery выключена — импорт выполнен синхронно
                    self.message_user(
                        request,
                        f'Прайс магазина «{result}» успешно загружен (синхронный режим).',
                    )
                else:
                    self.message_user(
                        request,
                        f'Задача do_import для магазина «{shop.name}» запущена в фоне.',
                    )
            return HttpResponseRedirect('')

        context = {
            **self.admin_site.each_context(request),
            'title': f'Импорт прайса: {shop.name}',
            'shop': shop,
            'opts': self.model._meta,
        }
        return TemplateResponse(request, 'backend/admin/import_page.html', context)

    def run_import_action(self, request, queryset):
        """Групповое действие списка: запуск do_import для выбранных магазинов."""
        launched = 0
        for shop in queryset:
            if not shop.url:
                self.message_user(
                    request,
                    f'Магазин «{shop.name}» пропущен: не задана ссылка на прайс',
                    level=messages.WARNING,
                )
                continue
            run_task(do_import, shop.url, shop.user_id)
            launched += 1
        if launched:
            self.message_user(
                request, f'Запущен импорт прайсов: {launched} магазин(ов).'
            )

    run_import_action.short_description = 'Импортировать прайс (Celery-задача do_import)'


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """
    Админка заказов (Этап 6): смена статуса заказа и уведомление клиента.

    При сохранении заказа с изменившимся статусом покупателю автоматически
    отправляется email (описание сервиса: «при любом изменении статуса
    заказа пользователю на email отправляется уведомление»).
    """

    list_display = ('id', 'user', 'dt', 'state', 'get_total', 'get_contact')
    list_filter = ('state',)
    search_fields = ('user__email', 'contact__city')
    date_hierarchy = 'dt'
    readonly_fields = ('dt', 'user')
    fields = ('user', 'dt', 'state', 'contact')
    inlines = (OrderItemInline,)

    @admin.display(description='Сумма, руб.')
    def get_total(self, obj):
        """Итоговая сумма заказа в колонке списка."""
        return obj.total_sum

    @admin.display(description='Адрес доставки')
    def get_contact(self, obj):
        """Краткий адрес доставки в колонке списка."""
        if obj.contact:
            return f'{obj.contact.city}, {obj.contact.street} {obj.contact.house}'
        return '—'

    def save_model(self, request, obj, form, change):
        """
        Уведомление отправляется только при реальном изменении статуса,
        а не при каждом сохранении страницы заказа.
        """
        state_changed = False
        if change:
            old_state = (
                Order.objects.filter(pk=obj.pk).values_list('state', flat=True).first()
            )
            state_changed = old_state != obj.state

        super().save_model(request, obj, form, change)

        if state_changed and obj.state != 'basket':
            send_order_state_notification(obj)
            messages.info(
                request,
                f'Статус заказа №{obj.id} изменён — покупателю ({obj.user.email}) '
                f'отправлено email-уведомление.',
            )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category')
    list_filter = ('category',)
    search_fields = ('name',)


@admin.register(ProductInfo)
class ProductInfoAdmin(admin.ModelAdmin):
    list_display = ('product', 'shop', 'model', 'price', 'price_rrc', 'quantity')
    list_filter = ('shop',)
    search_fields = ('product__name', 'model')


@admin.register(Parameter)
class ParameterAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(ProductParameter)
class ProductParameterAdmin(admin.ModelAdmin):
    list_display = ('product_info', 'parameter', 'value')
    list_filter = ('parameter',)
    search_fields = ('value',)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('user', 'city', 'street', 'house', 'phone')
    search_fields = ('user__email', 'city', 'street')


@admin.register(ConfirmEmailToken)
class ConfirmEmailTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'key', 'created_at')
