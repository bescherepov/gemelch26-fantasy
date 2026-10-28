#!/usr/bin/env python3
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
CHANGELOG = ROOT / "data" / "changelog.json"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SKIP_PREFIXES = ("Merge ", "merge ", "Revert ", "revert ", "WIP", "wip")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().rstrip(".")).lower()


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


def foundation_commits() -> set[str]:
    """Коммиты, которые создали data/site.json (первичная публикация сайта)."""
    output = run_git(["log", "--diff-filter=A", "--format=%H", "--", "data/site.json"])
    return {line.strip() for line in output.splitlines() if line.strip()}


def git_entries() -> list[dict]:
    output = run_git(
        ["log", "--date=short", "--pretty=format:%H%x09%ad%x09%s", "--", "data"]
    )
    if not output:
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
    return entries


def main() -> int:
    if not CHANGELOG.is_file():
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
        print(f"Лог: без изменений ({len(existing)} записей)")
        return 0

    existing.sort(key=lambda item: (item.get("date", ""), item.get("text", "")), reverse=True)
    data["entries"] = existing[:100]
    CHANGELOG.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Лог: добавлено {added} записей, всего {len(data['entries'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
