"""Generate an RSS feed from Deloitte Insights."""
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from lxml import etree

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

ALLOWED_CONTENT_TYPES = {"Article", "Collection", "Magazine", "Report", "Brief"}

CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
MEDIA_NS = "http://search.yahoo.com/mrss/"
ATOM_NS = "http://www.w3.org/2005/Atom"


def _canonical_url(href: str) -> str:
    """Strip tracking query params and return an absolute URL."""
    full = urljoin(SOURCE_URL, href)
    parsed = urlparse(full)
    return urlunparse(parsed._replace(query="", fragment=""))


def _fetch_og(url: str) -> dict:
    """Return og:image and og:description from an article page, or {} on failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        result = {}
        for m in soup.find_all("meta"):
            prop = m.get("property") or ""
            if prop == "og:image":
                result["image"] = m.get("content", "")
            elif prop == "og:description":
                result["description"] = m.get("content", "")
        return result
    except Exception:
        return {}


def fetch_articles() -> list[dict]:
    r = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    seen: set[str] = set()
    articles: list[dict] = []

    for a in soup.select("a[data-promo-name][href]"):
        title = a.get("data-promo-name", "").strip()
        content_type = a.get("data-promo-content-type", "").strip()
        href = a.get("href", "")

        if not title or not href:
            continue
        if content_type not in ALLOWED_CONTENT_TYPES:
            continue

        canonical = _canonical_url(href)
        if "deloitte.com" not in canonical:
            continue

        path = urlparse(canonical).path
        if path.count("/") < 4:
            continue

        if canonical in seen:
            continue
        seen.add(canonical)

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

    # For articles missing a thumbnail or description, fetch og: tags from the article page
    needs_og = [art for art in articles if not art["thumbnail"] or not art["description"]]
    if needs_og:
        print(f"Fetching og: data for {len(needs_og)} articles...")
        for art in needs_og:
            time.sleep(0.5)
            og = _fetch_og(art["url"])
            if not art["thumbnail"] and og.get("image"):
                art["thumbnail"] = og["image"]
            if not art["description"] and og.get("description"):
                art["description"] = og["description"]

    return articles


def build_feed(articles: list[dict]) -> bytes:
    nsmap = {
        "content": CONTENT_NS,
        "media": MEDIA_NS,
        "atom": ATOM_NS,
    }

    rss = etree.Element("rss", attrib={"version": "2.0"}, nsmap=nsmap)
    channel = etree.SubElement(rss, "channel")

    etree.SubElement(channel, "title").text = "Deloitte Insights"
    etree.SubElement(channel, "link").text = SOURCE_URL
    etree.SubElement(channel, "description").text = "Latest Deloitte Insights articles (unofficial feed)"
    etree.SubElement(channel, "language").text = "en"
    etree.SubElement(channel, "lastBuildDate").text = (
        datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    )

    for art in articles:
        item = etree.SubElement(channel, "item")
        etree.SubElement(item, "title").text = art["title"]
        etree.SubElement(item, "link").text = art["url"]
        guid = etree.SubElement(item, "guid", attrib={"isPermaLink": "true"})
        guid.text = art["url"]

        # Plain text <description> — safe fallback for basic readers
        plain_parts = []
        if art["content_type"]:
            plain_parts.append(art["content_type"])
        if art["read_time"]:
            plain_parts.append(art["read_time"])
        if art["description"]:
            plain_parts.append(art["description"])
        etree.SubElement(item, "description").text = " • ".join(plain_parts)

        # <content:encoded> — CDATA HTML rendered by newsletter tools
        html_parts = []
        if art["thumbnail"]:
            html_parts.append(f'<img src="{art["thumbnail"]}" alt="" style="max-width:100%"/>')
        meta_parts = []
        if art["content_type"]:
            meta_parts.append(art["content_type"])
        if art["read_time"]:
            meta_parts.append(art["read_time"])
        if meta_parts:
            html_parts.append(f'<p><em>{" • ".join(meta_parts)}</em></p>')
        if art["description"]:
            html_parts.append(f'<p>{art["description"]}</p>')
        if html_parts:
            encoded = etree.SubElement(item, f"{{{CONTENT_NS}}}encoded")
            encoded.text = etree.CDATA("".join(html_parts))

        # <media:thumbnail> — dedicated image slot used by newsletter card previews
        if art["thumbnail"]:
            etree.SubElement(
                item, f"{{{MEDIA_NS}}}thumbnail", attrib={"url": art["thumbnail"]}
            )

    return etree.tostring(rss, pretty_print=True, xml_declaration=True, encoding="UTF-8")


if __name__ == "__main__":
    articles = fetch_articles()
    print(f"Found {len(articles)} articles")
    for art in articles:
        ctype = f"[{art['content_type']}]" if art["content_type"] else ""
        thumb = "✓ thumbnail" if art["thumbnail"] else "no thumbnail"
        desc = "✓ description" if art["description"] else "no description"
        print(f"  {ctype} {art['title']!r} ({art['read_time']}) [{thumb}] [{desc}]")
        print(f"    {art['url']}")
    with open("deloitte_insights.xml", "wb") as f:
        f.write(build_feed(articles))
    print("\nWrote deloitte_insights.xml")
