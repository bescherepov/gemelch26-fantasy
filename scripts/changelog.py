#!/usr/bin/env python3
# ==== MODULE CONTRACT: changelog ====
# PURPOSE:   Дополнять курируемый лог изменений записями из истории git по каталогу data/, чтобы хронология правок данных велась без ручного труда.
# SCOPE:     чтение git log по data/, отсев merge/revert/WIP и коммита-основания, слияние с data/changelog.json по нормализованному ключу (дата, текст), сортировка по убыванию даты, лимит 100 записей, журнал операций.
# NON-GOALS: Не собирать сайт, не проверять данные, не писать другие файлы, не ходить в сеть, не менять сообщения коммитов.
# INVARIANTS:без git модуль завершается успешно и не пишет файл; дубликаты записей не появляются; после записи лог отсортирован по дате по убыванию и не длиннее 100 записей; выключенный журнал не меняет stdout, stderr и результат.
# DEPENDS:   data:Changelog, nuke-log:EventLogger
# EXPOSES:   main, git_entries, foundation_commits, normalize, run_git
# ERRORS:    нет исключений — при недоступном git возвращается ""; LogError журнала возможен только при включённом NUKE_LOG.
# TESTS:     T-CHANGELOG-001, T-CHANGELOG-002, T-CHANGELOG-003, T-CHANGELOG-004, T-CHANGELOG-005, T-CHANGELOG-006
# ==== END MODULE CONTRACT: changelog ====
"""Дополняет data/changelog.json записями из истории git по каталогу data/.

Идея: лог изменений не ведётся вручную. Всё, что меняло данные, попадает
в лог из сообщений коммитов. Курируемые записи (например, о старте партии)
сохраняются, если их ещё нет в истории.

В лог не попадают:
- merge/revert/WIP-коммиты;
- коммит, который создаёт data/site.json, — это публикация сайта, а не
  изменение игровых данных.

Запускается в CI перед сборкой; безопасен при отсутствии git.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    # Скрипт запускают как `python scripts/changelog.py`, поэтому корень
    # репозитория (где живёт nuke_log.py) не попадает в sys.path сам.
    sys.path.insert(0, str(ROOT))

from nuke_log import EventLogger  # noqa: E402  (путь к корню добавлен выше)

CHANGELOG = ROOT / "data" / "changelog.json"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SKIP_PREFIXES = ("Merge ", "merge ", "Revert ", "revert ", "WIP", "wip")

# Журнал выключен, пока не задан NUKE_LOG; при выключенном журнале события — no-op.
log = EventLogger("changelog")


# PURPOSE: Привести сообщение коммита к ключу сравнения, чтобы отличать дубликаты независимо от пробелов, регистра и завершающей точки.
# INPUTS:
#   text: str — сообщение коммита или запись лога; может быть пустым.
# OUTPUTS:
#   str — нижний регистр, одиночные пробелы, без завершающей точки; пустой вход → "".
# ERRORS: нет — нестроковый вход приводится через str().
# KEYWORDS: [Normalize, CommitMessage, Dedup, Key, Changelog]
# TESTS: [T-CHANGELOG-001]
def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().rstrip(".")).lower()


# START_BLOCK_GIT_READ: Безопасное чтение истории git по каталогу data/. #KEYWORDS: Git,Log,History,Commits,Foundation
# PURPOSE: Прочитать вывод git, не роняя сборку при отсутствии git или репозитория.
# INPUTS:
#   args: list[str] — аргументы git (подкоманда и фильтры); рабочий каталог — ROOT.
# OUTPUTS:
#   str — stdout при коде возврата 0; "" при недоступном git или ошибке.
# ERRORS: нет — FileNotFoundError и ненулевой код возврата дают "".
# KEYWORDS: [Git, Subprocess, Fallback, Safe, History]
# TESTS: [T-CHANGELOG-002, T-CHANGELOG-003]
def run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


# PURPOSE: Найти коммиты, создавшие data/site.json, чтобы не выдавать публикацию каркаса сайта за игровое изменение.
# INPUTS:
#   нет; читает git log с --diff-filter=A по data/site.json.
# OUTPUTS:
#   set[str] — хеши коммитов-оснований; пустое множество без git.
# ERRORS: нет.
# KEYWORDS: [Git, Foundation, Skip, Publication, site.json]
# TESTS: [T-CHANGELOG-003]
def foundation_commits() -> set[str]:
    output = run_git(["log", "--diff-filter=A", "--format=%H", "--", "data/site.json"])
    skip_hashes = {line.strip() for line in output.splitlines() if line.strip()}
    log.event(
        "GIT_READ",
        "foundation_commits",
        "changelog.foundation_commits",
        "ok" if skip_hashes else "skip",
        "T-CHANGELOG-003",
        commits=len(skip_hashes),
    )
    return skip_hashes


# PURPOSE: Собрать записи лога из сообщений коммитов, менявших data/, отсеяв служебные и коммит-основание.
# INPUTS:
#   нет; читает git log по data/ в формате «хеш, дата, тема».
# OUTPUTS:
#   list[dict] — элементы {"date": "ГГГГ-ММ-ДД", "text": тема коммита}; порядок git, новые сверху; [] без git.
# ERRORS: нет — строки без даты или темы пропускаются.
# KEYWORDS: [Git, Commit, Changelog, Filter, Merge, Wip]
# TESTS: [T-CHANGELOG-003]
def git_entries() -> list[dict]:
    output = run_git(
        ["log", "--date=short", "--pretty=format:%H%x09%ad%x09%s", "--", "data"]
    )
    if not output:
        log.event(
            "GIT_READ",
            "git_entries",
            "changelog.git_entries",
            "skip",
            "T-CHANGELOG-002",
            reason="git-unavailable",
        )
        return []

    skip_hashes = foundation_commits()

    entries = []
    for line in output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        commit, raw_date, subject = (part.strip() for part in parts)
        if not DATE_RE.match(raw_date) or not subject:
            continue
        if commit in skip_hashes:
            continue
        if subject.startswith(SKIP_PREFIXES):
            continue
        entries.append({"date": raw_date, "text": subject})

    log.event(
        "GIT_READ",
        "git_entries",
        "changelog.git_entries",
        "ok",
        "T-CHANGELOG-003",
        entries=len(entries),
    )
    return entries
# END_BLOCK_GIT_READ


# START_BLOCK_MERGE_LOG: Слияние записей git с курируемым логом, сортировка и запись файла. #KEYWORDS: Merge,Changelog,Dedup,Sort,Limit
# PURPOSE: Дополнить data/changelog.json записями git, сохранив сортировку и лимит, чтобы лог вёлся без ручной правки.
# INPUTS:
#   нет; читает data/changelog.json и результат git_entries().
# OUTPUTS:
#   int — 0; в stdout одна строка об добавлении или об отсутствии изменений.
# ERRORS: нет — отсутствующий файл лога и недоступный git дают успешный пропуск.
# SIDE EFFECTS: перезапись data/changelog.json при появлении новых записей.
# KEYWORDS: [Changelog, Merge, Dedup, Sort, Limit, Json]
# TESTS: [T-CHANGELOG-004, T-CHANGELOG-005, T-CHANGELOG-006]
def main() -> int:
    if not CHANGELOG.is_file():
        log.event(
            "MERGE_LOG",
            "main",
            "changelog.main",
            "skip",
            "T-CHANGELOG-004",
            reason="no-changelog-file",
        )
        print("Лог: нет data/changelog.json — пропуск", file=sys.stderr)
        return 0

    data = json.loads(CHANGELOG.read_text(encoding="utf-8"))
    existing = data.get("entries", [])
    seen = {(entry.get("date"), normalize(entry.get("text", ""))) for entry in existing}

    added = 0
    for entry in git_entries():
        key = (entry["date"], normalize(entry["text"]))
        if key in seen:
            continue
        existing.append(entry)
        seen.add(key)
        added += 1

    if not added:
        log.event(
            "MERGE_LOG",
            "main",
            "changelog.main",
            "skip",
            "T-CHANGELOG-005",
            added=0,
            total=len(existing),
        )
        print(f"Лог: без изменений ({len(existing)} записей)")
        return 0

    existing.sort(key=lambda item: (item.get("date", ""), item.get("text", "")), reverse=True)
    data["entries"] = existing[:100]
    CHANGELOG.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    log.event(
        "MERGE_LOG",
        "main",
        "changelog.main",
        "ok",
        "T-CHANGELOG-006",
        added=added,
        total=len(data["entries"]),
    )
    print(f"Лог: добавлено {added} записей, всего {len(data['entries'])}")
    return 0
# END_BLOCK_MERGE_LOG


if __name__ == "__main__":
    raise SystemExit(main())
