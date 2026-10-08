"""Theo-specific views over host Settings."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from src.config import Settings, get_settings

_DEMO_BASE = "https://demo.trading212.com/api/v0"
_LIVE_BASE = "https://live.trading212.com/api/v0"


def parse_duration(raw: str, *, default: timedelta) -> timedelta:
    text = (raw or "").strip().lower()
    if not text:
        return default
    if text.endswith("h") and text[:-1].isdigit():
        return timedelta(hours=int(text[:-1]))
    if text.endswith("m") and text[:-1].isdigit():
        return timedelta(minutes=int(text[:-1]))
    if text.endswith("s") and text[:-1].isdigit():
        return timedelta(seconds=int(text[:-1]))
    if text.isdigit():
        return timedelta(hours=int(text))
    return default


def _whitelist_file(path_raw: str) -> Path | None:
    raw = Path(path_raw)
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent
    candidates = (
        raw,
        Path.cwd() / raw,
        backend_root / raw,
        backend_root / raw.name,
        backend_root / "config" / raw.name,
        repo_root / raw,
    )
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate
    return None


def parse_whitelist(settings: Settings | None = None) -> tuple[str, ...]:
    cfg = settings or get_settings()
    path_raw = cfg.theo_whitelist_path
    if path_raw:
        path = _whitelist_file(path_raw)
        if path is not None:
            lines = [
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            return tuple(lines)
    raw = (cfg.theo_whitelist or "").strip()
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def parse_symbol_overrides(settings: Settings | None = None) -> dict[str, str]:
    cfg = settings or get_settings()
    raw = (cfg.theo_symbol_overrides or "").strip()
    if not raw:
        return {}
    out: dict[str, str] = {}
    for part in raw.split(","):
        if ":" not in part:
            continue
        ticker, vendor = part.split(":", 1)
        ticker, vendor = ticker.strip(), vendor.strip()
        if ticker and vendor:
            out[ticker] = vendor
    return out


def t212_base_url(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    if cfg.t212_env == "live" and cfg.t212_live_enabled:
        return _LIVE_BASE
    return _DEMO_BASE


def t212_environment(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    if cfg.t212_env == "live" and cfg.t212_live_enabled:
        return "live"
    return "demo"


def attention_notional(settings: Settings | None = None) -> Decimal:
    cfg = settings or get_settings()
    return Decimal(str(cfg.theo_attention_notional).strip() or "10000")


def intent_ttl(settings: Settings | None = None) -> timedelta:
    cfg = settings or get_settings()
    return parse_duration(cfg.theo_intent_ttl, default=timedelta(hours=24))
