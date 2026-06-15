# Tires_Bitrix

Отдельная web-копия ProTires для Bitrix24 и standalone browser wizard.

Стек:
- `web_backend/` — FastAPI backend, flow engine, S3 sync
- `web_frontend/` — React + Vite wizard
- `docs/` — документация API и архитектуры

## Быстрый старт

### Backend

```powershell
cd B:\Tires_Bitrix\web_backend
python -m pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 18080 --reload
```

Docker:

```powershell
cd B:\Tires_Bitrix\web_backend
docker compose up -d --build
```

Проверка:

```text
http://127.0.0.1:18080/health
http://127.0.0.1:18080/api/health
```

### Frontend

```powershell
cd B:\Tires_Bitrix\web_frontend
$env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1"
npm install
npm run dev
```

Открыть: `http://127.0.0.1:5173`

По умолчанию Vite проксирует `/api` на `http://127.0.0.1:18080`.
Для удалённого backend:

```powershell
$env:VITE_BACKEND_URL = "http://111.88.112.76:18080"
npm run dev
```

## Авторизация web wizard

Перед началом сессии пользователь вводит:
- **Telegram ID**
- **Фамилия**

Backend:
1. обновляет AtWork из Yandex S3 для этого ID;
2. сверяет фамилию с ФИО из базы;
3. при ошибке возвращает шаг `select_user` и сообщение: `В доступе отказано, проверьте введенные данные`.

Старт API:

```json
POST /api/flow/start
{
  "TelegramID": "1657181189",
  "surname": "Титов"
}
```

Для Bitrix можно использовать `BitrixID` вместо `TelegramID` и передать фамилию из профиля пользователя.

## Данные проекта

- `DATA_txt/`, `DEMO_img/`, `dir_json/` — локальные данные для backend
- `web_backend/DATA_txt`, `web_backend/DEMO_img`, `web_backend/dir_json` — копии для Docker build

## Документация

- [docs/README.md](docs/README.md) — обзор
- [docs/bitrix_api.md](docs/bitrix_api.md) — API для Bitrix и web
- [docs/Auth.md](docs/Auth.md) — S3 и авторизация
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — архитектура
- [Agent.md](Agent.md) — правила интеграции
