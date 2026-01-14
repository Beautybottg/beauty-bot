# Использование легковесного образа на базе Python 3.10
FROM python:3.10-slim

# Устанавливаем системные зависимости для работы с PostgreSQL (libpq) и загрузки сертификатов (ca-certificates, wget)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    ca-certificates \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Создаем папку для сертификата Яндекса
RUN mkdir -p /root/.postgresql

# Скачиваем корневой сертификат Яндекс Облака
RUN wget "https://storage.yandexcloud.net/cloud-certs/CA.pem" \
    -O /root/.postgresql/root.crt && \
    chmod 0600 /root/.postgresql/root.crt

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем и устанавливаем зависимости Python
# Используем psycopg2-binary для корректной работы в Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код бота в контейнер
COPY . .

# Указываем переменную окружения для поиска сертификата библиотекой psycopg2
ENV PGSSLROOTCERT=/root/.postgresql/root.crt

# Запуск бота
CMD ["python", "bot.py"]
