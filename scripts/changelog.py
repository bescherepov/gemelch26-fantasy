#!/usr/bin/env python3
"""Дополняет data/changelog.json записями из истории git по каталогу data/.

Идея: лог изменений не ведётся вручную. Всё, что меняло данные, попадает
в лог из сообщений коммитов. Курируемые записи (например, о старте партии)
сохраняются, если их ещё нет в истории.

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


def git_entries() -> list[dict]:
    command = [
        "git",
        "log",
        "--date=short",
        "--pretty=format:%ad%x09%s",
        "--",
        "data",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []

    entries = []
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        raw_date, subject = line.split("\t", 1)
        raw_date, subject = raw_date.strip(), subject.strip()
        if not DATE_RE.match(raw_date) or not subject:
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
