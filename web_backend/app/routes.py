from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Body, File, Form, HTTPException, Path, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .flow_engine import FlowEngine
from .settings import settings


router = APIRouter()
flow_engine = FlowEngine()


class FlowActionRequest(BaseModel):
    action: str
    payload: dict[str, Any] | None = None


def _normalize_error(payload: dict[str, Any] | None, fallback: str) -> str:
    if not isinstance(payload, dict):
        return fallback
    err = payload.get('error')
    if err in (None, '', 'null'):
        return fallback
    return str(err)


async def _forward_multipart(url: str, image: UploadFile, data: dict[str, Any] | None = None) -> dict[str, Any]:
    image_bytes = await image.read()
    files = {'image': (image.filename or 'upload.jpg', image_bytes, image.content_type or 'image/jpeg')}

    timeout = httpx.Timeout(settings.upstream_timeout_sec)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, files=files, data=data or {})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=502, detail=f'upstream_bad_status: {exc.response.status_code}') from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail='upstream_unavailable') from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail='upstream_invalid_json') from exc


@router.get('/health')
def api_health() -> dict[str, str]:
    return {'status': 'ok'}


@router.post('/car-number/recognize')
async def recognize_car_number(image: UploadFile = File(...)) -> dict[str, Any]:
    payload = await _forward_multipart(settings.car_number_api_url, image)
    return {
        'success': bool(payload.get('found', False)),
        'number': str(payload.get('number', '') or ''),
        'confidence': float(payload.get('confidence', 0.0) or 0.0),
        'error': None if payload.get('found') else _normalize_error(payload, 'car_number_not_found'),
        'raw_result': str(payload.get('raw_result', '') or ''),
        'upstream': payload,
    }


@router.post('/tire-number/recognize')
async def recognize_tire_number(image: UploadFile = File(...)) -> dict[str, Any]:
    payload = await _forward_multipart(settings.tire_number_api_url, image)
    return {
        'success': bool(payload.get('found', False)),
        'number': str(payload.get('number', '') or ''),
        'confidence': float(payload.get('confidence', 0.0) or 0.0),
        'error': None if payload.get('found') else _normalize_error(payload, 'tire_number_not_found'),
        'upstream': payload,
    }


@router.post('/tire-analysis/analyze')
async def analyze_tire(
    image: UploadFile = File(...),
    mode: str = Form('quality'),
) -> dict[str, Any]:
    if mode not in {'quality', 'season_spikes', 'full'}:
        raise HTTPException(status_code=400, detail='invalid_mode')

    payload = await _forward_multipart(settings.tire_analysis_api_url, image, data={'mode': mode})
    quality = payload.get('quality') if isinstance(payload.get('quality'), dict) else None
    return {
        'success': bool(payload.get('success', False)),
        'mode': str(payload.get('mode', mode)),
        'error': payload.get('error'),
        'quality': quality,
        'classification': quality.get('classification') if quality else None,
        'score': quality.get('score') if quality else None,
        'season_spikes': payload.get('season_spikes'),
        'detection': payload.get('detection'),
    }


@router.post('/flow/start')
async def flow_start(body: Any = Body(default=None)) -> dict[str, Any]:
    profile: dict[str, Any] | None = None
    bitrix_id: str | None = None

    # Preferred format: {"BitrixID": "..."} (or {"bitrix_id": "..."}).
    # Legacy compatibility: {"TelegramID": "..."} / {"telegram_id": "..."}.
    if isinstance(body, dict):
        raw_bitrix_id = body.get("BitrixID")
        if raw_bitrix_id is None:
            raw_bitrix_id = body.get("bitrix_id")
        if raw_bitrix_id is None:
            raw_bitrix_id = body.get("TelegramID")
        if raw_bitrix_id is None:
            raw_bitrix_id = body.get("telegram_id")
        if raw_bitrix_id not in (None, ""):
            bitrix_id = str(raw_bitrix_id).strip()
        if isinstance(body.get("profile"), dict):
            profile = body["profile"]
            # Internal storage keeps TelegramID key for backward compatibility.
            if "TelegramID" not in profile and profile.get("BitrixID") not in (None, ""):
                profile["TelegramID"] = profile.get("BitrixID")
            if "BitrixID" not in profile and profile.get("TelegramID") not in (None, ""):
                profile["BitrixID"] = profile.get("TelegramID")
        # Compatibility: allow direct object payload with profile fields.
        elif any(k in body for k in ("UID", "Name", "BaseName", "ConnectionString")):
            profile = body
            if "TelegramID" not in profile and profile.get("BitrixID") not in (None, ""):
                profile["TelegramID"] = profile.get("BitrixID")
            if "BitrixID" not in profile and profile.get("TelegramID") not in (None, ""):
                profile["BitrixID"] = profile.get("TelegramID")
    # New format for Bitrix integration: [{...}] (use first profile).
    elif isinstance(body, list) and body:
        first = body[0]
        if isinstance(first, dict):
            profile = first
            if "TelegramID" not in profile and profile.get("BitrixID") not in (None, ""):
                profile["TelegramID"] = profile.get("BitrixID")
            if "BitrixID" not in profile and profile.get("TelegramID") not in (None, ""):
                profile["BitrixID"] = profile.get("TelegramID")

    return await flow_engine.start_flow(profile=profile, bitrix_id=bitrix_id)


@router.get('/flow/{session_id}')
async def flow_get(session_id: str = Path(..., min_length=4)) -> dict[str, Any]:
    try:
        return flow_engine.get_flow(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='session_not_found')
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'flow_get_failed: {exc}')


@router.post('/flow/{session_id}/action')
async def flow_action(
    session_id: str,
    body: FlowActionRequest,
) -> dict[str, Any]:
    try:
        return await flow_engine.apply_action(session_id, body.action, body.payload)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='session_not_found')
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'flow_action_failed: {exc}')


@router.post('/flow/{session_id}/upload')
async def flow_upload(
    session_id: str,
    image: UploadFile = File(...),
) -> dict[str, Any]:
    try:
        image_bytes = await image.read()
        return await flow_engine.upload(session_id, image_bytes, image.filename or 'upload.jpg')
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='session_not_found')
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'flow_upload_failed: {exc}')


@router.get('/demo/{file_name}')
async def demo_image(file_name: str):
    """Serve example/demo images from DEMO_img directory."""
    from pathlib import Path
    import re
    if not re.match(r'^[\w\-]+\.(jpg|jpeg|png)$', file_name, re.IGNORECASE):
        raise HTTPException(status_code=400, detail='invalid_file_name')
    from .flow_engine import _to_abs
    demo_dir = _to_abs(settings.demo_img_dir)
    path = demo_dir / file_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail='demo_image_not_found')
    return FileResponse(path=str(path))


@router.get('/flow/{session_id}/file/{file_name}')
async def flow_file(session_id: str, file_name: str):
    try:
        path = flow_engine.resolve_session_file(session_id, file_name)
        return FileResponse(path=str(path))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='file_not_found')
    except ValueError:
        raise HTTPException(status_code=400, detail='invalid_file_name')
