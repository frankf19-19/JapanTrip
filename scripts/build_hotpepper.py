# -*- coding: utf-8 -*-
"""
build_hotpepper.py — 預建 Hot Pepper 餐廳庫 (data/hp/*.json)
=============================================================
呼叫リクルート Hot Pepper グルメサーチAPI(免費),把 217 個取樣點周邊 3km 的
餐廳(含店家照片/料理類型/預算/營業時間/訂位連結)抓成分區靜態 JSON。
訪客端按需載入所在區塊 → 餐廳卡片有真實店照,零 API 呼叫。

★ 啟用:到 https://webservice.recruit.co.jp/register/ 免費註冊(只要 email),
  取得 API KEY 貼進下面 HOTPEPPER_KEY。
額度:每日 3,000 次請求(本腳本全跑一次約 450 次,綽綽有餘)。
依服務條款,前端顯示處需標示「Powered by ホットペッパーグルメ Webサービス」(r167 已內建)。
"""
import json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
OUTDIR = ROOT / "data" / "hp"

HOTPEPPER_KEY = ""  # ← 貼你的 Hot Pepper API KEY(https://webservice.recruit.co.jp/register/)
ENDPOINT = "https://webservice.recruit.co.jp/hotpepper/gourmet/v1/"
PAUSE = 0.35        # 額度寬鬆(3000/日),禮貌間隔即可
PAGES = 2           # 每點最多 2 頁 × 100 間 = 200 間(依人氣序,夠用)

def api(url):
    req = urllib.request.Request(url, headers={"User-Agent": "TabibiyoriBot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def parse_centers():
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
            if all(((la-x)**2+(lo-y)**2)**0.5 > 0.025 for x, y in chosen):
                chosen.append((la, lo))
            if len(chosen) >= 4:
                break
        pts += [(a, la, lo) for la, lo in chosen]
    return pts

def fetch_point(la, lo):
    out, start = [], 1
    for _ in range(PAGES):
        qs = (f"?key={HOTPEPPER_KEY}&lat={la}&lng={lo}&range=5&count=100&start={start}&format=json")
        try:
            j = api(ENDPOINT + qs)
        except Exception as e:
            print(f"  [warn] {e} @({la},{lo})"); break
        res = j.get("results", {})
        if "error" in res:
            print(f"  [err] {res['error']}"); sys.exit(1)
        shops = res.get("shop", [])
        for s in shops:
            img = (((s.get("photo") or {}).get("pc") or {}).get("m")) or (((s.get("photo") or {}).get("pc") or {}).get("l"))
            if not img:
                continue
            out.append({
                "n": s["name"], "la": float(s["lat"]), "lo": float(s["lng"]),
                "im": img, "g": (s.get("genre") or {}).get("name", ""),
                "b": (s.get("budget") or {}).get("name", ""),
                "u": ((s.get("urls") or {}).get("pc", "")),
                "ad": s.get("address", ""), "oh": s.get("open", ""),
            })
        got = int(res.get("results_returned") or 0)
        avail = int(res.get("results_available") or 0)
        start += got
        if start > avail or got == 0:
            break
        time.sleep(PAUSE)
    return out

def main():
    if not HOTPEPPER_KEY:
        print("請先在腳本內貼上 HOTPEPPER_KEY(https://webservice.recruit.co.jp/register/ 免費申請)")
        sys.exit(1)
    pts = parse_centers()
    print(f"取樣點: {len(pts)}")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    idx = []
    for i, (a, la, lo) in enumerate(pts):
        got = fetch_point(la, lo)
        # 點內去重
        seen, uniq = set(), []
        for s in got:
            k = s["n"] + f'@{s["la"]:.3f},{s["lo"]:.3f}'
            if k in seen:
                continue
            seen.add(k); uniq.append(s)
        fn = f"{i}.json"
        (OUTDIR / fn).write_text(json.dumps(uniq, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        idx.append({"la": round(la, 4), "lo": round(lo, 4), "f": fn, "c": len(uniq), "a": a})
        print(f"[{i+1}/{len(pts)}] {a} +{len(uniq)}")
        time.sleep(PAUSE)
    (OUTDIR / "index.json").write_text(json.dumps({"t": int(time.time()*1000), "p": idx},
                                                  ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    total = sum(x["c"] for x in idx)
    print(f"完成 → data/hp/  共 {len(idx)} 區塊 / {total} 間餐廳")

if __name__ == "__main__":
    main()
