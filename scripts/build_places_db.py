# -*- coding: utf-8 -*-
"""
和遊誌 WAYU TRIP - 全日本餐廳/飯店資料庫建置腳本
以 1° 地理網格掃描全日本,從 OpenStreetMap(Overpass)抓取
餐廳/咖啡/飯店/旅館/民宿,輸出 data/osm/r{lat}_{lon}.json 分區檔。
品質過濾:餐廳需具備 料理類型/營業時間/官網 至少其一(排除低品質標記)。
預估總量 30,000–60,000 筆。GitHub Actions 執行,免金鑰。
"""
import json, time, os, sys, urllib.request, urllib.parse

# 多鏡像輪替:被限流(429)或逾時(504)自動換下一台
EPS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
UA = "WAYU-TRIP-PlacesDB/3.0 (GitHub Actions; static travel planner; contact via repo)"
CAP = 1800  # 每格上限(四分類共用)
SLEEP = 2   # 禮貌間隔(秒)
_ep_i = 0   # 目前鏡像索引

# 日本大致陸地網格(緯度, 經度)— 跳過純海域省時間
def japan_cells():
    cells = []
    for la in range(24, 46):
        for lo in range(123, 146):
            # 粗略陸地判斷:排除明顯外海格
            if la <= 26 and not (123 <= lo <= 129):   # 沖繩諸島
                continue
            if 27 <= la <= 29 and not (128 <= lo <= 131):  # 奄美一帶
                continue
            if 30 <= la <= 33 and not (129 <= lo <= 135):  # 九州
                continue
            if 33 <= la <= 35 and not (129 <= lo <= 141):  # 中四國近畿
                continue
            if 35 <= la <= 38 and not (132 <= lo <= 141):  # 中部關東
                continue
            if 38 <= la <= 41 and not (139 <= lo <= 142):  # 東北
                continue
            if 41 <= la <= 45 and not (139 <= lo <= 146):  # 北海道
                continue
            cells.append((la, lo))
    return cells

Q = """[out:json][timeout:120];
(
  node[amenity~"^(restaurant|cafe|fast_food|bar|pub|food_court|ice_cream)$"][name]({s},{w},{n},{e});
  way[amenity~"^(restaurant|cafe|fast_food|bar|pub)$"][name]({s},{w},{n},{e});
  node[tourism~"^(hotel|hostel|guest_house|apartment|motel)$"][name]({s},{w},{n},{e});
  way[tourism~"^(hotel|hostel|guest_house|apartment|motel)$"][name]({s},{w},{n},{e});
  node[shop~"^(mall|department_store|supermarket)$"][name]({s},{w},{n},{e});
  way[shop~"^(mall|department_store)$"][name]({s},{w},{n},{e});
  node[amenity=marketplace][name]({s},{w},{n},{e});
  node[tourism~"^(attraction|viewpoint|museum|gallery|theme_park|zoo|aquarium)$"][name]({s},{w},{n},{e});
  way[tourism~"^(attraction|viewpoint|museum|gallery|theme_park|zoo|aquarium)$"][name]({s},{w},{n},{e});
  node[historic][name]({s},{w},{n},{e});
  way[historic][name]({s},{w},{n},{e});
  node[amenity=place_of_worship][name]({s},{w},{n},{e});
  way[amenity=place_of_worship][name]({s},{w},{n},{e});
  way[leisure=park][name]({s},{w},{n},{e});
);out center tags {cap};"""

# 景點子類 →(標籤, 建議停留分)
SPOT_MAP = {
    "attraction":  ([],                       60),
    "viewpoint":   (["自然風景", "夜景展望"], 40),
    "museum":      (["博物館藝術"],           90),
    "gallery":     (["博物館藝術"],           60),
    "theme_park":  (["主題樂園", "親子同樂"], 300),
    "zoo":         (["親子同樂"],            150),
    "aquarium":    (["親子同樂"],            120),
}

def fetch(q, retries=3):
    global _ep_i
    data = urllib.parse.urlencode({"data": q}).encode()
    for i in range(retries):
        ep = EPS[_ep_i % len(EPS)]
        try:
            req = urllib.request.Request(ep, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r).get("elements", [])
        except urllib.error.HTTPError as ex:
            wait = 15
            if ex.code == 429:  # 限流:遵守 Retry-After 並換鏡像
                try:
                    wait = min(int(ex.headers.get("Retry-After", "20")), 45)
                except Exception:
                    wait = 20
                _ep_i += 1
                print(f"    429 限流 → 換鏡像 {EPS[_ep_i % len(EPS)].split('/')[2]},等 {wait}s", file=sys.stderr)
            elif ex.code in (504, 502, 503):
                _ep_i += 1
                wait = 4
                print(f"    {ex.code} → 換鏡像重試", file=sys.stderr)
            else:
                print(f"    HTTP {ex.code}", file=sys.stderr)
            time.sleep(wait)
        except Exception as ex:
            _ep_i += 1
            print(f"    重試 {i+1}: {ex}", file=sys.stderr)
            time.sleep(4)
    return None  # 全部失敗:回 None 以保留上一次的分區檔

def main():
    import subprocess
    subprocess.run(["git","config","user.name","wayu-bot"],check=False)
    subprocess.run(["git","config","user.email","actions@users.noreply.github.com"],check=False)
    os.makedirs("data/osm", exist_ok=True)
    cells = japan_cells()
    total = 0
    print(f"掃描 {len(cells)} 個網格…", flush=True)
    import subprocess
    def checkpoint(msg):
        try:
            files=sorted(f[:-5] for f in os.listdir("data/osm") if f.endswith(".json") and f!="index.json")
            json.dump(files, open("data/osm/index.json","w"))
            subprocess.run(["git","add","data/osm"],check=False)
            r=subprocess.run(["git","diff","--cached","--quiet"])
            if r.returncode!=0:
                subprocess.run(["git","commit","-m",msg],check=False)
                subprocess.run(["git","push"],check=False)
                print(f"  💾 已提交:{msg}", flush=True)
        except Exception as ex:
            print(f"  提交失敗(不影響續跑):{ex}", file=sys.stderr)
    failed = []
    skipped = 0
    RESUME = os.environ.get("WAYU_RESUME", "1") != "0"  # 預設開啟斷點續傳
    for idx, (la, lo) in enumerate(cells):
        path = f"data/osm/r{la}_{lo}.json"
        # 斷點續傳:已存在且有內容的分區檔直接跳過(只補沒抓到的)
        if RESUME and os.path.exists(path) and os.path.getsize(path) > 2:
            skipped += 1
            if skipped % 20 == 0:
                print(f"[{idx+1}/{len(cells)}] 已跳過 {skipped} 個既有分區檔…", flush=True)
            continue
        q = Q.format(s=la, w=lo, n=la + 1, e=lo + 1, cap=CAP)
        els = fetch(q)
        if els is None:
            # 整格查詢一直逾時 → 多半是超高密度格(東京/大阪),切成四個 0.5° 子格分批抓
            print(f"[{idx+1}/{len(cells)}] r{la}_{lo}: 整格逾時 → 切四子格分批抓…", flush=True)
            els = []
            sub_fail = 0
            for sla, slo in [(la, lo), (la, lo + 0.5), (la + 0.5, lo), (la + 0.5, lo + 0.5)]:
                sq = Q.format(s=sla, w=slo, n=sla + 0.5, e=slo + 0.5, cap=900)
                sub = fetch(sq)
                if sub is None:
                    sub_fail += 1
                    print(f"    子格 {sla},{slo}: 失敗", flush=True)
                else:
                    els.extend(sub)
                    print(f"    子格 {sla},{slo}: {len(sub)} 元素", flush=True)
                time.sleep(SLEEP)
            if sub_fail == 4:  # 四個子格全掛才算徹底失敗
                failed.append(f"r{la}_{lo}")
                print(f"[{idx+1}/{len(cells)}] r{la}_{lo}: ⚠️ 失敗(保留舊檔,下週重試)", flush=True)
                time.sleep(SLEEP)
                continue
        out, seen = [], set()
        for el in els:
            t = el.get("tags", {})
            name = t.get("name:zh") or t.get("name:zh-Hant") or t.get("name")
            if not name or len(name) > 40 or name in seen:
                continue
            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            lon = el.get("lon") or (el.get("center") or {}).get("lon")
            if lat is None:
                continue
            is_food = t.get("amenity") in ("restaurant", "cafe", "fast_food", "bar", "pub", "food_court", "ice_cream")
            is_hotel = t.get("tourism") in ("hotel", "hostel", "guest_house", "apartment", "motel")
            is_shop = bool(t.get("shop")) or t.get("amenity") == "marketplace"
            seen.add(name)
            if is_food:
                cat = "food"; tags = []; stay = 50
            elif is_hotel:
                cat = "hotel"; tags = []; stay = 0
            elif is_shop:
                cat = "shop"
                tags = ["市場老街"] if t.get("amenity") == "marketplace" else []
                stay = 90
            else:  # 景點
                cat = "spot"
                if t.get("amenity") == "place_of_worship":
                    tags, stay = ["神社寺廟"], 30
                elif t.get("historic"):
                    tags, stay = ["歷史古蹟"], 45
                elif t.get("leisure") == "park":
                    tags, stay = ["自然風景"], 45
                else:
                    tags, stay = SPOT_MAP.get(t.get("tourism"), ([], 60))
            e = {"n": name, "la": round(lat, 5), "lo": round(lon, 5), "c": cat}
            if cat == "spot":
                if tags:
                    e["t"] = tags
                e["s"] = stay
                wp = t.get("wikipedia", "")
                if wp.startswith("ja:"):
                    e["wt"] = wp[3:][:80]  # 維基條目名 → 前端介紹/相簿
            ja = t.get("name:ja") or (t.get("name") if t.get("name") != name else "")
            if ja and ja != name:
                e["j"] = ja
            adr = "".join(filter(None, [t.get("addr:province"), t.get("addr:city"),
                   t.get("addr:suburb") or t.get("addr:quarter"), t.get("addr:neighbourhood")]))
            if adr:
                e["ad"] = adr
            if t.get("cuisine"):
                e["cu"] = t["cuisine"][:60]
            if t.get("opening_hours"):
                e["oh"] = t["opening_hours"][:120]
            if t.get("website") or t.get("contact:website"):
                e["w"] = (t.get("website") or t.get("contact:website"))[:200]
            if t.get("stars"):
                e["st"] = t["stars"][:4]
            if is_hotel and t.get("tourism") in ("hostel", "guest_house", "apartment", "motel"):
                e["ht"] = t["tourism"]
            out.append(e)
        if out:
            path = f"data/osm/r{la}_{lo}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
            total += len(out)
            print(f"[{idx+1}/{len(cells)}] r{la}_{lo}: {len(out)} 筆(累計 {total:,})", flush=True)
        else:
            print(f"[{idx+1}/{len(cells)}] r{la}_{lo}: 0", flush=True)
        if (idx+1) % 15 == 0:
            checkpoint(f"chore: 餐飲住宿景點資料庫進度 {idx+1}/{len(cells)}(累計 {total:,} 筆)")
        time.sleep(SLEEP)
    # 索引檔
    files = sorted(f[:-5] for f in os.listdir("data/osm") if f.endswith(".json") and f != "index.json")
    with open("data/osm/index.json", "w", encoding="utf-8") as f:
        json.dump(files, f)
    print(f"✅ 完成:{len(files)} 個分區檔(本次跳過 {skipped} 個既有、新抓 {total:,} 筆)")
    if failed:
        print(f"⚠️ {len(failed)} 格本次失敗(沿用舊檔):{', '.join(failed[:20])}{'…' if len(failed)>20 else ''}")

if __name__ == "__main__":
    main()
