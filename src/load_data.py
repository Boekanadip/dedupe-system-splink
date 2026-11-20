"""Muat data untuk endpoint API /api/run-dedup."""
from pathlib import Path

import pandas as pd

from src.config import PROCESSED_DATA_PATH, RAW_DATA_PATH, SMOKE_SAMPLE_SIZE


def load_data(full: bool = False) -> pd.DataFrame:
    """Load data mentah sudah terstandarisasi dari outputs pipeline.

    Parameters
    ----------
    full : bool
        True → seluruh data processed. False → SMOKE_SAMPLE_SIZE baris pertama.
    """
    if not PROCESSED_DATA_PATH.exists():
        raise FileNotFoundError(
            f"Data processed tidak ditemukan: {PROCESSED_DATA_PATH}. "
            "Jalankan pipeline dari Upload Data terlebih dahulu."
        )
    df = pd.read_parquet(PROCESSED_DATA_PATH)
    if not full and len(df) > SMOKE_SAMPLE_SIZE:
        df = df.head(SMOKE_SAMPLE_SIZE).copy()
    return df.reset_index(drop=True)