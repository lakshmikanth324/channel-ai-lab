import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "channel_ai_lab.db"


DEFAULT_QUERY = """
SELECT
    batch_id,
    status,
    started_at,
    completed_at,
    row_counts,
    error_message
FROM ingest_batches
ORDER BY started_at DESC
LIMIT 10
"""


def execute_query(query: str = DEFAULT_QUERY, parameters: tuple = ()) -> list[tuple]:
    """Execute a read-only SQL query against the channel AI database."""
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DATABASE_PATH}. "
            "Run src/data/import_csv_to_sqlite.py first."
        )

    normalized_query = query.strip().upper()
    if not normalized_query.startswith("SELECT"):
        raise ValueError("Only read-only SELECT queries are allowed.")

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(query, parameters).fetchall()
        return [tuple(row) for row in rows]


def main() -> None:
    rows = execute_query()

    if not rows:
        print("No ingest batches found.")
        return

    print("Latest ingest batches:")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
