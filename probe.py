"""
Deep DOM probe for Deloitte Insights — run once to understand page structure,
then use the findings to tune scrape.py selectors.
"""
import json
import re
import sys
from collections import Counter
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

TARGET = "https://www.deloitte.com/us/en/insights.html"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SEP = "-" * 72


def section(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


def fetch(url: str) -> tuple[requests.Response, BeautifulSoup]:
    print(f"GET {url}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    print(f"Status: {r.status_code}  |  Content-Length: {len(r.text):,} chars")
    soup = BeautifulSoup(r.text, "html.parser")
    return r, soup


def check_js_rendering(soup: BeautifulSoup, raw_html: str) -> None:
    section("JS-RENDERING CHECK")
    body = soup.body
    text_len = len(body.get_text()) if body else 0
    print(f"Body text length: {text_len:,} chars")
    noscript_tags = soup.find_all("noscript")
    print(f"<noscript> tags: {len(noscript_tags)}")
    # Common SPA root patterns
    spa_hints = ["__NEXT_DATA__", "window.__INITIAL_STATE__", "ng-version", "data-reactroot"]
    for hint in spa_hints:
        if hint in raw_html:
            print(f"  [SPA hint found] {hint}")
    if text_len < 2000:
        print("  WARNING: very little body text — page likely requires JS to render articles")
    else:
        print("  OK: page has substantial text content")


def structured_data(soup: BeautifulSoup) -> None:
    section("STRUCTURED DATA (JSON-LD)")
    scripts = soup.find_all("script", type="application/ld+json")
    if not scripts:
        print("  None found")
        return
    for i, s in enumerate(scripts, 1):
        try:
            data = json.loads(s.string or "")
            dtype = data.get("@type", "?") if isinstance(data, dict) else f"array[{len(data)}]"
            print(f"  [{i}] @type={dtype}")
            if isinstance(data, dict) and data.get("@type") in ("ItemList", "Article", "NewsArticle"):
                print(json.dumps(data, indent=4)[:2000])
        except Exception as e:
            print(f"  [{i}] parse error: {e}")


def meta_tags(soup: BeautifulSoup) -> None:
    section("OPEN GRAPH / META")
    for m in soup.find_all("meta"):
        prop = m.get("property") or m.get("name") or ""
        if prop.startswith("og:") or prop in ("description", "keywords"):
            print(f"  {prop}: {m.get('content', '')[:120]}")


def page_outline(soup: BeautifulSoup) -> None:
    section("PAGE OUTLINE (headings + landmarks)")
    for tag in soup.find_all(["h1", "h2", "h3", "main", "article", "section", "nav", "aside"]):
        text = tag.get_text(strip=True)[:80]
        classes = " ".join(tag.get("class", []))[:60]
        print(f"  <{tag.name}> [{classes}]  {text!r}")


def link_patterns(soup: BeautifulSoup) -> None:
    section("LINK HREF PATTERNS (top 30 by frequency)")
    hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]
    # Bucket by path prefix (first two segments)
    def prefix(href: str) -> str:
        parts = href.strip("/").split("/")
        return "/" + "/".join(parts[:3]) if len(parts) >= 3 else href

    counter: Counter = Counter(prefix(h) for h in hrefs)
    for pattern, count in counter.most_common(30):
        print(f"  {count:4d}x  {pattern}")


def article_candidates(soup: BeautifulSoup) -> None:
    section("ARTICLE CANDIDATE ELEMENTS")
    candidate_selectors = [
        "article",
        "[class*='article']",
        "[class*='card']",
        "[class*='tile']",
        "[class*='insight']",
        "[class*='feature']",
        "[class*='content-item']",
        "[class*='listing']",
        "[class*='result']",
        "[class*='post']",
        "li[class]",
    ]
    for sel in candidate_selectors:
        found = soup.select(sel)
        if found:
            print(f"\n  selector: {sel!r}  ({len(found)} matches)")
            for el in found[:3]:
                classes = " ".join(el.get("class", []))
                text = el.get_text(" ", strip=True)[:120]
                links = el.find_all("a", href=True)
                hrefs = [a["href"] for a in links[:3]]
                print(f"    classes: {classes}")
                print(f"    text:    {text!r}")
                print(f"    links:   {hrefs}")


def data_attributes(soup: BeautifulSoup) -> None:
    section("DATA-* ATTRIBUTES (unique names, top 20)")
    attrs: Counter = Counter()
    for tag in soup.find_all(True):
        if isinstance(tag, Tag):
            for attr in tag.attrs:
                if attr.startswith("data-"):
                    attrs[attr] += 1
    for attr, count in attrs.most_common(20):
        sample = ""
        el = soup.find(attrs={attr: True})
        if el and isinstance(el, Tag):
            sample = str(el.get(attr, ""))[:60]
        print(f"  {count:4d}x  {attr}  eg: {sample!r}")


def insights_links(soup: BeautifulSoup) -> None:
    section("LINKS CONTAINING '/insights' (first 30)")
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/insight" in href.lower() and href not in seen:
            seen.add(href)
            full = urljoin(TARGET, href)
            text = a.get_text(strip=True)[:80]
            print(f"  {full}")
            print(f"    text: {text!r}")
            if len(seen) >= 30:
                break
    if not seen:
        print("  None found")


def save_html(raw: str) -> None:
    path = "probe_page.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw)
    print(f"\nRaw HTML saved to {path} ({len(raw):,} chars)")


def main() -> None:
    try:
        r, soup = fetch(TARGET)
    except Exception as e:
        print(f"Fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

    check_js_rendering(soup, r.text)
    structured_data(soup)
    meta_tags(soup)
    page_outline(soup)
    link_patterns(soup)
    article_candidates(soup)
    data_attributes(soup)
    insights_links(soup)
    save_html(r.text)


if __name__ == "__main__":
    main()
