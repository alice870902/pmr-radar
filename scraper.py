import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
from datetime import datetime, timezone

BASE = "https://www.sumroc.org.tw"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PMR-Radar/1.0; +https://github.com)"
}

SOURCES = [
    {
        "id": "sumroc",
        "name": "中華民國醫用超音波學會",
        "url": BASE,
    }
]


def get_soup(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    return BeautifulSoup(resp.text, "lxml")


def parse_date_range(date_str):
    """Return (date_start, date_end) in YYYY-MM-DD format."""
    if not date_str:
        return "", ""
    date_str = date_str.strip()
    if "~" in date_str:
        parts = date_str.split("~")
        start = parts[0].strip().replace(".", "-")
        end_raw = parts[1].strip()
        if re.match(r"\d{4}", end_raw):
            end = end_raw.replace(".", "-")
        else:
            # Short end like "19" — borrow year-month from start
            ym = "-".join(start.split("-")[:2])
            end = f"{ym}-{end_raw.zfill(2)}"
        return start, end
    else:
        d = date_str.replace(".", "-")
        return d, d


def get_info(item, label):
    for div in item.select("div.info"):
        span = div.select_one("span")
        val = div.select_one("p")
        if span and val and span.text.strip() == label:
            return val.text.strip()
    return ""


def scrape_activities():
    items = []
    page = 1
    while True:
        url = f"{BASE}/index.php?action=activity" + (f"&p={page}" if page > 1 else "")
        soup = get_soup(url)
        rows = soup.select("div.activityListItem")
        if not rows:
            break

        for row in rows:
            link_el = row.select_one("a[href*='activity_detail']")
            title_el = row.select_one("p.title")
            des_el = row.select_one("div.des p")

            if not link_el or not title_el:
                continue

            href = link_el["href"]
            if not href.startswith("http"):
                href = BASE + "/" + href.lstrip("/")

            id_match = re.search(r"id=(\d+)", href)
            item_id = f"sumroc-act-{id_match.group(1)}" if id_match else f"sumroc-act-{len(items)}"

            date_raw = get_info(row, "時間")
            date_start, date_end = parse_date_range(date_raw)

            items.append({
                "id": item_id,
                "type": "activity",
                "title": title_el.text.strip(),
                "url": href,
                "location": des_el.text.strip() if des_el else "",
                "organizer": get_info(row, "主辦"),
                "credits": get_info(row, "積分"),
                "date_raw": date_raw,
                "date_start": date_start,
                "date_end": date_end,
                "can_register": bool(row.select_one("a.hasSeat")),
                "source_id": "sumroc",
                "source_name": "中華民國醫用超音波學會",
            })

        if not soup.select_one(f"a.pageBtn[href*='p={page + 1}']"):
            break
        page += 1
        time.sleep(0.5)

    return items


def scrape_news():
    items = []
    seen_ids = set()
    categories = {"1": "學會公告", "5": "講習課程", "6": "研討會"}

    for cid, cat_name in categories.items():
        page = 1
        while True:
            url = f"{BASE}/index.php?action=news&cid={cid}" + (f"&p={page}" if page > 1 else "")
            soup = get_soup(url)

            for link in soup.select("a[href*='news_detail']"):
                title = link.text.strip()
                if not title or len(title) < 4:
                    continue

                href = link["href"]
                if not href.startswith("http"):
                    href = BASE + "/" + href.lstrip("/")

                id_match = re.search(r"id=(\d+)", href)
                item_id = f"sumroc-news-{id_match.group(1)}" if id_match else None
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                # Try to find a nearby date
                date_str = ""
                for el in [link.parent, link.parent.parent if link.parent else None]:
                    if el:
                        m = re.search(r"(\d{4}[.\-]\d{2}[.\-]\d{2})", el.get_text())
                        if m:
                            date_str = m.group(1).replace(".", "-")
                            break

                items.append({
                    "id": item_id,
                    "type": "news",
                    "category": cat_name,
                    "title": title,
                    "url": href,
                    "date_raw": date_str,
                    "date_start": date_str,
                    "date_end": date_str,
                    "source_id": "sumroc",
                    "source_name": "中華民國醫用超音波學會",
                })

            if not soup.select_one(f"a.pageBtn[href*='p={page + 1}']"):
                break
            page += 1
            time.sleep(0.5)

    return items


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)

    print("Scraping SUMROC activities...")
    activities = scrape_activities()
    print(f"  ✓ {len(activities)} activities")

    print("Scraping SUMROC news...")
    news = scrape_news()
    print(f"  ✓ {len(news)} news items")

    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sources": SOURCES,
        "items": activities + news,
    }

    with open("data/sumroc.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Done. {len(activities) + len(news)} total items → data/sumroc.json")
