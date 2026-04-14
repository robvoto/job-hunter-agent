"""Deprecated shim that forwards to the canonical scraper entry point.

Canonical command:
- python scraper_direct.py

This file remains only as a safety alias for older local habits.
"""

from run_jobs import main

if __name__ == "__main__":
    main()
