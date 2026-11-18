"""
Маршруты REST API приложения backend (все — под префиксом /api/v1/).

Соответствуют спецификации дипломного задания (Postman-коллекция задания):

Пользователи:
    POST /user/register              — регистрация
    POST /user/register/confirm      — подтверждение email
    POST /user/login                 — вход (получение токена)
    GET|POST /user/details           — данные учётной записи
    GET|POST|PUT|DELETE /user/contact— контакты/адреса доставки
    POST /user/password_reset        — запрос сброса пароля
    POST /user/password_reset/confirm— подтверждение сброса пароля

Каталог:
    GET /categories                  — список категорий
    GET /shops                       — список активных магазинов
    GET /products                    — каталог товаров (фильтры + поиск)
    GET /products/<id>               — спецификация отдельного товара

Заказы:
    GET|POST|PUT|DELETE /basket      — корзина
    GET|POST /order                  — заказы и подтверждение заказа

Партнёры (поставщики):
    POST /partner/update             — обновление прайса (импорт YAML)
    GET|POST /partner/state          — статус приёма заказов
    GET /partner/orders              — заказы с товарами магазина
"""

from django.urls import path
from django_rest_passwordreset.views import (
    reset_password_confirm,
    reset_password_request_token,
)

from backend.views import (
    AccountDetails,
    BasketView,
    CategoryView,
    ConfirmAccount,
    ContactView,
    LoginAccount,
    OrderView,
    PartnerOrders,
    PartnerState,
    PartnerUpdate,
    ProductInfoDetailView,
    ProductInfoView,
    RegisterAccount,
    ShopView,
)

app_name = 'backend'

urlpatterns = [
    # Партнёрские (поставщикские) эндпоинты
    path('partner/update', PartnerUpdate.as_view(), name='partner-update'),
    path('partner/state', PartnerState.as_view(), name='partner-state'),
    path('partner/orders', PartnerOrders.as_view(), name='partner-orders'),

    # Пользователи
    path('user/register', RegisterAccount.as_view(), name='user-register'),
    path('user/register/confirm', ConfirmAccount.as_view(), name='user-register-confirm'),
    path('user/details', AccountDetails.as_view(), name='user-details'),
    path('user/contact', ContactView.as_view(), name='user-contact'),
    path('user/login', LoginAccount.as_view(), name='user-login'),
    # Восстановление пароля (библиотека django-rest-passwordreset)
    path('user/password_reset', reset_password_request_token, name='password-reset'),
    path(
        'user/password_reset/confirm',
        reset_password_confirm,
        name='password-reset-confirm',
    ),

    # Каталог
    path('categories', CategoryView.as_view(), name='categories'),
    path('shops', ShopView.as_view(), name='shops'),
    path('products', ProductInfoView.as_view(), name='products'),
    path('products/<int:pk>', ProductInfoDetailView.as_view(), name='product-detail'),

    # Корзина и заказы
    path('basket', BasketView.as_view(), name='basket'),
    path('order', OrderView.as_view(), name='order'),
]
