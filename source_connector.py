"""Compatibility launcher for the packaged source connector."""

import logging
import os
import sys
from runpy import run_module

from dotenv import load_dotenv


def _log_launcher_status(message: str, level: str = "info") -> None:
    print(message)
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("job_hunter_agent")
    if level == "warning":
        logger.warning(message)
    else:
        logger.info(message)


if __name__ == "__main__":
    load_dotenv()

    cli_flags = set(sys.argv[1:])
    rebuild_only_mode = "--rebuild-dashboard" in cli_flags
    no_llm_mode = "--no-llm" in cli_flags
    has_openai_key = bool(os.getenv("OPENAI_API_KEY"))

    if rebuild_only_mode:
        if has_openai_key:
            _log_launcher_status(
                "OPENAI_API_KEY detected. Dashboard rebuild mode will not call LLM review."
            )
        else:
            _log_launcher_status(
                "OPENAI_API_KEY not found. Dashboard rebuild mode does not need LLM review."
            )
    elif not has_openai_key:
        warning_msg = "OPENAI_API_KEY not found. LLM review is DISABLED."
        print("\n" + "!" * 80)
        print(f"WARNING: {warning_msg}")
        print("The system will fall back to deterministic filters and keyword matching.")
        print("!" * 80 + "\n")
        logging.basicConfig(level=logging.INFO)
        logging.getLogger("job_hunter_agent").warning(warning_msg)
    elif no_llm_mode:
        _log_launcher_status(
            "OPENAI_API_KEY detected. --no-llm flag is active, so LLM review is disabled for this run."
        )
    else:
        _log_launcher_status("OPENAI_API_KEY loaded successfully. LLM review is ENABLED.")

    run_module("job_hunter_agent.source_connector", run_name="__main__")
