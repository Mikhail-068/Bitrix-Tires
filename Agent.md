# Agent.md
отвечай по возможности коротко

## Purpose
Internal project memo for Tires_Bitrix (web copy of ProTires).

## Current Product Model
- One backend API server and separate ML services.
- Backend orchestrates the full wizard flow (`/api/flow/*`).
- ML services are called by backend for recognition/analysis.
- Frontend (React wizard or Bitrix frontend) is a thin client: render by `step`, send `action`, upload images.

## Production Endpoints
- Backend base URL: `http://111.88.112.76:18080/api`
- Backend health: `http://111.88.112.76:18080/health`, `http://111.88.112.76:18080/api/health`
- ML host (direct): `http://5.35.10.157`
  - Car number: `:11436`
  - Tire number: `:11435`
  - Tire analysis: `:11437`

## Auth (Web / Bitrix start)
Start requires user ID and surname:

```json
{
  "BitrixID": "1657181189",
  "surname": "Титов"
}
```

Legacy aliases still accepted:
- `TelegramID` / `telegram_id` instead of `BitrixID`
- `last_name` / `family_name` instead of `surname`

On mismatch backend returns:
- `step`: `select_user`
- `errors[0].message`: `В доступе отказано, проверьте введенные данные`

## API Contract (External)
- Start flow: `POST /api/flow/start` with `BitrixID` + `surname`.
- In responses/UI payload use `bitrix_id`.

## Current Backend Behavior
- Session-driven flow:
  - `POST /api/flow/start`
  - `GET /api/flow/{session_id}`
  - `POST /api/flow/{session_id}/action`
  - `POST /api/flow/{session_id}/upload`
  - `GET /api/flow/{session_id}/file/{file_name}`
- On start backend syncs AtWork from S3 for the user and verifies surname before `select_base`.

## Frontend Integration Rules
- Never keep local step state as truth.
- Always render strictly from latest backend response (`step`, `ui_payload`, `allowed_actions`, `errors`).
- Send only actions present in `allowed_actions`.
- Upload only when `upload_image` is allowed.
- Keep and reuse `session_id` until `finished`.

## Dev Defaults
- Frontend: React + Vite in `web_frontend/`
- Vite proxy default: `http://127.0.0.1:18080`
- Override with `VITE_BACKEND_URL`

## Source of Truth Files
- Backend flow logic: `web_backend/app/flow_engine.py`
- Backend routes: `web_backend/app/routes.py`
- Frontend wizard: `web_frontend/src/App.jsx`
- Bitrix API documentation: `docs/bitrix_api.md`
