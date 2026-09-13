import sqlite3

from uzum_cat.analytics import compute_summary
from uzum_cat.storage import SCHEMA


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


def insert(conn, snapshot_id, product_id, title, price, rating, reviews_count, shop=None, orders_count=None):
    conn.execute(
        """
        INSERT INTO products (snapshot_id, product_id, title, price, rating, reviews_count, shop, orders_count, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}')
        """,
        (snapshot_id, product_id, title, price, rating, reviews_count, shop, orders_count),
    )


def test_compute_summary_basic_stats():
    conn = make_conn()
    conn.execute("INSERT INTO snapshots (category_url, captured_at) VALUES ('u', 't')")
    insert(conn, 1, "1", "Cheap", 100, 4.0, 5, orders_count=50)
    insert(conn, 1, "2", "Mid", 200, 4.5, 15, orders_count=200)
    insert(conn, 1, "3", "Expensive", 300, 5.0, 25)
    conn.commit()

    summary = compute_summary(conn, snapshot_id=1, top_n=2)

    assert summary.total_products == 3
    assert summary.with_price.min == 100
    assert summary.with_price.max == 300
    assert summary.with_price.mean == 200
    assert summary.total_reviews == 45
    assert summary.missing_shop == 3
    assert summary.with_orders == 2
    assert summary.total_orders == 250

    assert [p["title"] for p in summary.top_by_reviews] == ["Expensive", "Mid"]
    assert [p["title"] for p in summary.cheapest] == ["Cheap", "Mid"]
    assert [p["title"] for p in summary.top_by_orders] == ["Mid", "Cheap"]


def test_compute_summary_empty_db():
    conn = make_conn()
    summary = compute_summary(conn)
    assert summary.total_products == 0
    assert summary.with_price.count == 0
    assert summary.top_by_reviews == []
