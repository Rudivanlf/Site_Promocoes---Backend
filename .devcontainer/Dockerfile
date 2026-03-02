FROM python:3.12-slim

# Evita que o Python gere arquivos .pyc e permite logs em tempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /code

# Instala dependências do sistema e do Python
COPY requirements.txt /code/
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código
COPY . /code/

CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:$PORT"]