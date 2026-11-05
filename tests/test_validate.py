#!/usr/bin/env python3
# ==== MODULE CONTRACT: tests-validate ====
# PURPOSE:   Проверять таблицы без картинки и ссылки собранного сайта на позитивных, негативных и граничных случаях.
# SCOPE:     check_table_part, check_link и разбор ссылок dist/ через временный каталог в .tmp.
# NON-GOALS: Не проверять check_dist целиком, сборку сайта и данные реального репозитория.
# INVARIANTS:временный каталог создаётся в .tmp и удаляется в tearDown; validate.errors сбрасывается в setUp.
# DEPENDS:   validate:check_table_part, validate:check_link, validate:check_dist
# EXPOSES:   ValidateHelpersTest
# ERRORS:    AssertionError — проверка валидатора не совпала с ожиданием.
# TESTS:     T-VALIDATE-001, T-VALIDATE-002, T-VALIDATE-003, T-VALIDATE-004, T-VALIDATE-005, T-VALIDATE-006, T-VALIDATE-007, T-VALIDATE-008
# ==== END MODULE CONTRACT: tests-validate ====
"""Тесты проверок таблиц и ссылок в scripts/validate.py."""

from __future__ import annotations

import os
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import validate  # noqa: E402


# START_BLOCK_VALIDATE_TESTS: Тесты таблиц и ссылок валидатора на временном каталоге. #KEYWORDS: Validate,Tables,Links,Dist
# PURPOSE: Проверить check_table_part и check_link на позитивных, негативных и граничных случаях.
# INPUTS:
#   —
# OUTPUTS:
#   —
# ERRORS: AssertionError — проверка валидатора не совпала с ожиданием.
# KEYWORDS: [Validate, Tables, Links, Dist]
# TESTS: [T-VALIDATE-001, T-VALIDATE-002, T-VALIDATE-003, T-VALIDATE-004, T-VALIDATE-005, T-VALIDATE-006, T-VALIDATE-007, T-VALIDATE-008]
class ValidateHelpersTest(unittest.TestCase):
    def setUp(self):
        base = ROOT / ".tmp"
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / f"validate-test-{os.getpid()}"
        shutil.rmtree(self.path, ignore_errors=True)
        self.path.mkdir(parents=True, exist_ok=True)
        self.data = self.path / "data"
        self.dist = self.path / "dist"
        self.data.mkdir()
        self.dist.mkdir()
        self._saved = (validate.ROOT, validate.DATA, validate.DIST, validate.errors)
        validate.ROOT = self.path
        validate.DATA = self.data
        validate.DIST = self.dist
        validate.errors = []

    def tearDown(self):
        validate.ROOT, validate.DATA, validate.DIST, validate.errors = self._saved
        shutil.rmtree(self.path, ignore_errors=True)

    # TEST_ID: T-VALIDATE-001
    def test_table_part__accepts_numeric_table(self):
        item = {"columns": ["Город", "Население"], "rows": [["Мир", "12"], ["Антея", "7"]]}
        validate.check_table_part(item, "tables.json → tables[0]")
        self.assertEqual(validate.errors, [])

    # TEST_ID: T-VALIDATE-002
    def test_table_part__rejects_wrong_cell_count(self):
        item = {"columns": ["Город", "Население"], "rows": [["Мир", "12"], ["Антея"]]}
        validate.check_table_part(item, "tables.json → tables[0]")
        self.assertEqual(len(validate.errors), 1)
        self.assertIn("ожидалось 2 ячеек", validate.errors[0])

    # TEST_ID: T-VALIDATE-003
    def test_table_part__allows_file_table_without_rows(self):
        item = {"id": "table-1", "title": "Таблица", "caption": "Подпись", "file": "assets/img/table.png"}
        validate.check_table_part(item, "tables.json → tables[0]")
        self.assertEqual(validate.errors, [])

    # TEST_ID: T-VALIDATE-004
    def test_link__accepts_existing_target(self):
        page = self.dist / "index.html"
        page.write_text("<html><body>Главная</body></html>", encoding="utf-8")
        (self.dist / "page.html").write_text("<html><body>Страница</body></html>", encoding="utf-8")
        validate.check_link(page, "page.html", {})
        self.assertEqual(validate.errors, [])

    # TEST_ID: T-VALIDATE-005
    def test_link__rejects_missing_target(self):
        page = self.dist / "index.html"
        page.write_text("<html><body>Главная</body></html>", encoding="utf-8")
        validate.check_link(page, "missing.html", {})
        self.assertEqual(len(validate.errors), 1)
        self.assertIn("битая ссылка", validate.errors[0])

    # TEST_ID: T-VALIDATE-006
    def test_link__rejects_missing_anchor(self):
        page = self.dist / "index.html"
        page.write_text("<html><body>Главная</body></html>", encoding="utf-8")
        (self.dist / "page.html").write_text('<html><body><h1 id="top">Страница</h1></body></html>', encoding="utf-8")
        validate.check_link(page, "page.html#nope", {})
        self.assertEqual(len(validate.errors), 1)
        self.assertIn("нет якоря #nope", validate.errors[0])

    # TEST_ID: T-VALIDATE-007
    def test_link__skips_external_schemes(self):
        page = self.dist / "index.html"
        page.write_text("<html><body>Главная</body></html>", encoding="utf-8")
        for link in ("http://example.com/a", "https://example.com/b", "mailto:master@example.com", "tel:+70000000000", "javascript:void(0)"):
            validate.check_link(page, link, {})
        self.assertEqual(validate.errors, [])

    # TEST_ID: T-VALIDATE-008
    def test_link__rejects_path_outside_dist(self):
        page = self.dist / "index.html"
        page.write_text("<html><body>Главная</body></html>", encoding="utf-8")
        (self.path / "outside.html").write_text("<html><body>Вне сайта</body></html>", encoding="utf-8")
        validate.check_link(page, "../outside.html", {})
        self.assertEqual(len(validate.errors), 1)
        self.assertIn("выходит за пределы сайта", validate.errors[0])
# END_BLOCK_VALIDATE_TESTS


if __name__ == "__main__":
    unittest.main()
