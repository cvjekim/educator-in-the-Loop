"""
Trend collector — scrapes the latest AI/tech trends from public sources.

Sources:
  - arxiv.org (recent popular papers)
  - aitrends.kr/trending
  - news.ycombinator.com/news (Hacker News)

Collects up to 10 posts/papers from the past month per run,
then writes them to data/trends/ via archive.save_trend().
"""

from __future__ import annotations

from datetime import date

from src.trends.archive import save_trend


def collect_all(limit: int = 10) -> list[str]:
    """Collect trends from all sources and save to archive. Returns saved filenames."""
    items: list[dict] = []
    items.extend(_fetch_arxiv(limit))
    items.extend(_fetch_aitrends(limit))
    items.extend(_fetch_hackernews(limit))

    items = items[:limit]
    saved = []
    for item in items:
        path = save_trend(
            category=item["category"],
            date=date.today().strftime("%Y%m%d"),
            topic=_slugify(item["title"]),
            content=_format_content(item),
        )
        saved.append(path.name)
    return saved


def _fetch_arxiv(limit: int) -> list[dict]:
    # TODO: query arxiv API for recent CS.AI / CS.CV / CS.LG papers
    return []


def _fetch_aitrends(limit: int) -> list[dict]:
    # TODO: scrape aitrends.kr/trending with requests + BeautifulSoup
    return []


def _fetch_hackernews(limit: int) -> list[dict]:
    # TODO: scrape news.ycombinator.com/news for AI-related posts
    return []


def _slugify(title: str) -> str:
    return title.strip().replace(" ", "-")[:60]


def _format_content(item: dict) -> str:
    return (
        f"- Number: \n"
        f"- Date: {date.today()}\n"
        f"- Topic: {item.get('title', '')}\n"
        f"- Category: {item.get('category', '')}\n"
        f"- Summary: {item.get('summary', '')}\n"
        f"- Source URL: {item.get('url', '')}\n"
    )
