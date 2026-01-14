FROM python:3.10-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем список зависимостей
COPY requirements.txt .

# Устанавливаем библиотеки
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все остальные файлы проекта
COPY . .

# Команда для запуска бота
CMD ["python", "bot.py"]