# -*- coding: utf-8 -*-
"""
build_rakuten_hotels.py — 預建楽天飯店庫 (data/rakuten_hotels.json)
====================================================================
在 GitHub Actions(雲端)呼叫楽天 Travel API,把精選資料庫涵蓋的 91 個區域的
全部飯店(房間照/外觀照/最低房價/評分/聯盟訂房連結)抓成靜態 JSON。
訪客端直接載入檔案 → 零 API 呼叫、零限流風險、秒開。

流量禮儀:嚴格 1.2 秒/請求(楽天免費版規範),全程約 8-15 分鐘。
建議每週由 workflow 自動更新(房價會變,標示為參考價)。
"""
import json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
OUT = ROOT / "data" / "rakuten_hotels.json"

APP_ID = "0eb05990-6440-4ca1-ad99-ac627268281c"
ACCESS_KEY = "pk_NaKQ4f3CMsKt4gPQ3VRbtw5WoSgavcg6k9YbFZOUi45"
AFF_ID = "56130e5f.a61145fa.56130e60.1928a16a"
REFERER = "https://frankf19-19.github.io/JapanTrip/"  # 新版楽天 API 檢查來源,須在白名單網域內
ENDPOINT = "https://openapi.rakuten.co.jp/services/api/Travel/SimpleHotelSearch/20170426"
PAUSE = 1.2   # 每請求間隔(秒) — 楽天免費版每秒 1 次
MAX_PAGES = 34  # 每點最多 34 頁(=1020 間),等同無上限

def api(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "TabibiyoriBot/1.0 (github.com/frankf19-19/JapanTrip)",
        "Referer": REFERER,
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def parse_centers():
    """從 index.html 精選庫萃取各區域取樣點(大區域多點覆蓋,點間距>2.5km)"""
    html = INDEX.read_text(encoding="utf-8")
    body = re.search(r"const DB=\[(.*?)\n\];", html, re.S).group(1)
    areas = {}
    for m in re.finditer(r'\{n:"[^"]+",j:"[^"]*",la:([\d.]+),lo:([\d.]+),c:"\w+"[^\n]*a:"([^"]+)"', body):
        la, lo, a = float(m.group(1)), float(m.group(2)), m.group(3)
        areas.setdefault(a, []).append((la, lo))
    pts = []
    for a, coords in areas.items():
        chosen = []
        for la, lo in coords:
            if all(((la-x)**2+(lo-y)**2)**0.5 > 0.025 for x, y in chosen):  # ~2.5km
                chosen.append((la, lo))
            if len(chosen) >= 4:
                break
        pts += [(a, la, lo) for la, lo in chosen]
    return pts

def fetch_point(la, lo):
    out, page, page_count = [], 1, 1
    while page <= page_count and page <= MAX_PAGES:
        qs = (f"?applicationId={urllib.parse.quote(APP_ID)}&accessKey={urllib.parse.quote(ACCESS_KEY)}"
              f"&affiliateId={urllib.parse.quote(AFF_ID)}"
              f"&format=json&datumType=1&hits=30&page={page}"
              f"&latitude={la}&longitude={lo}&searchRadius=3")
        try:
            j = api(ENDPOINT + qs)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:200]
            print(f"  [warn] HTTP {e.code} @({la},{lo}) p{page}: {body}", file=sys.stderr)
            if e.code == 429:
                time.sleep(10); continue  # 被限流:多等再試同一頁
            break
        except Exception as e:
            print(f"  [warn] {e}", file=sys.stderr); break
        page_count = int((j.get("pagingInfo") or {}).get("pageCount") or 1)
        for x in j.get("hotels", []):
            h = (x.get("hotel") or [{}])[0].get("hotelBasicInfo") or {}
            if not h.get("hotelName"):
                continue
            out.append({
                "nm": h["hotelName"], "la": float(h["latitude"]), "lo": float(h["longitude"]),
                "img": h.get("hotelImageUrl"), "room": h.get("roomImageUrl"),
                "min": h.get("hotelMinCharge"), "rev": h.get("reviewAverage"),
                "revN": h.get("reviewCount"), "url": h.get("hotelInformationUrl"),
                "ad": (h.get("address1") or "") + (h.get("address2") or ""),
            })
        page += 1
        time.sleep(PAUSE)
    return out

def main():
    pts = parse_centers()
    print(f"取樣點: {len(pts)}(預估 {len(pts)*PAUSE*3/60:.0f}+ 分鐘)")
    seen, hotels = set(), []
    for i, (a, la, lo) in enumerate(pts):
        got = fetch_point(la, lo)
        n0 = len(hotels)
        for h in got:
            k = h["nm"] + "@" + f'{h["la"]:.3f},{h["lo"]:.3f}'
            if k in seen:
                continue
            seen.add(k); hotels.append(h)
        print(f"[{i+1}/{len(pts)}] {a} ({la},{lo}) +{len(hotels)-n0} (累計 {len(hotels)})")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"t": int(time.time()*1000), "h": hotels},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"完成 → {OUT}  共 {len(hotels)} 間 ({OUT.stat().st_size//1024} KB)")

if __name__ == "__main__":
    main()
