"""Compatibility entry point.

Main goal:
- preserve the simple `python main.py` entry path
- delegate to the clearer `run_jobs.py` runner

Notes:
- prefer `python run_jobs.py` in docs and day-to-day use
"""

from run_jobs import main

if __name__ == "__main__":
    main()
