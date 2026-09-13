"""Аналитика по собранному снапшоту категории: сводка по цене, рейтингу,
отзывам и топ товаров. Работает поверх того, что уже накоплено в SQLite
(storage.py) — отдельного похода в API не делает.
"""
from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field


@dataclass
class PriceStats:
    count: int = 0
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    median: float | None = None


@dataclass
class RatingStats:
    count: int = 0
    mean: float | None = None
    median: float | None = None


@dataclass
class Summary:
    total_products: int = 0
    with_price: PriceStats = field(default_factory=PriceStats)
    with_rating: RatingStats = field(default_factory=RatingStats)
    total_reviews: int = 0
    missing_shop: int = 0
    price_buckets: list[tuple[str, int]] = field(default_factory=list)
    top_by_reviews: list[dict] = field(default_factory=list)
    top_by_price: list[dict] = field(default_factory=list)
    cheapest: list[dict] = field(default_factory=list)


def _price_stats(prices: list[float]) -> PriceStats:
    if not prices:
        return PriceStats()
    return PriceStats(
        count=len(prices),
        min=min(prices),
        max=max(prices),
        mean=statistics.mean(prices),
        median=statistics.median(prices),
    )


def _rating_stats(ratings: list[float]) -> RatingStats:
    if not ratings:
        return RatingStats()
    return RatingStats(
        count=len(ratings),
        mean=statistics.mean(ratings),
        median=statistics.median(ratings),
    )


def _price_histogram(prices: list[float], num_buckets: int = 8) -> list[tuple[str, int]]:
    if not prices:
        return []
    lo, hi = min(prices), max(prices)
    if lo == hi:
        return [(f"{lo:,.0f}", len(prices))]
    width = (hi - lo) / num_buckets
    edges = [lo + i * width for i in range(num_buckets + 1)]
    counts = [0] * num_buckets
    for p in prices:
        idx = min(int((p - lo) / width), num_buckets - 1)
        counts[idx] += 1
    labels = [f"{edges[i]:,.0f}–{edges[i+1]:,.0f}" for i in range(num_buckets)]
    return list(zip(labels, counts))


def compute_summary(
    conn: sqlite3.Connection, snapshot_id: int | None = None, top_n: int = 10
) -> Summary:
    where = "WHERE snapshot_id = ?" if snapshot_id is not None else ""
    params: tuple = (snapshot_id,) if snapshot_id is not None else ()

    rows = conn.execute(
        f"""
        SELECT product_id, title, price, rating, reviews_count, shop
        FROM products
        {where}
        """,
        params,
    ).fetchall()

    summary = Summary(total_products=len(rows))

    prices = [r[2] for r in rows if r[2] is not None]
    ratings = [r[3] for r in rows if r[3] is not None]
    reviews = [r[4] for r in rows if r[4] is not None]

    summary.with_price = _price_stats(prices)
    summary.with_rating = _rating_stats(ratings)
    summary.total_reviews = sum(reviews)
    summary.missing_shop = sum(1 for r in rows if not r[5])
    summary.price_buckets = _price_histogram(prices)

    def as_dict(r: tuple) -> dict:
        return {
            "product_id": r[0],
            "title": r[1],
            "price": r[2],
            "rating": r[3],
            "reviews_count": r[4],
        }

    by_reviews = sorted((r for r in rows if r[4] is not None), key=lambda r: r[4], reverse=True)
    summary.top_by_reviews = [as_dict(r) for r in by_reviews[:top_n]]

    by_price_desc = sorted((r for r in rows if r[2] is not None), key=lambda r: r[2], reverse=True)
    summary.top_by_price = [as_dict(r) for r in by_price_desc[:top_n]]

    by_price_asc = sorted((r for r in rows if r[2] is not None), key=lambda r: r[2])
    summary.cheapest = [as_dict(r) for r in by_price_asc[:top_n]]

    return summary


def format_summary(summary: Summary, category_url: str | None = None) -> str:
    lines: list[str] = []
    if category_url:
        lines.append(f"Категория: {category_url}")
    lines.append(f"Всего товаров в снапшоте: {summary.total_products}")
    lines.append("")

    p = summary.with_price
    if p.count:
        lines.append(
            f"Цена (по {p.count} товарам): "
            f"мин {p.min:,.0f}, макс {p.max:,.0f}, "
            f"среднее {p.mean:,.0f}, медиана {p.median:,.0f} сум"
        )
    else:
        lines.append("Цена: данных нет")

    r = summary.with_rating
    if r.count:
        lines.append(f"Рейтинг (по {r.count} товарам): среднее {r.mean:.2f}, медиана {r.median:.2f}")
    else:
        lines.append("Рейтинг: данных нет")

    lines.append(f"Суммарно отзывов по категории: {summary.total_reviews:,}")
    if summary.missing_shop == summary.total_products and summary.total_products:
        lines.append("Магазин: API этого запроса не отдаёт продавца ни по одному товару")
    elif summary.missing_shop:
        lines.append(f"Магазин не указан у {summary.missing_shop} из {summary.total_products} товаров")

    if summary.price_buckets:
        lines.append("")
        lines.append("Распределение цен:")
        max_count = max(c for _, c in summary.price_buckets) or 1
        for label, count in summary.price_buckets:
            bar = "#" * max(1, round(count / max_count * 30)) if count else ""
            lines.append(f"  {label:>25} сум | {count:>4} | {bar}")

    def render_top(title: str, items: list[dict]) -> None:
        lines.append("")
        lines.append(title)
        for i, it in enumerate(items, 1):
            price = f"{it['price']:,.0f}" if it["price"] is not None else "?"
            rating = it["rating"] if it["rating"] is not None else "?"
            reviews = it["reviews_count"] if it["reviews_count"] is not None else "?"
            lines.append(f"  {i:>2}. {it['title'][:60]} — {price} сум, рейтинг {rating}, {reviews} отзывов")

    render_top("Топ по числу отзывов:", summary.top_by_reviews)
    render_top("Самые дорогие:", summary.top_by_price)
    render_top("Самые дешёвые:", summary.cheapest)

    return "\n".join(lines)
