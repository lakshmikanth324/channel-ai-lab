from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
DATABASE_PATH = PROJECT_ROOT / "channel_ai_lab.db"


POS_MATCHING_COLUMNS = {
    "matched_product_id": "TEXT",
    "match_method": "TEXT",
    "match_confidence": "REAL",
    "review_status": "TEXT NOT NULL DEFAULT 'pending'",
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_batches (
    batch_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    row_counts TEXT NOT NULL,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS distributors (
    distributor_id TEXT PRIMARY KEY,
    distributor_name TEXT NOT NULL,
    region TEXT NOT NULL,
    channel_segment TEXT NOT NULL,
    active INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    list_price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sales (
    month TEXT NOT NULL,
    distributor_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    revenue REAL NOT NULL,
    PRIMARY KEY (month, distributor_id, product_id),
    FOREIGN KEY (distributor_id) REFERENCES distributors(distributor_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS pos_records (
    pos_id INTEGER PRIMARY KEY,
    pos_date TEXT NOT NULL,
    distributor_id TEXT NOT NULL,
    pos_product_name TEXT NOT NULL,
    pos_product_code TEXT,
    quantity INTEGER NOT NULL,
    batch_id TEXT NOT NULL,
    matched_product_id TEXT,
    match_method TEXT,
    match_confidence REAL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    FOREIGN KEY (distributor_id) REFERENCES distributors(distributor_id),
    FOREIGN KEY (batch_id) REFERENCES ingest_batches(batch_id)
);

CREATE INDEX IF NOT EXISTS ix_sales_month ON sales(month);
CREATE INDEX IF NOT EXISTS ix_sales_distributor ON sales(distributor_id);
CREATE INDEX IF NOT EXISTS ix_pos_date ON pos_records(pos_date);
CREATE INDEX IF NOT EXISTS ix_pos_batch ON pos_records(batch_id);
"""


def migrate_pos_records_schema(connection: sqlite3.Connection) -> None:
    """Add matcher fields to existing databases; safe to run repeatedly."""
    existing = {
        row[1]
        for row in connection.execute("PRAGMA table_info(pos_records)").fetchall()
    }
    for name, definition in POS_MATCHING_COLUMNS.items():
        if name not in existing:
            connection.execute(
                f"ALTER TABLE pos_records ADD COLUMN {name} {definition}"
            )

    # Older databases may already have the column but contain NULL review states.
    connection.execute(
        "UPDATE pos_records SET review_status = 'pending' WHERE review_status IS NULL"
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def import_csv_to_sqlite(database_path: Path = DATABASE_PATH, raw_data_dir: Path = RAW_DATA_DIR) -> str:
    required_files = {
        "distributors": "distributors.csv",
        "products": "products.csv",
        "sales": "sales.csv",
        "pos_records": "pos_records.csv",
    }

    missing = [name for name in required_files.values() if not (raw_data_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing CSV files: {', '.join(missing)}")

    batch_id = str(uuid4())
    started_at = utc_now()
    row_counts: dict[str, int] = {}

    distributors = pd.read_csv(raw_data_dir / required_files["distributors"])
    products = pd.read_csv(raw_data_dir / required_files["products"])
    sales = pd.read_csv(raw_data_dir / required_files["sales"])
    pos_records = pd.read_csv(raw_data_dir / required_files["pos_records"])

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        migrate_pos_records_schema(connection)

        connection.execute(
            """
            INSERT INTO ingest_batches
                (batch_id, source, status, started_at, row_counts)
            VALUES (?, ?, 'running', ?, '{}')
            """,
            (batch_id, str(raw_data_dir), started_at),
        )

        try:
            connection.execute("DELETE FROM pos_records")
            connection.execute("DELETE FROM sales")

            connection.execute("DELETE FROM products")
            connection.execute("DELETE FROM distributors")

            connection.executemany(
                """
                INSERT INTO distributors
                    (distributor_id, distributor_name, region, channel_segment, active)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.distributor_id,
                        row.distributor_name,
                        row.region,
                        row.channel_segment,
                        int(bool(row.active)),
                    )
                    for row in distributors.itertuples(index=False)
                ],
            )

            connection.executemany(
                "INSERT INTO products (product_id, product_name, category, list_price) VALUES (?, ?, ?, ?)",
                list(products.itertuples(index=False, name=None)),
            )

            connection.executemany(
                "INSERT INTO sales (month, distributor_id, product_id, quantity, revenue) VALUES (?, ?, ?, ?, ?)",
                list(sales.itertuples(index=False, name=None)),
            )

            connection.executemany(
                """
                INSERT INTO pos_records
                    (pos_id, pos_date, distributor_id, pos_product_name, pos_product_code, quantity, batch_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        pos_index,
                        row.pos_date,
                        row.distributor_id,
                        row.pos_product_name,
                        None if pd.isna(row.pos_product_code) or row.pos_product_code == "" else row.pos_product_code,
                        int(row.quantity),
                        batch_id,
                    )
                    for pos_index, row in enumerate(pos_records.itertuples(index=False), start=1)
                ],
            )

            row_counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in required_files
            }

            connection.execute(
                """
                UPDATE ingest_batches
                SET status = 'completed', completed_at = ?, row_counts = ?
                WHERE batch_id = ?
                """,
                (utc_now(), str(row_counts), batch_id),
            )
            connection.commit()

        except Exception as error:
            connection.rollback()
            with sqlite3.connect(database_path) as error_connection:
                error_connection.execute(
                    """
                    UPDATE ingest_batches
                    SET status = 'failed', completed_at = ?, row_counts = ?, error_message = ?
                    WHERE batch_id = ?
                    """,
                    (utc_now(), str(row_counts), str(error), batch_id),
                )
                error_connection.commit()
            raise

    return batch_id


def main() -> None:
    batch_id = import_csv_to_sqlite()

    with sqlite3.connect(DATABASE_PATH) as connection:
        for table in ("distributors", "products", "sales", "pos_records"):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count:,} rows")

        latest = connection.execute(
            "SELECT batch_id, status, started_at, completed_at, row_counts, error_message "
            "FROM ingest_batches ORDER BY started_at DESC LIMIT 1"
        ).fetchone()

    print(f"batch_id: {batch_id}")
    print(f"Database: {DATABASE_PATH}")
    print(f"Latest ingest: {latest}")


if __name__ == "__main__":
    main()
