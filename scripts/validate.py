#!/usr/bin/env python3
# ==== MODULE CONTRACT: validate ====
# PURPOSE:   Проверять согласованность источника данных и собранного сайта, чтобы публиковать только проверенный контент.
# SCOPE:     data/*.json, data/turns/*.json, ссылки и якоря собранного dist/, тексты ошибок и коды возврата CLI.
# NON-GOALS: Не собирать dist/, не исправлять данные, не заменять unittest и аудит стандарта NUKE.
# INVARIANTS:код 0 только при отсутствии ошибок; ошибки копятся в errors; проверки не прерывают друг друга.
# DEPENDS:   build:PAGE_FILES, build:TYPE_LABELS, data:*, site-css:*, site-js:*, assets-img:*, nuke-log:EventLogger
# EXPOSES:   main, load, err, require, text, check_site, check_world, check_history, check_ethnoses, check_turns, check_gallery, check_table_part, check_buildings, check_links_and_misc, check_dist, check_link, PageScan
# ERRORS:    SystemExit(1) — найдена хотя бы одна ошибка (в main).
# TESTS:     T-VALIDATE-001, T-VALIDATE-002, T-VALIDATE-003, T-VALIDATE-004, T-VALIDATE-005, T-VALIDATE-006, T-VALIDATE-007, T-VALIDATE-008
# ==== END MODULE CONTRACT: validate ====
"""Проверка единого источника данных и собранного сайта."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DIST = ROOT / "dist"

sys.path.insert(0, str(ROOT))
from build import PAGE_FILES, TYPE_LABELS  # noqa: E402
from nuke_log import EventLogger  # noqa: E402  (после ROOT: журнал лежит в корне)

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

errors: list[str] = []
log = EventLogger("validate")


# START_BLOCK_VALIDATE_HELPERS: Накопление ошибок, чтение данных и запись исхода группы в журнал. #KEYWORDS: Helpers,Errors,Json,Log
# PURPOSE: Накопить сообщение об ошибке данных, чтобы main вернул код 1 после всех проверок.
# INPUTS:
#   message: str — текст ошибки; не пустой.
# OUTPUTS:
#   None — сообщение добавлено в общий список errors.
# ERRORS: нет.
# KEYWORDS: [Errors, Report, Collect, Validate]
# TESTS: [T-VALIDATE-002]
def err(message: str) -> None:
    errors.append(message)


# PURPOSE: Прочитать JSON-файл из data/, чтобы проверки работали с его содержимым.
# INPUTS:
#   rel: str — путь относительно data/; файл может отсутствовать.
# OUTPUTS:
#   object | None — разобранный JSON; None, если файла нет или JSON некорректен.
# ERRORS: нет исключений: ошибка чтения добавляется в errors.
# KEYWORDS: [Json, Load, Data, File]
# TESTS: [T-VALIDATE-001]
def load(rel: str):
    path = DATA / rel
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        err(f"нет файла данных data/{rel}")
    except json.JSONDecodeError as exc:
        err(f"data/{rel}: некорректный JSON — {exc}")
    return None


# PURPOSE: Убедиться, что обязательное поле присутствует и имеет ожидаемый тип.
# INPUTS:
#   obj: dict — проверяемый объект; key: str — имя поля; where: str — адрес для сообщения; kind — тип или None.
# OUTPUTS:
#   bool — True, если поле корректно; False, если ошибка добавлена в errors.
# ERRORS: нет исключений: отсутствующее или неверное поле попадает в errors.
# KEYWORDS: [Fields, Types, Require, Schema]
# TESTS: [T-VALIDATE-002]
def require(obj: dict, key: str, where: str, kind=None) -> bool:
    if key not in obj:
        err(f"{where}: отсутствует поле «{key}»")
        return False
    if kind is not None and not isinstance(obj[key], kind):
        err(f"{where}: поле «{key}» должно быть {kind.__name__}")
        return False
    return True


# PURPOSE: Проверить, что текстовое поле заполнено непустой строкой.
# INPUTS:
#   obj: dict — объект; key: str — имя поля; where: str — адрес для сообщения.
# OUTPUTS:
#   None — ошибка добавлена при необходимости.
# ERRORS: нет.
# KEYWORDS: [Text, Empty, Fields, Validate]
# TESTS: [T-VALIDATE-003]
def text(obj: dict, key: str, where: str) -> None:
    if require(obj, key, where, str) and not obj[key].strip():
        err(f"{where}: поле «{key}» пустое")


# PURPOSE: Опубликовать исход группы проверок в журнал, чтобы траекторию валидатора было видно в JSONL.
# INPUTS:
#   block: str — ID якоря группы; symbol: str — validate.<функция>; before: int — число ошибок до группы.
# OUTPUTS:
#   None; при выключенном NUKE_LOG — ничего.
# ERRORS: LogError — пустые поля события (не возникает при корректных вызовах).
# KEYWORDS: [Log, Event, Group, Outcome]
# TESTS: [T-VALIDATE-008]
def _group_event(block: str, symbol: str, before: int) -> None:
    outcome = "error" if len(errors) > before else "ok"
    log.event(
        block,
        "check",
        symbol,
        outcome,
        errors=len(errors),
        level="ERROR" if outcome == "error" else "INFO",
    )
# END_BLOCK_VALIDATE_HELPERS


# START_BLOCK_DATA_CHECKS: Проверки данных сайта, мира, летописи и народов. #KEYWORDS: Data,Site,World,History,Ethnos
# PURPOSE: Проверить site.json, чтобы меню вело на реально собираемые страницы.
# INPUTS:
#   page_names: set[str] — имена собираемых страниц; меню сверяется с ними.
# OUTPUTS:
#   None — ошибки добавляются в errors.
# ERRORS: нет.
# KEYWORDS: [Site, Menu, Pages, Meta]
# TESTS: [T-VALIDATE-001]
def check_site(page_names: set[str]) -> None:
    site = load("site.json")
    if not site:
        return
    for key in ("title", "subtitle", "tagline", "description", "base_url", "lang"):
        text(site, key, "site.json")
    if site.get("base_url") and not site["base_url"].endswith("/"):
        err("site.json: base_url должен заканчиваться слэшем")
    period = site.get("period", {})
    if not (isinstance(period.get("from"), int) and isinstance(period.get("to"), int)):
        err("site.json: period.from и period.to должны быть числами")

    menu = site.get("menu")
    if not isinstance(menu, list) or len(menu) < 3:
        err("site.json: menu должен содержать минимум 3 пункта")
        return
    seen_ids, seen_urls = set(), set()
    for index, item in enumerate(menu):
        where = f"site.json → menu[{index}]"
        if not isinstance(item, dict):
            err(f"{where}: ожидался объект")
            continue
        for key in ("id", "title", "url"):
            text(item, key, where)
        if item.get("id") in seen_ids:
            err(f"{where}: повторяющийся id «{item.get('id')}»")
        if item.get("url") in seen_urls:
            err(f"{where}: повторяющийся url «{item.get('url')}»")
        seen_ids.add(item.get("id"))
        seen_urls.add(item.get("url"))
        if item.get("url") not in page_names:
            err(f"{where}: url «{item.get('url')}» не соответствует ни одной странице")


# PURPOSE: Проверить world.json, чтобы раздел «Мир» был полным и непустым.
# INPUTS:
#   — (файл data/world.json).
# OUTPUTS:
#   None — ошибки добавляются в errors.
# ERRORS: нет.
# KEYWORDS: [World, Facts, Regions, Laws]
# TESTS: [T-VALIDATE-002]
def check_world() -> None:
    world = load("world.json")
    if not world:
        return
    text(world, "title", "world.json")
    text(world, "lead", "world.json")
    if not isinstance(world.get("intro"), list) or not world["intro"]:
        err("world.json: intro должен быть непустым списком")
    for index, fact in enumerate(world.get("facts", [])):
        where = f"world.json → facts[{index}]"
        text(fact, "label", where)
        text(fact, "value", where)
    for index, region in enumerate(world.get("regions", [])):
        where = f"world.json → regions[{index}]"
        text(region, "title", where)
        text(region, "text", where)
    for index, law in enumerate(world.get("laws", [])):
        where = f"world.json → laws[{index}]"
        for key in ("title", "text", "effect"):
            text(law, key, where)


# PURPOSE: Проверить history.json, чтобы эпохи, битвы и герои были описаны целиком.
# INPUTS:
#   — (файл data/history.json).
# OUTPUTS:
#   None — ошибки добавляются в errors.
# ERRORS: нет.
# KEYWORDS: [History, Epochs, Heroes, Battle]
# TESTS: [T-VALIDATE-003]
def check_history() -> None:
    history = load("history.json")
    if not history:
        return
    epochs = history.get("epochs", [])
    if not epochs:
        err("history.json: нет ни одной эпохи")
    seen = set()
    for index, epoch in enumerate(epochs):
        where = f"history.json → epochs[{index}]"
        for key in ("id", "number", "title", "years"):
            text(epoch, key, where)
        if epoch.get("id") in seen:
            err(f"{where}: повторяющийся id «{epoch.get('id')}»")
        seen.add(epoch.get("id"))
        if not epoch.get("blocks"):
            err(f"{where}: нет блоков")
        for block_index, block in enumerate(epoch.get("blocks", [])):
            text(block, "title", f"{where}.blocks[{block_index}]")
            text(block, "text", f"{where}.blocks[{block_index}]")
        battle = epoch.get("battle")
        if battle is not None:
            for key in ("name", "text", "result"):
                text(battle, key, f"{where}.battle")
            if not isinstance(battle.get("year"), int):
                err(f"{where}.battle: year должен быть числом")
        for hero_index, hero in enumerate(epoch.get("heroes", [])):
            where_hero = f"{where}.heroes[{hero_index}]"
            for key in ("name", "people", "text"):
                text(hero, key, where_hero)


# PURPOSE: Проверить ethnoses.json, чтобы у народов были уникальные id и канонический цвет.
# INPUTS:
#   — (файл data/ethnoses.json).
# OUTPUTS:
#   None — ошибки добавляются в errors.
# ERRORS: нет.
# KEYWORDS: [Ethnoses, Colors, Status, Ids]
# TESTS: [T-VALIDATE-004]
def check_ethnoses() -> None:
    data = load("ethnoses.json")
    if not data:
        return
    text(data, "intro", "ethnoses.json")
    seen = set()
    for index, item in enumerate(data.get("ethnoses", [])):
        where = f"ethnoses.json → ethnoses[{index}]"
        for key in ("id", "name", "color", "epithet", "analog", "geography", "description"):
            text(item, key, where)
        if item.get("id") in seen:
            err(f"{where}: повторяющийся id «{item.get('id')}»")
        seen.add(item.get("id"))
        if item.get("color") and not COLOR_RE.match(item["color"]):
            err(f"{where}: color должен быть в формате #rrggbb")
        if bool(item.get("status")) != bool(item.get("status_label")):
            err(f"{where}: status и status_label должны быть заполнены вместе")
# END_BLOCK_DATA_CHECKS


# START_BLOCK_TURN_CHECKS: Проверки ходов: нумерация, годы, события и карты. #KEYWORDS: Turns,Events,Years,Maps
# PURPOSE: Проверить ходы, чтобы номера и годы шли по порядку, а события имели известный тип.
# INPUTS:
#   — (каталог data/turns/*.json).
# OUTPUTS:
#   list[dict] — разобранные ходы для итогового сообщения main.
# ERRORS: нет: ошибки добавлены в errors, список может быть неполным.
# KEYWORDS: [Turns, Events, Years, Sequence]
# TESTS: [T-VALIDATE-005]
def check_turns() -> list[dict]:
    directory = DATA / "turns"
    paths = sorted(directory.glob("*.json"))
    if not paths:
        err("data/turns: нет ни одного хода")
        return []

    turns = []
    for path in paths:
        turn = load(f"turns/{path.name}")
        if turn is not None:
            turns.append(turn)

    numbers = []
    years = []
    for turn in turns:
        label = f"turns/{turn.get('number', '?')}.json"
        for key in ("number", "year", "title", "lead"):
            if key not in turn:
                err(f"{label}: отсутствует поле «{key}»")
        if not isinstance(turn.get("number"), int):
            err(f"{label}: number должен быть числом")
        if not isinstance(turn.get("year"), int):
            err(f"{label}: year должен быть числом")
        numbers.append(turn.get("number"))
        years.append(turn.get("year"))
        text(turn, "title", label)
        text(turn, "lead", label)

        events = turn.get("events")
        if not isinstance(events, list) or len(events) < 1:
            err(f"{label}: events должен быть непустым списком")
            continue
        for index, event in enumerate(events):
            where = f"{label} → events[{index}]"
            for key in ("type", "title", "text"):
                text(event, key, where)
            if event.get("type") not in TYPE_LABELS:
                err(f"{where}: неизвестный тип события «{event.get('type')}»")
        if turn.get("map"):
            image = turn["map"].get("image", "")
            text(turn["map"], "caption", f"{label}.map")
            if not (ROOT / image).is_file():
                err(f"{label}: нет изображения карты {image}")

    if numbers and numbers[0] != 1:
        err(f"turns: первый ход должен иметь номер 1, получено {numbers[0]}")
    if numbers != sorted(set(numbers)):
        err(f"turns: номера ходов должны возрастать без повторов, получено {numbers}")
    # Пропуск хода — не ошибка данных, но о нём нужно сказать вслух:
    # перенести в JSON успевают не все ходы, а нумерация приходит из источника.
    gaps = sorted(set(range(1, max(numbers) + 1)) - set(numbers)) if numbers else []
    if gaps:
        missing = ", ".join(str(number) for number in gaps)
        print(f"Внимание: ходы {missing} в data/turns отсутствуют — хроника идёт с пропуском")
    if years != sorted(years):
        err(f"turns: годы ходов должны возрастать, получено {years}")
    if len(set(years)) != len(years):
        err("turns: годы ходов повторяются")

    return turns
# END_BLOCK_TURN_CHECKS


# START_BLOCK_GALLERY_CHECKS: Проверки галереи карт и таблиц. #KEYWORDS: Gallery,Maps,Tables,Categories
# PURPOSE: Проверить галерею, чтобы карты и таблицы ссылались на объявленные категории и файлы.
# INPUTS:
#   — (файлы data/maps.json и data/tables.json).
# OUTPUTS:
#   tuple[dict | None, dict | None] — разобранные maps и tables для возможного расширения.
# ERRORS: нет: ошибки добавлены в errors.
# KEYWORDS: [Gallery, Maps, Tables, Categories]
# TESTS: [T-VALIDATE-001]
def check_gallery() -> tuple[dict | None, dict | None]:
    maps = load("maps.json")
    tables = load("tables.json")

    if maps:
        categories = {item.get("id") for item in maps.get("categories", [])}
        seen = set()
        for index, item in enumerate(maps.get("maps", [])):
            where = f"maps.json → maps[{index}]"
            for key in ("id", "title", "caption", "file"):
                text(item, key, where)
            if item.get("id") in seen:
                err(f"{where}: повторяющийся id «{item.get('id')}»")
            seen.add(item.get("id"))
            if item.get("category") not in categories:
                err(f"{where}: неизвестная категория «{item.get('category')}»")
            if item.get("file") and not (ROOT / item["file"]).is_file():
                err(f"{where}: нет файла {item.get('file')}")

    if tables:
        seen = set()
        for index, item in enumerate(tables.get("tables", [])):
            where = f"tables.json → tables[{index}]"
            for key in ("id", "title", "caption"):
                text(item, key, where)
            if item.get("id") in seen:
                err(f"{where}: повторяющийся id «{item.get('id')}»")
            seen.add(item.get("id"))
            if item.get("file") and not (ROOT / item["file"]).is_file():
                err(f"{where}: нет файла {item.get('file')}")
            check_table_part(item, where)

    return maps, tables


# PURPOSE: Проверить таблицу без картинки, чтобы число ячеек в строке совпадало с числом колонок.
# INPUTS:
#   item: dict — запись data/tables.json; where: str — адрес для сообщения.
# OUTPUTS:
#   None — ошибки добавляются в errors.
# ERRORS: нет.
# KEYWORDS: [Table, Columns, Rows, Cells]
# TESTS: [T-VALIDATE-001]
def check_table_part(item: dict, where: str) -> None:
    """Таблица без картинки: колонки и строки с одинаковым числом ячеек."""
    if item.get("file"):
        if item.get("rows") or item.get("columns"):
            err(f"{where}: таблица либо файл, либо строки — не оба сразу")
        return

    columns = item.get("columns")
    rows = item.get("rows")
    if not isinstance(columns, list) or not columns:
        err(f"{where}: нужен файл таблицы или непустые columns")
        return
    for column in columns:
        if not isinstance(column, str) or not column.strip():
            err(f"{where}: columns должен состоять из непустых строк")
    if not isinstance(rows, list) or not rows:
        err(f"{where}: нужен непустой rows")
        return
    for row_index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(columns):
            err(f"{where} → rows[{row_index}]: ожидалось {len(columns)} ячеек")
            continue
        for cell in row:
            if not isinstance(cell, str) or not cell.strip():
                err(f"{where} → rows[{row_index}]: пустая ячейка")
# END_BLOCK_GALLERY_CHECKS


# START_BLOCK_BUILDING_CHECKS: Проверки категорий, местных правил и перекрёстных ссылок построек. #KEYWORDS: Buildings,Categories,Rules,References
# PURPOSE: Проверить постройки, чтобы категории и местные правила ссылались друг на друга.
# INPUTS:
#   — (файл data/buildings.json).
# OUTPUTS:
#   None — ошибки добавляются в errors.
# ERRORS: нет.
# KEYWORDS: [Buildings, Categories, Rules, References]
# TESTS: [T-VALIDATE-002]
def check_buildings() -> None:
    """Постройки: категории, местные правила и перекрёстные ссылки."""
    data = load("buildings.json")
    if not data:
        return
    for key in ("title", "lead", "intro", "note", "description"):
        text(data, key, "buildings.json")

    categories = data.get("categories", [])
    if not categories:
        err("buildings.json: нет ни одной категории")
    category_ids = set()
    for index, category in enumerate(categories):
        where = f"buildings.json → categories[{index}]"
        for key in ("id", "title", "intro"):
            text(category, key, where)
        if category.get("id") in category_ids:
            err(f"{where}: повторяющийся id «{category.get('id')}»")
        category_ids.add(category.get("id"))

    changes = data.get("changes", [])
    if not changes:
        err("buildings.json: нет ни одного местного правила")
    change_ids = set()
    links: dict[str, set[str]] = {}
    for index, change in enumerate(changes):
        where = f"buildings.json → changes[{index}]"
        for key in ("id", "title", "text"):
            text(change, key, where)
        if change.get("id") in change_ids:
            err(f"{where}: повторяющийся id «{change.get('id')}»")
        change_ids.add(change.get("id"))
        ids = change.get("buildings")
        if not isinstance(ids, list) or not ids:
            err(f"{where}: buildings должен быть непустым списком id")
            continue
        for building_id in ids:
            links.setdefault(building_id, set()).add(change.get("id"))

    buildings = data.get("buildings", [])
    if not buildings:
        err("buildings.json: нет ни одной постройки")
    seen = set()
    rules: dict[str, str] = {}
    for index, building in enumerate(buildings):
        where = f"buildings.json → buildings[{index}]"
        for key in ("id", "name", "category", "location"):
            text(building, key, where)
        if building.get("id") in seen:
            err(f"{where}: повторяющийся id «{building.get('id')}»")
        seen.add(building.get("id"))
        if building.get("category") not in category_ids:
            err(f"{where}: неизвестная категория «{building.get('category')}»")
        rule = building.get("local_rule")
        if rule:
            if rule not in change_ids:
                err(f"{where}: неизвестное местное правило «{rule}»")
            else:
                rules[building.get("id")] = rule

    for building_id, change_ids_for_building in links.items():
        if building_id not in seen:
            err(f"buildings.json: местное правило ссылается на неизвестную постройку «{building_id}»")
            continue
        for change_id in change_ids_for_building:
            if rules.get(building_id) != change_id:
                err(
                    f"buildings.json: постройка «{building_id}» не отмечена правилом «{change_id}»"
                )

    for building_id, rule in rules.items():
        if rule not in links.get(building_id, set()):
            err(f"buildings.json: правило «{rule}» не ссылается на постройку «{building_id}»")
# END_BLOCK_BUILDING_CHECKS


# START_BLOCK_LINK_ASSET_CHECKS: Проверки ссылок, рассадки, лога изменений и статических ассетов. #KEYWORDS: Links,Assets,Changelog,Participants
# PURPOSE: Проверить ссылки, лог изменений и ассеты, чтобы на сайте не было внешних битых адресов.
# INPUTS:
#   — (data/links.json, participants.json, changelog.json и assets/).
# OUTPUTS:
#   None — ошибки добавляются в errors.
# ERRORS: нет.
# KEYWORDS: [Links, Assets, Changelog, Participants]
# TESTS: [T-VALIDATE-007]
def check_links_and_misc() -> None:
    links = load("links.json")
    if links:
        seen = set()
        for index, item in enumerate(links.get("links", [])):
            where = f"links.json → links[{index}]"
            for key in ("id", "title", "url", "description"):
                text(item, key, where)
            if item.get("id") in seen:
                err(f"{where}: повторяющийся id «{item.get('id')}»")
            seen.add(item.get("id"))
            if item.get("url") and not item["url"].startswith(("http://", "https://")):
                err(f"{where}: url должен начинаться с http(s)://")

    participants = load("participants.json")
    if participants:
        for key in ("title", "intro", "image"):
            text(participants, key, "participants.json")
        if not isinstance(participants.get("count"), int):
            err("participants.json: count должен быть числом")
        if participants.get("image") and not (ROOT / participants["image"]).is_file():
            err(f"participants.json: нет файла {participants['image']}")

    changelog = load("changelog.json")
    if changelog:
        for index, entry in enumerate(changelog.get("entries", [])):
            where = f"changelog.json → entries[{index}]"
            text(entry, "date", where)
            text(entry, "text", where)
            if entry.get("date") and not DATE_RE.match(entry["date"]):
                err(f"{where}: date должен быть в формате ГГГГ-ММ-ДД")
            elif entry.get("date"):
                try:
                    datetime.strptime(entry["date"], "%Y-%m-%d")
                except ValueError:
                    err(f"{where}: некорректная дата {entry['date']}")

    for asset in ("assets/css/style.css", "assets/js/site.js", "assets/img/favicon.svg"):
        if not (ROOT / asset).is_file():
            err(f"нет ассета {asset}")
# END_BLOCK_LINK_ASSET_CHECKS


# START_BLOCK_PAGE_SCAN: Разбор собранной HTML-страницы для проверки meta, h1 и ссылок. #KEYWORDS: Html,Parser,Links,Anchors
# PURPOSE: Собрать из HTML идентификаторы, ссылки, заголовок и meta description для проверки dist.
# INPUTS:
#   html: str — содержимое собранной страницы (передаётся через feed).
# OUTPUTS:
#   объект с полями ids, links, h1, title, description.
# ERRORS: нет: HTMLParser разбирает повреждённую разметку без исключений.
# KEYWORDS: [Html, Parser, Links, Anchors]
# TESTS: [T-VALIDATE-006]
class PageScan(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.h1 = 0
        self.title = ""
        self.description = ""
        self._in_title = False
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if data.get("id"):
            self.ids.add(data["id"])
        for attribute in ("href", "src"):
            if data.get(attribute):
                self.links.append(data[attribute])
        if data.get("name") == "description":
            self.description = data.get("content", "")
        if tag == "title":
            self._in_title = True
        if tag == "h1":
            self.h1 += 1
            self._in_h1 = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "h1":
            self._in_h1 = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_h1:
            self.title += ""
# END_BLOCK_PAGE_SCAN


# START_BLOCK_DIST_CHECKS: Проверка собранного сайта: страницы, meta, h1 и обход ссылок. #KEYWORDS: Dist,Pages,Meta,Links
# PURPOSE: Проверить dist, чтобы каждая страница имела заголовок, описание и ровно один h1.
# INPUTS:
#   — (каталог dist/ и PAGE_FILES сборки).
# OUTPUTS:
#   None — ошибки добавляются в errors; ссылки проверяются через check_link.
# ERRORS: нет: отсутствие dist/ фиксируется как ошибка данных.
# KEYWORDS: [Dist, Pages, Meta, Links]
# TESTS: [T-VALIDATE-008]
def check_dist() -> None:
    before = len(errors)
    if not DIST.is_dir():
        err("нет каталога dist — сначала запустите python build.py")
        _group_event("DIST_CHECKS", "validate.check_dist", before)
        return

    scans: dict[Path, PageScan] = {}
    pages = sorted(DIST.glob("*.html"))
    for page in pages:
        scan = PageScan()
        scan.feed(page.read_text(encoding="utf-8"))
        scans[page] = scan
        if not scan.title.strip():
            err(f"{page.name}: пустой <title>")
        if page.name != "404.html" and not scan.description.strip():
            err(f"{page.name}: пустая meta description")
        if scan.h1 != 1:
            err(f"{page.name}: должен быть ровно один <h1>, найдено {scan.h1}")

    for page in PAGE_FILES:
        if not (DIST / page).is_file():
            err(f"не собрана страница {page}")

    _group_event("DIST_CHECKS", "validate.check_dist", before)

    links_before = len(errors)
    total_links = 0
    for page, scan in scans.items():
        for link in scan.links:
            total_links += 1
            check_link(page, link, scans)

    print(f"Ссылки: проверено {len(pages)} страниц, {total_links} ссылок")
    _group_event("DIST_LINKS", "validate.check_link", links_before)
# END_BLOCK_DIST_CHECKS


# START_BLOCK_DIST_LINKS: Проверка одной ссылки и её якоря внутри dist. #KEYWORDS: Links,Anchor,Target,Schemes
# PURPOSE: Проверить одну ссылку страницы, чтобы она вела на существующий файл и якорь сайта.
# INPUTS:
#   page: Path — страница-источник; link: str — адрес; scans: dict[Path, PageScan] — разобранные страницы.
# OUTPUTS:
#   None — ошибка добавлена при нарушении цели.
# ERRORS: нет.
# KEYWORDS: [Links, Anchor, Target, Schemes]
# TESTS: [T-VALIDATE-005]
def check_link(page: Path, link: str, scans: dict[Path, PageScan]) -> None:
    if link.startswith(("http://", "https://", "mailto:", "tel:", "javascript:")):
        return
    parts = urlsplit(link)
    target_path = unquote(parts.path)
    fragment = parts.fragment

    if target_path == "":
        target = page
    else:
        target = (page.parent / target_path).resolve()

    try:
        target.relative_to(DIST.resolve())
    except ValueError:
        err(f"{page.name}: ссылка выходит за пределы сайта — {link}")
        return

    if not target.is_file():
        err(f"{page.name}: битая ссылка — {link}")
        return

    if fragment:
        scan = scans.get(target)
        if scan is None and target.suffix == ".html":
            scan = PageScan()
            scan.feed(target.read_text(encoding="utf-8"))
            scans[target] = scan
        if scan is not None and fragment not in scan.ids:
            err(f"{page.name}: нет якоря #{fragment} в {target.name}")
# END_BLOCK_DIST_LINKS


# START_BLOCK_MAIN: CLI и порядок групп проверок валидатора. #KEYWORDS: Cli,Report,Order,ExitCode
# PURPOSE: Запустить все проверки в прежнем порядке и вернуть код возврата для CI.
# INPUTS:
#   argv: list[str] | None — аргументы CLI; поддерживается флаг --dist.
# OUTPUTS:
#   int — 0 при отсутствии ошибок, 1 при найденной хотя бы одной ошибке.
# ERRORS: SystemExit(1) — при найденных ошибках (через __main__).
# SIDE EFFECTS: печать отчёта в stdout/stderr и событий в NUKE_LOG при его включении.
# KEYWORDS: [Cli, Report, Order, ExitCode]
# TESTS: [T-VALIDATE-008]
def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка данных и собранного сайта")
    parser.add_argument("--dist", action="store_true", help="проверить ссылки в dist/")
    args = parser.parse_args()

    page_names = set(PAGE_FILES) | {"index.html"}
    before = len(errors)
    check_site(page_names)
    check_world()
    check_history()
    check_ethnoses()
    _group_event("DATA_CHECKS", "validate.check_site", before)

    before = len(errors)
    turns = check_turns()
    _group_event("TURN_CHECKS", "validate.check_turns", before)

    before = len(errors)
    check_gallery()
    _group_event("GALLERY_CHECKS", "validate.check_gallery", before)

    before = len(errors)
    check_buildings()
    _group_event("BUILDING_CHECKS", "validate.check_buildings", before)

    before = len(errors)
    check_links_and_misc()
    _group_event("LINK_ASSET_CHECKS", "validate.check_links_and_misc", before)

    if errors:
        print(f"Найдено ошибок: {len(errors)}", file=sys.stderr)
        for message in errors:
            print(f"  • {message}", file=sys.stderr)
        _group_event("MAIN", "validate.main", 0)
        return 1

    events = sum(len(turn.get("events", [])) for turn in turns)
    print(f"Данные: OK — {len(turns)} хода, {events} событий")

    if args.dist:
        check_dist()
        if errors:
            print(f"Найдено ошибок в dist: {len(errors)}", file=sys.stderr)
            for message in errors:
                print(f"  • {message}", file=sys.stderr)
            _group_event("MAIN", "validate.main", 0)
            return 1

    _group_event("MAIN", "validate.main", len(errors))
    return 0
# END_BLOCK_MAIN


if __name__ == "__main__":
    raise SystemExit(main())
