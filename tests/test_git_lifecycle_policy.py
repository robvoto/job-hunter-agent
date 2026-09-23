"""Guard the current app-test-before-PR Git lifecycle contract."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GIT_SKILL = REPO_ROOT / ".agents" / "skills" / "git-lifecycle" / "SKILL.md"


def test_git_lifecycle_keeps_pr_as_final_integration_handoff():
    text = GIT_SKILL.read_text(encoding="utf-8")

    assert (
        "task branch/worktree -> implement and self-check -> commit/push task branch "
        "-> fast-forward local `main` for Rob's app testing"
    ) in text
    assert (
        "Do not create the PR while implementation and Rob's app testing are still in progress."
    ) in text
    assert "Every normal integration to `origin/main` requires a PR" in text
    assert "The authoring agent cannot count its own review as the independent cross-check." in text
    assert "Rob's confirmation that the app change is good authorizes the PR" in text
    assert "Do not push a task branch directly to `origin/main`" in text
