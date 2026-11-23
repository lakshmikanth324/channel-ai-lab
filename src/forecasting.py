"""Time-aware evaluation of pooled monthly sales forecasting models."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


GROUP_COLUMNS = ["distributor_id", "product_id"]
NUMERIC_FEATURES = ["time_index", "month_sin", "month_cos", "lag_1", "lag_3", "rolling_mean_3"]
CATEGORICAL_FEATURES = ["distributor_id", "product_id", "region"]
MODEL_NAMES = ["Naive", "Linear Regression", "Random Forest"]


def load_sales_data(database_path: str | Path) -> pd.DataFrame:
    """Load monthly sales with distributor region and product labels from SQLite."""
    with sqlite3.connect(database_path) as connection:
        frame = pd.read_sql_query(
            """
            SELECT s.month, s.distributor_id, d.region, s.product_id,
                   p.product_name, s.quantity
            FROM sales AS s
            JOIN distributors AS d USING (distributor_id)
            JOIN products AS p USING (product_id)
            ORDER BY s.month, s.distributor_id, s.product_id
            """,
            connection,
        )
    if frame.empty:
        raise ValueError("The sales table has no rows to forecast.")
    return frame


def make_forecast_features(sales: pd.DataFrame) -> pd.DataFrame:
    """Build leakage-safe one-step-ahead lag features for each distributor/product."""
    required = {"month", "distributor_id", "product_id", "quantity", "region"}
    missing = required.difference(sales.columns)
    if missing:
        raise ValueError(f"Sales data is missing required columns: {', '.join(sorted(missing))}")

    frame = sales.copy()
    frame["month"] = pd.to_datetime(frame["month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    frame["quantity"] = pd.to_numeric(frame["quantity"], errors="coerce")
    frame = frame.dropna(subset=["month", "quantity", *GROUP_COLUMNS])
    frame = frame.groupby(["month", *GROUP_COLUMNS], as_index=False).agg(
        quantity=("quantity", "sum"),
        region=("region", "first"),
        **({"product_name": ("product_name", "first")} if "product_name" in frame.columns else {}),
    )
    frame = frame.sort_values([*GROUP_COLUMNS, "month"]).reset_index(drop=True)
    month_number = frame["month"].dt.month
    frame["time_index"] = frame["month"].map(pd.Timestamp.toordinal).astype(float)
    frame["month_sin"] = np.sin(2 * np.pi * month_number / 12)
    frame["month_cos"] = np.cos(2 * np.pi * month_number / 12)
    grouped = frame.groupby(GROUP_COLUMNS, sort=False)["quantity"]
    frame["lag_1"] = grouped.shift(1)
    frame["lag_3"] = grouped.shift(3)
    frame["rolling_mean_3"] = grouped.transform(
        lambda values: values.shift(1).rolling(window=3, min_periods=1).mean()
    )
    return frame.dropna(subset=["lag_1", "lag_3"]).reset_index(drop=True)


def _regression_pipeline(estimator: object) -> Pipeline:
    preprocessing = ColumnTransformer(
        [
            ("numeric", StandardScaler(), NUMERIC_FEATURES),
            ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ]
    )
    return Pipeline([("preprocessing", preprocessing), ("model", estimator)])


def _error_metrics(actual: pd.Series, predicted: pd.Series) -> dict[str, float]:
    errors = actual.to_numpy(dtype=float) - predicted.to_numpy(dtype=float)
    nonzero = actual.to_numpy(dtype=float) != 0
    mape = float(np.mean(np.abs(errors[nonzero] / actual.to_numpy(dtype=float)[nonzero])) * 100) if nonzero.any() else float("nan")
    return {
        "MAE": float(np.mean(np.abs(errors))),
        "RMSE": float(np.sqrt(np.mean(errors**2))),
        "MAPE (%)": mape,
        "Observations": int(len(errors)),
    }


def evaluate_forecasts(sales: pd.DataFrame, test_periods: int = 3, random_state: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate a last-value baseline and pooled regressors on the latest time periods.

    Each test prediction is a one-step-ahead backtest: lag features use only earlier
    observed months, while fitted models are trained exclusively before the cutoff.
    """
    if test_periods < 1:
        raise ValueError("test_periods must be at least 1")
    frame = make_forecast_features(sales)
    months = np.sort(frame["month"].unique())
    if len(months) <= test_periods:
        raise ValueError(f"Need more than {test_periods} usable months for a time-based split.")
    cutoff = months[-test_periods]
    train = frame.loc[frame["month"] < cutoff].copy()
    test = frame.loc[frame["month"] >= cutoff].copy()
    if train.empty or test.empty:
        raise ValueError("The time-based split produced an empty training or test set.")

    test = test.copy()
    test["Naive"] = test["lag_1"]
    features = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    estimators = {
        "Linear Regression": LinearRegression(),
        "Random Forest": RandomForestRegressor(
            n_estimators=200, min_samples_leaf=2, random_state=random_state, n_jobs=-1
        ),
    }
    for name, estimator in estimators.items():
        model = _regression_pipeline(estimator)
        model.fit(train[features], train["quantity"])
        test[name] = np.maximum(0, model.predict(test[features]))

    predictions = test.rename(columns={"quantity": "actual"})
    predictions["split"] = np.where(predictions["month"] < cutoff, "train", "test")
    for model_name in MODEL_NAMES:
        predictions[f"{model_name} absolute error"] = (
            predictions["actual"] - predictions[model_name]
        ).abs()
    metrics = pd.DataFrame(
        [{"Model": name, **_error_metrics(predictions["actual"], predictions[name])} for name in MODEL_NAMES]
    ).sort_values("MAE").reset_index(drop=True)
    return predictions, metrics


def error_breakdown(predictions: pd.DataFrame, dimension: str, model_name: str) -> pd.DataFrame:
    """Summarize test-set errors by distributor, region, or product."""
    dimensions = {
        "Distributor": "distributor_id",
        "Region": "region",
        "Product": "product_name" if "product_name" in predictions else "product_id",
    }
    if dimension not in dimensions:
        raise ValueError(f"Unsupported breakdown dimension: {dimension}")
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unsupported model: {model_name}")
    data = predictions.loc[predictions["split"] == "test"].copy()
    data["absolute_error"] = (data["actual"] - data[model_name]).abs()
    data["squared_error"] = (data["actual"] - data[model_name]) ** 2
    data["absolute_percentage_error"] = np.where(
        data["actual"] != 0, data["absolute_error"] / data["actual"], np.nan
    )
    key = dimensions[dimension]
    result = data.groupby(key, dropna=False).agg(
        MAE=("absolute_error", "mean"),
        RMSE=("squared_error", lambda values: float(np.sqrt(values.mean()))),
        **{"MAPE (%)": ("absolute_percentage_error", lambda values: float(values.mean() * 100))},
        Observations=("actual", "size"),
    )
    return result.reset_index().sort_values("MAE", ascending=False).reset_index(drop=True)
