"Streamlit"
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Deduplication System", page_icon="🔗", layout="wide")

ROOT = Path(__file__).parent

page_defs = [
    ("upload", "pages/app_streamlit.py", "Upload", "📤"),
    ("review", "pages/1_review.py", "Review", "🔎"),
    ("master", "pages/2_master.py", "Master", "👥"),
    ("dashboard", "pages/3_dashboard.py", "Dashboard", "📊"),
    ("retrain", "pages/4_retrain.py", "Retrain", "⚙️"),
    ("queue", "pages/5_queue.py", "Queue", "📋"),
    ("batch", "pages/6_batch.py", "Batch", "📦"),
    ("gaps", "pages/7_gaps.py", "Gaps", "🕳️"),
    ("explain", "pages/8_explain.py", "Explain", "🔍"),
    ("history", "pages/9_history.py", "History", "📜"),
]
page_objects = {
    key: st.Page(path, title=title, icon=icon, default=(key == "upload"))
    for key, path, title, icon in page_defs
}
st.session_state["registered_pages"] = page_objects

pg = st.navigation(list(page_objects.values()), position="hidden")
pg.run()
