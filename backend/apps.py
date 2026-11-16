from django.apps import AppConfig


class BackendConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'backend'
    verbose_name = 'Сервис автоматизации закупок'

    def ready(self):
        # Регистрируем сигналы приложения: отправка писем при регистрации,
        # подтверждении заказа и т.д. (см. backend/signals.py)
        import backend.signals  # noqa: F401
