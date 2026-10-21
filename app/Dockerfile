FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NOTIFY_DATABASE_PATH=/data/notifications.sqlite3

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY notification_service ./notification_service
COPY main.py .

RUN groupadd --gid 10001 notification \
    && useradd --uid 10001 --gid notification --no-create-home notification \
    && mkdir -p /data && chown notification:notification /data

USER notification

EXPOSE 5000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]
