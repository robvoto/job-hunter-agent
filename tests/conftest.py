"""Shared pytest fixtures and test bootstrap."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent


if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


# Set up a shared test DB and seed knowledge before any production module is

# imported. Module-level knowledge loads (match_labels, profile_store, etc.)

# read from the DB at import time — mirroring production where the DB is

# always seeded before the app starts.

_test_db_dir = tempfile.mkdtemp(prefix="jh_test_")

_test_db_path = Path(_test_db_dir) / "test.db"

os.environ.setdefault("JOB_HUNTER_DB_PATH", str(_test_db_path))


from job_hunter_agent.database import init_db  # noqa: E402
from job_hunter_agent.global_settings import seed_global_settings_from_file  # noqa: E402
from job_hunter_agent.knowledge_store import seed_knowledge_from_dir  # noqa: E402

init_db(_test_db_path)

seed_knowledge_from_dir(ROOT_DIR / "data" / "knowledge", _test_db_path)

seed_knowledge_from_dir(ROOT_DIR / "data" / "signals", _test_db_path)

seed_global_settings_from_file(_test_db_path, overwrite=True)


@pytest.fixture(autouse=True)
def _set_test_user_context():

    from job_hunter_agent.user_context import set_user_id

    set_user_id("test_user")

    yield

    set_user_id(None)


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """Fresh DB seeded with all bundled knowledge, redirected via env var.



    Use this in tests that write knowledge so they don't pollute the shared

    session DB.

    """

    db = tmp_path / "isolated.db"

    from job_hunter_agent.database import init_db
    from job_hunter_agent.global_settings import seed_global_settings_from_file
    from job_hunter_agent.knowledge_store import seed_knowledge_from_dir

    init_db(db)

    seed_knowledge_from_dir(ROOT_DIR / "data" / "knowledge", db)

    seed_knowledge_from_dir(ROOT_DIR / "data" / "signals", db)

    seed_global_settings_from_file(db, overwrite=True)

    monkeypatch.setenv("JOB_HUNTER_DB_PATH", str(db))

    return db
