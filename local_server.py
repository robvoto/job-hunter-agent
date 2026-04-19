"""Compatibility launcher for the packaged local server."""

from runpy import run_module


if __name__ == "__main__":
    run_module("job_hunter_agent.local_server", run_name="__main__")
