"""Discover and safely refresh the local O*NET taxonomy from the official database release.

This module is an explicit maintenance action. Job-search runtime never calls the network.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlparse

from job_hunter_agent.onet_taxonomy_import import DEFAULT_OUTPUT_DIR, write_taxonomy_files

ONET_DATABASE_PAGE_URL = "https://www.onetcenter.org/database.html"
_JSON_DISTRIBUTION_RE = re.compile(r"^O\*NET\s+(\d+\.\d+)\s+Database,\s+JSON\s+version$", re.I)


@dataclass(frozen=True)
class OnetRelease:
    database_release: str
    download_url: str


@dataclass(frozen=True)
class RefreshResult:
    status: str
    database_release: str
    download_url: str
    previous_release: str


class _JsonLdScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self._parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        attr_map = {key.lower(): value for key, value in attrs}
        if str(attr_map.get("type") or "").lower() == "application/ld+json":
            self._capture = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._capture:
            self.blocks.append("".join(self._parts))
            self._capture = False
            self._parts = []


def _urlopen_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed official URL
        return response.read().decode("utf-8")


def discover_release_from_html(html: str) -> OnetRelease:
    """Read the advertised JSON database distribution from O*NET's JSON-LD metadata."""
    parser = _JsonLdScriptParser()
    parser.feed(html)
    candidates: list[OnetRelease] = []
    for block in parser.blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        payloads = payload if isinstance(payload, list) else [payload]
        for item in payloads:
            if not isinstance(item, dict) or item.get("@type") != "Dataset":
                continue
            for distribution in item.get("distribution") or []:
                if not isinstance(distribution, dict):
                    continue
                name = str(distribution.get("name") or "").strip()
                match = _JSON_DISTRIBUTION_RE.match(name)
                url = str(
                    distribution.get("contentURL")
                    or distribution.get("contentUrl")
                    or distribution.get("url")
                    or ""
                ).strip()
                if match and url:
                    candidates.append(OnetRelease(match.group(1), url))
    if not candidates:
        raise ValueError("Official O*NET database page did not advertise a JSON database release")
    releases = {(item.database_release, item.download_url) for item in candidates}
    if len(releases) != 1:
        raise ValueError(
            f"Official O*NET page advertised conflicting JSON releases: {sorted(releases)}"
        )
    return candidates[0]


def discover_current_release(page_url: str = ONET_DATABASE_PAGE_URL) -> OnetRelease:
    return discover_release_from_html(_urlopen_text(page_url))


def load_installed_metadata(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    index_path = output_dir / "onet_index.json"
    if not index_path.is_file():
        return {}
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def taxonomy_is_current(
    installed: dict[str, Any], release: OnetRelease, candidate: dict[str, Any] | None = None
) -> bool:
    """Compare release/source and, when available, the newly generated fingerprint."""
    installed_fingerprint = str(installed.get("dataset_fingerprint") or "")
    if not (
        str(installed.get("database_release") or "") == release.database_release
        and installed_fingerprint
        and str(installed.get("source_url") or "") == release.download_url
    ):
        return False
    if candidate is None:
        return True
    return installed_fingerprint == str(candidate.get("dataset_fingerprint") or "")


def _generated_files_match(installed_dir: Path, candidate_dir: Path) -> bool:
    for filename in ("onet_index.json", "onet_occupations.json"):
        installed = installed_dir / filename
        candidate = candidate_dir / filename
        if not installed.is_file() or not candidate.is_file():
            return False
        if installed.read_bytes() != candidate.read_bytes():
            return False
    return True


def _download(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as target:  # noqa: S310 - official URL discovered from fixed O*NET page
        shutil.copyfileobj(response, target)
    if destination.stat().st_size == 0:
        raise ValueError("Downloaded O*NET database archive is empty")


def refresh_taxonomy(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    update: bool,
    page_url: str = ONET_DATABASE_PAGE_URL,
) -> RefreshResult:
    """Check freshness, and optionally atomically rebuild from the current official release."""
    release = discover_current_release(page_url)
    installed = load_installed_metadata(output_dir)
    previous_release = str(installed.get("database_release") or "")

    # Rebuild in isolation even when the release number is unchanged. O*NET can
    # republish a release; comparing the generated fingerprint catches that case.
    with TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir)
        basename = Path(urlparse(release.download_url).path).name or "onet_database.zip"
        archive_path = tmp_root / basename
        candidate_dir = tmp_root / "generated"
        _download(release.download_url, archive_path)
        candidate_metadata = write_taxonomy_files(
            archive_path,
            candidate_dir,
            database_release=release.database_release,
            source_url=release.download_url,
        )
        if taxonomy_is_current(installed, release, candidate_metadata) and _generated_files_match(
            output_dir, candidate_dir
        ):
            return RefreshResult(
                "current", release.database_release, release.download_url, previous_release
            )
        if not update:
            return RefreshResult(
                "stale", release.database_release, release.download_url, previous_release
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        for filename in ("onet_index.json", "onet_occupations.json"):
            candidate = candidate_dir / filename
            staged = output_dir / f".{filename}.refresh"
            shutil.copy2(candidate, staged)
            staged.replace(output_dir / filename)
        obsolete = output_dir / "onet_alternate_titles.json"
        if obsolete.exists():
            obsolete.unlink()

    return RefreshResult(
        "updated", release.database_release, release.download_url, previous_release
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check", action="store_true", help="Report whether local O*NET data is current"
    )
    mode.add_argument(
        "--update",
        action="store_true",
        help="Refresh only when the official release is newer/different",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    result = refresh_taxonomy(args.output_dir, update=args.update)
    print(
        f"O*NET taxonomy: {result.status}; "
        f"installed={result.previous_release or 'not-installed'}; "
        f"official={result.database_release}"
    )
    if args.check and result.status == "stale":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
