from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.flow_engine import FlowEngine


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _iter_rows_from_file(path: Path) -> list[dict[str, Any]]:
    try:
        payload = _load_json(path)
    except Exception:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def build_index(atwork_dir: Path) -> dict[str, Any]:
    by_telegram: dict[str, list[dict[str, Any]]] = {}
    by_telegram_uid_base: dict[str, dict[str, Any]] = {}
    files_meta: dict[str, dict[str, Any]] = {}

    for file in sorted(atwork_dir.glob("*.json")):
        stat = file.stat()
        files_meta[file.name] = {
            "size": int(stat.st_size),
            "mtime": int(stat.st_mtime),
        }
        rows = _iter_rows_from_file(file)
        for idx, row in enumerate(rows):
            tid = str(row.get("TelegramID", "") or "").strip()
            if not tid:
                continue
            uid = str(row.get("UID", "") or "").strip()
            base_name = str(row.get("BaseName", "") or "").strip()
            name = str(row.get("Name", "") or "").strip()

            item = {
                "uid": uid,
                "base_name": base_name,
                "name": name,
                "file": file.name,
                "row_index": idx,
            }
            by_telegram.setdefault(tid, []).append(item)

            if uid and base_name:
                key = f"{tid}|{uid}|{base_name.casefold()}"
                by_telegram_uid_base[key] = {
                    "file": file.name,
                    "row_index": idx,
                }

    for tid in by_telegram:
        by_telegram[tid].sort(key=lambda x: (x["base_name"].casefold(), x["uid"]))

    return {
        "version": 1,
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files_meta,
        "by_telegram": by_telegram,
        "by_telegram_uid_base": by_telegram_uid_base,
    }


def find_profile_by_index(
    index_data: dict[str, Any],
    atwork_dir: Path,
    telegram_id: str,
    preferred_name: str | None = None,
) -> dict[str, Any] | None:
    tid = str(telegram_id or "").strip()
    if not tid:
        return None

    entries = list(index_data.get("by_telegram", {}).get(tid, []))
    if not entries:
        return None

    if preferred_name:
        target = preferred_name.strip().casefold()
        for e in entries:
            if str(e.get("name", "")).strip().casefold() == target:
                entries = [e]
                break

    chosen = entries[0]
    file_name = str(chosen.get("file", "") or "")
    row_idx = int(chosen.get("row_index", 0) or 0)
    if not file_name:
        return None

    rows = _iter_rows_from_file(atwork_dir / file_name)
    if row_idx < 0 or row_idx >= len(rows):
        return None
    return rows[row_idx]


async def run_benchmark(telegram_id: str, preferred_name: str | None, skip_s3: bool) -> int:
    engine = FlowEngine()
    atwork_dir = engine.paths.atwork_root
    index_path = atwork_dir / ".index_telegram.json"

    t0 = time.perf_counter()

    sync_error: str | None = None
    downloaded: list[str] = []
    t_sync_start = time.perf_counter()
    if not skip_s3:
        try:
            downloaded = await engine._sync_user_from_s3(telegram_id)  # noqa: SLF001 (benchmark helper)
        except Exception as exc:
            sync_error = str(exc)
    t_sync_end = time.perf_counter()

    t_index_start = time.perf_counter()
    index_data = build_index(atwork_dir)
    _dump_json(index_path, index_data)
    t_index_end = time.perf_counter()

    t_lookup_start = time.perf_counter()
    profile = find_profile_by_index(index_data, atwork_dir, telegram_id, preferred_name)
    t_lookup_end = time.perf_counter()

    t1 = time.perf_counter()

    entries = index_data.get("by_telegram", {}).get(telegram_id, [])
    print("=== INDEX START BENCHMARK ===")
    print(f"TelegramID: {telegram_id}")
    if preferred_name:
        print(f"Preferred Name: {preferred_name}")
    print(f"S3 sync enabled: {not skip_s3}")
    print(f"S3 downloaded files: {len(downloaded)}")
    if sync_error:
        print(f"S3 sync error: {sync_error}")
    print(f"Index path: {index_path}")
    print(f"Files indexed: {len(index_data.get('files', {}))}")
    print(f"Entries for TelegramID: {len(entries)}")
    print(f"User found: {bool(profile)}")
    if profile:
        print(
            "Selected profile: "
            f"{profile.get('Name', '')} | UID={profile.get('UID', '')} | Base={profile.get('BaseName', '')}"
        )
    print("--- Timings ---")
    print(f"S3 sync: {(t_sync_end - t_sync_start):.3f}s")
    print(f"Build+save index: {(t_index_end - t_index_start):.3f}s")
    print(f"Lookup by index: {(t_lookup_end - t_lookup_start):.6f}s")
    print(f"TOTAL: {(t1 - t0):.3f}s")

    return 0 if profile else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build AtWork index and benchmark user lookup/start bootstrap time."
    )
    parser.add_argument("--telegram-id", default="1657181189", help="TelegramID to simulate flow start")
    parser.add_argument("--name", default="Титов Михаил Сергеевич", help="Optional preferred user full name")
    parser.add_argument(
        "--skip-s3",
        action="store_true",
        help="Skip S3 refresh step and benchmark local index only",
    )
    args = parser.parse_args()

    return asyncio.run(run_benchmark(args.telegram_id, args.name, args.skip_s3))


if __name__ == "__main__":
    raise SystemExit(main())
