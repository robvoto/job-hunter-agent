from pathlib import Path
import sys
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@pytest.fixture(autouse=True)
def _set_test_user_context():
    from job_hunter_agent.user_context import set_user_id
    from job_hunter_agent.paths import LOCAL_USER_ID
    set_user_id(LOCAL_USER_ID)
    yield
    set_user_id(None)
