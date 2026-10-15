"""Immutable contracts shared by import, matching, review and export."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Literal
from concurrent.futures import CancelledError

SourceRole = Literal["bank", "ledger"]
RowId = str
Progress = Callable[[str, int, int], None]
Cancelled = Callable[[], bool]

class LocalReconcileError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)

def check_cancel(cancelled: Cancelled) -> None:
    if cancelled():
        raise CancelledError()

def quiet_progress(stage: str, current: int, total: int) -> None:
    pass

def never_cancel() -> bool:
    return False

@dataclass(frozen=True, slots=True)
class RawCell:
    value: str | int | float | bool | date | datetime | None = None
    kind: str = "text"
    cached_value: str | int | float | bool | date | datetime | None = None

@dataclass(frozen=True, slots=True)
class RawRow:
    id: RowId
    source_line: int
    cells: tuple[RawCell, ...]

@dataclass(frozen=True, slots=True)
class RawTable:
    role: SourceRole
    filename: str
    sha256: str
    sheet: str | None
    header_row: int
    excel_epoch: date | None
    headers: tuple[str, ...]
    rows: tuple[RawRow, ...]

@dataclass(frozen=True, slots=True)
class MappingSpec:
    date_col: int = 0
    amount_col: int | None = 1
    income_col: int | None = None
    expense_col: int | None = None
    summary_col: int | None = None
    party_col: int | None = None
    reference_col: int | None = None
    account_col: int | None = None
    currency_col: int | None = None
    date_format: str | None = None
    direction: str = "signed"
    declared_account: str = ""
    declared_currency: str = "CNY"
    confirmed: bool = False

@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    severity: str
    message: str
    row_ids: tuple[RowId, ...] = ()

@dataclass(frozen=True, slots=True)
class Transaction:
    id: RowId
    role: SourceRole
    day: date
    amount_minor: int
    party: str = ""
    reference: str = ""
    summary: str = ""
    account: str = ""
    currency: str = "CNY"

@dataclass(frozen=True, slots=True)
class Dataset:
    raw: RawTable
    mapping: MappingSpec
    transactions: tuple[Transaction, ...]
    issues: tuple[Issue, ...] = ()

@dataclass(frozen=True, slots=True)
class MatchConfig:
    date_tolerance_days: int = 0
    max_pairs_per_group: int = 100

@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    bank_id: RowId
    ledger_id: RowId
    rule: str
    conflicts: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class Difference:
    bank_id: RowId
    ledger_id: RowId
    delta_minor: int
    reason: str

@dataclass(frozen=True, slots=True)
class AmbiguityGroup:
    id: str
    bank_ids: tuple[RowId, ...]
    ledger_ids: tuple[RowId, ...]
    truncated: bool
    reason: str

@dataclass(frozen=True, slots=True)
class MatchResult:
    rule_version: str = "1"
    candidates: tuple[Candidate, ...] = ()
    differences: tuple[Difference, ...] = ()
    groups: tuple[AmbiguityGroup, ...] = ()
    issues: tuple[Issue, ...] = ()

@dataclass(frozen=True, slots=True)
class ConfirmedPair:
    id: str
    bank_id: RowId
    ledger_id: RowId
    basis: str

@dataclass(frozen=True, slots=True)
class ReviewEvent:
    sequence: int
    kind: str
    bank_id: RowId
    ledger_id: RowId
    note: str = ""

@dataclass(frozen=True, slots=True)
class ReviewState:
    pairs: tuple[ConfirmedPair, ...] = ()
    rejected: tuple[tuple[RowId, RowId], ...] = ()
    events: tuple[ReviewEvent, ...] = ()

@dataclass(frozen=True, slots=True)
class ProjectSnapshot:
    schema_version: int
    bank: Dataset
    ledger: Dataset
    config: MatchConfig
    result: MatchResult
    review: ReviewState = field(default_factory=ReviewState)
