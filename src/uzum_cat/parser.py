"""Извлечение списка товаров из произвольного JSON-ответа GraphQL/REST.

Вместо того чтобы жёстко зашивать путь вида data.makeSearch.items (который
может измениться в любой момент — это неофициальный API), мы рекурсивно
обходим ответ и ищем список словарей, «похожий на список товаров»: у
элементов есть характерные для карточки товара ключи (id/title/price/...).
Так и discovery, и harvest переживают небольшие изменения схемы ответа.
"""
from __future__ import annotations

from typing import Any

# Ключи (в разных вариантах именования), по которым узнаём карточку товара.
# Достаточно совпадения по паре штук — это не строгая схема, а эвристика.
_PRODUCT_HINT_KEYS = {
    "id", "productId", "sku",
    "title", "name",
    "price", "sellPrice", "fullPrice", "minPrice", "amount",
    "rating", "ratingValue",
    "reviews", "reviewsAmount", "feedbackQuantity",
    "shop", "seller", "shopTitle",
}

_MIN_HINT_MATCHES = 2  # сколько ключей-подсказок должно совпасть у элемента
_MIN_LIST_SIZE = 2  # список короче этого не считаем «листингом товаров»


_WRAPPER_KEYS = ("node", "item")  # обёртка GraphQL-стиля edges/node


def _looks_like_product(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if sum(1 for k in item if k in _PRODUCT_HINT_KEYS) >= _MIN_HINT_MATCHES:
        return True
    # GraphQL часто оборачивает элемент списка в {"node": {...}} (Relay-стиль).
    for wrapper in _WRAPPER_KEYS:
        inner = item.get(wrapper)
        if isinstance(inner, dict) and sum(1 for k in inner if k in _PRODUCT_HINT_KEYS) >= _MIN_HINT_MATCHES:
            return True
    return False


def _score_list(items: list) -> int:
    if len(items) < _MIN_LIST_SIZE:
        return 0
    matches = sum(1 for it in items if _looks_like_product(it))
    if matches == 0:
        return 0
    return matches


def find_product_list(payload: Any) -> list[dict] | None:
    """Рекурсивно ищет в payload список словарей, похожий на список товаров.

    Возвращает лучший (по количеству «похожих на товар» элементов) найденный
    список, либо None, если ничего подходящего не нашлось.
    """
    best: list[dict] | None = None
    best_score = 0

    def walk(node: Any) -> None:
        nonlocal best, best_score
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            score = _score_list(node)
            if score > best_score:
                best_score = score
                best = node
            for item in node:
                walk(item)

    walk(payload)
    return best


# Кандидаты имён полей, которые обычно несут смысл id/title/price/rating/...
# Используются только для CSV-экспорта «плоских» колонок поверх raw JSON —
# сырые данные всегда сохраняются целиком, так что потеря/неверная догадка
# здесь не теряет данные, просто не заполняет удобную колонку.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "product_id": ("id", "productId", "sku"),
    "title": ("title", "name"),
    "price": ("price", "sellPrice", "fullPrice", "minPrice", "amount"),
    "rating": ("rating", "ratingValue"),
    "reviews_count": ("reviews", "reviewsAmount", "feedbackQuantity"),
    "shop": ("shop", "seller", "shopTitle"),
}


def flatten_product(item: dict) -> dict:
    """Достаёт из карточки товара несколько удобных для CSV колонок.

    Оригинальный JSON не теряется — вызывающий код кладёт его рядом
    в отдельную колонку (raw_json), см. storage.py.
    """
    # Разворачиваем Relay-стиль {"node": {...}}, если это он.
    for wrapper in _WRAPPER_KEYS:
        inner = item.get(wrapper)
        if isinstance(inner, dict):
            item = inner
            break

    flat: dict[str, Any] = {}
    for out_key, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if alias in item and item[alias] is not None:
                flat[out_key] = item[alias]
                break
    return flat
