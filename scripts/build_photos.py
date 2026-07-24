# -*- coding: utf-8 -*-
"""
build_photos.py — 預建精選景點照片庫 (data/photos.json)
========================================================
離線批次解析 index.html 精選資料庫中每個景點的照片 URL,
使用者端載入 photos.json 即可零 API 呼叫直接顯示照片。

解析順序(與前端一致但更完整):
  1. ja.wikipedia pageimages (日文標題,批次 50 筆/請求)
  2. 標題去括號/取第一段重試
  3. zh.wikipedia pageimages (中文名稱清理後)
  4. Commons 座標搜圖 (150m 內,檔名須含名稱關鍵字)

用法:  python scripts/build_photos.py
輸出:  data/photos.json  { "中文名稱": "縮圖URL", ... }
既有的 photos.json 條目會保留(可手動修圖後不被覆蓋);
想全部重抓請加參數 --refresh
"""
import json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
OUT = ROOT / "data" / "photos.json"
UA = {"User-Agent": "TabibiyoriPhotoBot/1.0 (github.com/frankf19-19/JapanTrip)"}
THUMB = 520

def api(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def parse_db():
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r"const DB=\[(.*?)\n\];", html, re.S)
    entries = []
    for em in re.finditer(r'\{n:"([^"]+)",j:"([^"]*)",la:([\d.]+),lo:([\d.]+),c:"(\w+)"', m.group(1)):
        n, j, la, lo, c = em.groups()
        entries.append({"n": n, "j": j, "la": float(la), "lo": float(lo), "c": c})
    return entries

def wiki_batch(titles, lang):
    """批次查 pageimages,回傳 {原標題: url}"""
    out = {}
    for i in range(0, len(titles), 50):
        chunk = [t.replace("|", "") for t in titles[i:i+50] if t.strip()]
        if not chunk: continue
        u = (f"https://{lang}.wikipedia.org/w/api.php?action=query&format=json&redirects=1"
             f"&prop=pageimages&piprop=thumbnail&pithumbsize={THUMB}"
             f"&titles={urllib.parse.quote('|'.join(chunk))}")
        try:
            j = api(u)
        except Exception as e:
            print(f"  [warn] {lang} batch fail: {e}", file=sys.stderr); continue
        q = j.get("query", {})
        back = {}
        def add(frm, to): back.setdefault(to, []).append(frm)
        for x in q.get("normalized", []): add(x["from"], x["to"])
        for x in q.get("redirects", []):
            for s in back.get(x["from"], [x["from"]]): add(s, x["to"])
        for pg in q.get("pages", {}).values():
            th = pg.get("thumbnail")
            if not th: continue
            url = th["source"]
            out[pg["title"]] = url
            for orig in back.get(pg["title"], []): out[orig] = url
        time.sleep(0.4)  # 禮貌限速
    return out

def commons_geo(la, lo, ja, zh):
    u = (f"https://commons.wikimedia.org/w/api.php?action=query&format=json"
         f"&generator=geosearch&ggscoord={la}%7C{lo}&ggsradius=150&ggslimit=20&ggsnamespace=6"
         f"&prop=imageinfo&iiprop=url&iiurlwidth={THUMB}")
    try:
        j = api(u)
    except Exception:
        return None
    toks = {t for t in re.split(r"[\s・()()]", f"{ja} {zh}") if len(t) >= 2}
    for pg in (j.get("query", {}).get("pages", {}) or {}).values():
        t = pg.get("title", "")
        if not re.search(r"\.(jpe?g|png|webp)$", t, re.I): continue
        if any(k in t for k in toks):
            ii = (pg.get("imageinfo") or [{}])[0]
            if ii: return ii.get("thumburl") or ii.get("url")
    return None

def main():
    refresh = "--refresh" in sys.argv
    entries = [e for e in parse_db() if e["c"] in ("spot", "shop")]
    print(f"精選條目(spot/shop): {len(entries)}")
    old = {}
    if OUT.exists() and not refresh:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    photos = dict(old)
    todo = [e for e in entries if e["n"] not in photos]
    print(f"待解析: {len(todo)} (沿用既有 {len(old)})")

    # 第 1 層:日文標題
    ja_map = wiki_batch([e["j"] for e in todo if e["j"]], "ja")
    for e in todo:
        if e["j"] and e["j"] in ja_map: photos[e["n"]] = ja_map[e["j"]]
    # 第 2 層:日文去括號/第一段
    rest = [e for e in todo if e["n"] not in photos and e["j"]]
    alt = {e["j"]: re.split(r"[ ((]", e["j"])[0].strip() for e in rest}
    alt_map = wiki_batch(list({v for v in alt.values() if v}), "ja")
    for e in rest:
        a = alt.get(e["j"])
        if a and a in alt_map: photos[e["n"]] = alt_map[a]
    # 第 3 層:中文名稱
    rest = [e for e in todo if e["n"] not in photos]
    zh = {e["n"]: re.split(r"[・((]", e["n"])[0].strip() for e in rest}
    zh_map = wiki_batch(list({v for v in zh.values() if v}), "zh")
    for e in rest:
        z = zh.get(e["n"])
        if z and z in zh_map: photos[e["n"]] = zh_map[z]
    # 第 4 層:Commons 座標搜圖
    rest = [e for e in todo if e["n"] not in photos]
    print(f"進入座標搜圖: {len(rest)}")
    for e in rest:
        url = commons_geo(e["la"], e["lo"], e["j"], e["n"])
        if url: photos[e["n"]] = url
        time.sleep(0.4)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(photos, ensure_ascii=False, indent=1), encoding="utf-8")
    hit = sum(1 for e in entries if e["n"] in photos)
    print(f"完成 → {OUT}  覆蓋率 {hit}/{len(entries)} ({hit*100//max(len(entries),1)}%)")

if __name__ == "__main__":
    main()
