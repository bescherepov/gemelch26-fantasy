"""Минимальный движок шаблонов без внешних зависимостей.

Поддерживает:
    {{ выражение }}            — подстановка с автоэкранированием
    {{ выражение | safe }}     — вставка готового HTML
    {% for x in список %} … {% endfor %}   (доступен loop.index / first / last)
    {% if условие %} … {% elif … %} … {% else %} … {% endif %}
    {% include "partial.html" %}

Фильтры: safe, upper, lower, join(", "), default("—"), date_ru, number, length.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

__all__ = ["TemplateError", "Template", "TemplateSet", "Safe"]


class TemplateError(Exception):
    """Ошибка разбора или рендера шаблона."""


class Safe(str):
    """Строка, которую не нужно экранировать."""


_TOKEN_RE = re.compile(r"(\{\{.*?\}\}|\{%.*?%\})", re.S)
_FOR_RE = re.compile(r"^for\s+([A-Za-z_]\w*)\s+in\s+(.+)$", re.S)
_INCLUDE_RE = re.compile(r"""^include\s+["']([^"']+)["']$""")
_CALL_RE = re.compile(r"^([A-Za-z_]\w*)(?:\((.*)\))?$", re.S)
_COMPARE_RE = re.compile(r"^(.+?)\s*(==|!=)\s*(.+)$", re.S)
_NUM_RE = re.compile(r"^-?\d+$")

_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


# --------------------------------------------------------------------------- #
# Лексер и парсер
# --------------------------------------------------------------------------- #

def _tokenize(source: str) -> list[str]:
    return _TOKEN_RE.split(source)


def _parse(tokens: list[str], name: str) -> list[tuple]:
    nodes, pos = _parse_body(tokens, 0, name, stop=set())
    if pos != len(tokens):
        raise TemplateError(f"{name}: лишний закрывающий тег рядом с {tokens[pos]!r}")
    return nodes


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


# --------------------------------------------------------------------------- #
# Выражения
# --------------------------------------------------------------------------- #

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


def _unquote(text: str):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


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


def _eval_soft(expr: str, ctx: dict):
    """Как _eval_operand, но отсутствующий ключ считается пустым значением.

    Нужно для необязательных полей: {% if epoch.outro %} не должен падать,
    если у эпохи нет заключительной фразы.
    """
    try:
        return _eval_operand(expr, ctx)
    except TemplateError:
        return None


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


# --------------------------------------------------------------------------- #
# Рендер
# --------------------------------------------------------------------------- #

def _to_html(value) -> str:
    if isinstance(value, Safe):
        return str(value)
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


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


class Template:
    def __init__(self, name: str, source: str, loader) -> None:
        self.name = name
        self._loader = loader
        self.nodes = _parse(_tokenize(source), name)

    def render(self, ctx: dict) -> str:
        try:
            return _render(self.nodes, dict(ctx), self)
        except TemplateError as exc:
            raise TemplateError(f"{self.name}: {exc}") from exc


class TemplateSet:
    """Набор шаблонов из каталога с кэшем и include."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._cache: dict[str, Template] = {}

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

    def render(self, name: str, ctx: dict) -> str:
        return self.get(name).render(ctx)
