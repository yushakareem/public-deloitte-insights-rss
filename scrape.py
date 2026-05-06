"""Generate an RSS feed from Deloitte Insights."""
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

SOURCE_URL = "https://www.deloitte.com/us/en/insights.html"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Content types worth including in the feed
ALLOWED_CONTENT_TYPES = {"Article", "Collection", "Magazine", "Report", "Brief"}


def _canonical_url(href: str) -> str:
    """Strip tracking query params and return an absolute URL."""
    full = urljoin(SOURCE_URL, href)
    parsed = urlparse(full)
    # Drop the query string entirely — Deloitte only uses ?icid= tracking params
    return urlunparse(parsed._replace(query="", fragment=""))


def fetch_articles() -> list[dict]:
    r = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    seen: set[str] = set()
    articles: list[dict] = []

    # Primary selector: anchor tags that carry Deloitte's own promo metadata.
    # These are the article/card links rendered directly in the page HTML.
    # The data-promo-name attribute is only present on real content cards,
    # not on navigation or footer links.
    for a in soup.select("a[data-promo-name][href]"):
        title = a.get("data-promo-name", "").strip()
        content_type = a.get("data-promo-content-type", "").strip()
        href = a.get("href", "")

        if not title or not href:
            continue

        # Require a recognised content type; empty means nav/promo links, not articles
        if content_type not in ALLOWED_CONTENT_TYPES:
            continue

        # Skip external links (YouTube, etc.)
        canonical = _canonical_url(href)
        if "deloitte.com" not in canonical:
            continue

        # Skip generic landing pages (no article slug depth)
        path = urlparse(canonical).path
        if path.count("/") < 4:
            continue

        if canonical in seen:
            continue
        seen.add(canonical)

        # Pull description, read-time, and thumbnail from child elements
        desc_tag = a.select_one(".cmp-di-promo__content__desc p")
        read_time_tag = a.select_one(".cmp-di-promo__content__read-time")
        s7 = a.select_one(".s7dm-dynamic-media")

        description = desc_tag.get_text(strip=True) if desc_tag else ""
        read_time = read_time_tag.get_text(strip=True) if read_time_tag else ""

        thumbnail = ""
        if s7:
            img_server = s7.get("data-imageserver", "").rstrip("/")
            asset_path = s7.get("data-asset-path", "")
            if img_server and asset_path:
                thumbnail = f"{img_server}/{asset_path}?fmt=webp&wid=640"

        articles.append({
            "title": title,
            "url": canonical,
            "content_type": content_type,
            "description": description,
            "read_time": read_time,
            "thumbnail": thumbnail,
        })

    return articles


def build_feed(articles: list[dict]) -> FeedGenerator:
    fg = FeedGenerator()
    fg.id(SOURCE_URL)
    fg.title("Deloitte Insights")
    fg.link(href=SOURCE_URL, rel="alternate")
    fg.description("Latest Deloitte Insights articles (unofficial feed)")
    fg.language("en")
    fg.lastBuildDate(datetime.now(timezone.utc))

    for art in articles:
        fe = fg.add_entry()
        fe.id(art["url"])
        fe.title(art["title"])
        fe.link(href=art["url"])
        fe.guid(art["url"], permalink=True)

        # Build an HTML description: thumbnail image + meta line + summary text
        parts = []
        if art["content_type"]:
            parts.append(art["content_type"])
        if art["read_time"]:
            parts.append(art["read_time"])
        meta = " • ".join(parts)

        html_parts = []
        if art["thumbnail"]:
            html_parts.append(
                f'<img src="{art["thumbnail"]}" alt="" style="max-width:100%"/>'
            )
        if meta:
            html_parts.append(f"<p><em>{meta}</em></p>")
        if art["description"]:
            html_parts.append(f"<p>{art['description']}</p>")

        if html_parts:
            fe.description("".join(html_parts))

    return fg


if __name__ == "__main__":
    articles = fetch_articles()
    print(f"Found {len(articles)} articles")
    for art in articles:
        ctype = f"[{art['content_type']}]" if art["content_type"] else ""
        rt = art["read_time"]
        thumb = "✓ thumbnail" if art["thumbnail"] else "no thumbnail"
        print(f"  {ctype} {art['title']!r} ({rt}) [{thumb}]")
        print(f"    {art['url']}")
    fg = build_feed(articles)
    fg.rss_file("deloitte_insights.xml", pretty=True)
    print("\nWrote deloitte_insights.xml")
