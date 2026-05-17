import json
import hashlib
from html import escape
import re
import shutil
import threading
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

load_dotenv()

from job_hunter_agent.config import SERVER_HOST as HOST, SERVER_PORT as PORT, DEBUG_MODE, ALLOWED_DOC_REL_PATHS
from job_hunter_agent.user_settings import (
    DEFAULT_USER_SETTINGS,
    load_agent_state,
    KEY_WORKSPACE,
    KEY_TELEGRAM,
    KEY_SCHEDULE,
    KEY_LLM,
)
from job_hunter_agent.llm_gate import llm_suggest_rejection_blockers
from job_hunter_agent.notifiers.telegram_notifier import build_telegram_connect_link, send_telegram_notification, sync_telegram_subscribers
from job_hunter_agent.io_utils import load_job_history
from job_hunter_agent.config import AUTH_DISABLED
from job_hunter_agent.paths import (
    DATA_DIR,
    USERS_DIR,
    REPO_ROOT as ROOT_DIR,
    get_audit_records_path,
    get_job_history_path,
    get_review_data_path,
    get_run_stats_path,
    get_workspace_results_path,
    get_source_pack_dir,
)
from job_hunter_agent.profile_store import (
    BriefMode,
    DEFAULT_ONBOARDING_SETTINGS,
    DEFAULT_PROFILE,
    ENGAGEMENT_TYPE_OPTIONS,
    ENGAGEMENT_TYPE_DEFAULT_VALUES,
    GovPref,
    GOVERNMENT_PREFERENCE_CHOICE_OPTIONS,
    GOVERNMENT_PREFERENCE_OPTIONS,
    WorkMode,
    VALID_ENGAGEMENT_TYPES,
    WORK_MODE_PREFERENCE_NONE_LABEL,
    WORK_MODE_PREFERENCE_OPTIONS,
    build_candidate_profile_tiers_from_sections,
    load_profile,
    normalize_engagement_type_preferences,
    normalize_onboarding_settings,
    normalize_search_settings,
    normalize_work_mode_preferences,
    save_profile,
    KEY_KEYWORDS,
    KEY_LOCATIONS,
    KEY_ENGAGEMENT_TYPE,
    KEY_MIN_SALARY_YEARLY,
    KEY_MIN_DAILY_RATE,
    KEY_LOOKBACK_YEARS,
    KEY_MIN_MONTHS,
    KEY_MAX_TARGET,
    KEY_MAX_SECONDARY,
    KEY_CV_MAX_PAGES,
    KEY_BRIEF_MODE,
    KEY_BRIEF,
    KEY_STAR_EVIDENCE,
    KEY_FIT_GUIDANCE,
    KEY_CAP_GUIDANCE,
    KEY_CV_TEXT,
    KEY_EVIDENCE_TIERS,
    KEY_CAPABILITY_PROFILE_RULES,
    KEY_ONBOARDING_COMPLETE,
    KEY_ONBOARDING_SETTINGS,
    MATCHING_RULE_PROFILE_KEYS,
    patch_profile,
)
from job_hunter_agent.locations import resolve_location

from job_hunter_agent.workspace_refresh_service import rebuild_workspace_after_rule_change
from job_hunter_agent.workspace_rebuild_service import rebuild_workspace_results
from job_hunter_agent.source_connector import scrape_jobs_direct
from job_hunter_agent.source_documents import (
    DEFAULT_SOURCE_MATERIALS,
    build_llm_profile_brief,
    save_source_materials,
)
from job_hunter_agent.global_settings import (
    CAPABILITY_STRENGTH_PRESETS,
    KEY_LIMITS,
    KEY_CAPABILITY_ALIAS_LIMIT,
    KEY_DATE_RANGE_DAYS,
    KEY_LLM_SETTINGS,
    KEY_LINKEDIN_HOURS_OLD,
    KEY_LINKEDIN_RESULTS_PER_SEARCH,
    KEY_SEARCH_SETTINGS,
    KEY_MODEL_OPTIONS,
    KEY_SEEK_MAX_PAGES,
    KEY_SIGNAL_CLUSTER_MIN_ALIAS_HITS,
    KEY_SIGNAL_CLUSTER_MIN_SNIPPET_HITS,
    KEY_SIGNAL_CLUSTER_DENSE_SNIPPET_ALIAS_HITS,
    load_global_settings,
    get_salary_limits,
)
ONBOARDING_PAGE_COPY = {
    "steps": {
        "1": {
            "title": "Upload Your CV",
            "title_rebuild": "Upload Updated CV",
            "hero_title": "Build Your Job Profile",
            "hero_title_rebuild": "Refresh Your Profile",
            "hero_copy": "",
            "section_copy": "Start with the CV that best represents your real experience. We will use it to build your starting profile.",
        },
        "2": {
            "title": "Review Draft Profile",
            "hero_title": "Review Your Draft Profile",
            "hero_title_rebuild": "Review Refreshed Draft",
            "hero_copy": "",
            "section_copy": "Move titles between Primary and Secondary if needed before you continue.",
        },
        "3": {
            "title": "Set Search Basics",
            "hero_title": "Set Your Search Basics",
            "hero_copy": "",
            "section_copy": "Set the minimum information Job Hunter needs to search safely and score roles in the right direction.",
        },
        "4": {
            "title": "Check Your Setup",
            "hero_title": "Confirm Your Setup",
            "hero_title_rebuild": "Confirm Profile Refresh",
            "hero_copy": "",
            "section_copy": "Make sure this looks right. When you finish, onboarding is complete and Settings will unlock.",
        },
    },
}
_run_in_progress = False
_run_state_lock = threading.Lock()
_rejection_suggestions_cache: dict[str, dict[str, Any]] = {}


def get_docs() -> list[dict[str, str]]:
    """Return allowed markdown docs under the repo root (for /docs API)."""
    docs: list[dict[str, str]] = []
    root = ROOT_DIR.resolve()
    for rel_path in ALLOWED_DOC_REL_PATHS:
        file_path = (root / rel_path).resolve()
        if root not in file_path.parents and file_path != root:
            continue
        if file_path.is_file():
            docs.append({"name": rel_path, "content": file_path.read_text(encoding="utf-8")})
    return docs


def _set_run_in_progress(value: bool) -> None:
    global _run_in_progress
    with _run_state_lock:
        _run_in_progress = bool(value)


def _is_run_in_progress() -> bool:
    with _run_state_lock:
        return _run_in_progress



def _try_mark_run_started() -> bool:
    global _run_in_progress
    with _run_state_lock:
        if _run_in_progress:
            return False
        _run_in_progress = True
        return True


def _normalize_suggestion_phrase(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _parse_non_negative_salary_value(value: Any, *, label: str) -> int:
    try:
        parsed = int(str(value).replace(",", "").strip() or 0)
    except Exception as exc:
        raise ValueError(f"{label} must be a whole number.") from exc
    if parsed < 0:
        raise ValueError(f"{label} cannot be negative.")
    return parsed


def _enforce_salary_caps(value: int, *, label: str, limit_key: str) -> int:
    salary_limits = get_salary_limits()
    limit = salary_limits.get(limit_key, {}) if isinstance(salary_limits, dict) else {}
    try:
        maximum = int(limit.get("max", value))
    except Exception:
        maximum = value
    if value > maximum:
        raise ValueError(f"{label} cannot exceed {maximum:,}.")
    return value


def _render_template(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def build_bootstrap_script(
    *,
    csrf_token: str | None = None,
    location_options: list[dict[str, Any]] | None = None,
    default_location: str | None = None,
    onboarding_defaults: dict[str, Any] | None = None,
    onboarding_copy: dict[str, Any] | None = None,
    global_settings: dict[str, Any] | None = None,
    resume_step: int | None = None,
) -> str:
    parts = [f'<script>window.__JOB_HUNTER_DEBUG_MODE__ = {"true" if DEBUG_MODE else "false"};</script>']
    if onboarding_defaults is not None:
        parts.append(
            f'<script>window.__JOB_HUNTER_ONBOARDING_DEFAULTS__ = {json.dumps(onboarding_defaults, ensure_ascii=True)};</script>'
        )
    if onboarding_copy is not None:
        parts.append(
            f'<script>window.__JOB_HUNTER_ONBOARDING_COPY__ = {json.dumps(onboarding_copy, ensure_ascii=True)};</script>'
        )
    if resume_step is not None:
        parts.append(
            f'<script>window.__JOB_HUNTER_ONBOARDING_RESUME_STEP__ = {json.dumps(resume_step, ensure_ascii=True)};</script>'
        )
    if csrf_token is not None:
        parts.append(
            f'<script>window.__JOB_HUNTER_CSRF_TOKEN__ = {json.dumps(csrf_token, ensure_ascii=True)};</script>'
        )
    if location_options is not None:
        parts.append(
            f'<script>window.__JOB_HUNTER_LOCATION_OPTIONS__ = {json.dumps(location_options, ensure_ascii=True)};</script>'
        )
    if default_location is not None:
        parts.append(
            f'<script>window.__JOB_HUNTER_DEFAULT_LOCATION__ = {json.dumps(default_location, ensure_ascii=True)};</script>'
        )
    if global_settings is not None:
        parts.append(
            f'<script>window.__JOB_HUNTER_GLOBAL_SETTINGS__ = {json.dumps(global_settings, ensure_ascii=True)};</script>'
        )
    parts.append(
        f'<script>window.__JOB_HUNTER_SALARY_LIMITS__ = {json.dumps(get_salary_limits(), ensure_ascii=True)};</script>'
    )
    parts.append(
        f'<script>window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__ = {json.dumps(ENGAGEMENT_TYPE_OPTIONS, ensure_ascii=True)};</script>'
    )
    parts.append(
        f'<script>window.__JOB_HUNTER_ENGAGEMENT_TYPE_DEFAULT_VALUES__ = {json.dumps(ENGAGEMENT_TYPE_DEFAULT_VALUES, ensure_ascii=True)};</script>'
    )
    parts.append(
        f'<script>window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__ = {json.dumps(WORK_MODE_PREFERENCE_OPTIONS, ensure_ascii=True)};</script>'
    )
    parts.append(
        f'<script>window.__JOB_HUNTER_WORK_MODE_PREFERENCE_DEFAULT__ = {json.dumps(WorkMode.NONE, ensure_ascii=True)};</script>'
    )
    parts.append(
        f'<script>window.__JOB_HUNTER_WORK_MODE_PREFERENCE_NONE_LABEL__ = {json.dumps(WORK_MODE_PREFERENCE_NONE_LABEL, ensure_ascii=True)};</script>'
    )
    parts.append(
        f'<script>window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_OPTIONS__ = {json.dumps(GOVERNMENT_PREFERENCE_OPTIONS, ensure_ascii=True)};</script>'
    )
    parts.append(
        f'<script>window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_DEFAULT__ = {json.dumps(GovPref.ANY, ensure_ascii=True)};</script>'
    )
    return "\n  ".join(parts)


def _parse_locations_override(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[\r\n,]+", text) if part.strip()]


LOCATION_NAME_RE = re.compile(r"^[A-Za-z\s,'()-]+$")


def _normalize_choice_values(values: object) -> list[str]:
    if isinstance(values, str):
        source_values = [part.strip().lower() for part in re.split(r"[,\n|/]+", values) if part.strip()]
    elif isinstance(values, (list, tuple, set)):
        source_values = [str(value).strip().lower() for value in values if str(value).strip()]
    else:
        source_values = []
    selected: list[str] = []
    seen: set[str] = set()
    for value in source_values:
        if value and value not in seen:
            seen.add(value)
            selected.append(value)
    return selected


def render_choice_strip(*, name: str, options: list[dict[str, str]], selected_values: object, input_type: str, group_id: str, label_id: str, card_class: str) -> str:
    input_type = str(input_type or "radio").strip().lower()
    selected = _normalize_choice_values(selected_values)
    selected_set = set(selected)
    selected_value = selected[0] if selected else str(options[0]["value"] if options else "").strip().lower()
    if input_type == "radio" and not selected_value:
        selected_value = str(options[0]["value"] if options else "").strip().lower()
    rendered_options = []
    for item in options:
        value = str(item["value"]).strip().lower()
        checked = " checked" if (input_type == "radio" and value == selected_value) or (input_type != "radio" and value in selected_set) else ""
        rendered_options.append(
            f'<label class="choice-card {escape(card_class)}"><input type="{escape(input_type)}" name="{escape(name)}" value="{escape(value)}"{checked}><span>{escape(item["label"])}</span></label>'
        )
    role = "radiogroup" if input_type == "radio" else "group"
    return f'<div id="{escape(group_id)}" class="choice-strip" role="{role}" aria-labelledby="{escape(label_id)}">{"".join(rendered_options)}</div>'


def render_engagement_type_choices(*, name: str, selected_values: object) -> str:
    return render_choice_strip(
        name=name,
        options=list(ENGAGEMENT_TYPE_OPTIONS),
        selected_values=normalize_engagement_type_preferences(selected_values),
        input_type="checkbox",
        group_id="engagement_type_choices",
        label_id="engagement_type_label",
        card_class="choice-card--work-mode",
    )


def render_government_preference_select_options(*, selected_value: str) -> str:
    selected = str(selected_value or GovPref.ANY).strip().lower()
    options = []
    for item in GOVERNMENT_PREFERENCE_OPTIONS:
        selected_attr = " selected" if item["value"] == selected else ""
        options.append(
            f'<option value="{escape(item["value"])}"{selected_attr}>{escape(item["label"])}</option>'
        )
    return "".join(options)


def render_government_preference_choices(*, selected_values: object) -> str:
    valid_values = {item["value"] for item in GOVERNMENT_PREFERENCE_CHOICE_OPTIONS}
    selected = [value for value in _normalize_choice_values(selected_values) if value in valid_values]
    if not selected:
        selected = [item["value"] for item in GOVERNMENT_PREFERENCE_CHOICE_OPTIONS]
    return render_choice_strip(
        name="prefer_government",
        options=list(GOVERNMENT_PREFERENCE_CHOICE_OPTIONS),
        selected_values=selected,
        input_type="checkbox",
        group_id="prefer_government_choices",
        label_id="prefer_government_label",
        card_class="choice-card--work-mode",
    )


def render_work_mode_preference_choices(*, selected_values: object) -> str:
    return render_choice_strip(
        name="work_mode_preference",
        options=list(WORK_MODE_PREFERENCE_OPTIONS),
        selected_values=normalize_work_mode_preferences(selected_values),
        input_type="checkbox",
        group_id="work_mode_preference",
        label_id="work_mode_preference_label",
        card_class="choice-card--work-mode",
    )


def render_seek_max_pages_choices(*, selected_value: object | None = None, label_id: str = "seek_max_pages_label") -> str:
    global_settings = load_global_settings()
    search_settings = global_settings.get(KEY_SEARCH_SETTINGS, {}) if isinstance(global_settings, dict) else {}
    search_limits = global_settings.get(KEY_LIMITS, {}).get("search", {}) if isinstance(global_settings, dict) else {}
    bounds = search_limits.get(KEY_SEEK_MAX_PAGES, {})
    min_value = int(bounds.get("min", 1))
    max_value = int(bounds.get("max", 10))
    if min_value > max_value:
        raise ValueError("global_settings.limits.search.seek_max_pages.min must be <= max")
    options = [{"value": str(value), "label": str(value)} for value in range(min_value, max_value + 1)]
    selected = str(selected_value if selected_value is not None else search_settings.get(KEY_SEEK_MAX_PAGES, max_value)).strip()
    if selected not in {option["value"] for option in options}:
        raise ValueError(f"global_settings.search_settings.{KEY_SEEK_MAX_PAGES} must be between {min_value} and {max_value}")
    return render_choice_strip(
        name=KEY_SEEK_MAX_PAGES,
        options=options,
        selected_values=selected,
        input_type="radio",
        group_id="seek_max_pages_choices",
        label_id=label_id,
        card_class="choice-card--work-mode choice-card--seek-pages",
    )


def _normalize_onboarding_search_preferences(payload: dict | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    keywords = str(source.get(KEY_KEYWORDS) or "").strip()
    locations = _parse_locations_override(source.get(KEY_LOCATIONS))
    normalized = {
        KEY_KEYWORDS: keywords,
        KEY_LOCATIONS: locations,
        KEY_ENGAGEMENT_TYPE: normalize_engagement_type_preferences(source.get(KEY_ENGAGEMENT_TYPE), default_to_all=False),
    }
    if KEY_MIN_SALARY_YEARLY in source:
        normalized[KEY_MIN_SALARY_YEARLY] = source.get(KEY_MIN_SALARY_YEARLY)
    if KEY_MIN_DAILY_RATE in source:
        normalized[KEY_MIN_DAILY_RATE] = source.get(KEY_MIN_DAILY_RATE)
    return normalized


def _validate_required_onboarding_inputs(
    search_preferences: dict[str, Any],
    onboarding_settings_payload: dict | None,
) -> None:
    keywords = str(search_preferences.get(KEY_KEYWORDS) or "").strip()
    locations = _parse_locations_override(search_preferences.get(KEY_LOCATIONS))
    engagement_type = normalize_engagement_type_preferences(search_preferences.get(KEY_ENGAGEMENT_TYPE), default_to_all=False)

    if keywords and (len(keywords) < 2 or len(keywords) > 120):
        raise ValueError("Please keep the primary search title between 2 and 120 characters.")
    if len(locations) != 1:
        raise ValueError("Please choose one search location.")
    location = locations[0]
    if len(location) < 2 or len(location) > 80:
        raise ValueError("Location should be between 2 and 80 characters.")
    if not LOCATION_NAME_RE.match(location):
        raise ValueError("Location should look like a normal city, state, or region name.")
    resolve_location(location)
    if not engagement_type or any(value not in VALID_ENGAGEMENT_TYPES for value in engagement_type):
        raise ValueError("Please choose what type of work you are open to.")

    raw_yearly = search_preferences.get(KEY_MIN_SALARY_YEARLY)
    if raw_yearly not in (None, ""):
        yearly = _parse_non_negative_salary_value(raw_yearly, label="Minimum permanent salary")
        _enforce_salary_caps(yearly, label="Minimum permanent salary", limit_key=KEY_MIN_SALARY_YEARLY)

    raw_daily = search_preferences.get(KEY_MIN_DAILY_RATE)
    if raw_daily not in (None, ""):
        daily = _parse_non_negative_salary_value(raw_daily, label="Minimum contract daily rate")
        _enforce_salary_caps(daily, label="Minimum contract daily rate", limit_key=KEY_MIN_DAILY_RATE)

    raw_settings = onboarding_settings_payload if isinstance(onboarding_settings_payload, dict) else {}
    if isinstance(raw_settings.get(KEY_ONBOARDING_SETTINGS), dict):
        raw_settings = raw_settings.get(KEY_ONBOARDING_SETTINGS) or {}

    raw_lookback = raw_settings.get(KEY_LOOKBACK_YEARS)
    raw_min_months = raw_settings.get(KEY_MIN_MONTHS)
    if raw_lookback in (None, ""):
        raise ValueError("Please choose how far back we should look.")
    if raw_min_months in (None, ""):
        raise ValueError("Please choose when a role is too short to count as a main signal.")

    try:
        lookback = int(raw_lookback)
    except Exception as exc:
        raise ValueError("Lookback must be a whole number of years.") from exc
    try:
        min_months = int(raw_min_months)
    except Exception as exc:
        raise ValueError("Short-role threshold must be a whole number of months.") from exc

    if lookback < 1 or lookback > 20:
        raise ValueError("Please enter a lookback between 1 and 20 years.")
    if min_months < 1 or min_months > 24:
        raise ValueError("Please enter a short-role threshold between 1 and 24 months.")


def _read_last_run_timestamp() -> str | None:
    try:
        run_stats_path = get_run_stats_path()
        if run_stats_path.exists():
            payload = json.loads(run_stats_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                timestamp = str(
                    payload.get("last_run_attempt_at")
                    or payload.get("run_finished_at")
                    or payload.get("run_started_at")
                    or ""
                ).strip()
                if timestamp:
                    return timestamp
        state = load_agent_state()
        return str(state.get("last_agent_run_at") or "").strip() or None
    except Exception:
        return None


def _normalize_search_settings_payload(payload: dict | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    if isinstance(source.get("search_settings"), dict):
        source = source.get("search_settings") or {}

    overrides: dict[str, Any] = {}
    if KEY_KEYWORDS in source:
        value = str(source.get(KEY_KEYWORDS) or "").strip()
        if value:
            overrides[KEY_KEYWORDS] = value
    if KEY_LOCATIONS in source:
        parsed = _parse_locations_override(source.get(KEY_LOCATIONS))
        if parsed:
            overrides[KEY_LOCATIONS] = parsed
    if KEY_DATE_RANGE_DAYS in source:
        overrides[KEY_DATE_RANGE_DAYS] = source.get(KEY_DATE_RANGE_DAYS)
    if KEY_SEEK_MAX_PAGES in source:
        overrides[KEY_SEEK_MAX_PAGES] = source.get(KEY_SEEK_MAX_PAGES)
    if KEY_LINKEDIN_HOURS_OLD in source:
        overrides[KEY_LINKEDIN_HOURS_OLD] = source.get(KEY_LINKEDIN_HOURS_OLD)
    if KEY_LINKEDIN_RESULTS_PER_SEARCH in source:
        overrides[KEY_LINKEDIN_RESULTS_PER_SEARCH] = source.get(KEY_LINKEDIN_RESULTS_PER_SEARCH)

    if not overrides:
        return {}

    current_search_settings = normalize_search_settings(load_profile().get("search_settings", {}))
    current_search_settings.update(overrides)
    return normalize_search_settings(current_search_settings)


def _normalize_onboarding_settings_payload(payload: dict | None) -> dict[str, int]:
    allowed_keys = (
            KEY_CAPABILITY_ALIAS_LIMIT,
            KEY_LOOKBACK_YEARS,
            KEY_MIN_MONTHS,
            KEY_MAX_TARGET,
            KEY_MAX_SECONDARY,
            KEY_CV_MAX_PAGES,
            KEY_SIGNAL_CLUSTER_MIN_ALIAS_HITS,
            KEY_SIGNAL_CLUSTER_MIN_SNIPPET_HITS,
            KEY_SIGNAL_CLUSTER_DENSE_SNIPPET_ALIAS_HITS,
    )
    source = payload if isinstance(payload, dict) else {}
    if isinstance(source.get(KEY_ONBOARDING_SETTINGS), dict):
        source = source.get(KEY_ONBOARDING_SETTINGS) or {}

    if not source:
        current = load_profile().get(KEY_ONBOARDING_SETTINGS)
        if isinstance(current, dict) and current:
            source = current
        else:
            source = dict(DEFAULT_ONBOARDING_SETTINGS)

    normalized = normalize_onboarding_settings(source)
    return {key: int(normalized[key]) for key in allowed_keys if key in normalized}


def describe_capability_strength_preset(preset_name: str) -> dict[str, Any]:
    preset_key = str(preset_name or "").strip().lower()
    if preset_key not in CAPABILITY_STRENGTH_PRESETS:
        preset_key = str(DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]).strip().lower()
    return {
        "capability_strength_preset": preset_key,
        "values": dict(CAPABILITY_STRENGTH_PRESETS[preset_key]),
    }


def _onboarding_complete(profile: dict[str, Any] | None = None) -> bool:
    current = profile if isinstance(profile, dict) else load_profile()
    return bool(current.get(KEY_ONBOARDING_COMPLETE))


def _onboarding_resume_step(profile: dict[str, Any] | None = None) -> int:
    """Returns the wizard step to resume at (1 = upload, 2 = review draft)."""
    current = profile if isinstance(profile, dict) else load_profile()
    capability_rules = [r for r in current.get("capability_profile_rules", []) if r]
    if capability_rules:
        return 2
    return 1


def _write_run_stats_field(key: str, value: object) -> None:
    try:
        path = get_run_stats_path()
        payload: dict = {}
        if path.exists():
            import json as _json
            try:
                payload = _json.loads(path.read_text(encoding="utf-8")) or {}
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload[key] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as write_exc:
        print(f"[RUN][WARN] Could not write run_stats.{key}: {write_exc}")


def _run_scrape_job() -> None:
    try:
        scrape_jobs_direct()
        _write_run_stats_field("last_run_error", None)
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        print(f"[RUN][ERROR] {msg}")
        _write_run_stats_field("last_run_error", msg)
    finally:
        _set_run_in_progress(False)


def _rebuild_workspace_on_startup() -> None:
    if not get_workspace_results_path().exists() and not get_run_stats_path().exists() and not get_audit_records_path().exists():
        return
    if not AUTH_DISABLED:
        print("[WORKSPACE][INFO] Startup rebuild skipped: no request user context is available.")
        return
    try:
        rebuild_workspace_results(reason="server startup rebuild")
    except Exception as exc:
        print(f"[WORKSPACE][WARN] Could not rebuild on startup: {type(exc).__name__}: {exc}")


class SettingsHandler:
    @staticmethod
    def _patch_affects_matching_rules(patch: dict) -> bool:
        return any(key in (patch or {}) for key in MATCHING_RULE_PROFILE_KEYS)

    @staticmethod
    def _normalize_profile_patch_for_save(current: dict, patch: dict) -> dict:
        normalized = dict(patch or {})
        current = current or load_profile()
        brief_mode = str(
            normalized.get(KEY_BRIEF_MODE, current.get(KEY_BRIEF_MODE, BriefMode.AUTO))
            or BriefMode.AUTO
        ).strip().lower()
        if brief_mode != BriefMode.MANUAL:
            brief_mode = BriefMode.AUTO
        normalized[KEY_BRIEF_MODE] = brief_mode

        if brief_mode == BriefMode.MANUAL:
            normalized[KEY_BRIEF] = str(normalized.get(KEY_BRIEF) or "").strip()
        else:
            auto_brief = build_llm_profile_brief(
                capability_rules=normalized.get(
                    KEY_CAPABILITY_PROFILE_RULES,
                    current.get(KEY_CAPABILITY_PROFILE_RULES, []),
                ),
            )
            normalized[KEY_BRIEF] = auto_brief

        if KEY_STAR_EVIDENCE in normalized:
            normalized[KEY_STAR_EVIDENCE] = str(normalized.get(KEY_STAR_EVIDENCE) or "").strip()
        if KEY_FIT_GUIDANCE in normalized:
            normalized[KEY_FIT_GUIDANCE] = str(normalized.get(KEY_FIT_GUIDANCE) or "").strip()
        if KEY_CAP_GUIDANCE in normalized:
            normalized[KEY_CAP_GUIDANCE] = str(normalized.get(KEY_CAP_GUIDANCE) or "").strip()
        if KEY_CV_TEXT in normalized:
            new_cv = str(normalized.get(KEY_CV_TEXT) or "").strip()
            current_cv = str(current.get(KEY_CV_TEXT) or "").strip()
            cv_changed = new_cv != current_cv
            if cv_changed and KEY_EVIDENCE_TIERS not in normalized:
                inferred_tiers = build_candidate_profile_tiers_from_sections([{
                    "label": "Primary CV",
                    "text": new_cv,
                }])
                if any(inferred_tiers.values()):
                    normalized[KEY_EVIDENCE_TIERS] = inferred_tiers
        return normalized

    @classmethod
    def _reset_current_user_state(cls) -> dict[str, Any]:
        import traceback as _tb
        print("WARNING: _reset_current_user_state called — all user data will be wiped")
        _tb.print_stack()
        # Wipe every per-user data directory under data/users/
        if USERS_DIR.exists():
            for user_dir in USERS_DIR.iterdir():
                try:
                    if user_dir.is_dir():
                        shutil.rmtree(user_dir)
                    else:
                        user_dir.unlink(missing_ok=True)
                except Exception:
                    continue

        # Reset root-level fallback files (used when no user is authenticated)
        save_profile(DEFAULT_PROFILE)
        save_source_materials(DEFAULT_SOURCE_MATERIALS)

        source_pack_dir = get_source_pack_dir()
        if source_pack_dir.exists():
            shutil.rmtree(source_pack_dir)

        for path, empty_payload in [
            (get_job_history_path(), {}),
            (get_review_data_path(), {}),
            (get_run_stats_path(), {}),
            (get_audit_records_path(), []),
        ]:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(empty_payload), encoding="utf-8")
            except Exception:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

        for output_path in [get_workspace_results_path()]:
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass

        return {
            "ok": True,
            "message": "All user state reset. Shared learning was preserved.",
            "redirect_to": "/start?fresh=1",
        }

    @staticmethod
    def _reset_global_learning() -> dict[str, Any]:
        from job_hunter_agent.signal_registry import clear_signal_learning_state

        clear_signal_learning_state()
        return {
            "ok": True,
            "message": "Global learning reset. Shared learned signals were cleared.",
        }

    @staticmethod
    def _sanitize_user_settings_payload(payload: dict) -> dict:
        workspace = payload.get(KEY_WORKSPACE, {}) if isinstance(payload, dict) else {}
        telegram = payload.get(KEY_TELEGRAM, {}) if isinstance(payload, dict) else {}
        llm = payload.get(KEY_LLM, {}) if isinstance(payload, dict) else {}
        schedule_payload = payload.get(KEY_SCHEDULE) if isinstance(payload, dict) else None
        sanitized = {
            KEY_WORKSPACE: {
                "minimum_score": max(0, min(int(workspace.get("minimum_score", 55) or 55), 100)),
            },
            KEY_TELEGRAM: {
                "enabled": bool(telegram.get("enabled", False)),
                "bot_token": str(telegram.get("bot_token") or "").strip(),
                "bot_username": str(telegram.get("bot_username") or "").strip().lstrip("@"),
                "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
            },
        }
        model = str(llm.get("model") or "").strip()
        if "model" in llm or model:
            allowed_models = [
                str(value).strip()
                for value in (
                    load_global_settings()
                    .get(KEY_LLM_SETTINGS, {})
                    .get(KEY_MODEL_OPTIONS, [])
                )
                if str(value).strip()
            ]
            if not allowed_models:
                raise ValueError("No LLM models are configured in Admin.")
            if not model:
                raise ValueError("Please choose an LLM model.")
            if model not in allowed_models:
                raise ValueError("Please choose a model configured in Global Settings.")
            sanitized[KEY_LLM] = {
                "model": model,
            }
        if isinstance(schedule_payload, dict):
            daily_time_local = str(
                schedule_payload.get("daily_time_local")
                or DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["daily_time_local"]
            ).strip()
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", daily_time_local):
                raise ValueError("Schedule time must be in HH:MM 24-hour format.")
            try:
                loop_sleep_seconds = int(
                    schedule_payload.get(
                        "loop_sleep_seconds",
                        DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"],
                    )
                    or DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"]
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("Schedule polling interval must be a whole number of seconds.") from exc
            sanitized[KEY_SCHEDULE] = {
                "daily_time_local": daily_time_local,
                "loop_sleep_seconds": max(60, loop_sleep_seconds),
            }
        return sanitized

    @staticmethod
    def _public_user_settings_payload(settings: dict) -> dict:
        workspace = settings.get(KEY_WORKSPACE, {}) if isinstance(settings, dict) else {}
        telegram = settings.get(KEY_TELEGRAM, {}) if isinstance(settings, dict) else {}
        llm_settings = settings.get(KEY_LLM, {}) if isinstance(settings, dict) else {}
        schedule = settings.get(KEY_SCHEDULE, {}) if isinstance(settings, dict) else {}
        subscribers = telegram.get("subscribers", []) if isinstance(telegram, dict) else []
        return {
            KEY_WORKSPACE: {
                "minimum_score": max(0, min(int(workspace.get("minimum_score", DEFAULT_USER_SETTINGS[KEY_WORKSPACE]["minimum_score"]) or DEFAULT_USER_SETTINGS[KEY_WORKSPACE]["minimum_score"]), 100)),
            },
            KEY_SCHEDULE: {
                "daily_time_local": str(schedule.get("daily_time_local") or DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["daily_time_local"]).strip(),
                "loop_sleep_seconds": max(60, int(schedule.get("loop_sleep_seconds", DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"]) or DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"])),
            },
            KEY_TELEGRAM: {
                "enabled": bool(telegram.get("enabled", False)),
                "bot_token_present": bool(str(telegram.get("bot_token") or "").strip()),
                "bot_username": str(telegram.get("bot_username") or "").strip(),
                "chat_id_present": bool(str(telegram.get("chat_id") or "").strip()),
                "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
                "subscriber_count": len(subscribers),
                "subscribers": subscribers,
            },
            KEY_LLM: { # Use llm_settings here to avoid shadowing the imported KEY_LLM
                "model": str(llm_settings.get("model") or "").strip(),
            },
        }

    @staticmethod
    def _issue_rejection_suggestion_approval_tokens(job_id: str, suggestions: list[str]) -> dict[str, str]:
        normalized_job_id = normalize_job_key(job_id) or str(job_id or "").strip()
        tokens: dict[str, str] = {}
        for suggestion in suggestions:
            phrase = _normalize_suggestion_phrase(suggestion)
            if not phrase:
                continue
            token = hashlib.sha1(f"{normalized_job_id}|{phrase}".encode("utf-8")).hexdigest()[:16]
            tokens[phrase] = token
        return tokens

    @staticmethod
    def _validate_llm_suggestion_approvals(
        job_id: str,
        blockers: list[str],
        approved_suggestion_tokens: dict[str, str] | None = None,
    ) -> None:
        normalized_job_id = normalize_job_key(job_id) or str(job_id or "").strip()
        cached = _rejection_suggestions_cache.get(normalized_job_id)
        if not isinstance(cached, dict):
            return

        suggested_terms = {
            _normalize_suggestion_phrase(item)
            for item in (cached.get("suggestions") or [])
            if _normalize_suggestion_phrase(item)
        }
        if not suggested_terms:
            return

        provided = approved_suggestion_tokens if isinstance(approved_suggestion_tokens, dict) else {}
        expected_tokens = SettingsHandler._issue_rejection_suggestion_approval_tokens(
            normalized_job_id,
            list(suggested_terms),
        )
        for blocker in blockers:
            phrase = _normalize_suggestion_phrase(blocker)
            if not phrase or phrase not in suggested_terms:
                continue
            expected = expected_tokens.get(phrase, "")
            if not expected or str(provided.get(phrase) or "").strip() != expected:
                raise ValueError(f"Missing explicit approval for suggested blocker: {phrase}")
