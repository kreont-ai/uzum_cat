"""Хранилище снапшотов: SQLite (история по датам) + CSV-экспорт.

Каждый прогон harvest создаёт одну запись в snapshots и по одной записи в
products на каждый найденный товар. raw_json хранит весь ответ API как
есть — если понадобится колонка, которую parser.flatten_product сейчас не
достаёт, данные не потеряны, их можно вытащить из raw_json позже.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .parser import flatten_product

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_url TEXT NOT NULL,
    captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    product_id TEXT,
    title TEXT,
    price REAL,
    rating REAL,
    reviews_count INTEGER,
    shop TEXT,
    orders_count INTEGER,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_snapshot ON products(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_products_product_id ON products(product_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Добавляет колонки, появившиеся после первого релиза схемы, в уже
    существующие базы (CREATE TABLE IF NOT EXISTS их не тронет).
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
    if "orders_count" not in existing:
        conn.execute("ALTER TABLE products ADD COLUMN orders_count INTEGER")
        conn.commit()


def save_snapshot(conn: sqlite3.Connection, category_url: str, products: list[dict]) -> int:
    """Сохраняет карточки товаров одного прогона harvest как новый снапшот.

    Дедуплицирует по product_id: пагинация Uzum (offset + sort=BY_RELEVANCE_DESC)
    не гарантирует стабильный порядок между страницами — на практике один и
    тот же товар может попасться на нескольких разных страницах одного
    прогона (проверено вживую: один product_id встретился 48 раз). Первое
    вхождение оставляем, повторные пропускаем.
    """
    captured_at = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO snapshots (category_url, captured_at) VALUES (?, ?)",
        (category_url, captured_at),
    )
    snapshot_id = cur.lastrowid

    seen_product_ids: set[str] = set()
    duplicates_skipped = 0

    for item in products:
        flat = flatten_product(item)
        product_id = str(flat.get("product_id", "")) or None
        if product_id is not None:
            if product_id in seen_product_ids:
                duplicates_skipped += 1
                continue
            seen_product_ids.add(product_id)

        conn.execute(
            """
            INSERT INTO products
                (snapshot_id, product_id, title, price, rating, reviews_count, shop, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                product_id,
                flat.get("title"),
                flat.get("price"),
                flat.get("rating"),
                flat.get("reviews_count"),
                flat.get("shop"),
                json.dumps(item, ensure_ascii=False),
            ),
        )
    conn.commit()
    if duplicates_skipped:
        print(f"Пропущено {duplicates_skipped} повторов товаров (API отдал их на нескольких страницах)")
    return snapshot_id


def get_product_ids(
    conn: sqlite3.Connection, snapshot_id: int | None = None, missing_orders_only: bool = False
) -> list[int]:
    """product_id хранится как TEXT (см. save_snapshot) — фильтруем нечисловые
    и возвращаем int, чтобы дальше можно было построить URL товара.

    missing_orders_only=True пропускает товары, у которых orders_count уже
    заполнен хотя бы в одной строке — удобно, чтобы дозабрать после сбоя,
    не гоняя заново то, что уже получили.
    """
    conditions = []
    params: list = []
    if snapshot_id is not None:
        conditions.append("snapshot_id = ?")
        params.append(snapshot_id)
    if missing_orders_only:
        conditions.append(
            "product_id NOT IN (SELECT product_id FROM products WHERE orders_count IS NOT NULL)"
        )
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(f"SELECT DISTINCT product_id FROM products {where}", params).fetchall()
    ids = []
    for (pid,) in rows:
        if pid and pid.isdigit():
            ids.append(int(pid))
    return ids


def set_orders_count(conn: sqlite3.Connection, product_id: int, orders_count: int | None) -> None:
    conn.execute(
        "UPDATE products SET orders_count = ? WHERE product_id = ?",
        (orders_count, str(product_id)),
    )
    conn.commit()


def export_csv(conn: sqlite3.Connection, csv_path: Path, snapshot_id: int | None = None) -> int:
    """Экспортирует products (+ дата снапшота) в CSV. По умолчанию — весь
    накопленный история; передай snapshot_id, чтобы выгрузить только один
    прогон.
    """
    query = """
        SELECT s.captured_at, s.category_url, p.product_id, p.title, p.price,
               p.rating, p.reviews_count, p.shop, p.orders_count
        FROM products p
        JOIN snapshots s ON s.id = p.snapshot_id
    """
    params: tuple = ()
    if snapshot_id is not None:
        query += " WHERE p.snapshot_id = ?"
        params = (snapshot_id,)
    query += " ORDER BY s.captured_at, p.id"

    rows = conn.execute(query, params).fetchall()
    headers = [
        "captured_at", "category_url", "product_id", "title",
        "price", "rating", "reviews_count", "shop", "orders_count",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return len(rows)
