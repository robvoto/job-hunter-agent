from job_hunter_agent.profile_item_names import normalize_profile_item_name


def test_profile_item_name_normalization_is_shape_only():
    assert normalize_profile_item_name("  Australian   Citizenship  ") == "Australian Citizenship"
    assert normalize_profile_item_name("NV2 Security Clearance Required") == "NV2 Security Clearance Required"
    assert normalize_profile_item_name("CBAP or Agile BA") == "CBAP or Agile BA"


def test_profile_item_name_rejects_non_string_or_empty_shape():
    assert normalize_profile_item_name(None) == ""
    assert normalize_profile_item_name(123) == ""
    assert normalize_profile_item_name("   ") == ""
