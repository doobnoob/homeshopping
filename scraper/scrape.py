"""Daily price checker. Reads item URLs from Supabase, extracts the price,
and logs a new row only when the price has changed."""
import os, re, json, time
from datetime import datetime, timezone
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {"apikey": SB_KEY, "Content-Type": "application/json"}
if not SB_KEY.startswith("sb_secret_"):  # legacy service_role keys are JWTs and also go in Authorization
    HDR["Authorization"] = f"Bearer {SB_KEY}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

def sb(method, path, extra=None, **kw):
    r = requests.request(method, f"{SB_URL}/rest/v1/{path}",
                         headers={**HDR, **(extra or {})}, timeout=30, **kw)
    if not r.ok:
        raise SystemExit(f"Supabase error {r.status_code} on {method} {path.split('?')[0]}: {r.text[:300]}")
    return r.json() if r.text else None

def to_num(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = re.sub(r"[^\d.,]", "", str(v))
    if not s: return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) else s.replace(",", "")
    try: return float(s)
    except ValueError: return None

def walk(node):
    if isinstance(node, list):
        for n in node: yield from walk(n)
    elif isinstance(node, dict):
        yield node
        for v in node.values():
            if isinstance(v, (list, dict)): yield from walk(v)

def from_jsonld(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try: data = json.loads(tag.string or tag.get_text() or "")
        except Exception: continue
        for n in walk(data):
            if "Offer" not in str(n.get("@type", "")): continue
            spec = n.get("priceSpecification")
            spec = spec[0] if isinstance(spec, list) and spec else spec
            p = to_num(n.get("price") or n.get("lowPrice") or (spec or {}).get("price"))
            if p: return p

def from_meta(soup):
    for prop in ("product:price:amount", "og:price:amount", "product:sale_price:amount"):
        m = soup.find("meta", attrs={"property": prop})
        if m and to_num(m.get("content")): return to_num(m["content"])
    m = soup.find(attrs={"itemprop": "price"})
    if m: return to_num(m.get("content") or m.get_text())

def extract(soup, selector):
    if selector:
        el = soup.select_one(selector)
        p = to_num(el.get("content") or el.get_text()) if el else None
        if p: return p
    return from_jsonld(soup) or from_meta(soup)

def fetch(url, js):
    if js:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(user_agent=UA)
            pg.goto(url, wait_until="networkidle", timeout=45000)
            html = pg.content(); b.close(); return html
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-AU,en;q=0.9"}, timeout=25)
    r.raise_for_status()
    return r.text

def main():
    items = sb("GET", "items?select=*&bought=eq.false&url=like.http*")
    print(f"Checking {len(items)} items")
    for it in items:
        status, price = "ok", None
        try:
            soup = BeautifulSoup(fetch(it["url"], it.get("render_js")), "html.parser")
            price = extract(soup, it.get("selector"))
            if price is None: status = "no price found"
        except Exception as e:
            status = f"error: {str(e)[:120]}"
        if price is not None:
            last = sb("GET", f"prices?item_id=eq.{it['id']}&select=price&order=on_date.desc,created_at.desc&limit=1")
            if not last or abs(float(last[0]["price"]) - price) > 0.004:
                store = urlparse(it["url"]).hostname.replace("www.", "")
                sb("POST", "prices", {"Prefer": "return=minimal"},
                   json=[{"item_id": it["id"], "price": price, "store": store, "source": "auto"}])
        sb("PATCH", f"items?id=eq.{it['id']}", {"Prefer": "return=minimal"},
           json={"last_checked": datetime.now(timezone.utc).isoformat(), "last_status": status})
        print(f"- {it['name']}: {price} ({status})")
        time.sleep(2)  # be polite

if __name__ == "__main__":
    main()
