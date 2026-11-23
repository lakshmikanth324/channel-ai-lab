import sqlite3

import pytest

from src.matching.normalization import normalize_product_name
from src.matching.product_matcher import ProductMatcher


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "channel_ai_lab.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE products ("
            "product_id TEXT PRIMARY KEY, "
            "product_code TEXT, "
            "product_name TEXT)"
        )
        connection.executemany(
            "INSERT INTO products VALUES (?, ?, ?)",
            [("p1", "ABC-123", "Synthetic Pro"), ("p2", "XYZ-789", "Herbal Blend")],
        )
        connection.execute(
            "CREATE TABLE pos_records ("
            "pos_product_code TEXT, "
            "pos_product_name TEXT)"
        )
        connection.executemany(
            "INSERT INTO pos_records VALUES (?, ?)",
            [
                ("ABC-123", "Unrelated Name"),
                (None, "SYNTH.  PRO"),
                ("UNKNOWN", "Totally Missing"),
            ],
        )
    return path


def test_normalization_handles_case_abbreviation_and_punctuation():
    assert normalize_product_name("Synth.  Pro!") == "synthetic pro"


def test_exact_code_match(database):
    matcher = ProductMatcher(str(database))
    result = matcher.match_all()

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT matched_product_id, match_method, review_status "
            "FROM pos_records WHERE pos_product_code = 'ABC-123'"
        ).fetchone()

    assert row == ("p1", "exact_code", "matched")
    assert result["matched"] >= 1


def test_normalized_name_match(database):
    matcher = ProductMatcher(str(database))
    matcher.match_all()

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT matched_product_id, match_method "
            "FROM pos_records WHERE pos_product_code IS NULL"
        ).fetchone()

    assert row == ("p1", "exact_normalized_name")


def test_unknown_code_and_name_is_pending(database):
    matcher = ProductMatcher(str(database))
    result = matcher.match_all()

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT matched_product_id, match_method, review_status "
            "FROM pos_records WHERE pos_product_code = 'UNKNOWN'"
        ).fetchone()

    assert row == (None, None, "pending")
    assert result["pending"] >= 1
