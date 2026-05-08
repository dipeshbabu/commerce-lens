from __future__ import annotations

from commercelens.jobs.migrations import POSTGRES_MIGRATIONS, run_postgres_migrations


class FakeCursor:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict[str, str]]:
        return self.rows


class FakePostgresConnection:
    def __init__(self) -> None:
        self.applied: set[str] = set()
        self.statements: list[str] = []

    def execute(self, statement: str, params: tuple[str, str] | None = None) -> FakeCursor:
        self.statements.append(statement)
        if statement.startswith("SELECT id FROM commercelens_schema_migrations"):
            return FakeCursor([{"id": migration_id} for migration_id in sorted(self.applied)])
        if statement.strip().startswith("INSERT INTO commercelens_schema_migrations") and params:
            self.applied.add(params[0])
        return FakeCursor([])


def test_postgres_migrations_have_stable_unique_ids() -> None:
    ids = [migration.id for migration in POSTGRES_MIGRATIONS]

    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    assert "0001_hosted_core" in ids


def test_run_postgres_migrations_is_idempotent() -> None:
    conn = FakePostgresConnection()

    first = run_postgres_migrations(conn)
    second = run_postgres_migrations(conn)

    assert first == ["0001_hosted_core"]
    assert second == []
    assert "0001_hosted_core" in conn.applied
