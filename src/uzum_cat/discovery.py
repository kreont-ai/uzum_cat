"""ШАГ 1: обнаружение реального запроса, которым фронтенд uzum.uz получает
список товаров категории.

Открывает настоящий (не headless) браузер, заходит на страницу категории,
слушает все POST-запросы/ответы к graphql.uzum.uz и api.uzum.uz, и
для каждого пробует найти в ответе список товаров (parser.find_product_list).

Если находит — автоматически сохраняет ЭТОТ запрос как request_template.json
(шаблон для harvest.py). Если однозначно выбрать не получилось (несколько
кандидатов или ни одного) — просто сохраняет все пойманные запросы в
captured_requests.json, и дальше нужно выбрать руками (см. README).
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Request, async_playwright

from .parser import find_product_list

TARGET_HOSTS = ("graphql.uzum.uz", "api.uzum.uz")


@dataclass
class Capture:
    request: dict
    product_count: int = 0


@dataclass
class DiscoveryResult:
    all_requests: list[dict] = field(default_factory=list)
    best: Capture | None = None


def _request_to_dict(request: Request) -> dict:
    try:
        post_data = request.post_data
    except Exception:
        post_data = None
    return {
        "url": request.url,
        "method": request.method,
        "headers": dict(request.headers),
        "post_data": post_data,
    }


async def run_discovery(category_url: str, headless: bool = False) -> DiscoveryResult:
    result = DiscoveryResult()
    pending_by_url: dict[str, dict] = {}

    async with async_playwright() as p:
        # headless=False по умолчанию — так проще пройти анти-бот проверки
        # (капча, выбор города) и увидеть, что реально происходит на странице.
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(locale="ru-RU")
        page = await context.new_page()

        def on_request(request: Request) -> None:
            if request.method == "POST" and any(h in request.url for h in TARGET_HOSTS):
                d = _request_to_dict(request)
                result.all_requests.append(d)
                pending_by_url[id(request)] = d
                print(f"Поймал запрос #{len(result.all_requests)}: {request.url}")

        async def on_response(response) -> None:
            request = response.request
            if request.method != "POST" or not any(h in request.url for h in TARGET_HOSTS):
                return
            d = pending_by_url.get(id(request))
            if d is None:
                return
            try:
                payload = await response.json()
            except Exception:
                return
            items = find_product_list(payload)
            if items:
                cap = Capture(request=d, product_count=len(items))
                if result.best is None or cap.product_count > result.best.product_count:
                    result.best = cap
                print(f"  -> в ответе похоже на {len(items)} товаров")

        page.on("request", on_request)
        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        print(f"Открываю {category_url} ...")
        await page.goto(category_url, wait_until="networkidle", timeout=60000)

        # Прокручиваем — многие SPA подгружают следующую "страницу" товаров
        # именно по скроллу, а не сразу при заходе.
        for _ in range(3):
            await page.mouse.wheel(0, 3000)
            await page.wait_for_timeout(2000)

        print(f"\nВсего поймано запросов к целевым хостам: {len(result.all_requests)}")

        input("\nБраузер останется открытым — посмотри страницу, затем нажми Enter для выхода...")
        await browser.close()

    return result


def save_results(result: DiscoveryResult, captured_path: Path, template_path: Path) -> None:
    captured_path.write_text(
        json.dumps(result.all_requests, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Все пойманные запросы сохранены в {captured_path.resolve()}")

    if result.best is not None:
        template_path.write_text(
            json.dumps(result.best.request, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"Автоматически выбран запрос с {result.best.product_count} товарами "
            f"в ответе -> {template_path.resolve()}"
        )
    else:
        print(
            "\nНе удалось однозначно определить запрос со списком товаров.\n"
            f"Открой {captured_path.name}, найди нужный объект руками и сохрани "
            f"его как {template_path.name} (см. README)."
        )


async def discover(category_url: str, captured_path: Path, template_path: Path, headless: bool = False) -> None:
    result = await run_discovery(category_url, headless=headless)
    save_results(result, captured_path, template_path)
