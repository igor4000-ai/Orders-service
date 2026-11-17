"""
Management-команда загрузки прайса из YAML-файла.

Используется на Этапе 3 дипломного проекта для загрузки товаров
из приложенных к заданию файлов, а также для быстрого наполнения
демо-данными.

Примеры:
    python manage.py load_yaml data/shop1.yaml
    python manage.py load_yaml --url https://example.com/shop1.yaml
    python manage.py load_yaml data/shop1.yaml --user 5   # привязать магазин к поставщику
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from backend.importer import ImportValidationError, import_goods, parse_yaml_price_list


class Command(BaseCommand):
    help = 'Загружает товары в каталог из YAML-файла прайса (локальный файл или URL)'

    def add_arguments(self, parser):
        parser.add_argument(
            'file',
            nargs='?',
            type=str,
            help='Путь к локальному YAML-файлу прайса',
        )
        parser.add_argument(
            '--url',
            type=str,
            help='Ссылка (URL) на YAML-файл прайса',
        )
        parser.add_argument(
            '--user',
            type=int,
            help='ID пользователя-поставщика, к которому привязать магазин',
        )

    def handle(self, *args, **options):
        url = options.get('url')
        file_path = options.get('file')
        user_id = options.get('user')

        if not url and not file_path:
            raise CommandError('Укажите путь к файлу или ссылку через --url')

        try:
            if url:
                from requests import get

                response = get(url)
                response.raise_for_status()
                stream = response.content
                source = url
            else:
                path = Path(file_path)
                if not path.is_file():
                    raise CommandError(f'Файл не найден: {file_path}')
                stream = path.read_bytes()
                source = str(path)

            data = parse_yaml_price_list(stream)
            shop = import_goods(data, shop_user_id=user_id)
        except ImportValidationError as exc:
            raise CommandError(f'Ошибка импорта: {exc}') from exc
        except Exception as exc:
            raise CommandError(f'Ошибка загрузки {source}: {exc}') from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'Загружено товаров: {len(data["goods"])} '
                f'(магазин «{shop.name}», источник: {source})'
            )
        )
