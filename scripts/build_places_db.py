# -*- coding: utf-8 -*-
"""
和遊誌 WAYU TRIP - 全日本餐廳/飯店資料庫建置腳本
以 1° 地理網格掃描全日本,從 OpenStreetMap(Overpass)抓取
餐廳/咖啡/飯店/旅館/民宿,輸出 data/osm/r{lat}_{lon}.json 分區檔。
品質過濾:餐廳需具備 料理類型/營業時間/官網 至少其一(排除低品質標記)。
預估總量 30,000–60,000 筆。GitHub Actions 執行,免金鑰。
"""
import json, time, os, sys, urllib.request, urllib.parse

EP = "https://overpass-api.de/api/interpreter"
UA = "WAYU-TRIP-PlacesDB/1.0 (GitHub Actions; static travel planner)"
CAP = 900   # 每格上限
SLEEP = 4   # 禮貌間隔(秒)

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

Q = """[out:json][timeout:90];
(
  node[amenity~"^(restaurant|cafe)$"][name]({s},{w},{n},{e});
  way[amenity~"^(restaurant|cafe)$"][name]({s},{w},{n},{e});
  node[tourism~"^(hotel|hostel|guest_house)$"][name]({s},{w},{n},{e});
  way[tourism~"^(hotel|hostel|guest_house)$"][name]({s},{w},{n},{e});
);out center tags {cap};"""

def fetch(q, retries=3):
    data = urllib.parse.urlencode({"data": q}).encode()
    for i in range(retries):
        try:
            req = urllib.request.Request(EP, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=150) as r:
                return json.load(r).get("elements", [])
        except Exception as ex:
            print(f"    重試 {i+1}: {ex}", file=sys.stderr)
            time.sleep(20 * (i + 1))
    return []

def main():
    os.makedirs("data/osm", exist_ok=True)
    cells = japan_cells()
    total = 0
    print(f"掃描 {len(cells)} 個網格…", flush=True)
    for idx, (la, lo) in enumerate(cells):
        q = Q.format(s=la, w=lo, n=la + 1, e=lo + 1, cap=CAP)
        els = fetch(q)
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
            is_food = t.get("amenity") in ("restaurant", "cafe")
            # 品質過濾:餐廳需有 料理/時間/官網 其一
            if is_food and not (t.get("cuisine") or t.get("opening_hours") or t.get("website")):
                continue
            seen.add(name)
            e = {"n": name, "la": round(lat, 5), "lo": round(lon, 5),
                 "c": "food" if is_food else "hotel"}
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
            out.append(e)
        if out:
            path = f"data/osm/r{la}_{lo}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
            total += len(out)
            print(f"[{idx+1}/{len(cells)}] r{la}_{lo}: {len(out)} 筆(累計 {total:,})", flush=True)
        else:
            print(f"[{idx+1}/{len(cells)}] r{la}_{lo}: 0", flush=True)
        time.sleep(SLEEP)
    # 索引檔
    files = sorted(f[:-5] for f in os.listdir("data/osm") if f.endswith(".json") and f != "index.json")
    with open("data/osm/index.json", "w", encoding="utf-8") as f:
        json.dump(files, f)
    print(f"✅ 完成:{len(files)} 個分區檔,共 {total:,} 筆餐廳/飯店")

if __name__ == "__main__":
    main()
