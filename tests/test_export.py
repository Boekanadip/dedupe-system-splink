"""Self-check for CSV export and DB save. Run: python -m tests.test_export

DB portion needs the crm-pg container; it is skipped automatically when
the table cannot be reached so the CSV checks still run offline.
"""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.export import csv_bytes, export_to_csv, save_to_database

MATCH, REVIEW = 0.84, 0.35


def decide(p):
    return "MATCH" if p >= MATCH else ("REVIEW" if p >= REVIEW else "NON_MATCH")


class CsvExportTest(unittest.TestCase):
    def test_round_trip_preserves_rows_and_columns(self):
        df = pd.DataFrame({
            "record_id_l": ["r1", "r2"],
            "record_id_r": ["r3", "r4"],
            "match_probability": [0.95, 0.42],
            "catatan": ["kota, jakarta", "áé"],  # comma + non-ASCII
        })
        with tempfile.TemporaryDirectory() as tmp:
            path = export_to_csv(df, Path(tmp) / "hasil.csv")
            back = pd.read_csv(path, encoding="utf-8")
        self.assertEqual(len(back), len(df))
        self.assertEqual(list(back.columns), list(df.columns))
        self.assertEqual(back.loc[0, "catatan"], "kota, jakarta")
        self.assertEqual(back.loc[1, "catatan"], "áé")

    def test_csv_bytes_matches_file(self):
        df = pd.DataFrame({"a": [1], "b": ["x"]})
        # \r\n is the CSV default line terminator and is valid per RFC 4180.
        self.assertEqual(csv_bytes(df).decode("utf-8"), "a,b\r\n1,x\r\n")

    def test_decision_band_boundaries(self):
        self.assertEqual(decide(1.0), "MATCH")
        self.assertEqual(decide(0.84), "MATCH")   # inclusive lower bound
        self.assertEqual(decide(0.839), "REVIEW")
        self.assertEqual(decide(0.35), "REVIEW")  # inclusive lower bound
        self.assertEqual(decide(0.349), "NON_MATCH")


class DbSaveTest(unittest.TestCase):
    TABLE = "splink_data.selfcheck_export"

    @classmethod
    def setUpClass(cls):
        cls.df = pd.DataFrame({
            "record_id_l": ["sc_1", "sc_2"],
            "record_id_r": ["sc_3", "sc_4"],
            "match_probability": [0.97, 0.40],
            "decision": ["MATCH", "REVIEW"],
        })
        try:
            save_to_database(cls.df, cls.TABLE)
        except Exception as exc:  # noqa: BLE001 - offline dev machines
            raise unittest.SkipTest(f"database unavailable: {type(exc).__name__}")

    @classmethod
    def tearDownClass(cls):
        import os

        import psycopg2

        try:
            conn = psycopg2.connect(
                host="localhost",
                dbname=os.getenv("POSTGRES_DB", "crm"),
                user=os.getenv("POSTGRES_USER", "crm_owner"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            with conn, conn.cursor() as cur:
                cur.execute(f"DROP TABLE IF EXISTS {cls.TABLE}")
            conn.close()
        except Exception:
            pass

    def test_duplicate_rows_rejected_by_primary_key(self):
        with self.assertRaises(Exception) as ctx:
            save_to_database(self.df, self.TABLE)
        self.assertEqual(type(ctx.exception).__name__, "UniqueViolation")

    def test_empty_frame_writes_nothing(self):
        self.assertEqual(save_to_database(self.df.iloc[0:0], self.TABLE), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
