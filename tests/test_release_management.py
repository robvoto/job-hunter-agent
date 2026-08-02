from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import textwrap
import tomllib

import pytest
from starlette.requests import Request

from job_hunter_agent.routes import pages

REPO_ROOT = Path(__file__).resolve().parents[1]
INTEGRITY_SCRIPT = REPO_ROOT / "scripts" / "check-release-integrity.py"
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release-jobhunter.sh"
DEPLOY_RELEASE_SCRIPT = REPO_ROOT / "scripts" / "ec2" / "deploy-jobhunter-release.sh"
DEPLOY_LATEST_SCRIPT = REPO_ROOT / "scripts" / "ec2" / "deploy-jobhunter-latest.sh"
RELEASE_SKILL = REPO_ROOT / ".skills" / "release-management" / "SKILL.md"


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=cwd, check=check)


def _load_integrity_module():
    spec = importlib.util.spec_from_file_location("release_integrity", INTEGRITY_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_release_metadata(root: Path, *, project_version: str, lock_version: str) -> None:
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "job-hunter-agent"',
                f'version = "{project_version}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        "\n".join(
            [
                "version = 1",
                "revision = 3",
                "",
                "[[package]]",
                'name = "job-hunter-agent"',
                f'version = "{lock_version}"',
                'source = { virtual = "." }',
                "",
            ]
        ),
        encoding="utf-8",
    )


def _read_project_version(root: Path) -> str:
    payload = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def _write_runtime_release_files(root: Path) -> None:
    (root / "job_hunter_agent").mkdir(parents=True, exist_ok=True)
    (root / "job_hunter_agent" / "__init__.py").write_text("", encoding="utf-8")
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "ec2").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "run-e2e.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n",
        encoding="utf-8",
    )
    (root / "scripts" / "check-release-integrity.py").write_text(
        INTEGRITY_SCRIPT.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "scripts" / "release-jobhunter.sh").write_text(
        RELEASE_SCRIPT.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "scripts" / "ec2" / "deploy-jobhunter-release.sh").write_text(
        DEPLOY_RELEASE_SCRIPT.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "scripts" / "ec2" / "deploy-jobhunter-latest.sh").write_text(
        DEPLOY_LATEST_SCRIPT.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "job_hunter_agent" / "release_metadata.py").write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import tomllib
            from functools import lru_cache
            from pathlib import Path

            REPO_ROOT = Path(__file__).resolve().parents[1]


            @lru_cache(maxsize=1)
            def load_app_release_metadata() -> dict[str, str]:
                payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
                return {"version": str(payload["project"]["version"]).strip()}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    os.chmod(root / "scripts" / "run-e2e.sh", 0o755)
    os.chmod(root / "scripts" / "release-jobhunter.sh", 0o755)
    os.chmod(root / "scripts" / "ec2" / "deploy-jobhunter-release.sh", 0o755)
    os.chmod(root / "scripts" / "ec2" / "deploy-jobhunter-latest.sh", 0o755)


def _write_fake_tools(bin_dir: Path) -> None:
    fake_uv = textwrap.dedent(
        r"""
        #!/usr/bin/env python3
        from __future__ import annotations

        import os
        from pathlib import Path
        import re
        import subprocess
        import sys
        import tomllib

        root = Path.cwd()
        log_path = Path(os.environ.get("FAKE_TOOL_LOG", root / ".tool-log"))


        def log(message: str) -> None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")


        def read_version() -> str:
            payload = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
            return str(payload["project"]["version"]).strip()


        def bump_version(version: str, bump: str) -> str:
            major, minor, patch = [int(part) for part in version.split(".")]
            if bump == "patch":
                patch += 1
            elif bump == "minor":
                minor += 1
                patch = 0
            elif bump == "major":
                major += 1
                minor = 0
                patch = 0
            else:
                raise SystemExit(f"unsupported bump: {bump}")
            return f"{major}.{minor}.{patch}"


        def write_version(version: str) -> None:
            pyproject_path = root / "pyproject.toml"
            uv_lock_path = root / "uv.lock"
            pyproject_text = pyproject_path.read_text(encoding="utf-8")
            uv_lock_text = uv_lock_path.read_text(encoding="utf-8")
            pyproject_path.write_text(
                re.sub(r'version = "[0-9]+\.[0-9]+\.[0-9]+"', f'version = "{version}"', pyproject_text, count=1),
                encoding="utf-8",
            )
            uv_lock_path.write_text(
                re.sub(r'version = "[0-9]+\.[0-9]+\.[0-9]+"', f'version = "{version}"', uv_lock_text, count=1),
                encoding="utf-8",
            )


        def ensure_seed_files() -> None:
            data_dir = Path(os.environ["JOB_HUNTER_DATA_DIR"])
            (data_dir / "knowledge" / "occupation_taxonomy").mkdir(parents=True, exist_ok=True)
            (data_dir / "knowledge" / "locations_au.json").write_text("{}", encoding="utf-8")
            (data_dir / "knowledge" / "salary.json").write_text("{}", encoding="utf-8")
            (data_dir / "knowledge" / "occupation_taxonomy" / "onet_index.json").write_text(
                "{}",
                encoding="utf-8",
            )


        args = sys.argv[1:]
        if args == ["version", "--short"]:
            print(read_version())
            raise SystemExit(0)

        if len(args) >= 3 and args[0] == "version" and args[1] == "--bump":
            bump = args[2]
            next_version = bump_version(read_version(), bump)
            if "--dry-run" in args and "--short" in args:
                print(next_version)
                raise SystemExit(0)
            if "--no-sync" in args:
                write_version(next_version)
                raise SystemExit(0)

        if len(args) >= 2 and args[0] == "run" and args[1] == "pytest":
            log("uv run pytest")
            raise SystemExit(int(os.environ.get("FAKE_UV_PYTEST_EXIT", "0")))

        if args[:3] == ["run", "which", "python"]:
            print(sys.executable)
            raise SystemExit(0)

        if args[:2] == ["run", "playwright"]:
            log("uv run playwright")
            raise SystemExit(0)

        if args[:5] == ["run", "python", "-m", "job_hunter_agent.db_seed", "--upgrade"]:
            log("uv run python -m job_hunter_agent.db_seed --upgrade")
            ensure_seed_files()
            raise SystemExit(0)

        if args[:2] == ["run", "python"]:
            completed = subprocess.run([sys.executable, *args[2:]], check=False)
            raise SystemExit(completed.returncode)

        if args == ["sync", "--no-dev"]:
            log("uv sync --no-dev")
            raise SystemExit(0)

        raise SystemExit(f"fake uv does not support: {args}")
        """
    ).strip()
    (bin_dir / "uv").write_text(fake_uv + "\n", encoding="utf-8")
    os.chmod(bin_dir / "uv", 0o755)

    fake_sudo = textwrap.dedent(
        r"""
        #!/usr/bin/env bash
        set -euo pipefail
        echo "sudo $*" >> "${FAKE_TOOL_LOG:?}"
        if [[ $# -eq 0 ]]; then
          exit 0
        fi
        if [[ "$1" == "mkdir" ]]; then
          shift
          exec mkdir "$@"
        fi
        exit 0
        """
    ).strip()
    (bin_dir / "sudo").write_text(fake_sudo + "\n", encoding="utf-8")
    os.chmod(bin_dir / "sudo", 0o755)

    fake_curl = textwrap.dedent(
        r"""
        #!/usr/bin/env bash
        set -euo pipefail
        echo "HTTP/1.1 200 OK"
        echo "content-type: text/html"
        echo
        """
    ).strip()
    (bin_dir / "curl").write_text(fake_curl + "\n", encoding="utf-8")
    os.chmod(bin_dir / "curl", 0o755)


def _init_git_repo(tmp_path: Path, *, version: str = "1.5.1") -> Path:
    repo = tmp_path / "repo"
    origin = tmp_path / "origin.git"
    _run(["git", "init", "--bare", str(origin)], cwd=tmp_path)
    _run(["git", "init", "-b", "main", str(repo)], cwd=tmp_path)
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _write_release_metadata(repo, project_version=version, lock_version=version)
    _write_runtime_release_files(repo)
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Initial release state")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")
    return repo


def _tag_release(repo: Path, tag: str) -> str:
    _git(repo, "tag", "-a", tag, "-m", f"Release {tag}")
    _git(repo, "push", "origin", tag)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _ordinary_commit(repo: Path, message: str = "Ordinary commit after release") -> str:
    readme_path = repo / "README.md"
    readme_path.write_text(readme_path.read_text(encoding="utf-8") + message + "\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", message)
    _git(repo, "push", "origin", "main")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _repo_env(repo: Path, tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_fake_tools(bin_dir)
    env_file = tmp_path / "job-hunter.env"
    env_file.write_text("TEST_ENV=1\n", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_TOOL_LOG"] = str(tmp_path / "tool.log")
    env["JOB_HUNTER_DATA_DIR"] = str(tmp_path / "runtime-data")
    env["JOB_HUNTER_OUTPUT_DIR"] = str(tmp_path / "runtime-output")
    env["JOB_HUNTER_DB_PATH"] = str(tmp_path / "runtime-data" / "job_hunter.db")
    env["JOB_HUNTER_APP_DIR"] = str(repo)
    env["JOB_HUNTER_ENV_FILE"] = str(env_file)
    env["HOME"] = str(tmp_path / "home")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    return env


def test_current_repository_release_metadata_is_consistent():
    integrity = _load_integrity_module()

    version = integrity.check_release_integrity(REPO_ROOT)

    assert version == integrity._project_version(REPO_ROOT)


def test_release_integrity_rejects_lock_version_mismatch(tmp_path, monkeypatch):
    integrity = _load_integrity_module()
    _write_release_metadata(tmp_path, project_version="1.5.1", lock_version="1.5.0")
    monkeypatch.setattr(integrity, "_ui_version", lambda _root: "1.5.1")

    with pytest.raises(integrity.ReleaseIntegrityError, match="uv.lock does not match"):
        integrity.check_release_integrity(tmp_path)


def test_release_integrity_rejects_tag_version_mismatch(tmp_path, monkeypatch):
    integrity = _load_integrity_module()
    _write_release_metadata(tmp_path, project_version="1.5.1", lock_version="1.5.1")
    monkeypatch.setattr(integrity, "_ui_version", lambda _root: "1.5.1")

    with pytest.raises(integrity.ReleaseIntegrityError, match="does not match project version"):
        integrity.check_release_integrity(tmp_path, tag="v1.5.0")


def test_top_utility_bar_renders_version_from_release_metadata(monkeypatch):
    monkeypatch.setattr(pages.srv, "DEBUG_MODE", False)
    monkeypatch.setattr(pages.srv, "load_app_release_metadata", lambda: {"version": "9.8.7"})
    monkeypatch.setattr(pages, "read_session_user", lambda _request: None)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )

    html = pages._build_top_utility_bar_html(request)

    assert 'class="job-hunter-page-utility__release-version">v9.8.7</span>' in html


def test_ordinary_commits_after_release_tag_do_not_require_version_bump(tmp_path):
    repo = _init_git_repo(tmp_path)
    _tag_release(repo, "v1.5.1")
    ordinary_head = _ordinary_commit(repo)
    env = _repo_env(repo, tmp_path)

    result = _run(
        ["bash", "scripts/release-jobhunter.sh", "patch", "--dry-run"],
        cwd=repo,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert _read_project_version(repo) == "1.5.1"
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == ordinary_head
    assert "Planned release: v1.5.1 -> v1.5.2" in result.stdout


def test_release_creation_bumps_exactly_once(tmp_path):
    repo = _init_git_repo(tmp_path)
    _tag_release(repo, "v1.5.1")
    start_head = _ordinary_commit(repo)
    env = _repo_env(repo, tmp_path)

    result = _run(["bash", "scripts/release-jobhunter.sh", "patch"], cwd=repo, env=env, check=False)

    assert result.returncode == 0, result.stderr
    assert _read_project_version(repo) == "1.5.2"
    assert _git(repo, "rev-list", "--count", f"{start_head}..HEAD").stdout.strip() == "1"
    assert _git(repo, "log", "-1", "--pretty=%s").stdout.strip() == "Release v1.5.2"
    assert _git(repo, "describe", "--tags", "--exact-match").stdout.strip() == "v1.5.2"


def test_failed_release_push_removes_new_local_tag(tmp_path):
    repo = _init_git_repo(tmp_path)
    origin = tmp_path / "origin.git"
    _tag_release(repo, "v1.5.1")
    _ordinary_commit(repo)
    env = _repo_env(repo, tmp_path)

    hook_path = origin / "hooks" / "pre-receive"
    hook_path.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    os.chmod(hook_path, 0o755)

    result = _run(["bash", "scripts/release-jobhunter.sh", "patch"], cwd=repo, env=env, check=False)

    assert result.returncode != 0
    assert _git(repo, "tag", "--list", "v1.5.2").stdout.strip() == ""
    assert "removing local tag v1.5.2" in result.stderr


def test_deploy_rejects_missing_version_argument(tmp_path):
    repo = _init_git_repo(tmp_path)
    env = _repo_env(repo, tmp_path)

    result = _run(["bash", "scripts/ec2/deploy-jobhunter-release.sh"], cwd=repo, env=env, check=False)

    assert result.returncode != 0
    assert "Missing release tag" in result.stderr


def test_deploy_rejects_untagged_commit_argument(tmp_path):
    repo = _init_git_repo(tmp_path)
    _tag_release(repo, "v1.5.1")
    head_commit = _ordinary_commit(repo)
    env = _repo_env(repo, tmp_path)

    result = _run(
        ["bash", "scripts/ec2/deploy-jobhunter-release.sh", head_commit],
        cwd=repo,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "vMAJOR.MINOR.PATCH" in result.stderr


def test_latest_deploy_defaults_to_main_when_no_ref_is_provided(tmp_path):
    repo = _init_git_repo(tmp_path)
    _tag_release(repo, "v1.5.1")
    latest_main_commit = _ordinary_commit(repo, message="Later main commit")
    env = _repo_env(repo, tmp_path)

    result = _run(["bash", "scripts/ec2/deploy-jobhunter-latest.sh"], cwd=repo, env=env, check=False)

    assert result.returncode == 0, result.stderr
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == latest_main_commit
    assert "deploying ref:    main" in result.stdout
    assert "resolved source:  refs/remotes/origin/main" in result.stdout


def test_ref_deploy_rejects_release_tag_argument(tmp_path):
    repo = _init_git_repo(tmp_path)
    _tag_release(repo, "v1.5.1")
    env = _repo_env(repo, tmp_path)

    result = _run(
        ["bash", "scripts/ec2/deploy-jobhunter-latest.sh", "v1.5.1"],
        cwd=repo,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "production-only" in result.stderr


def test_deploy_checks_out_exact_tagged_commit_not_latest_main(tmp_path):
    repo = _init_git_repo(tmp_path)
    tagged_commit = _tag_release(repo, "v1.5.1")
    latest_main_commit = _ordinary_commit(repo, message="Later main commit")
    env = _repo_env(repo, tmp_path)

    result = _run(
        ["bash", "scripts/ec2/deploy-jobhunter-release.sh", "v1.5.1"],
        cwd=repo,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == tagged_commit
    assert tagged_commit != latest_main_commit
    assert "deploying tag:    v1.5.1" in result.stdout
    assert f"deploying commit: {tagged_commit}" in result.stdout


def test_ref_deploy_checks_out_latest_main_without_cutting_release(tmp_path):
    repo = _init_git_repo(tmp_path)
    _tag_release(repo, "v1.5.1")
    latest_main_commit = _ordinary_commit(repo, message="Later main commit")
    env = _repo_env(repo, tmp_path)

    result = _run(
        ["bash", "scripts/ec2/deploy-jobhunter-latest.sh", "main"],
        cwd=repo,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == latest_main_commit
    assert "deploying ref:    main" in result.stdout
    assert "resolved source:  refs/remotes/origin/main" in result.stdout
    assert _read_project_version(repo) == "1.5.1"


def test_ref_deploy_accepts_exact_commit_sha(tmp_path):
    repo = _init_git_repo(tmp_path)
    _tag_release(repo, "v1.5.1")
    latest_main_commit = _ordinary_commit(repo, message="Later main commit")
    env = _repo_env(repo, tmp_path)

    result = _run(
        ["bash", "scripts/ec2/deploy-jobhunter-latest.sh", latest_main_commit],
        cwd=repo,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == latest_main_commit
    assert f"deploying ref:    {latest_main_commit}" in result.stdout
    assert f"deploying commit: {latest_main_commit}" in result.stdout


def test_deploy_rejects_tag_version_mismatch(tmp_path):
    repo = _init_git_repo(tmp_path, version="1.5.1")
    _tag_release(repo, "v1.5.2")
    env = _repo_env(repo, tmp_path)

    result = _run(
        ["bash", "scripts/ec2/deploy-jobhunter-release.sh", "v1.5.2"],
        cwd=repo,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "does not match release tag v1.5.2" in result.stderr or "Expected version '1.5.2'" in result.stderr


def test_release_process_has_no_extra_release_modes():
    script = RELEASE_SCRIPT.read_text(encoding="utf-8")
    latest_script = DEPLOY_LATEST_SCRIPT.read_text(encoding="utf-8")
    skill = RELEASE_SKILL.read_text(encoding="utf-8")

    assert "patch|minor|major" in script
    assert "Choose patch, minor, or major." in script
    assert "deploy-jobhunter-release vX.Y.Z" in skill
    assert "deploy-jobhunter-latest\n" in skill
    assert "deploy-jobhunter-latest <branch-or-sha>" in skill
    assert "may legitimately contain unreleased commits after the latest release tag" in skill
    assert "separate schema/content versioning" in skill
    assert "staging/test/debug only" in skill
    assert "current release mode" not in script
    assert "fallback release mode" not in script
    assert "temporary release mode" not in script
    assert "one-time release mode" not in script
    assert "production-only" in latest_script


def test_release_command_owns_bump_tests_tag_and_atomic_push():
    script = RELEASE_SCRIPT.read_text(encoding="utf-8")
    deploy_release_script = DEPLOY_RELEASE_SCRIPT.read_text(encoding="utf-8")
    latest_script = DEPLOY_LATEST_SCRIPT.read_text(encoding="utf-8")

    assert 'uv version --bump "$bump" --no-sync' in script
    assert "uv run python scripts/check-release-integrity.py" in script
    assert "uv run pytest" in script
    assert "./scripts/run-e2e.sh -q" in script
    assert 'git tag -a "$release_tag" "$release_commit"' in script
    assert 'git push --atomic origin "$release_commit:refs/heads/main"' in script
    assert 'git tag -d "$release_tag"' in script
    assert "git status --porcelain --untracked-files=all" in script
    assert "assert_release_base_unchanged" in script
    assert "Local HEAD changed while release checks were running" in script
    assert "origin/main changed while release checks were running" in script
    assert "git pull --ff-only" not in deploy_release_script
    assert 'git fetch origin "$remote_tag_ref:$remote_tag_ref"' in deploy_release_script
    assert 'python3 scripts/check-release-integrity.py --expected-version "${RELEASE_TAG#v}" --tag "$RELEASE_TAG"' in deploy_release_script
    assert "deploy-jobhunter-latest" in latest_script
    assert "deploy-jobhunter-latest <branch-or-sha>" in latest_script
    assert 'DEFAULT_REF="${JOB_HUNTER_DEPLOY_DEFAULT_REF:-main}"' in latest_script
    assert "git fetch --prune origin" in latest_script
    assert "python3 scripts/check-release-integrity.py" in latest_script
    assert "--expected-version" not in latest_script
