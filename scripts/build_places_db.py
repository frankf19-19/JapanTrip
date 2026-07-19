# -*- coding: utf-8 -*-
"""
旅日和 TABIBIYORI - 全日本 POI 資料庫建置腳本 v10
架構轉換:不再使用 Overpass API(限流嚴重),改為解析 Geofabrik
全日本 OSM 擷取檔(workflow 先以 osmium 篩選並轉出 geojsonl)。
用法: python build_places_db.py pois.geojsonl
輸出: data/osm/r{lat}_{lon}.json 分區檔 + index.json
零網路請求、零限流,全量處理約數分鐘。
"""
import json, os, sys, time

FOOD_AMENITY = {"restaurant", "cafe", "fast_food", "bar", "pub", "food_court", "ice_cream"}
HOTEL_TOURISM = {"hotel", "hostel", "guest_house", "apartment", "motel"}
SHOP_KEEP = {"mall", "department_store", "supermarket"}
# v12:旅遊相關購物(麵包甜點/和菓子/伴手禮/茶/酒/動漫玩具)
SHOP_TRAVEL = {"bakery", "confectionery", "sweets", "gift", "souvenir", "tea", "sake", "anime", "toys"}
# v13:觀光購物再擴充 → 對應顯示標籤
SHOP_MORE = {
    "convenience": ("超商", 15),
    "chemist": ("藥妝", 40), "cosmetics": ("藥妝", 40),
    "clothes": ("服飾", 60), "shoes": ("服飾", 40),
    "electronics": ("電器", 60),
    "variety_store": ("激安雜貨", 60),
    "second_hand": ("二手古著", 45),
}
SPOT_MAP = {
    "attraction":  ([],                       60),
    "viewpoint":   (["自然風景", "夜景展望"], 40),
    "museum":      (["博物館藝術"],           90),
    "gallery":     (["博物館藝術"],           60),
    "artwork":     (["博物館藝術"],           30),
    "theme_park":  (["主題樂園", "親子同樂"], 300),
    "zoo":         (["親子同樂"],            150),
    "aquarium":    (["親子同樂"],            120),
}
NATURAL_MAP = {
    "hot_spring": (["溫泉"], 90),
    "waterfall":  (["自然風景"], 40),
    "beach":      (["自然風景", "親子同樂"], 90),
    "peak":       (["自然風景", "夜景展望"], 60),
}
# v11:不設上限 — 全量收錄;仍依標籤豐富度排序(資訊完整的排前面)


def centroid(geom):
    t = geom.get("type")
    c = geom.get("coordinates")
    try:
        if t == "Point":
            return c[1], c[0]
        if t == "LineString":
            m = c[len(c) // 2]
            return m[1], m[0]
        if t == "Polygon":
            ring = c[0]
            return (sum(p[1] for p in ring) / len(ring),
                    sum(p[0] for p in ring) / len(ring))
        if t == "MultiPolygon":
            ring = c[0][0]
            return (sum(p[1] for p in ring) / len(ring),
                    sum(p[0] for p in ring) / len(ring))
    except Exception:
        pass
    return None, None


def classify(t):
    """回傳 (cat, tags, stay) 或 None"""
    am = t.get("amenity", "")
    tm = t.get("tourism", "")
    if am in FOOD_AMENITY:
        return "food", [], 50
    if tm in HOTEL_TOURISM:
        return "hotel", [], 0
    if t.get("shop") in SHOP_KEEP or am == "marketplace":
        return "shop", (["市場老街"] if am == "marketplace" else []), 90
    if t.get("shop") in SHOP_MORE:
        tag, stay = SHOP_MORE[t["shop"]]
        return "shop", [tag], stay
    # v13:娛樂設施
    if t.get("leisure") == "amusement_arcade":
        return "spot", ["動漫電玩"], 60
    if am == "karaoke_box":
        return "spot", ["娛樂"], 90
    if t.get("shop") in SHOP_TRAVEL:
        tag = "美食巡禮" if t["shop"] in ("bakery", "confectionery", "sweets", "tea") else               "美酒微醺" if t["shop"] == "sake" else               "動漫電玩" if t["shop"] in ("anime", "toys") else "市場老街"
        return "shop", [tag], 40
    # v12:錢湯/溫泉設施、SPA
    if am == "public_bath" or t.get("leisure") == "spa":
        return "spot", ["溫泉"], 90
    # v12:酒藏/酒莊/啤酒廠
    if t.get("craft") in ("sake_brewery", "brewery", "winery", "distillery"):
        return "spot", ["美酒微醺"], 60
    # v12:展望塔等地標
    if t.get("man_made") == "tower" and t.get("tower:type") in ("observation", "communication", None) and t.get("tourism"):
        return "spot", ["夜景展望"], 45
    if am == "place_of_worship":
        return "spot", ["神社寺廟"], 30
    if t.get("historic"):
        return "spot", ["歷史古蹟"], 45
    if t.get("leisure") in ("park", "garden"):
        return "spot", ["自然風景"], 45
    if t.get("natural") in NATURAL_MAP:
        tags, stay = NATURAL_MAP[t["natural"]]
        return "spot", tags, stay
    if tm in SPOT_MAP:
        tags, stay = SPOT_MAP[tm]
        return "spot", tags, stay
    return None


def richness(t):
    """標籤豐富度:截取上限時優先保留資訊多的"""
    score = 0
    for k in ("cuisine", "opening_hours", "website", "wikipedia", "stars",
              "name:zh", "name:en", "addr:city", "contact:website"):
        if t.get(k):
            score += 1
    return score


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "pois.geojsonl"
    cells = {}   # key -> {cat: [entries]}
    seen = {}    # key -> set(names)
    n_read = n_kept = 0
    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.lstrip("\x1e").strip()
            if not line:
                continue
            n_read += 1
            try:
                feat = json.loads(line)
            except Exception:
                continue
            t = feat.get("properties") or {}
            name = t.get("name:zh") or t.get("name:zh-Hant") or t.get("name")
            if not name or len(name) > 40:
                continue
            cls = classify(t)
            if not cls:
                continue
            la, lo = centroid(feat.get("geometry") or {})
            if la is None or not (24 <= la <= 46 and 122 <= lo <= 146):
                continue
            cat, tags, stay = cls
            key = f"r{int(la)}_{int(lo)}"
            cs = seen.setdefault(key, set())
            if name in cs:
                continue
            cs.add(name)
            e = {"n": name, "la": round(la, 5), "lo": round(lo, 5), "c": cat,
                 "_r": richness(t)}
            ja = t.get("name:ja") or (t.get("name") if t.get("name") != name else "")
            if ja and ja != name:
                e["j"] = ja[:60]
            if cat == "spot" or cat == "shop":
                if tags:
                    e["t"] = tags
                e["s"] = stay
            if cat == "spot":
                wp = t.get("wikipedia", "")
                if wp.startswith("ja:"):
                    e["wt"] = wp[3:][:80]
            adr = "".join(filter(None, [t.get("addr:province"), t.get("addr:city"),
                   t.get("addr:suburb") or t.get("addr:quarter"), t.get("addr:neighbourhood")]))
            if adr:
                e["ad"] = adr[:60]
            if t.get("cuisine"):
                e["cu"] = t["cuisine"][:60]
            if t.get("opening_hours"):
                e["oh"] = t["opening_hours"][:120]
            w = t.get("website") or t.get("contact:website")
            if w:
                e["w"] = w[:200]
            if t.get("stars"):
                e["st"] = str(t["stars"])[:4]
            if cat == "hotel" and t.get("tourism") in ("hostel", "guest_house", "apartment", "motel"):
                e["ht"] = t["tourism"]
            cells.setdefault(key, {}).setdefault(cat, []).append(e)
            n_kept += 1

    os.makedirs("data/osm", exist_ok=True)
    total = 0
    stats = {"food": 0, "spot": 0, "hotel": 0, "shop": 0}
    for key, cats in sorted(cells.items()):
        out = []
        for cat, lst in cats.items():
            lst.sort(key=lambda x: -x["_r"])  # 不截取,全量收錄
            stats[cat] += len(lst)
            out.extend(lst)
        for e in out:
            e.pop("_r", None)
        with open(f"data/osm/{key}.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        total += len(out)
        print(f"{key}: {len(out):,} 筆", flush=True)
    files = sorted(f[:-5] for f in os.listdir("data/osm")
                   if f.endswith(".json") and f not in ("index.json", "meta.json")
                   and os.path.getsize(os.path.join("data/osm", f)) > 2)
    json.dump(files, open("data/osm/index.json", "w"))
    json.dump({"built": int(time.time())}, open("data/osm/meta.json", "w"))
    print(f"✅ 完成:讀入 {n_read:,} → 收錄 {total:,} 筆|{len(files)} 個分區檔")
    print(f"   景點 {stats['spot']:,}|美食 {stats['food']:,}|住宿 {stats['hotel']:,}|購物 {stats['shop']:,}")


if __name__ == "__main__":
    main()
