import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PMR-Radar/1.0; +https://github.com/alice870902/pmr-radar)"
}
MAX_PAGES = 3  # 每個來源最多抓幾頁（夠涵蓋近期活動）

ALL_SOURCES = [
    {"id": "sumroc",   "name": "中華民國醫用超音波學會",  "url": "https://www.sumroc.org.tw"},
    {"id": "pmr",      "name": "台灣復健醫學會",           "url": "https://www.pmr.org.tw"},
    {"id": "tapedpmr", "name": "台灣兒童復健醫學會",       "url": "https://www.tapedpmr.org.tw"},
    {"id": "tsnr",     "name": "台灣神經復健醫學會",        "url": "https://www.tsnr.org.tw"},
    {"id": "tpta",     "name": "台灣物理治療學會",          "url": "https://www.tpta.org.tw"},
]


def get_soup(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    return BeautifulSoup(resp.text, "lxml")


def parse_date_range(raw):
    """Return (date_start, date_end) as YYYY-MM-DD strings."""
    if not raw:
        return "", ""
    raw = raw.strip()

    # Helper: extract first full Western date from a string
    def _western(s):
        m = re.search(r"(\d{4})[./](\d{1,2})[./](\d{1,2})", s)
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""

    # Helper: extract first Chinese date from a string
    def _chinese(s):
        m = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", s)
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""

    # Split on range separator first
    if "~" in raw or "～" in raw:
        parts = re.split(r"[~～]", raw, maxsplit=1)
        s_raw, e_raw = parts[0].strip(), parts[1].strip()

        start = _chinese(s_raw) or _western(s_raw)
        if not start:
            return raw, raw

        # Try full date in end part first
        end = _chinese(e_raw) or _western(e_raw)
        if not end:
            # Try month.day  (e.g., "11.01" = Nov 1)
            m2 = re.match(r"(\d{1,2})[./](\d{1,2})", e_raw)
            if m2:
                year = start.split("-")[0]
                end = f"{year}-{int(m2.group(1)):02d}-{int(m2.group(2)):02d}"
            else:
                # Just a day number, possibly trailed by text (e.g., "20日，共三天")
                dm = re.match(r"(\d{1,2})", e_raw)
                if dm:
                    ym = "-".join(start.split("-")[:2])
                    end = f"{ym}-{int(dm.group(1)):02d}"
                else:
                    end = start

        return start, end

    # No range — try Chinese, then Western
    d = _chinese(raw) or _western(raw)
    return (d, d) if d else (raw, raw)


def make_item(source_id, source_name, type_, title, url, date_raw="",
              location="", organizer="", credits="", can_register=False, **kw):
    date_start, date_end = parse_date_range(date_raw)
    id_match = (
        re.search(r"[?&](?:id|getId|pid)=(\w+)", url) or  # ?id=123, &pid=456
        re.search(r"\?/(\d+)\.html", url) or              # ?/228.html
        re.search(r"/(\d+)\.html", url)                   # /4441.html
    )
    item_id = f"{source_id}-{id_match.group(1) if id_match else abs(hash(url)) % 999999}"
    return {
        "id": item_id,
        "type": type_,
        "title": title.strip(),
        "url": url,
        "location": location.strip(),
        "organizer": organizer.strip(),
        "credits": credits.strip(),
        "date_raw": date_raw,
        "date_start": date_start,
        "date_end": date_end,
        "can_register": can_register,
        "source_id": source_id,
        "source_name": source_name,
    }


# ─── SUMROC ──────────────────────────────────────────────────────────────────

def get_info(item, label):
    for div in item.select("div.info"):
        span = div.select_one("span")
        val = div.select_one("p")
        if span and val and span.text.strip() == label:
            return val.text.strip()
    return ""


def scrape_sumroc():
    BASE = "https://www.sumroc.org.tw"
    items, seen = [], set()
    for page in range(1, MAX_PAGES + 2):
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
            if href in seen:
                continue
            seen.add(href)
            items.append(make_item(
                "sumroc", "中華民國醫用超音波學會", "activity",
                title_el.text, href,
                date_raw=get_info(row, "時間"),
                location=(des_el.text if des_el else ""),
                organizer=get_info(row, "主辦"),
                credits=get_info(row, "積分"),
                can_register=bool(row.select_one("a.hasSeat")),
            ))
        if not soup.select_one(f"a.pageBtn[href*='p={page + 1}']"):
            break
        time.sleep(0.3)

    # News
    for cid, cat in [("1", "學會公告"), ("5", "講習課程")]:
        for page in range(1, 3):
            url = f"{BASE}/index.php?action=news&cid={cid}" + (f"&p={page}" if page > 1 else "")
            soup = get_soup(url)
            for link in soup.select("a[href*='news_detail']"):
                title = link.text.strip()
                if not title or len(title) < 4:
                    continue
                href = link["href"]
                if not href.startswith("http"):
                    href = BASE + "/" + href.lstrip("/")
                if href in seen:
                    continue
                seen.add(href)
                date_m = re.search(r"(\d{4}[.\-]\d{2}[.\-]\d{2})", link.parent.get_text())
                date_str = date_m.group(1).replace(".", "-") if date_m else ""
                items.append(make_item(
                    "sumroc", "中華民國醫用超音波學會", "news",
                    title, href, date_raw=date_str,
                ))
            if not soup.select_one(f"a.pageBtn[href*='p={page + 1}']"):
                break
            time.sleep(0.3)
    return items


# ─── PMR ─────────────────────────────────────────────────────────────────────

def scrape_pmr():
    BASE = "https://www.pmr.org.tw"
    items, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        url = (f"{BASE}/active_news/active.asp" if page == 1
               else f"{BASE}/active_news/active.asp?/{page}.html")
        soup = get_soup(url)
        # Each activity is a <ul> inside div.list that has li.text-dateO
        for ul in soup.select("div.activelist div.list > ul"):
            date_li = ul.select_one("li.text-dateO")
            if not date_li:
                continue
            date_raw = re.sub(r"日期[：:]?\s*", "", date_li.get_text()).strip()
            content_li = ul.select("li")[1] if len(ul.select("li")) > 1 else None
            if not content_li:
                continue
            link_el = content_li.select_one("a")
            if not link_el:
                continue
            href = link_el["href"]
            if not href.startswith("http"):
                href = BASE + "/" + href.lstrip("/")
            if href in seen:
                continue
            seen.add(href)
            # organizer and location are in <div> inside content_li
            divs = content_li.select("div")
            organizer = re.sub(r"主辦[：:]?\s*", "", divs[0].get_text()).strip() if divs else ""
            location  = re.sub(r"地點[：:]?\s*", "", divs[1].get_text()).strip() if len(divs) > 1 else ""
            items.append(make_item(
                "pmr", "台灣復健醫學會", "activity",
                link_el.text, href,
                date_raw=date_raw,
                organizer=organizer,
                location=location,
            ))
        next_link = soup.select_one(f"div.scott a[href*='/{page + 1}.html']")
        if not next_link:
            break
        time.sleep(0.3)
    return items


# ─── TAPEDPMR ────────────────────────────────────────────────────────────────

def scrape_tapedpmr():
    BASE = "https://www.tapedpmr.org.tw"
    items, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        url = (f"{BASE}/activity/index.asp" if page == 1
               else f"{BASE}/activity/index.asp?/{page}.html")
        soup = get_soup(url)
        for ul in soup.select("ul.list_td"):
            date_li = ul.select_one("li.w15p_lg")
            title_li = ul.select_one("li.w85p_lg")
            if not date_li or not title_li:
                continue
            date_raw = re.sub(r"活動日期[：:]?\s*", "", date_li.get_text()).strip()
            link_el = title_li.select_one("a")
            if not link_el:
                continue
            href = link_el["href"]
            if not href.startswith("http"):
                href = BASE + "/" + href.lstrip("/")
            if href in seen:
                continue
            seen.add(href)
            title = re.sub(r"活動標題[：:]?\s*", "", title_li.get_text()).strip()
            items.append(make_item(
                "tapedpmr", "台灣兒童復健醫學會", "activity",
                title, href, date_raw=date_raw,
            ))
        next_link = soup.select_one(f"div.scott a[href*='/{page + 1}.html']")
        if not next_link:
            break
        time.sleep(0.3)
    return items


# ─── TSNR ────────────────────────────────────────────────────────────────────

def scrape_tsnr():
    BASE = "https://www.tsnr.org.tw"
    items, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        url = (f"{BASE}/education.aspx" if page == 1
               else f"{BASE}/education.aspx?page={page}")
        soup = get_soup(url)
        for li in soup.select("#products ul li.clearfix"):
            link_el = li.select_one("a[href*='showeducation']")
            title_el = li.select_one("h5")
            date_el = li.select_one("small")
            if not link_el or not title_el:
                continue
            href = link_el["href"]
            if not href.startswith("http"):
                href = BASE + "/" + href.lstrip("/")
            if href in seen:
                continue
            seen.add(href)
            date_raw = date_el.text.strip() if date_el else ""
            # date_el text looks like "2026-08-01"
            desc_el = li.select_one("p")
            desc = desc_el.text.strip()[:200] if desc_el else ""
            items.append(make_item(
                "tsnr", "台灣神經復健醫學會", "activity",
                title_el.text, href,
                date_raw=date_raw,
                location=desc,
                organizer="台灣神經復健醫學會",
            ))
        next_link = soup.select_one(f"a.page-link[href*='page={page + 1}']")
        if not next_link:
            break
        time.sleep(0.3)
    return items


# ─── TPTA ────────────────────────────────────────────────────────────────────

def scrape_tpta():
    BASE = "https://www.tpta.org.tw"
    items, seen = [], set()
    url = f"{BASE}/articles.php?type=courses"
    soup = get_soup(url)
    for entry in soup.select("div.entry_c"):
        link_el = entry.select_one("div.entry_title a")
        if not link_el:
            continue
        href = link_el["href"]
        if not href.startswith("http"):
            href = BASE + "/" + href.lstrip("/")
        if href in seen:
            continue
        seen.add(href)
        title = link_el.text.strip()
        # Remove prefix like "(PT11556) "
        title = re.sub(r"^\([A-Z]+\d+\)\s*", "", title)

        meta_items = entry.select("ul.entry_meta li")
        location = meta_items[0].get_text(strip=True) if len(meta_items) > 0 else ""
        date_raw  = meta_items[1].get_text(strip=True).lstrip("/").strip() if len(meta_items) > 1 else ""
        credits   = meta_items[2].get_text(strip=True).lstrip("/").strip() if len(meta_items) > 2 else ""
        items.append(make_item(
            "tpta", "台灣物理治療學會", "activity",
            title, href,
            date_raw=date_raw,
            location=location,
            organizer="台灣物理治療學會",
            credits=re.sub(r"積分點數\s*[:：]\s*", "", credits),
        ))
    return items


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    all_items = []

    for fn, label in [
        (scrape_sumroc,   "SUMROC（超音波）"),
        (scrape_pmr,      "PMR（台灣復健醫學會）"),
        (scrape_tapedpmr, "TAPEDPMR（兒童復健）"),
        (scrape_tsnr,     "TSNR（神經復健）"),
        (scrape_tpta,     "TPTA（物理治療）"),
    ]:
        print(f"Scraping {label}...")
        try:
            items = fn()
            print(f"  ✓ {len(items)} items")
            all_items.extend(items)
        except Exception as e:
            print(f"  ✗ Error: {e}")

    # Deduplicate by id
    seen_ids, unique = set(), []
    for item in all_items:
        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            unique.append(item)

    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sources": ALL_SOURCES,
        "items": unique,
    }

    with open("data/sumroc.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(unique)} total items → data/sumroc.json")
