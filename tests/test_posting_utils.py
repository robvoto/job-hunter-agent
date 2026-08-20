from job_hunter_agent.posting_utils import format_timestamp_label, parse_timestamp


def test_parse_timestamp_accepts_spreadsheet_style_timestamp():
    timestamp = parse_timestamp("6/21/2021 18:37:57")

    assert timestamp is not None
    assert timestamp.isoformat(sep=" ") == "2021-06-21 18:37:57"


def test_format_timestamp_label_can_render_date_without_time():
    assert format_timestamp_label("6/21/2021 18:37:57", include_time=False) == "21 Jun 2021"
    assert "18:37:57" not in format_timestamp_label(
        "6/21/2021 18:37:57", include_time=False
    )


def test_format_timestamp_label_keeps_time_by_default():
    assert format_timestamp_label("2021-06-21 18:37:57") == "21 Jun 2021 06:37 PM"
