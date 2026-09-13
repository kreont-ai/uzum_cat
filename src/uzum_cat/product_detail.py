"""Достаёт число заказов (`ordersAmount`) со страницы отдельного товара.

Список категории (client.py/parser.py) не отдаёт этот показатель вообще —
проверено на живом ответе `MakeSearch_ItemsAndFilters`. Он есть только на
странице самого товара, встроенным в SSR-разметку (Nuxt payload) как
`ordersAmount:<число>` — обычным текстом, безо всякого отдельного API-вызова
и без запуска браузера: обычный `requests.get` уже возвращает готовый HTML.

Остальные поля этого payload (например `characteristics` — цвет/размер)
закодированы через общую таблицу строковых констант всего Nuxt-пейлоада
(значения вида `value:M` ссылаются на переменную M, объявленную в другом
месте огромного inline-скрипта) — надёжно распарсить их без полноценного
JS-движка не выйдет, поэтому здесь достаём только `ordersAmount`.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import requests

_ORDERS_AMOUNT_RE = re.compile(r"ordersAmount:(\d+)")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU",
}


@dataclass
class ProductDetail:
    product_id: int
    orders_amount: int | None


def fetch_orders_amount(product_id: int, timeout: float = 20.0, retries: int = 2) -> ProductDetail:
    """Тянет страницу товара и достаёт ordersAmount.

    Замечено вживую: примерно 1 из 5 запросов к одному и тому же товару
    возвращает валидный (200 OK, полноразмерный) HTML, но без блока pdp —
    похоже на нестабильность рендера/кеша на стороне Uzum, а не признак
    того, что у товара действительно нет этого поля. Поэтому при пустом
    результате пробуем ещё раз перед тем, как сдаться.
    """
    url = f"https://uzum.uz/ru/product/x-{product_id}"
    for attempt in range(retries + 1):
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        m = _ORDERS_AMOUNT_RE.search(resp.text)
        if m:
            return ProductDetail(product_id=product_id, orders_amount=int(m.group(1)))
        if attempt < retries:
            time.sleep(1.0)
    return ProductDetail(product_id=product_id, orders_amount=None)


def extract_orders_amount(html: str) -> int | None:
    """Чистая функция извлечения — вынесена отдельно, чтобы тестировать без сети."""
    m = _ORDERS_AMOUNT_RE.search(html)
    return int(m.group(1)) if m else None


def fetch_orders_for_products(
    product_ids: list[int], delay_seconds: float = 1.5, timeout: float = 20.0
):
    """Генератор: постранично (по одному товару) ходит на страницы товаров и
    отдаёт ProductDetail. Пауза между запросами обязательна — это уже не
    30-в-одном GraphQL-запрос категории, а по одному HTTP-запросу на товар.
    """
    for i, pid in enumerate(product_ids):
        try:
            yield fetch_orders_amount(pid, timeout=timeout)
        except requests.RequestException as e:
            yield ProductDetail(product_id=pid, orders_amount=None)
            print(f"  [{i+1}/{len(product_ids)}] товар {pid}: ошибка запроса ({e})")
            continue
        if i + 1 < len(product_ids):
            time.sleep(delay_seconds)
