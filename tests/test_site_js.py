# ==== MODULE CONTRACT: tests-site-js ====
# PURPOSE:   Проверять, что site.js синтаксически валиден и цепляется только к тем хукам разметки, которые реально есть в шаблонах.
# SCOPE:     node --check, извлечение data- и id-селекторов из исходника, сверка каждого селектора с templates/*.html.
# NON-GOALS: Не выполнять site.js в браузере, не проверять визуальное поведение, CSS и доступность.
# INVARIANTS:без node тест синтаксиса пропускается с причиной, а не падает; у реального site.js список селекторов непуст; тест не зависит от dist/.
# DEPENDS:   site-js:site.js, templates:HtmlHooks
# EXPOSES:   selectors_used, SiteJsTest
# ERRORS:    нет
# TESTS:     T-SITE-001, T-SITE-002, T-SITE-003, T-SITE-004
# ==== END MODULE CONTRACT: tests-site-js ====
"""Тесты site.js: синтаксис и совпадение JS-селекторов с разметкой шаблонов."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_JS = ROOT / "assets" / "js" / "site.js"
TEMPLATES = ROOT / "templates"

_SELECTOR_CALL_RE = re.compile(
    r"(querySelectorAll|querySelector|getElementById|closest)\(\s*[\"']([^\"']*)[\"']"
)
_DATA_ATTR_RE = re.compile(r"\[(data-[a-z0-9-]+)")
_ATTR_RE = re.compile(r"\[[^\]]*\]")
_ID_RE = re.compile(r"#([A-Za-z][A-Za-z0-9_-]*)")


# PURPOSE: Извлечь из исходника site.js селекторы-хуки разметки, чтобы сверять их с шаблонами.
# INPUTS:
#   source: str — текст site.js; читаются строковые аргументы querySelector/querySelectorAll/getElementById/closest.
# OUTPUTS:
#   list[str] — отсортированные уникальные токены «[data-...]» и «#id»; классы и составные селекторы не возвращаются.
# ERRORS: нет — текст без вызовов селекторов даёт [].
# KEYWORDS: [Selectors, DataAttributes, Id, Hooks, Html]
# TESTS: [T-SITE-002, T-SITE-003, T-SITE-004]
def selectors_used(source):
    found = set()
    for call, literal in _SELECTOR_CALL_RE.findall(source):
        if call == "getElementById":
            found.add("#" + literal)
            continue
        for attr in _DATA_ATTR_RE.findall(literal):
            found.add("[" + attr + "]")
        rest = _ATTR_RE.sub("", literal)
        for ident in _ID_RE.findall(rest):
            found.add("#" + ident)
    return sorted(found)


# PURPOSE: Проверить синтаксис site.js и совпадение его селекторов-хуков с разметкой шаблонов.
# INPUTS: нет — читает assets/js/site.js, templates/*.html и внешний node.
# OUTPUTS: нет — unittest фиксирует результат проверками.
# ERRORS: нет — отсутствие node даёт пропуск теста, а не падение.
# KEYWORDS: [SiteJs, Selectors, Templates, NodeCheck, Tests]
# TESTS: [T-SITE-001, T-SITE-002, T-SITE-003, T-SITE-004]
class SiteJsTest(unittest.TestCase):
    """Проверки синтаксиса и контракта селекторов site.js."""

    # TEST_ID: T-SITE-001
    def test_js_syntax__node_check(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node не установлен — синтаксис site.js не проверен")
        result = subprocess.run(
            [node, "--check", str(SITE_JS)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    # TEST_ID: T-SITE-002
    def test_selectors__exist_in_templates(self):
        selectors = selectors_used(SITE_JS.read_text(encoding="utf-8"))
        template_text = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(TEMPLATES.glob("*.html"))
        )
        for selector in selectors:
            with self.subTest(selector=selector):
                if selector.startswith("["):
                    needle = selector[1:-1]
                else:
                    needle = 'id="%s"' % selector[1:]
                self.assertIn(needle, template_text, f"{selector} не встречается в templates/*.html")

    # TEST_ID: T-SITE-003
    def test_selectors__helper_ignores_non_selectors(self):
        fake_source = (
            'var plain = "data-turn";\n'
            "/* [data-comment] и #anchor в комментарии — не селекторы */\n"
            "var number = 42;\n"
            'var title = "Ходы и карты";\n'
        )
        self.assertEqual(selectors_used(fake_source), [])

    # TEST_ID: T-SITE-004
    def test_selectors__non_empty(self):
        selectors = selectors_used(SITE_JS.read_text(encoding="utf-8"))
        self.assertTrue(selectors, "site.js не привязан ни к одному data- или id-хуку")
        self.assertIn("[data-turn-tab]", selectors)


if __name__ == "__main__":
    unittest.main()
