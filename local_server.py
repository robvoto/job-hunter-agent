"""Compatibility launcher for the packaged local server."""
import os
import logging
from dotenv import load_dotenv
from runpy import run_module

if __name__ == "__main__":
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        warning_msg = "OPENAI_API_KEY not found. LLM features (like Fit Brief generation) are DISABLED."
        print("\n" + "!" * 80)
        print(f"⚠️  WARNING: {warning_msg}")
        print("The server will start, but AI-assisted profiling will not work.")
        print("!" * 80 + "\n")
        
        # Ensure the warning also goes to the logs
        logging.basicConfig(level=logging.INFO)
        logging.getLogger("job_hunter_agent").warning(warning_msg)
    else:
        success_msg = "OPENAI_API_KEY loaded successfully. LLM features are ENABLED."
        print(f"✅ {success_msg}")
        logging.basicConfig(level=logging.INFO)
        logging.getLogger("job_hunter_agent").info(success_msg)

    run_module("job_hunter_agent.local_server", run_name="__main__")
