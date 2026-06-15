# Web Frontend

React + Vite wizard that works only through backend flow API (`/api/flow/*`).

## Run
```powershell
cd B:\Tires_Bitrix\web_frontend
$env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1"
npm install
npm run dev
```

Open: `http://127.0.0.1:5173`

## Backend connection

1. Start backend:
```powershell
cd B:\Tires_Bitrix\web_backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 18080 --reload
```

2. Start frontend:
```powershell
cd B:\Tires_Bitrix\web_frontend
npm run dev
```

Default API root in UI: `/api`

Dev proxy target:
- `http://127.0.0.1:18080` by default
- override with `VITE_BACKEND_URL`, for example:
```powershell
$env:VITE_BACKEND_URL = "http://111.88.112.76:18080"
npm run dev
```

## Auth screen

Before session start user enters:
- Telegram ID
- Surname

Backend validates the pair against AtWork/S3. On mismatch user stays on auth screen with:
`В доступе отказано, проверьте введенные данные`.

## Behavior
- UI renders from backend state (`GET /flow/{session_id}`)
- UI does not keep business logic locally
- next step is blocked until current step is confirmed

## Troubleshooting
- Use `Ctrl+F5` after frontend updates
- If `npm install` hangs, set `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`
- Do not use old `python -m http.server` flow for `app.js`; this project uses Vite + React
