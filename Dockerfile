FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY kraken_bot ./kraken_bot
COPY pyproject.toml .

EXPOSE 8080

CMD ["python", "-m", "kraken_bot.webui", "--config", "/config/config.yaml", "--host", "0.0.0.0", "--port", "8080", "--with-bot-loop"]
