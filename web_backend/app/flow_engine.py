from __future__ import annotations

import sys
# Force UTF-8 for S3 key handling on Windows (cp1251 console causes mojibake in filenames).
if sys.platform == "win32":
    for attr in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, attr)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

import asyncio
import base64
import copy
import glob
import hashlib
import io
import json
import logging
import os
import re
import shutil
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import httpx
import requests
from PIL import Image, ImageOps

from .settings import settings

logger = logging.getLogger(__name__)


STATE_FILE = "flow_state.json"
UPLOADS_DIR = "uploads"
ATWORK_INDEX_FILE = ".index_bitrix.json"
ATWORK_INDEX_LEGACY_FILE = ".index_telegram.json"
ATWORK_INDEX_VERSION = 1
ATWORK_S3_MANIFEST_FILE = ".s3_manifest.json"
ATWORK_S3_MANIFEST_VERSION = 1
ATWORK_INTERNAL_FILES = {ATWORK_INDEX_FILE, ATWORK_INDEX_LEGACY_FILE, ATWORK_S3_MANIFEST_FILE}

STEP_SELECT_BASE = "select_base"
STEP_SELECT_USER = "select_user"
STEP_SELECT_SOURCE = "select_source"
STEP_SELECT_TRANSPORT_METHOD = "select_transport_method"
STEP_UPLOAD_CAR_PHOTO = "upload_car_photo"
STEP_ENTER_MANUAL_CAR_NUMBER = "enter_manual_car_number"
STEP_CONFIRM_CAR = "confirm_car"
STEP_SET_TIRE_COUNT = "set_tire_count"
STEP_UPLOAD_TIRE_PHOTO = "upload_tire_photo"
STEP_CONFIRM_PHOTO = "confirm_photo"
STEP_CONFIRM_TIRE_NUMBER = "confirm_tire_number"
STEP_POST_REQUIRED = "post_required_photos"
STEP_COMMENT = "comment"
STEP_CONFIRM_SEND = "confirm_send"
STEP_FINISHED = "finished"

ACCESS_DENIED_CODE = "access_denied"
ACCESS_DENIED_MESSAGE = "В доступе отказано, проверьте введенные данные"
REGISTRATION_HELP_URL = "https://portal.rt24.ru/company/personal/user/4212/"
REGISTRATION_HELP_MESSAGE = "Пользователь с указанным ID не найден. Проверьте корректность введенных данных. Если ID указан верно, обратитесь к ответственному сотруднику для помощи в регистрации."


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sanitize_file_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "upload.jpg")
    return safe[:180]


def _to_abs(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (Path(settings.project_root).resolve() / path).resolve()


def _normalize_exchange_ai_url(base_url: str) -> str:
    base = str(base_url or "").strip()
    if not base:
        return ""
    if "://" not in base:
        base = f"http://{base}"
    base = base.rstrip("/")
    if re.search(r"/hs/Exchange_AI/[^/]+$", base, flags=re.IGNORECASE):
        return base
    return f"{base}/TireDefect"


def _safe_load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _safe_dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _normalize_number(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip().upper())


def _map_action_error(step: str, action: str) -> dict[str, Any]:
    return {
        "code": "invalid_action",
        "message": f"Action '{action}' is not allowed on step '{step}'",
    }


async def _run_in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(fn, *args, **kwargs)


@dataclass
class _FlowPaths:
    project_root: Path
    users_root: Path
    atwork_root: Path
    car_number_file: Path


class FlowEngine:
    def __init__(self) -> None:
        project_root = Path(settings.project_root).resolve()
        self.paths = _FlowPaths(
            project_root=project_root,
            users_root=_to_abs(settings.users_dir),
            atwork_root=_to_abs(settings.atwork_dir),
            car_number_file=_to_abs(settings.car_number_file_path),
        )
        self.paths.users_root.mkdir(parents=True, exist_ok=True)
        self.paths.atwork_root.mkdir(parents=True, exist_ok=True)
        self._car_db: dict[str, dict[str, str]] = {}
        self._atwork_index_path = self.paths.atwork_root / ATWORK_INDEX_FILE
        self._atwork_index_legacy_path = self.paths.atwork_root / ATWORK_INDEX_LEGACY_FILE
        self._s3_manifest_path = self.paths.atwork_root / ATWORK_S3_MANIFEST_FILE
        self._load_car_database()

    def _load_car_database(self) -> None:
        self._car_db = {}
        if not self.paths.car_number_file.exists():
            logger.warning("car_number.json not found: %s", self.paths.car_number_file)
            return
        try:
            payload = _safe_load_json(self.paths.car_number_file)
            if isinstance(payload, list):
                for row in payload:
                    if not isinstance(row, dict):
                        continue
                    plate = _normalize_number(str(row.get("ГосНомер", "")))
                    if not plate:
                        continue
                    self._car_db[plate] = {
                        "brand": str(row.get("МаркаМодель", "") or ""),
                        "org": str(row.get("Организация", "") or ""),
                    }
        except Exception:
            logger.exception("Failed to load car number database")

    def _session_dir(self, session_id: str) -> Path:
        # Primary legacy location (created at start before manual user id is known).
        legacy = self.paths.users_root / f"WEB_{session_id}"
        if legacy.exists():
            return legacy

        # Direct name fallback (if someone intentionally used session_id as folder name).
        direct = self.paths.users_root / session_id
        if direct.exists():
            return direct

        # Resolve moved session directories (e.g. D_HHMMSS_DDMMYYYY_USERID).
        pattern = str(self.paths.users_root / "*" / STATE_FILE)
        for state_file in glob.glob(pattern):
            try:
                payload = _safe_load_json(Path(state_file))
            except Exception:
                continue
            if isinstance(payload, dict) and str(payload.get("session_id")) == str(session_id):
                return Path(state_file).parent

        # Default path for new sessions.
        return legacy

    def _state_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / STATE_FILE

    def _uploads_dir(self, session_id: str) -> Path:
        path = self._session_dir(session_id) / UPLOADS_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _sanitize_dir_label(self, value: str) -> str:
        # Keep readable unicode names, strip path separators/control chars.
        safe = re.sub(r'[\\/:*?"<>|\x00-\x1F]+', "_", (value or "").strip())
        safe = re.sub(r"\s+", "_", safe).strip("._ ")
        return safe[:96] or "unknown"

    def _target_session_dir_name(self, state: dict[str, Any], user_label: str) -> str:
        created_at_raw = str(state.get("created_at") or "")
        try:
            dt = datetime.fromisoformat(created_at_raw)
        except Exception:
            dt = datetime.now()
        time_part = dt.strftime("%H%M%S")
        date_part = dt.strftime("%d%m%Y")
        label_part = self._sanitize_dir_label(user_label)
        return f"D_{time_part}_{date_part}_{label_part}"

    def _rename_session_dir_for_user(self, state: dict[str, Any], user_label: str) -> None:
        session_id = str(state.get("session_id") or "")
        if not session_id:
            return
        src_dir = self._session_dir(session_id)
        if not src_dir.exists():
            return
        target_name = self._target_session_dir_name(state, user_label)
        dst_dir = self.paths.users_root / target_name
        if src_dir.resolve() == dst_dir.resolve():
            return
        if dst_dir.exists():
            suffix = 1
            while True:
                candidate = self.paths.users_root / f"{target_name}_{suffix}"
                if not candidate.exists():
                    dst_dir = candidate
                    break
                suffix += 1
        shutil.move(str(src_dir), str(dst_dir))
        state["session_dir"] = str(dst_dir)

    def _session_dir_label_from_profile(self, profile: dict[str, Any] | None, fallback: str = "") -> str:
        if not isinstance(profile, dict):
            return str(fallback or "").strip()
        name = str(profile.get("Name", "") or "").strip()
        if name:
            return name
        bitrix_id = str(profile.get("BitrixID", "") or profile.get("TelegramID", "") or "").strip()
        if bitrix_id:
            return bitrix_id
        uid = str(profile.get("UID", "") or "").strip()
        if uid:
            return uid
        return str(fallback or "").strip()

    def _serialize_error(self, code: str, message: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": code, "message": message}
        if extra:
            payload.update(extra)
        return payload

    def _build_progress(self, state: dict[str, Any]) -> dict[str, Any]:
        tire_count = int(state.get("tire_count") or 0)
        current_tire = int(state.get("current_tire") or 1)
        current_photo = int(state.get("current_photo") or 0)
        max_photo = self._max_uploaded_photo(state, current_tire)
        return {
            "tire_count": tire_count,
            "current_tire": current_tire,
            "current_photo": current_photo,
            "max_photo": max_photo,  # highest photo uploaded (may be > current_photo when navigating back)
            "required_photos": 5,
            "is_last_tire": tire_count > 0 and current_tire >= tire_count,
        }

    def _format_state(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": state["session_id"],
            "step": state["step"],
            "allowed_actions": list(state.get("allowed_actions", [])),
            "progress": self._build_progress(state),
            "ui_payload": state.get("ui_payload", {}),
            "errors": list(state.get("errors", [])),
            "updated_at": state.get("updated_at"),
            "context": {
                "selected_base": state.get("selected_base"),
                "selected_user": (state.get("profile") or {}).get("Name") or state.get("selected_user"),
                "source": state.get("source"),
                "transport_method": state.get("transport_method"),
                "car_number": state.get("car_number"),
                "car_brand": state.get("car_brand"),
                "display_name": state.get("display_name"),
            },
        }

    def _save_state(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _now_iso()
        _safe_dump_json(self._state_path(state["session_id"]), state)

    def _normalize_legacy_steps(self, state: dict[str, Any]) -> bool:
        """Migrate obsolete flow steps in-memory. Returns True when state changed."""
        step = str(state.get("step") or "")
        if step != STEP_SELECT_TRANSPORT_METHOD:
            return False
        state["transport_method"] = "automatic"
        self._set_step(
            state,
            STEP_UPLOAD_CAR_PHOTO,
            allowed_actions=["upload_image", "submit_manual_car_number", "navigate_back"],
            ui_payload={
                "instruction": "Загрузите фото автомобиля для автоматического распознавания номера или введите номер вручную ниже",
                "demo_image": self._car_demo_image_filename(),
            },
        )
        return True

    def _load_state(self, session_id: str) -> dict[str, Any]:
        path = self._state_path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")
        data = _safe_load_json(path)
        if not isinstance(data, dict):
            raise ValueError("Invalid session payload")
        if data.get("bitrix_id") in (None, "") and data.get("telegram_id") not in (None, ""):
            data["bitrix_id"] = data.get("telegram_id")
        profile = data.get("profile")
        if isinstance(profile, dict):
            if profile.get("BitrixID") in (None, "") and profile.get("TelegramID") not in (None, ""):
                profile["BitrixID"] = profile.get("TelegramID")
            if profile.get("TelegramID") in (None, "") and profile.get("BitrixID") not in (None, ""):
                profile["TelegramID"] = profile.get("BitrixID")
        return data

    def _set_step(
        self,
        state: dict[str, Any],
        step: str,
        allowed_actions: list[str],
        ui_payload: dict[str, Any] | None = None,
    ) -> None:
        state["step"] = step
        state["allowed_actions"] = allowed_actions
        state["ui_payload"] = ui_payload or {}

    def _set_error(self, state: dict[str, Any], code: str, message: str, extra: dict[str, Any] | None = None) -> None:
        state["errors"] = [self._serialize_error(code, message, extra)]

    def _clear_errors(self, state: dict[str, Any]) -> None:
        state["errors"] = []

    def _sync_s3_atwork_blocking(self) -> None:
        """Full S3 sync logic — runs synchronously inside a thread."""
        try:
            import boto3
            import botocore
        except Exception:
            logger.warning("boto3 is not installed, S3 sync skipped")
            return

        prefix = (settings.s3_prefix or "").strip()
        if prefix and not prefix.endswith("/"):
            prefix += "/"

        session = boto3.session.Session()
        s3 = session.client(
            service_name="s3",
            endpoint_url=settings.yc_endpoint_url,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            config=botocore.client.Config(signature_version="s3v4"),
            region_name=settings.yc_region,
        )

        def _calc_md5(path: Path) -> str:
            h = hashlib.md5()
            try:
                with path.open("rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        h.update(chunk)
                return h.hexdigest()
            except Exception:
                return ""

        s3_filenames: set[str] = set()
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.s3_bucket_name, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = str(obj.get("Key") or "")
                if not key.endswith(".json"):
                    continue
                etag = obj.get("ETag", "").strip('"')
                local_name = Path(key).name
                local_path = self.paths.atwork_root / local_name
                s3_filenames.add(local_name)
                # Skip if local file is already up-to-date (MD5 == S3 ETag)
                if local_path.exists() and _calc_md5(local_path) == etag:
                    continue
                try:
                    s3.download_file(settings.s3_bucket_name, key, str(local_path))
                    logger.debug("S3 synced: %s", local_name)
                except Exception:
                    logger.exception("Failed to sync S3 object: %s", key)

        # Remove local AtWork files that no longer exist in S3
        for local_file in self.paths.atwork_root.glob("*.json"):
            if local_file.name not in s3_filenames:
                try:
                    local_file.unlink()
                    logger.debug("S3 cleanup: removed obsolete file %s", local_file.name)
                except Exception:
                    logger.exception("Failed to remove obsolete AtWork file: %s", local_file.name)

    async def _sync_s3_atwork(self) -> None:
        """Async wrapper: runs the full blocking S3 sync in a thread to avoid blocking the event loop."""
        if not (settings.aws_access_key_id or "").strip() or not (settings.aws_secret_access_key or "").strip():
            return
        try:
            await asyncio.wait_for(
                _run_in_thread(self._sync_s3_atwork_blocking),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            logger.warning("S3 sync timed out after 60s, continuing without sync")
        except Exception:
            logger.exception("S3 sync failed, continuing without sync")

    @staticmethod
    def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            return [payload]
        return []

    def _empty_atwork_index(self) -> dict[str, Any]:
        return {
            "version": ATWORK_INDEX_VERSION,
            "built_at": _now_iso(),
            "files": {},
            "by_file_entries": {},
            "by_bitrix": {},
            "by_bitrix_uid_base": {},
        }

    def _load_atwork_index(self) -> dict[str, Any]:
        index_path = self._atwork_index_path
        if not index_path.exists() and self._atwork_index_legacy_path.exists():
            index_path = self._atwork_index_legacy_path
        if not index_path.exists():
            return self._empty_atwork_index()
        try:
            data = _safe_load_json(index_path)
            if not isinstance(data, dict):
                return self._empty_atwork_index()
            if int(data.get("version") or 0) != ATWORK_INDEX_VERSION:
                return self._empty_atwork_index()
            # Migrate legacy index keys.
            if not isinstance(data.get("by_bitrix"), dict) and isinstance(data.get("by_telegram"), dict):
                data["by_bitrix"] = data.get("by_telegram", {})
            if not isinstance(data.get("by_bitrix_uid_base"), dict) and isinstance(data.get("by_telegram_uid_base"), dict):
                data["by_bitrix_uid_base"] = data.get("by_telegram_uid_base", {})
            for key in ("files", "by_file_entries", "by_bitrix", "by_bitrix_uid_base"):
                if not isinstance(data.get(key), dict):
                    data[key] = {}
            return data
        except Exception:
            logger.exception("Failed to load AtWork index, rebuilding")
            return self._empty_atwork_index()

    def _persist_atwork_index(self, index_data: dict[str, Any]) -> None:
        index_data["version"] = ATWORK_INDEX_VERSION
        index_data["built_at"] = _now_iso()
        _safe_dump_json(self._atwork_index_path, index_data)

    @staticmethod
    def _index_file_meta(path: Path) -> dict[str, int]:
        stat = path.stat()
        return {"size": int(stat.st_size), "mtime": int(stat.st_mtime)}

    @staticmethod
    def _index_entry_from_row(row: dict[str, Any], file_name: str, row_idx: int) -> dict[str, Any]:
        return {
            "bitrix_id": str(row.get("BitrixID", "") or row.get("TelegramID", "") or "").strip(),
            "uid": str(row.get("UID", "") or "").strip(),
            "base_name": str(row.get("BaseName", "") or "").strip(),
            "name": str(row.get("Name", "") or "").strip(),
            "file": file_name,
            "row_index": int(row_idx),
        }

    def _index_remove_file_entries(self, index_data: dict[str, Any], file_name: str) -> None:
        old_entries = index_data.get("by_file_entries", {}).pop(file_name, [])
        by_bitrix = index_data.get("by_bitrix", {})
        by_bub = index_data.get("by_bitrix_uid_base", {})

        if isinstance(old_entries, list):
            for raw in old_entries:
                if not isinstance(raw, dict):
                    continue
                bid = str(raw.get("bitrix_id", "") or raw.get("telegram_id", "") or "").strip()
                uid = str(raw.get("uid", "") or "").strip()
                base_name = str(raw.get("base_name", "") or "").strip()
                row_index = int(raw.get("row_index", 0) or 0)

                if bid:
                    arr = by_bitrix.get(bid, [])
                    if isinstance(arr, list):
                        arr = [
                            x for x in arr
                            if not (
                                isinstance(x, dict)
                                and str(x.get("file", "") or "") == file_name
                                and int(x.get("row_index", -1) or -1) == row_index
                            )
                        ]
                        if arr:
                            by_bitrix[bid] = arr
                        else:
                            by_bitrix.pop(bid, None)

                if bid and uid and base_name:
                    key = f"{bid}|{uid}|{base_name.casefold()}"
                    hit = by_bub.get(key)
                    if isinstance(hit, dict) and str(hit.get("file", "") or "") == file_name:
                        by_bub.pop(key, None)

    def _index_add_file_entries(self, index_data: dict[str, Any], file_name: str, rows: list[dict[str, Any]]) -> None:
        entries_for_file: list[dict[str, Any]] = []
        by_bitrix = index_data.get("by_bitrix", {})
        by_bub = index_data.get("by_bitrix_uid_base", {})

        for i, row in enumerate(rows):
            entry = self._index_entry_from_row(row, file_name, i)
            bid = entry["bitrix_id"]
            if not bid:
                continue

            entries_for_file.append(entry)
            by_bitrix.setdefault(bid, []).append(
                {
                    "uid": entry["uid"],
                    "base_name": entry["base_name"],
                    "name": entry["name"],
                    "file": entry["file"],
                    "row_index": entry["row_index"],
                }
            )

            if entry["uid"] and entry["base_name"]:
                key = f"{bid}|{entry['uid']}|{entry['base_name'].casefold()}"
                by_bub[key] = {"file": file_name, "row_index": entry["row_index"]}

        index_data.get("by_file_entries", {})[file_name] = entries_for_file

    def _refresh_atwork_index(self) -> dict[str, Any]:
        index_data = self._load_atwork_index()

        current_files: dict[str, dict[str, int]] = {}
        for file in self.paths.atwork_root.glob("*.json"):
            if file.name in ATWORK_INTERNAL_FILES:
                continue
            current_files[file.name] = self._index_file_meta(file)

        indexed_files = {
            k: v for k, v in index_data.get("files", {}).items()
            if isinstance(k, str) and k not in ATWORK_INTERNAL_FILES and isinstance(v, dict)
        }

        # A previous failed/partial build can leave file metadata present while
        # lookup maps are empty. In that state no file looks "changed", so force
        # a clean rebuild instead of returning an unusable index.
        if current_files and indexed_files and (
            not index_data.get("by_file_entries") or not index_data.get("by_bitrix")
        ):
            index_data = self._empty_atwork_index()
            indexed_files = {}

        deleted = set(indexed_files.keys()) - set(current_files.keys())
        changed_or_new = [
            file_name
            for file_name, meta in current_files.items()
            if indexed_files.get(file_name) != meta
        ]

        dirty = False
        for file_name in deleted:
            self._index_remove_file_entries(index_data, file_name)
            index_data.get("files", {}).pop(file_name, None)
            dirty = True

        for file_name in changed_or_new:
            file_path = self.paths.atwork_root / file_name
            self._index_remove_file_entries(index_data, file_name)
            try:
                payload = _safe_load_json(file_path)
                rows = self._rows_from_payload(payload)
            except Exception:
                logger.exception("Failed to parse AtWork file for index: %s", file_path)
                rows = []
            self._index_add_file_entries(index_data, file_name, rows)
            index_data.get("files", {})[file_name] = current_files[file_name]
            dirty = True

        for bid, arr in list(index_data.get("by_bitrix", {}).items()):
            if not isinstance(arr, list):
                index_data["by_bitrix"][bid] = []
                continue
            arr.sort(key=lambda x: (str(x.get("base_name", "") or "").casefold(), str(x.get("uid", "") or "")))

        if dirty or not self._atwork_index_path.exists():
            self._persist_atwork_index(index_data)

        return index_data

    def _empty_s3_manifest(self) -> dict[str, Any]:
        return {
            "version": ATWORK_S3_MANIFEST_VERSION,
            "updated_at": _now_iso(),
            "files": {},
            "user_files": {},
        }

    def _load_s3_manifest(self) -> dict[str, Any]:
        if not self._s3_manifest_path.exists():
            return self._empty_s3_manifest()
        try:
            data = _safe_load_json(self._s3_manifest_path)
            if not isinstance(data, dict):
                return self._empty_s3_manifest()
            if int(data.get("version") or 0) != ATWORK_S3_MANIFEST_VERSION:
                return self._empty_s3_manifest()
            if not isinstance(data.get("files"), dict):
                data["files"] = {}
            if not isinstance(data.get("user_files"), dict):
                data["user_files"] = {}
            return data
        except Exception:
            logger.exception("Failed to load S3 manifest, rebuilding")
            return self._empty_s3_manifest()

    def _persist_s3_manifest(self, manifest: dict[str, Any]) -> None:
        manifest["version"] = ATWORK_S3_MANIFEST_VERSION
        manifest["updated_at"] = _now_iso()
        _safe_dump_json(self._s3_manifest_path, manifest)

    @staticmethod
    def _s3_obj_signature(obj: dict[str, Any]) -> dict[str, Any]:
        last_modified = obj.get("LastModified")
        if hasattr(last_modified, "isoformat"):
            lm = last_modified.isoformat()
        else:
            lm = str(last_modified or "")
        return {
            "etag": str(obj.get("ETag", "")).strip('"'),
            "last_modified": lm,
            "size": int(obj.get("Size") or 0),
        }

    @staticmethod
    def _extract_bitrix_ids(rows: list[dict[str, Any]]) -> list[str]:
        ids: set[str] = set()
        for row in rows:
            bid = str(row.get("BitrixID", "") or row.get("TelegramID", "") or "").strip()
            if bid:
                ids.add(bid)
        return sorted(ids)

    @staticmethod
    def _rebuild_manifest_user_files(files_map: dict[str, Any]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for key, meta in files_map.items():
            if not isinstance(key, str) or not isinstance(meta, dict):
                continue
            ids = meta.get("bitrix_ids", meta.get("telegram_ids", []))
            if not isinstance(ids, list):
                continue
            for raw_id in ids:
                bid = str(raw_id or "").strip()
                if not bid:
                    continue
                out.setdefault(bid, []).append(key)
        for bid, keys in out.items():
            keys.sort()
        return out

    def _iter_atwork_rows(self) -> list[tuple[dict[str, Any], Path]]:
        rows: list[tuple[dict[str, Any], Path]] = []
        for file in self.paths.atwork_root.glob("*.json"):
            if file.name in ATWORK_INTERNAL_FILES:
                continue
            try:
                payload = _safe_load_json(file)
            except Exception:
                continue
            candidates = self._rows_from_payload(payload)
            for row in candidates:
                rows.append((row, file))
        return rows

    def _set_select_base_step(self, state: dict[str, Any], bitrix_id: str, code: str | None = None, message: str | None = None) -> None:
        bases = self._find_user_bases_by_bitrix_id(bitrix_id)
        user_name = str(bases[0].get("name", "") or "").strip() if bases else ""
        if code and message:
            self._set_error(state, code, message, {"bitrix_id": bitrix_id})
        self._set_step(
            state,
            STEP_SELECT_BASE,
            allowed_actions=["select_base"],
            ui_payload={
                "bitrix_id": bitrix_id,
                "user_name": user_name,
                "bases": [{"uid": b["uid"], "base_name": b["base_name"]} for b in bases],
            },
        )

    def _set_select_user_step(
        self,
        state: dict[str, Any],
        code: str | None = None,
        message: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if code and message:
            self._set_error(state, code, message, extra)
        self._set_step(
            state,
            STEP_SELECT_USER,
            allowed_actions=["select_user"],
            ui_payload={
                "title": "Авторизация",
                "instruction": "Введите ID",
            },
        )

    def _find_user_bases_by_bitrix_id(self, bitrix_id: str) -> list[dict[str, Any]]:
        bid = str(bitrix_id or "").strip()
        if not bid:
            return []
        seen: set[tuple[str, str]] = set()
        bases: list[dict[str, Any]] = []
        index_data = self._refresh_atwork_index()
        entries = index_data.get("by_bitrix", {}).get(bid, [])
        if not isinstance(entries, list):
            entries = []
        for raw in entries:
            if not isinstance(raw, dict):
                continue
            uid = str(raw.get("uid", "") or "").strip()
            base_name = str(raw.get("base_name", "") or "").strip()
            if not uid or not base_name:
                continue
            key = (uid, base_name.casefold())
            if key in seen:
                continue
            seen.add(key)
            bases.append({
                "uid": uid,
                "base_name": base_name,
                "name": str(raw.get("name", "") or "").strip(),
            })
        bases.sort(key=lambda x: (x["base_name"].casefold(), x["uid"]))
        return bases

    def _clear_auth_state(self, state: dict[str, Any]) -> None:
        state["bitrix_id"] = None
        state["telegram_id"] = None
        state["auth_verified"] = False
        state["verified_surname"] = None
        state["profile"] = None
        state["selected_base"] = None
        state["selected_user"] = None

    def _mark_auth_verified(self, state: dict[str, Any], telegram_id: str) -> None:
        tid = str(telegram_id or "").strip()
        state["bitrix_id"] = tid
        state["telegram_id"] = tid
        state["auth_verified"] = True
        state["verified_surname"] = None

    async def _authenticate_web_user(self, state: dict[str, Any], telegram_id: str) -> bool:
        tid = str(telegram_id or "").strip()
        if not tid:
            self._clear_auth_state(state)
            self._set_select_user_step(state, ACCESS_DENIED_CODE, ACCESS_DENIED_MESSAGE)
            return False

        sync_result = await self._sync_user_from_s3(tid)
        bases = self._find_user_bases_by_bitrix_id(tid)
        if not bases:
            self._clear_auth_state(state)
            if sync_result.get("error"):
                logger.warning("Access denied for TelegramID=%s after S3 sync error: %s", tid, sync_result.get("error"))
            self._set_select_user_step(
                state,
                ACCESS_DENIED_CODE,
                REGISTRATION_HELP_MESSAGE,
                {
                    "registration_help_url": REGISTRATION_HELP_URL,
                    "registration_help_label": "Помощь в регистрации",
                },
            )
            return False

        self._mark_auth_verified(state, tid)
        return True

    def _choose_profile_for_uid(self, uid: str, selected_base: str) -> dict[str, Any] | None:
        """Compatibility fallback: returns first matching profile row by UID + BaseName."""
        cf = selected_base.casefold()
        for row, _file in self._iter_atwork_rows():
            if (str(row.get("BaseName", "")).strip().casefold() == cf
                    and str(row.get("UID", "") or "").strip() == uid):
                return copy.deepcopy(row)
        return None

    def _choose_profile_by_bitrix_uid_base(
        self, bitrix_id: str, uid: str, selected_base: str
    ) -> tuple[dict[str, Any], Path] | None:
        bid = str(bitrix_id or "").strip()
        uid = str(uid or "").strip()
        cf = str(selected_base or "").strip().casefold()
        if not bid or not uid or not cf:
            return None

        index_data = self._refresh_atwork_index()
        key = f"{bid}|{uid}|{cf}"
        hit = index_data.get("by_bitrix_uid_base", {}).get(key)
        if isinstance(hit, dict):
            file_name = str(hit.get("file", "") or "").strip()
            row_index = int(hit.get("row_index", -1) or -1)
            if file_name:
                file = self.paths.atwork_root / file_name
                if file.exists():
                    try:
                        payload = _safe_load_json(file)
                        rows = self._rows_from_payload(payload)
                        if 0 <= row_index < len(rows):
                            row = rows[row_index]
                            return copy.deepcopy(row), file
                    except Exception:
                        logger.exception("Failed to read indexed profile file: %s", file)

        # Fallback scan for resilience if index was stale/corrupted.
        for row, file in self._iter_atwork_rows():
            row_bid = str(row.get("BitrixID", "") or row.get("TelegramID", "") or "").strip()
            if row_bid != bid:
                continue
            if str(row.get("UID", "") or "").strip() != uid:
                continue
            if str(row.get("BaseName", "") or "").strip().casefold() != cf:
                continue
            return copy.deepcopy(row), file
        return None

    def _sync_user_from_s3_blocking(self, bitrix_id: str) -> dict[str, Any]:
        downloaded: list[str] = []
        bid = str(bitrix_id or "").strip()
        if not bid:
            return {"downloaded": downloaded, "error": "empty_bitrix_id"}
        if not (settings.aws_access_key_id or "").strip() or not (settings.aws_secret_access_key or "").strip():
            logger.warning("S3 credentials are empty, skip user sync for BitrixID=%s", bid)
            return {"downloaded": downloaded, "error": "empty_s3_credentials"}

        try:
            import boto3
            import botocore
        except Exception:
            logger.warning("boto3 is not installed, S3 user sync skipped")
            return {"downloaded": downloaded, "error": "boto3_not_installed"}

        prefix = (settings.s3_prefix or "").strip()
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        list_prefix = prefix

        session = boto3.session.Session()
        s3 = session.client(
            service_name="s3",
            endpoint_url=settings.yc_endpoint_url,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            config=botocore.client.Config(
                signature_version="s3v4",
                connect_timeout=10,
                read_timeout=20,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
            region_name=settings.yc_region,
        )
        manifest = self._load_s3_manifest()
        files_map = manifest.get("files", {})
        if not isinstance(files_map, dict):
            files_map = {}
            manifest["files"] = files_map

        s3_json_objects: dict[str, dict[str, Any]] = {}
        s3_signatures: dict[str, dict[str, Any]] = {}
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.s3_bucket_name, Prefix=list_prefix):
            for obj in page.get("Contents", []):
                key = str(obj.get("Key") or "")
                if not key.endswith(".json"):
                    continue
                s3_json_objects[key] = obj
                s3_signatures[key] = self._s3_obj_signature(obj)

        deleted_keys = {key for key in files_map.keys() if str(key).startswith(list_prefix)} - set(s3_signatures.keys())
        changed_or_new_keys: set[str] = set()
        for key, sig in s3_signatures.items():
            prev_meta = files_map.get(key)
            prev_sig = {
                "etag": str((prev_meta or {}).get("etag", "")),
                "last_modified": str((prev_meta or {}).get("last_modified", "")),
                "size": int((prev_meta or {}).get("size", 0) or 0),
            }
            if sig != prev_sig:
                changed_or_new_keys.add(key)

        keys_to_inspect = sorted(changed_or_new_keys)
        for key in keys_to_inspect:
            if key not in s3_json_objects:
                continue
            sig = s3_signatures[key]
            local_name = Path(key).name
            try:
                response = s3.get_object(Bucket=settings.s3_bucket_name, Key=key)
                content = response["Body"].read().decode("utf-8")
                payload = json.loads(content)
            except Exception:
                logger.exception("Failed to inspect S3 object %s", key)
                continue
            rows = self._rows_from_payload(payload)
            files_map[key] = {
                "etag": sig["etag"],
                "last_modified": sig["last_modified"],
                "size": sig["size"],
                "local_name": local_name,
                "bitrix_ids": self._extract_bitrix_ids(rows),
            }

        for key in deleted_keys:
            files_map.pop(key, None)

        manifest["files"] = files_map
        manifest["user_files"] = self._rebuild_manifest_user_files(files_map)

        user_keys = [
            key for key in manifest.get("user_files", {}).get(bid, [])
            if isinstance(key, str) and key in s3_json_objects
        ]
        matched_local_names: set[str] = set()
        for key in user_keys:
            meta = files_map.get(key, {})
            local_name = str(meta.get("local_name", "") or Path(key).name)
            local_path = self.paths.atwork_root / local_name
            matched_local_names.add(local_name)
            try:
                s3.download_file(settings.s3_bucket_name, key, str(local_path))
                downloaded.append(local_name)
            except Exception:
                logger.exception("Failed to download user file from S3: %s", key)

        # Keep local cache coherent for this user: remove stale local files for this BitrixID.
        for file in self.paths.atwork_root.glob("*.json"):
            if file.name in (ATWORK_INDEX_FILE, ATWORK_S3_MANIFEST_FILE):
                continue
            try:
                payload = _safe_load_json(file)
            except Exception:
                continue
            rows = self._rows_from_payload(payload)
            belongs = any(str(row.get("BitrixID", "") or row.get("TelegramID", "") or "").strip() == bid for row in rows)
            if belongs and file.name not in matched_local_names:
                try:
                    file.unlink()
                    logger.info("Removed stale AtWork file for BitrixID=%s: %s", bid, file.name)
                except Exception:
                    logger.exception("Failed to remove stale AtWork file: %s", file)

        self._persist_s3_manifest(manifest)
        logger.info(
            "Per-user S3 sync done for BitrixID=%s: downloaded=%s, matched=%s",
            bid,
            len(downloaded),
            len(matched_local_names),
        )
        try:
            self._refresh_atwork_index()
        except Exception:
            logger.exception("Failed to refresh AtWork index after S3 sync")
        return {
            "downloaded": downloaded,
            "error": "",
            "matched_files": sorted(matched_local_names),
            "list_prefix": list_prefix,
        }

    async def _sync_user_from_s3(self, bitrix_id: str) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(
                _run_in_thread(self._sync_user_from_s3_blocking, bitrix_id),
                timeout=45.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Per-user S3 sync timed out for BitrixID=%s", bitrix_id)
            return {"downloaded": [], "error": "s3_sync_timeout"}
        except Exception as exc:
            logger.exception("Per-user S3 sync failed for BitrixID=%s", bitrix_id)
            return {"downloaded": [], "error": f"{type(exc).__name__}: {exc}"}

    def _copy_profile_json_to_session(self, state: dict[str, Any], source_file: Path) -> Path | None:
        session_id = str(state.get("session_id") or "")
        if not session_id:
            return None
        if not source_file.exists():
            return None
        session_dir = self._session_dir(session_id)
        target = session_dir / source_file.name
        shutil.copy2(source_file, target)
        state["preset_profile_file"] = target.name
        return target

    def _iter_user_session_dirs(self, bitrix_id: str) -> list[Path]:
        bid = str(bitrix_id or "").strip()
        if not bid:
            return []

        out: list[Path] = []
        seen: set[Path] = set()
        pattern = str(self.paths.users_root / "*" / STATE_FILE)
        for state_file in glob.glob(pattern):
            state_path = Path(state_file)
            try:
                payload = _safe_load_json(state_path)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue

            state_tid = str(payload.get("bitrix_id", "") or payload.get("telegram_id", "") or "").strip()
            profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
            profile_tid = str(profile.get("BitrixID", "") or profile.get("TelegramID", "") or "").strip()
            if state_tid != bid and profile_tid != bid:
                continue

            session_dir = state_path.parent.resolve()
            if session_dir in seen:
                continue
            seen.add(session_dir)
            out.append(session_dir)
        return out

    def _cleanup_user_sessions_if_no_unsent(self, bitrix_id: str) -> None:
        session_dirs = self._iter_user_session_dirs(bitrix_id)
        if not session_dirs:
            return

        has_unsent = False
        for session_dir in session_dirs:
            state_path = session_dir / STATE_FILE
            try:
                payload = _safe_load_json(state_path)
            except Exception:
                continue
            if isinstance(payload, dict) and not bool(payload.get("sent", False)):
                has_unsent = True
                break

        if has_unsent:
            return

        users_root_resolved = self.paths.users_root.resolve()
        for session_dir in session_dirs:
            try:
                resolved = session_dir.resolve()
            except Exception:
                continue
            if users_root_resolved not in resolved.parents:
                logger.warning("Skip deleting session outside Users root: %s", resolved)
                continue
            try:
                shutil.rmtree(resolved)
            except Exception:
                logger.exception("Failed to delete previous sent session dir: %s", resolved)

    async def start_flow(
        self,
        profile: dict[str, Any] | None = None,
        bitrix_id: str | None = None,
    ) -> dict[str, Any]:
        bid = str(bitrix_id or "").strip()
        if bid:
            self._cleanup_user_sessions_if_no_unsent(bid)

        session_id = uuid.uuid4().hex[:12]
        session_dir = self._session_dir(session_id)
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)
        session_dir.mkdir(parents=True, exist_ok=True)
        self._uploads_dir(session_id)

        state: dict[str, Any] = {
            "session_id": session_id,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "display_name": "Web User",
            "step": STEP_SELECT_USER,
            "allowed_actions": ["select_user"],
            "ui_payload": {
                "title": "Авторизация",
                "instruction": "Введите ID",
            },
            "errors": [],
            "selected_base": None,
            "selected_user": None,
            "source": None,
            "transport_method": None,
            "car_number": "",
            "car_brand": "",
            "car_org": "",
            "tire_count": 0,
            "current_tire": 1,
            "current_photo": 0,
            "comment": "",
            "profile": None,
            "bitrix_id": None,
            "telegram_id": None,
            "auth_verified": False,
            "verified_surname": None,
            "preset_profile_file": None,
            "photos": {},
            "extra_photos": [],
            "final_payload": None,
            "sent": False,
            "session_dir": str(session_dir),
        }

        # Start by Telegram/Bitrix ID: sync from S3 and verify access before base selection.
        if bid:
            if await self._authenticate_web_user(state, bid):
                self._set_select_base_step(state, bid)
            self._save_state(state)
            return self._format_state(state)

        # If profile is provided (e.g. from Bitrix), skip the select_user step.
        if isinstance(profile, dict) and profile:
            resolved_profile = copy.deepcopy(profile)
            if "BitrixID" not in resolved_profile and resolved_profile.get("TelegramID") not in (None, ""):
                resolved_profile["BitrixID"] = resolved_profile.get("TelegramID")
            if "TelegramID" not in resolved_profile and resolved_profile.get("BitrixID") not in (None, ""):
                resolved_profile["TelegramID"] = resolved_profile.get("BitrixID")
            uid = str(resolved_profile.get("UID", "") or "").strip()
            name = str(resolved_profile.get("Name", "") or "").strip() or "Bitrix User"
            base = str(resolved_profile.get("BaseName", "") or "").strip()
            resolved_profile["Name"] = name

            state["display_name"] = name
            state["selected_user"] = name
            state["selected_base"] = base or None
            state["profile"] = resolved_profile
            session_dir_label = self._session_dir_label_from_profile(resolved_profile, fallback=uid)
            if session_dir_label:
                self._rename_session_dir_for_user(state, session_dir_label)
            self._set_step(
                state,
                STEP_SELECT_SOURCE,
                allowed_actions=["select_source"],
                ui_payload={
                    "user_name": name,
                    "base_name": base,
                    "source_options": ["Склад", "Транспорт"],
                },
            )

        self._save_state(state)
        return self._format_state(state)

    def get_flow(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        if self._normalize_legacy_steps(state):
            self._save_state(state)
        return self._format_state(state)

    def _photo_key(self, tire_idx: int, photo_idx: int) -> str:
        return f"t{tire_idx}_p{photo_idx}"

    def _max_uploaded_photo(self, state: dict[str, Any], tire_number: int) -> int:
        """Highest photo number that has been stored for the given tire (0 if none)."""
        photos = state.get("photos", {})
        max_p = 0
        for p in range(1, 30):
            if self._photo_key(tire_number, p) in photos:
                max_p = p
            else:
                break
        return max_p

    def _car_lookup(self, car_number: str) -> dict[str, str]:
        return self._car_db.get(_normalize_number(car_number), {})

    def _demo_image_filename(self, source: str, photo_number: int) -> str | None:
        """Returns the demo image filename for a given source+photo combination."""
        prefix = "car_" if source == "Транспорт" else "warehause_"
        demo_dir = _to_abs(settings.demo_img_dir)
        for ext in (".jpg", ".png"):
            candidate = demo_dir / f"{prefix}{photo_number}{ext}"
            if candidate.exists():
                return candidate.name
        return None

    def _car_demo_image_filename(self) -> str | None:
        """Returns demo image filename for car upload step."""
        demo_dir = _to_abs(settings.demo_img_dir)
        preferred = demo_dir / "start_img.png"
        if preferred.exists():
            return preferred.name
        return self._demo_image_filename("Транспорт", 1)

    def _prepare_upload_step(
        self,
        state: dict[str, Any],
        photo_number: int | None = None,
        preview_file: str | None = None,
        last_result: dict[str, Any] | None = None,
    ) -> None:
        if photo_number is not None:
            state["current_photo"] = int(photo_number)
        p = int(state.get("current_photo") or 1)
        tire = int(state.get("current_tire") or 1)
        source = str(state.get("source") or "")
        # If caller did not provide preview/result explicitly, reuse already uploaded photo
        # for this tire/photo so backward navigation keeps the image visible.
        if preview_file is None or last_result is None:
            row = (state.get("photos") or {}).get(self._photo_key(tire, p), {})
            if preview_file is None:
                preview_file = row.get("file_name")
            if last_result is None:
                existing_result = row.get("result")
                if isinstance(existing_result, dict):
                    last_result = existing_result
        descriptions = {
            1: "Общий вид колеса (шина сбоку)",
            2: "Общий вид колеса (шина спереди)",
            3: "Высота протектора (с прил. измерит. инструмента)",
            4: "Идентификация шины (заводской номер)",
            5: "Идентификация шины (марка и модель шины)",
        }
        self._set_step(
            state,
            STEP_UPLOAD_TIRE_PHOTO,
            allowed_actions=["upload_image", "navigate_back", "navigate_forward"],
            ui_payload={
                "tire_number": tire,
                "photo_number": p,
                "description": descriptions.get(p, f"Дополнительное фото #{p}"),
                "required": p <= 5,
                "source": source,
                "demo_image": self._demo_image_filename(source, p),
                "preview_file": preview_file,
                "last_result": last_result,
            },
        )

    def _prepare_post_required_step(self, state: dict[str, Any]) -> None:
        tire = int(state.get("current_tire") or 1)
        tire_count = int(state.get("tire_count") or 0)
        is_last = tire >= tire_count
        actions = ["add_additional_photo", "navigate_back"]
        if is_last:
            actions += ["finish_with_comment", "finish_without_comment"]
        else:
            actions.append("next_tire")
        self._set_step(
            state,
            STEP_POST_REQUIRED,
            allowed_actions=actions,
            ui_payload={"tire_number": tire, "is_last_tire": is_last},
        )

    def _build_flow_summary(self, state: dict[str, Any]) -> dict[str, Any]:
        photo_rows: list[dict[str, Any]] = []
        photos = state.get("photos", {})
        for key in sorted(photos.keys()):
            row = photos[key]
            if not isinstance(row, dict):
                continue
            photo_rows.append(
                {
                    "tire_number": row.get("tire_number"),
                    "photo_number": row.get("photo_number"),
                    "file_name": row.get("file_name"),
                    "result": row.get("result", {}),
                }
            )
        profile = state.get("profile")
        user_name = profile.get("Name") if isinstance(profile, dict) else None
        return {
            "selected_base": state.get("selected_base"),
            "user_name": user_name,
            "source": state.get("source"),
            "car_number": state.get("car_number"),
            "car_brand": state.get("car_brand"),
            "tire_count": state.get("tire_count"),
            "comment": state.get("comment", ""),
            "photos": photo_rows,
        }

    def _check_allowed(self, state: dict[str, Any], action: str) -> None:
        allowed = state.get("allowed_actions", [])
        if action not in allowed:
            raise ValueError(json.dumps(_map_action_error(str(state.get("step")), action), ensure_ascii=False))

    async def apply_action(self, session_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        state = self._load_state(session_id)
        if self._normalize_legacy_steps(state):
            self._save_state(state)
        payload = payload or {}
        self._clear_errors(state)

        try:
            self._check_allowed(state, action)
        except ValueError:
            err = _map_action_error(str(state.get("step")), action)
            self._set_error(state, err["code"], err["message"])
            self._save_state(state)
            return self._format_state(state)

        try:
            if action == "select_base":
                if not state.get("auth_verified"):
                    self._set_select_user_step(state, ACCESS_DENIED_CODE, ACCESS_DENIED_MESSAGE)
                    self._save_state(state)
                    return self._format_state(state)

                uid = str(payload.get("uid", "") or "").strip()
                base_name = str(payload.get("base_name", "") or "").strip()
                bid = str(state.get("bitrix_id", "") or state.get("telegram_id", "") or "").strip()
                profile: dict[str, Any] | None = None
                profile_file: Path | None = None
                if bid:
                    picked = self._choose_profile_by_bitrix_uid_base(bid, uid, base_name)
                    if picked:
                        profile, profile_file = picked
                else:
                    profile = self._choose_profile_for_uid(uid, base_name) if uid and base_name else None

                if not profile:
                    self._set_error(state, "invalid_base", "База не найдена в AtWork.")
                    if bid:
                        self._set_select_base_step(state, bid)
                else:
                    if "BitrixID" not in profile and profile.get("TelegramID") not in (None, ""):
                        profile["BitrixID"] = profile.get("TelegramID")
                    if "TelegramID" not in profile and profile.get("BitrixID") not in (None, ""):
                        profile["TelegramID"] = profile.get("BitrixID")
                    state["profile"]       = profile
                    state["selected_base"] = base_name
                    state["selected_user"] = str(profile.get("Name", "") or "")
                    state["display_name"] = str(profile.get("Name", "") or "")
                    session_dir_label = self._session_dir_label_from_profile(profile, fallback=uid)
                    if session_dir_label:
                        self._rename_session_dir_for_user(state, session_dir_label)
                    if profile_file:
                        self._copy_profile_json_to_session(state, profile_file)
                    user_name = str(profile.get("Name", "") or state.get("selected_user", ""))
                    self._set_step(
                        state,
                        STEP_SELECT_SOURCE,
                        allowed_actions=["select_source", "navigate_back"],
                        ui_payload={
                            "base_name": base_name,
                            "user_name": user_name,
                            "source_options": ["Склад", "Транспорт"],
                        },
                    )

            elif action == "select_user":
                user_id = str(
                    payload.get("BitrixID", "")
                    or payload.get("bitrix_id", "")
                    or payload.get("TelegramID", "")
                    or payload.get("telegram_id", "")
                    or payload.get("user_id", "")
                    or ""
                ).strip()
                if await self._authenticate_web_user(state, user_id):
                    self._set_select_base_step(state, user_id)

            elif action == "navigate_back":
                # Go back to a specific photo (photo_number in payload) or to the previous step.
                step = str(state.get("step") or "")
                source = str(state.get("source") or "")
                transport_method = str(state.get("transport_method") or "")
                target_photo = payload.get("photo_number")  # specific photo dot clicked
                target_stage = payload.get("target_stage")  # stepper stage clicked (0 = Настройка)
                preserve_context = bool(payload.get("preserve_context"))

                tire_now = int(state.get("current_tire") or 1)
                max_p = self._max_uploaded_photo(state, tire_now)

                # Jump to specific photo when a numbered dot was clicked (backward)
                if target_photo is not None and step in (
                    STEP_UPLOAD_TIRE_PHOTO, STEP_CONFIRM_PHOTO,
                    STEP_CONFIRM_TIRE_NUMBER, STEP_POST_REQUIRED,
                ):
                    target_photo = int(target_photo)
                    # For post_required, use max uploaded photo as reference (not current_photo which may be 5)
                    if step == STEP_POST_REQUIRED:
                        cur_p = max_p + 1  # any target < max+1 is valid
                    else:
                        cur_p = int(state.get("current_photo") or 1)
                    if 1 <= target_photo < cur_p:
                        self._prepare_upload_step(state, photo_number=target_photo)
                        # If photos exist beyond the new position, allow forward navigation
                        if self._max_uploaded_photo(state, tire_now) > target_photo:
                            acts = list(state.get("allowed_actions", []))
                            if "navigate_forward" not in acts:
                                acts.append("navigate_forward")
                            state["allowed_actions"] = acts
                    else:
                        self._set_error(state, "cannot_go_back", "Нельзя перейти к этому фото")

                # Jump to Настройка stage (user/base/source selection) when stepper clicked
                elif target_stage == 0 or step in (STEP_SELECT_BASE, STEP_SELECT_SOURCE):
                    bid = str(state.get("bitrix_id", "") or state.get("telegram_id", "") or "").strip()
                    if target_stage == 0 and preserve_context and state.get("profile"):
                        profile = state.get("profile") if isinstance(state.get("profile"), dict) else {}
                        self._set_step(
                            state,
                            STEP_SELECT_SOURCE,
                            allowed_actions=["select_source", "navigate_back"],
                            ui_payload={
                                "user_name": str(profile.get("Name", "") or state.get("selected_user", "")),
                                "user_id": str(profile.get("UID", "") or ""),
                                "source_options": ["Склад", "Транспорт"],
                            },
                        )
                    elif bid:
                        state["profile"] = None
                        state["selected_base"] = None
                        state["source"] = None
                        self._set_select_base_step(state, bid)
                    else:
                        state["profile"] = None
                        state["selected_base"] = None
                        state["selected_user"] = None
                        state["source"] = None
                        self._set_step(
                            state, STEP_SELECT_USER,
                            allowed_actions=["select_user"],
                            ui_payload={
                                "title": "Авторизация",
                                "instruction": "Введите ID",
                            },
                        )
                elif step == STEP_SELECT_TRANSPORT_METHOD:
                    state["source"] = None
                    self._set_step(
                        state, STEP_SELECT_SOURCE,
                        allowed_actions=["select_source", "navigate_back"],
                        ui_payload={"source_options": ["Склад", "Транспорт"]},
                    )
                elif step in (STEP_UPLOAD_CAR_PHOTO, STEP_ENTER_MANUAL_CAR_NUMBER):
                    state["transport_method"] = "automatic"
                    self._set_step(
                        state, STEP_SELECT_SOURCE,
                        allowed_actions=["select_source", "navigate_back"],
                        ui_payload={"source_options": ["Склад", "Транспорт"]},
                    )
                elif step == STEP_CONFIRM_CAR:
                    state["car_number"] = ""
                    state["car_brand"] = ""
                    self._set_step(
                        state, STEP_UPLOAD_CAR_PHOTO,
                        allowed_actions=["upload_image", "submit_manual_car_number", "navigate_back"],
                        ui_payload={
                            "instruction": "Загрузите фото автомобиля для автоматического распознавания номера или введите номер вручную ниже",
                            "demo_image": self._car_demo_image_filename(),
                        },
                    )
                elif step == STEP_SET_TIRE_COUNT:
                    if source == "Транспорт":
                        self._set_step(
                            state, STEP_CONFIRM_CAR,
                            allowed_actions=["confirm_car", "retry_car", "navigate_back"],
                            ui_payload=state.get("ui_payload", {}),
                        )
                    else:
                        state["source"] = None
                        self._set_step(
                            state, STEP_SELECT_SOURCE,
                            allowed_actions=["select_source", "navigate_back"],
                            ui_payload={"source_options": ["Склад", "Транспорт"]},
                        )
                elif step == STEP_UPLOAD_TIRE_PHOTO:
                    p = int(state.get("current_photo") or 1)
                    if p <= 1:
                        self._set_step(
                            state, STEP_SET_TIRE_COUNT,
                            allowed_actions=["set_tire_count", "navigate_back"],
                            ui_payload={"source": source},
                        )
                    else:
                        self._prepare_upload_step(state, photo_number=p - 1)
                elif step == STEP_COMMENT:
                    self._prepare_post_required_step(state)
                else:
                    self._set_error(state, "cannot_go_back", "Возврат на предыдущий шаг недоступен")

            elif action == "navigate_forward":
                # Jump forward to a specific photo (dot click) or to the latest unfinished photo.
                tire = int(state.get("current_tire") or 1)
                max_p = self._max_uploaded_photo(state, tire)
                target_photo = payload.get("photo_number")

                if target_photo is not None:
                    target_photo = int(target_photo)
                    key = self._photo_key(tire, target_photo)
                    photo_data = (state.get("photos") or {}).get(key)
                    if photo_data:
                        # Already uploaded/accepted photo: open upload step with saved preview/result.
                        # This allows review/retake without forcing repeated "confirm".
                        self._prepare_upload_step(
                            state,
                            photo_number=target_photo,
                            preview_file=photo_data.get("file_name"),
                            last_result=photo_data.get("result") if isinstance(photo_data.get("result"), dict) else None,
                        )
                    else:
                        # Photo not stored yet, jump to upload
                        self._prepare_upload_step(state, photo_number=target_photo)
                elif max_p >= 5:
                    # All required photos done — restore post-required step
                    self._prepare_post_required_step(state)
                else:
                    # Jump to the next unprocessed photo
                    self._prepare_upload_step(state, photo_number=max_p + 1)

            elif action == "select_source":
                source = str(payload.get("source", "")).strip()
                if source not in {"Склад", "Транспорт"}:
                    self._set_error(state, "invalid_source", "Источник должен быть 'Склад' или 'Транспорт'")
                else:
                    state["source"] = source
                    if source == "Транспорт":
                        state["transport_method"] = "automatic"
                        self._set_step(
                            state,
                            STEP_UPLOAD_CAR_PHOTO,
                            allowed_actions=["upload_image", "submit_manual_car_number", "navigate_back"],
                            ui_payload={
                                "instruction": "Загрузите фото автомобиля для автоматического распознавания номера или введите номер вручную ниже",
                                "demo_image": self._car_demo_image_filename(),
                            },
                        )
                    else:
                        self._set_step(
                            state,
                            STEP_SET_TIRE_COUNT,
                            allowed_actions=["set_tire_count", "navigate_back"],
                            ui_payload={"source": source},
                        )

            elif action == "select_transport_method":
                method = str(payload.get("method", "")).strip().lower()
                if method not in {"automatic", "manual"}:
                    self._set_error(state, "invalid_transport_method", "Метод должен быть automatic/manual")
                else:
                    state["transport_method"] = method
                    self._set_step(
                        state,
                        STEP_UPLOAD_CAR_PHOTO,
                        allowed_actions=["upload_image", "submit_manual_car_number", "navigate_back"],
                        ui_payload={
                            "instruction": "Загрузите фото автомобиля для автоматического распознавания номера или введите номер вручную ниже",
                            "demo_image": self._car_demo_image_filename(),
                        },
                    )

            elif action == "submit_manual_car_number":
                number = _normalize_number(str(payload.get("car_number", "")))
                if not number:
                    self._set_error(state, "invalid_manual_number", "Номер автомобиля не введен")
                else:
                    hit = self._car_lookup(number)
                    state["car_number"] = number
                    state["car_brand"] = hit.get("brand", "")
                    state["car_org"] = hit.get("org", "")
                    self._set_step(
                        state,
                        STEP_CONFIRM_CAR,
                        allowed_actions=["confirm_car", "retry_car", "navigate_back"],
                        ui_payload={
                            "number": number,
                            "found_in_db": bool(hit),
                            "brand": state["car_brand"],
                            "org": state["car_org"],
                            "method": "manual",
                        },
                    )

            elif action == "confirm_car":
                if not state.get("car_number"):
                    self._set_error(state, "no_car_number", "Сначала распознайте или введите номер автомобиля")
                else:
                    self._set_step(
                        state,
                        STEP_SET_TIRE_COUNT,
                        allowed_actions=["set_tire_count"],
                        ui_payload={
                            "car_number": state.get("car_number"),
                            "car_brand": state.get("car_brand", ""),
                        },
                    )

            elif action == "retry_car":
                current_step = str(state.get("step") or "")
                # Unified flow: retry returns to car upload step with optional manual input.
                if current_step == STEP_UPLOAD_CAR_PHOTO:
                    self._set_step(
                        state,
                        STEP_UPLOAD_CAR_PHOTO,
                        allowed_actions=["upload_image", "submit_manual_car_number", "navigate_back"],
                        ui_payload={
                            "instruction": "Сделайте новое фото автомобиля для распознавания или введите номер вручную",
                            "demo_image": self._car_demo_image_filename(),
                        },
                    )
                elif state.get("transport_method") == "manual":
                    self._set_step(
                        state,
                        STEP_UPLOAD_CAR_PHOTO,
                        allowed_actions=["upload_image", "submit_manual_car_number", "navigate_back"],
                        ui_payload={
                            "instruction": "Сделайте новое фото автомобиля для распознавания или введите номер вручную",
                            "demo_image": self._car_demo_image_filename(),
                        },
                    )
                else:
                    self._set_step(
                        state,
                        STEP_UPLOAD_CAR_PHOTO,
                        allowed_actions=["upload_image", "submit_manual_car_number", "navigate_back"],
                        ui_payload={
                            "instruction": "Сделайте новое фото автомобиля для распознавания или введите номер вручную",
                            "demo_image": self._car_demo_image_filename(),
                        },
                    )

            elif action == "set_tire_count":
                count = int(payload.get("tire_count") or 0)
                if count <= 0:
                    self._set_error(state, "invalid_tire_count", "Количество шин должно быть > 0")
                else:
                    state["tire_count"] = count
                    state["current_tire"] = 1
                    state["current_photo"] = 1
                    self._prepare_upload_step(state, photo_number=1)

            elif action == "confirm_photo":
                photo_number = int(state.get("current_photo") or 0)
                if photo_number <= 0:
                    self._set_error(state, "invalid_photo_state", "Некорректный шаг подтверждения фото")
                elif photo_number < 5:
                    state["current_photo"] = photo_number + 1
                    self._prepare_upload_step(state)
                else:
                    self._prepare_post_required_step(state)

            elif action == "retry_photo":
                self._prepare_upload_step(state)

            elif action == "confirm_tire_number":
                number = _normalize_number(str(payload.get("number", "")))
                if not number:
                    self._set_error(state, "invalid_tire_number", "Подтвердить пустой номер нельзя")
                else:
                    key = self._photo_key(int(state["current_tire"]), 4)
                    row = state.get("photos", {}).get(key, {})
                    if isinstance(row, dict):
                        result = row.get("result", {})
                        if isinstance(result, dict):
                            result["number"] = number
                            result["found"] = True
                            result["error"] = None
                    state["current_photo"] = 5
                    self._prepare_upload_step(state)

            elif action == "manual_tire_number":
                number = _normalize_number(str(payload.get("number", "")))
                if not number:
                    self._set_error(state, "invalid_manual_tire_number", "Введите номер вручную")
                else:
                    key = self._photo_key(int(state["current_tire"]), 4)
                    row = state.get("photos", {}).get(key, {})
                    if isinstance(row, dict):
                        result = row.get("result", {})
                        if isinstance(result, dict):
                            result["number"] = number
                            result["found"] = True
                            result["error"] = None
                    state["current_photo"] = 5
                    self._prepare_upload_step(state)

            elif action == "retake_photo_4":
                state["current_photo"] = 4
                self._prepare_upload_step(state)

            elif action == "add_additional_photo":
                tire = int(state.get("current_tire") or 1)
                photos = state.get("photos", {})
                max_stored = max(
                    (int(v.get("photo_number", 0)) for k, v in photos.items()
                     if isinstance(v, dict) and int(v.get("tire_number", 0)) == tire),
                    default=5,
                )
                state["current_photo"] = max(6, max_stored + 1)
                self._prepare_upload_step(state)

            elif action == "next_tire":
                current_tire = int(state.get("current_tire") or 1)
                tire_count = int(state.get("tire_count") or 0)
                if current_tire >= tire_count:
                    self._set_error(state, "no_next_tire", "Все шины уже обработаны")
                else:
                    state["current_tire"] = current_tire + 1
                    state["current_photo"] = 1
                    self._prepare_upload_step(state, photo_number=1)

            elif action == "finish_with_comment":
                self._set_step(
                    state,
                    STEP_COMMENT,
                    allowed_actions=["submit_comment"],
                    ui_payload={"instruction": "Введите комментарий для завершения"},
                )

            elif action == "finish_without_comment":
                state["comment"] = ""
                self._set_step(
                    state,
                    STEP_CONFIRM_SEND,
                    allowed_actions=["confirm_send", "cancel_send"],
                    ui_payload={"summary": self._build_flow_summary(state)},
                )

            elif action == "submit_comment":
                comment = str(payload.get("comment", "") or "").strip()
                state["comment"] = comment
                self._set_step(
                    state,
                    STEP_CONFIRM_SEND,
                    allowed_actions=["confirm_send", "cancel_send"],
                    ui_payload={"summary": self._build_flow_summary(state)},
                )

            elif action == "confirm_send":
                sent, message, send_result = await self._export_to_1c(state)
                state["last_send_result"] = send_result
                if sent:
                    state["sent"] = True
                    self._set_step(
                        state,
                        STEP_FINISHED,
                        allowed_actions=[],
                        ui_payload={"status": "sent", "message": message, "send_result": send_result},
                    )
                else:
                    self._set_error(state, "send_failed", message, {"send_result": send_result})
                    self._set_step(
                        state,
                        STEP_CONFIRM_SEND,
                        allowed_actions=["confirm_send", "cancel_send"],
                        ui_payload={
                            "summary": self._build_flow_summary(state),
                            "send_result": send_result,
                        },
                    )

            elif action == "cancel_send":
                self._set_step(
                    state,
                    STEP_FINISHED,
                    allowed_actions=[],
                    ui_payload={"status": "cancelled", "message": "Отправка отменена пользователем"},
                )

            else:
                self._set_error(state, "unknown_action", f"Неизвестное действие: {action}")

        except Exception as exc:
            logger.exception("apply_action error")
            self._set_error(state, "internal_error", str(exc))

        self._save_state(state)
        return self._format_state(state)

    def _image_to_jpeg_bytes(self, image_bytes: bytes) -> bytes:
        image = Image.open(io.BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image).convert("RGB")
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=95)
        return out.getvalue()

    def _save_uploaded_image(self, session_id: str, tire_number: int, photo_number: int, image_bytes: bytes) -> Path:
        upload_dir = self._uploads_dir(session_id)
        file_name = f"tire_{tire_number}_photo_{photo_number}.jpg"
        target = upload_dir / file_name
        target.write_bytes(image_bytes)
        return target

    async def _call_container_api(self, url: str, image_bytes: bytes, data: dict[str, Any] | None = None) -> dict[str, Any]:
        files = {"image": ("upload.jpg", image_bytes, "image/jpeg")}
        timeout = httpx.Timeout(settings.upstream_timeout_sec)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, files=files, data=data or {})
            resp.raise_for_status()
            return resp.json()

    def _store_photo_result(
        self,
        state: dict[str, Any],
        tire_number: int,
        photo_number: int,
        file_path: Path,
        result: dict[str, Any],
        private_result: dict[str, Any] | None = None,
    ) -> None:
        key = self._photo_key(tire_number, photo_number)
        photos = state.setdefault("photos", {})
        row = {
            "tire_number": tire_number,
            "photo_number": photo_number,
            "file_name": file_path.name,
            "file_path": str(file_path),
            "result": result,
            "saved_at": _now_iso(),
        }
        if isinstance(private_result, dict):
            # Keep sensitive upstream payload for internal/export usage only.
            row["private_result"] = private_result
        photos[key] = row

    async def upload(self, session_id: str, image_bytes: bytes, file_name: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        self._clear_errors(state)
        current_step = str(state.get("step") or "")

        if "upload_image" not in state.get("allowed_actions", []):
            self._set_error(state, "upload_not_allowed", f"Загрузка недоступна на шаге {current_step}")
            self._save_state(state)
            return self._format_state(state)

        try:
            normalized = self._image_to_jpeg_bytes(image_bytes)
        except Exception as exc:
            self._set_error(state, "invalid_image", f"Файл не является валидным изображением: {exc}")
            self._save_state(state)
            return self._format_state(state)

        if current_step == STEP_UPLOAD_CAR_PHOTO:
            await self._handle_upload_car_photo(state, normalized, file_name)
            self._save_state(state)
            return self._format_state(state)

        if current_step == STEP_UPLOAD_TIRE_PHOTO:
            await self._handle_upload_tire_photo(state, normalized, file_name)
            self._save_state(state)
            return self._format_state(state)

        self._set_error(state, "unsupported_upload_step", f"Загрузка на шаге {current_step} не поддерживается")
        self._save_state(state)
        return self._format_state(state)

    async def _handle_upload_car_photo(self, state: dict[str, Any], image_bytes: bytes, file_name: str) -> None:
        upload_dir = self._uploads_dir(state["session_id"])
        target = upload_dir / "car_number.jpg"
        target.write_bytes(image_bytes)

        try:
            payload = await self._call_container_api(settings.car_number_api_url, image_bytes)
            found = bool(payload.get("found", False))
            number = _normalize_number(str(payload.get("number", "")))
            raw_result = str(payload.get("raw_result", "") or "").strip()
            error_code = str(payload.get("error") or "")
            if found and number:
                hit = self._car_lookup(number)
                state["car_number"] = number
                state["car_brand"] = hit.get("brand", "")
                state["car_org"] = hit.get("org", "")
                self._set_step(
                    state,
                    STEP_CONFIRM_CAR,
                    allowed_actions=["confirm_car", "retry_car", "navigate_back"],
                    ui_payload={
                        "number": number,
                        "found_in_db": bool(hit),
                        "brand": state["car_brand"],
                        "org": state["car_org"],
                        "method": "automatic",
                        "raw_result": raw_result,
                        "preview_file": target.name,
                    },
                )
            else:
                self._set_error(
                    state,
                    "car_number_not_recognized",
                    "Номер не распознан",
                    {"container_error": error_code or "number_not_found", "raw_result": raw_result or "<пусто>"},
                )
                self._set_step(
                    state,
                    STEP_UPLOAD_CAR_PHOTO,
                    allowed_actions=["upload_image", "submit_manual_car_number", "navigate_back"],
                    ui_payload={
                        "instruction": "Сделайте фото для распознавания номера транспортного средства",
                        "demo_image": self._car_demo_image_filename(),
                        "last_raw_result": raw_result or "",
                        "last_error_code": error_code or "number_not_found",
                        "last_recognized_number": number or state.get("car_number", ""),
                        "preview_file": target.name,
                    },
                )
        except httpx.HTTPStatusError as exc:
            self._set_error(state, "car_number_api_bad_status", f"Ошибка контейнера: {exc.response.status_code}")
        except Exception as exc:
            self._set_error(state, "car_number_api_unavailable", str(exc))

    async def _handle_upload_tire_photo(self, state: dict[str, Any], image_bytes: bytes, file_name: str) -> None:
        tire_number = int(state.get("current_tire") or 1)
        photo_number = int(state.get("current_photo") or 1)
        stored = self._save_uploaded_image(state["session_id"], tire_number, photo_number, image_bytes)

        if photo_number == 1:
            await self._handle_tire_analysis_photo(state, stored, image_bytes, mode="quality")
            return
        if photo_number == 2:
            await self._handle_tire_analysis_photo(state, stored, image_bytes, mode="full")
            return
        if photo_number == 3:
            result = {"success": True, "message": "Фото 3 сохранено (локальная обработка без контейнера)"}
            self._store_photo_result(state, tire_number, photo_number, stored, result)
            self._set_step(
                state,
                STEP_CONFIRM_PHOTO,
                allowed_actions=["confirm_photo", "retry_photo", "navigate_back"],
                ui_payload={"tire_number": tire_number, "photo_number": photo_number, "result": result, "preview_file": stored.name},
            )
            return
        if photo_number == 4:
            await self._handle_tire_number_photo(state, stored, image_bytes)
            return
        if photo_number == 5:
            result = {"success": True, "message": "Фото 5 сохранено (локальная обработка без контейнера)"}
            self._store_photo_result(state, tire_number, photo_number, stored, result)
            self._set_step(
                state,
                STEP_CONFIRM_PHOTO,
                allowed_actions=["confirm_photo", "retry_photo", "navigate_back"],
                ui_payload={"tire_number": tire_number, "photo_number": photo_number, "result": result, "preview_file": stored.name},
            )
            return

        result = {"success": True, "message": f"Дополнительное фото {photo_number} сохранено"}
        self._store_photo_result(state, tire_number, photo_number, stored, result)
        self._set_step(
            state,
            STEP_CONFIRM_PHOTO,
            allowed_actions=["confirm_photo", "retry_photo", "navigate_back"],
            ui_payload={"tire_number": tire_number, "photo_number": photo_number, "result": result, "preview_file": stored.name},
        )

    async def _handle_tire_analysis_photo(self, state: dict[str, Any], stored: Path, image_bytes: bytes, mode: str) -> None:
        tire_number = int(state.get("current_tire") or 1)
        photo_number = int(state.get("current_photo") or 1)
        try:
            payload = await self._call_container_api(settings.tire_analysis_api_url, image_bytes, data={"mode": mode})
            detection = payload.get("detection") or {}
            count = int(detection.get("count") or 0)
            upstream_error = str(payload.get("error") or "")

            if upstream_error in ("cropped", "cropped_multiple"):
                side_map = {
                    "top": "сверху",
                    "bottom": "снизу",
                    "left": "слева",
                    "right": "справа",
                }
                cropped_sides = detection.get("cropped_sides") or []
                side_text = ", ".join(side_map.get(str(s), str(s)) for s in cropped_sides) or "по краям"
                result = {
                    "success": False,
                    "mode": payload.get("mode", mode),
                    "error": upstream_error,
                    "quality": payload.get("quality"),
                    "classification": (payload.get("quality") or {}).get("classification") if isinstance(payload.get("quality"), dict) else None,
                    "score": (payload.get("quality") or {}).get("score") if isinstance(payload.get("quality"), dict) else None,
                    "season_spikes": payload.get("season_spikes"),
                    "detection": detection,
                }
                self._set_error(
                    state,
                    upstream_error,
                    f"Обнаружена обрезка шины ({side_text})",
                    {"mode": mode, "upstream": payload},
                )
                self._prepare_upload_step(
                    state,
                    photo_number=photo_number,
                    preview_file=stored.name,
                    last_result=result,
                )
                return

            if not bool(payload.get("success", False)):
                err = str(payload.get("error") or "tire_analysis_failed")
                self._set_error(state, "tire_analysis_failed", err, {"mode": mode, "upstream": payload})
                self._prepare_upload_step(state, photo_number=photo_number)
                return

            if count <= 0:
                self._set_error(state, "no_detection", "Шина не обнаружена на фото", {"mode": mode, "upstream": payload})
                self._prepare_upload_step(state, photo_number=photo_number)
                return

            result = {
                "success": True,
                "mode": payload.get("mode", mode),
                "quality": payload.get("quality"),
                "classification": (payload.get("quality") or {}).get("classification") if isinstance(payload.get("quality"), dict) else None,
                "score": (payload.get("quality") or {}).get("score") if isinstance(payload.get("quality"), dict) else None,
                "season_spikes": payload.get("season_spikes"),
                "detection": detection,
            }
            self._store_photo_result(
                state,
                tire_number,
                photo_number,
                stored,
                result,
                private_result=payload,
            )
            self._set_step(
                state,
                STEP_CONFIRM_PHOTO,
                allowed_actions=["confirm_photo", "retry_photo", "navigate_back"],
                ui_payload={"tire_number": tire_number, "photo_number": photo_number, "result": result, "preview_file": stored.name},
            )
        except httpx.HTTPStatusError as exc:
            self._set_error(state, "tire_analysis_api_bad_status", f"{exc.response.status_code}")
            self._prepare_upload_step(state, photo_number=photo_number)
        except Exception as exc:
            self._set_error(state, "tire_analysis_api_unavailable", str(exc))
            self._prepare_upload_step(state, photo_number=photo_number)

    async def _handle_tire_number_photo(self, state: dict[str, Any], stored: Path, image_bytes: bytes) -> None:
        tire_number = int(state.get("current_tire") or 1)
        photo_number = 4
        try:
            payload = await self._call_container_api(settings.tire_number_api_url, image_bytes)
            found = bool(payload.get("found", False))
            number = _normalize_number(str(payload.get("number", "")))
            result = {
                "found": found,
                "number": number,
                "confidence": float(payload.get("confidence", 0.0) or 0.0),
                "error": payload.get("error"),
            }
            self._store_photo_result(state, tire_number, photo_number, stored, result)
            self._set_step(
                state,
                STEP_CONFIRM_TIRE_NUMBER,
                allowed_actions=["confirm_tire_number", "manual_tire_number", "retake_photo_4", "navigate_back"],
                ui_payload={
                    "tire_number": tire_number,
                    "photo_number": photo_number,
                    "result": result,
                    "preview_file": stored.name,
                },
            )
        except httpx.HTTPStatusError as exc:
            self._set_error(state, "tire_number_api_bad_status", f"{exc.response.status_code}")
            self._prepare_upload_step(state, photo_number=photo_number)
        except Exception as exc:
            self._set_error(state, "tire_number_api_unavailable", str(exc))
            self._prepare_upload_step(state, photo_number=photo_number)

    def _compose_export_json(self, state: dict[str, Any]) -> dict[str, Any]:
        profile = state.get("profile") if isinstance(state.get("profile"), dict) else {}
        images: list[dict[str, Any]] = []
        photos = state.get("photos", {})
        for key in sorted(photos.keys()):
            row = photos[key]
            if not isinstance(row, dict):
                continue
            file_path = Path(str(row.get("file_path") or ""))
            if not file_path.exists():
                continue
            encoded = base64.b64encode(file_path.read_bytes()).decode("utf-8")
            name = file_path.stem
            ext = file_path.suffix.lstrip(".").lower() or "jpg"
            images.append({"name": name, "fileExtension": ext, "fileData": encoded})

        auto_comment_parts: list[str] = []
        for key in sorted(photos.keys()):
            row = photos[key]
            if not isinstance(row, dict):
                continue
            if int(row.get("photo_number") or 0) == 4:
                n = str((row.get("result") or {}).get("number", "")).strip()
                if n:
                    auto_comment_parts.append(f"Шина {row.get('tire_number')} - номер: {n}")
        user_comment = str(state.get("comment", "") or "").strip()
        if user_comment:
            auto_comment_parts.append(f"Комментарий пользователя: {user_comment}")
        final_comment = " | ".join(auto_comment_parts)

        data: dict[str, Any] = {
            "data_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": state.get("source"),
            "comment": final_comment,
            "images": images,
        }

        if str(state.get("source") or "") == "Транспорт":
            data["car_number"] = state.get("car_number", "")
            data["car_brand"] = state.get("car_brand", "")

        if isinstance(profile, dict):
            for key in ["UID", "Name", "BaseName", "ConnectionString", "NameCompany", "BitrixID", "TelegramID"]:
                if key in profile:
                    data[key] = profile[key]
        return data

    def _merge_preset_and_session_json(self, state: dict[str, Any], session_payload: dict[str, Any]) -> dict[str, Any]:
        preset_name = str(state.get("preset_profile_file", "") or "").strip()
        if not preset_name:
            return session_payload

        session_dir = self._session_dir(state["session_id"])
        preset_path = session_dir / preset_name
        if not preset_path.exists():
            logger.warning("Preset profile file missing in session dir: %s", preset_path)
            return session_payload

        try:
            preset_raw = _safe_load_json(preset_path)
        except Exception:
            logger.exception("Failed to read preset profile file: %s", preset_path)
            return session_payload

        if isinstance(preset_raw, list):
            if not preset_raw or not isinstance(preset_raw[0], dict):
                logger.warning("Preset profile has invalid list payload: %s", preset_path)
                return session_payload
            preset_data = preset_raw[0]
        elif isinstance(preset_raw, dict):
            preset_data = preset_raw
        else:
            logger.warning("Preset profile has unsupported payload type: %s", preset_path)
            return session_payload

        merged = {**preset_data, **session_payload}
        return merged

    def _send_log_path(self, state: dict[str, Any]) -> Path:
        session_dir = self._session_dir(state["session_id"])
        log_root = _to_abs(settings.log_upload_dir)
        log_root.mkdir(parents=True, exist_ok=True)
        return log_root / f"send_log_{session_dir.name}.json"

    def _send_result_payload(
        self,
        *,
        ok: bool,
        message: str,
        log_file: Path,
        request_url: str = "",
        connection_string: str = "",
        response_status: int | None = None,
        response_text: str = "",
        error_type: str = "",
        elapsed_seconds: float | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": ok,
            "status": "success" if ok else "error",
            "message": message,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "log_file": str(log_file),
        }
        if request_url:
            result["request_url"] = request_url
        if connection_string:
            result["connection_string"] = connection_string
        if response_status is not None:
            result["response_status"] = response_status
        if response_text:
            result["response_text"] = response_text[:1000]
        if error_type:
            result["error_type"] = error_type
        if elapsed_seconds is not None:
            result["elapsed_time_seconds"] = round(elapsed_seconds, 2)
        return result

    async def _export_to_1c(self, state: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        session_payload = self._compose_export_json(state)
        payload = self._merge_preset_and_session_json(state, session_payload)
        state["final_payload"] = payload
        session_dir = self._session_dir(state["session_id"])
        export_file = session_dir / f"{session_dir.name}.json"
        _safe_dump_json(export_file, payload)
        log_file = self._send_log_path(state)
        profile = state.get("profile") if isinstance(state.get("profile"), dict) else {}
        user_id = str(profile.get("BitrixID") or profile.get("TelegramID") or state.get("selected_user") or "")
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": user_id,
            "folder_path": str(session_dir),
            "source_file": str(export_file),
            "status": "initialized",
            "details": {},
        }
        _safe_dump_json(log_file, log_entry)

        username = (settings.admin_username or "").strip()
        password = (settings.admin_password or "").strip()
        if not username or not password:
            log_entry.update({
                "status": "error",
                "error_type": "missing_credentials",
                "error_message": "Не заданы ADMIN_USERNAME/ADMIN_PASSWORD",
            })
            _safe_dump_json(log_file, log_entry)
            message = "Не заданы ADMIN_USERNAME/ADMIN_PASSWORD"
            return False, message, self._send_result_payload(
                ok=False,
                message=message,
                log_file=log_file,
                error_type="missing_credentials",
            )

        connection_string = str(payload.get("ConnectionString", "") or "")
        endpoint_base = (settings.base_test or "").strip() if ("TEST" in connection_string.upper() and (settings.base_test or "").strip()) else (settings.base_url or "").strip()
        url = _normalize_exchange_ai_url(endpoint_base)
        if not url:
            log_entry.update({
                "status": "error",
                "error_type": "missing_url",
                "error_message": "Не задан BASE_URL/BASE_TEST",
            })
            _safe_dump_json(log_file, log_entry)
            message = "Не задан BASE_URL/BASE_TEST"
            return False, message, self._send_result_payload(
                ok=False,
                message=message,
                log_file=log_file,
                connection_string=connection_string,
                error_type="missing_url",
            )

        auth_raw = f"{username}:{password}".encode("utf-8")
        headers = {
            "Authorization": f"Basic {base64.b64encode(auth_raw).decode('utf-8')}",
            "Content-Type": "application/json",
        }
        try:
            start_time = time.time()
            response = await _run_in_thread(
                requests.post,
                url,
                headers=headers,
                json=payload,
                verify=False,
                timeout=400,
            )
            elapsed = time.time() - start_time
            response.raise_for_status()
            log_entry.update({
                "request_url": url,
                "connection_string": connection_string,
                "response_status": int(response.status_code),
                "response_text": response.text[:1000] if len(response.text) > 1000 else response.text,
                "response_text_full_length": len(response.text),
                "sent_data_size": len(str(payload)),
                "sent_data_size_mb": round(len(str(payload)) / (1024 * 1024), 2),
                "images_count": len(payload.get("images", [])) if isinstance(payload.get("images"), list) else 0,
                "request_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "elapsed_time_seconds": round(elapsed, 2),
                "elapsed_time_minutes": round(elapsed / 60, 2),
            })
            try:
                body = response.json()
            except Exception:
                body = {}
            is_ok = bool(body.get("Успех")) or (isinstance(body.get("trace_data"), dict) and body["trace_data"].get("Result") == "Ок!") or (
                "timestemp" in body and isinstance(body.get("Result"), dict)
            )
            if not is_ok:
                message = f"1C отклонил данные: {response.text[:500]}"
                log_entry.update({
                    "status": "error",
                    "error_type": "server_rejected",
                    "error_message": message,
                })
                _safe_dump_json(log_file, log_entry)
                return False, message, self._send_result_payload(
                    ok=False,
                    message=message,
                    log_file=log_file,
                    request_url=url,
                    connection_string=connection_string,
                    response_status=int(response.status_code),
                    response_text=response.text,
                    error_type="server_rejected",
                    elapsed_seconds=elapsed,
                )
            payload["sent"] = True
            _safe_dump_json(export_file, payload)
            log_entry["status"] = "success"
            _safe_dump_json(log_file, log_entry)
            message = "Данные успешно отправлены в 1С"
            return True, message, self._send_result_payload(
                ok=True,
                message=message,
                log_file=log_file,
                request_url=url,
                connection_string=connection_string,
                response_status=int(response.status_code),
                response_text=response.text,
                elapsed_seconds=elapsed,
            )
        except Exception as exc:
            logger.exception("1C send failed")
            message = str(exc)
            log_entry.update({
                "status": "error",
                "error_type": "request_exception",
                "error_message": message,
                "traceback": traceback.format_exc(),
            })
            _safe_dump_json(log_file, log_entry)
            return False, message, self._send_result_payload(
                ok=False,
                message=message,
                log_file=log_file,
                request_url=url,
                connection_string=connection_string,
                error_type="request_exception",
            )

    def resolve_session_file(self, session_id: str, file_name: str) -> Path:
        base = self._uploads_dir(session_id).resolve()
        target = (base / file_name).resolve()
        if target.parent != base:
            raise ValueError("invalid_file_name")
        if not target.exists():
            raise FileNotFoundError(file_name)
        return target
