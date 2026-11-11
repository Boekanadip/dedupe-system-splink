"""PostgreSQL storage for the active manual-review queue."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd

TABLE = "splink_data.review_queue_records"


def _csv_path():
    from .config import LABELS_DIR

    return LABELS_DIR / "review_queue.csv"


def _mirror_csv(frame: pd.DataFrame) -> None:
    """Keep review_queue.csv as the export/legacy mirror of the DB queue."""
    path = _csv_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        current = pd.read_csv(path) if path.exists() else pd.DataFrame()
        combined = pd.concat([current, frame], ignore_index=True) if not current.empty else frame
        combined = combined.drop_duplicates(subset=["record_id_l", "record_id_r"], keep="last")
        combined.to_csv(path, index=False)
    except Exception:
        # Mirror failure must never block the authoritative DB write.
        pass


def _mirror_decision(frame: pd.DataFrame) -> None:
    path = _csv_path()
    if not path.exists():
        return
    try:
        current = pd.read_csv(path)
        for col in ("label", "reviewer", "reviewer_note", "review_status"):
            if col in current.columns:
                current[col] = current[col].astype(object)
        for row in frame.to_dict("records"):
            mask = (current["record_id_l"].astype(str) == str(row["record_id_l"])) & (
                current["record_id_r"].astype(str) == str(row["record_id_r"])
            )
            label = row.get("label") or None
            current.loc[mask, "label"] = label
            current.loc[mask, "reviewer"] = row.get("reviewer") or None
            current.loc[mask, "reviewer_note"] = row.get("reviewer_note") or None
            current.loc[mask, "review_status"] = "reviewed" if label else "pending"
        current.to_csv(path, index=False)
    except Exception:
        pass


def _connect():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB", "crm"),
        user=os.getenv("POSTGRES_USER", "crm_user"),
        password=os.getenv("POSTGRES_PASSWORD", "crm_password_2026"),
    )


def ensure_table() -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                review_id BIGSERIAL PRIMARY KEY,
                record_id_l VARCHAR(255) NOT NULL,
                record_id_r VARCHAR(255) NOT NULL,
                stratum VARCHAR(100) NOT NULL DEFAULT 'manual_review',
                match_probability DOUBLE PRECISION,
                evidence JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                label VARCHAR(20),
                review_status VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (review_status IN ('pending', 'in_review', 'reviewed')),
                reviewer VARCHAR(255),
                reviewer_note TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMPTZ,
                UNIQUE(record_id_l, record_id_r)
            )
        """)
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_review_records_status ON {TABLE}(review_status)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_review_records_probability ON {TABLE}(match_probability)")


def _row_to_dict(row, columns):
    item = dict(zip(columns, row))
    evidence = item.pop("evidence") or {}
    item.update(evidence)
    return item


def load_queue() -> pd.DataFrame:
    ensure_table()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT review_id, record_id_l, record_id_r, stratum, match_probability, evidence, label, review_status, reviewer, reviewer_note, updated_at FROM {TABLE} ORDER BY match_probability DESC NULLS LAST, review_id")
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description]
    df = pd.DataFrame([_row_to_dict(row, columns) for row in rows])
    if not df.empty:
        df = df.sort_values("review_id").drop_duplicates(
            subset=["record_id_l", "record_id_r"], keep="last"
        ).reset_index(drop=True)
    return df


AGREE_COLS = ["agree_email", "agree_phone", "agree_dob", "agree_name", "agree_city"]


def upsert_queue(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    ensure_table()
    frame = frame.copy()
    for col in AGREE_COLS:
        if col not in frame.columns:
            frame[col] = False
    frame["agree_count"] = frame[AGREE_COLS].fillna(False).sum(axis=1)
    base = {"record_id_l", "record_id_r", "stratum", "match_probability", "label", "review_status", "reviewer", "reviewer_note"}
    evidence_cols = [c for c in frame.columns if c not in base]
    frame[["record_id_l", "record_id_r"]] = frame[["record_id_l", "record_id_r"]].astype(str)
    for index, row in frame.iterrows():
        if row["record_id_l"] > row["record_id_r"]:
            frame.at[index, "record_id_l"], frame.at[index, "record_id_r"] = row["record_id_r"], row["record_id_l"]
            for column in frame.columns:
                if column.endswith("_l"):
                    other = column[:-2] + "_r"
                    if other in frame.columns:
                        frame.at[index, column], frame.at[index, other] = row[other], row[column]
    frame = frame.drop_duplicates(subset=["record_id_l", "record_id_r"], keep="last")
    with _connect() as conn, conn.cursor() as cur:
        for row in frame.to_dict("records"):
            evidence = {c: (None if pd.isna(row.get(c)) else row.get(c)) for c in evidence_cols}
            cur.execute(f"""
                INSERT INTO {TABLE} (record_id_l, record_id_r, stratum, match_probability, evidence, label, review_status, reviewer, reviewer_note)
                VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)
                ON CONFLICT (record_id_l, record_id_r) DO UPDATE SET
                  stratum=EXCLUDED.stratum, match_probability=EXCLUDED.match_probability,
                  evidence=EXCLUDED.evidence,
                  updated_at=CURRENT_TIMESTAMP
            """, (str(row["record_id_l"]), str(row["record_id_r"]), row.get("stratum") or "manual_review",
                  None if pd.isna(row.get("match_probability")) else float(row["match_probability"]),
                  json.dumps(evidence, default=str), row.get("label") or None,
                  row.get("review_status") or "pending", row.get("reviewer") or None,
                  row.get("reviewer_note") or None))
    _mirror_csv(frame)
    return len(frame)


def update_decisions(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    ensure_table()
    frame = frame.copy()
    frame[["record_id_l", "record_id_r"]] = frame[["record_id_l", "record_id_r"]].astype(str)
    for index, row in frame.iterrows():
        if row["record_id_l"] > row["record_id_r"]:
            frame.at[index, "record_id_l"], frame.at[index, "record_id_r"] = row["record_id_r"], row["record_id_l"]
            for column in frame.columns:
                if column.endswith("_l"):
                    other = column[:-2] + "_r"
                    if other in frame.columns:
                        frame.at[index, column], frame.at[index, other] = row[other], row[column]
    frame = frame.drop_duplicates(subset=["record_id_l", "record_id_r"], keep="last")
    count = 0
    with _connect() as conn, conn.cursor() as cur:
        for row in frame.to_dict("records"):
            label = row.get("label") or None
            status = "reviewed" if label else "pending"
            cur.execute(f"""UPDATE {TABLE} SET label=%s, reviewer=%s, reviewer_note=%s,
                review_status=%s, reviewed_at=%s, updated_at=CURRENT_TIMESTAMP
                WHERE record_id_l=%s AND record_id_r=%s""",
                (label, row.get("reviewer") or None, row.get("reviewer_note") or None,
                 status, datetime.now(timezone.utc) if label else None,
                 str(row["record_id_l"]), str(row["record_id_r"])))
            count += cur.rowcount
    _mirror_decision(frame)
    return count
