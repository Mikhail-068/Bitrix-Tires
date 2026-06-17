# ProTires Web Frontend — AGENTS.md

Файл для AI-агентов, работающих с проектом. Читатель предполагается незнакомым с кодовой базой.

---

## 1. Обзор проекта

**ProTires Web Frontend** — это одностраничное приложение (SPA) на React, реализующее пошаговый визард («wizard») для списания шин. Весь бизнес-процесс и состояние сессии управляются бэкендом; фронтенд только отрисовывает то, что приходит с сервера, и отправляет действия пользователя.

- **Язык интерфейса**: русский.
- **Название продукта**: ProTires / «Списание шин».
- **Интеграции**: Bitrix24 (автозаполнение пользователя), 1С (отправка финальных данных).

---

## 2. Технологический стек

| Слой | Технология | Версия (из package.json) |
|------|-----------|--------------------------|
| UI-фреймворк | React | ^19.0.0 |
| Рендеринг | React DOM | ^19.0.0 |
| Сборщик | Vite | ^7.0.0 |
| React-плагин для Vite | @vitejs/plugin-react | ^5.0.0 |
| E2E-тестирование | Playwright | ^1.60.0 (devDep) |
| Стили | Чистый CSS (кастомные свойства, без фреймворков) | — |

- Проект использует ES-модули (`"type": "module"`).
- TypeScript **не используется** (plain JSX/JS).
- Точка входа — `index.html` → `src/main.jsx` → `src/App.jsx`.

---

## 3. Структура каталогов

```
web_frontend/
├── package.json          # Зависимости и скрипты
├── vite.config.js        # Конфиг Vite + dev-proxy
├── index.html            # Точка входа (title: "Списание шин")
├── src/
│   ├── main.jsx          # Монтирование React-приложения
│   └── App.jsx           # Единственный корневой компонент (~1300 строк)
├── styles.css            # Глобальные стили (~1600 строк, CSS-переменные, темы)
├── dist/                 # Артефакты production-сборки
└── *.png / *.jpg         # Статичные изображения (иконки, примеры фото)
```

---

## 4. Команды сборки и разработки

```bash
# Установка зависимостей
npm install

# Dev-сервер (по умолчанию 127.0.0.1, порт можно переопределить)
npm run dev -- --port 5173

# Production-сборка в dist/
npm run build

# Просмотр production-билда
npm run preview -- --port 5173
```

- В `vite.config.js` настроен прокси: `/api` → `VITE_BACKEND_URL` из `.env.local`, fallback `http://127.0.0.1:18080`.
- Текущая локальная схема использует `web_frontend/.env.local` с `VITE_BACKEND_URL=http://111.88.112.76:18080`, то есть frontend работает локально, а backend — на `Backgosha`.
- В dev-режиме в поле «API URL» интерфейса следует указывать `/api`, а не полный внешний URL, иначе возможны CORS-проблемы.

---

## 5. Архитектура и принципы работы

### 5.1 Backend-driven UI

- Фронтенд **не хранит бизнес-логику локально**.
- Состояние сессии хранится на бэкенде; фронт получает его через `GET /api/flow/{session_id}`.
- Каждое действие пользователя отправляется через `POST /api/flow/{session_id}/action`.
- Бэкенд возвращает новое состояние (`flowState`), и UI перерисовывается с нуля.

### 5.2 Шаги визарда (flow)

Основные шаги (перечислены в `STEP_STAGES`):

0. **Авторизация** (`select_user`) — ввод Telegram ID (см. §5.5)
1. **Настройка** (`select_base`, `select_source`)
2. **Источник / авто** (`select_transport_method`, `upload_car_photo`, `enter_manual_car_number`, `confirm_car`)
3. **Фото шин** (`set_tire_count`, `upload_tire_photo`, `confirm_photo`, `confirm_tire_number`, `post_required_photos`)
4. **Отправка** (`comment`, `confirm_send`)
5. **Готово** (`finished`)

### 5.3 Сессия

- `session_id` сохраняется в `localStorage` (ключ `protires_session_id`).
- Кнопка «+ Новая сессия» сбрасывает `session_id` и вызывает `POST /flow/start`.
- Старт выполняется с авторизационными данными (см. §5.5); при пустом теле бэкенд возвращает шаг `select_user` с просьбой ввести данные.

### 5.4 Загрузка изображений

- Фото отправляются через `POST /api/flow/{session_id}/upload` (multipart/form-data, поле `image`).
- Бэкенд возвращает `flowState` с результатом анализа (детекция, OCR серийных номеров, шипы и т.д.).

### 5.5 Авторизация (Telegram ID)

- Пользователь вводит **Telegram ID** на стартовом экране (или на шаге `select_user`).
- Запрос: `POST /api/flow/start` с телом `{ "TelegramID": "<id>" }` (поле `BitrixID` — legacy-алиас того же идентификатора).
- Бэкенд синхронизирует данные пользователя из S3 (`AtWork/`) и проверяет, что по ID найден хотя бы один профиль/база.
- Если ID не найден, возвращается шаг `select_user` с ошибкой `access_denied`; UI показывает официальный текст и кнопку «Помощь в регистрации» на `https://portal.rt24.ru/company/personal/user/4212/`.
- Успешная проверка ставит флаг `auth_verified` в сессии; без него действие `select_base` отклоняется на бэкенде.

---

## 6. Организация кода

### 6.1 React-приложение (актуальное)

- **`src/main.jsx`** — монтирует `<App />` в `#root`, импортирует `styles.css`.
- **`src/App.jsx`** — единственный файл с компонентами. Внутри него определены:
  - `App` — корневой компонент: состояние (`flowState`, `busy`, `toast`, `lightboxPhoto`, `theme`), API-обёртки (`apiFetch`, `apiPost`, `uploadImage`), контекст для дочерних шагов.
  - `WizardContent` — роутер шагов (switch по `flowState.step`).
  - Компоненты отдельных шагов: `SelectBase`, `SelectUser`, `SelectSource`, `UploadCarPhoto`, `EnterManualCarNumber`, `ConfirmCar`, `SetTireCount`, `UploadTirePhoto`, `ConfirmPhoto`, `ConfirmTireNumber`, `PostRequiredPhotos`, `CommentStep`, `ConfirmSend`, `Finished`.
  - UI-хелперы: `Stepper`, `FragmentStep`, `ErrorBanner`, `ProgressPanel`, `InfoCard`, `DemoImage`, `PhotoPreview`, `AnnotatedImage`, `PhotoLightbox`, `DonePhotos`, `TireProgress`, `UploadZone`.

### 6.2 Стили

- Все стили — в одном файле `styles.css`.
- Используются CSS-переменные (`:root`) для светлой и тёмной темы (`:root[data-theme="dark"]`).
- Переключение темы — через кнопку в топбаре; выбор сохраняется в `localStorage` (ключ `protires_theme`).

---

## 7. Соглашения и стиль кода

- **Язык комментариев и UI**: русский.
- **Код**: JavaScript (ES2020+), JSX, без TypeScript.
- **Именование**: camelCase для переменных/функций, PascalCase для компонентов React.
- **Состояние**: `useState`, `useEffect`, `useCallback`, `useMemo` из React.
- **API-вызовы**: обёрнуты в `runBusy` (блокирует UI и показывает анимацию загрузки).
- **Ошибки**: отображаются через `showToast` и в `ErrorBanner` (детали ошибки раскрываются через `<details>`).

---

## 8. Тестирование

- В `package.json` в devDependencies указан `playwright`, но **в проекте нет написанных тестов** (нет папок `tests/`, `__tests__/`, `e2e/` и т.п.).
- Playwright можно использовать для E2E-тестирования визарда, если потребуется.

---

## 9. Развёртывание

- Production-сборка формируется командой `npm run build` и попадает в `dist/`.
- `dist/index.html` + `dist/assets/` — статичные файлы, которые можно раздавать любым HTTP-сервером.
- В `index.html` используется относительный путь к скрипту (`/src/main.jsx` в dev, в production Vite заменяет на хэшированные ассеты в `dist/assets/`).

---

## 10. Безопасность и важные замечания

- **CORS**: в dev-режиме прокси Vite обходит CORS. В production фронтенд и бэкенд должны быть настроены на корректные CORS-заголовки.
- **API URL**: не хардкодить полный внешний URL в UI-поле при работе через dev-сервер — использовать `/api` (цель прокси задаётся через `VITE_BACKEND_URL`).
- **Авторизация**: доступ открывается только если Telegram ID найден в `AtWork/` (S3). Хардкод тестового BitrixID убран.
- **Файлы**: при загрузке изображений проверяйте, что отправляется `FormData` с полем `image`.
- **Session ID**: хранится в `localStorage`, поэтому сессия переживает перезагрузку страницы. Кнопка сброса («✕») полностью очищает сессию.

---

## 11. Ключевые константы (для справки)

| Константа | Значение | Назначение |
|-----------|----------|------------|
| `STORAGE_KEY` | `"protires_session_id"` | localStorage-ключ для session_id |
| `THEME_KEY` | `"protires_theme"` | localStorage-ключ для темы |
| `CAR_PHOTO_INSTRUCTION` | `"Загрузите автомобиль..."` | Инструкция для фото авто |
| `STEP_STAGES` | объект {step → stageIndex} | Сопоставление шага к номеру стадии (0..4) |

---

## 12. Полезные ссылки для агента

- `README.md` — краткая инструкция по запуску и подключению к бэкенд-контейнеру.
- `vite.config.js` — настройка dev-proxy и плагинов.
- `src/App.jsx` — основная бизнес-логика отрисовки шагов.
- `styles.css` — все стили, включая тёмную тему.
