import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_settings import load_agent_settings, save_agent_settings
from config import OUTPUT_HTML
from filters import build_title_block_rule, extract_rejection_suggestions, normalize_title_block_phrase, passes_saved_rejection_rules, suggest_title_block_phrase
from notifiers.telegram_notifier import build_telegram_connect_link, send_telegram_notification, sync_telegram_subscribers
from profile_learning import build_learning_patch, merge_capability_rules, repair_text
from profile_store import DEFAULT_PROFILE, load_profile, patch_profile, save_profile
from profile_store import build_evidence_tiers_from_sections, get_evidence_tiers
from review_insights import apply_capability_tuning_decisions, build_suggested_tuning_from_saved_review
from llm_gate import extract_strengths_from_cv
from source_documents import (
    build_llm_profile_brief,
    import_source_materials_to_profile,
    load_source_materials,
    persist_uploaded_source_pack,
    run_onboarding,
    save_source_materials,
)


HOST = "127.0.0.1"
PORT = 8765
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
RUN_STATS_PATH = OUTPUT_DIR / "run_stats.json"
REVIEW_DATA_PATH = OUTPUT_DIR / "review_data.json"
JOB_HISTORY_PATH = DATA_DIR / "job_history.json"
SHOWCASE_PATH = ROOT_DIR / "docs" / "SHOWCASE.html"
DASHBOARD_PATH = ROOT_DIR / OUTPUT_HTML
REJECTION_RULES_PATH = OUTPUT_DIR / "rejection_rules.json"
ADMIN_HTML_PATH = ROOT_DIR / "templates" / "admin.html"
ONBOARDING_HTML_PATH = ROOT_DIR / "templates" / "onboarding.html"



class AdminHandler(BaseHTTPRequestHandler):
    @staticmethod
    def _combine_text_sections(*sections: str) -> str:
        cleaned: list[str] = []
        seen: set[str] = set()
        for section in sections:
            value = repair_text(str(section or ""))
            if not value:
                continue
            normalized = value.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(value)
        return "\n\n".join(cleaned).strip()

    @staticmethod
    def _merge_profile_learning_patch(current: dict, patch: dict, raw_text: str) -> dict:
        merged_patch = dict(patch or {})
        current = current or load_profile()

        imported_summary = str(merged_patch.get("candidate_summary") or "").strip()
        existing_summary = str(current.get("candidate_summary") or "").strip()
        default_summary = str(DEFAULT_PROFILE.get("candidate_summary") or "").strip()
        if imported_summary and existing_summary and existing_summary != default_summary:
            merged_patch.pop("candidate_summary", None)

        if merged_patch.get("strengths"):
            merged_patch["strengths"] = list(dict.fromkeys([
                *current.get("strengths", []),
                *merged_patch.get("strengths", []),
            ]))[:20]

        if merged_patch.get("capability_profile_rules"):
            merged_patch["capability_profile_rules"] = merge_capability_rules(
                merge_capability_rules(
                    DEFAULT_PROFILE.get("capability_profile_rules", []),
                    current.get("capability_profile_rules", []),
                ),
                merged_patch.get("capability_profile_rules", []),
            )


        merged_cv_text = AdminHandler._combine_text_sections(current.get("cv_text", ""), raw_text)
        if merged_cv_text:
            merged_patch["cv_text"] = merged_cv_text
            current_tiers = get_evidence_tiers(current)
            inferred_tiers = build_evidence_tiers_from_sections([{"label": "Admin Input", "text": raw_text}])
            merged_patch["evidence_tiers"] = {
                "primary_current_evidence": AdminHandler._combine_text_sections(
                    current_tiers.get("primary_current_evidence", ""),
                    inferred_tiers.get("primary_current_evidence", ""),
                ),
                "secondary_older_evidence": AdminHandler._combine_text_sections(
                    current_tiers.get("secondary_older_evidence", ""),
                    inferred_tiers.get("secondary_older_evidence", ""),
                ),
                "background_optional_evidence": AdminHandler._combine_text_sections(
                    current_tiers.get("background_optional_evidence", ""),
                    inferred_tiers.get("background_optional_evidence", ""),
                ),
            }

        final_strengths = merged_patch.get("strengths") or current.get("strengths", [])
        final_rules = merged_patch.get("capability_profile_rules") or current.get("capability_profile_rules", [])
        brief_mode = str(
            merged_patch.get("llm_profile_brief_mode", current.get("llm_profile_brief_mode", "auto")) or "auto"
        ).strip().lower()
        if brief_mode != "manual":
            llm_profile_brief = build_llm_profile_brief(
                strengths=final_strengths,
                capability_rules=final_rules,
            )
            if llm_profile_brief:
                merged_patch["llm_profile_brief"] = llm_profile_brief
            merged_patch["llm_profile_brief_mode"] = "auto"

        return merged_patch

    @staticmethod
    def _normalize_profile_patch_for_save(current: dict, patch: dict) -> dict:
        normalized = dict(patch or {})
        current = current or load_profile()
        brief_mode = str(
            normalized.get("llm_profile_brief_mode", current.get("llm_profile_brief_mode", "auto")) or "auto"
        ).strip().lower()
        if brief_mode != "manual":
            brief_mode = "auto"
        normalized["llm_profile_brief_mode"] = brief_mode

        if brief_mode == "manual":
            normalized["llm_profile_brief"] = str(normalized.get("llm_profile_brief") or "").strip()
        else:
            auto_brief = build_llm_profile_brief(
                strengths=normalized.get("strengths", current.get("strengths", [])),
                capability_rules=normalized.get(
                    "capability_profile_rules",
                    current.get("capability_profile_rules", []),
                ),
            )
            normalized["llm_profile_brief"] = auto_brief

        if "star_evidence_text" in normalized:
            normalized["star_evidence_text"] = str(normalized.get("star_evidence_text") or "").strip()
        if "cv_text" in normalized:
            new_cv = str(normalized.get("cv_text") or "").strip()
            if new_cv:
                extracted = extract_strengths_from_cv(new_cv)
                if extracted:
                    existing = current.get("strengths") or []
                    merged = list(dict.fromkeys([*existing, *extracted]))[:20]
                    normalized.setdefault("strengths", merged)
        if "cv_text" in normalized and "evidence_tiers" not in normalized:
            inferred_tiers = build_evidence_tiers_from_sections([{
                "label": "Primary CV",
                "text": str(normalized.get("cv_text") or "").strip(),
            }])
            if any(inferred_tiers.values()):
                normalized["evidence_tiers"] = inferred_tiers
        return normalized

    @staticmethod
    def _load_job_history() -> dict:
        if not JOB_HISTORY_PATH.exists():
            return {}
        try:
            payload = json.loads(JOB_HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {}

    @staticmethod
    def _save_job_history(history: dict) -> None:
        JOB_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        JOB_HISTORY_PATH.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _apply_learning_text(text: str) -> dict:
        cleaned = repair_text(text)
        if not cleaned:
            raise ValueError("No learning text provided")
        patch = build_learning_patch(cleaned)
        if not patch:
            raise ValueError("Could not extract structured learning from that text")
        current = load_profile()
        patch = AdminHandler._merge_profile_learning_patch(current, patch, cleaned)
        profile = patch_profile(patch)
        return {
            "ok": True,
            "message": "Learning update applied to profile.json.",
            "profile": profile,
        }

    @staticmethod
    def _sanitize_agent_settings_payload(payload: dict) -> dict:
        telegram = payload.get("telegram", {}) if isinstance(payload, dict) else {}
        llm = payload.get("llm", {}) if isinstance(payload, dict) else {}
        _allowed_models = {"gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o"}
        model = str(llm.get("model") or "").strip()
        return {
            "telegram": {
                "enabled": bool(telegram.get("enabled", False)),
                "bot_token": str(telegram.get("bot_token") or "").strip(),
                "bot_username": str(telegram.get("bot_username") or "").strip().lstrip("@"),
                "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
            },
            "llm": {
                "model": model if model in _allowed_models else "gpt-4.1-mini",
            },
        }

    @staticmethod
    def _public_agent_settings_payload(settings: dict) -> dict:
        telegram = settings.get("telegram", {}) if isinstance(settings, dict) else {}
        llm = settings.get("llm", {}) if isinstance(settings, dict) else {}
        subscribers = telegram.get("subscribers", []) if isinstance(telegram, dict) else []
        return {
            "telegram": {
                "enabled": bool(telegram.get("enabled", False)),
                "bot_token_present": bool(str(telegram.get("bot_token") or "").strip()),
                "bot_username": str(telegram.get("bot_username") or "").strip(),
                "chat_id_present": bool(str(telegram.get("chat_id") or "").strip()),
                "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
                "subscriber_count": len(subscribers) if isinstance(subscribers, list) else 0,
                "subscribers": subscribers if isinstance(subscribers, list) else [],
            },
            "llm": {
                "model": str(llm.get("model") or "gpt-4.1-mini").strip(),
            },
        }

    @staticmethod
    def _normalize_job_key(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        import re

        # Pass through pre-namespaced keys (e.g. 'linkedin:4056789012')
        if re.match(r"^(seek|linkedin|indeed|glassdoor):[^\s]+$", raw):
            return raw
        match = re.search(r"/job/(\d+)", raw)
        if match:
            return match.group(1)
        if re.fullmatch(r"\d+", raw):
            return raw
        return raw.split("#", 1)[0]

    @classmethod
    def _append_review_event(
        cls,
        entry: dict,
        action: str,
        job_key: str,
        occurred_at: str,
        title: str = "",
        company: str = "",
        url: str = "",
        teaser: str = "",
        extra: dict | None = None,
    ) -> None:
        snapshot = entry.get("last_kept_snapshot")
        if not isinstance(snapshot, dict):
            snapshot = {}

        event = {
            "action": action,
            "job_key": job_key,
            "timestamp": occurred_at,
        }
        resolved_title = title or entry.get("title") or snapshot.get("title") or ""
        resolved_company = company or entry.get("company") or snapshot.get("company") or ""
        resolved_url = url or entry.get("url") or snapshot.get("url") or ""
        resolved_teaser = teaser or snapshot.get("teaser") or entry.get("teaser") or ""

        if resolved_title:
            event["title"] = resolved_title
        if resolved_company:
            event["company"] = resolved_company
        if resolved_url:
            event["url"] = resolved_url
        if resolved_teaser:
            event["teaser"] = resolved_teaser

        if isinstance(extra, dict):
            for key, value in extra.items():
                if value in (None, "", [], {}):
                    continue
                event[key] = value

        events = entry.get("review_events")
        if not isinstance(events, list):
            events = []
        events.append(event)
        entry["review_events"] = events[-50:]

    @classmethod
    def _persist_review_event(
        cls,
        action: str,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
        extra: dict | None = None,
    ) -> None:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            return

        history = cls._load_job_history()
        entry = history.get(normalized, {})
        now_iso = datetime.now().astimezone().isoformat(timespec="seconds")

        entry["job_key"] = normalized
        if title:
            entry["title"] = title
        if company:
            entry["company"] = company
        if url:
            entry["url"] = url

        if action == "hidden":
            entry["is_hidden"] = True
            if not entry.get("first_hidden_at"):
                entry["first_hidden_at"] = now_iso
            entry["last_hidden_at"] = now_iso
        elif action == "unhide":
            entry["is_hidden"] = False
            entry["last_unhidden_at"] = now_iso
        elif action == "applied":
            if not entry.get("first_applied_at"):
                entry["first_applied_at"] = now_iso
            entry["last_applied_at"] = now_iso
        elif action == "not_for_me":
            entry["last_not_for_me_at"] = now_iso
            entry["times_not_for_me"] = int(entry.get("times_not_for_me", 0) or 0) + 1
        elif action in ("block_similar", "block_title"):
            entry["last_block_title_at"] = now_iso
            entry["times_block_title"] = int(entry.get("times_block_title", 0) or 0) + 1

        cls._append_review_event(
            entry,
            action,
            normalized,
            now_iso,
            title=title,
            company=company,
            url=url,
            teaser=teaser,
            extra=extra,
        )

        history[normalized] = entry
        cls._save_job_history(history)

    @classmethod
    def _append_review_key(
        cls,
        action: str,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
    ) -> dict:
        normalized = cls._normalize_job_key(job_key)
        if not normalized:
            raise ValueError("Missing job key")

        profile = load_profile()
        review_controls = profile.setdefault("review_controls", {})

        list_name = {
            "applied": "applied_job_keys",
            "hidden": "hidden_job_keys",
        }.get(action)
        if not list_name:
            raise ValueError("Unsupported review action")

        existing = [
            cls._normalize_job_key(value)
            for value in review_controls.get(list_name, [])
            if cls._normalize_job_key(value)
        ]
        if normalized not in existing:
            existing.append(normalized)
        review_controls[list_name] = existing
        save_profile(profile)
        cls._persist_review_event(
            action,
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
        )
        return {
            "ok": True,
            "action": action,
            "job_key": normalized,
            "saved_count": len(existing),
        }

    @classmethod
    def _remove_review_key(
        cls,
        action: str,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
    ) -> dict:
        normalized = cls._normalize_job_key(job_key)
        if not normalized:
            raise ValueError("Missing job key")

        profile = load_profile()
        review_controls = profile.setdefault("review_controls", {})

        list_name = {
            "unhide": "hidden_job_keys",
        }.get(action)
        if not list_name:
            raise ValueError("Unsupported review action")

        existing = [
            cls._normalize_job_key(value)
            for value in review_controls.get(list_name, [])
            if cls._normalize_job_key(value)
        ]
        updated = [value for value in existing if value != normalized]
        review_controls[list_name] = updated
        save_profile(profile)
        cls._persist_review_event(
            action,
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
        )
        return {
            "ok": True,
            "action": action,
            "job_key": normalized,
            "saved_count": len(updated),
        }


    # ------------------------------------------------------------------
    # Rejection-learning helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_rejection_rules() -> list:
        if not REJECTION_RULES_PATH.exists():
            return []
        try:
            data = json.loads(REJECTION_RULES_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @staticmethod
    def _save_rejection_rules_list(rules: list) -> None:
        REJECTION_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        REJECTION_RULES_PATH.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def _get_job_description(cls, job_id: str) -> str:
        """Return the full description text for a job_id, or empty string."""
        history = cls._load_job_history()
        for key in [job_id, f"linkedin:{job_id}"]:
            entry = history.get(key) if isinstance(history, dict) else None
            if not isinstance(entry, dict):
                continue
            snap = entry.get("last_kept_snapshot") or {}
            if isinstance(snap, dict):
                desc = snap.get("full_description") or snap.get("fit_source_text") or ""
                if desc:
                    return desc
        seek_path = OUTPUT_DIR / "seek_results.json"
        if seek_path.exists():
            try:
                rows = json.loads(seek_path.read_text(encoding="utf-8"))
                if isinstance(rows, list):
                    for row in rows:
                        if str(row.get("job_key") or "") == str(job_id):
                            return row.get("full_description") or row.get("fit_source_text") or ""
            except Exception:
                pass
        return ""

    @classmethod
    def _save_not_for_me_feedback(
        cls,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
    ) -> dict:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            raise ValueError("Missing job key")

        cls._persist_review_event(
            "not_for_me",
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
        )
        return {
            "ok": True,
            "action": "not_for_me",
            "job_key": normalized,
            "message": "Saved as Not For Me. This is stored as learning feedback, not a permanent title block.",
        }

    @classmethod
    def _save_block_similar_feedback(
        cls,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
        block_phrase: str = "",
    ) -> dict:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            raise ValueError("Missing job key")

        phrase = normalize_title_block_phrase(block_phrase) or suggest_title_block_phrase(title)
        if not phrase:
            raise ValueError("Could not suggest a title keyword to block from this title yet")

        rule = build_title_block_rule(phrase)
        profile = load_profile()
        existing = list(profile.get("reject_title_rules", []))
        rule_exists = any(str(item.get("pattern") or "").strip() == rule["pattern"] for item in existing)
        if not rule_exists:
            existing.append(rule)
            profile["reject_title_rules"] = existing
            save_profile(profile)

        cls._persist_review_event(
            "block_title",
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
            extra={
                "extracted_phrase": phrase,
                "reject_title_pattern": rule["pattern"],
                "reject_title_reason": rule["reason"],
                "rule_added": not rule_exists,
            },
        )
        return {
            "ok": True,
            "action": "block_similar",
            "job_key": normalized,
            "block_phrase": phrase,
            "rule": rule,
            "rule_added": not rule_exists,
            "message": (
                f"Added title block for '{phrase}'. Similar jobs will be filtered in future runs."
                if not rule_exists
                else f"Title block for '{phrase}' already existed."
            ),
        }

    @classmethod
    def _record_job_view(cls, job_key: str, url: str = "", title: str = "") -> dict:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            raise ValueError("Missing job key")

        history = cls._load_job_history()
        entry = history.get(normalized, {})
        now_iso = __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds")

        entry["job_key"] = normalized
        if title and not entry.get("title"):
            entry["title"] = title
        if url:
            entry["url"] = url
        entry["times_viewed"] = int(entry.get("times_viewed", 0) or 0) + 1
        if not entry.get("first_viewed_at"):
            entry["first_viewed_at"] = now_iso
        entry["last_viewed_at"] = now_iso

        history[normalized] = entry
        cls._save_job_history(history)
        return {
            "ok": True,
            "action": "viewed",
            "job_key": normalized,
            "times_viewed": entry["times_viewed"],
            "last_viewed_at": entry["last_viewed_at"],
        }

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, PATCH, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        payload = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def do_OPTIONS(self) -> None:
        self._send_json(200, {"ok": True})

    def do_GET(self) -> None:
        if self.path in {"/", "/admin", "/profile", "/demo", "/start", "/onboarding", "/dashboard"}:
            if self.path == "/profile":
                self._redirect("/admin")
                return
            if self.path in {"/start", "/onboarding"}:
                if ONBOARDING_HTML_PATH.exists():
                    self._send_html(ONBOARDING_HTML_PATH.read_text(encoding="utf-8", errors="ignore"))
                else:
                    self._send_html("<h1>Template missing</h1><p>Missing templates/onboarding.html</p>")
                return
            if self.path == "/dashboard":
                if DASHBOARD_PATH.exists():
                    self._send_html(DASHBOARD_PATH.read_text(encoding="utf-8", errors="ignore"))
                    return
                self._send_html("<h1>Dashboard not found yet</h1><p>Run the current job-source connector first.</p>")
                return
            if self.path == "/demo":
                if SHOWCASE_PATH.exists():
                    self._send_html(SHOWCASE_PATH.read_text(encoding="utf-8", errors="ignore"))
                    return
                self._send_html("<h1>Demo page not found</h1>")
                return
            if ADMIN_HTML_PATH.exists():
                self._send_html(ADMIN_HTML_PATH.read_text(encoding="utf-8", errors="ignore"))
            else:
                self._send_html("<h1>Template missing</h1><p>Missing templates/admin.html</p>")
            return
        if self.path == "/api/health":
            self._send_json(200, {"ok": True})
            return
        if self.path == "/api/run-stats":
            if RUN_STATS_PATH.exists():
                try:
                    payload = json.loads(RUN_STATS_PATH.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        self._send_json(200, payload)
                        return
                except Exception:
                    pass
            self._send_json(200, {})
            return
        if self.path == "/api/review-data":
            if REVIEW_DATA_PATH.exists():
                try:
                    payload = json.loads(REVIEW_DATA_PATH.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        payload["suggested_tuning"] = build_suggested_tuning_from_saved_review(
                            payload,
                            load_profile(),
                        )
                        self._send_json(200, payload)
                        return
                except Exception:
                    pass
            self._send_json(200, {})
            return
        if self.path == "/api/job-history":
            history = self._load_job_history()
            slim_history: dict[str, dict] = {}
            for job_key, entry in history.items():
                if not isinstance(entry, dict):
                    continue
                slim_history[str(job_key)] = {
                    "times_viewed": int(entry.get("times_viewed", 0) or 0),
                    "first_viewed_at": entry.get("first_viewed_at"),
                    "last_viewed_at": entry.get("last_viewed_at"),
                }
            self._send_json(200, {"jobs": slim_history})
            return
        if self.path == "/api/profile":
            self._send_json(200, load_profile())
            return
        if self.path == "/api/agent-settings":
            self._send_json(200, self._public_agent_settings_payload(load_agent_settings(create_if_missing=True)))
            return
        if self.path == "/api/telegram/connect-link":
            try:
                settings = load_agent_settings(create_if_missing=True)
                link = build_telegram_connect_link(settings["telegram"])
                save_agent_settings(settings)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "connect_link": link,
                    "bot_username": str(settings["telegram"].get("bot_username") or "").strip(),
                },
            )
            return
        if self.path == "/api/source-materials":
            self._send_json(200, load_source_materials(create_if_missing=True))
            return
        # Rejection-learning: suggestions endpoint
        import re as _re
        if _re.match(r'^/api/rejection-suggestions', self.path):
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            job_id = (params.get("job_id") or [""])[0].strip()
            if not job_id:
                self._send_json(400, {"error": "job_id is required"})
                return
            description = self._get_job_description(job_id)
            if not description:
                self._send_json(200, {})
                return
            suggestions = extract_rejection_suggestions(description)
            self._send_json(200, suggestions)
            return

        self._send_json(404, {"error": "Not found"})

    def do_PATCH(self) -> None:
        if self.path == "/api/agent-settings":
            try:
                current = load_agent_settings(create_if_missing=True)
                patch = self._sanitize_agent_settings_payload(self._read_json_body())
                telegram_patch = patch.get("telegram", {})
                if not str(telegram_patch.get("bot_token") or "").strip():
                    telegram_patch.pop("bot_token", None)
                current.setdefault("telegram", {}).update(telegram_patch)
                current.setdefault("llm", {}).update(patch.get("llm", {}))
                updated = save_agent_settings(current)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, self._public_agent_settings_payload(updated))
            return
        if self.path != "/api/profile":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            current = load_profile()
            patch = self._normalize_profile_patch_for_save(current, self._read_json_body())
            updated = patch_profile(patch)
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, updated)

    def do_PUT(self) -> None:
        if self.path == "/api/profile":
            try:
                updated = save_profile(self._read_json_body())
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, updated)
            return
        if self.path == "/api/source-materials":
            try:
                updated = save_source_materials(self._read_json_body())
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, updated)
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path == "/api/learning":
            try:
                payload = self._read_json_body()
                result = self._apply_learning_text(str(payload.get("text") or ""))
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/import-source-materials":
            try:
                payload = self._read_json_body()
                materials = save_source_materials(payload) if payload else load_source_materials(create_if_missing=True)
                result = run_onboarding(materials)
                result["materials"] = materials
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/onboarding/import":
            try:
                payload = self._read_json_body()
                files = payload.get("files", [])
                extra_text = str(payload.get("extra_text") or "")
                if not isinstance(files, list):
                    raise ValueError("files must be a list")
                materials = persist_uploaded_source_pack(files, extra_text=extra_text)
                result = run_onboarding(materials)
                result["materials"] = materials
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/onboarding/confirm-title-patterns":
            try:
                payload = self._read_json_body()
                target = [str(p).strip() for p in payload.get("target_title_patterns", []) if str(p).strip()]
                adjacent = [str(p).strip() for p in payload.get("adjacent_title_patterns", []) if str(p).strip()]
                keyword = str(payload.get("search_keyword") or "").strip()
                if not target:
                    raise ValueError("target_title_patterns must not be empty")
                profile_patch: dict = {"target_title_patterns": target}
                if adjacent:
                    profile_patch["adjacent_title_patterns"] = adjacent
                if keyword:
                    current = load_profile()
                    search_settings = dict(current.get("search_settings", {}))
                    search_settings["keywords"] = keyword
                    profile_patch["search_settings"] = search_settings
                updated = patch_profile(profile_patch)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True, "message": "Title patterns and search keyword saved.", "profile": updated})
            return
        if self.path in {"/api/tuning-decisions", "/api/skill-decisions"}:
            try:
                payload = self._read_json_body()
                decisions = payload.get("decisions", [])
                if not isinstance(decisions, list):
                    raise ValueError("decisions must be a list")
                profile = load_profile()
                updated = apply_capability_tuning_decisions(profile, decisions)
                save_profile(updated)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "message": "Capability tuning suggestions applied to profile.json.",
                    "profile": updated,
                },
            )
            return
        if self.path == "/api/rule/phrase":
            try:
                payload = self._read_json_body()
                phrase = str(payload.get("phrase") or "").strip().lower()
                reason = str(payload.get("reason") or "").strip()
                if not phrase:
                    raise ValueError("phrase is required")
                profile = load_profile()
                existing = list(profile.get("reject_description_phrase_rules", []))
                if not any(str(r.get("phrase") or "").strip().lower() == phrase for r in existing):
                    existing.append({"phrase": phrase, "reason": reason or f"DESC_REJECT:{phrase}"})
                    profile["reject_description_phrase_rules"] = existing
                    updated = save_profile(profile)
                else:
                    updated = profile
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True, "message": f"Phrase rule added: {phrase}", "profile": updated})
            return
        if self.path == "/api/telegram/sync":
            try:
                settings = load_agent_settings(create_if_missing=True)
                result = sync_telegram_subscribers(settings["telegram"])
                updated = save_agent_settings(settings)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "message": f"Telegram sync complete. {result['total_subscribers']} subscriber(s) available.",
                    "result": result,
                    "settings": self._public_agent_settings_payload(updated),
                },
            )
            return
        if self.path == "/api/telegram/test-message":
            try:
                payload = self._read_json_body()
                settings = load_agent_settings(create_if_missing=True)
                message_text = str(payload.get("message") or "").strip() or "Job Hunter test message."
                result = send_telegram_notification(message_text, "", settings["telegram"])
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "message": "Telegram test message sent.",
                    "result": result,
                },
            )
            return
        if self.path == "/api/rejection-rules":
            _VALID_CATEGORIES = {
                "domain", "mandatory_experience", "mandatory_skill",
                "role_type", "seniority", "work_arrangement",
                "industry_platform", "clearance_or_regulation", "other",
            }
            _JUNK_VALUES = {"no", "bad", "not me", "yes", "ok", "good", "n/a"}
            try:
                payload = self._read_json_body()
                job_id = str(payload.get("job_id") or "").strip()
                job_title = str(payload.get("job_title") or "").strip()
                raw_rules = payload.get("rules")
                if not isinstance(raw_rules, list):
                    raise ValueError("rules must be a list")
                validated = []
                now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                for i, r in enumerate(raw_rules):
                    value = str(r.get("value") or "").strip()
                    category = str(r.get("category") or "other").strip()
                    if not value or len(value) < 3:
                        continue
                    if value.lower() in _JUNK_VALUES:
                        continue
                    if category not in _VALID_CATEGORIES:
                        category = "other"
                    validated.append({
                        "id": f"{job_id}_{now_iso}_{i}",
                        "job_id": job_id,
                        "job_title": job_title,
                        "value": value,
                        "category": category,
                        "source": str(r.get("source") or "user_selected"),
                        "active": True,
                        "created_at": now_iso,
                    })
                if not validated:
                    raise ValueError("No valid rules provided (check minimum length >= 3)")
                existing = self._load_rejection_rules()
                existing.extend(validated)
                self._save_rejection_rules_list(existing)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True, "saved": len(validated)})
            return

        if self.path != "/api/review":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            payload = self._read_json_body()
            action = str(payload.get("action", "")).strip().lower()
            job_key = str(payload.get("job_key") or payload.get("url") or "").strip()
            url = str(payload.get("url") or "").strip()
            title = str(payload.get("title") or "").strip()
            company = str(payload.get("company") or "").strip()
            teaser = str(payload.get("teaser") or "").strip()
            if action == "viewed":
                result = self._record_job_view(
                    job_key,
                    url,
                    title,
                )
            elif action == "not_for_me":
                result = self._save_not_for_me_feedback(
                    job_key,
                    url,
                    title,
                    company,
                    teaser,
                )
            elif action == "block_similar":
                result = self._save_block_similar_feedback(
                    job_key,
                    url,
                    title,
                    company,
                    teaser,
                    str(payload.get("block_phrase") or "").strip(),
                )
            elif action == "unhide":
                result = self._remove_review_key(
                    action,
                    job_key,
                    url,
                    title,
                    company,
                    teaser,
                )
            else:
                result = self._append_review_key(
                    action,
                    job_key,
                    url,
                    title,
                    company,
                    teaser,
                )
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, result)

    def do_DELETE(self) -> None:
        if self.path == "/api/rule/title-block":
            try:
                payload = self._read_json_body()
                pattern = str(payload.get("pattern") or "").strip()
                if not pattern:
                    raise ValueError("pattern is required")
                profile = load_profile()
                existing = list(profile.get("reject_title_rules", []))
                updated_rules = [r for r in existing if str(r.get("pattern") or "").strip() != pattern]
                if len(updated_rules) == len(existing):
                    self._send_json(404, {"error": "Rule not found"})
                    return
                profile["reject_title_rules"] = updated_rules
                saved = save_profile(profile)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True, "reject_title_rules": saved.get("reject_title_rules", [])})
            return
        self._send_json(404, {"error": "Not found"})

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), AdminHandler)
    print(f"Local server running at http://{HOST}:{PORT}")
    print(f"Dashboard: http://{HOST}:{PORT}/dashboard")
    print(f"Admin: http://{HOST}:{PORT}/admin")
    print(f"Onboarding: http://{HOST}:{PORT}/start")
    server.serve_forever()
