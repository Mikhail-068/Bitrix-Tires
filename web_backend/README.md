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

Standalone web wizard requires only Telegram/Bitrix ID. Surname is no longer required and is ignored if an old client still sends it.

```json
POST /api/flow/start
{
  "TelegramID": "1657181189"
}
```

Compatible aliases are accepted:
- `TelegramID`
- `BitrixID`
- `telegram_id`
- `bitrix_id`

On start, backend:
1. runs on-demand S3 sync for the submitted ID;
2. searches `AtWork` by `TelegramID` / `BitrixID`;
3. returns `select_base` when at least one base is found;
4. returns `select_user` with `access_denied` when the user is not found.

The on-demand sync is intentionally per-user and refreshes matched user files on every authorization attempt. The backend lists S3 metadata, maps JSON files to the submitted ID, downloads only those matched files into `AtWork/`, removes stale local files for the same ID, then rebuilds the local lookup index. This keeps changed bases and connection links current without downloading all users from the bucket.

Public `access_denied` response contains a registration-help message and link:

```json
{
  "code": "access_denied",
  "message": "Пользователь с указанным ID не найден. Проверьте корректность введенных данных. Если ID указан верно, обратитесь к ответственному сотруднику для помощи в регистрации.",
  "registration_help_url": "https://portal.rt24.ru/company/personal/user/4212/",
  "registration_help_label": "Помощь в регистрации"
}
```

S3/internal diagnostics are logged server-side and are not exposed to the user for this scenario.

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

## Production on Backgosha

Current server deployment runs only `web_backend`; frontend is not deployed there.

```bash
ssh Backgosha
cd /home/ProTires/web_backend
docker compose up -d --build
docker compose ps
```

The server keeps runtime data outside the image:
- `./runtime/AtWork` — S3-synced authorization files and lookup indexes;
- `./runtime/Users` — web sessions and uploads;
- `./runtime/log_upload` — 1C upload logs.

Do not overwrite `.env` during deploy. It contains production ML URLs, S3 credentials, and 1C credentials. `docker-compose.yml` sets `PROJECT_ROOT=/app/web_backend` inside the container.

