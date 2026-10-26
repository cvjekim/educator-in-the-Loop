"""
Node: crawl_github
Iterates the roster and crawls each student's GitHub repository.
Only repositories listed in the roster are accessed.
"""

from __future__ import annotations

from src.github.crawler import crawl_repo


def crawl_github(state: dict) -> dict:
    """
    State reads:  roster
    State writes: crawled_data
    """
    roster: list[dict] = state["roster"]
    crawled_data: dict = {}

    for i, entry in enumerate(roster, start=1):
        student_id = entry["student_id"]
        crawled_data[student_id] = crawl_repo(entry)

    total = len(roster)
    return {
        "current_stage": "crawl_github",
        "overall_progress": 30,
        "status_message": f"GitHub 크롤링 완료 — {total}명",
        "crawled_data": crawled_data,
    }
