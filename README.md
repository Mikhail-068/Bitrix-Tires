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

Для быстрого поиска backend поддерживает локальный индекс `AtWork/.index_bitrix.json`.
Индекс пересобирается автоматически при изменении JSON-файлов и не должен включать служебные файлы `.index_bitrix.json`, `.index_telegram.json`, `.s3_manifest.json`.
Если пользователь есть в `AtWork/`, но web всё равно пишет «доступ отказан», сначала проверьте индекс:

```powershell
cd B:\Tires_Bitrix
@'
from web_backend.app.flow_engine import FlowEngine
engine = FlowEngine()
idx = engine._refresh_atwork_index()
print(len(idx.get("files", {})), len(idx.get("by_bitrix", {})))
print(idx.get("by_bitrix", {}).get("5652315164"))
'@ | python -
```

S3-синхронизация требует установленных `boto3` и `botocore` из `web_backend/requirements.txt`.
Без них backend продолжит работать по локальному `AtWork/`, но будет писать в лог `boto3 is not installed, S3 user sync skipped`.

Старт API:

```json
POST /api/flow/start
{
  "TelegramID": "1657181189",
  "surname": "Титов"
}
```

Для Bitrix можно использовать `BitrixID` вместо `TelegramID` и передать фамилию из профиля пользователя.

## ⚠️ Типичная проблема: ML-контейнеры недоступны

Если при загрузке фото в web-интерфейсе шаг не меняется (снова показывает «Перетащите фото») или номер авто не распознаётся — проверьте настройки backend.

### Причина
Backend (`web_backend`) проксирует фото в ML-контейнеры для распознавания. Если URL в `.env` неверен — backend молча падает и возвращает тот же шаг.

### Правильная конфигурация `.env`

| Сервис | Backend API | ML-контейнеры |
|--------|-------------|---------------|
| Хост | `111.88.112.76` | `5.35.10.157` |
| Car number | `18080/api/car-number/recognize` | `11436/recognize` |
| Tire number | `18080/api/tire-number/recognize` | `11435/recognize` |
| Tire analysis | `18080/api/tire-analysis/analyze` | `11437/analyze` |

```env
# ✅ Правильно — ML-контейнеры на отдельном сервере
CAR_NUMBER_API_URL=http://5.35.10.157:11436/recognize
TIRE_NUMBER_API_URL=http://5.35.10.157:11435/recognize
TIRE_ANALYSIS_API_URL=http://5.35.10.157:11437/analyze

# ❌ Неправильно — IP backend ≠ IP ML-сервера
# CAR_NUMBER_API_URL=http://111.88.112.76:11436/recognize
```

### Диагностика
```bash
# С машины backend:
curl http://5.35.10.157:11436/health
curl http://5.35.10.157:11435/health
curl http://5.35.10.157:11437/health
```

### Исправление
1. Отредактируйте `web_backend/.env`
2. Перезапустите backend (`uvicorn` или `docker compose up -d --build`)
3. Проверьте загрузку фото снова

## Данные проекта

- `DATA_txt/`, `DEMO_img/`, `dir_json/` — локальные данные для backend
- `web_backend/DATA_txt`, `web_backend/DEMO_img`, `web_backend/dir_json` — копии для Docker build

## Документация

- [docs/README.md](docs/README.md) — обзор
- [docs/bitrix_api.md](docs/bitrix_api.md) — API для Bitrix и web
- [docs/Auth.md](docs/Auth.md) — S3 и авторизация
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — архитектура
- [Agent.md](Agent.md) — правила интеграции
