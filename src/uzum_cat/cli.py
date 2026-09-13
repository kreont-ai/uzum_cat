"""CLI: uzum-cat discover|harvest|export.

Примеры:
    uzum-cat discover "https://uzum.uz/ru/category/zhenshchinam-1"
    uzum-cat harvest --category-url "https://uzum.uz/ru/category/zhenshchinam-1"
    uzum-cat export --csv snapshot.csv
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .analytics import compute_summary, format_summary
from .client import TokenExpiredError, iter_products, load_template
from .config import HarvestConfig
from .discovery import discover
from .product_detail import fetch_orders_for_products
from .storage import connect, export_csv, get_product_ids, save_snapshot, set_orders_count


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--template", type=Path, default=Path("request_template.json"),
        help="Путь к шаблону запроса (по умолчанию request_template.json)",
    )
    parser.add_argument(
        "--db", type=Path, default=Path("uzum_cat.db"),
        help="Путь к SQLite-базе снапшотов (по умолчанию uzum_cat.db)",
    )


def cmd_discover(args: argparse.Namespace) -> None:
    asyncio.run(
        discover(
            category_url=args.category_url,
            captured_path=args.captured,
            template_path=args.template,
            headless=args.headless,
        )
    )


def cmd_harvest(args: argparse.Namespace) -> None:
    template = load_template(args.template)
    config = HarvestConfig.load(args.config)

    conn = connect(args.db)
    all_products: list[dict] = []
    try:
        for page in iter_products(template, config):
            all_products.extend(page)
    except TokenExpiredError as e:
        sys.exit(str(e))

    if not all_products:
        print("Ничего не собрано — проверь request_template.json и структуру ответа API.")
        return

    category_url = args.category_url or template.get("url", "")
    snapshot_id = save_snapshot(conn, category_url, all_products)
    print(f"\nСнапшот #{snapshot_id}: {len(all_products)} товаров сохранено в {args.db.resolve()}")

    if args.csv:
        n = export_csv(conn, args.csv, snapshot_id=snapshot_id)
        print(f"Также экспортировано {n} строк в {args.csv.resolve()}")


def cmd_export(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    n = export_csv(conn, args.csv, snapshot_id=args.snapshot_id)
    print(f"Экспортировано {n} строк в {args.csv.resolve()}")


def cmd_analyze(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    summary = compute_summary(conn, snapshot_id=args.snapshot_id, top_n=args.top)
    if summary.total_products == 0:
        print("В базе нет данных — сначала прогони `uzum-cat harvest`.")
        return

    category_url = None
    if args.snapshot_id is not None:
        row = conn.execute(
            "SELECT category_url FROM snapshots WHERE id = ?", (args.snapshot_id,)
        ).fetchone()
        category_url = row[0] if row else None

    print(format_summary(summary, category_url=category_url))


def cmd_enrich_orders(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    product_ids = get_product_ids(
        conn, snapshot_id=args.snapshot_id, missing_orders_only=args.missing_only
    )
    if not product_ids:
        print("Нет товаров для обогащения — сначала прогони `uzum-cat harvest`.")
        return

    print(f"Забираю число заказов по {len(product_ids)} товарам (пауза {args.delay}с между запросами)...")
    ok = 0
    for i, detail in enumerate(fetch_orders_for_products(product_ids, delay_seconds=args.delay)):
        set_orders_count(conn, detail.product_id, detail.orders_amount)
        if detail.orders_amount is not None:
            ok += 1
        if (i + 1) % 50 == 0:
            print(f"  ...{i + 1}/{len(product_ids)}")

    print(f"Готово: заказы получены для {ok} из {len(product_ids)} товаров.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uzum-cat", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_discover = sub.add_parser("discover", help="Захватить реальный запрос листинга товаров")
    p_discover.add_argument("category_url", help="URL страницы категории на uzum.uz")
    p_discover.add_argument("--captured", type=Path, default=Path("captured_requests.json"))
    p_discover.add_argument("--template", type=Path, default=Path("request_template.json"))
    p_discover.add_argument(
        "--headless", action="store_true",
        help="Запустить браузер в headless-режиме (по умолчанию выключено — так проще пройти анти-бот проверки)",
    )
    p_discover.set_defaults(func=cmd_discover)

    p_harvest = sub.add_parser("harvest", help="Собрать снапшот категории")
    _add_common_paths(p_harvest)
    p_harvest.add_argument("--config", type=Path, default=Path("config.yaml"))
    p_harvest.add_argument("--csv", type=Path, default=None, help="Дополнительно экспортировать этот снапшот в CSV")
    p_harvest.add_argument(
        "--category-url", default=None,
        help="URL категории для записи в БД (по умолчанию берётся из request_template.json)",
    )
    p_harvest.set_defaults(func=cmd_harvest)

    p_export = sub.add_parser("export", help="Экспортировать накопленную историю снапшотов в CSV")
    p_export.add_argument("--db", type=Path, default=Path("uzum_cat.db"))
    p_export.add_argument("--csv", type=Path, default=Path("uzum_cat_export.csv"))
    p_export.add_argument("--snapshot-id", type=int, default=None, help="Только один снапшот (по умолчанию — вся история)")
    p_export.set_defaults(func=cmd_export)

    p_analyze = sub.add_parser("analyze", help="Показать аналитику по накопленным снапшотам (цены, рейтинги, топы)")
    p_analyze.add_argument("--db", type=Path, default=Path("uzum_cat.db"))
    p_analyze.add_argument("--snapshot-id", type=int, default=None, help="Только один снапшот (по умолчанию — вся накопленная история)")
    p_analyze.add_argument("--top", type=int, default=10, help="Сколько строк показывать в топ-списках")
    p_analyze.set_defaults(func=cmd_analyze)

    p_enrich = sub.add_parser(
        "enrich-orders",
        help="Добавить число заказов (ordersAmount) к уже собранным товарам — по одному HTTP-запросу на товар",
    )
    p_enrich.add_argument("--db", type=Path, default=Path("uzum_cat.db"))
    p_enrich.add_argument("--snapshot-id", type=int, default=None, help="Только один снапшот (по умолчанию — все товары в БД)")
    p_enrich.add_argument("--delay", type=float, default=1.5, help="Пауза между запросами, секунд (не убирать/не уменьшать сильно)")
    p_enrich.add_argument(
        "--missing-only", action="store_true",
        help="Пропустить товары, для которых число заказов уже получено (дозабрать после сбоя)",
    )
    p_enrich.set_defaults(func=cmd_enrich_orders)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
