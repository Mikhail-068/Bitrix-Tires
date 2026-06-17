# Agent.md

Короткая рабочая памятка по проекту `Tires_Bitrix`.

## Как отвечать

- Отвечать по возможности коротко и по делу.
- Если правим код, сначала смотреть текущую реализацию и не ломать чужие незакоммиченные изменения.
- В проекте могут быть локальные тестовые JSON и рабочий кэш из S3. Не считать файл в корне проекта автоматически источником данных для приложения.

## Назначение проекта

`Tires_Bitrix` — web-версия ProTires для Bitrix24 и отдельного браузерного мастера списания шин.

Основная модель:
- `web_backend/` — FastAPI backend, хранит состояние wizard-сессий, синхронизирует пользователей из Yandex S3, вызывает ML-сервисы и отправляет итог в 1С.
- `web_frontend/` — React + Vite wizard. Frontend тонкий: показывает состояние, которое вернул backend.
- `docs/` — документация API и архитектуры.
- `AtWork/` — локальный кэш JSON-профилей пользователей, скачанных из Yandex S3.
- `Users/` — директории web-сессий, фотографии, `flow_state.json`, итоговые JSON.
- `log_upload/` — JSON-логи попыток отправки в 1С.

## Основные адреса

Backend:
- Локально: `http://127.0.0.1:18080`
- API: `http://127.0.0.1:18080/api`
- Health: `http://127.0.0.1:18080/health`, `http://127.0.0.1:18080/api/health`

Frontend:
- Vite dev: `http://127.0.0.1:5173`
- Vite проксирует `/api` на `http://127.0.0.1:18080`.
- Переопределение backend: `VITE_BACKEND_URL`.

ML-сервисы:
- Хост: `http://5.35.10.157`
- Номер авто: `:11436/recognize`
- Номер шины: `:11435/recognize`
- Анализ шины: `:11437/analyze`

## Запуск

Backend:

```powershell
cd B:\Tires_Bitrix\web_backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 18080 --reload
```

Frontend:

```powershell
cd B:\Tires_Bitrix\web_frontend
npm install
npm run dev
```

## Авторизация пользователя

Пользователь вводит:
- `TelegramID` или `BitrixID`
- фамилию

Пример:

```json
{
  "TelegramID": "5652315164",
  "surname": "Стеблев"
}
```

Backend при авторизации:
1. пытается скачать/обновить JSON-профили пользователя из Yandex S3;
2. обновляет локальный кэш `AtWork/`;
3. пересобирает индекс `AtWork/.index_bitrix.json`;
4. ищет базы по `TelegramID`/`BitrixID`;
5. сверяет введенную фамилию с ФИО из профиля;
6. возвращает шаг `select_base` или `select_user` с ошибкой доступа.

Ошибка доступа:

```text
В доступе отказано, проверьте введенные данные
```

Если S3-синхронизация не сработала, backend должен добавлять подробности в `errors[].s3_sync`.

## Yandex S3 и AtWork

Настройки S3 лежат в `web_backend/.env`:
- `S3_PREFIX=AITyres/users/`
- `S3_BUCKET_NAME=rgtelegram`
- `YC_ENDPOINT_URL=https://storage.yandexcloud.net`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

Для S3 нужны зависимости:

```powershell
cd B:\Tires_Bitrix\web_backend
python -m pip install -r requirements.txt
```

Важное:
- Без `boto3` backend не скачивает пользователей из S3.
- Старый вариант полного листинга `AITyres/users/` мог долго висеть.
- Сейчас синхронизация должна искать по префиксу фамилии, например `AITyres/users/Стеблев`.
- После скачивания JSON попадают в `AtWork/`.
- `AtWork/.index_bitrix.json` и `AtWork/.s3_manifest.json` — служебные файлы, их не считать профилями пользователей.

Проверка вручную:

```powershell
cd B:\Tires_Bitrix\web_backend
@'
from app.flow_engine import FlowEngine
engine = FlowEngine()
print(engine._sync_user_from_s3_blocking("5652315164", "Стеблев"))
print(engine._find_user_bases_by_bitrix_id("5652315164"))
'@ | python -
```

Если нужно полностью перескачать кэш:

```powershell
cd B:\Tires_Bitrix
Remove-Item -LiteralPath "AtWork\*.json" -Force
Remove-Item -LiteralPath "AtWork\.index_bitrix.json" -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "AtWork\.s3_manifest.json" -Force -ErrorAction SilentlyContinue
```

После этого начать новую сессию на frontend и снова ввести `TelegramID + фамилию`.

## Откуда берется адрес отправки в 1С

HTTP-адрес отправки **не** берется из `ConnectionString`.

По уточнению 1С есть промежуточное звено, которое принимает запросы и перенаправляет их в нужные базы:

```text
https://1c.rg24.ru/ATPLite/hs/Exchange_AI
```

В backend оно задается через `BASE_URL` в `web_backend/.env`.
Рабочий endpoint для списания шин:

```text
https://1c.rg24.ru/ATPLite/hs/Exchange_AI/TireDefect
```

Важно: для текущего пайплайна списания шин используется только сервис `TireDefect`.

`ConnectionString` выбранного JSON-профиля остается внутри отправляемого JSON и нужен промежуточному звену 1С, чтобы понять, в какую базу перенаправлять данные.

Пример:

```json
"ConnectionString": "http://ws-pub1c:800/RT83_ATP_KLG_TESTII"
```

У каждого пользователя/базы может быть свой `ConnectionString`, но это не URL HTTP POST из backend. Поэтому важно выбирать правильную базу на шаге `select_base`, чтобы в JSON ушел правильный маршрутизирующий `ConnectionString`.

## Отправка в 1С и отображение результата

Точка сценария:
- шаг `confirm_send`;
- действие `confirm_send`.

Backend:
- формирует итоговый JSON;
- сохраняет его в директорию сессии;
- отправляет POST в 1С;
- пишет лог в `log_upload/send_log_*.json`;
- возвращает во frontend `send_result`.

Frontend показывает карточку результата:
- `1С приняла данные` — успешная отправка;
- `1С не приняла данные` — ошибка;
- в карточке должны быть время, адрес, тип ошибки и путь к логу.

Если 1С недоступна, frontend все равно должен явно показать результат, а не просто оставаться на том же экране.

## Что значит “резолвит”

“Резолвит” значит “преобразует имя сервера в IP-адрес”.

Например, `ws-pub1c` должен превратиться в IP:

```text
ws-pub1c -> 10.x.x.x
```

Если backend напрямую обращается к `ws-pub1c` и Windows не знает IP для этого имени, запрос до этого сервера не дойдет.

После уточнения 1С backend не должен напрямую отправлять HTTP POST в `ws-pub1c`; он должен отправлять в промежуточный endpoint `https://1c.rg24.ru/ATPLite/hs/Exchange_AI/TireDefect`. Проверки `ws-pub1c` полезны только если 1С отдельно попросит диагностировать прямой доступ.

Проверка:

```powershell
Resolve-DnsName ws-pub1c
Test-NetConnection ws-pub1c -Port 800
```

Если `Test-NetConnection` пишет:

```text
Name resolution of ws-pub1c failed
```

то проблема не в JSON и не в backend, а в DNS/VPN/hosts/сетевом доступе.

Нужно попросить 1С/админов:
- IP или полный DNS/FQDN для `ws-pub1c`;
- подтверждение порта `800`;
- доступ с машины backend до этого адреса;
- при необходимости запись в `C:\Windows\System32\drivers\etc\hosts`.

## Главные файлы

- Backend flow: `web_backend/app/flow_engine.py`
- Backend routes: `web_backend/app/routes.py`
- Backend settings: `web_backend/app/settings.py`
- Backend env: `web_backend/.env`
- Frontend wizard: `web_frontend/src/App.jsx`
- Frontend styles: `web_frontend/styles.css`
- Bitrix API docs: `docs/bitrix_api.md`
- Auth/S3 docs: `docs/Auth.md`
- Общий README: `README.md`

## Диагностика

Проверить backend:

```powershell
Invoke-RestMethod http://127.0.0.1:18080/health
Invoke-RestMethod http://127.0.0.1:18080/api/health
```

Проверить сборку frontend:

```powershell
cd B:\Tires_Bitrix\web_frontend
npm run build
```

Проверить Python-синтаксис:

```powershell
cd B:\Tires_Bitrix
python -m py_compile web_backend\app\flow_engine.py
```

Проверить базы пользователя:

```powershell
cd B:\Tires_Bitrix\web_backend
@'
from app.flow_engine import FlowEngine
engine = FlowEngine()
print(engine._find_user_bases_by_bitrix_id("5652315164"))
'@ | python -
```

## Текущие заметки: где остановились

Дата заметок: 2026-06-16.

Что уже сделано:
- Добавлен явный результат отправки в 1С во frontend: карточка успеха/ошибки.
- Backend возвращает `send_result` с адресом отправки, типом ошибки, временем и путем к логу.
- Установлен `boto3` в текущее conda-окружение.
- S3-синхронизация backend изменена так, чтобы искать пользователя по префиксу фамилии, например `AITyres/users/Стеблев`, а не листить весь бакет.
- После этого пользователь `5652315164 / Стеблев` снова проходит авторизацию и видит базы.

Что выяснили:
- Предыдущая трактовка была неверной: `ConnectionString` не должен становиться HTTP-адресом отправки из backend.
- Правильная схема от 1С: backend отправляет данные в промежуточное звено:

```text
https://1c.rg24.ru/ATPLite/hs/Exchange_AI/TireDefect
```

- `ConnectionString` должен остаться в JSON как поле маршрутизации к нужной базе:

```json
"ConnectionString": "http://ws-pub1c:800/RT83_ATP_KLG_TESTII"
```

Что сейчас не получается:
- Нужно повторно проверить отправку после исправления backend на промежуточный endpoint.
- Если ошибка станет HTTP-ошибкой от `https://1c.rg24.ru/...`, значит запрос уже дошел до промежуточного звена 1С и дальше нужно разбирать ответ 1С.
- Проверка `ws-pub1c` больше не является главным критерием для backend, потому что backend не должен ходить туда напрямую.

Текущий блокер:
- Нужна новая тестовая отправка на `BASE_URL=https://1c.rg24.ru/ATPLite/hs/Exchange_AI/TireDefect`.
- В карточке результата frontend теперь нужно смотреть два поля:
  - `Адрес` — промежуточный endpoint HTTP POST;
  - `ConnectionString` — маршрутизирующая строка базы из JSON.

Отдельная важная деталь:
- В Yandex S3 для Стеблева может лежать старый профиль с `ConnectionString: http://ws-pub1c/RT_ATP_KLG_83` и `BaseName: Калининград`.
- Новый тестовый профиль с `ConnectionString: http://ws-pub1c:800/RT83_ATP_KLG_TESTII` должен быть загружен в S3, иначе после перескачивания `AtWork/` снова вернется старое значение.
