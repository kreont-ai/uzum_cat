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
# Намеренно НЕ включает общие ключи вроде id/title/name — они встречаются
# и в категориях, фильтрах и т.п., и по одним им легко принять список
# категорий за список товаров (так и произошло на реальном ответе Uzum:
# fastCategories тоже содержат id/title). Коммерческие поля вроде цены или
# рейтинга — куда более надёжный сигнал именно карточки товара.
_PRODUCT_HINT_KEYS = {
    "productId", "sku",
    "price", "sellPrice", "fullPrice", "minPrice",
    "rating", "ratingValue",
    "reviews", "reviewsAmount", "feedbackQuantity",
    "shop", "seller", "shopTitle",
}

_MIN_HINT_MATCHES = 2  # сколько ключей-подсказок должно совпасть у элемента
_MIN_LIST_SIZE = 2  # список короче этого не считаем «листингом товаров»


_MAX_KEY_SCAN_DEPTH = 6  # на случай глубокой вложенности GraphQL-фрагментов
_MAX_LIST_SAMPLE = 5  # не сканировать огромные вложенные списки полностью


def _collect_keys(node: Any, keys: set[str], depth: int = 0) -> None:
    if depth > _MAX_KEY_SCAN_DEPTH:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            keys.add(k)
            _collect_keys(v, keys, depth + 1)
    elif isinstance(node, list):
        for v in node[:_MAX_LIST_SAMPLE]:
            _collect_keys(v, keys, depth + 1)


def _looks_like_product(item: Any) -> bool:
    """Похоже ли это на карточку товара — независимо от того, на каком
    уровне вложенности (Relay-style edges/node, GraphQL-фрагменты вида
    catalogCard.discovery.* и т.п.) реально лежат узнаваемые поля.
    """
    if not isinstance(item, dict):
        return False
    keys: set[str] = set()
    _collect_keys(item, keys)
    return sum(1 for k in keys if k in _PRODUCT_HINT_KEYS) >= _MIN_HINT_MATCHES


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
    "product_id": ("productId", "id", "sku"),
    "title": ("title", "name"),
    "price": ("price", "sellPrice", "fullPrice", "minPrice", "amount"),
    "rating": ("rating", "ratingValue"),
    "reviews_count": ("reviews", "reviewsAmount", "feedbackQuantity", "quantity"),
    "shop": ("shop", "seller", "shopTitle"),
}


def _find_first(node: Any, alias_keys: tuple[str, ...], depth: int = 0) -> Any:
    """Обходит вложенную структуру в ширину и возвращает значение первого
    найденного ключа из alias_keys (порядок обхода не гарантирует, какой
    именно попадётся первым при нескольких совпадениях на разных уровнях,
    но для карточек товара Uzum совпадение обычно единственное).
    """
    if depth > _MAX_KEY_SCAN_DEPTH:
        return None
    if isinstance(node, dict):
        for alias in alias_keys:
            if alias in node and node[alias] is not None:
                return node[alias]
        for v in node.values():
            found = _find_first(v, alias_keys, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, list):
        for v in node[:_MAX_LIST_SAMPLE]:
            found = _find_first(v, alias_keys, depth + 1)
            if found is not None:
                return found
    return None


def flatten_product(item: dict) -> dict:
    """Достаёт из карточки товара несколько удобных для CSV колонок, на
    любом уровне вложенности (GraphQL-фрагменты часто прячут цену/рейтинг
    в дочерних объектах вроде catalogCard.discovery.priceBlock.sellPrice).

    Оригинальный JSON не теряется — вызывающий код кладёт его рядом
    в отдельную колонку (raw_json), см. storage.py.
    """
    flat: dict[str, Any] = {}
    for out_key, aliases in _FIELD_ALIASES.items():
        value = _find_first(item, aliases)
        if value is not None:
            # price/rating иногда приходят как {"amount": ...} — достаём число.
            if isinstance(value, dict) and "amount" in value:
                value = value["amount"]
            if not isinstance(value, (dict, list)):
                flat[out_key] = value
    return flat
