from job_hunter_agent import llm_gate


def test_build_capability_naming_guidance_uses_managed_defaults_only():
    prompt = llm_gate.build_capability_naming_guidance()

    assert "You are reviewing and labelling candidate professional capability clusters extracted from a CV." in prompt
    assert "Default capability naming guidance:" in prompt
    assert "Clusters:" in prompt
