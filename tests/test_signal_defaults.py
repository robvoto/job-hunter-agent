from job_hunter_agent import io_utils, signal_detection
from job_hunter_agent.profile_store import KEY_EVIDENCE_TIERS
from job_hunter_agent.signal_schema import (
    SIGNAL_FIT_LABEL_KEY,
    SIGNAL_NAME_KEY,
    SIGNAL_RISK_LABEL_KEY,
    SIGNAL_WATCHOUT_LABEL_KEY,
)


def test_signal_defaults_come_from_managed_knowledge():
    defaults = io_utils.load_signal_defaults()

    assert defaults == {
        "name": "domain specialist track",
        "fit_label": "specialist context",
        "watchout_label": "Role leans toward specialist depth",
        "risk_label": "Role leans toward specialist depth",
    }


def test_competitive_signal_detection_uses_managed_defaults():
    profile = {
        "dominant_signal_clusters": [
            {
                "name": "Platform engineering",
                "min_snippet_hits": 1,
            }
        ]
    }

    signals = signal_detection.detect_competitive_signals(
        "Platform engineering teams modernize delivery platforms.",
        profile,
    )

    assert signals == [
        {
            SIGNAL_NAME_KEY: "Platform engineering",
            SIGNAL_FIT_LABEL_KEY: "specialist context",
            SIGNAL_WATCHOUT_LABEL_KEY: "Role leans toward specialist depth",
            SIGNAL_RISK_LABEL_KEY: "Role leans toward specialist depth",
            "aliases": ["platform engineering"],
            "alias_hits": 1,
            "snippet_hits": 1,
            "dominance_level": 1,
        }
    ]


def test_competitive_signal_alignment_preserves_managed_labels():
    signal = {
        SIGNAL_NAME_KEY: "Platform engineering",
        SIGNAL_FIT_LABEL_KEY: "",
        SIGNAL_WATCHOUT_LABEL_KEY: "",
        SIGNAL_RISK_LABEL_KEY: "",
        "dominance_level": 1,
    }
    profile = {
        "capability_profile_rules": [
            {
                "name": "Platform engineering",
                "level": "strong",
                "aliases": ["platform engineering"],
            }
        ],
        KEY_EVIDENCE_TIERS: {},
        "star_evidence_text": "",
        "llm_profile_brief": "",
    }

    aligned = signal_detection.evaluate_competitive_signal_alignment(signal, profile)

    assert aligned[SIGNAL_NAME_KEY] == "Platform engineering"
    assert aligned[SIGNAL_FIT_LABEL_KEY] == "specialist context"
    assert aligned[SIGNAL_WATCHOUT_LABEL_KEY] == "Role leans toward specialist depth"
    assert aligned[SIGNAL_RISK_LABEL_KEY] == "Role leans toward specialist depth"
