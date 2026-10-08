# Load products.csv into the products table of huey.db, replacing what's there

import csv
import sqlite3

with sqlite3.connect("huey.db") as conn, open("products.csv", newline="", encoding="utf-8") as file:
    # Older copies of huey.db predate the img_url and price columns
    columns = [column[1] for column in conn.execute("PRAGMA table_info(products)")]
    for column in ("img_url", "price"):
        if column not in columns:
            conn.execute(f"ALTER TABLE products ADD COLUMN {column} TEXT")

    rows = []
    for row in csv.DictReader(file, delimiter=";"):
        row = {key: (value or "").strip() for key, value in row.items()}
        low, high = int(row["mst_range_min"]), int(row["mst_range_max"])

        if not 1 <= low <= high <= 10:
            raise ValueError(f"Bad MST range for {row['name']}: {low}-{high}")

        rows.append((
            row["name"], row["brand"], row["category"].lower(), low, high,
            row["sensitivity_flags"] or None, row["product-url"] or None,
            row["img-url"] or None, row["price"] or None,
        ))

    conn.execute("DELETE FROM products")
    conn.execute("DELETE FROM sqlite_sequence WHERE name = 'products'")
    conn.executemany(
        """
        INSERT INTO products (name, brand, category, mst_range_min, mst_range_max, sensitivity_flags, url, img_url, price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    print(f"Imported {len(rows)} products.")
