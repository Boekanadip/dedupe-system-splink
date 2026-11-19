"""Entrypoint alternatif: navigasi ke 10 halaman dashboard baru.

Jalankan: streamlit run app_baru.py
Tidak mengubah app.py maupun src/ui.py. Key navigasi dipertahankan agar
render_sidebar() yang memakai NAV_PAGES lama tetap bisa switch halaman.
"""
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Dashboard Baru - Entity Resolution", page_icon="📈", layout="wide")

ROOT = Path(__file__).parent

# Key sama seperti NAV_PAGES di src/ui.py, path diganti ke file *_baru.py
page_defs = [
    ("upload", "pages/10_upload_baru.py", "Upload (Baru)", "📤"),
    ("review", "pages/11_review_baru.py", "Review (Baru)", "🔎"),
    ("master", "pages/12_master_baru.py", "Master (Baru)", "👥"),
    ("dashboard", "pages/8_dashboard_baru.py", "Dashboard (Baru)", "📊"),
    ("retrain", "pages/13_retrain_baru.py", "Retrain (Baru)", "⚙️"),
    ("queue", "pages/14_queue_baru.py", "Queue (Baru)", "📋"),
    ("batch", "pages/15_batch_baru.py", "Batch (Baru)", "📦"),
    ("gaps", "pages/16_gaps_baru.py", "Gaps (Baru)", "🕳️"),
    ("explain", "pages/17_explain_baru.py", "Explain (Baru)", "🔍"),
    ("history", "pages/18_history_baru.py", "History (Baru)", "📜"),
]
page_objects = {
    key: st.Page(str(ROOT / path), title=title, icon=icon, default=(key == "dashboard"))
    for key, path, title, icon in page_defs
}
st.session_state["registered_pages"] = page_objects

pg = st.navigation(list(page_objects.values()), position="hidden")
pg.run()
