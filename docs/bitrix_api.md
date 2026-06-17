# ProTires API — Документация для Bitrix24

**Версия:** 2.4  
**Дата:** 17 июня 2026  

---

## Содержание

1. [Быстрый старт — минимальный код](#быстрый-старт)
2. [Базовый URL](#базовый-url)
3. [Как это работает — главная идея](#как-это-работает)
4. [Структура каждого ответа](#структура-каждого-ответа)
5. [Шаг 1 — Старт сессии](#шаг-1--старт-сессии)
6. [Шаг 2 — Отправка действия](#шаг-2--отправка-действия)
7. [Шаг 3 — Загрузка фото](#шаг-3--загрузка-фото)
8. [Шаг 4 — Получение состояния сессии](#шаг-4--получение-состояния-сессии)
9. [Полный список шагов (step) и что показывать](#полный-список-шагов)
10. [Полный список действий (action)](#полный-список-действий)
11. [Как рендерить каждый шаг](#как-рендерить-каждый-шаг)
12. [Обработка ошибок](#обработка-ошибок)
13. [Прогресс (поле progress)](#прогресс)
14. [Сценарии прохождения](#сценарии-прохождения)
15. [Вспомогательные эндпоинты](#вспомогательные-эндпоинты)
16. [Частые ошибки интеграции](#частые-ошибки-интеграции)

---

## Быстрый старт

Вот минимальный пример на JavaScript для Bitrix:

> Для Bitrix-разработки используйте идентификатор пользователя `Bitrix ID`.

```javascript
const API = "http://111.88.112.76:18080/api";
let SESSION_ID = null;

// 1. Старт — передаём Bitrix ID пользователя.
async function startSession(bitrixId) {
  const response = await fetch(`${API}/flow/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ BitrixID: bitrixId })
  });
  const data = await response.json();
  SESSION_ID = data.session_id;  // сохраняем session_id
  renderStep(data);              // рендерим экран по data.step
}

// 2. Действие пользователя
async function sendAction(action, payload = {}) {
  const response = await fetch(`${API}/flow/${SESSION_ID}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, payload })
  });
  const data = await response.json();
  renderStep(data);  // всегда перерисовываем по data.step
}

// 3. Загрузка фото
async function uploadPhoto(file) {
  const form = new FormData();
  form.append("image", file);
  const response = await fetch(`${API}/flow/${SESSION_ID}/upload`, {
    method: "POST",
    body: form
  });
  const data = await response.json();
  renderStep(data);  // всегда перерисовываем по data.step
}

// 4. Главная функция рендера — только по полю step
function renderStep(data) {
  // data.step говорит какой экран показать
  // data.allowed_actions говорит какие кнопки/формы активны
  // data.ui_payload содержит данные для отображения
  // data.errors содержит ошибки (если есть)
  console.log("Текущий шаг:", data.step);
}
```

**Пример вызова старта:**
```javascript
await startSession("1657181189");
```

---

## Базовый URL

```
http://111.88.112.76:18080/api
```

Backend развернут на сервере `Backgosha` в Docker-контейнере `protires-backend`.
Bitrix-интеграция работает напрямую с backend по `/api`; отдельный frontend для Bitrix не требуется.
При старте сессии backend точечно обновляет данные введенного `BitrixID` из Yandex Bucket и уже после этого проверяет доступные базы. Это защищает от устаревших данных при изменении базы или ссылки подключения.

Проверка доступности backend:

```text
http://111.88.112.76:18080/health
http://111.88.112.76:18080/api/health
```

---

## Как это работает

Bitrix не содержит никакой логики — только показывает экраны и передаёт действия пользователя.

```
Пользователь → Bitrix → POST /api/flow/... → Бэкенд → ответ с { step, ui_payload }
                   ↑                                                      |
                   └──────────────── рендерим по step ───────────────────┘
```

**Правила:**
1. Старт → бэкенд возвращает первый шаг
2. Пользователь что-то делает → Bitrix отправляет `action`
3. Бэкенд возвращает **новый step** → Bitrix перерисовывает экран
4. Повторяем до шага `finished`

**Главное правило:** всегда рендерьте экран по полю `step` из последнего ответа бэкенда. Никогда не храните «текущий шаг» на стороне Bitrix.

### Ограничение интеграции (обязательно)

- Bitrix-интеграция работает **только через backend** (`/api/...`).
- Прямые вызовы ML-сервисов/ML-контейнеров из Bitrix запрещены.
- Любое распознавание (авто, номер шины, анализ шины) запускается только через flow backend.

---

## Структура каждого ответа

Каждый ответ бэкенда (на старт, действие, загрузку фото) возвращает **один и тот же формат**:

```json
{
  "session_id": "abc123def456",
  "step": "select_base",
  "allowed_actions": ["select_base"],
  "ui_payload": {
    "bitrix_id": "1657181189",
    "user_name": "Титов Михаил Сергеевич",
    "bases": [
      { "uid": "0af2c315-4d7b-11e6-80c6-0017a477000a", "base_name": "АТП ЧЕЛЯБИНСК" }
    ]
  },
  "errors": [],
  "progress": {
    "tire_count": 0,
    "current_tire": 1,
    "current_photo": 0,
    "max_photo": 0,
    "required_photos": 5,
    "is_last_tire": false
  },
  "context": {
    "selected_user": null,
    "selected_base": null,
    "source": null,
    "transport_method": null,
    "car_number": null,
    "car_brand": null,
    "display_name": "Web User"
  }
}
```

> Примечание: поле `ui_payload.bitrix_id` в ответах backend содержит ваш `Bitrix ID`.

### Описание полей

| Поле | Тип | Что делать |
|------|-----|------------|
| `session_id` | string | Сохранить после старта, использовать во всех запросах |
| `step` | string | **По этому полю определяем какой экран показать** |
| `allowed_actions` | array | Только эти `action` можно отправлять прямо сейчас |
| `ui_payload` | object | Данные для отображения (тексты, результаты, имена файлов) |
| `errors` | array | Ошибки. Пустой массив = всё ОК. При ошибке `step` не меняется |
| `progress` | object | Прогресс: сколько шин, какое фото сейчас |
| `context` | object | Накопленный контекст сессии |

### Поле `progress` подробнее

| Поле | Описание |
|------|----------|
| `tire_count` | Общее количество шин (0 пока не задано) |
| `current_tire` | Номер текущей шины (с 1) |
| `current_photo` | Номер текущего фото (с 1) |
| `max_photo` | Наибольший номер уже загруженного фото (нужен для навигации) |
| `required_photos` | Всегда `5` — столько обязательных фото у каждой шины |
| `is_last_tire` | `true` если это последняя шина |

### Поле `context` подробнее

| Поле | Описание |
|------|----------|
| `selected_user` | ФИО пользователя |
| `selected_base` | Выбранная база |
| `source` | `"Транспорт"` или `"Склад"` (после выбора) |
| `transport_method` | `"automatic"` (всегда, это внутреннее поле) |
| `car_number` | Номер авто (после распознавания/ввода) |
| `car_brand` | Марка авто из базы (если найдена) |
| `display_name` | Имя для отображения |

---

## Шаг 1 — Старт сессии

```
POST /api/flow/start
Content-Type: application/json
```

**Тело запроса (рекомендуемый формат для Bitrix):**
```json
{
  "BitrixID": "1657181189"
}
```

Поддерживаются варианты:

1. `{"BitrixID": "..."}` — основной формат для Bitrix.
2. `{"bitrix_id": "..."}` — совместимый алиас.
3. `{"profile": {...}}` или список `[ {...} ]` — запуск от готового профиля.

Если старый клиент продолжает отправлять `surname`, `last_name` или `family_name`, backend игнорирует эти поля.

### Что делает backend на старте

На каждый `POST /flow/start` backend:
- получает `BitrixID` пользователя;
- обновляет из S3 только данные этого пользователя;
- ищет профиль и доступные базы;
- при успехе возвращает шаг `select_base`;
- при ошибке возвращает шаг `select_user`, код `access_denied`, официальный текст и ссылку помощи в регистрации.

Из-за per-user sync стартовый запрос может быть заметно дольше обычного.
На стороне Bitrix нужно:
- блокировать кнопку `Start` на время запроса;
- показывать loader или текст «Обновляем данные пользователя...»;
- не отправлять повторный `start`, пока предыдущий запрос не завершился.

| Поле | Откуда брать | Обязательно |
|------|-------------|-------------|
| `BitrixID` | `Bitrix ID` пользователя | Да |

**Ответ** — первый шаг `select_base`:
```json
{
  "session_id": "abc123def456",
  "step": "select_base",
  "allowed_actions": ["select_base"],
  "ui_payload": {
    "bitrix_id": "1657181189",
    "user_name": "Титов Михаил Сергеевич",
    "bases": [
      { "uid": "0af2c315-4d7b-11e6-80c6-0017a477000a", "base_name": "АТП ЧЕЛЯБИНСК" }
    ]
  },
  "errors": [],
  "progress": { "tire_count": 0, "current_tire": 1, "current_photo": 0, "max_photo": 0, "required_photos": 5, "is_last_tire": false },
  "context": { "selected_user": null, "selected_base": null, ... }
}
```

> **Сохраните `session_id`** — он используется во всех следующих запросах.

**Ответ, если пользователь не найден** — шаг `select_user` и ошибка `access_denied`:

```json
{
  "session_id": "abc123def456",
  "step": "select_user",
  "allowed_actions": ["select_user"],
  "ui_payload": {
    "title": "Авторизация",
    "instruction": "Введите ID"
  },
  "errors": [
    {
      "code": "access_denied",
      "message": "Пользователь с указанным ID не найден. Проверьте корректность введенных данных. Если ID указан верно, обратитесь к ответственному сотруднику для помощи в регистрации.",
      "registration_help_url": "https://portal.rt24.ru/company/personal/user/4212/",
      "registration_help_label": "Помощь в регистрации"
    }
  ]
}
```

Для этого сценария не показывайте пользователю технические детали диагностики. Покажите текст ошибки, поле повторного ввода ID и кнопку `registration_help_label`, ведущую на `registration_help_url`.
Поля `registration_help_url` и `registration_help_label` являются дополнительными: если UI пока не поддерживает кнопку помощи, их можно игнорировать и показывать только `message`.

---

## Шаг 2 — Отправка действия

```
POST /api/flow/{session_id}/action
Content-Type: application/json
```

**Тело запроса:**
```json
{
  "action": "название_действия",
  "payload": { ... }
}
```

**Правила:**
- Смотрите на `allowed_actions` последнего ответа
- Отправляйте **только** те `action`, которые там есть
- Если отправить неразрешённое действие — бэкенд вернёт ошибку `invalid_action`, шаг не изменится

**Пример — выбор базы:**
```javascript
await sendAction("select_base", {
  uid: "0af2c315-4d7b-11e6-80c6-0017a477000a",
  base_name: "АТП ЧЕЛЯБИНСК"
});
```

**Пример — выбор источника «Транспорт»:**
```javascript
await sendAction("select_source", { source: "Транспорт" });
// или
await sendAction("select_source", { source: "Склад" });
```

---

## Шаг 3 — Загрузка фото

```
POST /api/flow/{session_id}/upload
Content-Type: multipart/form-data
```

**Тело:** форма с полем `image` (файл изображения).

**Форматы:** JPG, PNG, HEIC и другие стандартные. Бэкенд сам конвертирует в JPEG.

**Когда загружать:**  
Только когда в `allowed_actions` есть `"upload_image"`.

```javascript
// Правильно — проверяем перед загрузкой:
if (data.allowed_actions.includes("upload_image")) {
  await uploadPhoto(file);
}
```

**Бэкенд сам определяет что делать с фото** по текущему шагу:

| Текущий `step` | Текущее фото | Что происходит |
|----------------|-------------|----------------|
| `upload_car_photo` | — | AI распознаёт номер авто |
| `upload_tire_photo` | 1 | AI анализирует качество шины (сбоку) |
| `upload_tire_photo` | 2 | AI анализирует шину полностью (сезон, шипы, качество) |
| `upload_tire_photo` | 3 | Сохраняется без AI |
| `upload_tire_photo` | 4 | AI распознаёт серийный номер шины |
| `upload_tire_photo` | 5 | Сохраняется без AI |
| `upload_tire_photo` | 6+ | Дополнительное фото, сохраняется без AI |

---

## Шаг 4 — Получение состояния сессии

```
GET /api/flow/{session_id}
```

Возвращает текущее состояние в том же формате.  
Используйте если пользователь закрыл и снова открыл приёмку.

```javascript
// Восстановление сессии при открытии
const sessionId = localStorage.getItem("session_id");
if (sessionId) {
  const data = await fetch(`${API}/flow/${sessionId}`).then(r => r.json());
  renderStep(data);
}
```

---

## Полный список шагов

Это значения поля `step` в ответе. По нему определяем что рендерить.

| `step` | Что показать пользователю |
|--------|--------------------------|
| `select_user` | Форма повторной авторизации по Bitrix ID |
| `select_base` | Список доступных баз пользователя и выбор базы |
| `select_source` | Кнопки «Склад» и «Транспорт» |
| `upload_car_photo` | Зону загрузки фото авто + поле ввода номера вручную + пример фото |
| `confirm_car` | Распознанный номер авто, марку, кнопки «Подтвердить» / «Переснять» |
| `set_tire_count` | Поле ввода количества шин |
| `upload_tire_photo` | Зону загрузки фото шины + описание ракурса из `ui_payload.description` + пример |
| `confirm_photo` | Результат анализа фото (качество, сезон, шипы), кнопки «Принять» / «Переснять» |
| `confirm_tire_number` | Распознанный серийный номер + поле ввода вручную + кнопка «Переснять» |
| `post_required_photos` | Кнопки: «Следующая шина» / «Завершить» / «Добавить доп. фото» |
| `comment` | Поле ввода комментария |
| `confirm_send` | Итоговую сводку из `ui_payload.summary`, кнопки «Отправить в 1С» / «Отменить» |
| `finished` | Итог: «Отправлено» или «Отменено» |

---

## Полный список действий

### Таблица всех `action` для Bitrix-интеграции

| `action` | На каком `step` | `payload` | Описание |
|----------|----------------|-----------|----------|
| `select_user` | `select_user` | `{ "BitrixID": "..." }` | Повторная авторизация по Bitrix ID |
| `select_base` | `select_base` | `{ "uid": "...", "base_name": "..." }` | Выбрать базу пользователя |
| `select_source` | `select_source` | `{ "source": "Транспорт" }` или `{ "source": "Склад" }` | Пользователь выбрал источник |
| `submit_manual_car_number` | `upload_car_photo` | `{ "car_number": "А123ВС77" }` | Пользователь ввёл номер вручную |
| `confirm_car` | `confirm_car` | `{}` | Подтвердить распознанный номер |
| `retry_car` | `confirm_car` | `{}` | Переснять авто |
| `set_tire_count` | `set_tire_count` | `{ "tire_count": 4 }` | Указать количество шин |
| `confirm_photo` | `confirm_photo` | `{}` | Принять результат анализа фото |
| `retry_photo` | `confirm_photo` | `{}` | Переснять фото шины |
| `confirm_tire_number` | `confirm_tire_number` | `{ "number": "АВС12345" }` | Подтвердить серийный номер |
| `manual_tire_number` | `confirm_tire_number` | `{ "number": "АВС12345" }` | Ввести серийный номер вручную |
| `retake_photo_4` | `confirm_tire_number` | `{}` | Переснять фото маркировки (фото 4) |
| `add_additional_photo` | `post_required_photos` | `{}` | Добавить доп. фото шины |
| `next_tire` | `post_required_photos` | `{}` | Перейти к следующей шине |
| `finish_with_comment` | `post_required_photos` | `{}` | Завершить с комментарием |
| `finish_without_comment` | `post_required_photos` | `{}` | Завершить без комментария |
| `submit_comment` | `comment` | `{ "comment": "Текст" }` | Отправить комментарий |
| `confirm_send` | `confirm_send` | `{}` | Подтвердить отправку в 1С |
| `cancel_send` | `confirm_send` | `{}` | Отменить отправку |
| `navigate_back` | большинство шагов | `{}` или расширенный (см. ниже) | Вернуться назад |
| `navigate_forward` | `upload_tire_photo` | `{}` или `{ "photo_number": 3 }` | Вперёд к следующему/конкретному фото |

### `navigate_back` — расширенный payload

Если нужно перейти к конкретному фото (например, при клике по точке прогресса):
```json
{ "photo_number": 2 }
```

Если нужно перейти на первый шаг (выбор источника), сохранив данные пользователя:
```json
{ "target_stage": 0, "preserve_context": true }
```

Если нужно перейти на первый шаг и сбросить всё:
```json
{ "target_stage": 0 }
```

> Действие `navigate_back` доступно почти на каждом шаге — проверяйте `allowed_actions`.

---

## Как рендерить каждый шаг

### `select_source`

```json
"ui_payload": {
  "user_name": "Титов Михаил Сергеевич",
  "base_name": "АТП ЧЕЛЯБИНСК",
  "source_options": ["Склад", "Транспорт"]
}
```

Показать: приветствие с именем, две кнопки из `source_options`.

```javascript
case "select_source":
  const { user_name, source_options } = data.ui_payload;
  // Показать кнопки для каждого элемента source_options
  source_options.forEach(src => {
    button.onclick = () => sendAction("select_source", { source: src });
  });
```

---

### `select_base`

```json
"ui_payload": {
  "bitrix_id": "1657181189",
  "user_name": "Титов Михаил Сергеевич",
  "bases": [
    { "uid": "0af2c315-4d7b-11e6-80c6-0017a477000a", "base_name": "АТП ЧЕЛЯБИНСК" }
  ]
}
```

Показать: список доступных баз и кнопку выбора каждой базы.

Если `bases` пустой массив:
- показать сообщение об ошибке из `errors[0].message`;
- не скрывать экран выбора базы;
- не предлагать пользователю переход дальше без успешного `select_base`.

```javascript
case "select_base":
  data.ui_payload.bases.forEach((b) => {
    button.onclick = () => sendAction("select_base", { uid: b.uid, base_name: b.base_name });
  });
```

---

### `upload_car_photo`

```json
"ui_payload": {
  "instruction": "Загрузите фото автомобиля...",
  "demo_image": "start_img.png",
  "preview_file": "car_number.jpg",
  "last_raw_result": "",
  "last_error_code": ""
}
```

Показать:
- Поле загрузки файла (отправляет через `POST /upload`)
- Поле ввода номера вручную (отправляет `submit_manual_car_number`)
- Пример фото: `GET /api/demo/{demo_image}` (если `demo_image` есть)
- Если есть `preview_file` — последнее загруженное фото: `GET /api/flow/{session_id}/file/{preview_file}`

---

### `confirm_car`

```json
"ui_payload": {
  "number": "А123ВС77",
  "found_in_db": true,
  "brand": "КАМАЗ",
  "org": "АТП Челябинск",
  "method": "automatic",
  "preview_file": "car_number.jpg"
}
```

Показать: номер авто крупно, марку (если `found_in_db: true`), кнопки «Подтвердить» и «Переснять».

---

### `set_tire_count`

```json
"ui_payload": {
  "car_number": "А123ВС77",
  "car_brand": "КАМАЗ"
}
```

Показать: числовой ввод (обычно от 1 до 20), кнопку подтверждения.

```javascript
button.onclick = () => sendAction("set_tire_count", { tire_count: parseInt(input.value) });
```

---

### `upload_tire_photo`

```json
"ui_payload": {
  "tire_number": 1,
  "photo_number": 2,
  "description": "Общий вид колеса (шина спереди)",
  "required": true,
  "source": "Транспорт",
  "demo_image": "car_2.jpg",
  "preview_file": "tire_1_photo_2.jpg",
  "last_result": null
}
```

Показать:
- Заголовок: «Шина 1, фото 2 из 5»
- Описание ракурса из `description`
- Пример фото: `GET /api/demo/{demo_image}` (если есть)
- Если есть `preview_file` — показать ранее загруженное фото
- Зону загрузки файла

**Описания ракурсов по номеру фото:**

| Фото | `description` | Обработка |
|------|---------------|-----------|
| 1 | «Общий вид колеса (шина сбоку)» | AI: качество |
| 2 | «Общий вид колеса (шина спереди)» | AI: сезон, шипы, качество |
| 3 | «Высота протектора (с прил. измерит. инструмента)» | Без AI |
| 4 | «Идентификация шины (заводской номер)» | AI: серийный номер |
| 5 | «Идентификация шины (марка и модель шины)» | Без AI |
| 6+ | «Дополнительное фото #N» | Без AI |

---

### `confirm_photo`

```json
"ui_payload": {
  "tire_number": 1,
  "photo_number": 1,
  "preview_file": "tire_1_photo_1.jpg",
  "result": {
    "success": true,
    "mode": "quality",
    "quality": {
      "classification": "УТОЧНИТЬ",
      "suffix": "УТОЧНИТЬ",
      "score": 75,
      "confidence": 0.93,
      "threshold": 8.0
    },
    "season_spikes": {
      "season": "winter",
      "confidence": 0.98,
      "spikes": { "good": 15, "missing": 2 },
      "spike_boxes": []
    },
    "detection": { "count": 1 }
  }
}
```

Показать: фото (через `/file/{preview_file}`), результат анализа, кнопки «Принять» / «Переснять».

### Визуальная разметка (overlay) от backend

Для фото шины №1 и №2 backend возвращает диагностическую разметку в `result.detection`.  
Эти данные нужно использовать для отрисовки рамки/линий поверх исходного изображения в UI Bitrix.

Пример:
```json
"result": {
  "success": true,
  "mode": "full",
  "detection": {
    "count": 1,
    "selected_bbox_original": [120, 80, 980, 720],
    "image_size": [1280, 960],
    "is_cropped": false,
    "cropped_sides": [],
    "crop_lines": []
  },
  "season_spikes": {
    "season": "winter",
    "spike_boxes": [
      { "bbox": [315, 410, 338, 433], "label": "spike_good" }
    ]
  }
}
```

Что рисовать:
- `detection.selected_bbox_original` — рамка шины на исходном изображении (`[x1, y1, x2, y2]`).
- `detection.crop_lines` — линии проблемных границ (если `is_cropped=true`).
- `season_spikes.spike_boxes` (фото №2, если есть) — доп. боксы по шипам.

> Координаты в `selected_bbox_original`, `crop_lines`, `spike_boxes[].bbox` относятся к исходному изображению `preview_file`.

---

**Структура `result.quality`** (для фото 1 и 2):

| Поле | Тип | Описание |
|------|-----|----------|
| `classification` | string | Итоговая классификация качества |
| `suffix` | string | Краткое значение для UI/маркировки |
| `score` | number | Числовой скор или метрика модели |
| `confidence` | number | Уверенность модели |
| `threshold` | number | Порог классификации |

**Структура `result.season_spikes`** (только для фото 2):

| Поле | Тип | Описание |
|------|-----|----------|
| `season` | string | `"summer"`, `"winter"`, `"all_season"` и др. |
| `confidence` | number | Уверенность классификации сезона |
| `spikes` | object/null | Сводка по шипам |
| `spike_boxes` | array/null | BBox шипов для overlay |
| `has_spikes_info` | boolean | Есть ли валидная информация по шипам |
| `error` | string/null | Ошибка анализа шипов, если была |

**Структура `result.detection`** (для фото 1 и 2):

| Поле | Тип | Описание |
|------|-----|----------|
| `count` | number | Сколько шин найдено на фото |
| `selected_bbox_original` | number[4] | BBox выбранной шины на исходном изображении `[x1,y1,x2,y2]` |
| `image_size` | number[2] | Размер исходного изображения `[width,height]` |
| `is_cropped` | boolean | Есть ли обрезка шины по краю кадра |
| `cropped_sides` | string[] | Стороны обрезки: `left/right/top/bottom` |
| `crop_lines` | array | Линии для визуальной подсветки проблемных границ |

---

### `confirm_tire_number`

```json
"ui_payload": {
  "tire_number": 1,
  "photo_number": 4,
  "preview_file": "tire_1_photo_4.jpg",
  "result": {
    "found": true,
    "number": "АВС12345",
    "confidence": 0.92,
    "error": null
  }
}
```

Показать: фото, распознанный номер (если `found: true`), поле ввода для ручного ввода, три кнопки.

```javascript
// Подтвердить найденный номер:
sendAction("confirm_tire_number", { number: result.number });

// Ввести вручную:
sendAction("manual_tire_number", { number: inputValue });

// Переснять:
sendAction("retake_photo_4");
```

---

### `post_required_photos`

```json
"ui_payload": {
  "tire_number": 1,
  "is_last_tire": false
}
```

Показать кнопки в зависимости от `allowed_actions`:
- Если есть `next_tire` — кнопка «Следующая шина»
- Если есть `finish_with_comment` — кнопка «Завершить с комментарием»
- Если есть `finish_without_comment` — кнопка «Завершить»
- Всегда показывать кнопку «Добавить доп. фото» (`add_additional_photo`)

---

### `comment`

```json
"ui_payload": {
  "instruction": "Введите комментарий для завершения"
}
```

Показать: текстовое поле, кнопку «Отправить».

---

### `confirm_send`

```json
"ui_payload": {
  "summary": {
    "selected_base": "АТП ЧЕЛЯБИНСК",
    "user_name": "Титов Михаил Сергеевич",
    "source": "Транспорт",
    "car_number": "А123ВС77",
    "car_brand": "КАМАЗ",
    "tire_count": 4,
    "comment": "",
    "photos": [
      {
        "tire_number": 1,
        "photo_number": 1,
        "file_name": "tire_1_photo_1.jpg",
        "result": { ... }
      }
    ]
  }
}
```

Показать: сводку данных, кнопки «Отправить в 1С» и «Отменить».

---

### `finished`

```json
"ui_payload": {
  "status": "sent",
  "message": "Данные успешно отправлены в 1С"
}
```

или при отмене:
```json
"ui_payload": {
  "status": "cancelled",
  "message": "Отправка отменена пользователем"
}
```

Показать: итоговое сообщение. `allowed_actions` будет пустым — никаких кнопок действий.

---

## Обработка ошибок

### Главное правило

При ошибке **шаг (`step`) не меняется** — нужно показать сообщение и дать пользователю повторить.

```javascript
function renderStep(data) {
  // Сначала проверяем ошибки
  if (data.errors && data.errors.length > 0) {
    showErrorBanner(data.errors[0].message);
    // НО! Всё равно рендерим текущий шаг — пользователь должен иметь возможность повторить
  }
  // Потом рендерим экран по step
  renderByStep(data.step, data);
}
```

### Структура ошибки

```json
{
  "errors": [
    {
      "code": "car_number_not_recognized",
      "message": "Номер не распознан",
      "container_error": "number_not_found",
      "raw_result": ""
    }
  ]
}
```

### Таблица кодов ошибок

| `code` | Что показать пользователю | Что делать |
|--------|--------------------------|------------|
| `access_denied` | «Пользователь с указанным ID не найден. Проверьте корректность введенных данных. Если ID указан верно, обратитесь к ответственному сотруднику для помощи в регистрации.» | Оставить экран `select_user`, дать ввести ID заново и показать кнопку `Помощь в регистрации` на `registration_help_url` |
| `invalid_base` | «База недоступна для этого пользователя» | Оставить экран `select_base`, дать выбрать базу заново |
| `car_number_not_recognized` | «Номер не распознан. Переснимите фото или введите вручную» | Показать форму повторной загрузки и ввода |
| `cropped` | «Шина обрезана по краям. Сделайте фото с отступом со всех сторон» | Показать форму повторной загрузки |
| `cropped_multiple` | «На фото несколько шин, или шина обрезана. Снимайте по одной» | Показать форму повторной загрузки |
| `no_detection` | «Шина не найдена. Убедитесь что шина в центре кадра» | Показать форму повторной загрузки |
| `tire_analysis_failed` | «Анализ не выполнен. Попробуйте переснять» | Показать форму повторной загрузки |
| `tire_analysis_api_unavailable` | «Сервис анализа временно недоступен. Попробуйте позже» | Показать форму повторной загрузки |
| `tire_analysis_api_bad_status` | «Ошибка сервиса анализа. Попробуйте позже» | Показать форму повторной загрузки |
| `tire_number_api_unavailable` | «Сервис распознавания номера недоступен» | Показать форму ввода вручную |
| `tire_number_api_bad_status` | «Ошибка сервиса распознавания номера шины» | Показать форму ввода вручную или повторную съёмку |
| `car_number_api_unavailable` | «Сервис распознавания авто недоступен» | Показать форму ввода вручную |
| `car_number_api_bad_status` | «Ошибка сервиса распознавания авто» | Показать форму ввода вручную или повторную съёмку |
| `send_failed` | «Ошибка отправки в 1С. Попробуйте ещё раз» | Оставить кнопку «Отправить» активной |
| `invalid_action` | «Действие сейчас недоступно» (ошибка Bitrix, не пользователя) | Проверить `allowed_actions` перед отправкой |
| `invalid_image` | «Не удалось прочитать изображение. Выберите другой файл» | Показать форму выбора файла |
| `upload_not_allowed` | Загрузка недоступна (ошибка Bitrix) | Проверить `allowed_actions` перед загрузкой |
| `invalid_tire_count` | «Введите корректное количество шин (больше 0)» | Показать форму ввода |
| `invalid_tire_number` | «Пустой номер подтверждать нельзя» | Оставить шаг `confirm_tire_number`, показать поле ввода |
| `invalid_manual_tire_number` | «Введите серийный номер вручную» | Оставить шаг `confirm_tire_number`, показать поле ввода |
| `invalid_source` | «Выберите источник: Склад или Транспорт» | Показать кнопки выбора |
| `cannot_go_back` | «Возврат невозможен на этом шаге» | Скрыть кнопку «Назад» |
| `no_next_tire` | «Все шины уже обработаны» (ошибка Bitrix) | Не показывать кнопку «Следующая шина» |

---

## Прогресс

Поле `progress` есть в каждом ответе. Используйте для полосы прогресса или счётчика шин.

```json
{
  "tire_count": 4,
  "current_tire": 2,
  "current_photo": 3,
  "max_photo": 3,
  "required_photos": 5,
  "is_last_tire": false
}
```

Пример использования:
```javascript
const { current_tire, tire_count, current_photo, required_photos } = data.progress;

// Показать: "Шина 2 из 4 — фото 3 из 5"
progressText.textContent = `Шина ${current_tire} из ${tire_count} — фото ${current_photo} из ${required_photos}`;

// Полоса прогресса по шинам
const tirePct = tire_count > 0 ? ((current_tire - 1) / tire_count) * 100 : 0;
```

---

## Сценарии прохождения

### Источник «Транспорт» (с фото авто)

```
1. POST /flow/start  {Bitrix ID}
   ← step: select_base

2. POST /flow/{id}/action  {action: "select_base", payload: {uid: "...", base_name: "..."}}
   ← step: select_source

3. POST /flow/{id}/action  {action: "select_source", payload: {source: "Транспорт"}}
   ← step: upload_car_photo

4. POST /flow/{id}/upload  (фото авто)
   ← step: confirm_car  (номер распознан)
   ИЛИ step: upload_car_photo + errors[car_number_not_recognized]  (не распознан)

   Если не распознан — пользователь вводит вручную:
   POST /flow/{id}/action  {action: "submit_manual_car_number", payload: {car_number: "А123ВС77"}}
   ← step: confirm_car

5. POST /flow/{id}/action  {action: "confirm_car"}
   ← step: set_tire_count

6. POST /flow/{id}/action  {action: "set_tire_count", payload: {tire_count: 4}}
   ← step: upload_tire_photo  (шина 1, фото 1)

   === Цикл по фотографиям шины ===

7. POST /flow/{id}/upload  (фото шины)
   ← step: confirm_photo  (для фото 1, 2, 3, 5)
   ИЛИ step: confirm_tire_number  (для фото 4)

7а. Если confirm_photo:
   POST /flow/{id}/action  {action: "confirm_photo"}
   ← step: upload_tire_photo  (следующее фото)

7б. Если confirm_tire_number (фото 4):
   POST /flow/{id}/action  {action: "confirm_tire_number", payload: {number: "АВС12345"}}
   ← step: upload_tire_photo  (фото 5)

   === Конец цикла по фото ===
   (повторяем шаги 6-7 для фото 1, 2, 3, 4, 5)

9. После 5 фото:
   ← step: post_required_photos

   Если шин больше одной:
   POST /flow/{id}/action  {action: "next_tire"}
   ← step: upload_tire_photo  (шина 2, фото 1)
   ... повторяем для каждой шины ...

10. POST /flow/{id}/action  {action: "finish_without_comment"}
   ← step: confirm_send

11. POST /flow/{id}/action  {action: "confirm_send"}
    ← step: finished  {status: "sent"}
```

### Источник «Склад» (без фото авто)

```
1. POST /flow/start  {Bitrix ID}
   ← step: select_base

2. POST /flow/{id}/action  {action: "select_base", payload: {uid: "...", base_name: "..."}}
   ← step: select_source

3. POST /flow/{id}/action  {action: "select_source", payload: {source: "Склад"}}
   ← step: set_tire_count  (шаг upload_car_photo пропускается)

4. ... далее аналогично «Транспорту», начиная с шага set_tire_count
```

### Если пользователь хочет добавить комментарий

```
На шаге post_required_photos (после всех шин):

POST /flow/{id}/action  {action: "finish_with_comment"}
← step: comment

POST /flow/{id}/action  {action: "submit_comment", payload: {comment: "Текст комментария"}}
← step: confirm_send
```

---

## Вспомогательные эндпоинты

### Проверка работоспособности

```
GET /api/health
```
Ответ: `{ "status": "ok" }`  
Используйте для проверки доступности сервера перед стартом.

### Проверка ML-контейнеров (важно!)

Backend проксирует распознавание в ML-контейнеры. Если при загрузке фото шаг не меняется — проверьте доступность ML:

```powershell
# С машины, где запущен backend:
curl.exe -s http://5.35.10.157:11436/health
curl.exe -s http://5.35.10.157:11435/health
curl.exe -s http://5.35.10.157:11437/health
```

Если контейнеры не отвечают — backend не сможет распознать номер или проанализировать шину, и вернёт тот же шаг загрузки.

### Получение demo-изображения (пример ракурса)

```
GET /api/demo/{file_name}
```

Когда в `ui_payload` есть поле `demo_image` — показывайте пример через этот эндпоинт.

```javascript
if (ui_payload.demo_image) {
  img.src = `${API}/demo/${ui_payload.demo_image}`;
}
```

Примеры файлов:
- `start_img.png` — пример фото авто
- `car_1.jpg`, `car_2.jpg` ... — примеры фото шин для источника «Транспорт»
- `warehause_1.jpg`, `warehause_2.jpg` ... — примеры для «Склад»

### Получение загруженного фото

```
GET /api/flow/{session_id}/file/{file_name}
```

Когда в `ui_payload` есть поле `preview_file` — загружайте фото через этот эндпоинт.

```javascript
if (ui_payload.preview_file) {
  img.src = `${API}/flow/${SESSION_ID}/file/${ui_payload.preview_file}`;
}
```

---

## Частые ошибки интеграции

### Отправка действия без проверки `allowed_actions`

Перед каждым `action` проверяйте, что оно есть в `allowed_actions` последнего ответа backend. Если отправить действие не на том шаге, backend вернет ошибку `invalid_action`, а `step` не изменится.

### Потеря `session_id`

`session_id` нужно сохранить после `POST /flow/start` и использовать во всех последующих запросах. Если пользователь закрыл страницу и вернулся, состояние можно восстановить через `GET /api/flow/{session_id}`.

### Повторный старт во время синхронизации

`POST /flow/start` может выполняться дольше обычного, потому что backend обновляет данные пользователя из Yandex Bucket. На время запроса заблокируйте кнопку старта и покажите loader.

### Пользователь не найден

Если backend вернул `step: "select_user"` и ошибку `access_denied`, покажите пользователю `errors[0].message`. Если в ошибке есть `registration_help_url` и `registration_help_label`, можно показать кнопку помощи. Эти поля дополнительные: если кнопка пока не реализована, их можно игнорировать.

### Фото загружено, но шаг не изменился

Ориентируйтесь на `errors` в ответе backend. Чаще всего это означает, что фото не распознано, изображение невалидно или временно недоступен один из ML-сервисов. В любом случае повторно рендерите экран по текущему `step` из ответа.
