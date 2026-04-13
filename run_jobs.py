"""Descriptive runner for the current job-source collection flow.

Main goals:
- run the current job collection pipeline
- regenerate dashboard and review outputs from the latest live run

Notes:
- this is the preferred descriptive entry point for human use
- main.py remains as a thin compatibility wrapper
"""

from scraper_direct import scrape_seek_jobs_direct


def main() -> None:
    scrape_seek_jobs_direct()


if __name__ == "__main__":
    main()
