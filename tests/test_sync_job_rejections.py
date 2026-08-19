from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "sync-job-rejections"


def test_sync_job_rejections_uses_only_the_local_json_export():
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'IMPORT_PATH="$PWD/data/imports/candidate_application_history_export.json"' in script
    assert "import_candidate_rejections_from_json" in script
    assert 'main(["status"])' in script
    assert "global_settings" not in script
    assert "spreadsheet" not in script.lower()
    assert "import-from-sheet" not in script
