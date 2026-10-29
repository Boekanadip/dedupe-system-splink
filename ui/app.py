"""Streamlit dashboard for CRM entity resolution."""
import os
import streamlit as st
import requests
import pandas as pd
from pathlib import Path

# Configuration
API_URL = os.environ.get("API_URL", "http://localhost:8000")

# Paths
PROJECT_DIR = Path(__file__).parent.parent
PREDICTIONS_PATH = PROJECT_DIR / "outputs" / "splink_predictions.parquet"

st.set_page_config(page_title="CRM Entity Resolution Dashboard", layout="wide")

# Load local predictions if available
_predictions_df = None

def get_local_predictions():
    global _predictions_df
    if _predictions_df is None and PREDICTIONS_PATH.exists():
        _predictions_df = pd.read_parquet(PREDICTIONS_PATH)
    return _predictions_df


def fetch_api_data(endpoint):
    """Fetch data from FastAPI."""
    try:
        response = requests.get(f"{API_URL}{endpoint}", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None


st.title("CRM Entity Resolution Dashboard")

# Sidebar
st.sidebar.header("Navigation")
page = st.sidebar.radio("Page", ["Overview", "Review Queue", "Pair Explorer", "Model Info"])

# Overview Page
if page == "Overview":
    st.header("Overview")
    
    col1, col2, col3 = st.columns(3)
    
    # Stats from API or local
    api_stats = fetch_api_data("/api/stats")
    
    if api_stats:
        total = api_stats.get("total_pairs", 0)
        matches = api_stats.get("matches", 0)
        review = api_stats.get("review", 0)
        non_matches = api_stats.get("non_matches", 0)
    else:
        df = get_local_predictions()
        if df is not None:
            total = len(df)
            matches = len(df[df["decision"] == "MATCH"])
            review = len(df[df["decision"] == "REVIEW"])
            non_matches = len(df[df["decision"] == "NON_MATCH"])
        else:
            total = matches = review = non_matches = 0
    
    with col1:
        st.metric("Total Pairs", total)
    with col2:
        st.metric("Matches", matches, delta_color="normal")
    with col3:
        st.metric("Review Required", review, delta_color="inverse")
    
    st.metric("Non-Matches (Auto-Rejected)", non_matches)
    
    # Probability distribution
    st.subheader("Match Probability Distribution")
    
    df = get_local_predictions()
    if df is not None:
        prob = df["match_probability"]
        
        # Create histogram data
        import plotly.express as px
        fig = px.histogram(
            df,
            x="match_probability",
            nbins=50,
            title="Match Probability Distribution",
            labels={"match_probability": "Probability", "count": "Count"}
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Decision summary
        st.subheader("Decision Summary")
        decision_counts = df["decision"].value_counts()
        st.bar_chart(decision_counts)

# Review Queue Page
elif page == "Review Queue":
    st.header("Review Queue")
    
    api_pairs = fetch_api_data("/api/pairs?status=REVIEW&page=1&per_page=50")
    
    if api_pairs and "pairs" in api_pairs:
        pairs = api_pairs["pairs"]
        st.write(f"Found {len(pairs)} pairs for review")
        
        for i, pair in enumerate(pairs[:10]):
            with st.expander(f"Pair {i+1}: {pair['record_id_l']} ↔ {pair['record_id_r']} (Prob: {pair['match_probability']:.3f})"):
                st.info(f"Probability: {pair['match_probability']:.4f}")
                st.info(f"Decision: {pair['decision']}")
    
    else:
        st.warning("No REVIEW pairs found or API not accessible")

# Pair Explorer Page
elif page == "Pair Explorer":
    st.header("Pair Explorer")
    
    search_id = st.text_input("Search Record ID")
    
    if search_id:
        api_result = fetch_api_data(f"/api/search?q={search_id}")
        
        if api_result and "results" in api_result:
            results = api_result["results"]
            st.write(f"Found {len(results)} results")
            
            for pair in results[:10]:
                col1, col2 = st.columns([1, 3])
                with col1:
                    st.metric("Prob", f"{pair['match_probability']:.4f}")
                with col2:
                    st.write(f"{pair['record_id_l']} ↔ {pair['record_id_r']}")
                    stbadge = "✅ MATCH" if pair['decision'] == "MATCH" else ("⚠️ REVIEW" if pair['decision'] == "REVIEW" else "❌ NON_MATCH")
                    st.write(f"Status: {stbadge}")
    
    else:
        st.info("Enter a record ID to search")

# Model Info Page
elif page == "Model Info":
    st.header("Model Information")
    
    st.subheader("Current Model Version")
    st.code("v20261027_161903", language="text")
    
    st.subheader("Threshold Configuration")
    st.json({
        "auto_match": ">= 0.84",
        "review": "0.35 - 0.84",
        "auto_non_match": "< 0.35"
    })
    
    st.subheader("Evaluation Results (Threshold 0.86)")
    st.json({
        "Recall": "0.9886",
        "Precision": "0.9263",
        "F1 Score": "0.9564"
    })
    
    st.subheader("Blocking Rules")
    rules = [
        "first_name + last_name + email",
        "first_name + last_name + phone",
        "first_name + last_name + city + state",
        "email_domain + city + state + dob",
        "phone_last4 + city + state + dob",
        "first_name + last_name + city",
        "first_name + email + phone",
        "last_name + email + phone",
        "email + phone + city",
        "first_name + last_name + dob",
        "email_domain + phone_last4",
        "city + state + dob",
        "phone_last4 + dob",
        "first_name + last_name + email_domain"
    ]
    st.write(f"Total: {len(rules)} rules")
    for i, rule in enumerate(rules[:5]):
        st.code(f"{i+1}. {rule}", language="text")

st.sidebar.markdown("---")
st.sidebar.info("CRM Entity Resolution System v1.0")
