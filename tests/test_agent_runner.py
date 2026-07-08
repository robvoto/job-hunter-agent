"""Tests for the daily agent runner CLI."""

from job_hunter_agent.agent_runner import _build_arg_parser


def test_daily_agent_runner_accepts_step_flag():
    args = _build_arg_parser().parse_args(["--step"])

    assert args.step is True
    assert args.loop is False
