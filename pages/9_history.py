"""Decision history per kandidat: feedback + overrides + queue labels + entity corrections.

Cari pasangan atau record → tampilkan semua keputusan/model yang pernah
menyentuhnya: feedback (human), overrides (apply_gold), queue (review),
entity_correction (split/merge). Sebagai 'riwayat keputusan per kandidat'
(Rank 3) dan 'entity lifecycle visibility' (Rank 4).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import LABELS_DIR, OUTPUT_DIR, predictions_path
from src.labels import QUEUE_PATH, GOLD_PATH
from src.ui import monitoring_sidebar, page_guide, page_header

st.set_page_config(page_title="Riwayat - Entity Resolution", page_icon="📜", layout="wide")
page_header(
    "Riwayat Keputusan",
    "Catatan siapa mengubah apa dan kapan. Dipakai untuk menelusuri kembali "
    "kenapa seorang customer digabung atau dipisah.",
)
monitoring_sidebar()
page_guide(__file__)

# ---- search
c1, c2 = st.columns(2)
search_rid = c1.text_input("Record ID (misal rec_000123)", "")
search_pair = c2.text_input("Pair ID (misal rec_000123__rec_000456)", "")

def load_all():
    """Load all audit sources once."""
    data = {}
    fb = LABELS_DIR / "feedback.csv"
    if fb.exists():
        data["feedback"] = pd.read_csv(fb)
    ov = OUTPUT_DIR / "human_overrides.jsonl"
    if ov.exists():
        try:
            data["overrides"] = pd.read_json(ov, lines=True)
        except ValueError:
            pass
    if QUEUE_PATH.exists():
        try:
            q = pd.read_csv(QUEUE_PATH)
            if not q.empty:
                q["pair_id"] = q.apply(
                    lambda r: f"{min(str(r.record_id_l), str(r.record_id_r))}__{max(str(r.record_id_l), str(r.record_id_r))}", axis=1
                )
                data["queue"] = q
        except Exception:
            pass
    if GOLD_PATH.exists():
        try:
            g = pd.read_csv(GOLD_PATH, sep=None, engine="python")
            if not g.empty:
                g["pair_id"] = g.apply(
                    lambda r: f"{min(str(r.record_id_l), str(r.record_id_r))}__{max(str(r.record_id_l), str(r.record_id_r))}", axis=1
                )
                data["gold"] = g
        except Exception:
            pass
    eh = OUTPUT_DIR / "entity_history.jsonl"
    if eh.exists():
        try:
            data["entity_hist"] = pd.read_json(eh, lines=True)
        except ValueError:
            pass
    return data

d = load_all()

def pair_id(l, r):
    return f"{min(l, r)}__{max(l, r)}"

# ---- per-pair timeline
if search_pair:
    pid = search_pair.strip()
    st.subheader(f"Timeline untuk pasangan {pid}")
    cols = st.columns(4)
    for name, df in d.items():
        if "pair_id" in df.columns:
            hit = df[df["pair_id"] == pid]
            if not hit.empty:
                with cols[list(d.keys()).index(name) % 4]:
                    st.write(f"**{name}**")
                    st.dataframe(hit.dropna(axis=1, how="all"), width="stretch", hide_index=True)

# ---- per-record timeline (record appears in any pair)
if search_rid:
    rid = search_rid.strip()
    st.subheader(f"Timeline untuk record {rid}")
    all_pairs = []
    # feedback
    if "feedback" in d:
        fb = d["feedback"]
        hit = fb[(fb.record_id_l == rid) | (fb.record_id_r == rid)].copy()
        if not hit.empty:
            hit["source"] = "feedback"
            all_pairs.append(hit)
    # overrides
    if "overrides" in d:
        ov = d["overrides"]
        hit = ov[
            (ov.record_id_l == rid) | (ov.record_id_r == rid)
        ].copy()
        if not hit.empty:
            hit["source"] = "overrides"
            all_pairs.append(hit)
    # queue
    if "queue" in d:
        q = d["queue"]
        hit = q[(q.record_id_l == rid) | (q.record_id_r == rid)].copy()
        if not hit.empty:
            hit["source"] = "queue"
            all_pairs.append(hit)
    # gold
    if "gold" in d:
        g = d["gold"]
        hit = g[(g.record_id_l == rid) | (g.record_id_r == rid)].copy()
        if not hit.empty:
            hit["source"] = "gold"
            all_pairs.append(hit)
    # entity history
    if "entity_hist" in d:
        eh = d["entity_hist"]
        # entity_hist has records list
        hit = eh[eh.records.apply(lambda r: rid in r if isinstance(r, list) else False)].copy()
        if not hit.empty:
            hit["source"] = "entity_hist"
            all_pairs.append(hit)

    if all_pairs:
        combined = pd.concat(all_pairs, ignore_index=True, sort=False)
        combined = combined.sort_values(
            by=[c for c in ["timestamp", "match_probability"] if c in combined.columns],
            ascending=False,
            na_position="last",
        )
        st.dataframe(combined.dropna(axis=1, how="all"), width="stretch", hide_index=True)
    else:
        st.info("Tidak ada jejak untuk record ini.")

# ---- entity history filter
st.divider()
st.subheader("Entity Correction History")
if "entity_hist" in d:
    eh = d["entity_hist"]
    ents = sorted(set().union(*eh.from_entity.dropna()) | set().union(*eh.to_entity.dropna()))
    ent_filter = st.selectbox("Filter entity", ["(semua)"] + ents)
    if ent_filter != "(semua)":
        eh = eh[(eh.from_entity == ent_filter) | (eh.to_entity == ent_filter)]
    st.dataframe(eh.sort_values("timestamp", ascending=False).dropna(axis=1, how="all"),
                 width="stretch", hide_index=True)
else:
    st.caption("Belum ada koreksi entity (entity_correction).")