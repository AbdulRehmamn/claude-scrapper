#!/usr/bin/env python3
"""
Generic Directory Scraper
Works on any domain that permits crawling (checks robots.txt automatically).
Includes legitimate Yelp Fusion API support instead of scraping Yelp directly.
"""

import re
import csv
import time
import random
import argparse
import urllib.robotparser
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PHONE_REGEX = re.compile(r'(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
                  "DirectoryScraperBot/1.0 (+contact: your-email@example.com)",
    "Accept-Language": "en-US,en;q=0.9",
}

NAME_TAG_CANDIDATES = ["h1", "h2", "h3", "h4", "a"]
LISTING_HINTS = ["result", "listing", "company", "profile", "card", "member", "search-result", "list-item", "business"]

_driver = None
_robots_cache = {}


# ---------------------------------------------------------------------------
# Robots.txt compliance (non-negotiable safety layer)
# ---------------------------------------------------------------------------

def is_allowed(url, user_agent="*"):
    """Checks robots.txt for the domain. Caches parser per-domain."""
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    if domain not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(urljoin(domain, "/robots.txt"))
        try:
            rp.read()
        except Exception:
            # If robots.txt can't be read, default to cautious: allow (standard behavior)
            # but log it so the user is aware.
            print(f"[i] Could not read robots.txt for {domain}, proceeding cautiously.")
        _robots_cache[domain] = rp

    rp = _robots_cache[domain]
    try:
        allowed = rp.can_fetch(user_agent, url)
    except Exception:
        allowed = True
    return allowed


def get_crawl_delay(url, user_agent="*"):
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(domain)
    if rp:
        delay = rp.crawl_delay(user_agent)
        if delay:
            return float(delay)
    return None


# ---------------------------------------------------------------------------
# Fetching (requests -> Selenium fallback)
# ---------------------------------------------------------------------------

def get_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch_with_requests(session, url, timeout=15):
    print(f"    [>] Fetching (requests): {url}")
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"    [!] requests failed for {url}: {e}")
        return None


def get_driver():
    global _driver
    if _driver is None:
        if not SELENIUM_AVAILABLE:
            raise RuntimeError("Selenium not installed. Run: pip install selenium webdriver-manager")
        print("    [>] Launching headless Chrome (first run may take 10-30s to download chromedriver)...")
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(f"user-agent={HEADERS['User-Agent']}")
        options.add_argument("--log-level=3")
        service = Service(ChromeDriverManager().install())
        _driver = webdriver.Chrome(service=service, options=options)
        print("    [✓] Chrome driver ready.")
    return _driver


def fetch_with_selenium(url, wait=3):
    print(f"    [>] Fetching (selenium): {url}")
    try:
        driver = get_driver()
        driver.get(url)
        time.sleep(wait)
        print(f"    [✓] Page loaded ({len(driver.page_source)} bytes).")
        return driver.page_source
    except Exception as e:
        print(f"    [!] Selenium failed for {url}: {e}")
        return None


def looks_empty(html):
    if not html:
        return True
    soup = BeautifulSoup(html, "lxml")
    return len(soup.get_text(strip=True)) < 200


def auto_fetch(session, url, user_agent_token="*"):
    """Checks robots.txt, then auto-detects whether JS rendering is needed."""
    if not is_allowed(url, user_agent_token):
        print(f"    [x] BLOCKED by robots.txt: {url}  (skipping — this site disallows crawling this path)")
        return None

    html = fetch_with_requests(session, url)
    if looks_empty(html):
        if SELENIUM_AVAILABLE:
            print("    [i] Page looks JS-rendered or empty, switching to Selenium...")
            html = fetch_with_selenium(url)
        else:
            print("    [!] Page looks empty but Selenium is not installed. Install it for full support.")
    return html


# ---------------------------------------------------------------------------
# Generic extraction
# ---------------------------------------------------------------------------

def extract_email_from_text(text):
    matches = [m for m in EMAIL_REGEX.findall(text)
               if not m.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
    return matches[0] if matches else ""


def extract_phone_from_text(text):
    m = PHONE_REGEX.search(text)
    return m.group(0).strip() if m else ""


def extract_email_from_soup(soup):
    mailto = soup.select_one('a[href^="mailto:"]')
    if mailto:
        return mailto.get("href").replace("mailto:", "").split("?")[0].strip()
    return extract_email_from_text(soup.get_text(" ", strip=True))


def extract_phone_from_soup(soup):
    tel = soup.select_one('a[href^="tel:"]')
    if tel:
        return tel.get("href").replace("tel:", "").strip()
    return extract_phone_from_text(soup.get_text(" ", strip=True))


def guess_name(block):
    for tag in NAME_TAG_CANDIDATES:
        el = block.find(tag)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return ""


def find_listing_blocks(soup):
    candidates, seen, unique = [], set(), []
    for hint in LISTING_HINTS:
        candidates.extend(soup.find_all(attrs={"class": re.compile(hint, re.I)}))
    for c in candidates:
        if id(c) not in seen:
            seen.add(id(c))
            unique.append(c)
    return unique


def find_detail_links(soup, base_url):
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if any(k in href for k in ["profile", "company", "contractor", "supplier", "detail", "member", "biz"]):
            links.add(urljoin(base_url, a["href"]))
    return list(links)


def find_next_page_url(soup, current_url):
    next_link = soup.find("a", rel="next")
    if next_link and next_link.get("href"):
        return urljoin(current_url, next_link["href"])

    for a in soup.find_all("a", href=True):
        if a.get_text(strip=True).lower() in ("next", "next >", "next page", "»", ">", ">>"):
            return urljoin(current_url, a["href"])

    pagination = soup.find(attrs={"class": re.compile("pag(ination|er)", re.I)})
    if pagination:
        active = pagination.find(attrs={"class": re.compile("active|current|selected", re.I)})
        if active:
            nxt = active.find_next("a", href=True)
            if nxt:
                return urljoin(current_url, nxt["href"])

    parsed = urlparse(current_url)
    qs = parse_qs(parsed.query)
    for key in ("page", "pg", "p"):
        if key in qs:
            try:
                qs[key] = [str(int(qs[key][0]) + 1)]
                return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
            except ValueError:
                pass
    return None


# ---------------------------------------------------------------------------
# Yelp — via official Fusion API (legitimate, no scraping/bypass involved)
# ---------------------------------------------------------------------------

def scrape_yelp_api(term, location, api_key, limit=50, output="results.csv"):
    """
    Uses Yelp's official Fusion API. Requires a free API key from:
    https://www.yelp.com/developers/v3/manage_app
    """
    url = "https://api.yelp.com/v3/businesses/search"
    headers = {"Authorization": f"Bearer {api_key}"}
    all_results = []
    offset = 0
    page_size = 50

    f = open(output, "w", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(f, fieldnames=["Name", "Phone", "Email", "Source URL"])
    writer.writeheader()

    try:
        while len(all_results) < limit:
            params = {"term": term, "location": location, "limit": min(page_size, limit - len(all_results)), "offset": offset}
            print(f"    [>] Querying Yelp API: term='{term}' location='{location}' offset={offset}")
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            if resp.status_code != 200:
                print(f"    [!] Yelp API error {resp.status_code}: {resp.text}")
                break
            data = resp.json()
            businesses = data.get("businesses", [])
            if not businesses:
                print("    [i] No more results.")
                break

            for b in businesses:
                row = {
                    "Name": b.get("name", ""),
                    "Phone": b.get("display_phone", ""),
                    "Email": "",  # Yelp API does not expose business emails (by design/privacy)
                    "Source URL": b.get("url", ""),
                }
                all_results.append(row)
                writer.writerow(row)
                print(f"    -> {row['Name']} | {row['Phone']}")

            offset += len(businesses)
            f.flush()
            time.sleep(0.5)
    finally:
        f.close()

    print(f"\n✅ Done. {len(all_results)} records saved to {output}")
    print("[i] Note: Yelp's public API does not provide business emails (they don't expose this data to anyone, including their own site's scrapers).")
    return all_results


# ---------------------------------------------------------------------------
# Generic site crawler (works on any domain that allows it via robots.txt)
# ---------------------------------------------------------------------------

def scrape(start_url, max_pages=0, delay=1.5, output="results.csv", visit_details=True):
    domain = urlparse(start_url).netloc
    print(f"[i] Target domain: {domain}")
    print(f"[i] Checking robots.txt for crawl permissions...")

    if not is_allowed(start_url):
        print(f"\n[x] This site's robots.txt disallows automated crawling of this URL.")
        print(f"    URL: {start_url}")
        print(f"    This tool will not proceed against the site's stated policy.")
        print(f"    Options:")
        print(f"      1. Check if {domain} offers an official API or data export.")
        print(f"      2. Contact the site owner for permission/data access.")
        print(f"      3. Try a different starting URL/path that robots.txt does allow.")
        return []

    crawl_delay = get_crawl_delay(start_url)
    if crawl_delay:
        print(f"[i] robots.txt specifies a crawl-delay of {crawl_delay}s — respecting it.")
        delay = max(delay, crawl_delay)

    session = get_session()
    visited_pages, visited_details, all_results = set(), set(), []
    current_url = start_url
    page_count = 0

    f = open(output, "w", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(f, fieldnames=["Name", "Phone", "Email", "Source URL"])
    writer.writeheader()

    try:
        while current_url and current_url not in visited_pages:
            page_count += 1
            print(f"\n=== Page {page_count}: {current_url} ===")
            visited_pages.add(current_url)

            html = auto_fetch(session, current_url)
            if not html:
                print("[!] Could not retrieve page (blocked or failed), stopping.")
                break

            soup = BeautifulSoup(html, "lxml")
            page_results = []

            blocks = find_listing_blocks(soup)
            print(f"    [i] Found {len(blocks)} potential listing blocks on this page.")

            for block in blocks:
                name = guess_name(block)
                phone = extract_phone_from_soup(block)
                email = extract_email_from_soup(block)
                if name or phone or email:
                    page_results.append({"Name": name, "Phone": phone, "Email": email, "Source URL": current_url})

            if visit_details:
                detail_links = find_detail_links(soup, current_url)
                new_links = [l for l in detail_links if l not in visited_details]
                print(f"    [i] Found {len(detail_links)} detail links ({len(new_links)} new).")

                for idx, link in enumerate(new_links, 1):
                    visited_details.add(link)
                    if not is_allowed(link):
                        print(f"    [x] Skipping (robots.txt disallows): {link}")
                        continue
                    print(f"    [{idx}/{len(new_links)}] Visiting detail page...")
                    time.sleep(delay + random.uniform(0, 0.7))
                    d_html = auto_fetch(session, link)
                    if not d_html:
                        continue
                    d_soup = BeautifulSoup(d_html, "lxml")
                    name = guess_name(d_soup) or (d_soup.title.get_text(strip=True) if d_soup.title else "")
                    phone = extract_phone_from_soup(d_soup)
                    email = extract_email_from_soup(d_soup)
                    if name or phone or email:
                        page_results.append({"Name": name, "Phone": phone, "Email": email, "Source URL": link})

            new_count = 0
            existing_sigs = {(x["Name"], x["Phone"], x["Email"]) for x in all_results}
            for r in page_results:
                sig = (r["Name"], r["Phone"], r["Email"])
                if sig not in existing_sigs:
                    all_results.append(r)
                    existing_sigs.add(sig)
                    writer.writerow(r)
                    f.flush()
                    new_count += 1
                    print(f"    -> {r['Name']} | {r['Phone']} | {r['Email']}")

            print(f"    [✓] Page {page_count} complete. {new_count} new records added (total: {len(all_results)}).")

            if max_pages and page_count >= max_pages:
                print("[i] Reached max page limit.")
                break

            next_url = find_next_page_url(soup, current_url)
            if not next_url or next_url == current_url:
                print("[i] No further pages detected. Done.")
                break

            if not is_allowed(next_url):
                print(f"[x] Next page blocked by robots.txt, stopping: {next_url}")
                break

            current_url = next_url
            time.sleep(delay + random.uniform(0, 1))
    finally:
        f.close()
        if _driver:
            print("[i] Closing browser...")
            _driver.quit()

    print(f"\n✅ Done. {len(all_results)} records saved to {output}")
    return all_results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generic directory scraper (robots.txt-compliant) with Yelp API support")
    parser.add_argument("--mode", choices=["site", "yelp"], help="'site' = generic URL crawl, 'yelp' = Yelp Fusion API search")
    parser.add_argument("--url", help="Starting URL (for --mode site)")
    parser.add_argument("--pages", type=int, default=0, help="Max pages (0 = auto-detect all)")
    parser.add_argument("--output", default="results.csv")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--no-details", action="store_true")
    parser.add_argument("--yelp-key", help="Yelp Fusion API key")
    parser.add_argument("--yelp-term", help="Search term, e.g. 'contractors'")
    parser.add_argument("--yelp-location", help="Location, e.g. 'Chicago, IL'")
    parser.add_argument("--yelp-limit", type=int, default=50)
    args = parser.parse_args()

    mode = args.mode
    if not mode:
        print("Choose data source:")
        print("  1. Any website URL (generic crawler, respects robots.txt)")
        print("  2. Yelp (via official Yelp Fusion API)")
        choice = input("Enter 1 or 2: ").strip()
        mode = "yelp" if choice == "2" else "site"

    if mode == "yelp":
        api_key = args.yelp_key or input("Enter your Yelp Fusion API key (get one free at yelp.com/developers): ").strip()
        term = args.yelp_term or input("Search term (e.g. 'contractors', 'plumbers'): ").strip()
        location = args.yelp_location or input("Location (e.g. 'Chicago, IL'): ").strip()
        scrape_yelp_api(term, location, api_key, args.yelp_limit, args.output)
    else:
        url = args.url or input("Enter the URL to scrape: ").strip()
        scrape(url, args.pages, args.delay, args.output, not args.no_details)


if __name__ == "__main__":
    main()