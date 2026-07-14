# -*- coding: utf-8 -*-
"""
和遊誌 WAYU TRIP - 全日本景點擴充資料庫建置腳本 v2(火力全開版)
從 Wikidata 抓取全日本觀光相關地點(只收有日文維基百科條目者)
含子分類展開、所在市町村、Commons 照片。預估 20,000–30,000 筆。
輸出:data/spots_extra.json  (在 GitHub Actions 執行,免金鑰)
"""
import json, time, os, sys, urllib.request, urllib.parse

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "WAYU-TRIP-DB-Builder/2.0 (GitHub Actions; static travel planner)"

# (Wikidata class, deep=是否展開子分類, 類別, 標籤, 停留分, 上限)
CLASSES = [
    ("Q845945",  True,  "spot", ["神社寺廟"],            45, 6000),  # 神社(含稻荷/八幡/天滿宮…)
    ("Q5393308", True,  "spot", ["神社寺廟"],            45, 6000),  # 佛寺
    ("Q23413",   True,  "spot", ["歷史古蹟"],            90, 2500),  # 城(含城跡)
    ("Q839954",  False, "spot", ["歷史古蹟"],            60, 2500),  # 遺跡/古墳
    ("Q33506",   True,  "spot", ["博物館藝術"],          90, 6000),  # 博物館(含美術館/科學館)
    ("Q1150958", False, "spot", ["溫泉"],               180, 1500),  # 溫泉
    ("Q177380",  False, "spot", ["溫泉"],               120, 1000),  # 湧泉/hot spring
    ("Q22698",   False, "spot", ["自然風景"],            60, 3000),  # 公園
    ("Q1107656", False, "spot", ["自然風景"],            75, 1200),  # 庭園
    ("Q167346",  False, "spot", ["自然風景","親子同樂"],  90,  500),  # 植物園
    ("Q34038",   False, "spot", ["自然風景"],            45, 1200),  # 瀑布
    ("Q39816",   False, "spot", ["自然風景"],            90,  800),  # 溪谷
    ("Q40080",   False, "spot", ["自然風景"],            90, 1000),  # 海灘
    ("Q8502",    False, "spot", ["自然風景"],           180, 3500),  # 山岳
    ("Q23397",   False, "spot", ["自然風景"],            60, 1500),  # 湖泊
    ("Q39715",   False, "spot", ["自然風景","夜景展望"],  45,  600),  # 燈塔
    ("Q2281788", False, "spot", ["親子同樂"],           150,  400),  # 水族館
    ("Q43501",   False, "spot", ["親子同樂"],           150,  500),  # 動物園
    ("Q194195",  False, "spot", ["主題樂園","親子同樂"], 300,  500),  # 遊樂園
    ("Q570116",  False, "spot", [],                      60, 3000),  # 觀光景點(泛用)
    ("Q1067164", False, "spot", ["市場老街","美食巡禮"],  45, 1500),  # 道之驛
    ("Q11315",   False, "shop", [],                      90, 1200),  # 購物中心
]

Q_TMPL = """
SELECT ?item ?ja ?zh ?coord ?img ?admL WHERE {{
  ?item {p31} wd:{cls} ; wdt:P17 wd:Q17 ; wdt:P625 ?coord .
  ?article schema:about ?item ; schema:isPartOf <https://ja.wikipedia.org/> .
  OPTIONAL {{ ?item wdt:P18 ?img }}
  OPTIONAL {{ ?item rdfs:label ?ja FILTER(lang(?ja)="ja") }}
  OPTIONAL {{ ?item rdfs:label ?zh FILTER(lang(?zh) IN ("zh-hant","zh-tw","zh")) }}
  OPTIONAL {{ ?item wdt:P131 ?adm . ?adm rdfs:label ?admL FILTER(lang(?admL)="ja") }}
}} LIMIT {limit}
"""

def sparql(query, retries=3):
    data = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(ENDPOINT, data=data,
                headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)["results"]["bindings"]
        except Exception as e:
            print(f"  ⚠️ 第 {attempt+1} 次失敗: {e}", file=sys.stderr)
            time.sleep(20 * (attempt + 1))
    return None

def fetch_class(cls, deep, limit):
    """深層(含子分類)優先,逾時自動退回直接分類。"""
    if deep:
        rows = sparql(Q_TMPL.format(p31="wdt:P31/wdt:P279*", cls=cls, limit=limit))
        if rows is not None:
            return rows
        print("  ↩️ 子分類展開逾時,改用直接分類", file=sys.stderr)
    return sparql(Q_TMPL.format(p31="wdt:P31", cls=cls, limit=limit)) or []

def parse_coord(wkt):
    try:
        lon, lat = wkt.replace("Point(", "").replace(")", "").split()
        return round(float(lat), 5), round(float(lon), 5)
    except Exception:
        return None, None

def thumb(img_url):
    if not img_url:
        return None
    return ("https://commons.wikimedia.org/wiki/Special:FilePath/"
            + img_url.rsplit("/", 1)[-1] + "?width=520")

def main():
    out, seen = [], set()
    for cls, deep, cat, tags, stay, limit in CLASSES:
        label = "/".join(tags) or cat
        print(f"抓取 {cls} ({label}) {'含子分類' if deep else ''}…", flush=True)
        rows = fetch_class(cls, deep, limit)
        added = 0
        for b in rows:
            ja = b.get("ja", {}).get("value", "")
            zh = b.get("zh", {}).get("value", "")
            name = (zh or ja).strip()
            if not name or len(name) > 40 or name in seen:
                continue
            la, lo = parse_coord(b.get("coord", {}).get("value", ""))
            if la is None or not (20.0 <= la <= 46.5 and 122.0 <= lo <= 154.5):
                continue
            seen.add(name)
            e = {"n": name, "la": la, "lo": lo, "c": cat, "t": tags, "s": stay}
            if ja and ja != name:
                e["j"] = ja
            adm = b.get("admL", {}).get("value")
            if adm:
                e["ad"] = adm
            im = thumb(b.get("img", {}).get("value"))
            if im:
                e["im"] = im
            out.append(e)
            added += 1
        print(f"  +{added} 筆(累計 {len(out)})", flush=True)
        time.sleep(6)  # WDQS 禮貌間隔

    os.makedirs("data", exist_ok=True)
    with open("data/spots_extra.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    kb = os.path.getsize("data/spots_extra.json") // 1024
    print(f"✅ 完成:data/spots_extra.json 共 {len(out):,} 筆({kb:,} KB)")

if __name__ == "__main__":
    main()
