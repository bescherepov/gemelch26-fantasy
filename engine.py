# ==== MODULE CONTRACT: engine ====
# PURPOSE:   Рендерить HTML-шаблоны сайта с автоэкранированием, чтобы страницы собирались из данных без внешних зависимостей.
# SCOPE:     лексер, парсер узлов, выражения, фильтры, рендер дерева, кэш шаблонов и include.
# NON-GOALS: сеть, запись файлов и dist/, пользовательские теги, журнал операций — модуль чистый (§9).
# INVARIANTS:автоэкранирование включено по умолчанию; отсутствующий ключ в {{ }} — TemplateError; Safe обходит экранирование; рендер не пишет на диск, не зависит от времени и не ведёт лог.
# DEPENDS:   нет.
# EXPOSES:   TemplateError, Safe, Template, TemplateSet, plural_ru
# ERRORS:    TemplateError — ошибка синтаксиса, отсутствующий ключ, неизвестный фильтр/тег
# TESTS:     T-ENGINE-001, T-ENGINE-002, T-ENGINE-003, T-ENGINE-004, T-ENGINE-005, T-ENGINE-006,
#            T-ENGINE-007, T-ENGINE-008, T-ENGINE-009, T-ENGINE-010, T-ENGINE-011, T-ENGINE-012,
#            T-ENGINE-013, T-ENGINE-014, T-ENGINE-015, T-ENGINE-016, T-ENGINE-017, T-ENGINE-018,
#            T-ENGINE-019, T-ENGINE-020, T-ENGINE-021, T-ENGINE-022, T-ENGINE-023, T-ENGINE-024,
#            T-ENGINE-025, T-ENGINE-026, T-ENGINE-027, T-ENGINE-028, T-ENGINE-029
# ==== END MODULE CONTRACT: engine ====
"""Движок HTML-шаблонов без внешних зависимостей."""

from __future__ import annotations

import html
import re
from pathlib import Path

__all__ = ["TemplateError", "Template", "TemplateSet", "Safe", "plural_ru"]


# PURPOSE: Обозначить ошибку разбора или рендера шаблона, чтобы сборка падала с понятной причиной.
# INPUTS:
#   message: str — описание с именем шаблона и причиной; не пустое.
# OUTPUTS: нет — символ существует только как исключение.
# ERRORS: нет.
# KEYWORDS: [TemplateError, Syntax, MissingKey, UnknownFilter, UnknownTag]
# TESTS: [T-ENGINE-006, T-ENGINE-023, T-ENGINE-025, T-ENGINE-026, T-ENGINE-027, T-ENGINE-028]
class TemplateError(Exception):
    """Ошибка разбора или рендера шаблона."""


# PURPOSE: Пометить готовый HTML, чтобы движок вставлял его без экранирования.
# INPUTS:
#   value: str — разметка, безопасность которой подтвердил вызывающий код.
# OUTPUTS: Safe — подкласс str, обходящий автоэкранирование.
# ERRORS: нет.
# KEYWORDS: [Safe, Markup, Escape, RawHtml]
# TESTS: [T-ENGINE-004, T-ENGINE-029]
class Safe(str):
    """Строка, которую не нужно экранировать."""


# START_BLOCK_TOKENIZE_PARSE: Лексер шаблона и рекурсивный разбор узлов for/if/include. #KEYWORDS: Tokenize,Parse,Node,For,If,Include
_TOKEN_RE = re.compile(r"(\{\{.*?\}\}|\{%.*?%\})", re.S)
_FOR_RE = re.compile(r"^for\s+([A-Za-z_]\w*)\s+in\s+(.+)$", re.S)
_INCLUDE_RE = re.compile(r"""^include\s+["']([^"']+)["']$""")


# PURPOSE: Разрезать исходник на текст и теги, чтобы парсер видел плоский поток токенов.
# INPUTS:
#   source: str — исходник шаблона целиком.
# OUTPUTS:
#   list[str] — чередование текста и фрагментов {{ }} / {% %}.
# ERRORS: нет.
# KEYWORDS: [Tokenize, Split, Lexer, Template]
# TESTS: [T-ENGINE-001, T-ENGINE-002, T-ENGINE-026]
def _tokenize(source: str) -> list[str]:
    return _TOKEN_RE.split(source)


# PURPOSE: Разобрать шаблон целиком и отвергнуть лишний закрывающий тег.
# INPUTS:
#   tokens: list[str] — результат лексера; name: str — имя шаблона для ошибок.
# OUTPUTS:
#   list[tuple] — дерево узлов шаблона.
# ERRORS:
#   TemplateError — после разбора остались необработанные токены.
# KEYWORDS: [Parse, Tree, TrailingTag, Template]
# TESTS: [T-ENGINE-010, T-ENGINE-026, T-ENGINE-027]
def _parse(tokens: list[str], name: str) -> list[tuple]:
    nodes, pos = _parse_body(tokens, 0, name, stop=set())
    if pos != len(tokens):
        raise TemplateError(f"{name}: лишний закрывающий тег рядом с {tokens[pos]!r}")
    return nodes


# PURPOSE: Набрать узлы тела блока до стоп-тега, рекурсивно раскрывая вложенные теги.
# INPUTS:
#   tokens: list[str] — токены лексера; pos: int — позиция продолжения разбора;
#   name: str — имя шаблона; stop: set[str] — теги, завершающие тело.
# OUTPUTS:
#   tuple[list[tuple], int] — узлы и позиция стоп-тега.
# ERRORS:
#   TemplateError — неизвестный тег, неверный for/include, незакрытый if.
# KEYWORDS: [ParseBody, Recursion, StopTag, NodeList]
# TESTS: [T-ENGINE-010, T-ENGINE-026, T-ENGINE-027]
def _parse_body(tokens: list[str], pos: int, name: str, stop: set[str]):
    nodes: list[tuple] = []
    while pos < len(tokens):
        token = tokens[pos]
        if token.startswith("{{"):
            nodes.append(("var", token[2:-2].strip()))
            pos += 1
            continue
        if not token.startswith("{%"):
            nodes.append(("text", token))
            pos += 1
            continue

        stmt = token[2:-2].strip()
        tag = stmt.split(None, 1)[0] if stmt else ""
        if tag in stop:
            return nodes, pos

        if tag == "for":
            match = _FOR_RE.match(stmt)
            if not match:
                raise TemplateError(f"{name}: неверный синтаксис for: {stmt!r}")
            var, expr = match.group(1), match.group(2).strip()
            body, pos = _parse_body(tokens, pos + 1, name, {"endfor", "else"})
            else_body: list[tuple] = []
            if _tag_at(tokens, pos) == "else":
                else_body, pos = _parse_body(tokens, pos + 1, name, {"endfor"})
            _expect(tokens, pos, "endfor", name)
            nodes.append(("for", var, expr, body, else_body))
            pos += 1

        elif tag == "if":
            branches: list[tuple[str, list[tuple]]] = []
            condition = stmt[2:].strip()
            body, pos = _parse_body(tokens, pos + 1, name, {"elif", "else", "endif"})
            branches.append((condition, body))
            while pos < len(tokens):
                current = _tag_at(tokens, pos)
                if current == "elif":
                    condition = tokens[pos][2:-2].strip()[4:].strip()
                    body, pos = _parse_body(tokens, pos + 1, name, {"elif", "else", "endif"})
                    branches.append((condition, body))
                elif current == "else":
                    body, pos = _parse_body(tokens, pos + 1, name, {"endif"})
                    branches.append(("__else__", body))
                elif current == "endif":
                    pos += 1
                    break
                else:  # pragma: no cover - защита от неверного шаблона
                    raise TemplateError(f"{name}: ожидался endif")
            else:
                raise TemplateError(f"{name}: незакрытый if")
            nodes.append(("if", branches))

        elif tag == "include":
            match = _INCLUDE_RE.match(stmt)
            if not match:
                raise TemplateError(f"{name}: неверный include: {stmt!r}")
            nodes.append(("include", match.group(1)))
            pos += 1

        else:
            raise TemplateError(f"{name}: неизвестный тег {tag!r}")

    return nodes, pos


def _tag_at(tokens: list[str], pos: int) -> str | None:
    if pos >= len(tokens) or not tokens[pos].startswith("{%"):
        return None
    stmt = tokens[pos][2:-2].strip()
    return stmt.split(None, 1)[0] if stmt else ""


def _expect(tokens: list[str], pos: int, tag: str, name: str) -> None:
    if _tag_at(tokens, pos) != tag:
        raise TemplateError(f"{name}: ожидался {tag}")
# END_BLOCK_TOKENIZE_PARSE


# START_BLOCK_EXPRESSION_FILTERS: Подготовка фильтров: разбор цепочки, аргументов и форм слова. #KEYWORDS: Filter,Split,Quote,Plural,Russian
_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


# PURPOSE: Отделить базовое значение от цепочки фильтров, не разрывая строки в кавычках.
# INPUTS:
#   expr: str — выражение из {{ }} или операнд условия.
# OUTPUTS:
#   list[str] — значение первым элементом, затем фильтры с аргументами.
# ERRORS: нет.
# KEYWORDS: [Split, Filter, Pipeline, Quote, Expression]
# TESTS: [T-ENGINE-002, T-ENGINE-028]
def _split_filters(expr: str) -> list[str]:
    parts, buf, quote = [], [], None
    for char in expr:
        if quote:
            buf.append(char)
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            buf.append(char)
        elif char == "|":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(char)
    parts.append("".join(buf).strip())
    return parts


def _split_args(raw: str) -> list[str]:
    """Делит аргументы фильтра по запятым вне кавычек."""
    parts, buf, quote = [], [], None
    for char in raw:
        if quote:
            buf.append(char)
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            buf.append(char)
        elif char == ",":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(char)
    parts.append("".join(buf).strip())
    return [part for part in parts if part]


# PURPOSE: Выбрать русскую форму слова по числу, чтобы подписи читались естественно.
# INPUTS:
#   number: int — количество; one: str — форма для 1; few: str — для 2–4; many: str — для 5+.
# OUTPUTS:
#   str — одна из переданных форм.
# ERRORS: нет.
# KEYWORDS: [Plural, Russian, Declension, Number, Grammar]
# TESTS: [T-ENGINE-022]
def plural_ru(number: int, one: str, few: str, many: str) -> str:
    """Русская форма слова по числу: 1 событие, 2 события, 5 событий."""
    tail, hundred = number % 10, number % 100
    if tail == 1 and hundred != 11:
        return one
    if 2 <= tail <= 4 and not 12 <= hundred <= 14:
        return few
    return many


def _unquote(text: str):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text
# END_BLOCK_EXPRESSION_FILTERS


# START_BLOCK_EXPRESSION_EVAL: Вычисление операндов, разрешение путей и применение фильтров. #KEYWORDS: Resolve,Eval,Filter,Condition,Literal
_CALL_RE = re.compile(r"^([A-Za-z_]\w*)(?:\((.*)\))?$", re.S)
_COMPARE_RE = re.compile(r"^(.+?)\s*(==|!=)\s*(.+)$", re.S)
_NUM_RE = re.compile(r"^-?\d+$")


# PURPOSE: Найти значение по точечному пути в контексте, чтобы {{ a.b }} работал предсказуемо.
# INPUTS:
#   path: str — путь через точки; ctx: dict — корень поиска.
# OUTPUTS:
#   значение из контекста; литералы true/false/none дают bool или None.
# ERRORS:
#   TemplateError — ключа нет в словаре или атрибута нет у объекта.
# KEYWORDS: [Resolve, DottedPath, Context, MissingKey]
# TESTS: [T-ENGINE-002, T-ENGINE-005, T-ENGINE-006]
def _resolve(path: str, ctx: dict):
    if path in ("true", "True"):
        return True
    if path in ("false", "False"):
        return False
    if path in ("none", "None", "null"):
        return None
    current = ctx
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise TemplateError(f"нет ключа {part!r} в {path!r}")
            current = current[part]
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            raise TemplateError(f"не удалось разрешить {path!r}")
    return current


def _literal(text: str):
    text = text.strip()
    if _NUM_RE.match(text):
        return int(text)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return _resolve(text, {})


# PURPOSE: Применить фильтр к значению по имени, чтобы шаблоны оставались без логики.
# INPUTS:
#   name: str — имя фильтра из белого списка; arg: str | None — аргумент в скобках; value — вход.
# OUTPUTS:
#   значение после фильтра; safe возвращает Safe, length и plural — числа или строки.
# ERRORS:
#   TemplateError — неизвестный фильтр, неверное число форм plural, неверная дата.
# KEYWORDS: [Filter, Registry, Safe, DateRu, Plural]
# TESTS: [T-ENGINE-004, T-ENGINE-016, T-ENGINE-017, T-ENGINE-018, T-ENGINE-019, T-ENGINE-020, T-ENGINE-021, T-ENGINE-022, T-ENGINE-023, T-ENGINE-028]
def _apply_filter(name: str, arg: str | None, value):
    if name == "safe":
        return Safe("" if value is None else str(value))
    if name == "upper":
        return str(value).upper()
    if name == "lower":
        return str(value).lower()
    if name == "length":
        return len(value)
    if name == "join":
        sep = _unquote(arg) if arg else ", "
        return sep.join(str(item) for item in value)
    if name == "default":
        fallback = _unquote(arg) if arg is not None else ""
        return value if value else fallback
    if name == "date_ru":
        from datetime import datetime
        parsed = datetime.strptime(str(value), "%Y-%m-%d").date()
        return f"{parsed.day} {_MONTHS[parsed.month - 1]} {parsed.year}"
    if name == "number":
        return f"{int(value):,}".replace(",", " ")
    if name == "plural":
        forms = [_unquote(part) for part in _split_args(arg or "")]
        if len(forms) != 3:
            raise TemplateError("фильтр plural требует три формы: одна, две, много")
        return plural_ru(int(value), *forms)
    raise TemplateError(f"неизвестный фильтр {name!r}")


def _eval_expr(expr: str, ctx: dict):
    parts = _split_filters(expr)
    value = _resolve(parts[0], ctx)
    for raw in parts[1:]:
        match = _CALL_RE.match(raw)
        if not match:
            raise TemplateError(f"неверный фильтр {raw!r}")
        value = _apply_filter(match.group(1), match.group(2), value)
    return value


def _eval_operand(text: str, ctx: dict):
    text = text.strip()
    if _NUM_RE.match(text):
        return int(text)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text in ("true", "True"):
        return True
    if text in ("false", "False"):
        return False
    if text in ("none", "None", "null"):
        return None
    return _eval_expr(text, ctx)


# PURPOSE: Вычислить операнд условия, считая отсутствующий ключ пустым значением.
# INPUTS:
#   expr: str — операнд условия; ctx: dict — контекст.
# OUTPUTS:
#   значение операнда или None, если ключа нет.
# ERRORS: нет — TemplateError подавляется намеренно ради необязательных полей.
# KEYWORDS: [SoftEval, Optional, MissingKey, Condition]
# TESTS: [T-ENGINE-009, T-ENGINE-011, T-ENGINE-012]
def _eval_soft(expr: str, ctx: dict):
    """Как _eval_operand, но отсутствующий ключ считается пустым значением.

    Нужно для необязательных полей: {% if epoch.outro %} не должен падать,
    если у эпохи нет заключительной фразы.
    """
    try:
        return _eval_operand(expr, ctx)
    except TemplateError:
        return None


# PURPOSE: Решить, какая ветка if/elif рендерится, по истинности или сравнению.
# INPUTS:
#   expr: str — условие; ctx: dict — контекст.
# OUTPUTS:
#   bool — результат условия; отсутствующий ключ считается ложным.
# ERRORS: нет — ошибки выражения проглатываются soft-вычислением.
# KEYWORDS: [Condition, Compare, Not, Truthiness, Branch]
# TESTS: [T-ENGINE-007, T-ENGINE-008, T-ENGINE-009, T-ENGINE-010, T-ENGINE-011, T-ENGINE-012]
def _eval_condition(expr: str, ctx: dict) -> bool:
    expr = expr.strip()
    if expr.startswith("not "):
        return not _eval_condition(expr[4:], ctx)
    match = _COMPARE_RE.match(expr)
    if match:
        left = _eval_soft(match.group(1), ctx)
        right = _eval_soft(match.group(3), ctx)
        return (left == right) if match.group(2) == "==" else (left != right)
    return bool(_eval_soft(expr, ctx))
# END_BLOCK_EXPRESSION_EVAL


# START_BLOCK_RENDER_TREE: Обход дерева узлов и сборка HTML с экранированием. #KEYWORDS: Render,Tree,Recursion,Loop,Include,Escape
# PURPOSE: Вставить значение в HTML, экранируя всё, кроме помеченного Safe.
# INPUTS:
#   value — любое значение контекста; None даёт пустую строку.
# OUTPUTS:
#   str — HTML-фрагмент; спецсимволы заменены на сущности.
# ERRORS: нет.
# KEYWORDS: [Escape, Safe, Html, Autoescape]
# TESTS: [T-ENGINE-003, T-ENGINE-004]
def _to_html(value) -> str:
    if isinstance(value, Safe):
        return str(value)
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


# PURPOSE: Собрать HTML из дерева узлов, рекурсивно раскрывая for/if/include.
# INPUTS:
#   nodes: list[tuple] — дерево разбора; ctx: dict — значения; template: Template — владелец для include.
# OUTPUTS:
#   str — HTML фрагмента шаблона.
# ERRORS:
#   TemplateError — неизвестный узел, ошибка выражения или отсутствующий include.
# KEYWORDS: [Render, Tree, Recursion, Loop, Include, Escape]
# TESTS: [T-ENGINE-001, T-ENGINE-002, T-ENGINE-003, T-ENGINE-007, T-ENGINE-008, T-ENGINE-013, T-ENGINE-014, T-ENGINE-015, T-ENGINE-024]
def _render(nodes: list[tuple], ctx: dict, template: "Template") -> str:
    out: list[str] = []
    for node in nodes:
        kind = node[0]

        if kind == "text":
            out.append(node[1])

        elif kind == "var":
            out.append(_to_html(_eval_expr(node[1], ctx)))

        elif kind == "for":
            _, var, expr, body, else_body = node
            items = _eval_expr(expr, ctx)
            if not items:
                out.append(_render(else_body, ctx, template))
                continue
            sequence = list(items)
            total = len(sequence)
            for index, item in enumerate(sequence):
                child = dict(ctx)
                child[var] = item
                child["loop"] = {
                    "index": index + 1,
                    "index0": index,
                    "first": index == 0,
                    "last": index == total - 1,
                    "length": total,
                }
                out.append(_render(body, child, template))

        elif kind == "if":
            for condition, body in node[1]:
                if condition == "__else__" or _eval_condition(condition, ctx):
                    out.append(_render(body, ctx, template))
                    break

        elif kind == "include":
            out.append(template._loader(node[1]).render(ctx))

        else:  # pragma: no cover
            raise TemplateError(f"неизвестный узел {kind!r}")

    return "".join(out)
# END_BLOCK_RENDER_TREE


# START_BLOCK_TEMPLATE_API: Публичный API шаблона и набора шаблонов с кэшем. #KEYWORDS: Template,TemplateSet,Cache,Include,Api
# PURPOSE: Разобрать исходник шаблона один раз и отрендерить его с контекстом.
# INPUTS:
#   name: str — имя для сообщений об ошибках; source: str — текст шаблона;
#   loader — функция загрузки include по имени.
# OUTPUTS:
#   Template — разобранный шаблон, готовый к рендеру.
# ERRORS:
#   TemplateError — синтаксис шаблона не разобран.
# KEYWORDS: [Template, Parse, Render, Include, Context]
# TESTS: [T-ENGINE-001, T-ENGINE-006, T-ENGINE-024]
class Template:
    def __init__(self, name: str, source: str, loader) -> None:
        self.name = name
        self._loader = loader
        self.nodes = _parse(_tokenize(source), name)

    # PURPOSE: Отрендерить шаблон с контекстом, добавляя имя шаблона к тексту ошибки.
    # INPUTS:
    #   ctx: dict — значения; копируется, исходный словарь не мутируется.
    # OUTPUTS:
    #   str — HTML страницы.
    # ERRORS:
    #   TemplateError — отсутствующий ключ или ошибка include, с префиксом имени.
    # KEYWORDS: [Render, Context, Html, ErrorPrefix]
    # TESTS: [T-ENGINE-001, T-ENGINE-002, T-ENGINE-006]
    def render(self, ctx: dict) -> str:
        try:
            return _render(self.nodes, dict(ctx), self)
        except TemplateError as exc:
            raise TemplateError(f"{self.name}: {exc}") from exc


# PURPOSE: Держать набор шаблонов каталога с кэшем, чтобы include не перечитывал диск.
# INPUTS:
#   root: Path — каталог шаблонов; путь нормализуется.
# OUTPUTS:
#   TemplateSet — доступ к шаблонам по имени.
# ERRORS:
#   TemplateError — запрошенный шаблон не найден.
# KEYWORDS: [TemplateSet, Cache, Directory, Include]
# TESTS: [T-ENGINE-024, T-ENGINE-025]
class TemplateSet:
    """Набор шаблонов из каталога с кэшем и include."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._cache: dict[str, Template] = {}

    # PURPOSE: Вернуть шаблон по имени из кэша, разбирая файл только при первом обращении.
    # INPUTS:
    #   name: str — путь относительно корня; обратные слэши нормализуются.
    # OUTPUTS:
    #   Template — разобранный шаблон из кэша.
    # ERRORS:
    #   TemplateError — файла шаблона нет в каталоге.
    # KEYWORDS: [Get, Cache, Normalize, Lookup]
    # TESTS: [T-ENGINE-024, T-ENGINE-025]
    def get(self, name: str) -> Template:
        name = name.replace("\\", "/")
        if name not in self._cache:
            path = self.root / name
            if not path.is_file():
                raise TemplateError(f"шаблон не найден: {name}")
            self._cache[name] = Template(
                name, path.read_text(encoding="utf-8"), self.get
            )
        return self._cache[name]

    # PURPOSE: Отрендерить шаблон по имени, не раскрывая кэш наружу.
    # INPUTS:
    #   name: str — имя шаблона; ctx: dict — контекст рендера.
    # OUTPUTS:
    #   str — HTML.
    # ERRORS:
    #   TemplateError — шаблон не найден или рендер не удался.
    # KEYWORDS: [Render, Lookup, Html]
    # TESTS: [T-ENGINE-024, T-ENGINE-025]
    def render(self, name: str, ctx: dict) -> str:
        return self.get(name).render(ctx)
# END_BLOCK_TEMPLATE_API
