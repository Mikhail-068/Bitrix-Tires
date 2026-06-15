# 🏗️ Архитектура системы ProTires

## 📋 Содержание
- [Общая архитектура](#общая-архитектура)
- [Слои системы](#слои-системы)
- [Модульная структура](#модульная-структура)
- [Потоки данных](#потоки-данных)
- [AI Pipeline](#ai-pipeline)
- [Файловая структура](#файловая-структура)

---

## 🏗️ Общая архитектура

Система построена на основе **многослойной модульной архитектуры** с четким разделением ответственности и двумя каналами взаимодействия:

```mermaid
flowchart TB
    subgraph presentation["🎨 Слой представления"]
        TG["📱 Интерфейс Telegram"]
        WEB["🌐 Web-визард (React)"]
        UI["🎨 UI компоненты"]
    end
    
    subgraph business["🧠 Слой бизнес-логики"]
        AUTH["🔐 Авторизация"]
        CORE["🧠 Основная обработка"]
        SEL["🎯 Логика выбора"]
        FLOW["⚡ Flow Engine (FastAPI)"]
    end
    
    subgraph aiml["🤖 Слой ИИ/МО"]
        YOLO["🎯 Детекция YOLO"]
        VIT["🧠 Анализ ViT"]
        SEASON["❄️ Классификация сезона"]
        SPIKES["🔩 Детекция шипов"]
        OCR["🔤 OCR номеров (Gemma)"]
    end
    
    subgraph data["💾 Слой данных"]
        FILES["📁 Файловая система"]
        EXPORT["📤 Система экспорта"]
        BACKUP["🔄 Резервирование"]
    end
    
    subgraph external["🌐 Внешние сервисы"]
        S3["☁️ Yandex S3"]
        API1C["🏢 1C API"]
        OLLAMA["🤖 Ollama AI"]
    end
    
    TG --> AUTH
    WEB --> FLOW
    AUTH --> SEL
    SEL --> CORE
    FLOW --> CORE
    CORE --> YOLO
    CORE --> VIT
    CORE --> SEASON
    CORE --> SPIKES
    CORE --> OCR
    
    SEASON --> SPIKES
    SPIKES --> VIT
    
    YOLO --> FILES
    VIT --> FILES
    SEASON --> FILES
    SPIKES --> FILES
    OCR --> FILES
    
    FILES --> EXPORT
    EXPORT --> BACKUP
    EXPORT --> API1C
    
    AUTH <--> S3
    OCR <--> OLLAMA
    
    UI --> TG
```

---

## 🎯 Слои системы

### 1. 🎨 Слой представления
- **📱 Интерфейс Telegram** — `tires.py` (python-telegram-bot)
- **🌐 Web-визард** — React SPA (`web_frontend/src/App.jsx`)
- **🎨 UI компоненты** — модули `ui/` (Telegram), `styles.css` (Web)

### 2. 🧠 Слой бизнес-логики
- **🔐 Авторизация** — `auth/authorization.py` (Telegram), `flow_engine.py` (Web)
- **🧠 Основная обработка** — `core/tire_classification.py` (Telegram), `flow_engine.py` (Web)
- **🎯 Логика выбора** — модули `selection/` (Telegram)
- **⚡ Flow Engine** — `web_backend/app/flow_engine.py` (Web backend)

### 3. 🤖 Слой ИИ/МО (Docker-контейнеры)
- **🎯 Детекция YOLO** — `tire-analysis-docker` (детекция шин)
- **🧠 Анализ ViT** — `tire-analysis-docker` (анализ состояния)
- **❄️ Классификация сезона** — `tire-analysis-docker` (определение сезона)
- **🔩 Детекция шипов** — `tire-analysis-docker` (детекция шипов)
- **🔤 OCR номеров авто** — `car_number_docker` (распознавание гос. номеров)
- **🔤 OCR номеров шин** — `tires_number_docker` (Gemma AI через Ollama)

### 4. 💾 Слой данных
- **📁 Файловая система** — структурированное хранение (`Users/`, `AtWork/`)
- **📤 Система экспорта** — интеграция с 1С
- **🔄 Резервирование** — резервное копирование (Yandex S3)

---

## 🔄 Модульная структура

```mermaid
flowchart LR
    subgraph core["🤖 Основные модули"]
        MAIN["tires.py<br/>📋 Точка входа (Telegram)"]
        FLOW["flow_engine.py<br/>⚡ Точка входа (Web)"]
        PROC["tire_processing/<br/>🛞 Обработка"]
        IMG["image/<br/>🖼️ Изображения"]
    end
    
    subgraph ui["🎨 UI модули"]
        UI_MOD["ui/<br/>🎨 Интерфейс Telegram"]
        SEL["selection/<br/>🎯 Выбор"]
        AUTH_MOD["auth/<br/>🔐 Авторизация"]
    end
    
    subgraph support["🔧 Вспомогательные модули"]
        EXP["export/<br/>📤 Экспорт"]
        UTIL["utils/<br/>🛠️ Утилиты"]
    end
    
    subgraph ml_containers["🤖 ML-контейнеры"]
        TIRE_ANAL["tire-analysis-docker<br/>🔬 Анализ шин"]
        CAR_NUM["car_number_docker<br/>🔢 Номера авто"]
        TIRE_NUM["tires_number_docker<br/>🔤 Номера шин (Gemma)"]
    end
    
    MAIN --> PROC
    MAIN --> IMG
    MAIN --> UI_MOD
    MAIN --> SEL
    MAIN --> AUTH_MOD
    FLOW --> PROC
    
    PROC --> TIRE_ANAL
    PROC --> CAR_NUM
    PROC --> TIRE_NUM
    IMG --> TIRE_ANAL
    UI_MOD --> UTIL
    SEL --> AUTH_MOD
    PROC --> EXP
```

---

## 📊 Потоки данных

### 🔄 Основной поток обработки (Telegram)

```mermaid
sequenceDiagram
    participant U as 👤 Пользователь
    participant T as 📱 Телеграм
    participant M as 🤖 Главный обработчик
    participant P as 🛞 Процессор
    participant AI as 🧠 ML-контейнеры
    participant ST as 💾 Хранилище
    
    U->>T: 📸 Загрузка фото №2
    T->>M: Сообщение с фото
    M->>M: Определить тип фото = 2
    M->>P: Направить в tire_2_front_view
    P->>AI: POST /analyze (mode=full)
    AI-->>P: Результат: сезон, шипы, качество
    P->>P: Усиленная логика решений
    Note over P: Отсутствуют шипы → "ПЛОХАЯ"
    P->>ST: Сохранить результаты + данные шипов
    P-->>M: Обработка завершена
    M-->>T: Отправить результаты с визуализацией шипов
    T-->>U: Показать обработанное изображение + данные шипов
```

### 🔄 Основной поток обработки (Web)

```mermaid
sequenceDiagram
    participant U as 👤 Пользователь
    participant W as 🌐 Браузер
    participant B as ⚡ FastAPI Backend
    participant AI as 🧠 ML-контейнеры
    participant ST as 💾 Хранилище
    
    U->>W: Загрузка фото
    W->>B: POST /api/flow/{id}/upload
    B->>AI: POST /analyze (mode=full)
    AI-->>B: Результат: сезон, шипы, качество
    B->>B: Усиленная логика решений
    B->>ST: Сохранить результаты
    B-->>W: Новый flow_state (step, ui_payload)
    W-->>U: Перерисовать экран
```

---

## 🤖 AI Pipeline

```mermaid
flowchart TB
    INPUT["📸 Входное изображение"] --> CONV["🔄 Конвертация формата"]
    CONV --> PREP["🛠️ Предобработка"]
    
    PREP --> ROUTER{"🎯 Роутер типа фото"}
    
    ROUTER -->|1| YOLO1["🎯 Детекция YOLO"]
    ROUTER -->|2| YOLO2["🎯 Детекция YOLO + Сезон"]
    ROUTER -->|3,5| SIMPLE["💾 Простое сохранение"]
    ROUTER -->|4| OCR_FLOW["🔤 Поток OCR (Gemma)"]
    
    YOLO1 --> VIT1["🧠 Анализ ViT"]
    YOLO2 --> SEASON["❄️ Классификация сезона"]
    
    SEASON --> SEASON_CHECK{"🌡️ Тип сезона"}
    SEASON_CHECK -->|Лето| VIT2["🧠 Анализ ViT"]
    SEASON_CHECK -->|Зима| SPIKES["🔩 Детекция шипов"]
    SEASON_CHECK -->|Уточнить| VIT2
    
    SPIKES --> SPIKE_COUNT["📊 Подсчёт и цвета шипов"]
    SPIKE_COUNT --> VIT2
    
    VIT1 --> CLASS1{"📊 Классификация"}
    VIT2 --> ENHANCED{"🧠 Усиленная логика"}
    
    ENHANCED --> SPIKE_CHECK{"🔩 Отсутствуют шипы?"}
    SPIKE_CHECK -->|Да| FORCE_BAD["❌ Принудительно 'ПЛОХАЯ'"]
    SPIKE_CHECK -->|Нет| NORMAL_CLASS["📊 Обычная логика ViT"]
    
    CLASS1 -->|>8.0| BAD1["❌ ПЛОХАЯ"]
    CLASS1 -->|≤8.0| CHECK1["⚠️ УТОЧНИТЬ"]
    
    NORMAL_CLASS -->|>8.0| BAD2["❌ ПЛОХАЯ"]
    NORMAL_CLASS -->|≤8.0| CHECK2["⚠️ УТОЧНИТЬ"]
    
    FORCE_BAD --> VISUAL["🎨 Создание визуализации"]
    BAD1 --> VISUAL
    CHECK1 --> VISUAL
    BAD2 --> VISUAL
    CHECK2 --> VISUAL
    SIMPLE --> VISUAL
    OCR_FLOW --> VISUAL
    
    VISUAL --> SAVE["💾 Сохранение файлов"]
    SAVE --> CONFIRM["✅ Подтверждение пользователя"]
```

---

## 📁 Файловая структура

### 🗂️ Реальная структура проекта

```
ProTires/
├── Telegram_bot/                # 🤖 Telegram-бот
│   ├── tires.py                # 🚀 Главный файл
│   ├── auth/                   # 🔐 Авторизация
│   ├── core/                   # 🧠 Ядро системы
│   ├── image/                  # 🖼️ Обработка изображений
│   ├── tire_processing/        # 🛞 Специализированная обработка
│   │   ├── tire_12_analysis_api.py   # API к tire-analysis-docker
│   │   ├── tire_3_tread_depth.py    # Фото 3 (глубина)
│   │   ├── tire_4_serial_number.py # Фото 4 (OCR через контейнер)
│   │   ├── tire_5_brand_model.py   # Фото 5 (марка/модель)
│   │   ├── tire_additional.py      # Доп. фото
│   │   └── tire_processor.py       # Центральный роутер
│   ├── ui/                     # 🎨 Интерфейс
│   ├── selection/              # 🎯 Выбор источника
│   ├── export/                 # 📤 Экспорт
│   └── utils/                  # 🛠️ Утилиты
├── web_backend/                # ⚡ FastAPI backend
│   ├── app/
│   │   ├── main.py            # Точка входа
│   │   ├── routes.py          # API endpoints
│   │   ├── flow_engine.py     # Оркестрация сессий
│   │   └── settings.py        # Конфигурация
│   ├── Dockerfile
│   └── docker-compose.yml
├── web_frontend/               # 🎨 React SPA
│   ├── src/App.jsx            # Визард
│   ├── styles.css             # Стили
│   └── vite.config.js         # Прокси на backend
├── tire-analysis-docker/       # 🔬 ML-контейнер: анализ шин
│   ├── app/engine.py          # YOLO + ViT + сезон + шипы
│   └── Dockerfile
├── car_number_docker/          # 🔢 ML-контейнер: номера авто
│   ├── app/detector.py        # Распознавание гос. номеров
│   └── Dockerfile
├── tires_number_docker/        # 🔤 ML-контейнер: номера шин
│   ├── app/detector.py        # YOLO-OBB + Gemma OCR
│   └── Dockerfile
├── model/                      # 🧠 ML-модели (веса)
│   ├── yolo_det_class_model.pt
│   ├── good_feats_fp16.pt
│   ├── YOLOv11_cls_summer_winter.pt
│   ├── weights_thorns.pt
│   └── YOLO_OBB_4_tires.pt
├── AtWork/                     # 👥 Данные пользователей
├── Users/                      # 📁 Пользовательские сессии
├── Save_JSON/                  # 💾 Резервные JSON
├── log_upload/                 # 📋 Логи отправки
├── DEMO_img/                   # 🖼️ Демо изображения
├── DATA_txt/                   # 📄 Текстовые данные
├── dir_json/                   # 📁 JSON конфигурации
└── docs/                       # 📖 Документация
```

### 🧠 ML Модели (хранятся в model/)
- `yolo_det_class_model.pt` — детекция шин (tire-analysis-docker)
- `good_feats_fp16.pt` — ViT эмбеддинги (tire-analysis-docker)
- `YOLOv11_cls_summer_winter.pt` — сезонная классификация (tire-analysis-docker)
- `weights_thorns.pt` — детекция шипов (tire-analysis-docker)
- `YOLO_OBB_4_tires.pt` — oriented bounding box для номеров шин (tires_number_docker)

---

### 🔧 Усиленная логика принятия решений
**Для зимних шин:**
- Отсутствие шипов → принудительно "ПЛОХАЯ"
- Наличие шипов → стандартная ViT логика

**Для летних шин:**
- Стандартная ViT классификация

### 📊 JSON экспорт включает:
```json
{
  "tire_analysis": {
    "season": "Зимняя шина",
    "season_confidence": 0.95,
    "spikes": {
      "Да": 15,
      "Нет": 2,
      "Другое": 1
    },
    "enhanced_decision": "Missing spikes detected → ПЛОХАЯ"
  }
}
```
