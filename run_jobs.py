"""Deprecated shim that forwards to the canonical scraper entry point.

Canonical command:
- python scraper_direct.py

This file remains only as a safety alias for older local habits.
"""

from scraper_direct import scrape_seek_jobs_direct


def main() -> None:
    scrape_seek_jobs_direct()


if __name__ == "__main__":
    main()
