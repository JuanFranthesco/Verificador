# Usamos uma imagem base oficial do Python
FROM python:3.11-slim

# Definimos um diretório de trabalho dentro do nosso contêiner
WORKDIR /app

# ATUALIZAMOS, INSTALAMOS E DEPOIS LIMPAMOS O CACHE
# A adição do 'rm -rf' no final é a otimização
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-por poppler-utils && rm -rf /var/lib/apt/lists/*

# Copiamos nosso arquivo de requisitos para dentro do contêiner
COPY requirements.txt .

# Instalamos as bibliotecas Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos todo o resto do nosso código (app.py, templates/) para o contêiner
COPY . .

# Expomos a porta que o Render vai usar
EXPOSE 10000

# O comando final para iniciar nosso aplicativo
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]
