from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import ProductParameter


SCHEMA = """
CREATE TABLE IF NOT EXISTS product_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product TEXT NOT NULL,
    module TEXT NOT NULL,
    feature TEXT NOT NULL,
    description TEXT NOT NULL,
    version TEXT NOT NULL,
    edition TEXT NOT NULL,
    remarks TEXT NOT NULL,
    source_file TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    raw_json TEXT NOT NULL,
    evidence_text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_product_parameters_product
ON product_parameters(product);
"""


class ParameterStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def reset(self) -> None:
        self.conn.execute("DELETE FROM product_parameters")
        self.conn.commit()

    def add_parameters(self, parameters: list[ProductParameter]) -> int:
        rows = [
            (
                p.product,
                p.module,
                p.feature,
                p.description,
                p.version,
                p.edition,
                p.remarks,
                p.source_file,
                p.sheet_name,
                p.row_number,
                json.dumps(p.raw, ensure_ascii=False),
                p.evidence_text,
            )
            for p in parameters
        ]
        self.conn.executemany(
            """
            INSERT INTO product_parameters (
                product, module, feature, description, version, edition, remarks,
                source_file, sheet_name, row_number, raw_json, evidence_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.conn.commit()
        return len(rows)

    def products(self) -> list[tuple[str, int]]:
        cursor = self.conn.execute(
            "SELECT product, COUNT(*) AS count FROM product_parameters GROUP BY product ORDER BY product"
        )
        return [(row["product"], int(row["count"])) for row in cursor.fetchall()]

    def by_product(self, product: str) -> list[ProductParameter]:
        cursor = self.conn.execute(
            """
            SELECT * FROM product_parameters
            WHERE product = ?
            ORDER BY source_file, sheet_name, row_number
            """,
            (product,),
        )
        return [self._row_to_parameter(row) for row in cursor.fetchall()]

    def all(self) -> list[ProductParameter]:
        cursor = self.conn.execute("SELECT * FROM product_parameters ORDER BY product, source_file, row_number")
        return [self._row_to_parameter(row) for row in cursor.fetchall()]

    @staticmethod
    def _row_to_parameter(row: sqlite3.Row) -> ProductParameter:
        return ProductParameter(
            product=row["product"],
            module=row["module"],
            feature=row["feature"],
            description=row["description"],
            version=row["version"],
            edition=row["edition"],
            remarks=row["remarks"],
            source_file=row["source_file"],
            sheet_name=row["sheet_name"],
            row_number=int(row["row_number"]),
            raw=json.loads(row["raw_json"] or "{}"),
        )
