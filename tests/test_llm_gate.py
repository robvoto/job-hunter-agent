"""Tests for llm gate."""

from job_hunter_agent import llm_gate


def test_build_capability_naming_guidance_uses_managed_defaults_only():
    prompt = llm_gate.build_capability_naming_guidance()

    assert "You are reviewing and labelling candidate professional capability clusters extracted from a CV." in prompt
    assert "Default capability naming guidance:" in prompt
    assert "Clusters:" in prompt
    assert "skip" not in prompt


def test_build_job_requirements_prompt_includes_work_type_guidance():
    prompt = llm_gate.build_job_requirements_prompt()

    assert "Permanent" in prompt
    assert "Contract" in prompt
    assert "Full Time Contract / FTC" in prompt
    assert "Temporary" in prompt
    assert "Unknown when the work type is unclear" in prompt
