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

Текущая рабочая схема: frontend запускается локально, а все запросы `/api` проксируются на backend на `Backgosha`.
Это закреплено в `web_frontend/.env.local`:

```env
VITE_BACKEND_URL=http://111.88.112.76:18080
```

Если `.env.local` отсутствует, Vite использует fallback `http://127.0.0.1:18080`.
После изменения `.env.local` dev-сервер нужно перезапустить.

## Авторизация web wizard

Перед началом сессии пользователь вводит:
- **Telegram ID**

Backend:
1. принимает `TelegramID` или совместимый алиас `BitrixID`;
2. при каждом обращении обновляет `AtWork` из Yandex S3 для этого ID;
3. ищет профиль и доступные базы по ID;
4. при успехе ставит `auth_verified=true` и возвращает шаг `select_base`;
5. при ошибке возвращает шаг `select_user` с официальным сообщением и ссылкой на помощь в регистрации.

Обновление из S3 выполняется точечно: backend не скачивает весь bucket, а находит JSON-файлы, связанные с введенным ID, и заново загружает их в `AtWork`. Это защищает от устаревших данных, например если у пользователя изменилась база, ссылка подключения или сам файл был исправлен в Yandex Bucket.

Сообщение для не найденного ID:

```text
Пользователь с указанным ID не найден. Проверьте корректность введенных данных. Если ID указан верно, обратитесь к ответственному сотруднику для помощи в регистрации.
```

Кнопка в UI:

```text
Помощь в регистрации → https://portal.rt24.ru/company/personal/user/4212/
```

Для `access_denied` frontend не показывает технические поля S3/индекса пользователю.

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
  "TelegramID": "1657181189"
}
```

Для Bitrix можно использовать `BitrixID` вместо `TelegramID`.

### Backend на Backgosha

На сервере `Backgosha` backend работает в Docker:

```bash
cd /home/ProTires/web_backend
docker compose up -d --build
```

Контейнер:
- `protires-backend`
- порт `18080`
- runtime volumes:
  - `./runtime/Users:/app/web_backend/Users`
  - `./runtime/AtWork:/app/web_backend/AtWork`
  - `./runtime/log_upload:/app/web_backend/log_upload`

Проверка на сервере:

```bash
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/api/health
```

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

