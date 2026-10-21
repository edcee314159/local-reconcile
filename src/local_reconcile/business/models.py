from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from ..domain import RawTable, MappingSpec

@dataclass(frozen=True)
class Account:
    code: str
    label: str

@dataclass(frozen=True)
class Batch:
    id: str
    role: str
    account: str
    raw: RawTable
    mapping: MappingSpec
    due_col: int | None = None
    statement_period: str | None = None

@dataclass(frozen=True)
class Record:
    id: str
    batch_id: str
    source_id: str
    role: str
    account: str
    day: date
    amount_minor: int
    party: str
    reference: str
    summary: str
    due: date | None = None

@dataclass(frozen=True)
class Settings:
    window_days: int = 7
    max_parts: int = 5
    max_pool: int = 16
    max_candidates: int = 100
    project_budget: int = 200000
    anchor_budget: int = 10000

@dataclass(frozen=True)
class Event:
    seq: int
    kind: str
    data: dict

@dataclass
class State:
    period: str
    visible: set = field(default_factory=set)
    excluded: set = field(default_factory=set)
    matches: dict = field(default_factory=dict)
    rejected: set = field(default_factory=set)
    explanations: dict = field(default_factory=dict)
    allocations: dict = field(default_factory=dict)
    transfers: dict = field(default_factory=dict)
    refunds: dict = field(default_factory=dict)
    advances: dict = field(default_factory=dict)
    closing_balances: dict = field(default_factory=dict)
    unreconciled_classes: dict = field(default_factory=dict)
    balance_revisions: dict = field(default_factory=dict)
    credits: dict = field(default_factory=dict)
    duplicate_decisions: dict = field(default_factory=dict)
    partner_statements: dict = field(default_factory=dict)
    partner_decisions: dict = field(default_factory=dict)
    closings: dict = field(default_factory=dict)

@dataclass(frozen=True)
class Workspace:
    start_period: str
    accounts: tuple = ()
    batches: tuple = ()
    events: tuple = ()
    settings: Settings = field(default_factory=Settings)

    @cached_property
    def records(self):
        from .workspace import build_records
        return build_records(self)

    @cached_property
    def state(self):
        from .workspace import replay
        return replay(self)

@dataclass(frozen=True)
class Suggestion:
    id: str
    left: tuple
    right: tuple
    amount_minor: int
    basis: str
    conflicts: tuple = ()

@dataclass(frozen=True)
class LimitedRange:
    rows: tuple
    reason: str

@dataclass(frozen=True)
class Analysis:
    candidates: tuple
    ranges: tuple
