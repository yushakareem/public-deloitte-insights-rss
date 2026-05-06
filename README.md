# Deloitte Insights RSS

An unofficial RSS feed for [Deloitte Insights](https://www.deloitte.com/us/en/insights.html), auto-updated daily.

## Feed URL

```
https://raw.githubusercontent.com/yushakareem/public-deloitte-insights-rss/refs/heads/main/deloitte_insights.xml
```

## What's in the feed

Each entry includes the article title, a short description, read time, and a thumbnail where available. Content types: Articles, Collections, Reports, and Magazines.

## How it works

`scrape.py` fetches the Deloitte Insights homepage, extracts article cards, and writes `deloitte_insights.xml`. A GitHub Actions workflow runs this every day at 05:00 Amsterdam time and commits the updated feed back to the repo.

## Local run

```bash
uv run scrape.py
```
