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
### Current production-like setup

The usual workflow is local frontend + backend on `Backgosha`.
`web_frontend/.env.local` sets:

```env
VITE_BACKEND_URL=http://111.88.112.76:18080
```

Vite reads this via `loadEnv` in `vite.config.js`, so local browser requests to `/api` are proxied to the server backend.
Start only the local frontend:

```powershell
cd B:\Tires_Bitrix\web_frontend
npm run dev -- --port 5173
```

Open `http://127.0.0.1:5173`.

### Local backend fallback

If you need to test against a local backend instead, change `web_frontend/.env.local` to `http://127.0.0.1:18080` or temporarily remove it, then start backend:

```powershell
cd B:\Tires_Bitrix\web_backend
docker compose up -d --build
```

Default backend URL is auto-filled as:
- `/api`

In dev mode Vite proxies `/api` to:
- `VITE_BACKEND_URL` из `.env.local`, сейчас `http://111.88.112.76:18080`;
- fallback `http://127.0.0.1:18080`, если env-переменная не задана.

Do not put a full external URL into the UI field in dev mode unless the backend explicitly allows CORS from the Vite origin — use `/api`.

## Authentication
- На старте пользователь вводит только **Telegram ID**.
- Backend при каждом вводе ID точечно обновляет файлы этого пользователя из Yandex S3 в `AtWork/`.
- После обновления backend ищет профиль по ID в `AtWork/`.
- Если ID найден, backend возвращает выбор базы.
- Если ID не найден, backend возвращает `access_denied`, а UI показывает официальный текст и кнопку «Помощь в регистрации» со ссылкой на ответственного сотрудника.

Текст для не найденного ID:

```text
Пользователь с указанным ID не найден. Проверьте корректность введенных данных. Если ID указан верно, обратитесь к ответственному сотруднику для помощи в регистрации.
```

Кнопка:

```text
Помощь в регистрации → https://portal.rt24.ru/company/personal/user/4212/
```

## Behavior
- UI renders from backend state (`GET /flow/{session_id}`)
- UI does not keep business logic locally
- next step is blocked until current step is confirmed

## Troubleshooting
- Если поле «API URL» содержит полный внешний URL — замените на `/api` и перезапустите Vite после изменения конфига.
- Цель прокси меняется переменной `VITE_BACKEND_URL` в `.env.local` (требует перезапуска dev-сервера).
- Если пользователь есть в Yandex Bucket, но авторизация возвращает `access_denied`, проверьте backend-индекс `AtWork/.index_bitrix.json`, manifest `AtWork/.s3_manifest.json`, наличие `boto3` в окружении backend и S3-доступы; frontend отправляет только `{ TelegramID }`.

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

