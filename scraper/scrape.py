"""Price checker. Reads every product link from Supabase, extracts the price,
logs a new row only when it changed, and fills in product name + image."""
import os, re, json, time
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
QUICK = os.environ.get("QUICK") == "true"          # hourly run: only never-checked links
COUNTRY = os.environ.get("SHOP_COUNTRY", "AU")     # Shopify shops price by country
COOKIES = {"localization": COUNTRY}
HDR = {"apikey": SB_KEY, "Content-Type": "application/json"}
if not SB_KEY.startswith("sb_secret_"):            # legacy service_role keys are JWTs
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

def jsonld_nodes(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try: data = json.loads(tag.string or tag.get_text() or "")
        except Exception: continue
        yield from walk(data)

def from_jsonld(soup):
    for n in jsonld_nodes(soup):
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

def first_str(v):
    if isinstance(v, str): return v
    if isinstance(v, list) and v: return first_str(v[0])
    if isinstance(v, dict): return first_str(v.get("url"))

def clean_title(t):
    if not t: return None
    t = re.split(r"\s+[|–—]\s+", t.strip())[0].strip()
    return t[:150] or None

def page_info(soup):
    """Product name and image from the page."""
    name = image = None
    for n in jsonld_nodes(soup):
        if "Product" in str(n.get("@type", "")):
            name = name or first_str(n.get("name"))
            image = image or first_str(n.get("image"))
    def meta(prop):
        m = soup.find("meta", attrs={"property": prop})
        return m.get("content") if m else None
    name = name or meta("og:title") or (soup.title.string if soup.title and soup.title.string else None)
    image = image or meta("og:image")
    return {"name": clean_title(name), "image": image if image and image.startswith("http") else None}

def from_shopify(url):
    """Shopify shops expose exact per-variant prices at /products/<handle>.js"""
    u = urlparse(url)
    m = re.match(r"^/products/([^/?#]+)", u.path)
    if not m: return None
    try:
        r = requests.get(f"{u.scheme}://{u.netloc}/products/{m.group(1)}.js",
                         headers={"User-Agent": UA}, cookies=COOKIES, timeout=25)
        if not r.ok: return None
        data = r.json()
        variants = data.get("variants") or []
    except Exception:
        return None
    if not variants: return None
    vid = parse_qs(u.query).get("variant", [None])[0]
    v = (next((x for x in variants if str(x.get("id")) == vid), None)
         or next((x for x in variants if x.get("available")), variants[0]))
    p = v.get("price")
    img = data.get("featured_image") or ""
    if img.startswith("//"): img = "https:" + img
    return {"price": p / 100 if isinstance(p, int) else to_num(p),
            "name": clean_title(data.get("title")), "image": img or None}

def fetch(url, js):
    if js:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(user_agent=UA)
            pg.goto(url, wait_until="networkidle", timeout=45000)
            html = pg.content(); b.close(); return html
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-AU,en;q=0.9"},
                     cookies=COOKIES, timeout=25)
    r.raise_for_status()
    return r.text

def main():
    q = "item_urls?select=*,items!inner(id,name,name_auto,image_url,bought)&items.bought=eq.false"
    if QUICK: q += "&last_checked=is.null&render_js=eq.false"
    rows = sb("GET", q)
    print(f"Checking {len(rows)} links ({'new only' if QUICK else 'all'})")
    patched = {}  # item id -> fields already filled this run
    for r in rows:
        it, url = r["items"], r["url"]
        status, price, info = "ok", None, {}
        try:
            if not r.get("selector"):
                info = from_shopify(url) or {}
                price = info.get("price")
            if price is None:
                soup = BeautifulSoup(fetch(url, r.get("render_js")), "html.parser")
                price = extract(soup, r.get("selector"))
                info = {**page_info(soup), **{k: v for k, v in info.items() if v}}
            if price is None: status = "no price found"
        except Exception as e:
            status = f"error: {str(e)[:120]}"
        store = (urlparse(url).hostname or "").replace("www.", "")
        if price is not None:
            last = sb("GET", f"prices?url_id=eq.{r['id']}&select=price&order=on_date.desc,created_at.desc&limit=1")
            if not last or abs(float(last[0]["price"]) - price) > 0.004:
                sb("POST", "prices", {"Prefer": "return=minimal"},
                   json=[{"item_id": it["id"], "url_id": r["id"], "price": price, "store": store, "source": "auto"}])
        done = patched.setdefault(it["id"], set())
        upd = {}
        if it.get("name_auto") and info.get("name") and "name" not in done:
            upd["name"], upd["name_auto"] = info["name"], False
        if not it.get("image_url") and info.get("image") and "image" not in done:
            upd["image_url"] = info["image"]
        if upd:
            sb("PATCH", f"items?id=eq.{it['id']}", {"Prefer": "return=minimal"}, json=upd)
            done.update({"name" if "name" in upd else "", "image" if "image_url" in upd else ""})
        sb("PATCH", f"item_urls?id=eq.{r['id']}", {"Prefer": "return=minimal"},
           json={"last_checked": datetime.now(timezone.utc).isoformat(), "last_status": status, "store": store})
        print(f"- {it['name']} @ {store}: {price} ({status})")
        time.sleep(2)  # be polite

if __name__ == "__main__":
    main()
