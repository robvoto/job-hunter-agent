"""Compatibility launcher for the packaged agent runner."""

from runpy import run_module


if __name__ == "__main__":
    run_module("job_hunter_agent.agent_runner", run_name="__main__")
