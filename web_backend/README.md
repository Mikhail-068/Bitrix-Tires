# Web Backend

FastAPI backend with two layers:
- service proxy endpoints to model containers;
- stateful orchestration API `/api/flow/*` for the web wizard.

## Main endpoints
- `GET /health`
- `GET /api/health`
- `POST /api/flow/start`
- `GET /api/flow/{session_id}`
- `POST /api/flow/{session_id}/action`
- `POST /api/flow/{session_id}/upload` (`multipart/form-data`, `image`)
- `GET /api/flow/{session_id}/file/{file_name}`

## Service endpoints
- `POST /api/car-number/recognize`
- `POST /api/tire-number/recognize`
- `POST /api/tire-analysis/analyze`

## Auth on start

Standalone web wizard requires Telegram/Bitrix ID and surname:

```json
POST /api/flow/start
{
  "TelegramID": "1657181189",
  "surname": "Титов"
}
```

If ID or surname does not match AtWork data, backend returns step `select_user` with:
`В доступе отказано, проверьте введенные данные`.

## Run
```powershell
cd B:\Tires_Bitrix\web_backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 18080 --reload
```

## Run in Docker
```powershell
cd B:\Tires_Bitrix\web_backend
copy .env.example .env
docker compose up -d --build
```

Fill required upstream URLs in `.env`:
```env
CAR_NUMBER_API_URL=http://<car-ml-host>:11436/recognize
TIRE_NUMBER_API_URL=http://<tire-number-host>:11435/recognize
TIRE_ANALYSIS_API_URL=http://<tire-analysis-host>:11437/analyze
```

Runtime-created directories:
- `AtWork` (S3 sync)
- `Users` (sessions)

Health checks:
- `GET http://localhost:18080/health`
- `GET http://localhost:18080/api/health`
