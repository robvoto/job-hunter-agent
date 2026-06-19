from __future__ import annotations

from pathlib import Path

import job_hunter_agent.knowledge_sync_roundtrip as _knowledge_sync_roundtrip
from job_hunter_agent.database import init_db
from job_hunter_agent.knowledge_store import get_knowledge, set_knowledge
from job_hunter_agent.knowledge_sync import sync_shared_knowledge


def test_sync_shared_knowledge_merges_capability_entries(tmp_path):
    left_db = tmp_path / "left.db"
    right_db = tmp_path / "right.db"
    init_db(left_db)
    init_db(right_db)

    set_knowledge(
        "capability_knowledge",
        {
            "kind": "managed_knowledge",
            "name": "capability_knowledge",
            "version": 1,
            "entries": [
                {"value": "BPMN 2.0", "aliases": ["Business Process Modelling"]},
            ],
        },
        left_db,
    )
    set_knowledge(
        "capability_knowledge",
        {
            "kind": "managed_knowledge",
            "name": "capability_knowledge",
            "version": 1,
            "entries": [
                {"value": "BPMN 2.0", "aliases": ["workflow mapping"]},
                {"value": "SQL", "aliases": ["sql querying"]},
            ],
        },
        right_db,
    )

    changed = sync_shared_knowledge(left_db, right_db, keys=("capability_knowledge",))

    assert changed == ["capability_knowledge"]
    expected = {
        "kind": "managed_knowledge",
        "name": "capability_knowledge",
        "version": 1,
        "entries": [
            {
                "value": "BPMN 2.0",
                "aliases": ["Business Process Modelling", "workflow mapping"],
            },
            {"value": "SQL", "aliases": ["sql querying"]},
        ],
    }
    assert get_knowledge("capability_knowledge", left_db)["entries"] == expected["entries"]
    assert get_knowledge("capability_knowledge", right_db)["entries"] == expected["entries"]


def test_sync_shared_knowledge_merges_job_type_and_parsing_rules(tmp_path):
    left_db = tmp_path / "left.db"
    right_db = tmp_path / "right.db"
    init_db(left_db)
    init_db(right_db)

    set_knowledge(
        "job_type",
        {
            "mapping": {"fulltime": "Full time"},
            "filter_groups": [
                {"label": "Permanent", "values": ["Permanent", "Full time"]},
            ],
            "work_type_inference": {
                "rules": [
                    {
                        "id": "rule_one",
                        "enabled": True,
                        "trigger_work_types": ["Full time"],
                        "no_signal_infers": "Permanent",
                        "contract_signal_infers": "Full Time Contract",
                        "contract_signal_keywords": ["fixed term"],
                    }
                ]
            },
        },
        left_db,
    )
    set_knowledge(
        "job_type",
        {
            "mapping": {"part-time": "Part time"},
            "filter_groups": [
                {"label": "Permanent", "values": ["Permanent", "Flexible"]},
                {"label": "Contract", "values": ["Contract"]},
            ],
            "work_type_inference": {
                "rules": [
                    {
                        "id": "rule_one",
                        "enabled": True,
                        "trigger_work_types": ["Permanent"],
                        "no_signal_infers": "Permanent",
                        "contract_signal_infers": "Full Time Contract",
                        "contract_signal_keywords": ["contract role"],
                    },
                    {
                        "id": "rule_two",
                        "enabled": True,
                        "trigger_work_types": ["Casual"],
                        "no_signal_infers": "Casual",
                        "contract_signal_infers": "Casual",
                        "contract_signal_keywords": ["casual role"],
                    },
                ]
            },
        },
        right_db,
    )

    set_knowledge(
        "parsing_rules",
        {
            "kind": "system_config",
            "name": "parsing_rules",
            "version": 13,
            "candidate_profile_section_routing": {
                "default_bucket": "primary_candidate_profile_context",
                "primary_labels": ["primary", "current"],
                "secondary_labels": ["supporting"],
                "supplementary_labels": ["background"],
            },
        },
        left_db,
    )
    set_knowledge(
        "parsing_rules",
        {
            "kind": "system_config",
            "name": "parsing_rules",
            "version": 13,
            "candidate_profile_section_routing": {
                "default_bucket": "secondary_candidate_profile_context",
                "primary_labels": ["main"],
                "secondary_labels": ["supporting", "legacy"],
                "supplementary_labels": ["education", "background"],
            },
        },
        right_db,
    )

    changed = sync_shared_knowledge(
        left_db,
        right_db,
        keys=("job_type", "parsing_rules"),
    )

    assert changed == ["job_type", "parsing_rules"]

    job_type = get_knowledge("job_type", left_db)
    assert job_type["mapping"] == {
        "fulltime": "Full time",
        "part-time": "Part time",
    }
    assert job_type["filter_groups"] == [
        {"label": "Permanent", "values": ["Permanent", "Full time", "Flexible"]},
        {"label": "Contract", "values": ["Contract"]},
    ]
    assert job_type["work_type_inference"]["rules"] == [
        {
            "id": "rule_one",
            "enabled": True,
            "trigger_work_types": ["Full time", "Permanent"],
            "no_signal_infers": "Permanent",
            "contract_signal_infers": "Full Time Contract",
            "contract_signal_keywords": ["fixed term", "contract role"],
        },
        {
            "id": "rule_two",
            "enabled": True,
            "trigger_work_types": ["Casual"],
            "no_signal_infers": "Casual",
            "contract_signal_infers": "Casual",
            "contract_signal_keywords": ["casual role"],
        },
    ]

    parsing_rules = get_knowledge("parsing_rules", right_db)
    routing = parsing_rules["candidate_profile_section_routing"]
    assert routing["default_bucket"] == "secondary_candidate_profile_context"
    assert routing["primary_labels"] == ["primary", "current", "main"]
    assert routing["secondary_labels"] == ["supporting", "legacy"]
    assert routing["supplementary_labels"] == ["background", "education"]


def test_sync_knowledge_roundtrip_builds_expected_commands(tmp_path, monkeypatch):
    local_db = tmp_path / "data" / "app.db"
    local_db.parent.mkdir(parents=True, exist_ok=True)
    local_db.write_bytes(b"sqlite")

    calls: list[list[str]] = []

    def fake_run(command, check):  # type: ignore[no-untyped-def]
        assert check is True
        calls.append(command)
        if command[0] == "scp" and command[-1].endswith(".syncing"):
            Path(command[-1]).write_bytes(b"sqlite")

    monkeypatch.setattr(_knowledge_sync_roundtrip.subprocess, "run", fake_run)

    result = _knowledge_sync_roundtrip.sync_knowledge_roundtrip(
        host="ec2-32-236-144-98.ap-southeast-2.compute.amazonaws.com",
        key="/tmp/KeyPair-JobHunter.pem",
        local_db=str(local_db),
        remote_db="/var/lib/job-hunter/data/job_hunter.db",
    )

    assert result == Path(local_db).resolve()
    assert calls == [
        [
            "scp",
            "-i",
            "/tmp/KeyPair-JobHunter.pem",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={Path.home() / '.ssh' / 'known_hosts'}",
            str(local_db.resolve()),
            "ubuntu@ec2-32-236-144-98.ap-southeast-2.compute.amazonaws.com:/tmp/desktop.db",
        ],
        [
            "ssh",
            "-i",
            "/tmp/KeyPair-JobHunter.pem",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={Path.home() / '.ssh' / 'known_hosts'}",
            "ubuntu@ec2-32-236-144-98.ap-southeast-2.compute.amazonaws.com",
            "cd /home/ubuntu/job-hunter-agent && uv run python -m job_hunter_agent.knowledge_sync --left-db /tmp/desktop.db --right-db /var/lib/job-hunter/data/job_hunter.db",
        ],
        [
            "scp",
            "-i",
            "/tmp/KeyPair-JobHunter.pem",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={Path.home() / '.ssh' / 'known_hosts'}",
            "ubuntu@ec2-32-236-144-98.ap-southeast-2.compute.amazonaws.com:/tmp/desktop.db",
            str(local_db.with_name("app.db.syncing").resolve()),
        ],
        [
            "ssh",
            "-i",
            "/tmp/KeyPair-JobHunter.pem",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={Path.home() / '.ssh' / 'known_hosts'}",
            "ubuntu@ec2-32-236-144-98.ap-southeast-2.compute.amazonaws.com",
            "rm -f /tmp/desktop.db",
        ],
    ]
    assert local_db.read_bytes() == b"sqlite"


def test_sync_knowledge_roundtrip_main_uses_defaults(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(_knowledge_sync_roundtrip, "DEFAULT_AWS_HOST", "example.aws")
    monkeypatch.setattr(_knowledge_sync_roundtrip, "DEFAULT_SSH_KEY", "/tmp/example.pem")
    monkeypatch.setattr(_knowledge_sync_roundtrip, "DEFAULT_LOCAL_DB", "/tmp/local.db")
    monkeypatch.setattr(_knowledge_sync_roundtrip, "DEFAULT_REMOTE_DB", "/tmp/remote.db")
    monkeypatch.setattr(_knowledge_sync_roundtrip, "DEFAULT_REMOTE_USER", "ubuntu")
    monkeypatch.setattr(_knowledge_sync_roundtrip, "DEFAULT_REMOTE_TMP", "/tmp/desktop.db")
    monkeypatch.setattr(_knowledge_sync_roundtrip, "DEFAULT_REMOTE_APP_DIR", "/home/ubuntu/job-hunter-agent")
    monkeypatch.setattr(
        _knowledge_sync_roundtrip,
        "sync_knowledge_roundtrip",
        lambda **kwargs: captured.update(kwargs) or Path("/tmp/local.db"),
    )

    assert _knowledge_sync_roundtrip.main([]) == 0
    assert captured == {
        "host": "example.aws",
        "key": "/tmp/example.pem",
        "local_db": "/tmp/local.db",
        "remote_db": "/tmp/remote.db",
        "remote_user": "ubuntu",
        "remote_tmp": "/tmp/desktop.db",
        "remote_app_dir": "/home/ubuntu/job-hunter-agent",
    }
