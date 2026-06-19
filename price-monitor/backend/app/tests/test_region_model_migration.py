from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_region_migration() -> ModuleType:
    backend_dir = Path(__file__).resolve().parents[2]
    migration_path = (
        backend_dir / "alembic" / "versions" / "20260619_0017_add_region_model.py"
    )
    spec = importlib.util.spec_from_file_location(
        "region_model_migration",
        migration_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingBatchOp:
    def __init__(self, table_name: str, events: list[tuple]) -> None:
        self._table_name = table_name
        self._events = events

    def __enter__(self) -> _RecordingBatchOp:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def drop_constraint(self, name: str, *, type_: str) -> None:
        self._events.append(
            ("drop_constraint", self._table_name, name, type_),
        )

    def create_unique_constraint(self, name: str, columns: list[str]) -> None:
        self._events.append(
            ("create_unique_constraint", self._table_name, name, tuple(columns)),
        )


class _RecordingOp:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def add_column(self, *args: object, **kwargs: object) -> None:
        self.events.append(("add_column", args, kwargs))

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        **kwargs: object,
    ) -> None:
        self.events.append(("create_index", name, table_name, tuple(columns), kwargs))

    def batch_alter_table(self, table_name: str) -> _RecordingBatchOp:
        return _RecordingBatchOp(table_name, self.events)


def test_region_model_migration_creates_product_offers_fk_index_before_unique_swap(
    monkeypatch,
) -> None:
    migration = _load_region_migration()
    recording_op = _RecordingOp()

    monkeypatch.setattr(migration, "op", recording_op)
    monkeypatch.setattr(migration, "_backfill_region_codes", lambda: None)

    migration.upgrade()

    create_index_positions = [
        index
        for index, event in enumerate(recording_op.events)
        if event[:4]
        == (
            "create_index",
            "ix_product_offers_match_group_id",
            "product_offers",
            ("match_group_id",),
        )
    ]
    drop_unique_positions = [
        index
        for index, event in enumerate(recording_op.events)
        if event
        == (
            "drop_constraint",
            "product_offers",
            "uq_product_offers_identity",
            "unique",
        )
    ]

    assert drop_unique_positions
    assert create_index_positions
    assert create_index_positions[0] < drop_unique_positions[0]
