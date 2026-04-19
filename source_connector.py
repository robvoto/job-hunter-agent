"""Compatibility launcher for the packaged source connector."""

from runpy import run_module


if __name__ == "__main__":
    run_module("job_hunter_agent.source_connector", run_name="__main__")
