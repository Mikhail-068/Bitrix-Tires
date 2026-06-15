FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app/web_backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r ./requirements.txt

COPY app ./app
COPY DATA_txt ./DATA_txt
COPY DEMO_img ./DEMO_img
COPY dir_json ./dir_json

# AtWork is synchronized from S3 on demand; Users starts empty.
RUN mkdir -p /app/web_backend/AtWork /app/web_backend/Users

EXPOSE 18080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-18080}"]
