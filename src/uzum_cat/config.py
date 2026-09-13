"""Конфигурация харвестера.

Все параметры можно задать через config.yaml рядом с request_template.json,
либо переопределить флагами CLI. Значения по умолчанию — консервативные
(медленный, вежливый темп запросов).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")


@dataclass
class HarvestConfig:
    # Путь до поля offset внутри variables запроса (через точку — см. README).
    # По умолчанию соответствует реальному запросу MakeSearch_ItemsAndFilters
    # graphql.uzum.uz, пойманному через `uzum-cat discover`.
    pagination_field: str = "queryInput.pagination.offset"
    page_size: int = 48
    max_pages: int = 40
    delay_seconds: float = 3.0
    request_timeout: float = 20.0

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> "HarvestConfig":
        if not path.exists():
            return cls()
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        known = {f: raw[f] for f in cls.__dataclass_fields__ if f in raw}
        return cls(**known)
