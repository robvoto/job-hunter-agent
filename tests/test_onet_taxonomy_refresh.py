"""Tests for O*NET release discovery and safe freshness checks."""

import json

from job_hunter_agent.onet_taxonomy_refresh import (
    OnetRelease,
    discover_release_from_html,
    taxonomy_is_current,
)


def test_discover_release_uses_official_json_ld_distribution():
    payload = {
        "@context": "http://schema.org",
        "@type": "Dataset",
        "name": "O*NET Database",
        "distribution": [
            {
                "@type": "DataDownload",
                "name": "O*NET 30.3 Database, JSON version",
                "contentURL": "https://www.onetcenter.org/dl_files/database/db_30_3_json.zip",
            },
            {
                "@type": "DataDownload",
                "name": "O*NET 30.3 Database, Excel version",
                "contentURL": "https://example.invalid/excel.zip",
            },
        ],
    }
    html = (
        "<html><head><script type='application/ld+json'>"
        + json.dumps(payload)
        + "</script></head></html>"
    )

    release = discover_release_from_html(html)

    assert release.database_release == "30.3"
    assert release.download_url.endswith("db_30_3_json.zip")


def test_freshness_requires_release_source_and_dataset_fingerprint():
    release = OnetRelease("30.3", "https://www.onetcenter.org/dl_files/database/db_30_3_json.zip")
    current = {
        "database_release": "30.3",
        "source_url": release.download_url,
        "dataset_fingerprint": "a" * 64,
    }
    assert taxonomy_is_current(current, release) is True
    assert taxonomy_is_current(current, release, {"dataset_fingerprint": "a" * 64}) is True
    assert taxonomy_is_current(current, release, {"dataset_fingerprint": "b" * 64}) is False
    assert taxonomy_is_current({**current, "database_release": "30.2"}, release) is False
    assert taxonomy_is_current({**current, "dataset_fingerprint": ""}, release) is False
    assert taxonomy_is_current({**current, "source_url": "legacy"}, release) is False
