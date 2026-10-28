"""Интеграционные тесты сборки: собираем сайт и проверяем результат."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

PAGES = [
    "index.html",
    "world.html",
    "ethnoses.html",
    "turns.html",
    "maps.html",
    "tables.html",
    "participants.html",
    "log.html",
    "links.html",
    "404.html",
]


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run("build.py")
        if result.returncode != 0:
            raise AssertionError(f"build.py упал:\n{result.stdout}\n{result.stderr}")

    def test_pages_exist(self):
        for page in PAGES:
            with self.subTest(page=page):
                self.assertTrue((DIST / page).is_file(), f"нет {page}")

    def test_no_unresolved_templates(self):
        for page in PAGES:
            text = (DIST / page).read_text(encoding="utf-8")
            self.assertNotIn("{{", text, page)
            self.assertNotIn("{%", text, page)

    def test_sitemap_lists_pages(self):
        sitemap = (DIST / "sitemap.xml").read_text(encoding="utf-8")
        for page in PAGES:
            if page == "404.html":
                continue
            self.assertIn(page, sitemap)

    def test_index_has_brand_and_hero(self):
        index = (DIST / "index.html").read_text(encoding="utf-8")
        self.assertIn("Расфадаль", index)
        self.assertIn("hero__title", index)

    def test_turns_have_search_and_stats(self):
        turns = (DIST / "turns.html").read_text(encoding="utf-8")
        self.assertIn("data-search-input", turns)
        self.assertIn("bars__fill", turns)
        self.assertIn('id="turn-3"', turns)

    def test_nojs_fallback_keeps_all_turns_reachable(self):
        turns = (DIST / "turns.html").read_text(encoding="utf-8")
        self.assertIn("html.js .turn.is-hidden", (ROOT / "assets/css/style.css").read_text(encoding="utf-8"))
        self.assertIn("turn-1", turns)
        self.assertIn("turn-2", turns)

    def test_validate_and_links(self):
        result = run("scripts/validate.py", "--dist")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Данные: OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
