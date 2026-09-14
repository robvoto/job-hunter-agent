"""Tests for scraper health validation."""

from job_hunter_agent import scraper_health


def test_run_scraper_configuration_validation_passes_without_warnings(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        scraper_health,
        "record_system_warning",
        lambda **kwargs: recorded.append(kwargs) or {"id": 1},
    )

    result = scraper_health.run_scraper_configuration_validation()

    assert result["ok"] is True
    assert result["warnings_recorded"] == 0
    assert recorded == []
    assert {item["source"] for item in result["results"]} == {
        "source_registry",
        "seek",
        "linkedin",
        "apsjobs",
    }


def test_source_registry_validation_requires_jmm_display_label(monkeypatch):
    registry = scraper_health.load_source_registry()
    labels_without_jmm = dict(registry["source_display_labels"])
    labels_without_jmm.pop("job_market_map")
    monkeypatch.setattr(
        scraper_health,
        "load_source_registry",
        lambda: {**registry, "source_display_labels": labels_without_jmm},
    )

    result = scraper_health._validate_source_registry()

    assert result["status"] == "warning"
    assert any("job_market_map" in issue for issue in result["issues"])


def test_run_scraper_configuration_validation_records_warning_for_failed_group(monkeypatch):
    monkeypatch.setattr(
        scraper_health,
        "_validate_seek_configuration",
        lambda: {
            "source": "seek",
            "status": "warning",
            "summary": "seek failed",
            "checks": ["example"],
            "issues": ["Broken selector"],
        },
    )
    recorded = []
    monkeypatch.setattr(
        scraper_health,
        "record_system_warning",
        lambda **kwargs: recorded.append(kwargs) or {"id": 7},
    )

    result = scraper_health.run_scraper_configuration_validation()

    assert result["ok"] is False
    assert result["warnings_recorded"] == 1
    assert recorded[0]["category"] == "scraper_configuration_validation"
    assert recorded[0]["source"] == "seek"
    assert recorded[0]["context"]["issues"] == ["Broken selector"]
