"""Compatibility launcher for the packaged test runner."""

from runpy import run_module


if __name__ == "__main__":
    run_module("job_hunter_agent.test_runner", run_name="__main__")
