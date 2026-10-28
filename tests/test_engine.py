"""Тесты движка шаблонов (стандартный unittest, без зависимостей)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import Safe, Template, TemplateError, TemplateSet  # noqa: E402


def render(source: str, context: dict | None = None) -> str:
    return Template("test", source, lambda name: None).render(context or {})


class TextAndVariables(unittest.TestCase):
    def test_plain_text(self):
        self.assertEqual(render("Привет, мир"), "Привет, мир")

    def test_variable(self):
        self.assertEqual(render("{{ name }}", {"name": "Расфадаль"}), "Расфадаль")

    def test_escaping(self):
        self.assertEqual(
            render("{{ value }}", {"value": '<b title="x">&</b>'}),
            "&lt;b title=&quot;x&quot;&gt;&amp;&lt;/b&gt;",
        )

    def test_safe_filter(self):
        self.assertEqual(render("{{ html | safe }}", {"html": "<b>ok</b>"}), "<b>ok</b>")

    def test_dotted_access(self):
        context = {"turn": {"map": {"caption": "Карта"}}}
        self.assertEqual(render("{{ turn.map.caption }}", context), "Карта")

    def test_missing_key_raises(self):
        with self.assertRaises(TemplateError):
            render("{{ turn.nope }}", {"turn": {}})


class Conditions(unittest.TestCase):
    def test_truthy(self):
        self.assertEqual(render("{% if x %}да{% endif %}", {"x": True}), "да")

    def test_falsy(self):
        self.assertEqual(render("{% if x %}да{% else %}нет{% endif %}", {"x": []}), "нет")

    def test_missing_key_is_falsy_in_condition(self):
        self.assertEqual(render("{% if x.y %}да{% else %}нет{% endif %}", {"x": {}}), "нет")

    def test_elif_chain(self):
        source = "{% if n == 1 %}один{% elif n == 2 %}два{% else %}много{% endif %}"
        self.assertEqual(render(source, {"n": 2}), "два")
        self.assertEqual(render(source, {"n": 7}), "много")

    def test_not(self):
        self.assertEqual(render("{% if not items %}пусто{% endif %}", {"items": []}), "пусто")

    def test_inequality(self):
        source = '{% if a != "b" %}разные{% endif %}'
        self.assertEqual(render(source, {"a": "c"}), "разные")


class Loops(unittest.TestCase):
    def test_loop_metadata(self):
        source = (
            "{% for item in items %}"
            "{{ loop.index }}/{{ loop.length }}:{{ item }}"
            "{% if not loop.last %};{% endif %}"
            "{% endfor %}"
        )
        self.assertEqual(render(source, {"items": ["a", "b"]}), "1/2:a;2/2:b")

    def test_loop_else(self):
        source = "{% for item in items %}{{ item }}{% else %}пусто{% endfor %}"
        self.assertEqual(render(source, {"items": []}), "пусто")

    def test_nested_loop_uses_parent(self):
        source = (
            "{% for row in rows %}"
            "{% for cell in row %}{{ cell }}{% endfor %}|"
            "{% endfor %}"
        )
        self.assertEqual(render(source, {"rows": [[1, 2], [3]]}), "12|3|")


class Filters(unittest.TestCase):
    def test_date_ru(self):
        self.assertEqual(render("{{ d | date_ru }}", {"d": "2026-10-26"}), "26 октября 2026")

    def test_join(self):
        self.assertEqual(render('{{ items | join(", ") }}', {"items": ["а", "б"]}), "а, б")

    def test_default(self):
        self.assertEqual(render('{{ value | default("—") }}', {"value": ""}), "—")

    def test_length(self):
        self.assertEqual(render("{{ items | length }}", {"items": [1, 2, 3]}), "3")

    def test_upper_lower(self):
        self.assertEqual(render("{{ x | upper }}{{ x | lower }}", {"x": "Аб"}), "АБаб")

    def test_number(self):
        self.assertEqual(render("{{ n | number }}", {"n": 1234}), "1 234")


class Includes(unittest.TestCase):
    def test_include(self):
        templates = TemplateSet(ROOT / "tests" / "fixtures")
        self.assertEqual(
            templates.render("page.html", {"content": "текст"}).strip(),
            "<main>текст</main>",
        )

    def test_include_missing(self):
        with self.assertRaises(TemplateError):
            TemplateSet(ROOT).render("nope.html", {})


class Errors(unittest.TestCase):
    def test_unknown_tag(self):
        with self.assertRaises(TemplateError):
            render("{% unknown x %}")

    def test_unclosed_if(self):
        with self.assertRaises(TemplateError):
            render("{% if x %}да")

    def test_unknown_filter(self):
        with self.assertRaises(TemplateError):
            render("{{ x | nope }}", {"x": 1})


class SafeType(unittest.TestCase):
    def test_safe_is_str(self):
        self.assertIsInstance(Safe("x"), str)


if __name__ == "__main__":
    unittest.main()
