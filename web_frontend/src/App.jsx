import React, { useCallback, useEffect, useMemo, useState } from "react";
import countImageUrl from "../count.png";
import logoUrl from "../tire.png";
import transportIconUrl from "../transport.png";
import warehouseIconUrl from "../warehouse.png";

const STORAGE_KEY = "protires_session_id";
const THEME_KEY = "protires_theme";
const CAR_PHOTO_INSTRUCTION = "Загрузите автомобиль, чтобы полностью был в кадре. Не отходите слишком далеко, номер должен быть читаемым";

const STEP_STAGES = {
  select_base: 0,
  select_user: 0,
  select_source: 0,
  select_transport_method: 1,
  upload_car_photo: 1,
  enter_manual_car_number: 1,
  confirm_car: 1,
  set_tire_count: 1,
  upload_tire_photo: 2,
  confirm_photo: 2,
  confirm_tire_number: 2,
  post_required_photos: 2,
  comment: 3,
  confirm_send: 3,
  finished: 4,
};

function getDefaultApiRoot() {
  return "/api";
}

function getSessionId() {
  return localStorage.getItem(STORAGE_KEY) || "";
}

function setSessionId(id) {
  if (!id) localStorage.removeItem(STORAGE_KEY);
  else localStorage.setItem(STORAGE_KEY, id);
}

function getInitialTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

async function resizeImageToFHD(file) {
  if (!file || !file.type.startsWith("image/")) return file;
  return new Promise((resolve) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      const maxDim = 1920;
      let { width, height } = img;
      if (width <= maxDim && height <= maxDim) {
        resolve(file);
        return;
      }
      if (width > height) {
        height = Math.round((height * maxDim) / width);
        width = maxDim;
      } else {
        width = Math.round((width * maxDim) / height);
        height = maxDim;
      }
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0, width, height);
      canvas.toBlob((blob) => {
        if (!blob) {
          resolve(file);
          return;
        }
        const newFile = new File([blob], file.name.replace(/\.[^.]+$/, ".jpg"), {
          type: "image/jpeg",
          lastModified: Date.now(),
        });
        resolve(newFile);
      }, "image/jpeg", 0.85);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(file);
    };
    img.src = url;
  });
}

function escText(value) {
  return String(value ?? "");
}

// Палитра bbox в деловом стиле (синий → бирюзовый → зелёный), углы для билинейного меша
const BBOX_CORNERS = {
  tl: [47, 134, 214],   // синий
  tr: [37, 183, 196],   // бирюзовый
  br: [25, 168, 110],   // зелёный
  bl: [55, 128, 206],   // глубокий синий
};

function lerpColor(a, b, t) {
  const r = Math.round(a[0] + (b[0] - a[0]) * t);
  const g = Math.round(a[1] + (b[1] - a[1]) * t);
  const bl = Math.round(a[2] + (b[2] - a[2]) * t);
  return `rgb(${r}, ${g}, ${bl})`;
}

function getStages(flowState) {
  const source = String(flowState?.context?.source || "");
  let stage2 = "Выбор источника";
  if (source === "Транспорт") stage2 = "Номер авто";
  if (source === "Склад") stage2 = "Склад";
  return [
    { label: "Настройка" },
    { label: stage2 },
    { label: "Фото шин" },
    { label: "Отправка" },
    { label: "Готово" },
  ];
}

function App() {
  const [apiRoot] = useState(getDefaultApiRoot());
  const [flowState, setFlowState] = useState(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [lightboxPhoto, setLightboxPhoto] = useState(null);
  const [theme, setTheme] = useState(getInitialTheme);

  const normalizedApiRoot = useMemo(() => apiRoot.trim().replace(/\/$/, ""), [apiRoot]);

  const showToast = useCallback((message, type = "info") => {
    setToast({ message: String(message), type });
    window.clearTimeout(showToast._timer);
    showToast._timer = window.setTimeout(() => setToast(null), 6000);
  }, []);

  const fileUrl = useCallback((fileName) => {
    if (!flowState?.session_id || !fileName) return "";
    return `${normalizedApiRoot}/flow/${encodeURIComponent(flowState.session_id)}/file/${encodeURIComponent(fileName)}?t=${Date.now()}`;
  }, [flowState?.session_id, normalizedApiRoot]);

  const apiFetch = useCallback(async (path, opts = {}) => {
    const response = await fetch(`${normalizedApiRoot}${path}`, opts);
    const text = await response.text();
    let json;
    try {
      json = JSON.parse(text);
    } catch {
      json = { raw: text };
    }
    if (!response.ok) {
      const error = Object.assign(new Error(`HTTP ${response.status}`), { body: json });
      throw error;
    }
    return json;
  }, [normalizedApiRoot]);

  const runBusy = useCallback(async (fn) => {
    setBusy(true);
    try {
      await fn();
    } catch (error) {
      const detail = error.body ? JSON.stringify(error.body, null, 2) : String(error);
      showToast(detail, "error");
    } finally {
      setBusy(false);
    }
  }, [showToast]);

  const apiPost = useCallback((path, body) => apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }), [apiFetch]);

  const startFlow = useCallback(async ({ telegramId = "", surname = "" } = {}) => {
    setSessionId(null);
    setFlowState(null);
    await runBusy(async () => {
      const trimmedId = String(telegramId || "").trim();
      const trimmedSurname = String(surname || "").trim();
      const body = trimmedId ? { TelegramID: trimmedId, surname: trimmedSurname } : {};
      const nextState = await apiPost("/flow/start", body);
      setSessionId(nextState.session_id);
      setFlowState(nextState);
    });
  }, [apiPost, runBusy]);

  const loadFlow = useCallback(async () => {
    const id = getSessionId();
    if (!id) return;
    await runBusy(async () => {
      setFlowState(await apiFetch(`/flow/${id}`));
    });
  }, [apiFetch, runBusy]);

  const sendAction = useCallback(async (action, payload = {}) => {
    const id = getSessionId();
    if (!id) {
      showToast("Сессия не запущена", "error");
      return;
    }
    await runBusy(async () => {
      setFlowState(await apiPost(`/flow/${id}/action`, { action, payload }));
    });
  }, [apiPost, runBusy, showToast]);

  const uploadImage = useCallback(async (file) => {
    const id = getSessionId();
    if (!id) {
      showToast("Сессия не запущена", "error");
      return;
    }
    if (!file) {
      showToast("Выберите изображение", "error");
      return;
    }
    await runBusy(async () => {
      const form = new FormData();
      form.append("image", file);
      setFlowState(await apiFetch(`/flow/${id}/upload`, { method: "POST", body: form }));
    });
  }, [apiFetch, runBusy, showToast]);

  useEffect(() => {
    setSessionId(null);
    setFlowState(null);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    if (!lightboxPhoto) return undefined;
    const close = (event) => {
      if (event.key === "Escape") setLightboxPhoto(null);
    };
    window.addEventListener("keydown", close);
    document.body.classList.add("lightbox-open");
    return () => {
      window.removeEventListener("keydown", close);
      document.body.classList.remove("lightbox-open");
    };
  }, [lightboxPhoto]);

  const contextValue = {
    apiRoot: normalizedApiRoot,
    flowState,
    fileUrl,
    startFlow,
    sendAction,
    uploadImage,
    openLightbox: setLightboxPhoto,
    showToast,
  };

  return (
    <>
      <div className={`busy-bar${busy ? " active" : ""}`} />
      <header className="topbar">
        <div className="topbar-left">
          <div className="brand-plate">
            <img className="topbar-logo" src={logoUrl} alt="ProTires" />
            <div className="topbar-copy">
              <span className="topbar-eyebrow">Списание шин</span>
              <span className="topbar-title">ProTires</span>
            </div>
          </div>
        </div>
        <div className="topbar-right">
          <button
            className="theme-toggle"
            type="button"
            aria-label={theme === "dark" ? "Включить светлую тему" : "Включить темную тему"}
            aria-pressed={theme === "dark"}
            onClick={() => setTheme((value) => (value === "dark" ? "light" : "dark"))}
          >
            <span className="theme-toggle-icon" aria-hidden="true">☀</span>
            <span className="theme-toggle-icon" aria-hidden="true">☾</span>
            <span className="theme-toggle-thumb" aria-hidden="true" />
          </button>
          <button className="btn-primary btn-sm" type="button" disabled={busy} onClick={() => startFlow()}>+ Новая сессия</button>
          <button className="btn-ghost btn-sm" type="button" disabled={busy} title="Обновить состояние" onClick={loadFlow}>↻</button>
          <button className="btn-ghost btn-sm" type="button" disabled={busy} title="Сбросить сессию" onClick={() => { setSessionId(null); setFlowState(null); }}>✕</button>
        </div>
      </header>

      {flowState && (
        <nav className="stepper-nav">
          <Stepper flowState={flowState} sendAction={sendAction} />
        </nav>
      )}

      <main className="main">
        <ErrorBanner errors={flowState?.errors || []} />
        <ProgressPanel flowState={flowState} />
        <div className="wizard-card">
          <WizardContent context={contextValue} />
        </div>
      </main>

      <div className={`toast toast-${toast?.type || "info"}${toast ? " show" : ""}`}>{toast?.message || ""}</div>
      {lightboxPhoto && <PhotoLightbox photo={lightboxPhoto} onClose={() => setLightboxPhoto(null)} />}
    </>
  );
}

function sessionMeta(flowState) {
  if (!flowState) return "";
  const ctx = flowState.context || {};
  const p = flowState.progress || {};
  const parts = [`#${flowState.session_id}`];
  if (ctx.selected_base) parts.push(ctx.selected_base);
  if (ctx.selected_user) parts.push(ctx.selected_user);
  if (ctx.source) parts.push(ctx.source);
  if (ctx.car_number) parts.push(ctx.car_number);
  if (p.tire_count > 0) parts.push(`Шина ${p.current_tire}/${p.tire_count}`);
  return parts.join(" · ");
}

function Stepper({ flowState, sendAction }) {
  if (!flowState) return <div className="stepper" />;
  const stage = STEP_STAGES[flowState.step] ?? 0;
  const allowed = flowState.allowed_actions || [];
  const canBack = allowed.includes("navigate_back");

  return (
    <div className="stepper">
      {getStages(flowState).map((item, index) => {
        const done = index < stage;
        const active = index === stage;
        return (
          <FragmentStep
            key={item.label}
            item={item}
            index={index}
            done={done}
            active={active}
            isLast={index === getStages(flowState).length - 1}
            onBack={done && canBack ? () => {
              if (index === 0 && !window.confirm("Вернуться к шагу «Настройка»?\nБудет открыт выбор источника (Склад/Транспорт) для текущей базы.")) return;
              sendAction("navigate_back", { target_stage: index, preserve_context: index === 0 });
            } : null}
          />
        );
      })}
    </div>
  );
}

function FragmentStep({ item, index, done, active, isLast, onBack }) {
  return (
    <>
      <div className={`step-item${done ? " done" : active ? " active" : ""}${onBack ? " step-item-nav" : ""}`} onClick={onBack || undefined} title={onBack ? `Вернуться: ${item.label}` : undefined}>
        <div className="step-dot">{done ? "✓" : index + 1}</div>
        <span className="step-label">{item.label}</span>
      </div>
      {!isLast && <div className={`step-line${done ? " done" : ""}`} />}
    </>
  );
}

function ErrorBanner({ errors }) {
  if (!errors.length) return <div className="error-banner" />;
  return (
    <div className="error-banner">
      {errors.map((error, index) => (
        <div className="error-item" key={`${error.code || "error"}-${index}`}>
          <div className="error-header">
            <span className="error-msg">{error.message || ""}</span>
          </div>
          {Object.keys(error).some((key) => !["code", "message"].includes(key)) && (
            <details className="error-detail">
              <summary>Подробности</summary>
              <pre>{JSON.stringify(error, null, 2)}</pre>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}

function ProgressPanel({ flowState }) {
  const stage = STEP_STAGES[flowState?.step] ?? 0;
  const stages = getStages(flowState);
  const percent = flowState ? Math.round(((stage + 1) / stages.length) * 100) : 0;
  const ctx = flowState?.context || {};
  const progress = flowState?.progress || {};
  const details = [];
  if (ctx.selected_base) details.push(ctx.selected_base);
  if (ctx.source) details.push(ctx.source);
  if (ctx.car_number) details.push(ctx.car_number);
  // tire count moved to TireRemainingBadge above tire content

  return (
    <section className="progress-panel" aria-label="Текущий прогресс">
      <div className="progress-track">
        <div style={{ width: `${percent}%` }} />
      </div>
      <div className="progress-meta">
        <span>{flowState ? (details.join(" · ") || `Сессия #${flowState.session_id}`) : "Bitrix24 и справочники подтянутся после старта"}</span>
      </div>
    </section>
  );
}

function WizardContent({ context }) {
  const { flowState } = context;
  const [telegramId, setTelegramId] = useState("");
  const [surname, setSurname] = useState("");

  useEffect(() => {
    if (flowState?.step) {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, [flowState?.step]);

  if (!flowState) {
    const submitTelegramId = () => {
      const idValue = telegramId.trim();
      const surnameValue = surname.trim();
      if (!idValue || !surnameValue) {
        context.showToast("Введите Telegram ID и фамилию", "error");
        return;
      }
      context.startFlow({ telegramId: idValue, surname: surnameValue });
    };

    return (
      <div className="step-body">
        <h2 className="step-title">Авторизация</h2>
        <p className="step-hint">Введите Telegram ID и фамилию. Backend обновит базу из Yandex S3 и проверит доступ.</p>
        <input
          className="input-full"
          value={telegramId}
          onChange={(event) => setTelegramId(event.target.value.replace(/\D+/g, ""))}
          onKeyDown={(event) => { if (event.key === "Enter") submitTelegramId(); }}
          placeholder="Telegram ID"
          inputMode="numeric"
          autoComplete="off"
        />
        <input
          className="input-full"
          value={surname}
          onChange={(event) => setSurname(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter") submitTelegramId(); }}
          placeholder="Фамилия"
          autoComplete="family-name"
        />
        <button className="btn-primary btn-full mt-12" type="button" onClick={submitTelegramId}>▶ Начать сессию</button>
      </div>
    );
  }

  const payload = flowState.ui_payload || {};
  const allowed = flowState.allowed_actions || [];
  const props = { payload, allowed, context };

  switch (flowState.step) {
    case "select_base": return <SelectBase {...props} />;
    case "select_user": return <SelectUser {...props} />;
    case "select_source": return <SelectSource {...props} />;
    case "select_transport_method": return <UploadCarPhoto payload={{ ...payload, instruction: CAR_PHOTO_INSTRUCTION }} allowed={["upload_image", "submit_manual_car_number", "navigate_back"]} context={context} />;
    case "upload_car_photo": return <UploadCarPhoto {...props} />;
    case "enter_manual_car_number": return <EnterManualCarNumber {...props} />;
    case "confirm_car": return <ConfirmCar {...props} />;
    case "set_tire_count": return <SetTireCount {...props} />;
    case "upload_tire_photo": return <UploadTirePhoto {...props} />;
    case "confirm_photo": return <ConfirmPhoto {...props} />;
    case "confirm_tire_number": return <ConfirmTireNumber {...props} />;
    case "post_required_photos": return <PostRequiredPhotos {...props} />;
    case "comment": return <CommentStep {...props} />;
    case "confirm_send": return <ConfirmSend {...props} />;
    case "finished": return <Finished {...props} />;
    default:
      return <div className="step-body"><p className="step-hint">Шаг: {flowState.step}</p></div>;
  }
}

function SelectBase({ payload, context }) {
  const bases = payload.bases || [];
  return (
    <div className="step-body">
      <h2 className="step-title">Выберите базу</h2>
      {payload.user_name && <p className="step-sub">Сотрудник: {payload.user_name}</p>}
      <p className="step-hint">С какой базой работаем сегодня?</p>
      {!bases.length ? <p className="step-hint">Нет доступных баз. Проверьте AtWork.</p> : (
        <div className="choice-grid">
          {bases.map((base) => (
            <button className="choice-card" key={`${base.uid}-${base.base_name}`} type="button" onClick={() => context.sendAction("select_base", { uid: base.uid, base_name: base.base_name })}>
              <span className="choice-icon">🏢</span>
              <span className="choice-label">{base.base_name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function SelectUser({ payload, context }) {
  const [telegramId, setTelegramId] = useState("");
  const [surname, setSurname] = useState("");
  const submit = () => {
    if (!telegramId.trim() || !surname.trim()) {
      context.showToast("Введите Telegram ID и фамилию", "error");
      return;
    }
    context.sendAction("select_user", { telegram_id: telegramId.trim(), surname: surname.trim() });
  };
  return (
    <div className="step-body">
      <h2 className="step-title">{payload.title || "Авторизация"}</h2>
      <p className="step-hint">{payload.instruction || "Введите Telegram ID и фамилию"}</p>
      <input
        className="input-full"
        value={telegramId}
        onChange={(event) => setTelegramId(event.target.value.replace(/\D+/g, ""))}
        onKeyDown={(event) => { if (event.key === "Enter") submit(); }}
        placeholder="Telegram ID"
        inputMode="numeric"
        autoComplete="off"
      />
      <input
        className="input-full"
        value={surname}
        onChange={(event) => setSurname(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") submit(); }}
        placeholder="Фамилия"
        autoComplete="family-name"
      />
      <button className="btn-primary btn-full mt-12" type="button" onClick={submit}>Продолжить →</button>
    </div>
  );
}

function SelectSource({ payload, context }) {
  const userLine = payload.user_name ? (payload.user_id ? `${payload.user_name} · ID ${payload.user_id}` : payload.user_name) : "";
  return (
    <div className="step-body">
      <h2 className="step-title">Откуда поступают шины?</h2>
      {userLine && <p className="step-sub">Пользователь: {userLine}</p>}
      <div className="choice-grid">
        {[{ source: "Склад", icon: warehouseIconUrl, iconClass: "source-choice-img-warehouse" }, { source: "Транспорт", icon: transportIconUrl, iconClass: "source-choice-img-transport" }].map((item) => (
          <button className="choice-card source-choice-card" key={item.source} type="button" aria-label={item.source} onClick={() => context.sendAction("select_source", { source: item.source })}>
            <img className={`source-choice-img ${item.iconClass}`} src={item.icon} alt="" aria-hidden="true" />
          </button>
        ))}
      </div>
    </div>
  );
}

function UploadCarPhoto({ payload, allowed, context }) {
  const [manualNumber, setManualNumber] = useState("");
  const demoImage = payload.demo_image || "start_img.png";
  const fallbackRecognized = String(payload.last_recognized_number || context.flowState?.context?.car_number || "").trim();
  return (
    <div className="step-body">
      <h2 className="step-title">Фото автомобиля</h2>
      <p className="step-hint">{CAR_PHOTO_INSTRUCTION}</p>
      <DemoImage src={`${context.apiRoot}/demo/${encodeURIComponent(demoImage)}`} alt="Пример фото номера автомобиля" label="Фото автомобиля" />
      {payload.last_error_code && <div className="warn-box">Предыдущая попытка: {payload.last_error_code}{payload.last_raw_result ? ` — ${payload.last_raw_result}` : ""}</div>}
      <PhotoPreview fileName={payload.preview_file} label="Предпросмотр фото автомобиля" context={context} />
      <UploadZone onFile={context.uploadImage} />
      {allowed.includes("submit_manual_car_number") && (
        <>
          <input className="input-full mt-12" value={manualNumber} onChange={(event) => setManualNumber(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") context.sendAction("submit_manual_car_number", { car_number: (manualNumber.trim() || fallbackRecognized) }); }} placeholder="Введите номер вручную…" autoComplete="off" style={{ textTransform: "uppercase" }} />
          <button className="btn-ghost btn-full mt-8" type="button" onClick={() => {
            const value = manualNumber.trim() || fallbackRecognized;
            if (!value) return context.showToast("Введите номер перед сохранением", "error");
            return context.sendAction("submit_manual_car_number", { car_number: value });
          }}>💾 Сохранить введённый номер</button>
        </>
      )}
    </div>
  );
}

function EnterManualCarNumber({ context }) {
  const [value, setValue] = useState("");
  return (
    <div className="step-body">
      <h2 className="step-title">Номер автомобиля</h2>
      <p className="step-hint">Введите государственный номер транспортного средства:</p>
      <input className="input-full" value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") context.sendAction("submit_manual_car_number", { car_number: value.trim() }); }} placeholder="А123ВС68" autoComplete="off" style={{ textTransform: "uppercase" }} />
      <button className="btn-primary btn-full mt-12" type="button" onClick={() => context.sendAction("submit_manual_car_number", { car_number: value.trim() })}>Проверить →</button>
    </div>
  );
}

function ConfirmCar({ payload, context }) {
  const rows = [
    ["Номер", payload.number || "—"],
    ["Марка / модель", payload.brand || "—"],
    ["Организация", payload.org || "—"],
    ["В базе", payload.found_in_db ? "✓ Найден" : "✗ Не найден"],
  ];
  return (
    <div className="step-body">
      <h2 className="step-title">{payload.method === "automatic" ? "Номер авто распознан" : "Проверьте номер авто"}</h2>
      <PhotoPreview fileName={payload.preview_file} label="Фото автомобиля" context={context} />
      <InfoCard rows={rows} />
      <div className="btn-row mt-12">
        <button className="btn-primary" type="button" onClick={() => context.sendAction("confirm_car")}>✓ Подтвердить</button>
        <button className="btn-ghost" type="button" onClick={() => context.sendAction("retry_car")}>↺ Повторить</button>
      </div>
    </div>
  );
}

function SetTireCount({ context }) {
  const [count, setCount] = useState("1");
  const ctx = context.flowState?.context || {};
  const carLabel = ctx.car_number ? `${ctx.car_number}${ctx.car_brand ? ` · ${ctx.car_brand}` : ""}` : "";
  const submit = () => {
    const value = parseInt(count, 10);
    if (!value || value < 1) return context.showToast("Введите корректное количество шин", "error");
    return context.sendAction("set_tire_count", { tire_count: value });
  };
  const changeCount = (delta) => {
    setCount((prev) => {
      const current = parseInt(prev, 10) || 1;
      const next = Math.max(1, Math.min(999, current + delta));
      return String(next);
    });
  };
  return (
    <div className="step-body tire-count-step">
      <div className="count-visual">
        <img src={countImageUrl} alt="" aria-hidden="true" />
      </div>
      <div className="count-form">
        <h2 className="step-title">Сколько списываем шин?</h2>
        {carLabel && <p className="step-sub">Автомобиль: {carLabel}</p>}
        <div className="count-input-shell">
          <button
            className="count-btn count-btn-minus"
            type="button"
            aria-label="Уменьшить количество"
            onClick={() => changeCount(-1)}
          >
            −
          </button>
          <input
            className="count-input"
            type="number"
            min="1"
            max="999"
            inputMode="numeric"
            pattern="[0-9]*"
            value={count}
            aria-label="Количество списываемых шин"
            onChange={(event) => setCount(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") submit(); }}
            onWheel={(event) => { event.preventDefault(); changeCount(event.deltaY < 0 ? 1 : -1); }}
          />
          <button
            className="count-btn count-btn-plus"
            type="button"
            aria-label="Увеличить количество"
            onClick={() => changeCount(1)}
          >
            +
          </button>
        </div>
        <button className="btn-primary btn-full mt-12" type="button" onClick={submit}>Начать съёмку →</button>
      </div>
    </div>
  );
}

function TireRemainingBadge({ tireNumber, context }) {
  const total = Number(context.flowState?.progress?.tire_count) || 1;
  const current = Number(tireNumber) || 1;
  const remaining = Math.max(0, total - current + 1);
  return (
    <div className="tire-remaining-badge">
      <span className="tire-remaining-label">Осталось обработать шин</span>
      <div className="tire-remaining-numbers">
        <span className="tire-remaining-value" key={remaining}>{remaining}</span>
        <span className="tire-remaining-sep">/</span>
        <span className="tire-remaining-total">{total}</span>
      </div>
    </div>
  );
}

function UploadTirePhoto({ payload, allowed, context }) {
  const { tire_number, photo_number, description, demo_image } = payload;
  const pn = Number(photo_number);
  const maxP = Number(context.flowState?.progress?.max_photo || 0);
  const err = (context.flowState?.errors || [])[0] || null;
  const upstream = err?.upstream || null;
  const lastResult = payload.last_result || upstream || null;
  const lastError = String(lastResult?.error || err?.code || "");
  const detectionOverlay = lastResult?.detection || upstream?.detection || null;
  const hasPrev = !!payload.preview_file;
  const isCropped = (pn === 1 || pn === 2) && (lastError === "cropped" || lastError === "cropped_multiple");
  const croppedSides = (detectionOverlay?.cropped_sides || []).map((side) => ({ top: "сверху", bottom: "снизу", left: "слева", right: "справа" }[String(side)] || String(side)));

  return (
    <div className="step-body">
      <div className="tire-header">
        <h2 className="step-title step-title-badge">Шина {tire_number} — Фото {photo_number}</h2>
        <TireRemainingBadge tireNumber={tire_number} context={context} />
      </div>
      <TireProgress tireNumber={tire_number} photoNumber={photo_number} context={context} result={lastResult} />
      {description && <p className="step-hint photo-desc">{description}</p>}
      {demo_image && !hasPrev && <DemoImage src={`${context.apiRoot}/demo/${encodeURIComponent(demo_image)}`} alt={`Пример фото ${photo_number}`} />}
      {isCropped && hasPrev && <div className="warn-box">⚠️ Обнаружена обрезка шины ({croppedSides.length ? croppedSides.join(", ") : "по краям"}). Для этого фото шина должна быть в кадре полностью, с отступами со всех сторон.</div>}
      {hasPrev && !isCropped && <p className="step-hint">Ранее загруженное фото:</p>}
      {hasPrev && isCropped && <p className="step-hint crop-preview-label">Проблемное фото: красным отмечено место обрезки</p>}
      {hasPrev && <PhotoPreview fileName={payload.preview_file} label={`Шина ${tire_number} · Фото ${photo_number}`} result={lastResult} context={context} />}
      {hasPrev && !isCropped && <UploadStepResult result={lastResult} photoNumber={pn} />}
      <UploadZone
        key={`${tire_number}-${photo_number}-${lastError}-${payload.preview_file || "empty"}`}
        onFile={context.uploadImage}
      />
      {allowed.includes("navigate_forward") && hasPrev && !isCropped && (
        <button className="btn-fwd mt-8" type="button" onClick={() => {
          if (pn < maxP) context.sendAction("navigate_forward", { photo_number: pn + 1 });
          else if (maxP >= 5) context.sendAction("navigate_forward");
          else context.sendAction("navigate_forward", { photo_number: maxP + 1 });
        }}>{pn < maxP ? `Перейти к фото ${pn + 1} →` : maxP >= 5 ? "К завершению этой шины →" : `Перейти к фото ${maxP + 1} →`}</button>
      )}
    </div>
  );
}

function ConfirmPhoto({ payload, context }) {
  const { tire_number, photo_number, result, preview_file } = payload;
  return (
    <div className="step-body">
      <div className="tire-header">
        <h2 className="step-title step-title-badge">Шина {tire_number} — Фото {photo_number}</h2>
        <TireRemainingBadge tireNumber={tire_number} context={context} />
      </div>
      <TireProgress tireNumber={tire_number} photoNumber={photo_number} context={context} result={result} />
      <PhotoPreview fileName={preview_file} label={`Шина ${tire_number} · Фото ${photo_number}`} result={result} context={context} />
      <ResultTable result={result} photoNumber={photo_number} />
      <div className="btn-row mt-12">
        <button className="btn-primary" type="button" onClick={() => context.sendAction("confirm_photo")}>✓ Принять</button>
        <button className="btn-ghost" type="button" onClick={() => context.sendAction("retry_photo")}>↺ Переснять</button>
      </div>
    </div>
  );
}

function ConfirmTireNumber({ payload, context }) {
  const [manualNumber, setManualNumber] = useState("");
  const result = payload.result || {};
  return (
    <div className="step-body">
      <div className="tire-header">
        <h2 className="step-title step-title-badge">Шина {payload.tire_number} — Серийный номер</h2>
        <TireRemainingBadge tireNumber={payload.tire_number} context={context} />
      </div>
      <TireProgress tireNumber={payload.tire_number} photoNumber={payload.photo_number ?? 4} context={context} />
      <PhotoPreview fileName={payload.preview_file} label={`Шина ${payload.tire_number} · Серийный номер`} context={context} />
      <div className="number-card">
        {result.found && result.number ? (
          <>
            <div className="num-label">Распознанный номер</div>
            <div className="num-value">{result.number}</div>
          </>
        ) : <div className="num-not-found">Номер не распознан{result.error ? ` — ${result.error}` : ""}</div>}
      </div>
      <input className="input-full mt-12" value={manualNumber} onChange={(event) => setManualNumber(event.target.value)} placeholder="Введите номер вручную…" autoComplete="off" />
      <button className="btn-ghost btn-full mt-8" type="button" onClick={() => {
        const value = manualNumber.trim() || String(result.number || "").trim();
        if (!value) return context.showToast("Введите номер перед сохранением", "error");
        return context.sendAction("manual_tire_number", { number: value });
      }}>💾 Сохранить введённый номер</button>
      <button className="btn-ghost btn-full mt-8" type="button" onClick={() => context.sendAction("retake_photo_4")}>📷 Переснять фото</button>
    </div>
  );
}

function PostRequiredPhotos({ payload, allowed, context }) {
  const p = context.flowState?.progress || {};
  const maxP = (p.max_photo != null && p.max_photo > 0) ? Number(p.max_photo) : 5;
  const tireNumber = payload.tire_number;
  return (
    <div className="step-body">
      <div className="tire-header">
        <h2 className="step-title step-title-badge">Шина {tireNumber} — Обязательные фото готовы</h2>
        <TireRemainingBadge tireNumber={tireNumber} context={context} />
      </div>
      <TireProgress tireNumber={tireNumber} photoNumber={maxP + 1} context={context} />
      <p className="step-hint">{payload.is_last_tire ? "Все шины обработаны. Выберите дальнейшее действие:" : "Выберите дальнейшее действие:"}</p>
      <div className="action-grid">
        {allowed.includes("next_tire") && <button className="btn-primary btn-full" type="button" onClick={() => context.sendAction("next_tire")}>▶ Следующая шина ({Number(tireNumber) + 1})</button>}
        {allowed.includes("finish_without_comment") && <button className="btn-primary btn-full" type="button" onClick={() => context.sendAction("finish_without_comment")}>✓ Завершить</button>}
        {allowed.includes("finish_with_comment") && <button className="btn-ghost btn-full" type="button" onClick={() => context.sendAction("finish_with_comment")}>💬 Завершить с комментарием</button>}
        {allowed.includes("add_additional_photo") && <button className="btn-ghost btn-full" type="button" onClick={() => context.sendAction("add_additional_photo")}>📎 Добавить дополнительное фото</button>}
      </div>
    </div>
  );
}

function CommentStep({ context }) {
  const [comment, setComment] = useState("");
  return (
    <div className="step-body">
      <h2 className="step-title">Комментарий</h2>
      <p className="step-hint">Добавьте комментарий к сессии (необязательно):</p>
      <textarea className="textarea-full" rows={4} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Введите комментарий…" />
      <button className="btn-primary btn-full mt-12" type="button" onClick={() => context.sendAction("submit_comment", { comment })}>Продолжить →</button>
    </div>
  );
}

function ConfirmSend({ payload, context }) {
  const summary = payload.summary || {};
  const sendResult = payload.send_result || null;
  const photos = Array.isArray(summary.photos) ? summary.photos : [];
  const serials = photos.filter((photo) => Number(photo.photo_number) === 4 && photo.result?.number).map((photo) => `Шина ${photo.tire_number}: ${photo.result.number}`);
  const rows = [
    ["База", summary.selected_base],
    ["Пользователь", summary.user_name],
    ["Источник", summary.source],
  ];
  if (summary.car_number) rows.push(["Автомобиль", `${summary.car_number}${summary.car_brand ? ` · ${summary.car_brand}` : ""}`]);
  rows.push(["Шин", summary.tire_count ?? "—"]);
  if (summary.comment) rows.push(["Комментарий", summary.comment]);
  if (serials.length) rows.push(["Серийные номера", serials.join(" · ")]);
  rows.push(["Фотографий", photos.length]);

  return (
    <div className="step-body">
      <h2 className="step-title">Готово к отправке в 1С</h2>
      <p className="step-hint">Проверьте данные перед отправкой:</p>
      <InfoCard rows={rows} />
      <DonePhotos photos={photos} context={context} />
      <div className="btn-row mt-16">
        <button className="btn-primary btn-large" type="button" onClick={() => context.sendAction("confirm_send")}>📤 Отправить в 1С</button>
        <button className="btn-ghost" type="button" onClick={() => context.sendAction("cancel_send")}>✗ Отменить</button>
      </div>
      <SendResultPanel result={sendResult} />
    </div>
  );
}

function Finished({ payload, context }) {
  const success = payload.status === "sent";
  return (
    <div className="step-body center">
      <div className={`finish-icon${success ? " success" : ""}`}>{success ? "✓" : "✗"}</div>
      <h2 className="step-title mt-12">{success ? "Данные успешно отправлены!" : "Сессия завершена"}</h2>
      {payload.message && <p className="step-hint mt-8">{payload.message}</p>}
      <SendResultPanel result={payload.send_result} />
      <button className="btn-primary btn-full mt-20" type="button" onClick={() => context.showToast("Нажмите «+ Новая сессия» в верхней панели", "info")}>Начать новую сессию</button>
    </div>
  );
}

function SendResultPanel({ result }) {
  if (!result || typeof result !== "object") return null;
  const ok = result.ok === true || result.status === "success";
  const rows = [
    ["Время", result.timestamp],
    ["Адрес", result.request_url],
    ["ConnectionString", result.connection_string],
    ["HTTP", result.response_status],
    ["Тип ошибки", result.error_type],
    ["Длительность", result.elapsed_time_seconds != null ? `${result.elapsed_time_seconds} сек.` : ""],
    ["Лог", result.log_file],
  ].filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== "");
  return (
    <section className={`send-result-panel ${ok ? "send-result-success" : "send-result-error"}`} role="status" aria-live="polite">
      <div className="send-result-head">
        <span className="send-result-mark">{ok ? "✓" : "!"}</span>
        <div>
          <strong>{ok ? "1С приняла данные" : "1С не приняла данные"}</strong>
          <p>{result.message || (ok ? "Отправка завершена успешно" : "Отправка завершилась ошибкой")}</p>
        </div>
      </div>
      {rows.length > 0 && (
        <div className="send-result-grid">
          {rows.map(([key, value]) => (
            <React.Fragment key={key}>
              <span>{key}</span>
              <strong>{String(value)}</strong>
            </React.Fragment>
          ))}
        </div>
      )}
      {result.response_text && (
        <details className="send-result-detail">
          <summary>Ответ сервера</summary>
          <pre>{String(result.response_text)}</pre>
        </details>
      )}
    </section>
  );
}

function InfoCard({ rows }) {
  return (
    <div className="info-card">
      {rows.map(([key, value]) => (
        <div className="info-row" key={key}>
          <span>{key}</span>
          <strong>{escText(value ?? "—")}</strong>
        </div>
      ))}
    </div>
  );
}

function DemoImage({ src, alt, label = "Пример правильного фото:" }) {
  return (
    <div className="demo-photo-block">
      <p className="demo-photo-label">{label}</p>
      <img className="demo-photo-img" src={src} alt={alt} loading="lazy" />
    </div>
  );
}

function PhotoPreview({ fileName, label, result, context }) {
  if (!fileName) return null;
  const src = context.fileUrl(fileName);
  return (
    <button className="photo-preview photo-preview-button" type="button" onClick={() => context.openLightbox({ url: src, label, result })} aria-label={`Открыть фото: ${label}`}>
      <AnnotatedImage src={src} alt={label} result={result} />
    </button>
  );
}

function DonePhotos({ photos, context }) {
  const validPhotos = photos.filter((photo) => photo?.file_name);
  if (!validPhotos.length) return null;
  return (
    <section className="done-photos-section">
      <h3 className="done-photos-title">Сделанные фотографии</h3>
      <div className="done-photos-grid">
        {validPhotos.map((photo) => {
          const label = `Шина ${photo.tire_number ?? "—"} · Фото ${photo.photo_number ?? "—"}`;
          const src = context.fileUrl(photo.file_name);
          return (
            <button className="done-photo-card" type="button" key={`${photo.tire_number}-${photo.photo_number}-${photo.file_name}`} onClick={() => context.openLightbox({ url: src, label, result: photo.result })} aria-label={`Открыть фото: ${label}`}>
              <AnnotatedImage className="done-photo-img" src={src} alt={label} result={photo.result} loading="lazy" />
              <span className="done-photo-label">{label}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function PhotoLightbox({ photo, onClose }) {
  return (
    <div className="photo-lightbox" role="dialog" aria-modal="true" aria-label={photo.label}>
      <button className="photo-lightbox-backdrop" type="button" onClick={onClose} aria-label="Закрыть фото" />
      <div className="photo-lightbox-content">
        <div className="photo-lightbox-head">
          <strong>{photo.label}</strong>
          <button className="photo-lightbox-close" type="button" onClick={onClose} aria-label="Закрыть фото">×</button>
        </div>
        <AnnotatedImage className="photo-lightbox-image" src={photo.url} alt={photo.label} result={photo.result} />
      </div>
    </div>
  );
}

function bboxFromResult(result) {
  const detection = result?.detection;
  if (!detection || typeof detection !== "object") return null;
  const imageSize = Array.isArray(detection.image_size) && detection.image_size.length >= 2
    ? detection.image_size.map((value) => Number(value) || 0)
    : null;
  const box = Array.isArray(detection.selected_bbox_original) && detection.selected_bbox_original.length === 4
    ? detection.selected_bbox_original
    : Array.isArray(detection.selected_bbox) && detection.selected_bbox.length === 4
      ? detection.selected_bbox
      : null;
  if (!box) return null;
  const [x1, y1, x2, y2] = box.map((value) => Number(value));
  if (![x1, y1, x2, y2].every(Number.isFinite) || x2 <= x1 || y2 <= y1) return null;
  return {
    box: [x1, y1, x2, y2],
    imageSize,
  };
}

function cropSidesFromResult(result) {
  const sides = result?.detection?.cropped_sides;
  if (!Array.isArray(sides)) return [];
  const allowed = new Set(["top", "right", "bottom", "left"]);
  return [...new Set(sides.map((side) => String(side)).filter((side) => allowed.has(side)))];
}

function spikeBoxesFromResult(result, imageSize) {
  const rawBoxes =
    (Array.isArray(result?.season_spikes?.spike_boxes) ? result.season_spikes.spike_boxes : null) ||
    (Array.isArray(result?.vit_analysis?.season_spikes?.spike_boxes) ? result.vit_analysis.season_spikes.spike_boxes : null) ||
    (Array.isArray(result?.spike_boxes) ? result.spike_boxes : null) ||
    [];
  if (!rawBoxes.length) return [];

  const [imageW, imageH] = Array.isArray(imageSize) ? imageSize.map((value) => Number(value) || 0) : [0, 0];
  const maxSide = Math.max(imageW, imageH);
  const offsetLeft = imageW > 0 && imageH > 0 ? Math.floor((maxSide - imageW) / 2) : 0;
  const offsetTop = imageW > 0 && imageH > 0 ? Math.floor((maxSide - imageH) / 2) : 0;

  return rawBoxes.map((item, index) => {
    if (!item || !Array.isArray(item.bbox) || item.bbox.length !== 4) return null;
    const label = String(item.class || item.label || item.status || "Другое");
    const className = label === "Да" || label.toLowerCase() === "found"
      ? "found"
      : label === "Нет" || label.toLowerCase() === "lost"
        ? "lost"
        : "other";
    const [b1, b2, b3, b4] = item.bbox.map((value) => Number(value));
    if (![b1, b2, b3, b4].every(Number.isFinite)) return null;

    const isXYWH = b3 > 0 && b4 > 0 && (b3 <= b1 || b4 <= b2);
    let x1 = b1;
    let y1 = b2;
    let x2 = isXYWH ? b1 + b3 : b3;
    let y2 = isXYWH ? b2 + b4 : b4;

    const appearsSquarePadded = imageW > 0 && imageH > 0 && maxSide > 0
      && (x2 > imageW || y2 > imageH || x1 > imageW || y1 > imageH);
    if (appearsSquarePadded) {
      x1 -= offsetLeft;
      x2 -= offsetLeft;
      y1 -= offsetTop;
      y2 -= offsetTop;
    }

    if (imageW > 0) {
      x1 = Math.max(0, Math.min(imageW, x1));
      x2 = Math.max(0, Math.min(imageW, x2));
    }
    if (imageH > 0) {
      y1 = Math.max(0, Math.min(imageH, y1));
      y2 = Math.max(0, Math.min(imageH, y2));
    }
    if (x2 <= x1 || y2 <= y1) return null;

    return { id: `spike-${index}`, className, x1, y1, x2, y2 };
  }).filter(Boolean);
}

function AnnotatedImage({ src, alt, result, className = "", loading }) {
  const [naturalSize, setNaturalSize] = useState(null);
  const bbox = bboxFromResult(result);
  const cropSides = cropSidesFromResult(result);
  const imageSize = bbox?.imageSize?.[0] > 0 && bbox?.imageSize?.[1] > 0
    ? bbox.imageSize
    : naturalSize;
  const spikeBoxes = spikeBoxesFromResult(result, imageSize);

  if (!bbox && !cropSides.length && !spikeBoxes.length) {
    return (
      <img
        className={className}
        src={src}
        alt={alt}
        loading={loading}
        onLoad={(event) => setNaturalSize([event.currentTarget.naturalWidth, event.currentTarget.naturalHeight])}
      />
    );
  }

  const [w, h] = imageSize || [100, 100];
  const [x1, y1, x2, y2] = bbox?.box || [0, 0, 0, 0];
  const boxWidth = Math.max(1, x2 - x1);
  const boxHeight = Math.max(1, y2 - y1);
  const boxSize = Math.min(boxWidth, boxHeight);
  const chamfer = Math.max(8, Math.min(18, Math.round(boxSize * 0.035)));
  const cornerLength = Math.max(92, Math.min(220, Math.round(boxSize * 0.5)));
  const cornerGap = Math.max(7, Math.min(16, Math.round(boxSize * 0.026)));
  const top = y1;
  const bottom = y2;
  const left = x1;
  const right = x2;

  // Билинейный меш как в ArcFace: вертикальные линии красятся вертикальным
  // градиентом (верх→низ), горизонтальные — горизонтальным (лево→право),
  // цвета линий плавно интерполируются между 4 угловыми цветами.
  const GRID_CELLS = 10;
  const gridInsetX = Math.min(chamfer, boxWidth * 0.12);
  const gridInsetY = Math.min(chamfer, boxHeight * 0.12);
  const vLines = Array.from({ length: GRID_CELLS - 1 }, (_, index) => {
    const t = (index + 1) / GRID_CELLS;
    return {
      id: `bboxMeshV-${index}`,
      x: left + boxWidth * t,
      from: lerpColor(BBOX_CORNERS.tl, BBOX_CORNERS.tr, t),
      to: lerpColor(BBOX_CORNERS.bl, BBOX_CORNERS.br, t),
    };
  });
  const hLines = Array.from({ length: GRID_CELLS - 1 }, (_, index) => {
    const t = (index + 1) / GRID_CELLS;
    return {
      id: `bboxMeshH-${index}`,
      y: top + boxHeight * t,
      from: lerpColor(BBOX_CORNERS.tl, BBOX_CORNERS.bl, t),
      to: lerpColor(BBOX_CORNERS.tr, BBOX_CORNERS.br, t),
    };
  });
  const rgbOf = (c) => `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
  const cssTL = rgbOf(BBOX_CORNERS.tl);
  const cssTR = rgbOf(BBOX_CORNERS.tr);
  const cssBR = rgbOf(BBOX_CORNERS.br);
  const cssBL = rgbOf(BBOX_CORNERS.bl);
  return (
    <span className={`annotated-image ${className}`}>
      <img
        src={src}
        alt={alt}
        loading={loading}
        onLoad={(event) => setNaturalSize([event.currentTarget.naturalWidth, event.currentTarget.naturalHeight])}
      />
      <svg className="bbox-overlay" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="bboxEdgeH" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={cssTL} />
            <stop offset="100%" stopColor={cssTR} />
          </linearGradient>
          <linearGradient id="bboxEdgeV" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor={cssTL} />
            <stop offset="100%" stopColor={cssBL} />
          </linearGradient>
          <linearGradient id="bboxCornerGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={cssTL} />
            <stop offset="50%" stopColor={cssTR} />
            <stop offset="100%" stopColor={cssBR} />
          </linearGradient>
          <linearGradient id="bboxFillGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={cssTL} stopOpacity="0.10" />
            <stop offset="100%" stopColor={cssBR} stopOpacity="0.10" />
          </linearGradient>
          {vLines.map((line) => (
            <linearGradient key={line.id} id={line.id} x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor={line.from} />
              <stop offset="100%" stopColor={line.to} />
            </linearGradient>
          ))}
          {hLines.map((line) => (
            <linearGradient key={line.id} id={line.id} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor={line.from} />
              <stop offset="100%" stopColor={line.to} />
            </linearGradient>
          ))}
        </defs>
        {bbox && (
          <g className="bbox-modern">
            <polygon
              className="bbox-fill"
              points={`${left + chamfer},${top} ${right - chamfer},${top} ${right},${top + chamfer} ${right},${bottom - chamfer} ${right - chamfer},${bottom} ${left + chamfer},${bottom} ${left},${bottom - chamfer} ${left},${top + chamfer}`}
            />
            <g className="bbox-grid">
              {vLines.map((line) => (
                <line
                  key={line.id}
                  stroke={`url("#${line.id}")`}
                  x1={line.x}
                  y1={top + gridInsetY}
                  x2={line.x}
                  y2={bottom - gridInsetY}
                />
              ))}
              {hLines.map((line) => (
                <line
                  key={line.id}
                  stroke={`url("#${line.id}")`}
                  x1={left + gridInsetX}
                  y1={line.y}
                  x2={right - gridInsetX}
                  y2={line.y}
                />
              ))}
            </g>
            <line className="bbox-edge bbox-edge-h" x1={left + chamfer} y1={top} x2={right - chamfer} y2={top} />
            <line className="bbox-edge bbox-edge-h" x1={left + chamfer} y1={bottom} x2={right - chamfer} y2={bottom} />
            <line className="bbox-edge bbox-edge-v" x1={left} y1={top + chamfer} x2={left} y2={bottom - chamfer} />
            <line className="bbox-edge bbox-edge-v" x1={right} y1={top + chamfer} x2={right} y2={bottom - chamfer} />
            <line className="bbox-edge bbox-edge-v" x1={left} y1={top + chamfer} x2={left + chamfer} y2={top} />
            <line className="bbox-edge bbox-edge-v" x1={right - chamfer} y1={top} x2={right} y2={top + chamfer} />
            <line className="bbox-edge bbox-edge-v" x1={left} y1={bottom - chamfer} x2={left + chamfer} y2={bottom} />
            <line className="bbox-edge bbox-edge-v" x1={right - chamfer} y1={bottom} x2={right} y2={bottom - chamfer} />
            <g className="bbox-corners">
              <path d={`M ${left - cornerGap + chamfer} ${top - cornerGap} H ${left - cornerGap + cornerLength} M ${left - cornerGap} ${top - cornerGap + chamfer} V ${top - cornerGap + cornerLength} M ${left - cornerGap} ${top - cornerGap + chamfer} L ${left - cornerGap + chamfer} ${top - cornerGap}`} />
              <path d={`M ${right + cornerGap - chamfer} ${top - cornerGap} H ${right + cornerGap - cornerLength} M ${right + cornerGap} ${top - cornerGap + chamfer} V ${top - cornerGap + cornerLength} M ${right + cornerGap} ${top - cornerGap + chamfer} L ${right + cornerGap - chamfer} ${top - cornerGap}`} />
              <path d={`M ${left - cornerGap + chamfer} ${bottom + cornerGap} H ${left - cornerGap + cornerLength} M ${left - cornerGap} ${bottom + cornerGap - chamfer} V ${bottom + cornerGap - cornerLength} M ${left - cornerGap} ${bottom + cornerGap - chamfer} L ${left - cornerGap + chamfer} ${bottom + cornerGap}`} />
              <path d={`M ${right + cornerGap - chamfer} ${bottom + cornerGap} H ${right + cornerGap - cornerLength} M ${right + cornerGap} ${bottom + cornerGap - chamfer} V ${bottom + cornerGap - cornerLength} M ${right + cornerGap} ${bottom + cornerGap - chamfer} L ${right + cornerGap - chamfer} ${bottom + cornerGap}`} />
            </g>
          </g>
        )}
        {spikeBoxes.length > 0 && (
          <g className="spike-boxes">
            {spikeBoxes.map((box) => (
              <g className={`spike-box spike-box-${box.className}`} key={box.id}>
                <rect x={box.x1} y={box.y1} width={box.x2 - box.x1} height={box.y2 - box.y1} rx="2" />
                <circle cx={(box.x1 + box.x2) / 2} cy={(box.y1 + box.y2) / 2} r="3.5" />
              </g>
            ))}
          </g>
        )}
        {cropSides.includes("top") && <rect className="crop-side crop-top" x="0" y="0" width={w} height={Math.max(h * 0.055, 8)} />}
        {cropSides.includes("bottom") && <rect className="crop-side crop-bottom" x="0" y={h - Math.max(h * 0.055, 8)} width={w} height={Math.max(h * 0.055, 8)} />}
        {cropSides.includes("left") && <rect className="crop-side crop-left" x="0" y="0" width={Math.max(w * 0.055, 8)} height={h} />}
        {cropSides.includes("right") && <rect className="crop-side crop-right" x={w - Math.max(w * 0.055, 8)} y="0" width={Math.max(w * 0.055, 8)} height={h} />}
      </svg>
      {cropSides.length > 0 && <span className="crop-badge">Обрезка</span>}
    </span>
  );
}

function UploadZone({ onFile }) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [preview, setPreview] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  const setFile = (file) => {
    if (!file) return;
    setSelectedFile(file);
    setPreview((current) => {
      if (current) URL.revokeObjectURL(current);
      return URL.createObjectURL(file);
    });
  };

  const clearSelection = () => {
    setSelectedFile(null);
    setPreview((current) => {
      if (current) URL.revokeObjectURL(current);
      return "";
    });
  };

  return (
    <div className="upload-wrapper">
      <label className={`upload-zone${selectedFile ? " has-file" : ""}${dragOver ? " drag-over" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)} onDrop={(event) => { event.preventDefault(); setDragOver(false); setFile(event.dataTransfer.files?.[0]); }}>
        <input className="upload-input" type="file" accept="image/*" capture="environment" onChange={(event) => setFile(event.target.files?.[0])} />
        {preview ? (
          <div className="upload-preview-wrap">
            <img className="upload-preview" src={preview} alt="preview" />
            <button
              className="upload-preview-clear"
              type="button"
              aria-label="Удалить выбранное фото"
              onClick={(event) => { event.preventDefault(); event.stopPropagation(); clearSelection(); }}
            >
              ×
            </button>
          </div>
        ) : (
          <span className="upload-inner">
            <span className="upload-icon">📷</span>
            <span className="upload-text">Перетащите фото сюда, нажмите для выбора или снимите камерой</span>
            <span className="upload-hint">JPG, PNG, HEIC и другие форматы изображений</span>
          </span>
        )}
      </label>
      {uploading && (
        <div className="recognition-card" role="status" aria-live="polite">
          <div className="recognition-orbit" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div>
            <span>Обработка фото</span>
            <strong>Загружаем кадр и ждем результат распознавания</strong>
          </div>
        </div>
      )}
      <button className="btn-primary btn-full" type="button" disabled={!selectedFile || uploading} onClick={async () => {
        if (!selectedFile) return;
        setUploading(true);
        try {
          await onFile(selectedFile);
          clearSelection();
        } finally {
          setUploading(false);
        }
      }}>{uploading ? "Загружаем..." : "Загрузить →"}</button>
    </div>
  );
}

function ObjectCountBadge({ result }) {
  const det = result?.detection;
  if (!det || typeof det !== "object") return null;
  const count = det.count ?? "—";
  return (
    <div className="object-count-badge">
      <span className="object-count-label">Обнаружено объектов</span>
      <span className="object-count-value">{count}</span>
    </div>
  );
}

function TireProgress({ tireNumber, photoNumber, context, result }) {
  const p = context.flowState?.progress || {};
  const total = p.tire_count || "?";
  const pn = Number(photoNumber);
  const maxP = (p.max_photo != null && p.max_photo > 0) ? Number(p.max_photo) : pn;
  const allowed = context.flowState?.allowed_actions || [];
  const canBack = allowed.includes("navigate_back") || allowed.includes("upload_image");
  const canFwd = allowed.includes("navigate_forward");
  const dots = Math.max(5, maxP);

  return (
    <div className="tire-progress-row">
      <div className="tire-progress">
        {Array.from({ length: dots }, (_, index) => index + 1).map((dot) => {
          const done = dot < pn;
          const active = dot === pn;
          const uploaded = dot <= maxP && dot !== pn;
          const canClickBack = done && canBack && dot < pn;
          const canClickFwd = canFwd && dot > pn && dot <= (maxP + 1);
          return (
            <button
              className={`photo-dot${active ? " active" : uploaded || done ? " done" : ""}${canClickBack || canClickFwd ? " photo-dot-nav" : ""}${canClickFwd ? " photo-dot-fwd" : ""}`}
              type="button"
              key={dot}
              title={canClickBack || canClickFwd ? `Перейти к фото ${dot}` : undefined}
              onClick={canClickBack ? () => context.sendAction("navigate_back", { photo_number: dot }) : canClickFwd ? () => context.sendAction("navigate_forward", { photo_number: dot }) : undefined}
            >
              {dot}
            </button>
          );
        })}
      </div>
      <ObjectCountBadge result={result} />
    </div>
  );
}

function ResultTable({ result, photoNumber }) {
  if (!result || typeof result !== "object") return null;
  const pn = Number(photoNumber);
  let rows = [];
  if (pn === 1 || pn === 2) {
    const vit = result.vit_analysis && typeof result.vit_analysis === "object" ? result.vit_analysis : {};
    const seasonAnalysis = vit.season_analysis && typeof vit.season_analysis === "object" ? vit.season_analysis : {};
    const seasonSpikes = result.season_spikes && typeof result.season_spikes === "object" ? result.season_spikes : seasonAnalysis;
    const det = result.detection;

    if (pn === 2) {
      const season = result.season || seasonSpikes.season || result.season_class || "Неопределено";
      rows.push(["Сезонность", season]);
      const spikes = seasonSpikes.spikes || result.spikes || result.spikes_class || null;
      if (spikes && typeof spikes === "object") {
        const found = Number(spikes["Да"] ?? 0);
        const lost = Number(spikes["Нет"] ?? 0);
        const other = Number(spikes["Другое"] ?? 0);
        rows.push(["Шипы", `найдено: ${found}\nпотеряно: ${lost}\nдругое: ${other}`]);
      } else if (spikes) {
        rows.push(["Шипы", String(spikes)]);
      }
    }
  } else if (pn === 4) {
    rows = [
      ["Номер", result.number || "—"],
      ["Найден", result.found ? "Да" : "Нет"],
      ["Ошибка", result.error || "—"],
    ];
  } else {
    rows = Object.entries(result).filter(([, value]) => typeof value !== "object").map(([key, value]) => [key, String(value ?? "—")]);
  }
  rows = rows.filter(([, value]) => value !== undefined && value !== "");
  if (!rows.length) return null;
  return (
    <table className="result-table">
      <tbody>
        {rows.map(([key, value]) => (
          <tr key={key}>
            <td>{key}</td>
            <td>{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function UploadStepResult({ result, photoNumber }) {
  if (!result || typeof result !== "object") return null;
  if (Number(photoNumber) === 4) {
    return (
      <div className="step-body">
        <p className="step-hint">Результат предыдущего распознавания:</p>
        <div className="number-card">
          {result.found && result.number ? (
            <>
              <div className="num-label">Распознанный номер</div>
              <div className="num-value">{result.number}</div>
            </>
          ) : <div className="num-not-found">Номер не распознан{result.error ? ` — ${result.error}` : ""}</div>}
        </div>
      </div>
    );
  }
  return (
    <div className="step-body">
      <p className="step-hint">Результат предыдущего распознавания:</p>
      <ResultTable result={result} photoNumber={photoNumber} />
    </div>
  );
}

export default App;
