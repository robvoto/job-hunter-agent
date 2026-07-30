"""Helpers for classifying captured page text before treating it as job content."""

from __future__ import annotations

import re

_CHALLENGE_MARKERS = (
    "help us keep seek secure",
    "enable javascript and cookies to continue",
    "verification successful. waiting for",
    "challenge-error-text",
    "sorry to interrupt",
    "css error",
)

_CHALLENGE_COMPACT_MARKERS = (
    "cfchl",
    "sorrytointerruptcsserror",
    "navigatorcookieenabled",
    "cookiemessageinnerhtml",
    "enablejavascriptandcookiestocontinue",
)

_BLOCK_MARKERS = (
    "access denied",
    "temporarily unavailable",
    "request unsuccessful",
)


def classify_captured_page_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not normalized:
        return "empty"

    compact = re.sub(r"[^a-z0-9]+", "", normalized)
    if any(marker in normalized for marker in _CHALLENGE_MARKERS) or any(
        marker in compact for marker in _CHALLENGE_COMPACT_MARKERS
    ):
        return "challenge_page"
    if any(marker in normalized for marker in _BLOCK_MARKERS):
        return "blocked_page"
    return "ok"


def looks_like_browser_interstitial_text(text: str) -> bool:
    return classify_captured_page_text(text) in {"challenge_page", "blocked_page"}
