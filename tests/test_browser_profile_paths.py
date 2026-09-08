from job_hunter_agent.paths import (
    APSJOBS_PLAYWRIGHT_USER_DATA_DIR,
    SEEK_PLAYWRIGHT_USER_DATA_DIR,
)


def test_seek_and_apsjobs_use_separate_persistent_browser_profiles():
    assert SEEK_PLAYWRIGHT_USER_DATA_DIR != APSJOBS_PLAYWRIGHT_USER_DATA_DIR
    assert SEEK_PLAYWRIGHT_USER_DATA_DIR.name == "playwright_seek_user_data"
    assert APSJOBS_PLAYWRIGHT_USER_DATA_DIR.name == "playwright_apsjobs_user_data"
