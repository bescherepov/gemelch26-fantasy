# ==== MODULE CONTRACT: tests-changelog ====
# PURPOSE:   Проверять, что модуль changelog безопасно читает историю git и сливает записи без дублей, с сортировкой и лимитом.
# SCOPE:     normalize, run_git, git_entries и main на временных файлах и подменённом git.
# NON-GOALS: Не ходить в реальную историю репозитория, не менять рабочий data/changelog.json, не собирать сайт.
# INVARIANTS:каждый тест изолирован временным каталогом; рабочий data/ не изменяется; подмены и переменные окружения снимаются в tearDown; проверка отсутствия репозитория задаёт GIT_CEILING_DIRECTORIES, чтобы не зависеть от расположения временного каталога.
# DEPENDS:   changelog:normalize, changelog:git_entries, changelog:main
# EXPOSES:   ChangelogTest, ChangelogMainTest
# ERRORS:    нет
# TESTS:     T-CHANGELOG-001, T-CHANGELOG-002, T-CHANGELOG-003, T-CHANGELOG-004, T-CHANGELOG-005, T-CHANGELOG-006
# ==== END MODULE CONTRACT: tests-changelog ====
"""Тесты модуля changelog: нормализация, чтение git и слияние записей лога."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import changelog  # noqa: E402  (путь к scripts добавлен выше)


# PURPOSE: Проверить чистые функции changelog и чтение git без реального репозитория.
# INPUTS: нет — подмены и временный каталог готовятся в setUp, восстанавливаются в tearDown.
# OUTPUTS: нет — unittest фиксирует результат проверками.
# ERRORS: нет — ошибка подмены всплывает как падение теста.
# KEYWORDS: [Changelog, Normalize, Git, Subprocess, Tests]
# TESTS: [T-CHANGELOG-001, T-CHANGELOG-002, T-CHANGELOG-003]
class ChangelogTest(unittest.TestCase):
    """Чистые функции и чтение истории git без реального репозитория."""

    def setUp(self):
        self._patchers = []

    def tearDown(self):
        for patcher in reversed(self._patchers):
            patcher.stop()

    def _patch(self, target, new=mock.DEFAULT, **kwargs):
        patcher = mock.patch.object(changelog, target, new, **kwargs)
        self._patchers.append(patcher)
        return patcher.start()

    # TEST_ID: T-CHANGELOG-001
    def test_normalize__ignores_case_spaces_and_trailing_dot(self):
        self.assertEqual(
            changelog.normalize("  Добавлен   4-й ход.  "),
            "добавлен 4-й ход",
        )
        self.assertEqual(
            changelog.normalize("ВЕРХНИЙ Регистр"),
            "верхний регистр",
        )

    # TEST_ID: T-CHANGELOG-002
    def test_run_git__outside_repository_returns_empty(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="nuke-changelog-no-git-"))
        self.addCleanup(shutil.rmtree, temp_dir, True)
        # В песочнице системный TEMP может быть недоступен, и tempfile кладёт каталог
        # внутрь репозитория. Потолок поиска не даёт git увидеть .git выше временного каталога,
        # поэтому тест проверяет отсутствие репозитория независимо от расположения TEMP.
        previous = os.environ.get("GIT_CEILING_DIRECTORIES")
        os.environ["GIT_CEILING_DIRECTORIES"] = str(temp_dir.parent)

        def restore_env():
            if previous is None:
                os.environ.pop("GIT_CEILING_DIRECTORIES", None)
            else:
                os.environ["GIT_CEILING_DIRECTORIES"] = previous

        self.addCleanup(restore_env)
        self._patch("ROOT", temp_dir)
        self.assertEqual(changelog.run_git(["log", "--format=%H"]), "")

    # TEST_ID: T-CHANGELOG-003
    def test_git_entries__keeps_data_commits_and_skips_service_ones(self):
        foundation = "a" * 40
        output = "\n".join(
            [
                "b" * 40 + "\t2026-10-26\tДобавлен 4-й ход (915 г.)",
                "c" * 40 + "\t2026-10-25\tMerge branch 'data'",
                "d" * 40 + "\t2026-10-24\tWIP: черновик карты",
                foundation + "\t2026-10-20\tПубликация каркаса сайта",
                "e" * 40 + "\tне дата\tБитая дата",
                "f" * 40 + "\t2026-10-23\tОбновлена политическая карта",
                "g" * 40 + "\t2026-10-22\tRevert «неудачная правка»",
            ]
        )

        def fake_run_git(args):
            if "--diff-filter=A" in args:
                return foundation + "\n"
            return output

        self._patch("run_git", side_effect=fake_run_git)
        self.assertEqual(
            changelog.git_entries(),
            [
                {"date": "2026-10-26", "text": "Добавлен 4-й ход (915 г.)"},
                {"date": "2026-10-23", "text": "Обновлена политическая карта"},
            ],
        )


# PURPOSE: Проверить слияние записей git с курируемым логом на временном changelog.json.
# INPUTS: нет — временный файл лога и подмена git_entries готовятся в setUp.
# OUTPUTS: нет — unittest фиксирует результат проверками.
# ERRORS: нет — ошибка подмены всплывает как падение теста.
# KEYWORDS: [Changelog, Merge, Dedup, Sort, Limit, Tests]
# TESTS: [T-CHANGELOG-004, T-CHANGELOG-005, T-CHANGELOG-006]
class ChangelogMainTest(unittest.TestCase):
    """Слияние записей git с курируемым логом на временном changelog.json."""

    def setUp(self):
        self._patchers = []
        # Файл создаётся в корне репозитория: системный temp в песочнице
        # тестового окружения может быть закрыт на запись.
        handle, name = tempfile.mkstemp(prefix=".nuke-changelog-", suffix=".json", dir=str(ROOT))
        os.close(handle)
        self._changelog = Path(name)
        self._patch("CHANGELOG", self._changelog)

    def tearDown(self):
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._changelog.unlink(missing_ok=True)

    def _patch(self, target, new=mock.DEFAULT, **kwargs):
        patcher = mock.patch.object(changelog, target, new, **kwargs)
        self._patchers.append(patcher)
        return patcher.start()

    def _write_entries(self, entries):
        self._changelog.write_text(
            json.dumps({"entries": entries}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return self._changelog

    def _read_entries(self):
        return json.loads(self._changelog.read_text(encoding="utf-8"))["entries"]

    # TEST_ID: T-CHANGELOG-004
    def test_main__appends_new_git_entries(self):
        self._write_entries([{"date": "2026-10-01", "text": "Курируемая запись"}])
        self._patch(
            "git_entries",
            return_value=[
                {"date": "2026-10-03", "text": "Обновлена политическая карта"},
                {"date": "2026-10-05", "text": "Добавлен 4-й ход (915 г.)"},
            ],
        )

        self.assertEqual(changelog.main(), 0)

        entries = self._read_entries()
        self.assertEqual(
            [entry["date"] for entry in entries],
            ["2026-10-05", "2026-10-03", "2026-10-01"],
        )

    # TEST_ID: T-CHANGELOG-005
    def test_main__skips_existing_entries(self):
        original = [{"date": "2026-10-26", "text": "Опубликован 3-й ход (910 г.) — «Кашшу»."}]
        self._write_entries(original)
        before = self._changelog.read_text(encoding="utf-8")
        self._patch(
            "git_entries",
            return_value=[
                {"date": "2026-10-26", "text": "опубликован  3-й ход (910 г.) — «Кашшу»"}
            ],
        )

        self.assertEqual(changelog.main(), 0)

        self.assertEqual(self._changelog.read_text(encoding="utf-8"), before)
        self.assertEqual(self._read_entries(), original)

    # TEST_ID: T-CHANGELOG-006
    def test_main__limits_entries_to_hundred_and_sorts_desc(self):
        existing = [{"date": "2026-12-31", "text": "Курируемая запись"}]
        self._write_entries(existing)
        fresh = [
            {
                "date": "2026-10-%02d" % (index % 28 + 1),
                "text": "Запись %03d" % index,
            }
            for index in range(120)
        ]
        self._patch("git_entries", return_value=fresh)

        self.assertEqual(changelog.main(), 0)

        entries = self._read_entries()
        self.assertEqual(len(entries), 100)
        expected = sorted(
            existing + fresh,
            key=lambda item: (item["date"], item["text"]),
            reverse=True,
        )[:100]
        self.assertEqual(entries, expected)


if __name__ == "__main__":
    unittest.main()
