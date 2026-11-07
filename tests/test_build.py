# ==== MODULE CONTRACT: tests-build ====
# PURPOSE:   Проверять собранный сайт и сквозной путь data/ → dist/, чтобы регрессии сборки ловились до публикации.
# SCOPE:     сборка через subprocess, наличие страниц, отсутствие шаблонных маркеров, sitemap, контент ходов, построек и таблиц, валидатор с --dist.
# NON-GOALS: Не проверять движок шаблонов (tests/test_engine.py), журнал и аудит (tests/test_nuke.py), данные по отдельности (scripts/validate.py).
# INVARIANTS:сборка выполняется один раз на класс; тесты читают dist/ и data/, но не меняют их; фикстуры не подгоняются под реализацию.
# DEPENDS:   build:*, validate:main, data:*, templates:*
# EXPOSES:   BuildTest, run
# ERRORS:    AssertionError — сборка или проверка не прошла.
# TESTS:     T-BUILD-001, T-BUILD-002, T-BUILD-003, T-BUILD-004, T-BUILD-005, T-BUILD-006, T-BUILD-007, T-BUILD-008, T-BUILD-009, T-BUILD-010, T-BUILD-011, T-BUILD-012, T-BUILD-013, T-BUILD-014, T-BUILD-015, T-BUILD-016, T-BUILD-017
# ==== END MODULE CONTRACT: tests-build ====
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
    "buildings.html",
    "participants.html",
    "log.html",
    "links.html",
    "404.html",
]


# PURPOSE: Запустить сборку или проверку отдельным процессом, чтобы тест видел настоящий результат, а не подменённые объекты.
# INPUTS:
#   *args: str — команда и аргументы, например "build.py" или "scripts/validate.py", "--dist".
# OUTPUTS:
#   subprocess.CompletedProcess — код возврата, stdout и stderr, декодированные как UTF-8.
# ERRORS: нет: сбой процесса возвращается кодом возврата, а не исключением.
# SIDE EFFECTS: порождает процесс; build.py пересоздаёт dist/, validate.py только читает.
# KEYWORDS: [Subprocess, Build, Validate, Dist, CompletedProcess]
# TESTS: [T-BUILD-001, T-BUILD-011, T-BUILD-012]
def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# PURPOSE: Проверить, что сборка создаёт полный сайт и наполняет страницы данными из единственного источника.
# INPUTS:
#   нет: сборка запускается в setUpClass один раз на класс.
# OUTPUTS:
#   нет: тесты класса проверяют файлы dist/ и данные data/.
# ERRORS: AssertionError — сборка упала или страница не соответствует контракту.
# PRECONDITIONS: рядом лежат data/, templates/ и assets/; dist/ пересоздаётся.
# KEYWORDS: [Build, Dist, Pages, Integration, Sitemap]
# TESTS: [T-BUILD-001, T-BUILD-002, T-BUILD-003, T-BUILD-004, T-BUILD-005, T-BUILD-006, T-BUILD-007, T-BUILD-008, T-BUILD-009, T-BUILD-010, T-BUILD-011, T-BUILD-012]
class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run("build.py")
        if result.returncode != 0:
            raise AssertionError(f"build.py упал:\n{result.stdout}\n{result.stderr}")

    # TEST_ID: T-BUILD-001
    def test_build__creates_all_pages(self):
        for page in PAGES:
            with self.subTest(page=page):
                self.assertTrue((DIST / page).is_file(), f"нет {page}")

    # TEST_ID: T-BUILD-002
    def test_render__leaves_no_template_markers(self):
        for page in PAGES:
            text = (DIST / page).read_text(encoding="utf-8")
            self.assertNotIn("{{", text, page)
            self.assertNotIn("{%", text, page)

    # TEST_ID: T-BUILD-003
    def test_sitemap__lists_all_pages(self):
        sitemap = (DIST / "sitemap.xml").read_text(encoding="utf-8")
        for page in PAGES:
            if page == "404.html":
                continue
            self.assertIn(page, sitemap)

    # TEST_ID: T-BUILD-004
    def test_index__has_brand_and_hero(self):
        index = (DIST / "index.html").read_text(encoding="utf-8")
        self.assertIn("Расфадаль", index)
        self.assertIn("hero__title", index)

    # TEST_ID: T-BUILD-005
    def test_turns__has_search_and_stats(self):
        turns = (DIST / "turns.html").read_text(encoding="utf-8")
        self.assertIn("data-search-input", turns)
        self.assertIn("bars__fill", turns)
        self.assertIn('id="turn-3"', turns)

    # TEST_ID: T-BUILD-006
    def test_nojs__keeps_all_turns_reachable(self):
        turns = (DIST / "turns.html").read_text(encoding="utf-8")
        self.assertIn("html.js .turn.is-hidden", (ROOT / "assets/css/style.css").read_text(encoding="utf-8"))
        self.assertIn("turn-1", turns)
        self.assertIn("turn-2", turns)

    # TEST_ID: T-BUILD-007
    def test_buildings__catalog_and_local_rules(self):
        page = (DIST / "buildings.html").read_text(encoding="utf-8")
        self.assertIn('id="changes"', page)
        self.assertIn('id="b-svinarnik"', page)
        self.assertIn("Местное правило", page)
        self.assertIn("data-buildings-input", page)
        self.assertIn('id="cat-agriculture"', page)
        self.assertIn('id="cat-military"', page)
        self.assertNotIn("инн «Пенька»", page)

    # TEST_ID: T-BUILD-008
    def test_local_rules__linked_with_buildings(self):
        import json

        data = json.loads((ROOT / "data/buildings.json").read_text(encoding="utf-8"))
        page = (DIST / "buildings.html").read_text(encoding="utf-8")
        for change in data["changes"]:
            with self.subTest(rule=change["id"]):
                self.assertIn(f'id="change-{change["id"]}"', page)
                for building_id in change["buildings"]:
                    self.assertIn(f'id="b-{building_id}"', page)

    # TEST_ID: T-BUILD-009
    def test_tables__render_images_and_numbers(self):
        import json

        data = json.loads((ROOT / "data/tables.json").read_text(encoding="utf-8"))
        page = (DIST / "tables.html").read_text(encoding="utf-8")
        self.assertTrue(
            any(item.get("rows") for item in data["tables"]),
            "нет ни одной таблицы, собранной из чисел",
        )
        for table in data["tables"]:
            with self.subTest(table=table["id"]):
                marker = f'id="table-{table["id"]}"'
                self.assertIn(marker, page)
                block = page[page.index(marker):]
                block = block[: block.index("</figure>")]
                if table.get("file"):
                    self.assertIn("<img", block)
                    continue
                self.assertIn("<table>", block)
                for column in table["columns"]:
                    self.assertIn(column, block)
                for row in table["rows"]:
                    for cell in row:
                        self.assertIn(cell, block)

    # TEST_ID: T-BUILD-010
    def test_turns__sections_for_every_turn(self):
        import json

        page = (DIST / "turns.html").read_text(encoding="utf-8")
        for path in sorted((ROOT / "data/turns").glob("*.json")):
            number = json.loads(path.read_text(encoding="utf-8"))["number"]
            with self.subTest(turn=path.name, number=number):
                self.assertIn(f'id="turn-{number}"', page)

    # TEST_ID: T-BUILD-011
    def test_turn_gaps__warned_not_fatal(self):
        """Пропуск в нумерации ходов — предупреждение, а не ошибка данных.

        Перенести в JSON успевают не все ходы, а номера приходят из источника,
        поэтому валидатор сообщает о пропуске и продолжает проверку остального.
        """
        import json

        numbers = [
            json.loads(path.read_text(encoding="utf-8"))["number"]
            for path in sorted((ROOT / "data/turns").glob("*.json"))
        ]
        gaps = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
        result = run("scripts/validate.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = "отсутствуют — хроника идёт с пропуском"
        if gaps:
            self.assertIn(marker, result.stdout)
        else:
            self.assertNotIn(marker, result.stdout)

    # TEST_ID: T-BUILD-012
    def test_validate__passes_with_dist(self):
        result = run("scripts/validate.py", "--dist")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Данные: OK", result.stdout)

    # TEST_ID: T-BUILD-013
    def test_buildings__table_has_every_building(self):
        import json

        data = json.loads((ROOT / "data/buildings.json").read_text(encoding="utf-8"))
        page = (DIST / "buildings.html").read_text(encoding="utf-8")
        self.assertIn("bldg-table__table", page)
        self.assertNotIn('class="building"', page)
        self.assertEqual(page.count('<tr class="bldg"'), len(data["buildings"]))
        for column in ("Постройка", "Цена", "Доход", "Производство", "Требования"):
            with self.subTest(column=column):
                self.assertIn(column, page)

    # TEST_ID: T-BUILD-014
    def test_buildings__sort_keys_and_details(self):
        import json

        data = json.loads((ROOT / "data/buildings.json").read_text(encoding="utf-8"))
        page = (DIST / "buildings.html").read_text(encoding="utf-8")
        self.assertIn('id="b-svinarnik" data-name="Свинарник" data-cost="25" data-income="0"', page)
        self.assertIn("data-sort=\"cost\"", page)
        self.assertIn("data-sort=\"income\"", page)
        self.assertIn("cost-expensive", page)
        self.assertIn("income-negative", page)
        self.assertEqual(page.count('<tr class="bldg" id="b-'), len(data["buildings"]))
        self.assertGreaterEqual(page.count("<details>"), len(data["buildings"]) - 5)
        self.assertIn("Инновации и традиции", page)


# PURPOSE: Проверять подготовку числовых таблиц на синтетических данных, чтобы раскраска и ошибки не зависели от содержимого data/.
# INPUTS:
#   нет: тесты вызывают prepare_tables напрямую.
# OUTPUTS:
#   нет: unittest фиксирует уровни раскраски и отказ при неверной ширине строки.
# ERRORS: AssertionError — нарушение контракта prepare_tables.
# KEYWORDS: [PrepareTables, Matrix, Heatmap, Tests]
# TESTS: [T-BUILD-015, T-BUILD-016]
class PrepareTablesTest(unittest.TestCase):
    # TEST_ID: T-BUILD-015
    def test_prepare_tables__builds_levels(self):
        import build

        raw = {
            "tables": [
                {
                    "id": "demo",
                    "layout": "matrix",
                    "heat": "log",
                    "columns": ["Товар", "А", "Б"],
                    "rows": [["Медь", "0", "10"], ["Соль", "10", "0"], ["Уголь", "5", "5"]],
                }
            ]
        }
        table = build.prepare_tables(raw)["tables"][0]
        matrix = table["matrix"]
        self.assertEqual(matrix["columns"], ["А", "Б"])
        self.assertEqual([row["label"] for row in matrix["rows"]], ["Медь", "Соль", "Уголь"])
        for row in matrix["rows"]:
            self.assertEqual(len(row["cells"]), 2)
            for cell in row["cells"]:
                self.assertTrue(0 <= cell["level"] < build.HEAT_LEVELS)
        self.assertGreater(matrix["rows"][1]["cells"][0]["level"], matrix["rows"][0]["cells"][0]["level"])
        self.assertEqual(matrix["rows"][0]["cells"][0]["level"], matrix["rows"][1]["cells"][1]["level"])

    # TEST_ID: T-BUILD-017
    def test_tables__matrix_renders_grid_and_heat(self):
        import json

        data = json.loads((ROOT / "data/tables.json").read_text(encoding="utf-8"))
        page = (DIST / "tables.html").read_text(encoding="utf-8")
        matrices = [table for table in data["tables"] if table.get("layout") == "matrix"]
        self.assertTrue(matrices, "нет ни одной матричной таблицы")
        for table in matrices:
            with self.subTest(table=table["id"]):
                marker = f'id="table-{table["id"]}"'
                self.assertIn(marker, page)
                block = page[page.index(marker):]
                block = block[: block.index("</figure>")]
                self.assertIn("matrix-table", block)
                self.assertIn("heat-0", block)
                for column in table["columns"][1:]:
                    self.assertIn(column, block)
                for row in table["rows"]:
                    self.assertIn(f'<th scope="row">{row[0]}</th>', block)

    # TEST_ID: T-BUILD-016
    def test_prepare_tables__rejects_short_row(self):
        import build

        raw = {
            "tables": [
                {
                    "id": "bad",
                    "layout": "matrix",
                    "columns": ["Товар", "А"],
                    "rows": [["Медь"]],
                }
            ]
        }
        with self.assertRaises(SystemExit):
            build.prepare_tables(raw)


if __name__ == "__main__":
    unittest.main()
