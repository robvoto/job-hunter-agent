"""Tests for fetch_job_rejection_sheet_rows and fetch_candidate_job_rejection_rows."""

from unittest.mock import MagicMock, patch

import pytest

from job_hunter_agent.candidate_application_history import (
    fetch_candidate_job_rejection_rows,
    fetch_job_rejection_sheet_rows,
)
from job_hunter_agent.global_settings import (
    get_candidate_application_history_spreadsheet_id,
    get_candidate_application_history_tab_name,
)

_VALID_CSV = (
    "Run Date,Company,From,Subject,Content,Thread ID,Message ID,Status\r\n"
    "2025-01-15,noreply@workday.com,hr@anz.com,"
    "Your application for Business Analyst at ANZ Bank,"
    "We regret to inform you...,T1,M1,Rejected\r\n"
)

_MISSING_HEADER_CSV = (
    "Date,Company,From,Subject,Content,Thread ID,Message ID,Status\r\n"
    "2025-01-15,X,Y,Z,W,T1,M1,Rejected\r\n"
)


def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.ok = status_code < 400
    resp.status_code = status_code
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# Successful fetch
# ---------------------------------------------------------------------------


def test_fetch_returns_list_of_dicts():
    with patch("job_hunter_agent.candidate_application_history.requests.get") as mock_get:
        mock_get.return_value = _mock_response(_VALID_CSV)
        rows = fetch_job_rejection_sheet_rows()

    assert isinstance(rows, list)
    assert len(rows) == 1
    row = rows[0]
    assert row["Run Date"] == "2025-01-15"
    assert row["Company"] == "noreply@workday.com"
    assert row["From"] == "hr@anz.com"
    assert row["Thread ID"] == "T1"
    assert row["Message ID"] == "M1"
    assert row["Status"] == "Rejected"


def test_fetch_uses_default_sheet_id_and_tab_in_url():
    with patch("job_hunter_agent.candidate_application_history.requests.get") as mock_get:
        mock_get.return_value = _mock_response(_VALID_CSV)
        fetch_job_rejection_sheet_rows()

    called_url = mock_get.call_args[0][0]
    assert get_candidate_application_history_spreadsheet_id() in called_url
    assert get_candidate_application_history_tab_name() in called_url


def test_fetch_accepts_custom_sheet_id_and_tab():
    with patch("job_hunter_agent.candidate_application_history.requests.get") as mock_get:
        mock_get.return_value = _mock_response(_VALID_CSV)
        fetch_job_rejection_sheet_rows(sheet_id="custom_id", tab_name="Custom_Tab")

    called_url = mock_get.call_args[0][0]
    assert "custom_id" in called_url
    assert "Custom_Tab" in called_url


# ---------------------------------------------------------------------------
# Missing headers raises ValueError
# ---------------------------------------------------------------------------


def test_missing_required_header_raises_value_error():
    with patch("job_hunter_agent.candidate_application_history.requests.get") as mock_get:
        mock_get.return_value = _mock_response(_MISSING_HEADER_CSV)
        with pytest.raises(ValueError, match="missing required headers"):
            fetch_job_rejection_sheet_rows()


def test_missing_header_error_names_the_missing_field():
    with patch("job_hunter_agent.candidate_application_history.requests.get") as mock_get:
        mock_get.return_value = _mock_response(_MISSING_HEADER_CSV)
        with pytest.raises(ValueError, match="Run Date"):
            fetch_job_rejection_sheet_rows()


# ---------------------------------------------------------------------------
# HTTP failure raises RuntimeError
# ---------------------------------------------------------------------------


def test_http_404_raises_runtime_error():
    with patch("job_hunter_agent.candidate_application_history.requests.get") as mock_get:
        mock_get.return_value = _mock_response("Not Found", status_code=404)
        with pytest.raises(RuntimeError, match="HTTP 404"):
            fetch_job_rejection_sheet_rows()


def test_http_500_raises_runtime_error():
    with patch("job_hunter_agent.candidate_application_history.requests.get") as mock_get:
        mock_get.return_value = _mock_response("Server Error", status_code=500)
        with pytest.raises(RuntimeError, match="HTTP 500"):
            fetch_job_rejection_sheet_rows()


# ---------------------------------------------------------------------------
# fetch_candidate_job_rejection_rows
# ---------------------------------------------------------------------------


def test_fetch_candidate_returns_empty_when_disabled():
    with patch(
        "job_hunter_agent.candidate_application_history.is_candidate_application_history_enabled",
        return_value=False,
    ):
        result = fetch_candidate_job_rejection_rows()
    assert result == []


def test_fetch_candidate_returns_rows_when_enabled():
    with (
        patch(
            "job_hunter_agent.candidate_application_history.is_candidate_application_history_enabled",
            return_value=True,
        ),
        patch("job_hunter_agent.candidate_application_history.requests.get") as mock_get,
    ):
        mock_get.return_value = _mock_response(_VALID_CSV)
        result = fetch_candidate_job_rejection_rows()

    assert len(result) == 1
    assert result[0]["Run Date"] == "2025-01-15"


def test_fetch_candidate_excludes_not_job_related_audit_rows():
    csv_text = (
        "Run Date,Company,Role,From,Subject,Content,Thread ID,Message ID,Status\r\n"
        "2026-09-01,Acme,Business Analyst,a@example.com,A,B,T1,M1,Rejected\r\n"
        "2026-09-01,Other,Newsletter,b@example.com,C,D,T2,M2,Not job-related\r\n"
    )
    with (
        patch(
            "job_hunter_agent.candidate_application_history.is_candidate_application_history_enabled",
            return_value=True,
        ),
        patch("job_hunter_agent.candidate_application_history.requests.get") as mock_get,
    ):
        mock_get.return_value = _mock_response(csv_text)
        result = fetch_candidate_job_rejection_rows()

    assert [row["Company"] for row in result] == ["Acme"]


def test_fetch_candidate_reads_config_from_settings():
    """URL must use spreadsheet_id and tab_name from global settings, not hardcoded values."""
    with (
        patch(
            "job_hunter_agent.candidate_application_history.is_candidate_application_history_enabled",
            return_value=True,
        ),
        patch("job_hunter_agent.candidate_application_history.requests.get") as mock_get,
    ):
        mock_get.return_value = _mock_response(_VALID_CSV)
        fetch_candidate_job_rejection_rows()

    called_url = mock_get.call_args[0][0]
    assert get_candidate_application_history_spreadsheet_id() in called_url
    assert get_candidate_application_history_tab_name() in called_url
