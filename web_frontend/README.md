# Web Frontend

Wizard SPA that works only through backend flow API (`/api/flow/*`).

## Run
```powershell
cd B:\Tires_Bitrix\web_frontend
npm install
npm run dev -- --port 5173
```

Open: `http://127.0.0.1:5173`

> Если `npm install` зависает на установке Playwright, отключите загрузку браузеров:
> `$env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1; npm install`

## Connect to backend container
1. Start backend container:
```powershell
cd B:\Tires_Bitrix\web_backend
docker compose up -d --build
```
2. Start frontend dev server:
```powershell
cd B:\Tires_Bitrix\web_frontend
npm run dev -- --port 5173
```
3. Open `http://127.0.0.1:5173`

Default backend URL is auto-filled as:
- `/api`

In dev mode Vite proxies `/api` to:
- `http://127.0.0.1:18080` (по умолчанию)
- или `VITE_BACKEND_URL`, если переменная задана перед запуском dev-сервера

Do not put a full external URL into the UI field in dev mode unless the backend explicitly allows CORS from the Vite origin — use `/api`.

## Authentication
- На старте пользователь вводит **Telegram ID** и **фамилию**.
- Backend сверяет данные с профилем из `AtWork/` (синхронизируется из Yandex S3).
- При несовпадении — ошибка «В доступе отказано, проверьте введенные данные», форма ввода открывается заново.

## Behavior
- UI renders from backend state (`GET /flow/{session_id}`)
- UI does not keep business logic locally
- next step is blocked until current step is confirmed

## Troubleshooting
- Если поле «API URL» содержит полный внешний URL — замените на `/api` и перезапустите Vite после изменения конфига.
- Цель прокси меняется переменной `VITE_BACKEND_URL` (требует перезапуска dev-сервера).
- Если пользователь есть в `AtWork/`, но авторизация возвращает «В доступе отказано», проверьте backend-индекс `AtWork/.index_bitrix.json` и наличие `boto3` в окружении backend; frontend отправляет только `{ TelegramID, surname }`.

## ⚠️ Если фото загружается, но шаг не меняется (снова «Перетащите фото»)

Это означает, что backend не может достучаться до ML-контейнеров. Проверьте:

1. **Backend `.env`** — URL-ы ML-сервисов должны указывать на правильный сервер:
   ```env
   # ✅ Правильно (ML на отдельном сервере)
   CAR_NUMBER_API_URL=http://5.35.10.157:11436/recognize
   TIRE_NUMBER_API_URL=http://5.35.10.157:11435/recognize
   TIRE_ANALYSIS_API_URL=http://5.35.10.157:11437/analyze
   
   # ❌ Неправильно (IP backend вместо ML-сервера)
   # CAR_NUMBER_API_URL=http://111.88.112.76:11436/recognize
   ```

2. **Проверьте доступность ML с машины backend**:
   ```powershell
   curl http://5.35.10.157:11436/health
   curl http://5.35.10.157:11435/health
   curl http://5.35.10.157:11437/health
   ```

3. **Перезапустите backend** после изменения `.env`.
