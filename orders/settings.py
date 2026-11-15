"""
Настройки Django-проекта «orders» — backend сервиса автоматизации закупок
в розничной сети (дипломный проект курса «Python-разработчик: расширенный курс»).

Все чувствительные и окружение-зависимые параметры читаются из переменных
окружения (см. .env.example), чтобы один и тот же код работал и при локальном
запуске, и в docker-compose, без изменения исходников.
"""

import os
import sys
from pathlib import Path

# Базовая директория проекта: /path/to/diplom
BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: str = 'False') -> bool:
    """Читает булеву переменную окружения ('true', '1', 'yes', 'on')."""
    return os.getenv(name, default).strip().lower() in ('true', '1', 'yes', 'on')


def env_list(name: str, default: str = '') -> list:
    """Читает переменную окружения со списком значений, разделённых запятой."""
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


# Безопасность
# В продакшене секретный ключ обязательно задаётся переменной окружения DJANGO_SECRET_KEY
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-dev-key-change-me-in-production')
DEBUG = env_bool('DJANGO_DEBUG', 'True')
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', '*')

# Приложения
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Сторонние пакеты
    'rest_framework',            # Django REST Framework — ядро REST API
    'rest_framework.authtoken',  # токенная аутентификация (Authorization: Token <key>)
    'django_rest_passwordreset', # восстановление пароля через API
    'drf_spectacular',           # автоматическая OpenAPI/Swagger документация
    # Приложения проекта
    'backend',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'orders.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # Общая папка шаблонов проекта (используется админкой импорта прайса)
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'orders.wsgi.application'

# База данных
# По умолчанию — SQLite (просто для локального запуска).
# Если заданы переменные POSTGRES_*, проект переключается на PostgreSQL
# (эта конфигурация используется в docker-compose).
if os.getenv('POSTGRES_HOST'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('POSTGRES_DB', 'orders'),
            'USER': os.getenv('POSTGRES_USER', 'orders'),
            'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'orders'),
            'HOST': os.getenv('POSTGRES_HOST', 'postgres'),
            'PORT': os.getenv('POSTGRES_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Валидаторы паролей (стандартные проверки сложности)
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Локализация
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = os.getenv('DJANGO_TIME_ZONE', 'Europe/Moscow')
USE_I18N = True
USE_TZ = True

# Статика
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Собственная модель пользователя (вход по email, а не по username)
AUTH_USER_MODEL = 'backend.User'

# Настройки Django REST Framework
REST_FRAMEWORK = {
    # Аутентификация по токену: заголовок Authorization: Token <ключ>
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.TokenAuthentication',
    ),
    # Схема OpenAPI для drf-spectacular
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ),
}

# Настройки Swagger/OpenAPI документации (/api/schema/, /api/docs/)
SPECTACULAR_SETTINGS = {
    'TITLE': 'Сервис автоматизации закупок',
    'DESCRIPTION': 'REST API дипломного проекта: каталог товаров нескольких магазинов, '
                   'корзина, оформление заказов, загрузка прайсов поставщиками.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# ---------------------------------------------------------------------------
# Настройки почты
#
# По умолчанию используется консольный backend: письма выводятся в stdout —
# это удобно при локальной разработке. В docker-compose включается SMTP-ретранслятор
# MailHog (EMAIL_HOST=mailhog), письма попадают в веб-интерфейс http://localhost:8025.
# Для боевого SMTP достаточно задать переменные окружения EMAIL_HOST, EMAIL_PORT,
# EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_USE_TLS/EMAIL_USE_SSL.
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend'
)
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = os.getenv('EMAIL_PORT', '25')
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', 'False')
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', 'False')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'no-reply@orders-service.local')

# Email администратора: на него отправляется «накладная» после оформления заказа
# (для исполнения заказа сотрудниками). Если не задан — письмо администратору не отправляется.
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', '')

# ---------------------------------------------------------------------------
# Celery: вынос «медленных» операций (отправка писем, импорт прайса) в фон.
#
# USE_CELERY=True — задачи уходят в брокер и выполняются воркером
# (запуск: celery -A orders worker --loglevel=info).
# USE_CELERY=False — те же функции выполняются синхронно, без брокера:
# проект остаётся полностью работоспособным при локальном запуске без Redis.
# ---------------------------------------------------------------------------
USE_CELERY = env_bool('USE_CELERY', 'False')
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# При запуске тестов письма складываются в память (locmem), а задачи Celery
# выполняются синхронно — так тесты не зависят от внешних сервисов.
if 'test' in sys.argv:
    EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

# Максимальное количество адресов доставки у одного пользователя
# (по описанию сервиса: «до 5 записей»)
MAX_USER_ADDRESSES = int(os.getenv('MAX_USER_ADDRESSES', '5'))

# Тип первичных ключей по умолчанию
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
