# Дипломный проект «Backend-приложение для автоматизации закупок»

Профессия «Python-разработчик: расширенный курс» (Нетология).

REST API-сервис для автоматизации закупок в розничной сети: единый каталог
товаров нескольких поставщиков, корзина, оформление заказов с email-подтверждениями,
загрузка прайсов поставщиками из YAML-файлов.

## Возможности

**Базовая часть (обязательная):**

* регистрация покупателей с подтверждением email одноразовым токеном;
* авторизация по токену (Django REST Framework TokenAuthentication);
* восстановление пароля через email;
* каталог товаров нескольких магазинов с фильтрацией (магазин, категория)
  и текстовым поиском (название, модель, категория, характеристики);
* настраиваемые поля (характеристики) товаров — состав задаётся данными, без правки схемы БД;
* импорт товаров поставщиком из YAML-файла по ссылке (POST /partner/update);
* корзина: добавление товаров разных магазинов, изменение количества, удаление;
* адреса доставки (до 5 на пользователя) и телефон;
* оформление заказа с фиксацией адреса и отправкой писем:
  подтверждение покупателю + накладная администратору сервиса;
* список заказов и детали заказа;
* партнёрские эндпоинты: статус приёма заказов, список заказов с товарами магазина.

**Продвинутая часть (Этапы 6–8):**

* админка Django: управление заказами и их статусами с автоматическим
  email-уведомлением покупателя при каждой смене статуса;
* Celery-задачи `send_email` и `do_import` — «медленные» операции вынесены в фон;
* view запуска задачи `do_import` прямо из админки (кнопка на странице магазина)
  и групповое действие в списке магазинов;
* docker-compose: приложение + PostgreSQL + Redis + воркер Celery + MailHog
  (веб-интерфейс для просмотра всех отправленных писем).

## Технологии

| Компонент | Назначение |
|---|---|
| Python 3.10+ | язык |
| Django 5 | веб-фреймворк |
| Django REST Framework | REST API |
| django-rest-passwordreset | восстановление пароля через API |
| drf-spectacular | OpenAPI/Swagger документация |
| Celery + Redis | фоновые задачи |
| PyYAML / requests | разбор прайсов и загрузка по URL |
| ujson | быстрый разбор JSON-тела запросов |
| PostgreSQL / SQLite | СУБД (SQLite для локальной разработки) |
| Docker / docker-compose | контейнеризация |

## Структура проекта

```
├── manage.py
├── requirements.txt            # зависимости
├── Dockerfile                  # образ приложения
├── docker-compose.yml          # полный стек: web, celery, redis, postgres, mailhog
├── .env.example                # пример конфигурации окружения
├── data/
│   └── shop1.yaml              # прайс из условия задания (магазин «Связной»)
├── orders/                     # конфигурация Django-проекта
│   ├── settings.py             # настройки (все параметры — через переменные окружения)
│   ├── urls.py                 # корневые маршруты
│   └── celery.py               # приложение Celery
└── backend/                    # основное приложение
    ├── models.py               # модели данных (Этап 2)
    ├── importer.py             # импорт товаров из YAML (Этап 3)
    ├── views.py                # API views (Этапы 4–5)
    ├── serializers.py          # сериализаторы
    ├── urls.py                 # маршруты API (/api/v1/...)
    ├── signals.py              # email-уведомления о событиях
    ├── tasks.py                # Celery-задачи send_email и do_import (Этап 7)
    ├── admin.py                # админка заказов и импорта (Этапы 6–7)
    ├── templates/backend/admin/import_page.html
    ├── management/commands/
    │   ├── load_yaml.py        # загрузка прайса из файла/URL
    │   └── create_demo_data.py # демо-пользователи
    ├── migrations/
    └── tests/test_api.py       # 26 интеграционных тестов полного сценария
```

## Быстрый старт (локально)

Требуется Python 3.10+.

```bash
# 1. Клонировать репозиторий и создать окружение
git clone <адрес-вашего-репозитория> orders-service
cd orders-service
python -m venv env
source env/bin/activate            # Windows: env\Scripts\activate

# 2. Установить зависимости
pip install -r requirements.txt

# 3. Применить миграции
python manage.py migrate

# 4. Загрузить товары из приложенного к заданию прайса
python manage.py load_yaml data/shop1.yaml

# 5. Создать демо-пользователей (админ, поставщик, покупатель)
python manage.py create_demo_data

# 6. Запустить сервер
python manage.py runserver
```

* API: http://127.0.0.1:8000/api/v1/
* Swagger-документация: http://127.0.0.1:8000/api/docs/
* Админка: http://127.0.0.1:8000/admin/

Письма при локальном запуске печатаются в консоль сервера
(консольный email-backend).

### Демо-учётные данные

Создаются командой `create_demo_data`:

| Роль | Email | Пароль |
|---|---|---|
| Администратор (админка) | `admin@example.com` | `admin` |
| Поставщик «Связной» | `svyaznoy@example.com` | `supplier123` |
| Покупатель | `buyer@example.com` | `buyer123` |

Пользователь-поставщик уже привязан к магазину «Связной», у магазина задана
ссылка на прайс — импорт можно запускать из админки без настройки.

Вместе с проектом поставляется `db.sqlite3` с уже загруженным каталогом
(14 товаров магазина «Связной») и демо-пользователями — можно запускать
сразу после `pip install`. Файл можно удалить и пересоздать командами выше.

## Запуск через Docker

Требуются Docker и docker compose. Один поднимает весь стек:

```bash
docker compose up --build
```

Состав стека:

| Сервис | Адрес | Описание |
|---|---|---|
| web | http://localhost:8000 | Django: миграции, демо-данные, сервер |
| celery | — | воркер задач `send_email` и `do_import` |
| db | localhost:5432 | PostgreSQL 16 (данные в volume `pgdata`) |
| redis | — | брокер Celery |
| mailhog | http://localhost:8025 | веб-интерфейс со всеми письмами сервиса |

Сборка отдельного образа приложения (без compose):

```bash
docker build -t orders-service .
docker run -p 8000:8000 orders-service
```

Параметры контейнера задаются в `docker-compose.yml` (секретный ключ,
параметры БД, email) — при необходимости переопределяются через `.env`
рядом с `docker-compose.yml` (см. `.env.example`).

## Сценарий проверки API (как в Этапе 5 задания)

Полный сценарий «пользователь авторизуется → наполняет корзину →
подтверждает заказ с адресом → получает письма → видит заказ в списке»
можно пройти curl-ом:

```bash
# 1. Регистрация (на email придёт токен подтверждения)
curl -X POST http://127.0.0.1:8000/api/v1/user/register \
  -H "Content-Type: application/json" \
  -d '{"first_name":"Мария","last_name":"Тестовая","email":"maria@example.com","password":"My-Str0ng-Pass"}'

# 2. Подтверждение email (токен — из письма)
curl -X POST http://127.0.0.1:8000/api/v1/user/register/confirm \
  -H "Content-Type: application/json" \
  -d '{"email":"maria@example.com","token":"<токен из письма>"}'

# 3. Вход — получаем токен
curl -X POST http://127.0.0.1:8000/api/v1/user/login \
  -H "Content-Type: application/json" \
  -d '{"email":"maria@example.com","password":"My-Str0ng-Pass"}'

TOKEN="..."

# 4. Каталог: все смартфоны / поиск по слову «iPhone»
curl "http://127.0.0.1:8000/api/v1/products?category_id=224"
curl "http://127.0.0.1:8000/api/v1/products?q=iPhone"

# 5. Корзина: добавить товары (id позиций — из каталога)
curl -X POST http://127.0.0.1:8000/api/v1/basket \
  -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  -d '{"items":[{"product_info":2,"quantity":1},{"product_info":7,"quantity":3}]}'

curl http://127.0.0.1:8000/api/v1/basket -H "Authorization: Token $TOKEN"

# 6. Адрес доставки
curl -X POST http://127.0.0.1:8000/api/v1/user/contact \
  -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  -d '{"city":"Москва","street":"Ленинская слобода","house":"19","phone":"+7 999 123-45-67"}'

# 7. Подтверждение заказа (id корзины и контакта — из ответов выше);
#    покупателю придёт письмо-подтверждение, администратору — накладная
curl -X POST http://127.0.0.1:8000/api/v1/order \
  -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  -d '{"id":1,"contact":1}'

# 8. Список заказов
curl http://127.0.0.1:8000/api/v1/order -H "Authorization: Token $TOKEN"
```

## API

Все маршруты — под префиксом `/api/v1/`, авторизация — заголовок
`Authorization: Token <ключ>`. Интерактивная документация: `/api/docs/`.

| Метод | URL | Описание |
|---|---|---|
| POST | `/user/register` | регистрация (first_name, last_name, email, password; company, position — опционально) |
| POST | `/user/register/confirm` | подтверждение email (email, token) |
| POST | `/user/login` | вход, возвращает Token |
| GET / POST | `/user/details` | данные учётной записи / редактирование |
| GET / POST / PUT / DELETE | `/user/contact` | адреса доставки и телефон |
| POST | `/user/password_reset` | запрос сброса пароля (email) |
| POST | `/user/password_reset/confirm` | подтверждение сброса (email, password, token) |
| GET | `/categories` | список категорий |
| GET | `/shops` | список активных магазинов |
| GET | `/products` | каталог: фильтры `shop_id`, `category_id`, поиск `q` |
| GET | `/products/<id>` | спецификация отдельного товара |
| GET / POST / PUT / DELETE | `/basket` | корзина (items: product_info + quantity) |
| GET / POST | `/order` | список заказов / подтверждение заказа (id, contact) |
| POST | `/partner/update` | обновление прайса (url на YAML) — только для типа «магазин» |
| GET / POST | `/partner/state` | статус приёма заказов магазином |
| GET | `/partner/orders` | заказы с товарами магазина поставщика |

Формат ответов ошибок: `{"Status": false, "Errors": "..."}`.

## Импорт товаров (формат прайса)

Прайс — YAML-файл вида `data/shop1.yaml`:

```yaml
shop: Связной
categories:
  - id: 224
    name: Смартфоны
goods:
  - id: 4216292          # внешний идентификатор
    category: 224
    model: apple/iphone/xs-max
    name: Смартфон Apple iPhone XS Max 512GB (золотистый)
    price: 110000
    price_rrc: 116990
    quantity: 14
    parameters:            # настраиваемые характеристики товара
      "Цвет": золотистый
```

Способы загрузки:

* API: `POST /api/v1/partner/update` с `url` (пользователь типа «магазин»);
* админка: страница магазина → «Импорт прайса» (запускает Celery-задачу `do_import`);
* командная строка: `python manage.py load_yaml data/shop1.yaml` (файл или `--url`).

Импорт выполняется в транзакции: позиции обновляются по внешнему ИД,
позиции, отсутствующие в новом прайсе, удаляются — кроме тех, на которые
ссылаются оформленные заказы (они сохраняются с нулевым остатком, чтобы
не терять историю заказов).

## Админка

* **Заказы** (`/admin/backend/order/`): состав заказа, адрес, смена статуса.
  При каждом изменении статуса покупателю автоматически уходит email.
* **Магазины** (`/admin/backend/shop/`): колонка «Импорт прайса» — страница
  запуска Celery-задачи `do_import`; групповое действие «Импортировать прайс».
* Разделы пользователей, каталога, контактов и токенов.

## Celery

Задачи определены в `backend/tasks.py`:

* `send_email` — универсальная отправка писем (все уведомления сервиса);
* `do_import` — загрузка прайса по ссылке.

Поведение переключается настройкой `USE_CELERY`:

* `False` (по умолчанию, локальный запуск) — функции выполняются синхронно,
  Redis не нужен;
* `True` (docker-compose) — задачи отправляются в Redis и выполняются
  воркером (`celery -A orders worker --loglevel=info`).

## Тесты

```bash
python manage.py test
```

26 интеграционных тестов покрывают полный сценарий из Этапа 5: регистрацию
и подтверждение email, каталог с фильтрами и поиском, корзину, ограничение
адресов, оформление заказа с письмами (подтверждение + накладная),
партнёрские эндпоинты, импорт прайса и сохранение истории заказов.

## Конфигурация

Все параметры — переменные окружения (см. `.env.example`): секретный ключ,
DEBUG, ALLOWED_HOSTS, СУБД (SQLite/PostgreSQL), параметры email,
`ADMIN_EMAIL` для накладных, `USE_CELERY`, `CELERY_BROKER_URL`,
`MAX_USER_ADDRESSES`.

## Примечания по продакшену

* задать `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, корректный `ALLOWED_HOSTS`;
* SMTP-сервер вместо MailHog (`EMAIL_*`);
* `collectstatic` + gunicorn/nginx вместо development-сервера;
* значения по умолчанию рассчитаны на разработку и демо.

---

Проект выполнен по заданию [netology-code/python-final-diplom](https://github.com/netology-code/python-final-diplom).
