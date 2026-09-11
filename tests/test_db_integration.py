"""Integration tests for the DB-backed service paths, against a REAL PostgreSQL.

WHY THIS FILE EXISTS. `src/auth.py`, `src/audit.py` and `src/api.py` were never
migrated from asyncpg to psycopg v3. They called `pool.acquire()`, `conn.fetch()`,
`conn.fetchval()`, `conn.fetchrow()` and `$1` placeholders -- none of which exist on
psycopg -- so every one of those paths raised
`AttributeError: 'AsyncConnectionPool' object has no attribute 'acquire'` at runtime.

⚠️ NOTHING in the project could see it. `compile` only parses. The import census in
test_import_census.py cannot reach inside a function body. `smoke` never installs the
project. And no test had ever opened a database connection, so the entire persistence
layer was unexercised. The bug survived a driver migration and months of CI.

WORSE, in one case it was SILENT: `AuditLogService.delete_logs_before` wraps its body
in `except Exception: return 0`, so the AttributeError was swallowed and audit-log
retention reported success while deleting nothing. That is why
`test_delete_logs_before_actually_deletes` asserts the COUNT and not merely that the
call did not raise -- a "did it throw?" check PASSES against the broken version.
Measured, against the original code: deleted=0 (want 3), remaining=4 (want 1).

These tests need a real PostgreSQL because the defect lives in the driver boundary; a
mock of the pool would have been written against whichever API the author believed in,
and would have agreed with the bug.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from src.audit import AuditLogService
from src.auth import AuthService
from src.mcp_postgres_db import MCPPostgresDB

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DOC = REPO_ROOT / "docs" / "database_schema.sql"

DSN = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://verify:verify@localhost:55432/ems_verify"
)


def _schema_sql() -> str:
    """Extract the DDL from docs/database_schema.sql.

    That file is Markdown with ```sql fences despite its .sql extension, so it
    cannot be fed to psql directly. We parse the fences and then assert a FLOOR on
    how many CREATE TABLE statements we found: if the document is ever reformatted,
    this fails loudly instead of silently creating an empty schema and letting every
    test below pass against nothing.
    """
    text = SCHEMA_DOC.read_text(encoding="utf-8")
    blocks = re.findall(r"```sql\n(.*?)```", text, flags=re.DOTALL)
    sql = "\n".join(blocks)
    found = len(re.findall(r"CREATE TABLE", sql, flags=re.IGNORECASE))
    assert found >= 10, (
        f"only {found} CREATE TABLE statements parsed from {SCHEMA_DOC.name}; "
        "the document format changed and this fixture is no longer building a schema"
    )
    return sql


def _db_available() -> bool:
    try:
        with psycopg.connect(DSN, connect_timeout=3):
            return True
    except Exception:
        return False


DB_UP = _db_available()


def test_database_is_reachable_in_ci():
    """A skipped integration suite is indistinguishable from a passing one.

    Locally the suite may skip (no database running). In CI it must NOT: the
    workflow provides a postgres service, so a skip there means the service died or
    TEST_DATABASE_URL is wrong, and the persistence layer would silently go
    unexercised again -- exactly how the original bug survived.
    """
    if os.environ.get("CI") == "true":
        assert DB_UP, f"CI must have a database; could not connect to {DSN}"
    else:
        pytest.skip("local run: database presence is optional")


pytestmark = pytest.mark.skipif(
    not DB_UP, reason=f"no PostgreSQL at {DSN} (set TEST_DATABASE_URL)"
)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def prepared_database():
    """Build the schema, tables before indexes.

    The fenced blocks appear in DOCUMENTATION order, not dependency order (an index
    on `users` is documented before the `users` table), so a single execute() aborts
    on the first forward reference. Run CREATE TABLE blocks first, then the rest.
    """
    sql = _schema_sql()
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    tables = [s for s in statements if re.search(r"CREATE TABLE", s, re.IGNORECASE)]
    rest = [s for s in statements if s not in tables]
    with psycopg.connect(DSN, autocommit=True) as conn:
        for stmt in tables + rest:
            try:
                conn.execute(stmt)
            except psycopg.errors.DuplicateTable:
                pass
            except psycopg.Error:
                # Indexes/constraints that reference objects this document does not
                # define are not needed by these tests; the CREATE TABLEs above are.
                pass
    with psycopg.connect(DSN) as conn:
        cur = conn.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'")
        built = cur.fetchone()[0]
    assert built >= 10, f"schema fixture only built {built} tables"
    return DSN


async def _make_db() -> tuple[MCPPostgresDB, AsyncConnectionPool]:
    pool = AsyncConnectionPool(
        DSN, min_size=1, max_size=2, open=False, kwargs={"row_factory": dict_row}
    )
    await pool.open(wait=True)
    db = MCPPostgresDB(
        pool, asyncio.get_running_loop(), concurrent.futures.ThreadPoolExecutor(1)
    )
    return db, pool


def _run(coro):
    return asyncio.run(coro)


def test_authenticate_api_key_executes(prepared_database):
    """src/auth.py:311 -- pool.acquire() + conn.fetch(). Raised AttributeError."""

    async def go():
        db, pool = await _make_db()
        try:
            return await AuthService(db).authenticate_api_key("no-such-key")
        finally:
            await pool.close()

    assert _run(go()) is None  # no such key, but it must REACH that conclusion


def test_initialize_roles_and_permissions_executes(prepared_database):
    """src/auth.py:464 -- pool.acquire() + transaction + fetch/fetchrow/fetchval."""

    async def go():
        db, pool = await _make_db()
        try:
            await AuthService(db).initialize_roles_and_permissions()
            async with pool.connection() as conn:
                cur = await conn.execute("SELECT COUNT(*) AS n FROM roles")
                return (await cur.fetchone())["n"]
        finally:
            await pool.close()

    assert _run(go()) > 0, "roles should have been seeded"


def test_delete_logs_before_actually_deletes(prepared_database):
    """src/audit.py:104 -- the SILENT one.

    Asserts the count, not the absence of an exception: the method swallows
    Exception and returns 0, so a 'did it raise?' test passes while broken.
    """

    async def go():
        db, pool = await _make_db()
        try:
            old = datetime.now(UTC) - timedelta(days=365)
            recent = datetime.now(UTC)
            async with pool.connection() as conn:
                await conn.execute("DELETE FROM audit_logs")
                for ts in (old, old, old, recent):
                    await conn.execute(
                        "INSERT INTO audit_logs (timestamp, actor_type, action_type,"
                        " resource_type, status)"
                        " VALUES (%s, 'test', 'test', 'test', 'ok')",
                        (ts,),
                    )
            cutoff = datetime.now(UTC) - timedelta(days=90)
            deleted = await AuditLogService(db).delete_logs_before(cutoff)
            async with pool.connection() as conn:
                cur = await conn.execute("SELECT COUNT(*) AS n FROM audit_logs")
                remaining = (await cur.fetchone())["n"]
            return deleted, remaining
        finally:
            await pool.close()

    deleted, remaining = _run(go())
    assert deleted == 3, f"expected 3 rows deleted, got {deleted}"
    assert remaining == 1, f"expected 1 recent row to survive, got {remaining}"
