#!/usr/bin/env python3
# ==== MODULE CONTRACT: nuke-audit ====
# PURPOSE:   Проверять соблюдение стандарта NUKE, чтобы контракты, якоря, граф, тесты и логи не расходились с кодом.
# SCOPE:     C1–C10 из NUKE.md §16: контракты модулей и символов, якоря, граф, .md, ID тестов, схема журнала, сверка поведения с контрактом.
# NON-GOALS: Не исправлять код, не собирать dist/, не заменять validate.py (данные) и unittest (поведение).
# INVARIANTS:код 0 только при отсутствии расхождений; проверки не прерывают друг друга; аудит не зависит от сети и времени.
# DEPENDS:   nuke-log:EventLogger
# EXPOSES:   main, audit, load_graph, check_module_contracts, check_purpose_contracts, check_anchors, check_graph, check_markdown, check_test_ids, check_log, check_contracts_with_diff
# ERRORS:    SystemExit(1) — найденное расхождение (в main); ошибки чтения файлов пропускаются с сообщением в отчёте.
# TESTS:     T-NUKE-006, T-NUKE-007, T-NUKE-008, T-NUKE-009, T-NUKE-010, T-NUKE-011, T-NUKE-012, T-NUKE-013, T-NUKE-014, T-NUKE-015, T-NUKE-016, T-NUKE-017, T-NUKE-018, T-NUKE-019, T-NUKE-020, T-NUKE-021, T-NUKE-022, T-NUKE-023, T-NUKE-024
# ==== END MODULE CONTRACT: nuke-audit ====
"""Аудит соблюдения стандарта NUKE (NUKE.md §16)."""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nuke_log import EventLogger  # noqa: E402  (после ROOT: модуль журнала лежит в корне)

CODE_EXTENSIONS = (".py", ".js", ".css")
IGNORED_DIRS = {
    ".git",
    ".github",
    ".shots",
    ".tmp",
    "__pycache__",
    "dist",
    "docs",
    "dsh",
    "nuke",
    "sources",
}
ALLOWED_MARKDOWN = {"AGENTS.md", "CONCEPT.md", "NUKE.md", "README.md"}
CONTRACT_FIELDS = (
    "PURPOSE",
    "SCOPE",
    "NON-GOALS",
    "INVARIANTS",
    "DEPENDS",
    "EXPOSES",
    "ERRORS",
    "TESTS",
)
PURPOSE_FIELDS = ("PURPOSE", "INPUTS", "OUTPUTS", "ERRORS", "KEYWORDS", "TESTS")
MAX_BLOCK_LINES = 200
GRAPH_BUDGET_TOKENS = 8000

CONTRACT_START_RE = re.compile(r"MODULE CONTRACT:\s*([a-z0-9][a-z0-9-]*)")
CONTRACT_END_RE = re.compile(r"END MODULE CONTRACT:\s*([a-z0-9][a-z0-9-]*)")
PUBLIC_DEF_RE = re.compile(r"^(?:async\s+)?def\s+([A-Za-z]\w*)\s*\(|^class\s+([A-Za-z]\w*)\b")
START_ANCHOR_RE = re.compile(
    r"START_BLOCK_([A-Z][A-Z0-9_]{0,31}):\s+(\S.*?)#KEYWORDS:\s*([A-Za-z][\w,]*)\s*$"
)
END_ANCHOR_RE = re.compile(r"END_BLOCK_([A-Z][A-Z0-9_]{0,31})\s*$")
TEST_DEF_RE = re.compile(r"^\s+def\s+(test_\w+)\s*\(")
TEST_ID_RE = re.compile(r"TEST_ID:\s*(T-[A-Z0-9]+-\d{3})")
TEST_TOKEN_RE = re.compile(r"T-[A-Z0-9]+-\d{3}")
FIELD_LINE_RE = re.compile(r"^[A-Z][A-Z0-9 _-]{1,28}:")


# START_BLOCK_FILE_HELPERS: Обход файлов кода и мелкие разборщики строк. #KEYWORDS: Files,Walk,Comments,Fields
# PURPOSE: Перебрать все файлы кода репозитория, пропуская служебные каталоги.
# INPUTS: root — корень репозитория; IGNORED_DIRS задаёт пропуски.
# OUTPUTS: list[Path] — файлы .py/.js/.css в устойчивом порядке.
# ERRORS: нет: нечитаемые каталоги пропускаются.
# KEYWORDS: [Files, Walk, Code, Repository]
# TESTS: [T-NUKE-012]
def _code_files(root):
    root = Path(root)
    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_DIRS)
        for name in sorted(filenames):
            if Path(name).suffix in CODE_EXTENSIONS:
                result.append(Path(dirpath) / name)
    return result


# PURPOSE: Прочитать текстовый файл, не выбрасывая исключение наружу.
# INPUTS: path — файл; OUTPUTS: str | None; ERRORS: нет.
# KEYWORDS: [Read, Text, Utf8, Fallback]
# TESTS: [T-NUKE-006]
def _read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# PURPOSE: Задать путь файла относительно корня в posix-виде для отчётов.
# INPUTS: root — корень; path — файл; OUTPUTS: str; ERRORS: нет.
# KEYWORDS: [Path, Relative, Posix, Report]
# TESTS: [T-NUKE-006]
def _rel(root, path):
    return Path(path).relative_to(Path(root)).as_posix()


# PURPOSE: Решить, входит ли путь в служебный каталог, который аудит не смотрит.
# INPUTS: root — корень; path — проверяемый путь; OUTPUTS: bool; ERRORS: нет.
# KEYWORDS: [Ignore, Directories, Filter]
# TESTS: [T-NUKE-012]
def _is_ignored(root, path):
    return any(part in IGNORED_DIRS for part in Path(path).relative_to(Path(root)).parts)


# PURPOSE: Снять с строки маркер комментария, чтобы читать поля контрактов.
# INPUTS: line — строка файла; OUTPUTS: str — содержимое без #, //, /*, *, */; ERRORS: нет.
# KEYWORDS: [Comments, Syntax, Contract, Fields]
# TESTS: [T-NUKE-007]
def _strip_comment(line):
    value = line.strip()
    for prefix in ("<!--", "/*!", "/*", "*/", "//", "#", "*"):
        if value.startswith(prefix):
            value = value[len(prefix) :].strip()
            break
    if value.endswith("*/"):
        value = value[:-2].strip()
    return value


# PURPOSE: Собрать комментарий, стоящий непосредственно над объявлением символа.
# INPUTS: lines — строки файла; index — номер строки объявления.
# OUTPUTS: str — текст контракта без маркеров комментариев; пустая строка, если блока нет.
# ERRORS: нет.
# KEYWORDS: [Contract, Comments, Symbol, Purpose]
# TESTS: [T-NUKE-007]
def _preceding_comment_block(lines, index):
    cursor = index - 1
    while cursor >= 0 and not lines[cursor].strip():
        cursor -= 1
    block = []
    while cursor >= 0 and lines[cursor].strip().startswith("#"):
        block.append(_strip_comment(lines[cursor]))
        cursor -= 1
    return "\n".join(reversed(block))


# PURPOSE: Извлечь значение поля-списка из текста контракта.
# INPUTS: block — текст контракта; field — имя поля (DEPENDS, EXPOSES, TESTS).
# OUTPUTS: list[str] — элементы списка через запятую; пустой список, если поля нет.
# ERRORS: нет.
# KEYWORDS: [Contract, Fields, List, Depends]
# TESTS: [T-NUKE-006]
def _list_field(block, field):
    for line in block.splitlines():
        stripped = _strip_comment(line)
        if stripped.startswith(field + ":"):
            value = stripped.split(":", 1)[1].strip()
            if value.lower() in ("нет", "нет.", "—", "-", "нет зависимостей"):
                return []
            return [part.strip() for part in value.split(",") if part.strip()]
    return []
# PURPOSE: Разобрать Python-модуль в AST, чтобы отличать код от текста в строках.
# INPUTS: text — исходник; OUTPUTS: ast.Module | None; ERRORS: нет, ошибка синтаксиса возвращает None.
# KEYWORDS: [Python, Ast, Parse, Structure]
# TESTS: [T-NUKE-007]
def _python_ast(text):
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


# PURPOSE: Собрать настоящие комментарии Python-файла по номерам строк.
# INPUTS: text — исходник; OUTPUTS: dict[int, str] — строка → текст комментария.
# ERRORS: нет: ошибки токенизации игнорируются.
# KEYWORDS: [Python, Comments, Tokenize, Lines]
# TESTS: [T-NUKE-008]
def _python_comments(text):
    comments = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                comments[token.start[0]] = token.string
    except (tokenize.TokenError, IndentationError):
        return {}
    return comments


# PURPOSE: Взять блок комментариев, стоящий прямо над объявлением.
# INPUTS: comments — карта комментариев; lines — строки файла; def_line — номер строки объявления.
# OUTPUTS: str — текст контракта; пустая строка, если блока нет.
# ERRORS: нет.
# KEYWORDS: [Contract, Comments, Above, Symbol]
# TESTS: [T-NUKE-007]
def _comment_block_above(comments, lines, def_line):
    cursor = def_line - 1
    while cursor >= 1 and not lines[cursor - 1].strip():
        cursor -= 1
    block = []
    while cursor >= 1 and cursor in comments:
        block.append(comments[cursor])
        cursor -= 1
    return "\n".join(reversed(block))


# PURPOSE: Определить первую строку объявления с учётом декораторов.
# INPUTS: node — ast-узел def/class.
# OUTPUTS: int — номер первой строки объявления.
# ERRORS: нет.
# KEYWORDS: [Ast, Decorator, Def, Line]
# TESTS: [T-NUKE-007]
def _first_line(node):
    lines = [node.lineno] + [item.lineno for item in getattr(node, "decorator_list", [])]
    return min(lines)


# PURPOSE: Собрать места, где может стоять якорь: в .py — только настоящие комментарии.
# INPUTS: text — исходник; path — файл (по расширению выбирается способ).
# OUTPUTS: list[tuple[int, str]] — номер строки и текст строки.
# ERRORS: нет.
# KEYWORDS: [Anchors, Comments, Python, Entries]
# TESTS: [T-NUKE-008]
def _anchor_entries(text, path):
    if path.suffix == ".py":
        comments = _python_comments(text)
        return [(number, comments[number]) for number in sorted(comments)]
    result = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = _strip_comment(line)
        if "START_BLOCK_" in stripped or "END_BLOCK_" in stripped:
            result.append((number, line))
    return result
# END_BLOCK_FILE_HELPERS


# START_BLOCK_GRAPH_LOAD: Разбор nuke/graph.yaml на стандартной библиотеке. #KEYWORDS: Graph,Yaml,Parser,Schema
# PURPOSE: Читать подмножество YAML, достаточное для схемы графа NUKE.
# INPUTS:
#   root: Path — корень репозитория; файл nuke/graph.yaml существует.
# OUTPUTS:
#   tuple[dict | None, list[str]] — граф и сообщения об ошибках разбора.
# ERRORS: нет исключений: ошибки разбора возвращаются строками отчёта.
# KEYWORDS: [Graph, Yaml, Parser, Schema, Budget]
# TESTS: [T-NUKE-018]
def load_graph(root):
    path = Path(root) / "nuke" / "graph.yaml"
    if not path.is_file():
        return None, ["[C5] nuke/graph.yaml: файл графа не найден"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [f"[C5] nuke/graph.yaml: не читается — {exc}"]
    if len(text) // 4 > GRAPH_BUDGET_TOKENS:
        return None, [f"[C5] nuke/graph.yaml: превышен бюджет {GRAPH_BUDGET_TOKENS} токенов"]
    parsed, parse_errors = _parse_yaml_subset(text)
    if parse_errors:
        return None, [f"[C5] nuke/graph.yaml: {message}" for message in parse_errors]
    if not isinstance(parsed, dict):
        return None, ["[C5] nuke/graph.yaml: ожидалась схема с ключом nodes"]
    return parsed, []


# PURPOSE: Разобрать YAML-подмножество (вложенные словари, списки словарей, inline-списки).
# INPUTS:
#   text: str — содержимое graph.yaml; комментарии и пустые строки допустимы.
# OUTPUTS:
#   tuple[dict | None, list[str]] — структура и ошибки разбора.
# ERRORS: нет исключений; ошибки отступов и строк возвращаются списком.
# KEYWORDS: [Yaml, Parser, Indent, Scalar, Mapping]
# TESTS: [T-NUKE-018]
def _parse_yaml_subset(text):
    lines = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            return None, [f"табуляция в отступе, строка {number}"]
        lines.append((len(raw) - len(raw.lstrip(" ")), stripped, number))
    if not lines:
        return None, ["пустой граф"]
    try:
        value, index = _parse_mapping(lines, 0, lines[0][0])
    except ValueError as exc:
        return None, [str(exc)]
    if index != len(lines):
        return None, [f"лишняя строка {lines[index][2]}"]
    return value, []


# PURPOSE: Разобрать блок словаря на заданном отступе.
# INPUTS:
#   lines: list[tuple[int, str, int]] — отступ, текст, номер строки.
#   index: int — первая строка блока; indent: int — отступ блока.
# OUTPUTS:
#   tuple[dict, int] — словарь и индекс следующей строки.
# ERRORS: ValueError — строка не является парой «ключ: значение».
# KEYWORDS: [Yaml, Mapping, KeyValue, Indent]
# TESTS: [T-NUKE-018]
def _parse_mapping(lines, index, indent):
    result = {}
    while index < len(lines) and lines[index][0] == indent:
        _, content, number = lines[index]
        if content.startswith("- "):
            break
        key, _, raw_value = content.partition(":")
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            raise ValueError(f"строка {number}: пустой ключ")
        index += 1
        if raw_value:
            result[key] = _scalar(raw_value)
        elif index < len(lines) and lines[index][0] > indent:
            child_indent = lines[index][0]
            if lines[index][1].startswith("- "):
                result[key], index = _parse_sequence(lines, index, child_indent)
            else:
                result[key], index = _parse_mapping(lines, index, child_indent)
        else:
            result[key] = None
    return result, index


# PURPOSE: Разобрать блок списка (элементы «- ...») на заданном отступе.
# INPUTS:
#   lines: list[tuple[int, str, int]] — отступ, текст, номер строки.
#   index: int — первая строка списка; indent: int — отступ элементов.
# OUTPUTS:
#   tuple[list, int] — список и индекс следующей строки.
# ERRORS: ValueError — элемент списка не является словарём или скаляром.
# KEYWORDS: [Yaml, Sequence, Mapping, Elements]
# TESTS: [T-NUKE-018]
def _parse_sequence(lines, index, indent):
    items = []
    while index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
        head = lines[index][1][2:].strip()
        index += 1
        if not head:
            raise ValueError(f"строка {index}: пустой элемент списка")
        if ":" not in head:
            items.append(_scalar(head))
            continue
        key, _, raw_value = head.partition(":")
        item = {key.strip(): _scalar(raw_value.strip())}
        if index < len(lines) and lines[index][0] > indent:
            rest, index = _parse_mapping(lines, index, lines[index][0])
            item.update(rest)
        items.append(item)
    return items, index


# PURPOSE: Преобразовать скаляр YAML в Python-значение без внешних зависимостей.
# INPUTS:
#   raw: str — «строка», число или inline-список [a, b].
# OUTPUTS:
#   str | int | list — значение; кавычки снимаются.
# ERRORS: нет: непонятная строка возвращается как есть.
# KEYWORDS: [Yaml, Scalar, List, Number]
# TESTS: [T-NUKE-018]
def _scalar(raw):
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [_scalar(part) for part in inner.split(",") if part.strip()] if inner else []
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value
# END_BLOCK_GRAPH_LOAD


# START_BLOCK_CONTRACT_CHECKS: Проверки контрактов модулей и символов (C1). #KEYWORDS: Contracts,Purpose,Module,Symbol
# PURPOSE: Проверить шапки модулей и контракты публичных символов по §5–§6.
# INPUTS:
#   root: Path — корень репозитория; graph: dict | None — разобранный граф.
# OUTPUTS:
#   list[str] — расхождения; пустой список — контракты на месте.
# ERRORS: нет исключений: нечитаемые файлы попадают в отчёт.
# KEYWORDS: [Contracts, Purpose, Module, Symbol, Navigation]
# TESTS: [T-NUKE-006, T-NUKE-007, T-NUKE-022]
def check_module_contracts(root, graph):
    errors = []
    node_ids = _node_ids(graph)
    for path in _code_files(root):
        text = _read_text(path)
        if text is None:
            errors.append(f"[C1] {_rel(root, path)}: файл не читается")
            continue
        if path.suffix not in (".py", ".js", ".css"):
            continue
        lines = text.splitlines()
        start = _contract_bounds(lines)
        if start is None:
            errors.append(f"[C1] {_rel(root, path)}: нет MODULE CONTRACT")
            continue
        start_index, end_index = start
        block = "\n".join(lines[start_index : end_index + 1])
        for field in CONTRACT_FIELDS:
            if f"{field}:" not in block:
                errors.append(f"[C1] {_rel(root, path)}: в контракте модуля нет поля {field}")
        contract_id = CONTRACT_START_RE.search(lines[start_index]).group(1)
        if not _contract_id_allowed(contract_id, node_ids):
            errors.append(f"[C1] {_rel(root, path)}: контракт ссылается на неизвестный узел {contract_id}")
        for dependency in _list_field(block, "DEPENDS"):
            node = dependency.split(":", 1)[0].strip()
            if node and node not in node_ids:
                errors.append(f"[C1] {_rel(root, path)}: DEPENDS ссылается на неизвестный узел {node}")
        if "PURPOSE:" not in block:
            errors.append(f"[C1] {_rel(root, path)}: в контракте модуля нет PURPOSE")
    return errors


# PURPOSE: Найти контракт символа над каждым top-level def/class без ведущего «_».
# INPUTS:
#   root: Path — корень репозитория; проверяются все .py-модули кода.
# OUTPUTS:
#   list[str] — расхождения по полям, KEYWORDS и PURPOSE.
# ERRORS: нет исключений: нечитаемые файлы попадают в отчёт.
# KEYWORDS: [Contracts, Symbol, Purpose, Keywords, Field]
# TESTS: [T-NUKE-006, T-NUKE-007]
def check_purpose_contracts(root):
    errors = []
    for path in _code_files(root):
        if path.suffix != ".py":
            continue
        text = _read_text(path)
        if text is None:
            errors.append(f"[C1] {_rel(root, path)}: файл не читается")
            continue
        rel = _rel(root, path)
        tree = _python_ast(text)
        if tree is None:
            errors.append(f"[C1] {rel}: модуль не разбирается как Python")
            continue
        comments = _python_comments(text)
        lines = text.splitlines()
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            name = node.name
            if name.startswith("_"):
                continue
            block = _comment_block_above(comments, lines, _first_line(node))
            where = f"[C1] {rel}:{node.lineno} {name}"
            if not block:
                errors.append(f"{where}: нет контракта символа")
                continue
            for field in PURPOSE_FIELDS:
                if f"{field}:" not in block:
                    errors.append(f"{where}: нет поля {field}")
            keywords = re.search(r"KEYWORDS:\s*\[([^\]]*)\]", block)
            if not keywords:
                errors.append(f"{where}: KEYWORDS должен быть списком в [..]")
            else:
                terms = [part.strip() for part in keywords.group(1).split(",") if part.strip()]
                if not 3 <= len(terms) <= 8:
                    errors.append(f"{where}: KEYWORDS должен содержать 3–8 терминов, найдено {len(terms)}")
    return errors


# PURPOSE: Проверить шапку модуля на корректность парности START/END контракта.
# INPUTS:
#   lines: list[str] — строки файла.
# OUTPUTS:
#   tuple[int, int] | None — границы блока контракта или None.
# ERRORS: нет: непарный контракт обнаруживается проверками выше.
# KEYWORDS: [Contract, Bounds, Marker, Header]
# TESTS: [T-NUKE-006]
def _contract_bounds(lines):
    for index, line in enumerate(lines[:120]):
        match = CONTRACT_START_RE.search(line)
        if match:
            end = CONTRACT_END_RE.search(line)
            start = index
            if end:
                return start, start
            for offset in range(index + 1, len(lines)):
                if CONTRACT_END_RE.search(lines[offset]):
                    return start, offset
            return None
    return None
# END_BLOCK_CONTRACT_CHECKS


# START_BLOCK_ANCHOR_CHECKS: Проверки якорей C2–C4. #KEYWORDS: Anchors,Blocks,Balance,Nesting
# PURPOSE: Проверить баланс, отсутствие вложенности, уникальность и длину блоков.
# INPUTS:
#   root: Path — корень репозитория; проверяются .py, .js, .css.
# OUTPUTS:
#   list[str] — расхождения по якорям.
# ERRORS: нет исключений: нечитаемые файлы попадают в отчёт.
# KEYWORDS: [Anchors, Blocks, Balance, Nesting, PatchTargets]
# TESTS: [T-NUKE-008, T-NUKE-009, T-NUKE-010]
def check_anchors(root):
    errors = []
    for path in _code_files(root):
        if path.suffix not in CODE_EXTENSIONS:
            continue
        text = _read_text(path)
        if text is None:
            continue
        rel = _rel(root, path)
        stack = []
        seen = set()
        for number, raw in _anchor_entries(text, path):
            stripped = _strip_comment(raw)
            index = number - 1
            if "START_BLOCK_" in stripped:
                match = START_ANCHOR_RE.search(stripped)
                if not match:
                    errors.append(f"[C2] {rel}:{number}: якорь без «#KEYWORDS:» или с неверным ID")
                    continue
                anchor, _goal, keywords = match.groups()
                terms = [part for part in keywords.split(",") if part.strip()]
                if not 2 <= len(terms) <= 8:
                    errors.append(f"[C2] {rel}:{number} {anchor}: нужно 2–8 ключевых слов")
                if anchor in seen:
                    errors.append(f"[C2] {rel}:{number} {anchor}: ID якоря повторяется")
                if stack:
                    errors.append(f"[C3] {rel}:{number} {anchor}: вложенный якорь внутри {stack[-1][0]}")
                seen.add(anchor)
                stack.append((anchor, index))
            elif "END_BLOCK_" in stripped:
                match = END_ANCHOR_RE.search(stripped)
                if not match:
                    errors.append(f"[C2] {rel}:{number}: неверный формат END_BLOCK")
                    continue
                anchor = match.group(1)
                if not stack:
                    errors.append(f"[C2] {rel}:{number} {anchor}: END без START")
                    continue
                opened, start_index = stack.pop()
                if opened != anchor:
                    errors.append(f"[C2] {rel}:{number}: END_BLOCK_{anchor} закрывает START_BLOCK_{opened}")
                block_lines = index - start_index - 1
                if block_lines > MAX_BLOCK_LINES:
                    errors.append(f"[C4] {rel}:{start_index + 1} {anchor}: блок {block_lines} строк, максимум {MAX_BLOCK_LINES}")
        for anchor, start_index in stack:
            errors.append(f"[C2] {rel}:{start_index + 1} {anchor}: нет END_BLOCK_{anchor}")
    return errors
# END_BLOCK_ANCHOR_CHECKS


# START_BLOCK_GRAPH_CHECKS: Проверки графа C5–C6. #KEYWORDS: Graph,Nodes,Depends,Coverage
# PURPOSE: Убедиться, что граф описывает все узлы, зависимости и тесты.
# INPUTS:
#   root: Path — корень; graph: dict | None — разобранный граф.
# OUTPUTS:
#   list[str] — расхождения по узлам, зависимостям, путям и покрытию.
# ERRORS: нет исключений: ошибки схемы возвращаются строками.
# KEYWORDS: [Graph, Nodes, Depends, Coverage, Cycle]
# TESTS: [T-NUKE-011, T-NUKE-012, T-NUKE-013]
def check_graph(root, graph):
    errors = []
    if graph is None:
        return errors
    for key in ("nuke_version", "app", "purpose", "stack", "budget_tokens", "nodes"):
        if key not in graph or graph[key] in (None, "", []):
            errors.append(f"[C5] nuke/graph.yaml: нет обязательного поля {key}")
    if graph.get("nuke_version") != "2.0":
        errors.append("[C5] nuke/graph.yaml: nuke_version должен быть 2.0")
    nodes = graph.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        return errors + ["[C5] nuke/graph.yaml: список nodes пуст"]
    node_ids = set()
    paths = []
    for node in nodes:
        if not isinstance(node, dict):
            errors.append("[C5] nuke/graph.yaml: узел должен быть словарём")
            continue
        node_id = node.get("id")
        if not node_id:
            errors.append("[C5] nuke/graph.yaml: узел без id")
            continue
        if node_id in node_ids:
            errors.append(f"[C5] nuke/graph.yaml: повторяющийся id узла {node_id}")
        node_ids.add(node_id)
        for key in ("path", "purpose", "owns", "depends", "tests"):
            if key not in node or node[key] is None:
                errors.append(f"[C5] {node_id}: нет обязательного поля {key}")
        if not node.get("tests"):
            errors.append(f"[C6] {node_id}: у узла нет тестов")
        if not node.get("purpose"):
            errors.append(f"[C5] {node_id}: пустой purpose")
        purpose = str(node.get("purpose") or "")
        if purpose and purpose == node.get("path"):
            errors.append(f"[C5] {node_id}: purpose дублирует path")
        path = str(node.get("path") or "")
        if path:
            if not (Path(root) / path.rstrip("/")).exists():
                errors.append(f"[C5] {node_id}: путь {path} не существует")
            paths.append(path.rstrip("/"))
        for test in node.get("tests") or []:
            if not (Path(root) / str(test).rstrip("/")).exists():
                errors.append(f"[C6] {node_id}: тест {test} не существует")
    for node in nodes:
        if not isinstance(node, dict) or not node.get("id"):
            continue
        for dependency in node.get("depends") or []:
            if dependency not in node_ids:
                errors.append(f"[C5] {node['id']}: зависимость {dependency} не описана в графе")
            if dependency == node["id"]:
                errors.append(f"[C5] {node['id']}: узел зависит сам от себя")
    errors.extend(_check_cycles(nodes, node_ids))
    errors.extend(_check_coverage(root, paths))
    graph_file = Path(root) / "nuke" / "graph.yaml"
    try:
        size = len(graph_file.read_text(encoding="utf-8").split())
    except OSError:
        size = 0
    if size > GRAPH_BUDGET_TOKENS:
        errors.append(f"[C5] nuke/graph.yaml: {size} токенов, бюджет {GRAPH_BUDGET_TOKENS}")
    return errors


# PURPOSE: Найти циклы в зависимостях узлов, чтобы граф оставался направленным.
# INPUTS:
#   nodes: list[dict] — узлы графа; node_ids: set[str] — известные id.
# OUTPUTS:
#   list[str] — сообщения о циклах.
# ERRORS: нет: обход не выбрасывает исключений.
# KEYWORDS: [Graph, Cycle, Depends, Dfs]
# TESTS: [T-NUKE-011]
def _check_cycles(nodes, node_ids):
    graph = {}
    for node in nodes:
        if isinstance(node, dict) and node.get("id"):
            graph[node["id"]] = [dep for dep in node.get("depends") or [] if dep in node_ids]
    errors = []
    visited, stack = set(), set()

    def visit(node_id, trail):
        if node_id in stack:
            errors.append("[C5] цикл зависимостей: " + " → ".join(trail + [node_id]))
            return
        if node_id in visited:
            return
        stack.add(node_id)
        for dependency in graph.get(node_id, []):
            visit(dependency, trail + [node_id])
        stack.discard(node_id)
        visited.add(node_id)

    for node_id in graph:
        visit(node_id, [])
    return errors


# PURPOSE: Проверить, что каждый файл кода покрыт узлом графа.
# INPUTS:
#   root: Path — корень; paths: list[str] — пути узлов без завершающего слэша.
# OUTPUTS:
#   list[str] — непокрытые файлы кода.
# ERRORS: нет: обход каталогов не выбрасывает исключений.
# KEYWORDS: [Graph, Coverage, Files, Nodes]
# TESTS: [T-NUKE-012]
def _check_coverage(root, paths):
    errors = []
    for path in _code_files(root):
        rel = _rel(root, path)
        if not any(rel == prefix or rel.startswith(prefix + "/") for prefix in paths):
            errors.append(f"[C5] {rel}: файл не покрыт ни одним узлом графа")
    return errors


# PURPOSE: Определить, допустим ли id контракта модуля для узла графа.
# INPUTS:
#   contract_id: str — id из шапки; node_ids: set[str] — id узлов графа.
# OUTPUTS:
#   bool — True, если id совпадает с узлом или является его подмодулем.
# ERRORS: нет.
# KEYWORDS: [Contract, Node, Submodule, Namespace]
# TESTS: [T-NUKE-006]
def _contract_id_allowed(contract_id, node_ids):
    if contract_id in node_ids:
        return True
    return any(contract_id.startswith(node_id + "-") for node_id in node_ids)


# PURPOSE: Собрать id узлов графа как множество.
# INPUTS:
#   graph: dict | None — разобранный граф.
# OUTPUTS:
#   set[str] — идентификаторы узлов.
# ERRORS: нет.
# KEYWORDS: [Graph, Nodes, Ids]
# TESTS: [T-NUKE-006]
def _node_ids(graph):
    if not graph:
        return set()
    return {node["id"] for node in graph.get("nodes") or [] if isinstance(node, dict) and node.get("id")}
# END_BLOCK_GRAPH_CHECKS


# START_BLOCK_REPO_CHECKS: Проверки репозитория: C8 (.md) и C10 (ID тестов). #KEYWORDS: Markdown,Tests,TestIds,Repository
# PURPOSE: Не допускать внешней документации кода и неразрешённых ID тестов.
# INPUTS:
#   root: Path — корень репозитория.
# OUTPUTS:
#   list[str] — расхождения C8 и C10.
# ERRORS: нет исключений: нечитаемые файлы попадают в отчёт.
# KEYWORDS: [Markdown, Tests, TestIds, Repository]
# TESTS: [T-NUKE-014, T-NUKE-015]
def check_markdown(root):
    errors = []
    for path in Path(root).rglob("*.md"):
        if _is_ignored(root, path):
            continue
        if path.name not in ALLOWED_MARKDOWN:
            errors.append(f"[C8] {_rel(root, path)}: .md с описанием кода запрещён — контракт живёт в коде")
    return errors


# PURPOSE: Сверить объявленные ID тестов с именами тестов и ссылками из контрактов.
# INPUTS:
#   root: Path — корень; тест-модули лежат в tests/.
# OUTPUTS:
#   list[str] — расхождения C10.
# ERRORS: нет исключений: нечитаемые файлы пропускаются.
# KEYWORDS: [Tests, TestIds, Naming, Contracts]
# TESTS: [T-NUKE-014]
def check_test_ids(root):
    errors = []
    declared = {}
    refs = []
    for path in _code_files(root):
        text = _read_text(path)
        if text is None:
            continue
        rel = _rel(root, path)
        if path.suffix == ".py":
            comments = _python_comments(text)
            lines = text.splitlines()
            tree = _python_ast(text)
            if tree is not None:
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if not node.name.startswith("test_") or path.parent.name != "tests":
                        continue
                    if not re.match(r"^test_[a-z0-9_]+__[a-z0-9_]+$", node.name):
                        errors.append(f"[C10] {rel}:{node.lineno} {node.name}: имя должно быть test_<purpose>__<case>")
                    found = TEST_ID_RE.search(_comment_block_above(comments, lines, _first_line(node)))
                    if not found:
                        errors.append(f"[C10] {rel}:{node.lineno} {node.name}: нет # TEST_ID")
                    else:
                        declared.setdefault(found.group(1), []).append(f"{rel}:{node.name}")
            for comment in comments.values():
                if "TESTS:" in comment:
                    for token in TEST_TOKEN_RE.findall(comment):
                        refs.append((rel, token))
        else:
            for line in text.splitlines():
                stripped = _strip_comment(line)
                if "TESTS:" in stripped:
                    for token in TEST_TOKEN_RE.findall(stripped):
                        refs.append((rel, token))
    for test_id, places in declared.items():
        if len(places) > 1:
            errors.append(f"[C10] {test_id}: ID теста продублирован ({', '.join(places)})")
    for rel, token in refs:
        if token not in declared:
            errors.append(f"[C10] {rel}: ссылка на несуществующий тест {token}")
    return errors
# END_BLOCK_REPO_CHECKS


# START_BLOCK_LOG_AND_DIFF: Проверки C7 (контракт вместе с кодом) и C9 (схема журнала). #KEYWORDS: Log,Jsonl,Schema,Diff
# PURPOSE: Проверить схему JSONL-журнала и соответствие диффа контрактам.
# INPUTS:
#   root: Path — корень; graph: dict | None — граф; log_path: Path | None — журнал.
# OUTPUTS:
#   list[str] — расхождения C7/C9.
# ERRORS: нет исключений: ошибки чтения возвращаются строками.
# KEYWORDS: [Log, Jsonl, Schema, Diff, Contract]
# TESTS: [T-NUKE-016, T-NUKE-017, T-NUKE-019, T-NUKE-020]
def check_log(root, graph, log_path):
    errors = []
    if log_path is None:
        return errors
    path = Path(log_path)
    if not path.is_file():
        return [f"[C9] журнал {log_path}: файл не найден"]
    anchors = _anchors_by_node(root, graph)
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return [f"[C9] журнал {log_path}: пуст"]
    required = ("ts", "level", "module", "block", "op", "ref", "outcome", "test")
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"[C9] журнал:{number}: строка не JSON")
            continue
        missing = [key for key in required if key not in record]
        if missing:
            errors.append(f"[C9] журнал:{number}: нет полей {', '.join(missing)}")
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", str(record["ts"])):
            errors.append(f"[C9] журнал:{number}: ts не в формате ISO8601 UTC")
        if record["level"] not in ("DEBUG", "INFO", "WARN", "ERROR"):
            errors.append(f"[C9] журнал:{number}: неизвестный level {record['level']}")
        if record["outcome"] not in ("ok", "error", "skip"):
            errors.append(f"[C9] журнал:{number}: неизвестный outcome {record['outcome']}")
        module = record["module"]
        if graph is not None and module not in _node_ids(graph):
            errors.append(f"[C9] журнал:{number}: модуль {module} не описан в графе")
        elif graph is not None and record["block"] not in anchors.get(module, set()):
            errors.append(f"[C9] журнал:{number}: блок {record['block']} не найден в якорях {module}")
        if record["test"] and not re.match(r"^T-[A-Z0-9]+-\d{3}$", str(record["test"])):
            errors.append(f"[C9] журнал:{number}: test должен быть ID вида T-MODULE-NNN")
    return errors


# PURPOSE: Сверить изменённое поведение с изменением контракта относительно базовой ревизии.
# INPUTS:
#   root: Path — корень git-репозитория; base: str | None — ревизия сравнения.
# OUTPUTS:
#   list[str] — расхождения C7; при base=None проверка пропускается.
# ERRORS: нет исключений: недоступность git возвращается сообщением.
# KEYWORDS: [Diff, Contract, Behavior, Git, Patch]
# TESTS: [T-NUKE-019]
def check_contracts_with_diff(root, base):
    if not base:
        return []
    root = Path(root)
    if not (root / ".git").exists():
        return ["[C7] не найден .git — сверка контрактов с диффом невозможна"]
    if _git(root, "rev-parse", "--verify", base) is None:
        return [f"[C7] ревизия {base} не найдена"]
    changed = _git(root, "diff", "--name-only", base, "--")
    if changed is None:
        return ["[C7] не удалось получить git diff"]
    errors = []
    for rel in changed.splitlines():
        rel = rel.strip()
        if not rel or Path(rel).suffix not in CODE_EXTENSIONS:
            continue
        current = root / rel
        if not current.is_file():
            continue
        old_text = _git(root, "show", f"{base}:{rel}")
        if old_text is None:
            continue
        new_text = _read_text(current)
        if new_text is None:
            continue
        if _behavior_lines(old_text) != _behavior_lines(new_text):
            if _contract_text(old_text) == _contract_text(new_text):
                errors.append(f"[C7] {rel}: поведение изменено без изменения контракта")
    return errors


# PURPOSE: Выделить строки поведения, игнорируя комментарии и пустые строки.
# INPUTS:
#   text: str — содержимое файла.
# OUTPUTS:
#   list[str] — значимые строки кода.
# ERRORS: нет.
# KEYWORDS: [Behavior, Comments, Diff, Normalize]
# TESTS: [T-NUKE-019]
def _behavior_lines(text):
    result = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _is_comment_line(stripped):
            continue
        result.append(stripped)
    return result


# PURPOSE: Выделить строки контрактов, чтобы отличить правку контракта от правки поведения.
# INPUTS:
#   text: str — содержимое файла.
# OUTPUTS:
#   list[str] — нормализованные строки контрактных полей и якорей.
# ERRORS: нет.
# KEYWORDS: [Contract, Diff, Fields, Anchors]
# TESTS: [T-NUKE-019]
def _contract_text(text):
    result = []
    for line in text.splitlines():
        stripped = _strip_comment(line).strip()
        if not stripped:
            continue
        if "MODULE CONTRACT" in stripped or "START_BLOCK_" in stripped or "END_BLOCK_" in stripped:
            result.append(stripped)
        elif FIELD_LINE_RE.match(stripped) or stripped.startswith("TEST_ID:"):
            result.append(stripped)
    return result


# PURPOSE: Определить, является ли строка комментарием в поддерживаемых языках.
# INPUTS:
#   stripped: str — строка без внешних пробелов.
# OUTPUTS:
#   bool — True для #, //, /*, *, <!-- и */.
# ERRORS: нет.
# KEYWORDS: [Comment, Syntax, Languages]
# TESTS: [T-NUKE-019]
def _is_comment_line(stripped):
    return stripped.startswith(("#", "//", "/*", "*", "<!--"))


# PURPOSE: Собрать якоря по узлам графа, чтобы проверить block в журнале.
# INPUTS:
#   root: Path — корень; graph: dict | None — граф.
# OUTPUTS:
#   dict[str, set[str]] — id узла → множество ID якорей в его файлах.
# ERRORS: нет: нечитаемые файлы пропускаются.
# KEYWORDS: [Anchors, Graph, Nodes, Log, Blocks]
# TESTS: [T-NUKE-017]
def _anchors_by_node(root, graph):
    anchors = {}
    if not graph:
        return anchors
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or not node.get("id"):
            continue
        node_path = (Path(root) / str(node.get("path") or "").rstrip("/"))
        paths = [node_path] if node_path.is_file() else list(node_path.rglob("*")) if node_path.exists() else []
        found = set()
        for path in paths:
            if not path.is_file() or path.suffix not in CODE_EXTENSIONS:
                continue
            text = _read_text(path) or ""
            for line in text.splitlines():
                match = START_ANCHOR_RE.search(_strip_comment(line))
                if match:
                    found.add(match.group(1))
        anchors[node["id"]] = found
    return anchors


# PURPOSE: Выполнить git-команду в корне репозитория и вернуть stdout.
# INPUTS:
#   root: Path — рабочий каталог; args — аргументы git.
# OUTPUTS:
#   str | None — stdout при успехе, None при ошибке или отсутствии git.
# ERRORS: нет исключений: сбои git возвращают None.
# KEYWORDS: [Git, Subprocess, History, Diff]
# TESTS: [T-NUKE-019]
def _git(root, *args):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout
# END_BLOCK_LOG_AND_DIFF


# START_BLOCK_MAIN: Оркестрация проверок и CLI. #KEYWORDS: Audit,Report,Checks,Ci
# PURPOSE: Собрать все проверки в один отчёт и вернуть код возврата для CI.
# INPUTS:
#   root: Path — корень; log_path: Path | None — журнал сборки; base: str | None — ревизия для C7.
# OUTPUTS:
#   list[str] — все найденные расхождения.
# ERRORS: нет исключений: каждая проверка изолирована.
# KEYWORDS: [Audit, Report, Checks, Ci]
# TESTS: [T-NUKE-021]
def audit(root, log_path=None, base=None):
    root = Path(root)
    log = EventLogger("nuke-audit")
    graph, errors = load_graph(root)
    errors.extend(check_graph(root, graph))
    errors.extend(check_module_contracts(root, graph))
    errors.extend(check_purpose_contracts(root))
    errors.extend(check_anchors(root))
    errors.extend(check_markdown(root))
    errors.extend(check_test_ids(root))
    errors.extend(check_log(root, graph, log_path))
    errors.extend(check_contracts_with_diff(root, base))
    if log.enabled:
        for name, count in _errors_by_check(errors).items():
            log.event(
                "RUN_CHECKS",
                "audit",
                "nuke_audit.audit",
                "ok" if count == 0 else "error",
                check=name,
                errors=count,
            )
        log.event("RUN_CHECKS", "audit", "nuke_audit.audit", "ok", nodes=len(_node_ids(graph)), errors=len(errors))
    return errors


# PURPOSE: Сгруппировать сообщения аудита по коду проверки для журнала и отчёта.
# INPUTS:
#   errors: list[str] — сообщения вида «[C1] …».
# OUTPUTS:
#   dict[str, int] — код проверки → число расхождений.
# ERRORS: нет.
# KEYWORDS: [Audit, Report, Group, Codes]
# TESTS: [T-NUKE-021]
def _errors_by_check(errors):
    counts = {}
    for message in errors:
        match = re.match(r"^\[(C\d+)\]", message)
        key = match.group(1) if match else "other"
        counts[key] = counts.get(key, 0) + 1
    return counts


# PURPOSE: Запустить аудит из командной строки и напечатать отчёт.
# INPUTS:
#   argv: list[str] | None — аргументы CLI: --root, --log, --base.
# OUTPUTS:
#   int — 0 при соответствии, 1 при расхождениях.
# ERRORS: SystemExit(1) — при найденных расхождениях.
# SIDE EFFECTS: печать в stdout/stderr, запись в журнал при NUKE_LOG.
# KEYWORDS: [Cli, Audit, ExitCode, Report]
# TESTS: [T-NUKE-021]
def main(argv=None):
    parser = argparse.ArgumentParser(description="Аудит соблюдения стандарта NUKE")
    parser.add_argument("--root", default=str(ROOT), help="корень репозитория")
    parser.add_argument("--log", default=None, help="JSONL-журнал сборки (C9)")
    parser.add_argument("--base", default=None, help="ревизия для сверки контрактов (C7)")
    args = parser.parse_args(argv)
    root = Path(args.root)
    log_path = Path(args.log) if args.log else None
    errors = audit(root, log_path=log_path, base=args.base)
    if errors:
        print(f"NUKE: найдено расхождений — {len(errors)}", file=sys.stderr)
        for message in errors:
            print(f"  • {message}", file=sys.stderr)
        return 1
    graph, _ = load_graph(root)
    nodes = len(_node_ids(graph))
    print(f"NUKE: OK — граф {nodes} узлов, контракты и якоря согласованы")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
# END_BLOCK_MAIN
