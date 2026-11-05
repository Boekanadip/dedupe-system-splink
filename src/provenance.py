"""Utility functions for pipeline provenance metadata.

Used by export and sync scripts to ensure every export / snapshot carries
the same canonical metadata fields.

Example usage:

    from src.provenance import current_run_info
    meta = current_run_info()
    print(meta)
    # {'model_version': 'v0.1.2+20240827',
    #  'pipeline_run_id': 'run-20261104T023000Z', 'source_scope': 'full',
    #  'exported_at': '2026-11-04T02:30:00Z'}
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import json

from src.config import (
    MASTER_PATH,
    ENTITY_MAP_PATH,
    PREDICTIONS_FULL_PATH,
    read_meta,
    scope_of,
)
from src.model_lifecycle import latest


def model_version() -> str | None:
    """Ambil model_version dari meta artefak atau latest run."""

    meta = read_meta(MASTER_PATH)
    if meta and meta.get("model_version"):
        return str(meta["model_version"])
    v = latest()
    return v.name if v else None


def source_scope() -> str:
    """Ambil scope ('sample' atau 'full') dari meta artefak atau default."""

    meta = read_meta(MASTER_PATH)
    if meta and meta.get("scope"):
        return str(meta["scope"])
    return scope_of(full=False)


def current_run_info() -> dict[str, str | None]:
    """Membangun dictionary metadata pipeline untuk satu eksport / snapshot."""

    now = datetime.now(timezone.utc)
    return {
        "model_version": model_version(),
        "pipeline_run_id": f"run-{now:%Y%m%dT%H%M%SZ}",
        "source_scope": source_scope(),
        "exported_at": now.isoformat(timespec="seconds"),
    }


def write_export_meta(csv_path: Path | None = None) -> dict:
    """Return metadata dict; optionally write sampingan metadata JSON untuk CSV."""

    meta = current_run_info()
    if csv_path is not None:
        meta_path = Path(csv_path).with_name(Path(csv_path).stem + ".meta.json")
        meta_path.write_text(
            json.dumps(meta, indent=2, default=str),
            encoding="utf-8",
        )
    return meta
