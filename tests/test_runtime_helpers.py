import os
from pathlib import Path

from job_hunter_agent.runtime_helpers import load_repo_dotenv


def test_load_repo_dotenv_loads_an_explicit_env_path(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=from-temp\nSAMPLE_VAR=hello\n", encoding="utf-8")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SAMPLE_VAR", raising=False)

    cwd = tmp_path / "nested" / "deeper"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)

    assert load_repo_dotenv(env_file) is True
    assert Path.cwd() == cwd
    assert os.environ["OPENAI_API_KEY"] == "from-temp"
    assert os.environ["SAMPLE_VAR"] == "hello"
