import sqlite3

from uzum_cat.storage import connect, save_snapshot


def make_conn(tmp_path) -> sqlite3.Connection:
    return connect(tmp_path / "test.db")


def test_save_snapshot_dedupes_repeated_product_id(tmp_path):
    """Uzum's pagination (offset + sort=BY_RELEVANCE_DESC) isn't stable
    across pages — verified live: the same product_id showed up 48 times
    in one harvest run. save_snapshot should keep only the first occurrence.
    """
    conn = make_conn(tmp_path)
    products = [
        {"catalogCard": {"discovery": {"productId": 1, "title": "A", "priceBlock": {"sellPrice": {"amount": 100}}}}},
        {"catalogCard": {"discovery": {"productId": 2, "title": "B", "priceBlock": {"sellPrice": {"amount": 200}}}}},
        {"catalogCard": {"discovery": {"productId": 1, "title": "A", "priceBlock": {"sellPrice": {"amount": 100}}}}},
    ]

    snapshot_id = save_snapshot(conn, "https://example.com/cat", products)

    rows = conn.execute("SELECT product_id FROM products WHERE snapshot_id = ?", (snapshot_id,)).fetchall()
    assert sorted(r[0] for r in rows) == ["1", "2"]


def test_save_snapshot_keeps_items_without_product_id(tmp_path):
    conn = make_conn(tmp_path)
    products = [{"catalogCard": {"discovery": {"title": "No id"}}}] * 3

    snapshot_id = save_snapshot(conn, "https://example.com/cat", products)

    count = conn.execute(
        "SELECT COUNT(*) FROM products WHERE snapshot_id = ?", (snapshot_id,)
    ).fetchone()[0]
    assert count == 3
