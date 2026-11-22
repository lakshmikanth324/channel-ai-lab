from pathlib import Path

import pandas as pd

from src.data.generate_synthetic import generate_synthetic_data


def test_synthetic_data(tmp_path: Path) -> None:
    datasets = generate_synthetic_data(tmp_path)

    distributors = datasets["distributors.csv"]
    products = datasets["products.csv"]
    sales = datasets["sales.csv"]
    pos_records = datasets["pos_records.csv"]

    assert distributors["distributor_id"].is_unique
    assert products["product_id"].is_unique
    assert set(distributors["region"]) == {"AMER", "EMEA", "APAC"}

    assert len(sales) == 20 * 50 * 24
    assert (sales["quantity"] >= 0).all()
    assert (sales["revenue"] >= 0).all()

    assert set(pos_records["pos_date"]) == set(pd.date_range("2024-01-01", periods=24, freq="MS").strftime("%Y-%m-%d"))
    assert (pos_records["quantity"] >= 1).all()

    for filename in datasets:
        assert (tmp_path / filename).is_file()
