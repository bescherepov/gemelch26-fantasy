#!/usr/bin/env python3
# ==== MODULE CONTRACT: nuke-log ====
# PURPOSE:   Вести машиночитаемый журнал ключевых операций, чтобы траекторию сборки и проверок можно было сверять по логам, а не по пересказу.
# SCOPE:     JSON Lines, обязательные поля ts/level/module/block/op/ref/outcome/test, значимые величины операции; включение через NUKE_LOG.
# NON-GOALS: Не заменять человекочитаемые отчёты stdout/stderr, не писать в dist/, не хранить состояние между запусками.
# INVARIANTS:одна строка — один JSON-объект; выключенный журнал не меняет stdout, stderr и результат программы.
# DEPENDS:   нет.
# EXPOSES:   EventLogger, LogError, event
# ERRORS:    LogError — пустые обязательные поля или недоступный файл журнала.
# TESTS:     T-NUKE-001, T-NUKE-002, T-NUKE-003, T-NUKE-004, T-NUKE-005
# ==== END MODULE CONTRACT: nuke-log ====
"""Журнал операций в формате JSON Lines для Log Driven Development."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


# START_BLOCK_LOG_SINK: Выбор приёмника журнала по переменной окружения NUKE_LOG. #KEYWORDS: Sink,Env,Stderr,Disabled
# PURPOSE: Определить приёмник журнала по переменной окружения NUKE_LOG.
# INPUTS:
#   env: os.environ — NUKE_LOG: пусто или 0 — выключено, 1/stderr — stderr, иначе путь к файлу.
# OUTPUTS:
#   TextIO | Path | None — приёмник; None означает, что журнал выключен.
# ERRORS: LogError — NUKE_LOG задан путём, который нельзя открыть на запись.
# KEYWORDS: [Log, Sink, Environment, Jsonl, Stderr]
# TESTS: [T-NUKE-001, T-NUKE-002]
def _sink_from_env():
    raw = os.environ.get("NUKE_LOG", "").strip()
    if not raw or raw == "0":
        return None
    if raw in ("1", "stderr"):
        return sys.stderr
    return Path(raw)
# END_BLOCK_LOG_SINK


# START_BLOCK_LOG_EVENT: Формирование и запись одной JSONL-строки журнала. #KEYWORDS: Event,Jsonl,Schema,Outcome
# PURPOSE: Сообщить об ошибке журнала, не теряя причину сбоя.
# INPUTS:
#   message: str — причина нарушения контракта журнала; не пуста.
# OUTPUTS: нет; исключение наследует ValueError, чтобы ловиться как ошибка данных.
# ERRORS: LogError — пустые module/block/op/ref/outcome или недоступный приёмник.
# KEYWORDS: [Log, Error, Contract, Journal]
# TESTS: [T-NUKE-003, T-NUKE-005]
class LogError(ValueError):
    """Нарушение контракта журнала: пустые поля или недоступный приёмник."""


# PURPOSE: Писать события одного модуля в JSON Lines, не влияя на поведение при выключенном журнале.
# INPUTS:
#   module: str — идентификатор узла графа (например, build); не пустой.
#   sink: TextIO | Path | None — приёмник; None — журнал выключен; по умолчанию берётся из NUKE_LOG.
# OUTPUTS: нет; каждая операция добавляет одну строку.
# ERRORS: LogError — пустой module или недоступный файл журнала.
# SIDE EFFECTS: запись в stderr либо в файл, указанный NUKE_LOG.
# KEYWORDS: [Log, Jsonl, Event, Trace, Observability]
# TESTS: [T-NUKE-001, T-NUKE-002, T-NUKE-003]
class EventLogger:
    """Журнал событий модуля: пишет только когда включён."""

    def __init__(self, module, sink=None):
        if not isinstance(module, str) or not module.strip():
            raise LogError("журнал: пустой module")
        self.module = module.strip()
        self._sink = _sink_from_env() if sink is None else sink

    @property
    def enabled(self):
        return self._sink is not None

    # PURPOSE: Записать одно событие операции, чтобы по журналу восстановить её исход.
    # INPUTS:
    #   block: str — ID якоря блока; op: str — символ/операция; ref: str — module.symbol.
    #   outcome: str — ok | error | skip; test: str — ID теста или пусто в рантайме.
    # OUTPUTS: нет (побочный эффект — JSONL-строка).
    # ERRORS: LogError — пустое обязательное поле.
    # KEYWORDS: [Event, Outcome, Block, Ref, Jsonl]
    # TESTS: [T-NUKE-001, T-NUKE-002, T-NUKE-004]
    def event(self, block, op, ref, outcome, test="", level="INFO", **fields):
        if not self.enabled:
            return
        for name, value in (("block", block), ("op", op), ("ref", ref), ("outcome", outcome)):
            if not isinstance(value, str) or not value.strip():
                raise LogError(f"журнал: пустое поле {name}")
        record = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": level,
            "module": self.module,
            "block": block,
            "op": op,
            "ref": ref,
            "outcome": outcome,
            "test": test,
        }
        for key, value in fields.items():
            record[key] = value
        self._write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")

    # PURPOSE: Отправить готовую строку в приёмник журнала, не смешивая её с отчётами программы.
    # INPUTS:
    #   line: str — одна строка JSON; дописывается целиком.
    # OUTPUTS: нет.
    # ERRORS: LogError — файл журнала нельзя открыть или записать.
    # SIDE EFFECTS: запись в stderr или файл.
    # KEYWORDS: [Write, Sink, File, Stderr]
    # TESTS: [T-NUKE-003, T-NUKE-005]
    def _write(self, line):
        sink = self._sink
        try:
            if isinstance(sink, Path):
                with sink.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line)
            else:
                sink.write(line)
                sink.flush()
        except OSError as exc:
            raise LogError(f"журнал: не удалось записать {sink}: {exc}") from exc
# END_BLOCK_LOG_EVENT


# PURPOSE: Записать событие, не заводя долгоживущий объект журнала в точке вызова.
# INPUTS:
#   module/block/op/ref/outcome/test — те же, что у EventLogger.event.
# OUTPUTS: нет; при выключенном журнале — ничего.
# ERRORS: LogError — пустые обязательные поля или недоступный приёмник.
# KEYWORDS: [Log, Event, Helper, Jsonl]
# TESTS: [T-NUKE-001, T-NUKE-005]
def event(module, block, op, ref, outcome, test="", **fields):
    EventLogger(module).event(block, op, ref, outcome, test=test, **fields)
