"""Focused tests for current O*NET database import formats and metadata."""

import json
import zipfile

import pytest

from job_hunter_agent.onet_taxonomy_import import build_taxonomy


def _write_json_zip(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "db_30_3_json/occupation_data.json",
            json.dumps(
                {
                    "row": [
                        {
                            "onetsoc_code": "13-1111.00",
                            "title": "Management Analysts",
                            "description": "Analyse organisations.",
                        },
                        {
                            "onetsoc_code": "15-1299.05",
                            "title": "Information Security Engineers",
                            "description": "Engineer security systems.",
                        },
                    ]
                }
            ),
        )
        archive.writestr(
            "db_30_3_json/job_titles.json",
            json.dumps(
                {
                    "row": [
                        {
                            "onetsoc_code": "13-1111.00",
                            "title": "Management Analysts",
                            "job_title": "Business Analyst",
                            "short_title": None,
                            "sources": "02,10",
                        },
                        {
                            "onetsoc_code": "15-1299.05",
                            "title": "Information Security Engineers",
                            "job_title": "Cloud Engineer",
                            "short_title": None,
                            "sources": "01,02",
                        },
                    ]
                }
            ),
        )
        archive.writestr(
            "db_30_3_json/sample_of_reported_titles.json",
            json.dumps(
                {
                    "row": [
                        {
                            "onetsoc_code": "13-1111.00",
                            "title": "Management Analysts",
                            "reported_job_title": "Business Analyst",
                            "shown_in_my_next_move": "Y",
                        }
                    ]
                }
            ),
        )


def test_current_json_zip_builds_job_title_index_and_target_preference(tmp_path):
    archive = tmp_path / "db_30_3_json.zip"
    _write_json_zip(archive)

    taxonomy = build_taxonomy(
        archive,
        source_url="https://www.onetcenter.org/dl_files/database/db_30_3_json.zip",
    )

    metadata = taxonomy["metadata"]
    assert metadata["database_release"] == "30.3"
    assert metadata["format"] == "fulldb_json"
    assert len(metadata["dataset_fingerprint"]) == 64
    business = taxonomy["by_normalized_title"]["business analyst"]
    assert business[0]["occupation_code"] == "13-1111.00"
    assert business[0]["target_query_preferred"] is True
    cloud = taxonomy["by_normalized_title"]["cloud engineer"]
    assert cloud[0]["occupation_code"] == "15-1299.05"
    assert "target_query_preferred" not in cloud[0]


def test_current_text_zip_accepts_nested_members_and_job_titles_rename(tmp_path):
    archive_path = tmp_path / "db_30_3_text.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "db_30_3_text/Occupation Data.txt",
            "O*NET-SOC Code\tTitle\tDescription\n"
            "15-1299.05\tInformation Security Engineers\tEngineer security systems.\n",
        )
        archive.writestr(
            "db_30_3_text/Job Titles.txt",
            "O*NET-SOC Code\tJob Title\tShort Title\tSource(s)\n"
            "15-1299.05\tCloud Engineer\tn/a\t01,02\n",
        )
        archive.writestr(
            "db_30_3_text/Sample of Reported Titles.txt",
            "O*NET-SOC Code\tReported Job Title\tShown in My Next Move\n"
            "15-1299.05\tCloud Engineer\tN\n",
        )

    taxonomy = build_taxonomy(archive_path)

    assert taxonomy["metadata"]["format"] == "fulldb_text"
    assert taxonomy["metadata"]["database_release"] == "30.3"
    assert taxonomy["by_normalized_title"]["cloud engineer"][0]["source"] == "job_title"


def test_legacy_occupational_listings_zip_is_rejected(tmp_path):
    archive_path = tmp_path / "OccupationalListings.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("2019_Occupations.xlsx", b"obsolete")
        archive.writestr("2019_Alt_Titles.xlsx", b"obsolete")

    with pytest.raises(ValueError, match=r"current full O\*NET database"):
        build_taxonomy(archive_path)
