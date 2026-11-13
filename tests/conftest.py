"""Shared test fixtures.

Tests must run offline and deterministically: the Supabase client is replaced
with a small fluent fake and LLM-backed agent runs are avoided (TestModel
overrides or stubbed `run` functions).
"""

import os
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

# Must be set before `voca.services.supabase_client` is imported anywhere.
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy-service-role-key")


@dataclass
class FakeResult:
    data: Any = None
    error: Any = None


@dataclass
class FakeAuth:
    token: str = "valid-token"
    user_id: str = "user-1"

    def get_user(self, token: str) -> SimpleNamespace:
        if token != self.token:
            raise ValueError("invalid token")
        return SimpleNamespace(user=SimpleNamespace(id=self.user_id))


@dataclass
class FakeSupabaseQuery:
    """Fluent builder mirroring the supabase-py calls `voca` makes."""

    client: FakeSupabase
    table: str
    operation: str = "select"
    filters: dict[str, Any] = field(default_factory=dict)
    payload: Any = None

    # --- builder methods (all return self, like the real client) ---
    def select(self, *_args: Any, **_kwargs: Any) -> FakeSupabaseQuery:
        self.operation = "select"
        return self

    def insert(self, values: Any, **_kwargs: Any) -> FakeSupabaseQuery:
        self.operation = "insert"
        self.payload = values
        rows = values if isinstance(values, list) else [values]
        self.client.inserted.setdefault(self.table, []).extend(rows)
        return self

    def upsert(self, values: Any, **_kwargs: Any) -> FakeSupabaseQuery:
        self.operation = "upsert"
        self.payload = values
        rows = values if isinstance(values, list) else [values]
        self.client.upserted.setdefault(self.table, []).extend(rows)
        return self

    def update(self, values: Any, **_kwargs: Any) -> FakeSupabaseQuery:
        self.operation = "update"
        self.payload = values
        return self

    def eq(self, column: str, value: Any) -> FakeSupabaseQuery:
        self.filters[column] = value
        return self

    def lt(self, _column: str, _value: Any) -> FakeSupabaseQuery:
        return self

    def or_(self, _expression: str) -> FakeSupabaseQuery:
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> FakeSupabaseQuery:
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> FakeSupabaseQuery:
        return self

    def single(self) -> FakeSupabaseQuery:
        self._single = True
        return self

    def maybe_single(self) -> FakeSupabaseQuery:
        self._single = True
        return self

    # --- terminal call ---
    def execute(self) -> FakeResult:
        key = (self.table, self.operation)
        if key in self.client.results:
            data = self.client.results[key]
        elif self.operation == "insert":
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            # Simulate the database fill-ins PostgREST returns for inserted rows.
            data = [{**row, "id": row.get("id", str(uuid4()))} for row in rows]
        else:
            data = []
        # `.single()`/`.maybe_single()` return the row itself, not a list.
        if getattr(self, "_single", False) and isinstance(data, list):
            data = data[0] if data else None
        # Record select filters after builder completion, so assertions can check
        # query scoping (e.g. the language filter on cards/sessions selects).
        if self.operation == "select":
            self.client.select_filters.setdefault(self.table, []).append(dict(self.filters))
        # Record update rows after builder completion, so filters applied after
        # `.update(...)` (e.g. `.eq("id", …)`) are captured.
        if self.operation == "update":
            self.client.updated.setdefault(self.table, []).append(
                {"values": self.payload, "filters": dict(self.filters)}
            )
        return FakeResult(data=data)


@dataclass
class FakeSupabase:
    """Fake `create_client(...)` result: `.table(...)` builder + `.auth`."""

    results: dict[tuple[str, str], Any] = field(default_factory=dict)
    inserted: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    upserted: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    updated: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    select_filters: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    auth: FakeAuth = field(default_factory=FakeAuth)

    def table(self, name: str) -> FakeSupabaseQuery:
        return FakeSupabaseQuery(client=self, table=name)

    def inserted_rows(self, table: str) -> list[dict[str, Any]]:
        return self.inserted.get(table, [])

    def upserted_rows(self, table: str) -> list[dict[str, Any]]:
        return self.upserted.get(table, [])

    def updated_rows(self, table: str) -> list[dict[str, Any]]:
        return self.updated.get(table, [])

    def select_filters_rows(self, table: str) -> list[dict[str, Any]]:
        return self.select_filters.get(table, [])


@pytest.fixture
def fake_supabase(monkeypatch):
    """Replace the Supabase client used inside `voca.main` with a fake."""
    from voca import main as voca_main

    client = FakeSupabase()
    monkeypatch.setattr(voca_main, "supabase", client)
    return client
