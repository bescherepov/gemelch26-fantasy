#!/usr/bin/env python3
# ==== MODULE CONTRACT: tests-nuke ====
# PURPOSE:   Проверять контракт журнала и все проверки аудита NUKE на позитивных, негативных и граничных случаях.
# SCOPE:     JSONL-журнал, разбор графа, контракты, якоря, покрытие, .md, ID тестов, схема лога, сверка с диффом.
# NON-GOALS: Не проверять поведение сборки сайта (tests/test_build.py) и данные (scripts/validate.py).
# INVARIANTS:фикстуры собираются во временном каталоге .tmp и не зависят от реального репозитория; реальный аудит проверяется один раз.
# DEPENDS:   nuke-log:EventLogger, nuke-audit:audit
# EXPOSES:   LogTests, RepoAuditTests, GraphAndLogTests, DiffTests, ReportTests
# ERRORS:    AssertionError — проверка не совпала с ожиданием.
# TESTS:     T-NUKE-001, T-NUKE-002, T-NUKE-003, T-NUKE-004, T-NUKE-005, T-NUKE-006, T-NUKE-007, T-NUKE-008, T-NUKE-009, T-NUKE-010, T-NUKE-011, T-NUKE-012, T-NUKE-013, T-NUKE-014, T-NUKE-015, T-NUKE-016, T-NUKE-017, T-NUKE-018, T-NUKE-019, T-NUKE-020, T-NUKE-021, T-NUKE-022, T-NUKE-023, T-NUKE-024
# ==== END MODULE CONTRACT: tests-nuke ====
"""Тесты журнала и аудита стандарта NUKE."""

from __future__ import annotations

import contextlib
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from nuke_log import EventLogger, LogError  # noqa: E402
import nuke_audit  # noqa: E402

_TEMP_COUNTER = itertools.count(1)

# START_BLOCK_FIXTURE: Мини-репозиторий, соответствующий стандарту, для проверок аудита. #KEYWORDS: Fixture,Repo,Graph,Contract
MODULE_CONTRACT = """\
# ==== MODULE CONTRACT: {module} ====
# PURPOSE:   {purpose}
# SCOPE:     Демонстрационный модуль для проверки аудита.
# NON-GOALS: Ничего, кроме демонстрации схемы контракта.
# INVARIANTS:поведение не зависит от окружения.
# DEPENDS:   {depends}
# EXPOSES:   {exposes}
# ERRORS:    нет.
# TESTS:     {tests}
# ==== END MODULE CONTRACT: {module} ====
"""


# PURPOSE: Создать пустой временный каталог внутри .tmp, который песочница позволяет удалить.
# INPUTS: prefix — префикс имени; OUTPUTS: Path — пустой каталог; ERRORS: OSError — нет прав на запись.
# KEYWORDS: [Temp, Directory, Fixture, Sandbox]
# TESTS: [T-NUKE-006]
def _temp_dir(prefix="nuke"):
    base = ROOT / ".tmp"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{prefix}-{os.getpid()}-{next(_TEMP_COUNTER)}"
    path.mkdir()
    return path


# PURPOSE: Удалить временный каталог фикстуры, не ломая прогон при частичном отказе.
# INPUTS: path — каталог; OUTPUTS: нет; ERRORS: нет (ошибки удаления игнорируются).
# KEYWORDS: [Temp, Cleanup, Rmtree]
# TESTS: [T-NUKE-006]
def _drop(path):
    shutil.rmtree(str(path), ignore_errors=True)


# PURPOSE: Записать текстовый файл в фикстуру, создавая каталоги.
# INPUTS: root — корень фикстуры; relative — путь; text — содержимое.
# OUTPUTS: Path — созданный файл; ERRORS: OSError — нет прав.
# KEYWORDS: [Fixture, Write, File, Repo]
# TESTS: [T-NUKE-006]
def _write(root, relative, text):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


# PURPOSE: Собрать временный репозиторий с одним модулем, тестом и графом.
# INPUTS: root — пустой временный каталог; module_contract — подменный контракт модуля.
# OUTPUTS: Path — корень фикстуры; ERRORS: OSError — нет прав на запись.
# KEYWORDS: [Fixture, Repo, Graph, Demo, Contract]
# TESTS: [T-NUKE-006]
def _make_repo(root, module_contract=None):
    root = Path(root)
    _write(root, "README.md", "# Демо\n")
    contract = MODULE_CONTRACT.format(
        module="demo",
        purpose="Демонстрировать минимальный соответствующий стандарту модуль.",
        depends="нет.",
        exposes="greet",
        tests="T-DEMO-001",
    ) if module_contract is None else module_contract
    demo = contract + '''"""Демонстрационный модуль."""


# START_BLOCK_GREET: Приветствие по имени. #KEYWORDS: Demo,Greet,Name
# PURPOSE: Поприветствовать пользователя по имени.
# INPUTS:
#   name: str — имя; не пусто.
# OUTPUTS:
#   str — приветствие.
# ERRORS: нет.
# KEYWORDS: [Demo, Greet, Text]
# TESTS: [T-DEMO-001]
def greet(name):
    return "Привет, " + name
# END_BLOCK_GREET
'''
    _write(root, "demo.py", demo)
    test_contract = MODULE_CONTRACT.format(
        module="tests-demo",
        purpose="Проверять демонстрационный модуль.",
        depends="demo:greet",
        exposes="DemoTests",
        tests="T-DEMO-001",
    )
    _write(
        root,
        "tests/test_demo.py",
        test_contract
        + '''"""Тесты демонстрационного модуля."""

import unittest


# PURPOSE: Проверить приветствие демонстрационного модуля.
# INPUTS:
#   —
# OUTPUTS:
#   —
# ERRORS: AssertionError — приветствие не совпало.
# KEYWORDS: [Demo, Test, Greet]
# TESTS: [T-DEMO-001]
class DemoTests(unittest.TestCase):
    # TEST_ID: T-DEMO-001
    def test_greet__returns_text(self):
        self.assertTrue(True)
''',
    )
    _write(
        root,
        "nuke/graph.yaml",
        """# NUKE-GRAPH v1
nuke_version: "2.0"
app: demo
purpose: "Демонстрировать минимальный соответствующий стандарту репозиторий"
stack: [python3.9]
budget_tokens: 8000

nodes:
  - id: demo
    path: demo.py
    purpose: "Показывать демонстрационный символ"
    owns: [greet]
    depends: []
    tests: [tests/test_demo.py]
  - id: tests
    path: tests/
    purpose: "Проверять демонстрационный модуль"
    owns: [test_demo.py]
    depends: [demo]
    tests: [tests/]
""",
    )
    return root


# PURPOSE: Выполнить аудит временной фикстуры и вернуть список расхождений.
# INPUTS: root — корень фикстуры; log_path — журнал для C9.
# OUTPUTS: list[str] — сообщения аудита; ERRORS: нет.
# KEYWORDS: [Audit, Fixture, Report]
# TESTS: [T-NUKE-006]
def _audit(root, log_path=None):
    return nuke_audit.audit(root, log_path=log_path)
# END_BLOCK_FIXTURE


# START_BLOCK_LOG_TESTS: Тесты контракта журнала EventLogger (C9/§9). #KEYWORDS: Log,Jsonl,Schema,Event
# PURPOSE: Проверить запись и валидацию событий журнала.
# INPUTS:
#   —
# OUTPUTS:
#   —
# ERRORS: AssertionError — журнал повёл себя иначе контракта.
# KEYWORDS: [Log, Jsonl, Event, Test]
# TESTS: [T-NUKE-001, T-NUKE-002, T-NUKE-003, T-NUKE-004, T-NUKE-005]
class LogTests(unittest.TestCase):
    # TEST_ID: T-NUKE-001
    def test_event__writes_jsonl_record(self):
        path = _temp_dir("nuke-log") / "build.jsonl"
        try:
            logger = EventLogger("build", sink=path)
            logger.event("RUN_CHECKS", "build", "build.build", "ok", turns=4)
            record = json.loads(path.read_text(encoding="utf-8").strip())
            for key in ("ts", "level", "module", "block", "op", "ref", "outcome", "test"):
                self.assertIn(key, record)
            self.assertEqual(record["module"], "build")
            self.assertEqual(record["block"], "RUN_CHECKS")
            self.assertEqual(record["turns"], 4)
        finally:
            _drop(path.parent)

    # TEST_ID: T-NUKE-002
    def test_disabled__writes_nothing(self):
        with mock.patch.dict(os.environ, {"NUKE_LOG": ""}):
            logger = EventLogger("build", sink=None)
            self.assertFalse(logger.enabled)
            logger.event("RUN_CHECKS", "build", "build.build", "ok")
        with mock.patch.dict(os.environ, {"NUKE_LOG": "0"}):
            self.assertFalse(EventLogger("build", sink=None).enabled)

    # TEST_ID: T-NUKE-003
    def test_empty_fields__raise(self):
        with self.assertRaises(LogError):
            EventLogger("")
        folder = _temp_dir("nuke-log")
        try:
            logger = EventLogger("build", sink=folder / "log.jsonl")
            with self.assertRaises(LogError):
                logger.event("", "build", "build.build", "ok")
        finally:
            _drop(folder)

    # TEST_ID: T-NUKE-004
    def test_stderr_sink__writes_line(self):
        captured = io.StringIO()
        with mock.patch.dict(os.environ, {"NUKE_LOG": "1"}):
            with contextlib.redirect_stderr(captured):
                EventLogger("build", sink=None).event("RUN_CHECKS", "build", "build.build", "ok")
        record = json.loads(captured.getvalue().strip())
        self.assertEqual(record["outcome"], "ok")

    # TEST_ID: T-NUKE-005
    def test_bad_sink__raises_log_error(self):
        folder = _temp_dir("nuke-log")
        try:
            sink = folder / "нет" / "такого" / "каталога" / "log.jsonl"
            with self.assertRaises(LogError):
                EventLogger("build", sink=sink).event("RUN_CHECKS", "build", "build.build", "ok")
        finally:
            _drop(folder)
# END_BLOCK_LOG_TESTS


# START_BLOCK_REPO_TESTS: Тесты проверок C1–C5 на временных фикстурах. #KEYWORDS: Audit,Contracts,Anchors,Graph,Coverage
# PURPOSE: Проверить, что аудит находит каждое типовое расхождение.
# INPUTS:
#   —
# OUTPUTS:
#   —
# ERRORS: AssertionError — расхождение не найдено или найдено лишнее.
# KEYWORDS: [Audit, Contracts, Anchors, Graph, Tests]
# TESTS: [T-NUKE-006, T-NUKE-007, T-NUKE-008, T-NUKE-009, T-NUKE-010, T-NUKE-011, T-NUKE-012, T-NUKE-013, T-NUKE-014, T-NUKE-022]
class RepoAuditTests(unittest.TestCase):
    def setUp(self):
        self.root = _make_repo(_temp_dir("nuke-repo"))

    def tearDown(self):
        _drop(self.root)

    # TEST_ID: T-NUKE-006
    def test_clean_fixture__passes(self):
        self.assertEqual(_audit(self.root), [])

    # TEST_ID: T-NUKE-007
    def test_missing_purpose__fails(self):
        path = self.root / "demo.py"
        text = path.read_text(encoding="utf-8").replace(
            "# PURPOSE: Поприветствовать пользователя по имени.\n", ""
        )
        path.write_text(text, encoding="utf-8")
        errors = _audit(self.root)
        self.assertTrue(any("нет поля PURPOSE" in error or "нет контракта" in error for error in errors), errors)

    # TEST_ID: T-NUKE-008
    def test_unbalanced_anchor__fails(self):
        path = self.root / "demo.py"
        path.write_text(
            path.read_text(encoding="utf-8").replace("# END_BLOCK_GREET\n", ""), encoding="utf-8"
        )
        errors = _audit(self.root)
        self.assertTrue(any("[C2]" in error and "GREET" in error for error in errors), errors)

    # TEST_ID: T-NUKE-009
    def test_nested_anchor__fails(self):
        path = self.root / "demo.py"
        text = path.read_text(encoding="utf-8").replace(
            '    return "Привет, " + name\n',
            '    # START_BLOCK_INNER: Вложенный блок. #KEYWORDS: Inner,Nested\n'
            '    return "Привет, " + name\n'
            "    # END_BLOCK_INNER\n",
        )
        path.write_text(text, encoding="utf-8")
        errors = _audit(self.root)
        self.assertTrue(any("[C3]" in error for error in errors), errors)

    # TEST_ID: T-NUKE-010
    def test_long_block__fails(self):
        path = self.root / "demo.py"
        filler = "".join(f"    pass  # {number}\n" for number in range(205))
        text = path.read_text(encoding="utf-8").replace(
            '    return "Привет, " + name\n', filler + '    return "Привет, " + name\n'
        )
        path.write_text(text, encoding="utf-8")
        errors = _audit(self.root)
        self.assertTrue(any("[C4]" in error for error in errors), errors)

    # TEST_ID: T-NUKE-011
    def test_unknown_dependency__fails(self):
        path = self.root / "nuke" / "graph.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("depends: [demo]", "depends: [missing]"),
            encoding="utf-8",
        )
        errors = _audit(self.root)
        self.assertTrue(any("[C5]" in error and "missing" in error for error in errors), errors)

    # TEST_ID: T-NUKE-012
    def test_uncovered_file__fails(self):
        _write(self.root, "extra.py", "# ==== MODULE CONTRACT: extra ====\n")
        errors = _audit(self.root)
        self.assertTrue(any("[C5]" in error and "extra.py" in error for error in errors), errors)

    # TEST_ID: T-NUKE-013
    def test_extra_markdown__fails(self):
        _write(self.root, "NOTES.md", "# Заметки о коде\n")
        errors = _audit(self.root)
        self.assertTrue(any("[C8]" in error for error in errors), errors)

    # TEST_ID: T-NUKE-014
    def test_unresolved_test_id__fails(self):
        path = self.root / "demo.py"
        path.write_text(
            path.read_text(encoding="utf-8").replace("# TESTS: [T-DEMO-001]", "# TESTS: [T-DEMO-999]"),
            encoding="utf-8",
        )
        errors = _audit(self.root)
        self.assertTrue(any("[C10]" in error and "T-DEMO-999" in error for error in errors), errors)

    # TEST_ID: T-NUKE-022
    def test_missing_contract_field__fails(self):
        root = _make_repo(
            _temp_dir("nuke-repo-field"),
            module_contract=MODULE_CONTRACT.format(
                module="demo",
                purpose="Демонстрировать модуль.",
                depends="нет.",
                exposes="greet",
                tests="T-DEMO-001",
            ).replace("# NON-GOALS: Ничего, кроме демонстрации схемы контракта.\n", ""),
        )
        try:
            errors = _audit(root)
            self.assertTrue(any("NON-GOALS" in error for error in errors), errors)
        finally:
            _drop(root)
# END_BLOCK_REPO_TESTS


# START_BLOCK_GRAPH_LOG_TESTS: Тесты разбора графа и схемы журнала (C5/C9). #KEYWORDS: Graph,Parser,Log,Schema
# PURPOSE: Проверить разбор графа и валидацию JSONL-журнала.
# INPUTS:
#   —
# OUTPUTS:
#   —
# ERRORS: AssertionError — разбор или схема повели себя иначе контракта.
# KEYWORDS: [Graph, Yaml, Log, Schema, Test]
# TESTS: [T-NUKE-015, T-NUKE-016, T-NUKE-017, T-NUKE-018]
class GraphAndLogTests(unittest.TestCase):
    # TEST_ID: T-NUKE-015
    def test_tab_indent__graph_parse_fails(self):
        root = _make_repo(_temp_dir("nuke-yaml"))
        try:
            graph = root / "nuke" / "graph.yaml"
            graph.write_text(
                graph.read_text(encoding="utf-8").replace("    purpose:", "\tpurpose:", 1),
                encoding="utf-8",
            )
            parsed, errors = nuke_audit.load_graph(root)
            self.assertIsNone(parsed)
            self.assertTrue(errors, "ожидалась ошибка разбора YAML")
        finally:
            _drop(root)

    # TEST_ID: T-NUKE-016
    def test_valid_log__passes(self):
        root = _make_repo(_temp_dir("nuke-log-ok"))
        try:
            log_path = root / "build.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "ts": "2026-01-01T00:00:00Z",
                        "level": "INFO",
                        "module": "demo",
                        "block": "GREET",
                        "op": "greet",
                        "ref": "demo.greet",
                        "outcome": "ok",
                        "test": "",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            graph, _ = nuke_audit.load_graph(root)
            self.assertEqual(nuke_audit.check_log(root, graph, log_path), [])
        finally:
            _drop(root)

    # TEST_ID: T-NUKE-017
    def test_broken_log__fails(self):
        root = _make_repo(_temp_dir("nuke-log-bad"))
        try:
            log_path = root / "build.jsonl"
            log_path.write_text('{"module":"demo","block":"NOPE","outcome":"ok"}\n', encoding="utf-8")
            graph, _ = nuke_audit.load_graph(root)
            errors = nuke_audit.check_log(root, graph, log_path)
            self.assertTrue(errors, "ожидались ошибки схемы журнала")
        finally:
            _drop(root)

    # TEST_ID: T-NUKE-018
    def test_graph_parser__reads_nodes(self):
        root = _make_repo(_temp_dir("nuke-yaml-ok"))
        try:
            graph, errors = nuke_audit.load_graph(root)
            self.assertEqual(errors, [])
            self.assertEqual(graph["app"], "demo")
            self.assertEqual([node["id"] for node in graph["nodes"]], ["demo", "tests"])
            self.assertEqual(graph["nodes"][1]["depends"], ["demo"])
        finally:
            _drop(root)
# END_BLOCK_GRAPH_LOG_TESTS


# START_BLOCK_DIFF_TESTS: Тесты C7: контракт меняется вместе с поведением. #KEYWORDS: Diff,Contract,Git,Behavior
# PURPOSE: Проверить сверку изменённого поведения с изменением контракта.
# INPUTS:
#   —
# OUTPUTS:
#   —
# ERRORS: AssertionError — сверка пропустила расхождение.
# KEYWORDS: [Diff, Contract, Git, Behavior, Test]
# TESTS: [T-NUKE-019, T-NUKE-020]
@unittest.skipUnless(shutil.which("git"), "git недоступен")
class DiffTests(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git недоступен")
        self.root = _make_repo(_temp_dir("nuke-diff"))
        for args in (
            ["init"],
            ["config", "user.email", "nuke@example.invalid"],
            ["config", "user.name", "NUKE"],
            ["add", "-A"],
            ["commit", "-m", "init"],
        ):
            result = subprocess.run(
                ["git", *args], cwd=str(self.root), capture_output=True, text=True, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def tearDown(self):
        _drop(self.root)

    # TEST_ID: T-NUKE-019
    def test_behavior_change_without_contract__fails(self):
        path = self.root / "demo.py"
        path.write_text(
            path.read_text(encoding="utf-8").replace('return "Привет, " + name', 'return "Здравствуй, " + name'),
            encoding="utf-8",
        )
        errors = nuke_audit.check_contracts_with_diff(self.root, "HEAD")
        self.assertTrue(any("[C7]" in error and "demo.py" in error for error in errors), errors)

    # TEST_ID: T-NUKE-020
    def test_behavior_with_contract_change__passes(self):
        path = self.root / "demo.py"
        text = path.read_text(encoding="utf-8")
        text = text.replace('return "Привет, " + name', 'return "Здравствуй, " + name')
        text = text.replace(
            "# PURPOSE: Поприветствовать пользователя по имени.",
            "# PURPOSE: Поприветствовать пользователя по имени официально.",
        )
        path.write_text(text, encoding="utf-8")
        self.assertEqual(nuke_audit.check_contracts_with_diff(self.root, "HEAD"), [])
# END_BLOCK_DIFF_TESTS


# START_BLOCK_REPORT_TESTS: Тесты отчёта и реального репозитория. #KEYWORDS: Report,Audit,RealRepo
# PURPOSE: Проверить сводку по кодам проверок и соответствие реального репозитория.
# INPUTS:
#   —
# OUTPUTS:
#   —
# ERRORS: AssertionError — отчёт или реальный аудит разошёлся с ожиданием.
# KEYWORDS: [Report, Audit, Repository, Test]
# TESTS: [T-NUKE-021, T-NUKE-023, T-NUKE-024]
class ReportTests(unittest.TestCase):
    # TEST_ID: T-NUKE-021
    def test_errors_by_check__groups_codes(self):
        counts = nuke_audit._errors_by_check(["[C1] a", "[C2] b", "[C2] c", "без кода"])
        self.assertEqual(counts, {"C1": 1, "C2": 2, "other": 1})

    # TEST_ID: T-NUKE-023
    def test_errors_by_check__empty(self):
        self.assertEqual(nuke_audit._errors_by_check([]), {})

    # TEST_ID: T-NUKE-024
    def test_real_repository__passes_audit(self):
        errors = nuke_audit.audit(ROOT)
        self.assertEqual(errors, [], "\n".join(errors))


if __name__ == "__main__":
    unittest.main()
# END_BLOCK_REPORT_TESTS
