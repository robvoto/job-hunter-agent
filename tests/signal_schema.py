# New constants
CATEGORY_SECTOR = "sector"
CATEGORY_SECTOR_PATTERN = "sector_pattern"

# Other existing constants (hypothetical, based on context)
CATEGORY_CAPABILITY_CONCEPT = "capability_concept"
CATEGORY_ROLE_TITLE_TOKEN = "role_title_token"
CATEGORY_ROLE_TITLE_PATTERN = "role_title_pattern"
CATEGORY_HARD_BLOCKER_PATTERN = "hard_blocker_pattern"
CATEGORY_TITLE_NORMALIZATION_CANDIDATE = "title_normalization_candidate"
CATEGORY_CV_FARMING_PATTERN = "cv_farming_pattern"
CATEGORY_PROFILE_SECTION_LABEL = "profile_section_label"

# All valid categories, including old ones for backward compatibility in data
VALID_SIGNAL_CATEGORIES = {
    CATEGORY_CAPABILITY_CONCEPT,
    CATEGORY_SECTOR,
    CATEGORY_SECTOR_PATTERN,
    CATEGORY_ROLE_TITLE_TOKEN,
    CATEGORY_ROLE_TITLE_PATTERN,
    CATEGORY_HARD_BLOCKER_PATTERN,
    CATEGORY_TITLE_NORMALIZATION_CANDIDATE,
    CATEGORY_CV_FARMING_PATTERN,
    CATEGORY_PROFILE_SECTION_LABEL,
}
