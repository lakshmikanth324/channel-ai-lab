import numpy as np
import pandas as pd
import pytest

from src.forecasting import error_breakdown, evaluate_forecasts, make_forecast_features


def sample_sales(months=12):
    rows = []
    for month in pd.date_range("2023-01-01", periods=months, freq="MS"):
        for distributor, region in [("D1", "North"), ("D2", "South")]:
            for product in ["P1", "P2"]:
                rows.append({
                    "month": month,
                    "distributor_id": distributor,
                    "region": region,
                    "product_id": product,
                    "product_name": f"Product {product}",
                    "quantity": 20 + month.month + (5 if distributor == "D2" else 0),
                })
    return pd.DataFrame(rows)


def test_features_are_ordered_and_lags_are_prior_observations():
    features = make_forecast_features(sample_sales())
    row = features.loc[
        (features["distributor_id"] == "D1")
        & (features["product_id"] == "P1")
        & (features["month"] == pd.Timestamp("2023-04-01"))
    ].iloc[0]
    assert row["lag_1"] == 23
    assert row["lag_3"] == 21
    assert row["rolling_mean_3"] == 22


def test_evaluation_uses_last_months_as_test_and_returns_all_models():
    predictions, metrics = evaluate_forecasts(sample_sales(), test_periods=3)
    assert predictions.loc[predictions["split"] == "test", "month"].nunique() == 3
    assert set(metrics["Model"]) == {"Naive", "Linear Regression", "Random Forest"}
    assert (predictions.loc[predictions["split"] == "test", "Naive"] >= 0).all()
    assert np.isfinite(metrics["MAE"]).all()


def test_breakdown_reports_error_by_region_and_distributor():
    predictions, _ = evaluate_forecasts(sample_sales(), test_periods=2)
    region = error_breakdown(predictions, "Region", "Naive")
    distributor = error_breakdown(predictions, "Distributor", "Linear Regression")
    assert set(region["region"]) == {"North", "South"}
    assert set(distributor["distributor_id"]) == {"D1", "D2"}
    assert {"MAE", "RMSE", "MAPE (%)", "Observations"}.issubset(region.columns)


def test_rejects_holdout_with_no_training_months():
    with pytest.raises(ValueError, match="Need more than"):
        evaluate_forecasts(sample_sales(months=6), test_periods=6)
