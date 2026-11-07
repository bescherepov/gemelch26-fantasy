#!/usr/bin/env python3
# ==== MODULE CONTRACT: build ====
# PURPOSE:   Собирать статический сайт хроники из data/ в dist/, чтобы публикация шла из единственного источника без сети и внешних пакетов.
# SCOPE:     загрузка JSON, подготовка ходов, построек и таблиц, статистика типов, проверка изображений, контекст шаблонов, рендер страниц, запись dist/, sitemap и robots.
# NON-GOALS: не хранить игровой контент и не проверять его полноту (scripts/validate.py), не публиковать сайт (CI), не писать журнал при выключенном NUKE_LOG.
# INVARIANTS:dist/ — производное от data/, templates/ и assets/; сборка без сети, случайности и текущего времени в контенте (дата — только подвал и sitemap); при выключенном журнале вывод и dist/ не меняются.
# DEPENDS:   engine:TemplateSet, data:*, templates:*, site-css:*, site-js:*, assets-img:*, nuke-log:EventLogger
# EXPOSES:   build, prepare_turns, prepare_buildings, prepare_tables, build_type_stats, check_assets, load_json, fail, plural, TYPE_LABELS, PAGE_FILES, BUILDING_DETAIL_FIELDS, HEAT_LEVELS
# ERRORS:    SystemExit(1) — нет файла данных, битый JSON или отсутствующее изображение; TemplateError — ошибка шаблона.
# TESTS:     T-BUILD-001, T-BUILD-002, T-BUILD-003, T-BUILD-004, T-BUILD-005, T-BUILD-006, T-BUILD-007, T-BUILD-008, T-BUILD-009, T-BUILD-010, T-BUILD-011, T-BUILD-012, T-BUILD-013, T-BUILD-014, T-BUILD-015, T-BUILD-016, T-BUILD-017
# ==== END MODULE CONTRACT: build ====
"""Собрать сайт «Расфадаль» из data/ в dist/ без внешних зависимостей и сети."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

from engine import Safe, TemplateError, TemplateSet, plural_ru
from nuke_log import EventLogger

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TEMPLATES = ROOT / "templates"
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"

# PURPOSE: Вести журнал шагов сборки для сверки траектории по §9, не меняя вывод при выключенном NUKE_LOG.
log = EventLogger("build")

# PURPOSE: Сопоставить тип события хода с подписью бейджа, чтобы шаблоны не знали кодов типов.
# KEYWORDS: [Labels, Types, Badges, Turn]
# TESTS: [T-BUILD-005]
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

# PURPOSE: Задать полный список собираемых страниц как единственный источник для sitemap и проверок.
# KEYWORDS: [Pages, Sitemap, Routes, Files]
# TESTS: [T-BUILD-003]
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


# START_BLOCK_FAIL_FAST: Аварийный выход сборки с понятным сообщением. #KEYWORDS: Fail,Error,Exit,Diagnostics
# PURPOSE: Прервать сборку с внятным сообщением, чтобы ошибка данных не давала молча битый dist/.
# INPUTS:
#   message: str — что именно сломалось; не пусто.
# OUTPUTS:
#   нет: управление не возвращается.
# ERRORS:
#   SystemExit(1) — всегда, сразу после печати сообщения.
# SIDE EFFECTS: печать строки «Ошибка сборки: …» в stderr.
# PRECONDITIONS: message уже содержит имя файла и поле — диагностика не досочиняется.
# POSTCONDITIONS: процесс завершён с кодом 1; dist/ после вызова не меняется.
# KEYWORDS: [Fail, Error, ExitCode, Diagnostics, Stderr]
# TESTS: [T-BUILD-001, T-BUILD-012]
def fail(message: str) -> None:
    print(f"Ошибка сборки: {message}", file=sys.stderr)
    raise SystemExit(1)
# END_BLOCK_FAIL_FAST


# START_BLOCK_PLURAL_RU: Согласование числительных с существительными в отчёте сборки. #KEYWORDS: Plural,Ru,Report,Declension
# PURPOSE: Согласовать число с существительным для итоговой строки сборки, чтобы отчёт читался по-русски.
# INPUTS:
#   number: int — количество, целое, >= 0.
#   one/few/many: str — словоформы для 1, 2–4 и прочих чисел.
# OUTPUTS:
#   str — выбранная словоформа.
# SIDE EFFECTS: нет.
# ERRORS: нет: при нуле и нецелых числах возвращается форма «many».
# PRECONDITIONS: number — целое; словоформы заданы вызывающим кодом.
# POSTCONDITIONS: возвращённая форма согласована с number по правилам русского языка.
# INVARIANTS: результат не зависит от времени, локали и порядка вызовов.
# KEYWORDS: [Plural, Russian, Declension, Report]
# TESTS: [T-BUILD-001]
def plural(number: int, one: str, few: str, many: str) -> str:
    return plural_ru(number, one, few, many)
# END_BLOCK_PLURAL_RU


# START_BLOCK_LOAD_JSON: Чтение JSON-источника с ошибкой сборки вместо трейсбека. #KEYWORDS: Load,Json,File,Error
# PURPOSE: Прочитать JSON-источник данных, превратив отсутствие файла и битый JSON в понятную ошибку сборки с событием журнала.
# INPUTS:
#   path: Path — путь к файлу в data/; файл может отсутствовать или быть некорректным.
# OUTPUTS:
#   object — разобранное содержимое JSON без преобразований.
# ERRORS:
#   SystemExit(1) — файла нет или JSON некорректен; перед выходом пишется событие outcome="error".
# SIDE EFFECTS: чтение файла; при включённом журнале — запись события об ошибке.
# KEYWORDS: [Json, Load, DataSource, Validation, Error]
# TESTS: [T-BUILD-001, T-BUILD-010]
def load_json(path: Path):
    if not path.is_file():
        log.event("LOAD_JSON", "build", "build.load_json", "error", level="ERROR", path=path.name)
        fail(f"нет файла данных {path.relative_to(ROOT)}")
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        log.event("LOAD_JSON", "build", "build.load_json", "error", level="ERROR", path=path.name)
        fail(f"{path.relative_to(ROOT)}: некорректный JSON — {exc}")
# END_BLOCK_LOAD_JSON


# START_BLOCK_PREPARE_TURNS: Подготовка ходов к рендеру. #KEYWORDS: Turns,Sort,Events,Neighbors
# PURPOSE: Упорядочить ходы и обогатить их подписями типов и соседями, чтобы шаблон только выводил готовые данные.
# INPUTS:
#   raw_turns: list[dict] — загруженные ходы; у каждого есть number и непустой events.
# OUTPUTS:
#   list[dict] — ходы по возрастанию number; у событий type_label, у хода type_counts/prev/next.
# ERRORS:
#   KeyError — если в данных нет обязательного поля; полноту данных проверяет scripts/validate.py.
# POSTCONDITIONS: ходы упорядочены стабильно; prev/next образуют связный список.
# KEYWORDS: [Turns, Sort, Events, Timeline, Neighbors]
# TESTS: [T-BUILD-005, T-BUILD-010]
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
# END_BLOCK_PREPARE_TURNS


# START_BLOCK_TYPE_STATS: Статистика типов событий для полос на странице ходов. #KEYWORDS: Stats,Types,Bars,Percent
# PURPOSE: Посчитать частоты типов событий и их ширину в процентах, чтобы страница ходов показывала соразмерные полосы.
# INPUTS:
#   turns: list[dict] — подготовленные ходы с непустым events.
# OUTPUTS:
#   list[dict] — записи id/label/count/width в порядке TYPE_LABELS; пустой список, если событий нет.
# ERRORS: нет: отсутствие событий даёт пустой список, а не деление на ноль.
# POSTCONDITIONS: у самого частого типа width == 100; больших чисел не бывает.
# KEYWORDS: [Stats, Types, Percent, Distribution, Bars]
# TESTS: [T-BUILD-005]
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
# END_BLOCK_TYPE_STATS


# START_BLOCK_CHECK_ASSETS: Проверка существования всех изображений данных. #KEYWORDS: Assets,Images,References,Existence
# PURPOSE: Убедиться, что каждое изображение из данных лежит в assets/, чтобы сборка не публиковала битые ссылки.
# INPUTS:
#   turns: list[dict] — ходы; map.image может отсутствовать.
#   maps: dict — каталог карт с ключом maps; tables: dict — таблицы с ключом tables.
# OUTPUTS:
#   нет — функция только проверяет.
# ERRORS:
#   SystemExit(1) — хотя бы одного файла изображения нет; перед выходом пишется событие outcome="error".
# SIDE EFFECTS: чтение файловой системы; при включённом журнале — событие об ошибке.
# KEYWORDS: [Assets, Images, Reference, Integrity, Dist]
# TESTS: [T-BUILD-009, T-BUILD-012]
def check_assets(turns: list[dict], maps: dict, tables: dict) -> None:
    referenced: set[str] = set()
    for turn in turns:
        if turn.get("map"):
            referenced.add(turn["map"]["image"])
    for item in maps["maps"]:
        referenced.add(item["file"])
    for item in tables["tables"]:
        if item.get("file"):
            referenced.add(item["file"])
    referenced.add("assets/img/favicon.svg")
    missing = [path for path in sorted(referenced) if not (ROOT / path).is_file()]
    if missing:
        log.event("CHECK_ASSETS", "build", "build.check_assets", "error", level="ERROR", missing=len(missing))
        fail("не найдены изображения: " + ", ".join(missing))
# END_BLOCK_CHECK_ASSETS


# PURPOSE: Задать поля, которые уходят в раскрываемые подробности строки таблицы, чтобы шаблон не придумывал подписи.
# KEYWORDS: [Buildings, Details, Labels, Catalog, Table]
# TESTS: [T-BUILD-007, T-BUILD-014]
BUILDING_DETAIL_FIELDS = (
    ("input", "Сырьё"),
    ("climate", "Климат"),
    ("terrain", "Местность"),
    ("bonuses", "Инновации и традиции"),
)

# PURPOSE: Задать число уровней тепловой раскраски числовых таблиц, чтобы товары и цены читались как на старом сайте.
# KEYWORDS: [Heatmap, Levels, Cells, Tables]
# TESTS: [T-BUILD-015, T-BUILD-016]
HEAT_LEVELS = 6


# PURPOSE: Подставить прочерк в пустую ячейку таблицы, чтобы строка не выглядела сломанной.
# INPUTS:
#   value: str — значение поля постройки; может быть пустым или «—».
# OUTPUTS:
#   str — исходный текст либо «—».
# ERRORS: нет.
# KEYWORDS: [Buildings, Fallback, Cell, Table]
# TESTS: [T-BUILD-013]
def _fallback(value: str) -> str:
    text = value.strip()
    return text if text and text != "—" else "—"


# PURPOSE: Отличить содержательное поле от пустого и всеобщего, чтобы не засорять раскрываемые подробности.
# INPUTS:
#   value: str — значение поля постройки.
# OUTPUTS:
#   bool — True, если поле стоит показывать.
# ERRORS: нет.
# KEYWORDS: [Buildings, Details, Filter, Cell]
# TESTS: [T-BUILD-014]
def _visible(value: str) -> bool:
    text = value.strip()
    return bool(text) and text != "—" and text.lower() != "все"


# PURPOSE: Вытащить первое число из текста, чтобы сортировать строки по цене и базовому доходу.
# INPUTS:
#   value: str — значение вида «17,5», «1+1(Овцы/Меринос)», «0, эмиссия…».
# OUTPUTS:
#   str — число с точкой в качестве разделителя или пустая строка, если числа нет.
# ERRORS: нет: отсутствие числа даёт пустую строку, а не исключение.
# KEYWORDS: [Buildings, Number, Sort, Parse]
# TESTS: [T-BUILD-014]
def _first_number(value: str) -> str:
    match = re.search(r"-?\d+(?:[.,]\d+)?", value)
    return match.group(0).replace(",", ".") if match else ""


# PURPOSE: Отнести цену к диапазону старого справочника, чтобы таблица читалась по цвету.
# INPUTS:
#   value: str — числовая строка цены; пустая допустима.
# OUTPUTS:
#   str — CSS-класс диапазона или пустая строка.
# ERRORS: ValueError, если строка не число; вызывающий код передаёт только результат _first_number.
# KEYWORDS: [Buildings, Cost, Range, Class]
# TESTS: [T-BUILD-014]
def _cost_class(value: str) -> str:
    if not value:
        return ""
    number = float(value)
    if number <= 15:
        return "cost-cheap"
    if number < 40:
        return "cost-mid"
    return "cost-expensive"


# PURPOSE: Отнести доход к диапазону, чтобы таблица показывала убыточные и доходные постройки.
# INPUTS:
#   value: str — числовая строка дохода; пустая допустима.
# OUTPUTS:
#   str — CSS-класс диапазона или пустая строка.
# ERRORS: ValueError, если строка не число; вызывающий код передаёт только результат _first_number.
# KEYWORDS: [Buildings, Income, Range, Class]
# TESTS: [T-BUILD-014]
def _income_class(value: str) -> str:
    if not value:
        return ""
    number = float(value)
    if number < 0:
        return "income-negative"
    if number <= 2:
        return "income-low"
    if number <= 4:
        return "income-mid"
    return "income-high"


# START_BLOCK_PREPARE_BUILDINGS: Подготовка каталога построек. #KEYWORDS: Buildings,Categories,Rules,Table
# PURPOSE: Разложить постройки по категориям, связать с местными правилами и собрать ячейки таблицы, чтобы шаблон только выводил готовые значения.
# INPUTS:
#   raw: dict — buildings.json с ключами buildings/changes/categories; id уникальны.
# OUTPUTS:
#   dict — тот же объект: у правил items, у построек local/variant/requirements/cost_display/income_display/base_display/cost_value/income_value/cost_class/income_class/details, у категорий items/count, total — число построек.
# ERRORS:
#   SystemExit(1) — правило ссылается на неизвестную постройку или у постройки неизвестное правило; перед выходом пишется событие outcome="error".
# PRECONDITIONS: buildings.json уже прочитан; все постройки имеют непустой name.
# KEYWORDS: [Buildings, Categories, LocalRule, Table, Values]
# TESTS: [T-BUILD-007, T-BUILD-008, T-BUILD-013, T-BUILD-014]
def prepare_buildings(raw: dict) -> dict:
    """Раскладывает постройки по категориям и готовит значения строк таблицы."""
    buildings = raw["buildings"]
    by_id = {building["id"]: building for building in buildings}
    changes = {change["id"]: change for change in raw["changes"]}

    for change in raw["changes"]:
        items = []
        for building_id in change["buildings"]:
            if building_id not in by_id:
                log.event("PREPARE_BUILDINGS", "build", "build.prepare_buildings", "error", level="ERROR", rule=change["id"])
                fail(f"buildings.json: правило «{change['id']}» ссылается на неизвестную постройку {building_id}")
            items.append(by_id[building_id])
        change["items"] = items

    for building in buildings:
        rule = building.get("local_rule")
        if rule and rule not in changes:
            log.event("PREPARE_BUILDINGS", "build", "build.prepare_buildings", "error", level="ERROR", building=building["id"])
            fail(f"buildings.json: у постройки «{building['name']}» неизвестное правило «{rule}»")
        building["local"] = changes.get(rule) if rule else None
        resource = building["resource"].strip()
        group = building["group"].strip()
        if resource and resource != "нет":
            building["variant"] = resource
        elif group and group != building["name"]:
            building["variant"] = group
        else:
            building["variant"] = "—"
        building["requirements"] = _fallback(building["conditions"])
        building["cost_display"] = _fallback(building["cost"])
        building["income_display"] = _fallback(building["income"])
        building["base_display"] = _fallback(building["base"])
        building["cost_value"] = _first_number(building["cost"])
        building["income_value"] = _first_number(building["income"])
        building["cost_class"] = _cost_class(building["cost_value"])
        building["income_class"] = _income_class(building["income_value"])
        building["details"] = [
            {"label": label, "value": building[key].strip()}
            for key, label in BUILDING_DETAIL_FIELDS
            if _visible(building[key])
        ]

    for category in raw["categories"]:
        category["items"] = [
            building for building in buildings if building["category"] == category["id"]
        ]
        category["count"] = len(category["items"])

    raw["total"] = len(buildings)
    return raw
# END_BLOCK_PREPARE_BUILDINGS


# START_BLOCK_PREPARE_TABLES: Подготовка числовых таблиц к рендеру. #KEYWORDS: Tables,Matrix,Heatmap,Cells
# PURPOSE: Собрать для числовых матриц колонки, строки и уровни тепловой раскраски, чтобы шаблон не считал числа сам.
# INPUTS:
#   raw: dict — tables.json с ключом tables; у матричных таблиц layout="matrix", есть columns и rows.
# OUTPUTS:
#   dict — тот же объект: у матричных таблиц поле matrix с колонками и строками {label, cells:[{value, level}]}.
# ERRORS:
#   SystemExit(1) — у матрицы меньше двух колонок, строка не совпадает по длине или нет раскрашиваемых чисел; перед выходом пишется событие outcome="error".
# PRECONDITIONS: tables.json уже прочитан; ячейки матрицы непустые.
# POSTCONDITIONS: level каждой ячейки лежит в диапазоне 0..HEAT_LEVELS-1; пустая матрица даёт пустой matrix.
# KEYWORDS: [Tables, Matrix, Heatmap, Cells, Goods]
# TESTS: [T-BUILD-015, T-BUILD-016]
def prepare_tables(raw: dict) -> dict:
    """Готовит числовые матрицы товаров и цен: значения и уровни раскраски по колонкам."""
    for table in raw["tables"]:
        if table.get("layout") != "matrix":
            continue
        columns = table["columns"]
        rows = table["rows"]
        if len(columns) < 2:
            log.event("PREPARE_TABLES", "build", "build.prepare_tables", "error", level="ERROR", table=table["id"])
            fail(f"tables.json: у матрицы «{table['id']}» меньше двух колонок")
        width = len(columns) - 1
        for index, row in enumerate(rows):
            if len(row) != len(columns):
                log.event("PREPARE_TABLES", "build", "build.prepare_tables", "error", level="ERROR", table=table["id"], row=index)
                fail(
                    f"tables.json: у матрицы «{table['id']}» строка {index + 1} содержит "
                    f"{len(row)} ячеек вместо {len(columns)}"
                )
        values = [
            [float(_first_number(row[column + 1])) for row in rows]
            for column in range(width)
        ]
        scale = table.get("heat", "linear")
        levels = []
        for column in range(width):
            numbers = values[column]
            scaled = [math.log1p(number) for number in numbers] if scale == "log" else numbers
            low = min(scaled)
            high = max(scaled)
            levels.append(
                [
                    0 if high == low else round((number - low) / (high - low) * (HEAT_LEVELS - 1))
                    for number in scaled
                ]
            )
        raw["has_matrix"] = True
        table["matrix"] = {
            "columns": columns[1:],
            "rows": [
                {
                    "label": row[0],
                    "cells": [
                        {"value": row[column + 1], "level": levels[column][index]}
                        for column in range(width)
                    ],
                }
                for index, row in enumerate(rows)
            ],
        }
    return raw
# END_BLOCK_PREPARE_TABLES


# PURPOSE: Собрать сайт из data/ в dist/, чтобы публикация шла из единственного источника без ручной правки страниц.
# INPUTS:
#   нет: окружение — каталог data/ с JSON, templates/, assets/; SOURCE_DATE_EPOCH задаёт дату сборки.
# OUTPUTS:
#   нет: пишет dist/ со страницами, 404.html, assets/, sitemap.xml, robots.txt и .nojekyll.
# ERRORS:
#   SystemExit(1) — ошибки данных или изображений (через fail); TemplateError — ошибка шаблона.
# SIDE EFFECTS: удаляет и пересоздаёт dist/, пишет файлы, печатает итог, ведёт журнал при NUKE_LOG.
# POSTCONDITIONS: dist/ содержит PAGE_FILES + 404.html; при выключенном журнале вывод не меняется.
# KEYWORDS: [Build, StaticSite, Templates, Dist, Sitemap]
# TESTS: [T-BUILD-001, T-BUILD-002, T-BUILD-003, T-BUILD-004, T-BUILD-006, T-BUILD-012]
def build() -> None:
    # START_BLOCK_LOAD_DATA: Загрузка всех данных сайта и проверка изображений. #KEYWORDS: Load,Data,Turns,Assets
    site = load_json(DATA / "site.json")
    world = load_json(DATA / "world.json")
    history = load_json(DATA / "history.json")
    ethnoses = load_json(DATA / "ethnoses.json")
    maps = load_json(DATA / "maps.json")
    tables = prepare_tables(load_json(DATA / "tables.json"))
    buildings = prepare_buildings(load_json(DATA / "buildings.json"))
    links = load_json(DATA / "links.json")
    participants = load_json(DATA / "participants.json")
    changelog = load_json(DATA / "changelog.json")

    turn_files = sorted((DATA / "turns").glob("*.json"))
    if not turn_files:
        log.event("LOAD_DATA", "build", "build.build", "error", level="ERROR", turns=0)
        fail("в data/turns нет ни одного хода")
    turns = prepare_turns([load_json(path) for path in turn_files])

    check_assets(turns, maps, tables)
    log.event(
        "LOAD_DATA",
        "build",
        "build.build",
        "ok",
        turns=len(turns),
        events=sum(len(turn["events"]) for turn in turns),
    )
    # END_BLOCK_LOAD_DATA

    # START_BLOCK_BUILD_CONTEXT: Подготовка контекста шаблонов. #KEYWORDS: Context,Stats,Jsonld,Templates
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
        (item for item in maps["maps"] if item["id"] == "political-935"),
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
    log.event(
        "BUILD_CONTEXT",
        "build",
        "build.build",
        "ok",
        type_stats=len(type_stats),
        pages=len(PAGE_FILES),
    )
    # END_BLOCK_BUILD_CONTEXT

    # START_BLOCK_RENDER_PAGES: Рендер всех страниц в dist/. #KEYWORDS: Render,Templates,Pages,Dist
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
    log.event(
        "RENDER_PAGES",
        "build",
        "build.build",
        "ok",
        pages=len(pages),
        not_found=1,
    )
    # END_BLOCK_RENDER_PAGES

    # START_BLOCK_WRITE_DIST_SITEMAP: Запись ассетов, sitemap и robots в dist/. #KEYWORDS: Dist,Sitemap,Robots,Assets
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
    log.event(
        "WRITE_DIST_SITEMAP",
        "build",
        "build.build",
        "ok",
        urls=len(PAGE_FILES),
        assets="assets",
    )
    # END_BLOCK_WRITE_DIST_SITEMAP

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
        log.event("RENDER_PAGES", "build", "build.build", "error", level="ERROR", error=str(exc)[:160])
        fail(str(exc))
