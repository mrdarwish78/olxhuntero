"""
Egyptian Used Phone Market Hunter
Self-contained scraper + AI evaluator + Telegram alerter.
"""
import csv
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

import cloudscraper
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

DUBIZZLE_URL = (
    "https://www.dubizzle.com.eg/en/mobile-phones-tablets-accessories-numbers/"
    "mobile-phones/cairo/?filter=price_between_5000_to_30000%2Cpurpose_eq_1"
)
PROCESSED_IDS_FILE = "processed_ids.txt"
SYSTEM_LOGS_FILE = "system_logs.csv"
MARKET_DB_FILE = "market_database.csv"
EGYPT_OFFSET = timedelta(hours=3)
MAX_RETRIES = 3

# â"€â"€ Logging â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def log(level, event, detail=""):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts},{level},{event},{detail}"
    try:
        print(line)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((line + "\n").encode("utf-8", errors="replace"))
    try:
        with open(SYSTEM_LOGS_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass

# â"€â"€ Scraping â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def scrape_listings(url):
    scraper = cloudscraper.create_scraper(
        delay=random.uniform(2, 4),
        browser={
            "browser": "chrome",
            "platform": "windows",
            "mobile": False,
        },
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = scraper.get(url, headers=headers, timeout=60)
            if resp.status_code == 200:
                log("INFO", "SCRAPE_OK", f"status=200 size={len(resp.text)}")
                return resp.text
            log("WARN", "SCRAPE_FAIL", f"attempt={attempt} status={resp.status_code}")
        except Exception as e:
            log("WARN", "SCRAPE_ERR", f"attempt={attempt} err={str(e)[:80]}")
        if attempt < MAX_RETRIES:
            time.sleep(random.uniform(10, 20))
    log("ERROR", "SCRAPE_EXHAUSTED", "all retries failed")
    return None

# â"€â"€ HTML Parsing (hybrid) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def _text(el):
    return el.get_text(strip=True) if el else ""

def _extract_price_value(price_text):
    digits = re.sub(r"[^\d]", "", price_text.split("EGP")[-1] if "EGP" in price_text else price_text)
    return int(digits) if digits else 0

def _parse_relative_minutes(text):
    m = re.search(r"(\d+)\s*(minute|minutes|hour|hours|day|days|week|weeks)\s*ago", text, re.IGNORECASE)
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("minute"):
        return val
    if unit.startswith("hour"):
        return val * 60
    if unit.startswith("day"):
        return val * 1440
    if unit.startswith("week"):
        return val * 10080
    return None

def _extract_ad_id(url):
    m = re.search(r"-ID(\d+)", url)
    return m.group(1) if m else ""

def _build_ad_id(link_el, title, price):
    if link_el:
        aid = _extract_ad_id(link_el["href"])
        if aid:
            return aid
    return hashlib.md5(f"{title}|{price}".encode()).hexdigest()[:12]

def _parse_via_classes(soup):
    cards = soup.find_all(class_="_23f16658")
    if not cards:
        return None
    ads = []
    for card in cards:
        title_el = card.find(class_="_802d99a1")
        price_el = card.find(class_="_7961d5a8")
        time_el = card.find(attrs={"aria-label": "Creation date"})
        link_el = None
        article = card.find_parent("article")
        if article:
            link_el = article.find("a", href=re.compile(r"/en/ad/"))
        if not link_el:
            link_el = card.find("a", href=True)
        title = _text(title_el)
        price = _text(price_el)
        if not title or not price:
            continue
        posted_text = _text(time_el)
        if not posted_text:
            card_text = card.get_text()
            tm = re.search(r"â€¢\s*\d+\s*(minute|minutes|hour|hours|day|days)\s*ago", card_text)
            if tm:
                posted_text = tm.group(0).strip("â€¢ ").strip()
        url = ""
        if link_el:
            href = link_el["href"]
            url = href if href.startswith("http") else "https://www.dubizzle.com.eg" + href
        ads.append({
            "id": _build_ad_id(link_el, title, price),
            "title": title,
            "price": price,
            "price_value": _extract_price_value(price),
            "posted_text": posted_text,
            "url": url,
        })
    return ads if ads else None

def _parse_via_structure(soup):
    ads = []
    for li in soup.find_all("li"):
        link = li.find("a", href=re.compile(r"/en/ad/"))
        if not link:
            continue
        title_el = li.find("h2")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue
        price_text = ""
        price_el = li.find(string=re.compile(r"EGP"))
        if price_el:
            price_text = price_el.strip()
        elif li.find(class_=re.compile(r"price", re.I)):
            price_text = li.find(class_=re.compile(r"price", re.I)).get_text(strip=True)
        else:
            for span in li.find_all("span"):
                txt = span.get_text(strip=True)
                if "EGP" in txt:
                    price_text = txt
                    break
        if not price_text:
            continue
        text_content = li.get_text()
        time_match = re.search(r"â€¢\s*\d+\s*(minute|minutes|hour|hours|day|days)\s*ago", text_content)
        posted_text = time_match.group(0).strip("â€¢ ").strip() if time_match else ""
        href = link["href"]
        full_url = href if href.startswith("http") else "https://www.dubizzle.com.eg" + href
        aid = _extract_ad_id(href)
        if not aid:
            aid = hashlib.md5(f"{title}|{price_text}".encode()).hexdigest()[:12]
        ads.append({
            "id": aid,
            "title": title,
            "price": price_text,
            "price_value": _extract_price_value(price_text),
            "posted_text": posted_text,
            "url": full_url,
        })
    return ads if ads else None

def _parse_via_regex(html):
    ads = []
    blocks = re.split(r'<li[^>]*class="[^"]*"[^>]*>', html)
    if len(blocks) < 2:
        blocks = re.split(r'<div[^>]*class="[^"]*"[^>]*>', html)
    for block in blocks:
        title_m = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.DOTALL)
        price_m = re.search(r'EGP\s*[\d,]+', block)
        time_m = re.search(r'â€¢\s*\d+\s*(minute|minutes|hour|hours|day|days)\s*ago', block)
        url_m = re.search(r'href="(/en/ad/[^"]+)"', block)
        if not title_m or not price_m:
            continue
        title = BeautifulSoup(title_m.group(1), "html.parser").get_text(strip=True)
        href = url_m.group(1) if url_m else ""
        ads.append({
            "id": _extract_ad_id(href),
            "title": title,
            "price": price_m.group(0),
            "price_value": _extract_price_value(price_m.group(0)),
            "posted_text": time_m.group(0).strip("â€¢ ").strip() if time_m else "",
            "url": "https://www.dubizzle.com.eg" + href if href else "",
        })
    return ads

def parse_listings(html):
    soup = BeautifulSoup(html, "html.parser")
    ads = _parse_via_classes(soup)
    if ads:
        log("INFO", "PARSE_METHOD", "classes")
    else:
        ads = _parse_via_structure(soup)
        if ads:
            log("INFO", "PARSE_METHOD", "structure")
        else:
            ads = _parse_via_regex(html)
            log("INFO", "PARSE_METHOD", "regex")
    log("INFO", "PARSE_OK", f"total_ads={len(ads)}")
    return ads

# â"€â"€ Time Filter â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def is_within_target_window(posted_text, bulk_mode):
    mins = _parse_relative_minutes(posted_text)
    if mins is None:
        return False
    limit = 240 if bulk_mode else 60
    return mins <= limit

# â"€â"€ Dedup â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def load_processed_ids():
    if not os.path.isfile(PROCESSED_IDS_FILE):
        return set()
    try:
        with open(PROCESSED_IDS_FILE, "r") as f:
            return {line.strip() for line in f if line.strip()}
    except OSError:
        return set()

def filter_new_ads(ads, processed_ids):
    new_ads = [a for a in ads if a["id"] and a["id"] not in processed_ids]
    log("INFO", "FILTER_OK", f"new={len(new_ads)} total_seen={len(processed_ids)}")
    return new_ads

# â"€â"€ Gemini AI Evaluation â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

EVALUATION_PROMPT = """You are a used phone market expert for Egypt. 
Analyze each listing and use Google Search to find current real market prices in EGP.

Return ONLY a valid JSON array. Each item:
{"phone": "normalized model name",
 "price": "price as written",
 "classification": "ðŸ"¥ Ù„Ù‚Ø·Ø©"|"ðŸš¨ Ù†ØµØ¨"|"âœ… Ø¹Ø§Ø¯Ù„"|"âŒ Ù…Ø¨Ø§Ù„Øº ÙÙŠÙ‡"|"âš ï¸ Ù…ØµÙŠØ¯Ø©",
 "range": "minâ€"max EGP" or "Ù…Ø´ Ù…ØªÙˆÙØ±",
 "diff_percent": "+-% over market",
 "action": "exactly 5 words in Arabic",
 "risk_factor": "risk description in Arabic"}

Rules:
- If price < 50% of market min â†’ "ðŸš¨ Ù†ØµØ¨"
- If price <= market min and >= 50% of market min â†’ "ðŸ"¥ Ù„Ù‚Ø·Ø©"
- If price within market range â†’ "âœ… Ø¹Ø§Ø¯Ù„"
- If price > market max + 15% â†’ "âŒ Ù…Ø¨Ø§Ù„Øº ÙÙŠÙ‡"
- If model is End-of-Life and overpriced â†’ "âš ï¸ Ù…ØµÙŠØ¯Ø©"
- "action" must be exactly 5 Arabic words
- If market data unavailable, use "Ù…Ø´ Ù…ØªÙˆÙØ±" for range and "âœ… Ø¹Ø§Ø¯Ù„" default

Listings:
"""

def evaluate_with_gemini(client, ads):
    if not ads:
        return []
    listings_json = json.dumps([{
        "title": a["title"],
        "price": a["price"],
        "price_value": a["price_value"],
    } for a in ads], ensure_ascii=False)
    prompt = EVALUATION_PROMPT + listings_json
    models_to_try = ["gemini-2.5-flash"]
    for attempt in range(1, MAX_RETRIES + 1):
        model = models_to_try[min(attempt - 1, len(models_to_try) - 1)]
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0] if "```" in text else text
            result = json.loads(text.strip())
            if isinstance(result, dict):
                result = [result]
            log("INFO", "GEMINI_OK", f"evaluated={len(result)}")
            return result
        except json.JSONDecodeError:
            log("WARN", "GEMINI_JSON_ERR", f"attempt={attempt} model={model}")
        except Exception as e:
            log("WARN", "GEMINI_ERR", f"attempt={attempt} model={model} err={str(e)[:100]}")
        if attempt < MAX_RETRIES:
            time.sleep(3)
    log("ERROR", "GEMINI_FAIL", "all retries exhausted")
    return []

# â"€â"€ Telegram Alert â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def send_telegram(message, ad_url=""):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log("WARN", "TELEGRAM_SKIP", "token or chat_id missing")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }
    if ad_url:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": "ÙŠÙ„Ø§ Ù†Ø´ÙˆÙ", "url": ad_url}]]}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            import requests
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                log("INFO", "TELEGRAM_OK", "")
                return True
            log("WARN", "TELEGRAM_FAIL", f"status={resp.status_code}")
        except Exception as e:
            log("WARN", "TELEGRAM_ERR", f"attempt={attempt} err={e}")
        if attempt < MAX_RETRIES:
            time.sleep(2)
    return False

def format_alert(ad, ev):
    lines = [
        f"<b>{ev.get('classification', 'ðŸ"±')}</b>",
        f"<b>{ev.get('phone', ad['title'])}</b>",
        f"Ø§Ù„Ø³Ø¹Ø±: {ad['price']}",
    ]
    r = ev.get("range", "")
    if r:
        lines.append(f"Ù†Ø·Ø§Ù‚ Ø§Ù„Ø³ÙˆÙ‚: {r}")
    d = ev.get("diff_percent", "")
    if d:
        lines.append(f"Ø§Ù„ÙØ±Ù‚: {d}")
    a = ev.get("action", "")
    if a:
        lines.append(f"Ù†ØµÙŠØ­Ø©: {a}")
    r2 = ev.get("risk_factor", "")
    if r2:
        lines.append(f"âš ï¸ Ø®Ø·Ø±: {r2}")
    return "\n".join(lines)

# â"€â"€ State Persistence â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def save_processed_ids(ids):
    try:
        with open(PROCESSED_IDS_FILE, "a", encoding="utf-8") as f:
            for aid in ids:
                f.write(aid + "\n")
        log("INFO", "STATE_SAVED", f"ids_appended={len(ids)}")
    except OSError as e:
        log("ERROR", "STATE_ERR", str(e))

NEW_DB_HEADER = (
    "timestamp,ad_id,title,price,classification,range_min,range_max,"
    "diff_percent,action,risk_factor,phone_model,ad_url,issue_reason,"
    "user_score,user_notes,is_real_deal,session_type"
)

NEW_DB_HEADER = (
    "timestamp,ad_id,title,price,classification,range_min,range_max,"
    "diff_percent,action,risk_factor,phone_model,ad_url,issue_reason,"
    "user_score,user_notes,is_real_deal,session_type"
)

def append_market_db(ads, evaluations, bulk_mode=False, egypt_hour=None):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_label = "BULK_WINDOW" if bulk_mode else "Hourly"
    if not os.path.isfile(MARKET_DB_FILE):
        try:
            with open(MARKET_DB_FILE, "w", encoding="utf-8") as f:
                f.write(NEW_DB_HEADER + "\n")
        except OSError:
            pass
    else:
        with open(MARKET_DB_FILE, "r", encoding="utf-8") as f:
            first = f.readline().strip()
        if first.count(",") < 16:
            legacy = "market_database_legacy.csv"
            os.rename(MARKET_DB_FILE, legacy)
            log("INFO", "DB_MIGRATE", f"renamed old csv -> {legacy}")
            with open(MARKET_DB_FILE, "w", encoding="utf-8") as f:
                f.write(NEW_DB_HEADER + "\n")
    try:
        with open(MARKET_DB_FILE, "a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            for i, ad in enumerate(ads):
                ev = evaluations[i] if i < len(evaluations) else {}
                classification = ev.get("classification", "")
                ad_url = ad.get("url", "")
                rabita = "\u0631\u0627\u0628\u0637"
                excel_link = f'=HYPERLINK("{ad_url}", "رابط")' if ad_url else ""
                issue_reason = "AI_Success"
                if not classification:
                    issue_reason = "Missing_Evaluation_Data"
                if not ad.get("title") or not ad.get("price"):
                    issue_reason = "Scraping_Error_Missing_Price"
                dash = chr(8211)
                range_text = ev.get("range", "")
                range_min = range_text.split(dash)[0].strip() if dash in range_text else ""
                range_max = range_text.split(dash)[-1].strip() if dash in range_text else ""
                w.writerow([
                    ts,
                    ad.get("id", ""),
                    ad.get("title", ""),
                    ad.get("price", ""),
                    classification,
                    range_min,
                    range_max,
                    ev.get("diff_percent", ""),
                    ev.get("action", ""),
                    ev.get("risk_factor", ""),
                    ev.get("phone", ""),
                    excel_link,
                    issue_reason,
                    "",
                    "",
                    "",
                    session_label,
                ])
            w.writerow(["---" for _ in range(17)])
        log("INFO", "DB_APPEND_OK", f"rows={len(ads)} session={session_label}")
    except OSError as e:
        log("ERROR", "DB_ERR", str(e))
def git_push():
    try:
        subprocess.run(["git", "config", "user.name", "phone-hunter-bot"],
                       capture_output=True)
        subprocess.run(["git", "config", "user.email", "bot@phone-hunter.local"],
                       capture_output=True)
        subprocess.run(["git", "add", PROCESSED_IDS_FILE, MARKET_DB_FILE, SYSTEM_LOGS_FILE],
                       capture_output=True)
        diff = subprocess.run(["git", "diff", "--staged", "--quiet"],
                              capture_output=True)
        if diff.returncode == 0:
            log("INFO", "GIT_SKIP", "no changes to commit")
            return True
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        subprocess.run(["git", "commit", "-m", f"auto: update state {ts}"],
                       capture_output=True)
        subprocess.run(["git", "pull", "--rebase", "origin", "main"],
                       capture_output=True)
        push = subprocess.run(["git", "push"], capture_output=True)
        if push.returncode == 0:
            log("INFO", "GIT_PUSH_OK", "")
            return True
        log("ERROR", "GIT_PUSH_ERR", push.stderr.decode()[:200])
        return False
    except Exception as e:
        log("ERROR", "GIT_ERR", str(e))
        return False

# â"€â"€ Main â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def main():
    log("INFO", "START", f"BULK_MODE={os.environ.get('BULK_MODE', '')}")

    egypt_hour = (datetime.now(timezone.utc) + EGYPT_OFFSET).hour
    bulk_mode = egypt_hour in [2, 6] or os.environ.get("BULK_MODE", "").lower() == "true"
    log("INFO", "MODE", f"bulk={bulk_mode} egypt_hour={egypt_hour}")

    html = scrape_listings(DUBIZZLE_URL)
    if not html:
        log("ERROR", "ABORT", "no html fetched")
        return 1

    all_ads = parse_listings(html)
    if not all_ads:
        log("INFO", "END", "no ads parsed")
        return 0

    time_filtered = [a for a in all_ads if is_within_target_window(a["posted_text"], bulk_mode)]
    log("INFO", "TIME_FILTER", f"kept={len(time_filtered)} discarded={len(all_ads)-len(time_filtered)}")
    if not time_filtered:
        log("INFO", "END", "no ads in time window")
        return 0

    processed_ids = load_processed_ids()
    new_ads = filter_new_ads(time_filtered, processed_ids)
    if not new_ads:
        log("INFO", "END", "no new ads")
        return 0

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        log("ERROR", "ABORT", "GEMINI_API_KEY not set")
        return 1
    client = genai.Client(api_key=gemini_key)

    evaluations = evaluate_with_gemini(client, new_ads)
    if not evaluations:
        log("INFO", "END", "no evaluations returned")
        save_processed_ids([a["id"] for a in new_ads])
        return 0

    new_ids = []
    for i, ad in enumerate(new_ads):
        new_ids.append(ad["id"])
        ev = evaluations[i] if i < len(evaluations) else {}
        if ev.get("classification") in ("🔥 لَقطَة",):
            msg = format_alert(ad, ev)
            send_telegram(msg, ad["url"])
            log("INFO", "ALERT", f"deal: {ad['title']} {ad['price']}")

    save_processed_ids(new_ids)
    append_market_db(new_ads, evaluations, bulk_mode, egypt_hour)
    git_push()
    log("INFO", "DONE", "cycle complete")
    return 0

if __name__ == "__main__":
    sys.exit(main())

