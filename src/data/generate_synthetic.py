from pathlib import Path

import numpy as np
import pandas as pd


SEED = 42
N_DISTRIBUTORS = 20
N_PRODUCTS = 50
START_DATE = "2024-01-01"
N_MONTHS = 24


def generate_synthetic_data(output_dir: Path) -> dict[str, pd.DataFrame]:
    """Generate synthetic channel sales and POS data."""
    rng = np.random.default_rng(SEED)
    output_dir.mkdir(parents=True, exist_ok=True)

    regions = ["AMER", "EMEA", "APAC"]
    categories = ["Sensors", "Connectors", "Cable Assembly", "Terminals"]

    distributors = pd.DataFrame(
        {
            "distributor_id": [f"DIST-{index:03d}" for index in range(1, N_DISTRIBUTORS + 1)],
            "distributor_name": [f"Distribution Partner {index}" for index in range(1, N_DISTRIBUTORS + 1)],
            "region": [regions[index % len(regions)] for index in range(N_DISTRIBUTORS)],
            "channel_segment": rng.choice(["Strategic", "Growth", "Transactional"], N_DISTRIBUTORS),
            "active": rng.choice([True, True, True, False], N_DISTRIBUTORS),
        }
    )

    products = pd.DataFrame(
        {
            "product_id": [f"PROD-{index:04d}" for index in range(1, N_PRODUCTS + 1)],
            "product_name": [f"Synthetic {category} {index}" for index, category in enumerate(rng.choice(categories, N_PRODUCTS), start=1)],
            "category": rng.choice(categories, N_PRODUCTS),
            "list_price": rng.uniform(10, 500, N_PRODUCTS).round(2),
        }
    )

    months = pd.date_range(START_DATE, periods=N_MONTHS, freq="MS")
    sales_rows: list[dict] = []

    for distributor_index, distributor in distributors.iterrows():
        for product_index, product in products.iterrows():
            base_demand = rng.uniform(20, 200)
            regional_factor = {"AMER": 1.15, "EMEA": 1.0, "APAC": 1.25}[distributor["region"]]

            for month_index, month in enumerate(months):
                seasonal = 1 + 0.2 * np.sin((month_index / 12) * 2 * np.pi)
                trend = 1 + month_index * rng.uniform(0.002, 0.008)
                noise = rng.normal(1, 0.12)
                quantity = max(0, round(base_demand * regional_factor * seasonal * trend * noise))
                revenue = round(quantity * product["list_price"], 2)

                sales_rows.append(
                    {
                        "month": month.strftime("%Y-%m-%d"),
                        "distributor_id": distributor["distributor_id"],
                        "product_id": product["product_id"],
                        "quantity": quantity,
                        "revenue": revenue,
                    }
                )

    sales = pd.DataFrame(sales_rows)

    pos_rows: list[dict] = []
    for month in months:
        for _ in range(300):
            product = products.iloc[rng.integers(0, len(products))]
            distributor = distributors.iloc[rng.integers(0, len(distributors))]

            name = product["product_name"]
            noisy_name = rng.choice(
                [
                    name,
                    name.lower(),
                    name.replace("Synthetic", "Synth."),
                    name.replace(" ", "-"),
                    name + " Ltd",
                ]
            )

            pos_rows.append(
                {
                    "pos_date": month.strftime("%Y-%m-%d"),
                    "distributor_id": distributor["distributor_id"],
                    "pos_product_name": noisy_name,
                    "pos_product_code": rng.choice([product["product_id"], "", "UNKNOWN"]),
                    "quantity": max(1, int(rng.poisson(8))),
                }
            )

    pos_records = pd.DataFrame(pos_rows)

    datasets = {
        "distributors.csv": distributors,
        "products.csv": products,
        "sales.csv": sales,
        "pos_records.csv": pos_records,
    }

    for filename, frame in datasets.items():
        frame.to_csv(output_dir / filename, index=False)

    return datasets


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    raw_data_dir = project_root / "data" / "raw"
    generated = generate_synthetic_data(raw_data_dir)

    print("Generated synthetic datasets:")
    for filename, frame in generated.items():
        print(f"- {filename}: {len(frame):,} rows")
