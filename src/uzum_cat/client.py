"""ШАГ 2: используя шаблон запроса (request_template.json), пойманный
discovery.py, проходит по категории постранично и отдаёт карточки товаров.

Токен в headers["Authorization"] — обычный JWT с ограниченным сроком
жизни. Если начнут приходить 401 — значит, токен протух и нужно заново
прогнать `uzum-cat discover`.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Iterator

import requests

from .config import HarvestConfig
from .parser import find_product_list


class TokenExpiredError(RuntimeError):
    pass


def _set_nested(body: dict, dotted_path: str, value: int) -> None:
    """Записывает value по пути вида "queryInput.pagination.offset" внутри
    body["variables"]. GraphQL-запросы Uzum кладут параметры пагинации не
    плоско в variables, а вложенно — путь может быть любой глубины.
    """
    node = body.setdefault("variables", {})
    keys = dotted_path.split(".")
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value


def load_template(path: Path) -> dict:
    if not path.exists():
        sys.exit(
            f"Не найден {path}. Сначала прогони `uzum-cat discover <url категории>`, "
            f"либо вручную сохрани туда объект запроса (см. README)."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def iter_products(template: dict, config: HarvestConfig) -> Iterator[list[dict]]:
    """Постранично ходит по API и на каждой итерации отдаёт список карточек
    товаров с одной страницы. Останавливается, когда страница пуста, когда
    достигнут config.max_pages, либо когда сервер вернул 401 (токен протух).
    """
    url = template["url"]
    headers = template["headers"]
    raw_body = template["post_data"]
    body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

    offset = 0
    for page_num in range(config.max_pages):
        _set_nested(body, config.pagination_field, offset)

        resp = requests.post(url, headers=headers, json=body, timeout=config.request_timeout)

        if resp.status_code == 401:
            raise TokenExpiredError(
                "Токен протух (401). Обнови request_template.json командой "
                "`uzum-cat discover <url категории>`."
            )
        resp.raise_for_status()

        data = resp.json()
        items = find_product_list(data)
        if not items:
            print(f"Страница {page_num}: пусто, останавливаюсь.")
            return

        print(f"Страница {page_num}: +{len(items)} товаров")
        yield items

        offset += config.page_size
        time.sleep(config.delay_seconds)
