# ==== MODULE CONTRACT: tests-engine ====
# PURPOSE:   Проверять контракт движка шаблонов, чтобы регрессии рендера ловились до сборки сайта.
# SCOPE:     подстановка, экранирование, условия, циклы, фильтры, include, ошибки и тип Safe.
# NON-GOALS: вёрстка dist/, запуск build.py, сеть и записи на диск — тесты работают в памяти.
# INVARIANTS:каждый тест сверяет вывод рендера или класс ошибки; фикстуры берутся из tests/fixtures; ID T-ENGINE идут по порядку объявления.
# DEPENDS:   engine:Template, engine:TemplateSet
# EXPOSES:   render, TextAndVariables, Conditions, Loops, Filters, Includes, Errors, SafeType
# ERRORS:    AssertionError — рендер не совпал с ожиданием
# TESTS:     T-ENGINE-001, T-ENGINE-002, T-ENGINE-003, T-ENGINE-004, T-ENGINE-005, T-ENGINE-006,
#            T-ENGINE-007, T-ENGINE-008, T-ENGINE-009, T-ENGINE-010, T-ENGINE-011, T-ENGINE-012,
#            T-ENGINE-013, T-ENGINE-014, T-ENGINE-015, T-ENGINE-016, T-ENGINE-017, T-ENGINE-018,
#            T-ENGINE-019, T-ENGINE-020, T-ENGINE-021, T-ENGINE-022, T-ENGINE-023, T-ENGINE-024,
#            T-ENGINE-025, T-ENGINE-026, T-ENGINE-027, T-ENGINE-028, T-ENGINE-029
# ==== END MODULE CONTRACT: tests-engine ====
"""Тесты движка шаблонов (стандартный unittest, без зависимостей)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import Safe, Template, TemplateError, TemplateSet  # noqa: E402


# PURPOSE: Отрендерить шаблон из строки в памяти, чтобы тест не зависел от файлов на диске.
# INPUTS:
#   source: str — исходник шаблона; context: dict | None — значения, None означает пустой контекст.
# OUTPUTS:
#   str — HTML; отсутствие ключа в {{ }} поднимает TemplateError.
# ERRORS:
#   TemplateError — ошибка шаблона в проверяемом кейсе.
# KEYWORDS: [Render, Helper, Memory, Fixture]
# TESTS: [T-ENGINE-001, T-ENGINE-029]
def render(source: str, context: dict | None = None) -> str:
    return Template("test", source, lambda name: None).render(context or {})


# PURPOSE: Проверить подстановку текста и переменных, чтобы базовый рендер не деградировал.
# INPUTS: —
# OUTPUTS: —
# ERRORS: AssertionError — вывод рендера не совпал с ожиданием.
# KEYWORDS: [PlainText, Variable, Escape, Safe, DottedPath]
# TESTS: [T-ENGINE-001, T-ENGINE-002, T-ENGINE-003, T-ENGINE-004, T-ENGINE-005, T-ENGINE-006]
class TextAndVariables(unittest.TestCase):
    # TEST_ID: T-ENGINE-001
    def test_plain_text__renders_as_is(self):
        self.assertEqual(render("Привет, мир"), "Привет, мир")

    # TEST_ID: T-ENGINE-002
    def test_variable__substitutes_value(self):
        self.assertEqual(render("{{ name }}", {"name": "Расфадаль"}), "Расфадаль")

    # TEST_ID: T-ENGINE-003
    def test_escaping__escapes_html_by_default(self):
        self.assertEqual(
            render("{{ value }}", {"value": '<b title="x">&</b>'}),
            "&lt;b title=&quot;x&quot;&gt;&amp;&lt;/b&gt;",
        )

    # TEST_ID: T-ENGINE-004
    def test_safe_filter__bypasses_escaping(self):
        self.assertEqual(render("{{ html | safe }}", {"html": "<b>ok</b>"}), "<b>ok</b>")

    # TEST_ID: T-ENGINE-005
    def test_dotted_access__resolves_nested_keys(self):
        context = {"turn": {"map": {"caption": "Карта"}}}
        self.assertEqual(render("{{ turn.map.caption }}", context), "Карта")

    # TEST_ID: T-ENGINE-006
    def test_missing_key__raises_template_error(self):
        with self.assertRaises(TemplateError):
            render("{{ turn.nope }}", {"turn": {}})


# PURPOSE: Проверить ветвление if/elif/else, чтобы необязательные блоки страниц рендерились верно.
# INPUTS: —
# OUTPUTS: —
# ERRORS: AssertionError — выбрана не та ветка условия.
# KEYWORDS: [Condition, Truthiness, Elif, Not, Compare]
# TESTS: [T-ENGINE-007, T-ENGINE-008, T-ENGINE-009, T-ENGINE-010, T-ENGINE-011, T-ENGINE-012]
class Conditions(unittest.TestCase):
    # TEST_ID: T-ENGINE-007
    def test_truthy__renders_body(self):
        self.assertEqual(render("{% if x %}да{% endif %}", {"x": True}), "да")

    # TEST_ID: T-ENGINE-008
    def test_falsy__renders_else_branch(self):
        self.assertEqual(render("{% if x %}да{% else %}нет{% endif %}", {"x": []}), "нет")

    # TEST_ID: T-ENGINE-009
    def test_missing_key__is_falsy_in_condition(self):
        self.assertEqual(render("{% if x.y %}да{% else %}нет{% endif %}", {"x": {}}), "нет")

    # TEST_ID: T-ENGINE-010
    def test_elif_chain__picks_matching_branch(self):
        source = "{% if n == 1 %}один{% elif n == 2 %}два{% else %}много{% endif %}"
        self.assertEqual(render(source, {"n": 2}), "два")
        self.assertEqual(render(source, {"n": 7}), "много")

    # TEST_ID: T-ENGINE-011
    def test_not__negates_condition(self):
        self.assertEqual(render("{% if not items %}пусто{% endif %}", {"items": []}), "пусто")

    # TEST_ID: T-ENGINE-012
    def test_inequality__compares_operands(self):
        source = '{% if a != "b" %}разные{% endif %}'
        self.assertEqual(render(source, {"a": "c"}), "разные")


# PURPOSE: Проверить циклы for с метаданными loop, чтобы списки событий и таблиц выводились полностью.
# INPUTS: —
# OUTPUTS: —
# ERRORS: AssertionError — элементы или метаданные цикла не совпали с ожиданием.
# KEYWORDS: [Loop, Metadata, Else, Nested, Scope]
# TESTS: [T-ENGINE-013, T-ENGINE-014, T-ENGINE-015]
class Loops(unittest.TestCase):
    # TEST_ID: T-ENGINE-013
    def test_loop_metadata__exposes_index_and_length(self):
        source = (
            "{% for item in items %}"
            "{{ loop.index }}/{{ loop.length }}:{{ item }}"
            "{% if not loop.last %};{% endif %}"
            "{% endfor %}"
        )
        self.assertEqual(render(source, {"items": ["a", "b"]}), "1/2:a;2/2:b")

    # TEST_ID: T-ENGINE-014
    def test_loop_else__renders_when_empty(self):
        source = "{% for item in items %}{{ item }}{% else %}пусто{% endfor %}"
        self.assertEqual(render(source, {"items": []}), "пусто")

    # TEST_ID: T-ENGINE-015
    def test_nested_loop__uses_parent_scope(self):
        source = (
            "{% for row in rows %}"
            "{% for cell in row %}{{ cell }}{% endfor %}|"
            "{% endfor %}"
        )
        self.assertEqual(render(source, {"rows": [[1, 2], [3]]}), "12|3|")


# PURPOSE: Проверить фильтры значений, чтобы форматирование подписей оставалось предсказуемым.
# INPUTS: —
# OUTPUTS: —
# ERRORS: AssertionError — результат фильтра не совпал с ожиданием; TemplateError в негативном кейсе.
# KEYWORDS: [Filter, DateRu, Join, Default, Plural]
# TESTS: [T-ENGINE-016, T-ENGINE-017, T-ENGINE-018, T-ENGINE-019, T-ENGINE-020, T-ENGINE-021, T-ENGINE-022, T-ENGINE-023]
class Filters(unittest.TestCase):
    # TEST_ID: T-ENGINE-016
    def test_date_ru__formats_iso_date(self):
        self.assertEqual(render("{{ d | date_ru }}", {"d": "2026-10-26"}), "26 октября 2026")

    # TEST_ID: T-ENGINE-017
    def test_join__joins_with_separator(self):
        self.assertEqual(render('{{ items | join(", ") }}', {"items": ["а", "б"]}), "а, б")

    # TEST_ID: T-ENGINE-018
    def test_default__replaces_falsy_value(self):
        self.assertEqual(render('{{ value | default("—") }}', {"value": ""}), "—")

    # TEST_ID: T-ENGINE-019
    def test_length__counts_items(self):
        self.assertEqual(render("{{ items | length }}", {"items": [1, 2, 3]}), "3")

    # TEST_ID: T-ENGINE-020
    def test_upper_lower__changes_case(self):
        self.assertEqual(render("{{ x | upper }}{{ x | lower }}", {"x": "Аб"}), "АБаб")

    # TEST_ID: T-ENGINE-021
    def test_number__groups_thousands(self):
        self.assertEqual(render("{{ n | number }}", {"n": 1234}), "1 234")

    # TEST_ID: T-ENGINE-022
    def test_plural__chooses_russian_form(self):
        source = '{{ n }} {{ n | plural("событие", "события", "событий") }}'
        cases = {1: "1 событие", 2: "2 события", 4: "4 события", 5: "5 событий",
                 11: "11 событий", 21: "21 событие", 57: "57 событий"}
        for number, expected in cases.items():
            self.assertEqual(render(source, {"n": number}), expected)

    # TEST_ID: T-ENGINE-023
    def test_plural__requires_three_forms(self):
        with self.assertRaises(TemplateError):
            render('{{ n | plural("событие") }}', {"n": 1})


# PURPOSE: Проверить include и кэш набора шаблонов, чтобы партиалы подключались из каталога.
# INPUTS: —
# OUTPUTS: —
# ERRORS: AssertionError — вставка партиала не совпала с ожиданием; TemplateError в негативном кейсе.
# KEYWORDS: [Include, TemplateSet, Cache, Fixture]
# TESTS: [T-ENGINE-024, T-ENGINE-025]
class Includes(unittest.TestCase):
    # TEST_ID: T-ENGINE-024
    def test_include__renders_partial(self):
        templates = TemplateSet(ROOT / "tests" / "fixtures")
        self.assertEqual(
            templates.render("page.html", {"content": "текст"}).strip(),
            "<main>текст</main>",
        )

    # TEST_ID: T-ENGINE-025
    def test_include_missing_file__raises_template_error(self):
        with self.assertRaises(TemplateError):
            TemplateSet(ROOT).render("nope.html", {})


# PURPOSE: Проверить отказ движка на неверном шаблоне, чтобы опечатки ловились до публикации.
# INPUTS: —
# OUTPUTS: —
# ERRORS: AssertionError — ошибка TemplateError не поднялась там, где ожидалась.
# KEYWORDS: [Error, UnknownTag, UnclosedIf, UnknownFilter]
# TESTS: [T-ENGINE-026, T-ENGINE-027, T-ENGINE-028]
class Errors(unittest.TestCase):
    # TEST_ID: T-ENGINE-026
    def test_unknown_tag__raises_template_error(self):
        with self.assertRaises(TemplateError):
            render("{% unknown x %}")

    # TEST_ID: T-ENGINE-027
    def test_unclosed_if__raises_template_error(self):
        with self.assertRaises(TemplateError):
            render("{% if x %}да")

    # TEST_ID: T-ENGINE-028
    def test_unknown_filter__raises_template_error(self):
        with self.assertRaises(TemplateError):
            render("{{ x | nope }}", {"x": 1})


# PURPOSE: Зафиксировать тип Safe как подкласс str, чтобы обход экранирования не ломал строковые операции.
# INPUTS: —
# OUTPUTS: —
# ERRORS: AssertionError — Safe перестал быть подклассом str.
# KEYWORDS: [Safe, Str, Subclass, Escaping]
# TESTS: [T-ENGINE-029]
class SafeType(unittest.TestCase):
    # TEST_ID: T-ENGINE-029
    def test_safe_type__is_str_subclass(self):
        self.assertIsInstance(Safe("x"), str)


if __name__ == "__main__":
    unittest.main()
