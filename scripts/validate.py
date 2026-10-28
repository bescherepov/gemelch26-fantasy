#!/usr/bin/env python3
"""Проверка единого источника данных и собранного сайта.

Запуск:
    python scripts/validate.py           # только данные
    python scripts/validate.py --dist    # данные + ссылки в dist/

Код возврата 1, если найдена хотя бы одна ошибка.
"""

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

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

errors: list[str] = []


def err(message: str) -> None:
    errors.append(message)


def load(rel: str):
    path = DATA / rel
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        err(f"нет файла данных data/{rel}")
    except json.JSONDecodeError as exc:
        err(f"data/{rel}: некорректный JSON — {exc}")
    return None


def require(obj: dict, key: str, where: str, kind=None) -> bool:
    if key not in obj:
        err(f"{where}: отсутствует поле «{key}»")
        return False
    if kind is not None and not isinstance(obj[key], kind):
        err(f"{where}: поле «{key}» должно быть {kind.__name__}")
        return False
    return True


def text(obj: dict, key: str, where: str) -> None:
    if require(obj, key, where, str) and not obj[key].strip():
        err(f"{where}: поле «{key}» пустое")


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

    if numbers != list(range(1, len(numbers) + 1)):
        err(f"turns: номера ходов должны идти подряд с 1, получено {numbers}")
    if years != sorted(years):
        err(f"turns: годы ходов должны возрастать, получено {years}")
    if len(set(years)) != len(years):
        err("turns: годы ходов повторяются")

    return turns


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
            for key in ("id", "title", "file"):
                text(item, key, where)
            if item.get("id") in seen:
                err(f"{where}: повторяющийся id «{item.get('id')}»")
            seen.add(item.get("id"))
            if item.get("file") and not (ROOT / item["file"]).is_file():
                err(f"{where}: нет файла {item.get('file')}")

    return maps, tables


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


# --------------------------------------------------------------------------- #
# Проверка собранного сайта
# --------------------------------------------------------------------------- #


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


def check_dist() -> None:
    if not DIST.is_dir():
        err("нет каталога dist — сначала запустите python build.py")
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

    total_links = 0
    for page, scan in scans.items():
        for link in scan.links:
            total_links += 1
            check_link(page, link, scans)

    print(f"Ссылки: проверено {len(pages)} страниц, {total_links} ссылок")


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка данных и собранного сайта")
    parser.add_argument("--dist", action="store_true", help="проверить ссылки в dist/")
    args = parser.parse_args()

    page_names = set(PAGE_FILES) | {"index.html"}
    check_site(page_names)
    check_world()
    check_history()
    check_ethnoses()
    turns = check_turns()
    check_gallery()
    check_buildings()
    check_links_and_misc()

    if errors:
        print(f"Найдено ошибок: {len(errors)}", file=sys.stderr)
        for message in errors:
            print(f"  • {message}", file=sys.stderr)
        return 1

    events = sum(len(turn.get("events", [])) for turn in turns)
    print(f"Данные: OK — {len(turns)} хода, {events} событий")

    if args.dist:
        check_dist()
        if errors:
            print(f"Найдено ошибок в dist: {len(errors)}", file=sys.stderr)
            for message in errors:
                print(f"  • {message}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
