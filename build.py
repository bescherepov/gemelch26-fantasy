#!/usr/bin/env python3
"""Сборка сайта «Расфадаль» из единого источника данных.

Единственный вход — каталог data/*.json. Всё, что попадает в dist/,
является производным от этих файлов, шаблонов и статических ассетов.
Никаких внешних зависимостей: только стандартная библиотека Python.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

from engine import Safe, TemplateError, TemplateSet

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TEMPLATES = ROOT / "templates"
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"

TYPE_LABELS = {
    "politics": "Политика",
    "war": "Война",
    "diplomacy": "Дипломатия",
    "dynasty": "Династия",
    "religion": "Религия",
    "disaster": "Катастрофа",
    "economy": "Экономика",
    "city": "Город",
    "culture": "Культура",
    "migration": "Переселение",
}

PAGE_FILES = [
    "index.html",
    "world.html",
    "ethnoses.html",
    "turns.html",
    "maps.html",
    "tables.html",
    "buildings.html",
    "participants.html",
    "log.html",
    "links.html",
]


def fail(message: str) -> None:
    print(f"Ошибка сборки: {message}", file=sys.stderr)
    raise SystemExit(1)


def plural(number: int, one: str, few: str, many: str) -> str:
    tail, hundred = number % 10, number % 100
    if tail == 1 and hundred != 11:
        return one
    if 2 <= tail <= 4 and not 12 <= hundred <= 14:
        return few
    return many


def load_json(path: Path):
    if not path.is_file():
        fail(f"нет файла данных {path.relative_to(ROOT)}")
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        fail(f"{path.relative_to(ROOT)}: некорректный JSON — {exc}")


def prepare_turns(raw_turns: list[dict]) -> list[dict]:
    turns = sorted(raw_turns, key=lambda item: item["number"])
    for turn in turns:
        for event in turn["events"]:
            event["type_label"] = TYPE_LABELS.get(event["type"], event["type"])
        counts = {}
        for event in turn["events"]:
            counts[event["type"]] = counts.get(event["type"], 0) + 1
        turn["type_counts"] = [
            {"id": key, "label": TYPE_LABELS[key], "count": counts[key]}
            for key in TYPE_LABELS
            if key in counts
        ]
    for index, turn in enumerate(turns):
        turn["prev"] = turns[index - 1] if index > 0 else None
        turn["next"] = turns[index + 1] if index + 1 < len(turns) else None
    return turns


def build_type_stats(turns: list[dict]) -> list[dict]:
    counts = {}
    for turn in turns:
        for event in turn["events"]:
            counts[event["type"]] = counts.get(event["type"], 0) + 1
    if not counts:
        return []
    top = max(counts.values())
    return [
        {
            "id": key,
            "label": TYPE_LABELS[key],
            "count": counts[key],
            "width": round(counts[key] / top * 100),
        }
        for key in TYPE_LABELS
        if key in counts
    ]


def check_assets(turns: list[dict], maps: dict, tables: dict) -> None:
    referenced: set[str] = set()
    for turn in turns:
        if turn.get("map"):
            referenced.add(turn["map"]["image"])
    for item in maps["maps"]:
        referenced.add(item["file"])
    for item in tables["tables"]:
        referenced.add(item["file"])
    referenced.add("assets/img/favicon.svg")
    missing = [path for path in sorted(referenced) if not (ROOT / path).is_file()]
    if missing:
        fail("не найдены изображения: " + ", ".join(missing))


FACT_FIELDS = (
    ("cost", "Стоимость"),
    ("income", "Доход"),
    ("base", "Производство"),
    ("input", "Сырьё"),
    ("conditions", "Требования"),
    ("resource", "Ресурс"),
    ("location", "Где"),
    ("climate", "Климат"),
    ("terrain", "Местность"),
    ("bonuses", "Инновации и традиции"),
)


def prepare_buildings(raw: dict) -> dict:
    """Раскладывает постройки по категориям и связывает их с местными правилами."""
    buildings = raw["buildings"]
    by_id = {building["id"]: building for building in buildings}
    changes = {change["id"]: change for change in raw["changes"]}

    for change in raw["changes"]:
        items = []
        for building_id in change["buildings"]:
            if building_id not in by_id:
                fail(f"buildings.json: правило «{change['id']}» ссылается на неизвестную постройку {building_id}")
            items.append(by_id[building_id])
        change["items"] = items

    for building in buildings:
        rule = building.get("local_rule")
        if rule and rule not in changes:
            fail(f"buildings.json: у постройки «{building['name']}» неизвестное правило «{rule}»")
        building["local"] = changes.get(rule) if rule else None
        building["has_group"] = bool(building["group"]) and building["group"] != building["name"]
        building["facts"] = [
            {"label": label, "value": building[key].strip()}
            for key, label in FACT_FIELDS
            if building[key].strip()
            and building[key].strip() != "—"
            and not (key == "resource" and building[key].strip() == "нет")
            and not (key in ("climate", "terrain") and building[key].strip().lower() == "все")
        ]

    for category in raw["categories"]:
        category["items"] = [
            building for building in buildings if building["category"] == category["id"]
        ]
        category["count"] = len(category["items"])

    raw["total"] = len(buildings)
    return raw


def build() -> None:
    site = load_json(DATA / "site.json")
    world = load_json(DATA / "world.json")
    history = load_json(DATA / "history.json")
    ethnoses = load_json(DATA / "ethnoses.json")
    maps = load_json(DATA / "maps.json")
    tables = load_json(DATA / "tables.json")
    buildings = prepare_buildings(load_json(DATA / "buildings.json"))
    links = load_json(DATA / "links.json")
    participants = load_json(DATA / "participants.json")
    changelog = load_json(DATA / "changelog.json")

    turn_files = sorted((DATA / "turns").glob("*.json"))
    if not turn_files:
        fail("в data/turns нет ни одного хода")
    turns = prepare_turns([load_json(path) for path in turn_files])

    check_assets(turns, maps, tables)

    latest = turns[-1]
    stats = {
        "turns": len(turns),
        "events": sum(len(turn["events"]) for turn in turns),
        "ethnoses": len(ethnoses["ethnoses"]),
        "maps": len(maps["maps"]),
        "buildings": buildings["total"],
        "years": f"{turns[0]['year']}–{latest['year']}",
    }

    stamp = os.environ.get("SOURCE_DATE_EPOCH")
    today = (
        datetime.fromtimestamp(int(stamp)).date() if stamp else date.today()
    )
    build_info = {
        "date_iso": today.isoformat(),
        "date_ru": today.strftime("%d.%m.%Y"),
        "year": today.year,
    }

    changelog["entries"] = sorted(
        changelog["entries"], key=lambda item: item["date"], reverse=True
    )

    hero_map = next(
        (item for item in maps["maps"] if item["id"] == "political-905"),
        maps["maps"][0],
    )
    preview_maps = maps["maps"][:3]
    latest_preview = latest["events"][:5]
    type_stats = build_type_stats(turns)

    jsonld = Safe(
        json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": f"{site['title']}. {site['subtitle']}",
                "url": site["base_url"],
                "inLanguage": site["lang"],
                "description": site["description"],
            },
            ensure_ascii=False,
        )
    )

    templates = TemplateSet(TEMPLATES)
    context = {
        "site": site,
        "world": world,
        "history": history,
        "ethnoses": ethnoses,
        "maps": maps,
        "tables": tables,
        "buildings": buildings,
        "links": links,
        "participants": participants,
        "changelog": changelog,
        "turns": turns,
        "latest": latest,
        "latest_preview": latest_preview,
        "preview_maps": preview_maps,
        "hero_map": hero_map,
        "type_stats": type_stats,
        "jsonld": jsonld,
        "stats": stats,
        "build": build_info,
    }

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    pages = [
        ("index.html", "index.html", "index", "Главная", site["description"]),
        ("world.html", "world.html", "world", "Мир", world["lead"]),
        ("ethnoses.html", "ethnoses.html", "ethnoses", "Этносы", ethnoses["intro"]),
        ("turns.html", "turns.html", "turns", "Ходы", "Хроника партии по ходам: события, войны и решения."),
        ("maps.html", "maps.html", "maps", "Карты", maps["intro"]),
        ("tables.html", "tables.html", "tables", "Таблицы", tables["intro"]),
        ("buildings.html", "buildings.html", "buildings", "Постройки", buildings["description"]),
        ("participants.html", "participants.html", "participants", "Рассадка", participants["intro"]),
        ("log.html", "log.html", "log", "Лог", "История изменений сайта и хроники."),
        ("links.html", "links.html", "links", "Ссылки", "Первоисточники и материалы партии."),
    ]

    for filename, template_name, page_id, title, description in pages:
        page = {
            "id": page_id,
            "title": title,
            "description": description,
            "file": filename,
        }
        local = {**context, "page": page}
        content = templates.render(template_name, local)
        document = templates.render("base.html", {**local, "content": Safe(content)})
        (DIST / filename).write_text(document, encoding="utf-8", newline="\n")

    not_found = templates.render("404.html", {**context, "page": {"id": "404"}})
    (DIST / "404.html").write_text(not_found, encoding="utf-8", newline="\n")

    shutil.copytree(ASSETS, DIST / "assets", dirs_exist_ok=True)

    (DIST / ".nojekyll").write_text("", encoding="utf-8")

    base = site["base_url"].rstrip("/") + "/"
    locations = "\n".join(
        f"  <url><loc>{base}{name}</loc><lastmod>{build_info['date_iso']}</lastmod></url>"
        for name in PAGE_FILES
    )
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{locations}\n"
        "</urlset>\n"
    )
    (DIST / "sitemap.xml").write_text(sitemap, encoding="utf-8", newline="\n")
    (DIST / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\nSitemap: " + base + "sitemap.xml\n",
        encoding="utf-8",
        newline="\n",
    )

    print(
        "Собрано: "
        f"{len(PAGE_FILES) + 1} страниц, "
        f"{stats['turns']} {plural(stats['turns'], 'ход', 'хода', 'ходов')}, "
        f"{stats['events']} {plural(stats['events'], 'событие', 'события', 'событий')}, "
        f"{stats['ethnoses']} {plural(stats['ethnoses'], 'народ', 'народа', 'народов')}, "
        f"{stats['maps']} {plural(stats['maps'], 'карта', 'карты', 'карт')}, "
        f"{stats['buildings']} {plural(stats['buildings'], 'постройка', 'постройки', 'построек')} → dist/"
    )


if __name__ == "__main__":
    try:
        build()
    except TemplateError as exc:
        fail(str(exc))
