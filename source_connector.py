"""Compatibility launcher for the packaged source connector."""
import os
import logging
from dotenv import load_dotenv
from runpy import run_module

if __name__ == "__main__":
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        warning_msg = "OPENAI_API_KEY not found. LLM review is DISABLED."
        print("\n" + "!" * 80)
        print(f"⚠️  WARNING: {warning_msg}")
        print("The system will fall back to deterministic filters and keyword matching.")
        print("!" * 80 + "\n")
        
        # Ensure the warning also goes to the logs
        logging.basicConfig(level=logging.INFO)
        logging.getLogger("job_hunter_agent").warning(warning_msg)
    else:
        success_msg = "OPENAI_API_KEY loaded successfully. LLM review is ENABLED."
        print(f"✅ {success_msg}")
        logging.basicConfig(level=logging.INFO)
        logging.getLogger("job_hunter_agent").info(success_msg)

    run_module("job_hunter_agent.source_connector", run_name="__main__")
