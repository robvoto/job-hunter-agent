from job_hunter_agent.profile_item_names import canonical_profile_item_name


def test_accepts_atomic_canonical_profile_names():
    assert canonical_profile_item_name("NV2") == "NV2"
    assert canonical_profile_item_name("Australian Citizenship") == "Australian Citizenship"
    assert canonical_profile_item_name("CBAP") == "CBAP"
    assert canonical_profile_item_name("Java") == "Java"
    assert canonical_profile_item_name("Governance and Compliance Management") == "Governance and Compliance Management"


def test_rejects_requirement_prose_and_compound_alternatives():
    assert canonical_profile_item_name("NV2 Security Clearance Required") == ""
    assert canonical_profile_item_name("Australian Citizenship is Mandatory") == ""
    assert canonical_profile_item_name("CBAP, Agile BA, or equivalent certifications are desirable") == ""
    assert canonical_profile_item_name("CBAP or Agile BA") == ""
