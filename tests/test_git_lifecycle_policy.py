"""Guard the mandatory branch -> PR -> integration-owner workflow."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GIT_SKILL = REPO_ROOT / ".agents" / "skills" / "git-lifecycle" / "SKILL.md"


def test_git_lifecycle_requires_pr_and_separate_integration_owner():
    text = GIT_SKILL.read_text(encoding="utf-8")

    assert "Every task branch intended to reach `main` must go through a pull request." in text
    assert "The authoring/working agent owns implementation through validation, commit, push, and PR creation." in text
    assert "A separate integration owner/coordinating agent owns PR review and merge" in text
    assert "The authoring agent must not merge its own PR as normal workflow." in text
    assert "Do not integrate normal task work by directly merging or pushing a task branch to `main`" in text
    assert "A pull request is optional" not in text
