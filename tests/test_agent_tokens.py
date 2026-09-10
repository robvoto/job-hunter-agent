"""JH-305 external-agent token lifecycle tests."""

from __future__ import annotations

from job_hunter_agent import agent_token_store as tokens
from job_hunter_agent.database import db_conn


def test_token_plaintext_is_returned_once_and_only_hash_is_stored(isolated_db):
    created = tokens.create_agent_token(
        user_id="user-a", agent_id="chatgpt", label="ChatGPT", expires_at="2099-01-01T00:00:00Z"
    )
    assert created["token"].startswith(tokens.TOKEN_PREFIX)
    assert tokens.authenticate_agent_token(created["token"])["user_id"] == "user-a"
    assert all(item["token_id"] == created["token_id"] for item in tokens.list_agent_tokens("user-a"))
    with db_conn() as conn:
        row = conn.execute("SELECT token_hash FROM agent_tokens WHERE token_id = ?", (created["token_id"],)).fetchone()
        assert row["token_hash"] != created["token"]
        assert created["token"] not in row["token_hash"]


def test_token_revoke_and_user_scope(isolated_db):
    created = tokens.create_agent_token(user_id="user-a", agent_id="claude")
    assert tokens.authenticate_agent_token(created["token"])["agent_id"] == "claude"
    assert tokens.list_agent_tokens("user-b") == []
    assert tokens.revoke_agent_token("user-b", created["token_id"]) is False
    assert tokens.authenticate_agent_token(created["token"]) is not None
    assert tokens.revoke_agent_token("user-a", created["token_id"]) is True
    assert tokens.authenticate_agent_token(created["token"]) is None
