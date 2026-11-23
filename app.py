"""Streamlit dashboard for time-based channel sales forecasts."""

from pathlib import Path
import os

import pandas as pd
import streamlit as st

from src.forecasting import MODEL_NAMES, error_breakdown, evaluate_forecasts, load_sales_data


DEFAULT_DATABASE = Path(__file__).resolve().parent / "channel_ai_lab.db"


@st.cache_data(show_spinner=False)
def load_data(database_path: str, modified_time: float) -> pd.DataFrame:
    del modified_time  # Included in the cache key so updated databases are reloaded.
    return load_sales_data(database_path)


st.set_page_config(page_title="Channel Sales Forecasts", layout="wide")
st.title("Channel Sales Forecast Evaluation")
st.caption("Chronological holdout comparison for monthly sales. Test predictions use a one-step-ahead backtest.")

with st.sidebar:
    st.header("Forecast settings")
    database_path = Path(os.environ.get("CHANNEL_AI_DB", str(DEFAULT_DATABASE)))
    configured_path = st.text_input("SQLite database", str(database_path))
    test_periods = st.slider("Test months", min_value=1, max_value=12, value=3)

try:
    database = Path(configured_path).expanduser()
    if not database.is_file():
        st.info("Database not found. Generate/import the project data first, or enter a valid SQLite database path in the sidebar.")
        st.stop()
    sales = load_data(str(database), database.stat().st_mtime)
    predictions, metrics = evaluate_forecasts(sales, test_periods=test_periods)
except (ValueError, OSError, Exception) as error:
    st.error(f"Could not build forecasts: {error}")
    st.stop()

with st.sidebar:
    st.header("Result filters")
    regions = sorted(predictions["region"].dropna().astype(str).unique())
    selected_regions = st.multiselect("Region", regions, default=regions)
    distributor_values = sorted(predictions["distributor_id"].dropna().astype(str).unique())
    selected_distributors = st.multiselect("Distributor", distributor_values, default=distributor_values)
    product_column = "product_name" if "product_name" in predictions else "product_id"
    products = sorted(predictions[product_column].dropna().astype(str).unique())
    selected_products = st.multiselect("Product", products, default=products)

filtered = predictions.loc[
    predictions["region"].astype(str).isin(selected_regions)
    & predictions["distributor_id"].astype(str).isin(selected_distributors)
    & predictions[product_column].astype(str).isin(selected_products)
].copy()
if filtered.empty:
    st.warning("No rows match the selected filters.")
    st.stop()

st.subheader("Holdout model comparison")
filtered_metrics = pd.DataFrame(
    [{"Model": model, **{
        "MAE": float((filtered["actual"] - filtered[model]).abs().mean()),
        "RMSE": float(((filtered["actual"] - filtered[model]) ** 2).mean() ** 0.5),
        "MAPE (%)": float(((filtered.loc[filtered["actual"] != 0, model] - filtered.loc[filtered["actual"] != 0, "actual"]).abs() / filtered.loc[filtered["actual"] != 0, "actual"]).mean() * 100) if (filtered["actual"] != 0).any() else float("nan"),
        "Observations": len(filtered),
    }} for model in MODEL_NAMES]
).sort_values("MAE")
st.dataframe(filtered_metrics, use_container_width=True, hide_index=True)
st.caption(f"Train through {predictions.loc[predictions['month'] < predictions.loc[predictions['split'] == 'test', 'month'].min(), 'month'].max():%Y-%m}; test from {predictions.loc[predictions['split'] == 'test', 'month'].min():%Y-%m} through {predictions.loc[predictions['split'] == 'test', 'month'].max():%Y-%m}.")

st.subheader("Forecast error by business dimension")
left, right = st.columns(2)
with left:
    dimension = st.selectbox("Break down by", ["Distributor", "Region", "Product"])
with right:
    model_name = st.selectbox("Model", MODEL_NAMES)

breakdown = error_breakdown(filtered, dimension, model_name)
st.dataframe(breakdown, use_container_width=True, hide_index=True)
if not breakdown.empty:
    category_column = breakdown.columns[0]
    st.bar_chart(breakdown.set_index(category_column)["MAE"])

st.subheader("Test-period actuals and forecasts")
plot_dimension = st.selectbox("Forecast series", sorted(filtered[product_column].astype(str).unique()))
series = filtered.loc[filtered[product_column].astype(str) == plot_dimension]
chart = series.groupby("month", as_index=True)[["actual", *MODEL_NAMES]].sum().sort_index()
st.line_chart(chart)

with st.expander("Prediction details"):
    columns = ["month", "region", "distributor_id", "product_id", "actual", *MODEL_NAMES]
    st.dataframe(filtered[columns].sort_values(["month", "region", "distributor_id", "product_id"]), use_container_width=True, hide_index=True)
