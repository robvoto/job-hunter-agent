"""Guard the review-first, PR-last Git lifecycle contract."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GIT_SKILL = REPO_ROOT / ".agents" / "skills" / "git-lifecycle" / "SKILL.md"


def test_git_lifecycle_keeps_pr_as_final_integration_handoff():
    text = GIT_SKILL.read_text(encoding="utf-8")

    assert "Commits come before PRs" in text
    assert "A PR is the final integration handoff" in text
    assert "Do not create a PR while implementation, UI checking, code review, or user acceptance is still in progress." in text
    assert "When the human explicitly says the work is ready to merge" in text
    assert "The integration owner takes over once the PR exists." in text
    assert "The authoring agent does not normally merge its own PR." in text
    assert "Do not directly merge or push a normal task branch to `main`." in text
