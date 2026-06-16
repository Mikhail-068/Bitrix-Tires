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

## ⚠️ Critical: ML Container Network Configuration

ML services (car-number, tire-number, tire-analysis) run in **separate Docker containers** and can be on **different machines** from the backend.

### Production setup (current)

| Service | Host | Port |
|---------|------|------|
| Backend API | `111.88.112.76` | `18080` |
| Car number OCR | `5.35.10.157` | `11436` |
| Tire number OCR | `5.35.10.157` | `11435` |
| Tire analysis | `5.35.10.157` | `11437` |

### `.env` configuration

```env
# ✅ CORRECT — points to ML server
CAR_NUMBER_API_URL=http://5.35.10.157:11436/recognize
TIRE_NUMBER_API_URL=http://5.35.10.157:11435/recognize
TIRE_ANALYSIS_API_URL=http://5.35.10.157:11437/analyze

# ❌ WRONG — backend IP is NOT the ML server
# CAR_NUMBER_API_URL=http://111.88.112.76:11436/recognize
```

### Common mistake
If photo upload shows "Перетащите фото" repeatedly or car number is not recognized — **check `.env` URLs first**. The backend silently fails to reach ML containers and returns the same upload step.

### Verify ML containers are reachable
```powershell
# From backend machine:
curl http://5.35.10.157:11436/health
curl http://5.35.10.157:11435/health
curl http://5.35.10.157:11437/health
```

### Local development (all on one machine)
```env
CAR_NUMBER_API_URL=http://localhost:11436/recognize
TIRE_NUMBER_API_URL=http://localhost:11435/recognize
TIRE_ANALYSIS_API_URL=http://localhost:11437/analyze
```

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

Auth data is read from `AtWork/*.json`. The backend maintains a local lookup index:
- `AtWork/.index_bitrix.json` — generated lookup cache;
- `AtWork/.s3_manifest.json` — generated S3 metadata cache, when S3 sync runs.

These generated files are excluded from indexing. If the index is empty or partially built while `AtWork/` contains user JSON files, it is rebuilt automatically on the next lookup.

Quick diagnosis for "user exists in AtWork, but is not found":

```powershell
cd B:\Tires_Bitrix
@'
from web_backend.app.flow_engine import FlowEngine
engine = FlowEngine()
idx = engine._refresh_atwork_index()
print("indexed_files", len(idx.get("files", {})))
print("indexed_ids", len(idx.get("by_bitrix", {})))
print("user", idx.get("by_bitrix", {}).get("5652315164"))
print("bases", engine._find_user_bases_by_bitrix_id("5652315164"))
'@ | python -
```

S3 sync requires `boto3` and `botocore` from `requirements.txt`. If they are missing, the backend logs `boto3 is not installed, S3 user sync skipped` and falls back to the local `AtWork/` cache.

## Run
```powershell
cd B:\Tires_Bitrix\web_backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 18080 --reload
```

The backend loads configuration from `web_backend/.env` even when the process is started from `B:\Tires_Bitrix` or another working directory.

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
