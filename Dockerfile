# Dockerfile дипломного проекта «Сервис автоматизации закупок»
# Образ: Python 3.12 (задание требует Python >= 3.10)
FROM python:3.12-slim

# Не писать .pyc и не буферизовать stdout — корректные логи в Docker
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Сначала копируем только зависимости — слой кэшируется отдельно от кода
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код проекта
COPY . .

EXPOSE 8000

# Команда по умолчанию: запуск development-сервера.
# Инструкция сборки и запуска — в README.md (раздел «Запуск через Docker»).
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
