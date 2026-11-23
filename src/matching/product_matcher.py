from __future__ import annotations

from difflib import SequenceMatcher
import sqlite3

from src.matching.normalization import normalize_product_name


FUZZY_MATCH_THRESHOLD = 0.85


class ProductMatcher:
    def __init__(self, database_path: str):
        self.database_path = database_path

    def _products(self, connection: sqlite3.Connection) -> list[sqlite3.Row]:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT product_id, product_code, product_name FROM products"
        ).fetchall()

    def match_product(
        self,
        pos_product_code: str | None,
        pos_product_name: str | None,
        products: list[sqlite3.Row],
    ) -> tuple[str | None, str | None, float, str]:
        code = (pos_product_code or "").strip().upper()
        if code:
            for product in products:
                product_code = str(product["product_code"] or "").strip().upper()
                if product_code == code:
                    return str(product["product_id"]), "exact_code", 1.0, "matched"

        normalized_name = normalize_product_name(pos_product_name)
        if normalized_name:
            for product in products:
                product_name = normalize_product_name(product["product_name"])
                if product_name == normalized_name:
                    return str(product["product_id"]), "exact_normalized_name", 1.0, "matched"

        best_product_id = None
        best_score = 0.0
        if normalized_name:
            for product in products:
                product_name = normalize_product_name(product["product_name"])
                if not product_name:
                    continue
                score = SequenceMatcher(None, normalized_name, product_name).ratio()
                if score > best_score:
                    best_score = score
                    best_product_id = str(product["product_id"])

        if best_score >= FUZZY_MATCH_THRESHOLD:
            return best_product_id, "fuzzy_name", round(best_score, 4), "matched"

        return None, None, round(best_score, 4), "pending"

    def ensure_matching_columns(self, connection: sqlite3.Connection) -> None:
        existing = {
            row[1]
            for row in connection.execute("PRAGMA table_info(pos_records)").fetchall()
        }
        columns = {
            "matched_product_id": "TEXT",
            "match_method": "TEXT",
            "match_confidence": "REAL",
            "review_status": "TEXT",
        }
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(
                    f"ALTER TABLE pos_records ADD COLUMN {name} {definition}"
                )

    def match_all(self) -> dict[str, int]:
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            self.ensure_matching_columns(connection)

            products = self._products(connection)
            pos_records = connection.execute(
                "SELECT rowid, pos_product_code, pos_product_name FROM pos_records"
            ).fetchall()

            matched = 0
            pending = 0
            for record in pos_records:
                product_id, method, confidence, status = self.match_product(
                    record["pos_product_code"],
                    record["pos_product_name"],
                    products,
                )
                connection.execute(
                    """
                    UPDATE pos_records
                    SET matched_product_id = ?,
                        match_method = ?,
                        match_confidence = ?,
                        review_status = ?
                    WHERE rowid = ?
                    """,
                    (product_id, method, confidence, status, record["rowid"]),
                )
                if status == "matched":
                    matched += 1
                else:
                    pending += 1

        return {"matched": matched, "pending": pending}


def main() -> None:
    from pathlib import Path

    database_path = Path(__file__).resolve().parents[2] / "channel_ai_lab.db"
    result = ProductMatcher(str(database_path)).match_all()
    print(result)


if __name__ == "__main__":
    main()
