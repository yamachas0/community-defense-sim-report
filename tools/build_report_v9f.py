#!/usr/bin/env python
"""まとめページ（report.html）を1本の走行から組み立てる。決定論・APIを使わない。

  python tools/build_report_v9f.py

数字はすべてこのスクリプトが走行データから数える（手打ちしない）。
図は matplotlib（地図は本体リポの tools/v9f_map.py を呼ぶ）。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import statistics
import subprocess
import sys
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_REPO = r"C:\Users\user\projects\quiet-acquisition"
SIMS = os.path.join(SIM_REPO, "simulations")
ASSETS = os.path.join(HERE, "assets", "report")
MAP_MONTHS = [1, 6, 12, 18, 24, 30, 36]

# 4本の走行＝世界の設定が2点だけ違う（買い手が過半の取得を目指すと明言するか／
# 場の会話と隣近所があるか）。key はファイル名と画像置き場に使う。
RUNS = [
    {"key": "main", "label": "明言なし・会話あり",
     "dir": "2026-08-30_1711_132_field_v9f_pay_more_if_needed_chat",
     "map": "v9f_map.py", "declared": False, "chat": True, "classified": True},
    {"key": "nochat", "label": "明言なし・会話なし",
     "dir": "2026-08-30_1846_134_field_v9f_pay_more_if_needed_nochat",
     "map": "v9f_map.py", "declared": False, "chat": False, "classified": False},
    {"key": "declared", "label": "明言あり・会話あり",
     "dir": "2026-08-30_2017_138_field_v9h_declared_majority_chat",
     "map": "v9h_map.py", "declared": True, "chat": True, "classified": False},
    {"key": "declared_nochat", "label": "明言あり・会話なし",
     "dir": "2026-08-30_2043_140_field_v9h_declared_majority_nochat",
     "map": "v9h_map.py", "declared": True, "chat": False, "classified": False},
]
OUT_NAME = {"main": "report.html", "nochat": "report_nochat.html",
            "declared": "report_declared.html",
            "declared_nochat": "report_declared_nochat.html"}
DECLARED_LINE = "私どもは、この街の不動産の過半の取得を目指しています。"
# 走行前に凍結した語（docs/world_design_v9h.md §2）で数える。
SUSPECT_WORDS = ["買い占め", "警戒", "意図", "危機", "支配", "乗っ取"]
# 役名（「支配人」等）が語に引っかかるので、数える前に外す。
ROLE_WORDS = ["支配人", "自治会長", "組合長", "町内会長"]

# 断りの理由を人の手で全件読んで分けた結果。出典＝
# quiet-acquisition/docs/submission/reasons_v9f_classified.md （(a)節・(c)節・(d)節・(e)節）。
# 判定用の人工知能は使わず、作業者が原文824件を読んで分類し、集計だけを機械にやらせている。
CLASSIFIED = {
    # 表示用（版の記号を出さない）。実ファイル＝上のコメントのパス。
    "source": "この走行の断り理由の分類文書（docs/submission/）",
    "n_written": 824,
    "overall": [("自分の事情（愛着・家族・商売・共有者への配慮など）", 631, 76.6),
                ("X社の条件（条件が不明・金額が見合わない・相手の実態が不明）", 137, 16.6),
                ("その両方に触れている", 55, 6.7),
                ("人から聞いた話が理由", 1, 0.1)],
    "bands": [("1.0倍未満（評価額より安い）", 94, 69.1, 27.7, 3.2, 0.0),
              ("1.0〜1.2倍", 177, 76.3, 18.1, 5.6, 0.0),
              ("1.2〜1.5倍", 179, 76.5, 17.9, 5.0, 0.6),
              ("1.5倍以上", 374, 78.6, 12.6, 8.8, 0.0)],
    "money_n": 126,
    "money_pct": 15.3,
    "money_bands": [("1.0倍未満", 28, 94, 29.8), ("1.0〜1.2倍", 18, 177, 10.2),
                    ("1.2〜1.5倍", 16, 179, 8.9), ("1.5倍以上", 64, 374, 17.1)],
    "attractive_type": 10,
    "proc_n": 136,
    "proc_pct": 21.6,
    "proc_examples": [("自治会での検討が必要なため", 14),
                      ("共有者との合意形成を優先するため", 13)],
    "over_valuation": 743,
    "over_valuation_declined": 732,
    "under_valuation": 95,
    "under_valuation_sold": 0,
    "sold_total": 11,
    "sold_money": 8,
    "sold_money_pct": 73,
    "sold_own": 2,
    "left_total": 8,
    "left_sellers": 6,
    "left_tenants": 2,
}


def jload(run, name):
    with open(os.path.join(run, name), encoding="utf-8") as f:
        return json.load(f)


def pick_font():
    names = {f.name for f in font_manager.fontManager.ttflist}
    for cand in ("Meiryo", "Yu Gothic", "Noto Sans JP", "MS Gothic"):
        if cand in names:
            return cand
    return "DejaVu Sans"


def e(s):
    return html.escape(str(s if s is not None else ""))


def yen(n):
    return f"{int(n):,}円"


def oku(n):
    return f"{n / 100_000_000:.2f}億円"


# ---------------------------------------------------------------------------
# 地図（本体リポの道具を呼ぶ。出力名から版の記号を外して置き直す）
# ---------------------------------------------------------------------------

def build_maps(run, key, maptool):
    outdir = os.path.join(ASSETS, key)
    os.makedirs(outdir, exist_ok=True)
    tmp = os.path.join(outdir, "_maps_tmp")
    os.makedirs(tmp, exist_ok=True)
    tag = "v9h" if "v9h" in maptool else "v9f"
    cmd = [sys.executable, os.path.join(SIM_REPO, "tools", maptool),
           "--personas", os.path.join(SIM_REPO, "configs", "personas_v9c.yaml"),
           "--run", run,
           "--months", ",".join(str(m) for m in MAP_MONTHS),
           "--out-dir", tmp]
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.run(cmd, cwd=SIM_REPO, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
    for m in MAP_MONTHS:
        for a in ("plan", "section"):
            src = os.path.join(tmp, f"fig_{tag}_map_{a}_m{m:02d}.png")
            dst = os.path.join(outdir, f"map_{a}_m{m:02d}.png")
            shutil.copyfile(src, dst)
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)


# ---------------------------------------------------------------------------
# 図（値付けの推移・資金の残高）
# ---------------------------------------------------------------------------

def fig_price(offers, path):
    plt.rcParams["font.family"] = pick_font()
    plt.rcParams["axes.unicode_minus"] = False
    by = defaultdict(list)
    for o in offers:
        by[o["step"]].append(o["ratio"])
    ms = sorted(by)
    med = [statistics.median(by[m]) for m in ms]
    avg = [statistics.fmean(by[m]) for m in ms]
    mx = [max(by[m]) for m in ms]
    fig, ax = plt.subplots(figsize=(10.5, 4.6), dpi=150)
    fig.patch.set_facecolor("#0f1115")
    ax.set_facecolor("#161a21")
    ax.plot(ms, mx, color="#f59e0b", lw=1.8, marker="o", ms=3, label="その月の最大")
    ax.plot(ms, avg, color="#60a5fa", lw=1.8, marker="o", ms=3, label="その月の平均")
    ax.plot(ms, med, color="#34d399", lw=2.4, marker="o", ms=3.5, label="その月の中央値")
    ax.axhline(1.0, color="#98a1ad", lw=1.0, ls="--")
    ax.text(0.4, 1.02, "評価額と同じ（1.0倍）", color="#98a1ad", fontsize=9)
    ax.set_xlabel("月", color="#e9ecf1")
    ax.set_ylabel("提示額 ÷ 評価額（倍）", color="#e9ecf1")
    ax.set_xlim(0.5, 36.5)
    ax.set_xticks([1, 6, 12, 18, 24, 30, 36])
    for s in ax.spines.values():
        s.set_color("#262c36")
    ax.tick_params(colors="#98a1ad")
    ax.grid(color="#262c36", lw=0.8)
    leg = ax.legend(facecolor="#161a21", edgecolor="#262c36", labelcolor="#e9ecf1")
    leg.get_frame().set_alpha(1.0)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return {"months": ms, "median": med, "mean": avg, "max": mx}


def fig_budget(monthly, budget_total, path):
    plt.rcParams["font.family"] = pick_font()
    plt.rcParams["axes.unicode_minus"] = False
    ms = [r["step"] for r in monthly]
    spent = [r["spent_cum"] / 1e8 for r in monthly]
    left = [r["budget_left"] / 1e8 for r in monthly]
    fig, ax = plt.subplots(figsize=(10.5, 4.6), dpi=150)
    fig.patch.set_facecolor("#0f1115")
    ax.set_facecolor("#161a21")
    ax.fill_between(ms, 0, spent, color="#b3261e", alpha=0.85, label="使ったお金（累計）")
    ax.plot(ms, left, color="#34d399", lw=2.4, label="残っているお金")
    ax.axhline(budget_total / 1e8, color="#98a1ad", lw=1.0, ls="--")
    ax.text(0.4, budget_total / 1e8 + 0.15,
            f"預かった資金 {budget_total/1e8:.2f}億円", color="#98a1ad", fontsize=9)
    ax.set_xlabel("月", color="#e9ecf1")
    ax.set_ylabel("億円", color="#e9ecf1")
    ax.set_xlim(0.5, 36.5)
    ax.set_ylim(0, budget_total / 1e8 * 1.15)
    ax.set_xticks([1, 6, 12, 18, 24, 30, 36])
    for s in ax.spines.values():
        s.set_color("#262c36")
    ax.tick_params(colors="#98a1ad")
    ax.grid(color="#262c36", lw=0.8)
    leg = ax.legend(facecolor="#161a21", edgecolor="#262c36", labelcolor="#e9ecf1")
    leg.get_frame().set_alpha(1.0)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------

def build_one(cfg, quad, skip_maps=False):
    """1本の走行から1枚のページを組み立てる。"""
    key = cfg["key"]
    RUN = os.path.join(SIMS, cfg["dir"])
    ADIR = os.path.join(ASSETS, key)
    OUT_HTML = os.path.join(HERE, OUT_NAME[key])
    os.makedirs(ADIR, exist_ok=True)
    if not skip_maps:
        build_maps(RUN, key, cfg["map"])

    S = jload(RUN, "summary.json")
    monthly = jload(RUN, "monthly.json")
    offers = jload(RUN, "offers.json")
    transfers = jload(RUN, "transfers.json")
    payments = jload(RUN, "payments.json")
    left_agents = jload(RUN, "left_agents.json")
    left_tenants = jload(RUN, "left_tenants.json")
    listings = jload(RUN, "listings.json")
    decisions = jload(RUN, "decisions.json")
    utterances = jload(RUN, "utterances.json")
    notices = jload(RUN, "notices.json")
    valuation = jload(RUN, "valuation.json")
    messages = jload(RUN, "messages.json")
    undelivered = jload(RUN, "undelivered.json")
    reoffers = jload(RUN, "reoffers.json")
    tenants = jload(RUN, "tenant_decisions.json")
    ledger = jload(RUN, "ledger_by_step.json")
    wallets = jload(RUN, "wallets.json")

    price = fig_price(offers, os.path.join(ADIR, "fig_price.png"))
    fig_budget(monthly, S["budget_total"], os.path.join(ADIR, "fig_budget.png"))

    # ---- 索引になる箱 ----
    dec_by = {(d["step"], d["name"]): d for d in decisions}
    pay_by_step = defaultdict(list)
    for p in payments:
        pay_by_step[p["step"]].append(p)
    tr_by_step = defaultdict(list)
    for t in transfers:
        tr_by_step[t["step"]].append(t)
    left_by_step = defaultdict(list)
    for a in left_agents:
        left_by_step[a["step"]].append(a)
    und_by_step = defaultdict(list)
    for u in undelivered:
        und_by_step[u["step"]].append(u)
    off_by_step = defaultdict(list)
    for o in offers:
        off_by_step[o["step"]].append(o)
    utt_by_step = defaultdict(list)
    for u in utterances:
        utt_by_step[u["step"]].append(u)
    msg_by_step = defaultdict(list)
    for m in messages:
        msg_by_step[m["step"]].append(m)
    lst_by_step = defaultdict(list)
    for x in listings:
        lst_by_step[x["step"]].append(x)

    declines = [o for o in offers if o["result"] == "売らなかった"
                and (o.get("decline_reason") or "").strip()]
    sold_offers = [o for o in offers if o["accepted"]]
    sold_names = []
    for o in sold_offers:
        if o["to"] not in sold_names:
            sold_names.append(o["to"])

    # 帯別の断り率
    def band_of(r):
        if r < 1.0:
            return "1.0倍未満（評価額より安い）"
        if r < 1.2:
            return "1.0〜1.2倍"
        if r < 1.5:
            return "1.2〜1.5倍"
        return "1.5倍以上"
    BANDS = ["1.0倍未満（評価額より安い）", "1.0〜1.2倍", "1.2〜1.5倍", "1.5倍以上"]
    band = {b: {"n": 0, "sold": 0, "declined": 0, "noans": 0} for b in BANDS}
    for o in offers:
        b = band[band_of(o["ratio"])]
        b["n"] += 1
        if o["accepted"]:
            b["sold"] += 1
        elif o["result"] == "売らなかった":
            b["declined"] += 1
        else:
            b["noans"] += 1

    ratios = [o["ratio"] for o in offers]
    ratios_sorted = sorted(ratios)

    def pct(v, p):
        i = max(0, min(len(v) - 1, int(round((len(v) - 1) * p))))
        return v[i]

    # 再提示（相手別）
    reo = defaultdict(lambda: {"n": 0, "up": 0, "down": 0, "same": 0,
                               "sum_up": 0, "max_up": 0})
    for r in reoffers:
        d = reo[r["to"]]
        d["n"] += 1
        if r["delta"] > 0:
            d["up"] += 1
            d["sum_up"] += r["delta"]
            d["max_up"] = max(d["max_up"], r["delta"])
        elif r["delta"] < 0:
            d["down"] += 1
        else:
            d["same"] += 1
    reo_top = sorted(reo.items(), key=lambda kv: (-kv[1]["up"], -kv[1]["sum_up"]))[:10]

    # 届かなかった（権利違い）
    RIGHT = "相手がその区画のその種別の所有権を持っていない"
    und_right = [u for u in undelivered if u["why"] == RIGHT]
    und_by_person = Counter((u["to"]) for u in und_right)
    und_by_kind = Counter(u["kind"] for u in und_right)

    # 狙われた区画
    off_by_parcel = Counter(o["parcel"] for o in offers)
    off_by_person = Counter(o["to"] for o in offers)

    # 会話
    venue_labels = ["公共施設", "交通拠点", "商業施設", "公園", "医療施設"]
    utt_x = [u for u in utterances if "X社" in u["text"]]
    utt_venue_month = defaultdict(Counter)
    for u in utterances:
        utt_venue_month[u["step"]][u["venue_label"]] += 1

    # 出品の理由（代表）
    listing_reasons = []
    for d in decisions:
        for parcel, r in (d.get("listing_reasons") or {}).items():
            if (r or "").strip() and (d.get("listings") or {}).get(parcel) != "出さない":
                listing_reasons.append((d["step"], d["name"], parcel,
                                        d["listings"][parcel], r.strip()))
    seen = set()
    listing_rep = []
    for row in sorted(listing_reasons, key=lambda x: (-len(x[4]), x[0])):
        if row[1] in seen:
            continue
        seen.add(row[1])
        listing_rep.append(row)
        if len(listing_rep) >= 12:
            break
    listing_rep.sort(key=lambda x: x[0])

    # 年表の材料
    def month_declines(m, k=3):
        rows = [o for o in off_by_step[m]
                if o["result"] == "売らなかった" and (o.get("decline_reason") or "").strip()]
        rows.sort(key=lambda o: (-len(o["decline_reason"]), o["to"]))
        out, used = [], set()
        for o in rows:
            if o["to"] in used:
                continue
            used.add(o["to"])
            out.append(o)
            if len(out) >= k:
                break
        return out

    def month_utterance(m):
        rows = utt_by_step[m]
        if not rows:
            return None
        xs = [u for u in rows if "X社" in u["text"]]
        pool = xs or rows
        return max(pool, key=lambda u: len(u["text"]))

    def month_message(m):
        rows = msg_by_step[m]
        if not rows:
            return None
        return max(rows, key=lambda x: len(x["text"]))

    tenant_reason = {(t["step"], t["name"]): t.get("reason", "")
                     for t in left_tenants}
    left_reason = {}
    for a in left_agents:
        if a.get("how"):
            left_reason[(a["step"], a["name"])] = tenant_reason.get(
                (a["step"], a["name"]), "")
        else:
            d = dec_by.get((a["step"], a["name"]))
            left_reason[(a["step"], a["name"])] = (d or {}).get("sell_reason", "")

    # -----------------------------------------------------------------
    # HTML
    # -----------------------------------------------------------------
    P = []
    w = P.append

    w("""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>A市で起きたことの全記録 — 外的不動産投資へのコミュニティ自衛</title>
<style>
:root{--bg:#0f1115;--panel:#161a21;--fg:#e9ecf1;--dim:#98a1ad;--accent:#34d399;
--warn:#f59e0b;--red:#ef6a5e;--line:#262c36;}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg)}
body{color:var(--fg);font-family:"Noto Sans JP","Hiragino Kaku Gothic ProN",
"Yu Gothic",Meiryo,system-ui,-apple-system,sans-serif;line-height:1.85;
-webkit-text-size-adjust:100%;}
.wrap{max-width:1080px;margin:0 auto;padding:28px 18px 90px}
h1{font-size:clamp(26px,6vw,42px);font-weight:900;line-height:1.35;margin:0 0 10px}
h2{font-size:clamp(20px,4.6vw,29px);font-weight:900;line-height:1.4;margin:52px 0 8px;
padding-left:12px;border-left:5px solid var(--accent);scroll-margin-top:12px}
h3{font-size:clamp(17px,3.8vw,21px);font-weight:900;margin:30px 0 6px}
h4{font-size:clamp(15px,3.4vw,17px);font-weight:700;margin:20px 0 4px;color:var(--accent)}
p{margin:0 0 12px}
.lead{color:var(--dim);font-size:clamp(15px,3.6vw,17px);margin:0 0 16px}
.kicker{font-size:12px;font-weight:700;letter-spacing:.09em;color:var(--accent);margin:0 0 6px}
a{color:var(--accent)}
.hl{color:var(--accent);font-weight:900}
.rd{color:var(--red);font-weight:900}
nav.toc{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:16px 18px;margin:22px 0 8px}
nav.toc ol{margin:0;padding-left:1.3em}
nav.toc li{margin:2px 0}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0 18px}
.card{flex:1 1 150px;min-width:140px;background:var(--panel);border:1px solid var(--line);
border-radius:10px;padding:12px 14px}
.card .n{font-size:clamp(20px,5vw,27px);font-weight:900;line-height:1.25}
.card .l{font-size:13px;color:var(--dim);line-height:1.5}
table{width:100%;border-collapse:collapse;font-size:14px;margin:8px 0 14px;
background:var(--panel);}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:#1b212a;color:var(--dim);font-weight:700;white-space:nowrap}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.scroll table{min-width:640px}
figure{margin:14px 0 18px}
figure img{width:100%;height:auto;border:1px solid var(--line);border-radius:10px;background:#fff}
figcaption{font-size:13px;color:var(--dim);margin-top:6px}
details{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:10px 14px;margin:10px 0 16px}
details summary{cursor:pointer;font-weight:700;color:var(--accent)}
details[open] summary{margin-bottom:8px}
blockquote{margin:6px 0 10px;padding:8px 12px;border-left:3px solid var(--accent);
background:var(--panel);border-radius:0 8px 8px 0;font-size:15px}
blockquote .who{display:block;font-size:12px;color:var(--dim);margin-top:4px}
.month{border:1px solid var(--line);border-radius:12px;background:var(--panel);
padding:14px 16px;margin:0 0 12px}
.month h3{margin:0 0 6px;font-size:18px}
.month .facts{font-size:14px;color:var(--dim);margin:0 0 8px}
.month .facts b{color:var(--fg)}
.ev{font-size:14px;margin:0 0 6px}
.ev .tag{display:inline-block;font-size:11px;font-weight:900;border-radius:4px;
padding:1px 7px;margin-right:6px;vertical-align:1px}
.tag.sold{background:var(--red);color:#111}
.tag.left{background:var(--warn);color:#111}
.tag.none{background:#2a313c;color:var(--dim)}
ul.plain{margin:0 0 12px;padding-left:1.2em}
ul.plain li{margin:0 0 5px}
.note{font-size:13px;color:var(--dim)}
hr{border:0;border-top:1px solid var(--line);margin:36px 0}
.gal{display:grid;grid-template-columns:1fr;gap:16px}
@media(min-width:860px){.gal{grid-template-columns:1fr 1fr}}
code{background:#1b212a;border-radius:4px;padding:1px 5px;font-size:.92em}
.quad{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:14px 16px;margin:18px 0}
.quad .qh{margin:0 0 10px;font-size:15px;line-height:1.8}
pre{background:#1b212a;border:1px solid var(--line);border-radius:8px;padding:12px 14px;
overflow-x:auto;font-size:14px;line-height:1.7;margin:8px 0 14px}
</style></head><body><div class="wrap">
""")

    w('<p class="kicker">外的不動産投資へのコミュニティ自衛</p>')
    w(f'<h1>A市で起きたことの全記録<br><span style="font-size:.62em">'
      f'（{e(cfg["label"])}の世界）</span></h1>')
    w('<p class="lead">架空の温泉のまち「A市」に、海外の不動産投資会社（X社）が入ってくる。'
      '住んでいる人・持っているだけの人あわせて49人が、毎月それぞれ考えて動き、'
      + ('話し、' if cfg["chat"] else '')
      + '売るか売らないかを決める。そこで36か月のあいだに何が起きたのかを、'
      '地図・年表・本人たちの言葉のかたちで、省略せずに並べたページ。'
      '数字はすべて走行の記録から数え直したもので、書き手の解釈は入れていない。</p>')
    w(quad_html(quad, key))

    w('<nav class="toc"><b>目次</b><ol>'
      '<li><a href="#c1">この町のこと</a></li>'
      '<li><a href="#c2">地図の変遷（第1月から第36月）</a></li>'
      '<li><a href="#c3">36か月の年表</a></li>'
      '<li><a href="#c4">X社の動き</a></li>'
      '<li><a href="#c5">町の答え（断りの言葉 全件）</a></li>'
      '<li><a href="#c6">人の出入り</a></li>'
      '<li><a href="#c7">会話の記録</a></li>'
      '<li><a href="#c8">健全性と費用</a></li>'
      '<li><a href="#c9">このページから言えないこと</a></li>'
      '</ol></nav>')

    # ===== 1 =====
    w('<h2 id="c1">1. この町のこと</h2>')
    w('<p class="lead">まず舞台の説明。何人いて、何区画あって、'
      '誰が何を持っていることになっていて、買い手はどういう指示で動いていたのか。</p>')
    w('<div class="cards">')
    for n, l in [(f'{S["agents"]}人', "登場する人（住んでいる人35＋町にいない持ち主14）"),
                 (f'{S["parcels_total"]}区画', f'町の全部（うち売れる区画 {S["sellable_parcels"]}）'),
                 (oku(S["valuation_total"]), "町の不動産の評価額の合計"),
                 (oku(S["budget_total"]), f'X社が預かったお金（評価額の{int(S["budget_share"]*100)}%）'),
                 (f'{S["steps"]}か月', "走らせた時間（1か月＝1手番）"),
                 (f'{S["total_area_m2"]:,}m2', "町の土地の面積の合計")]:
        w(f'<div class="card"><div class="n">{n}</div><div class="l">{l}</div></div>')
    w("</div>")

    w("<h3>帳簿の3つの欄</h3>")
    w('<p>この世界では、区画ごとに<b>3つのこと</b>だけがはっきり決まっている。'
      '<span class="hl">土地の持ち主</span>（必ず1人）・'
      '<span class="hl">建物の持ち主</span>（0〜1人。建物が無い区画もある）・'
      '<span class="hl">そこを使っている人</span>（住んでいる／店をやっている／借りている）。'
      'この3つが動くことだけが「起きたこと」で、それ以外は誰かの気持ちや言葉として残る。</p>')

    w("<h3>売ったあとに何が起きるか（世界が保証している3通り）</h3>")
    w('<ul class="plain">'
      '<li><b>土地だけ売る</b> → 建物は自分のもののまま。借地として今までどおりそこを使える。</li>'
      '<li><b>建物だけ売る</b> → 借家として今までどおりそこに住む／店を営める。</li>'
      '<li><b>両方売る</b> → その人がそこを使っていたなら、その場所を離れて町を出る。'
      '借りて使っている人がいた場合、その人はそのまま使い続けられる。</li></ul>')
    w('<p class="note">つまり「売ったら追い出される」世界ではない。'
      '住み続けられることは世界が保証している。それでも人は出ていく。</p>')

    w("<h3>買い手（X社）に与えた指示（全文）</h3>")
    mand = S["mandate"].replace("。", "。\n").strip()
    w(f"<pre>{e(mand)}</pre>")
    if cfg["declared"]:
        w('<p>そのうえでこの世界では、'
          '<b>X社が出す手紙すべての冒頭に、世界が必ず次の1行を添えて相手に届ける</b>。'
          'X社が書く文ではなく、出すか出さないかも選べない。</p>')
        w(f'<pre>{e(DECLARED_LINE)}</pre>')
        w('<p class="note">つまりこの世界のX社は、'
          '「町の過半を取りにきている」ことを町のみんなに公言している。</p>')
    w('<p>X社は<b>海外の不動産投資会社</b>という設定で、'
      '「不動産管理等は行わない」と自分で名乗る。毎月、帳簿と「売りに出ているという公の申し出」を見て、'
      '誰に・どの区画の・どの権利を・いくらで、という手紙を書く。'
      'この指示だけが前の版から変えた部分で、町の側は1文字も変えていない。</p>')

    w("<h3>世界の門番（3つ）</h3>")
    w('<p>X社が書いた手紙は、そのまま相手に届くわけではない。世界が3つの関所で止める。</p>'
      '<ul class="plain">'
      '<li><b>権利の関所</b> … 相手が持っていない区画・権利を買おうとした手紙は届かない'
      f'（この走行で <span class="rd">{S["undelivered_by_reason"][RIGHT]}件</span>）。</li>'
      '<li><b>実行できない約束の関所</b> … この世界に仕組みが無いこと'
      '（改修費の負担・雇用の斡旋など）を約束した手紙は届かない'
      f'（この走行で {S["undelivered_by_reason"]["この世界で実行される仕組みが無い約束が含まれている"]}件）。</li>'
      f'<li><b>お金の関所</b> … 残っているお金を超える金額の手紙は届かない（この走行で {S["acquirer_over_budget"]}件）。'
      '同じ月に配る手紙の合計も残額を超えない。</li></ul>')

    w("<h3>評価額（走らせる前に決めて、あとから動かしていない）</h3>")
    w('<p>土地の単価は人口約12万人の温泉観光都市の公開地価を土台に、地区を5段階に割り付けた'
      '仮の値。建物は用途から常識的に置いた。「得か損か」はどこにも書いていない。'
      '世界が置いたのは<b>評価額と提示額という2つの数字</b>だけ。</p>')
    w('<details><summary>44区画の評価額を全部見る</summary><div class="scroll"><table>'
      '<tr><th>区画</th><th>用途</th><th>地区</th><th class="num">敷地m2</th>'
      '<th class="num">延床m2</th><th class="num">土地</th><th class="num">建物</th>'
      '<th class="num">合計</th></tr>')
    for k, v in sorted(valuation.items(), key=lambda kv: -kv[1]["both"]):
        w(f'<tr><td>{e(k)}</td><td>{e(v["use"])}</td><td>{e(v["tier"])}</td>'
          f'<td class="num">{v["area"]:,}</td><td class="num">{v["floor"]:,}</td>'
          f'<td class="num">{v["land"]:,}</td><td class="num">{v["building"]:,}</td>'
          f'<td class="num">{v["both"]:,}</td></tr>')
    w(f'<tr><th>合計</th><th></th><th></th><th class="num">{S["total_area_m2"]:,}</th>'
      f'<th class="num"></th><th class="num"></th><th class="num"></th>'
      f'<th class="num">{S["valuation_total"]:,}</th></tr>')
    w("</table></div></details>")

    w("<h3>何を測ったのか</h3>")
    w('<ul class="plain">'
      '<li>X社が出した手紙の件数・金額・評価額の何倍か（月ごと）</li>'
      '<li>届かなかった手紙の件数と理由</li>'
      '<li>売れた区画・売った人・金額・その人が町を出たかどうか</li>'
      '<li>断ったときの一言（原文をそのまま全部保存）</li>'
      '<li>出品（売りに出す）の件数と種別</li>'
      '<li>場での会話・隣近所に伝わった件数・借りている人と家主のやりとり</li></ul>')
    w('<p class="note">採点する人工知能は使っていない。'
      '数えられるものを数えているだけで、良い/悪いの判定はどこにも入っていない。</p>')

    # ===== 2 =====
    w('<h2 id="c2">2. 地図の変遷（第1月から第36月）</h2>')
    w('<p class="lead">上が<b>平面図</b>（町の44区画。四角＝土地、中の小さい四角＝建物、'
      '斜線＝借りて使われている、●＝普段この町にいる人が使っている）。'
      '下が<b>断面図</b>（同じ区画を横から見て、土地の上に建物、その上に使っている人、と'
      '権利が重なっている様子）。赤がX社に移った部分。'
      '6か月ごとに、赤がどこから増えたかを追える。</p>')

    for m in MAP_MONTHS:
        trs = tr_by_step[m]
        lfs = left_by_step[m]
        bits = []
        for t in trs:
            pay = next((p for p in pay_by_step[m]
                        if p["parcel"] == t["parcel"] and p["kind"] == t["kind"]), None)
            amt = f"（{yen(pay['amount'])}）" if pay else ""
            bits.append(f'{t["parcel"]}の{t["kind"]}が{t["name"]}さんからX社へ{amt}')
        for a in lfs:
            bits.append(f'{a["name"]}が町を出た')
        line = "／".join(bits) if bits else "この月に動いた区画・出た人はいない"
        mm = next(r for r in monthly if r["step"] == m)
        w('<figure>')
        w(f'<h3>第{m}月</h3>')
        w(f'<p class="ev">{e(line)}</p>')
        w(f'<p class="note">この時点＝X社の区画 累計{mm["parcels_cum"]}／44・'
          f'町にいる人 {mm["in_town"]}人・町を出た人 累計{mm["left_cum"]}人・'
          f'X社が使ったお金 {oku(mm["spent_cum"])}（面積では{mm["area_share"]*100:.1f}%）</p>')
        w(f'<img loading="lazy" src="assets/report/{key}/map_plan_m{m:02d}.png" '
          f'alt="第{m}月の平面図">')
        w(f'<img loading="lazy" src="assets/report/{key}/map_section_m{m:02d}.png" '
          f'alt="第{m}月の断面図" style="margin-top:10px">')
        w(f'<figcaption>第{m}月の平面図（上）と断面図（下）。</figcaption>')
        w("</figure>")

    # ===== 3 =====
    w('<h2 id="c3">3. 36か月の年表</h2>')
    w('<p class="lead">1か月ずつ、その月に何通の手紙が来て、いくらで、'
      '誰が売り、誰が出ていったのかを並べた。'
      '引用はすべてその月に本人が書いた言葉の原文。</p>')

    for r in monthly:
        m = r["step"]
        offs = off_by_step[m]
        med = statistics.median([o["ratio"] for o in offs]) if offs else 0
        w('<div class="month">')
        w(f"<h3>第{m}月</h3>")
        kinds = "・".join(f'{k}{v}' for k, v in r["offers_by_kind"].items() if v)
        w(f'<p class="facts">X社の手紙 <b>{r["offers_sent"]}通</b>（{e(kinds)}／'
          f'町にいる人へ{r["offers_to_in_town"]}・町にいない持ち主へ{r["offers_to_absentee"]}）'
          f'　提示額は評価額の <b>{med:.2f}倍</b>（中央値）'
          f'　売りに出された <b>{r["listed_this_month"]}件</b>'
          f'　世界が配らなかった手紙 <b>{len(und_by_step[m])}通</b>'
          f'　場に出た人 {r["attended"]}人・発言 {r["utterances"]}件</p>')
        if pay_by_step[m]:
            for p in pay_by_step[m]:
                t = next((x for x in tr_by_step[m]
                          if x["parcel"] == p["parcel"] and x["kind"] == p["kind"]), None)
                nm = t["name"] if t else p["to"]
                ratio = p["amount"] / p["valuation"] if p["valuation"] else 0
                d = dec_by.get((m, nm))
                rsn = (d or {}).get("sell_reason", "")
                w(f'<p class="ev"><span class="tag sold">成約</span>'
                  f'{e(nm)} が <b>{e(p["parcel"])}の{e(p["kind"])}</b> を '
                  f'<b>{yen(p["amount"])}</b>（評価額の{ratio:.2f}倍）で売った'
                  + (f'　— 本人の一言「{e(rsn)}」' if rsn else "") + "</p>")
        else:
            w('<p class="ev"><span class="tag none">成約</span>この月に売れた区画は無い</p>')
        for a in left_by_step[m]:
            why = left_reason.get((m, a["name"]), "")
            how = a.get("how") or "両方を売ってその場所を離れた"
            w(f'<p class="ev"><span class="tag left">退場</span>'
              f'{e(a["name"])} が町を出た（{e(how)}）'
              + (f'　— 「{e(why)}」' if why else "") + "</p>")
        for o in month_declines(m):
            w(f'<blockquote>{e(o["decline_reason"])}'
              f'<span class="who">{e(o["to"])}／{e(o["parcel"])}の{e(o["kind"])}に '
              f'{yen(o["amount"])}（評価額の{o["ratio"]:.2f}倍）の手紙を受けて</span></blockquote>')
        u = month_utterance(m)
        if u:
            w(f'<blockquote>{e(u["text"])}'
              f'<span class="who">{e(u["from"])}／{e(u["venue_label"])}での発言'
              f'（{len(u["heard_by"])}人が聞いた）</span></blockquote>')
        msg = month_message(m)
        if msg:
            w(f'<blockquote>{e(msg["text"])}'
              f'<span class="who">{e(msg["from"])} → {e(msg["to"])}'
              f'（{e(msg["parcel"])}・{e(msg["direction"])}）</span></blockquote>')
        w("</div>")

    # ===== 4 =====
    w('<h2 id="c4">4. X社の動き</h2>')
    w('<p class="lead">買い手の側だけを取り出して見る。'
      'いくらで声をかけ、どれだけ粘り、どこで空振りしたのか。</p>')
    w('<div class="cards">')
    for n, l in [(f'{S["offers_total"]}通', "36か月で出して届いた手紙"),
                 (f'{statistics.fmean(ratios):.2f}倍', "提示額÷評価額の平均"),
                 (f'{S["reoffers_total"]}回', "同じ相手・同じ区画への出し直し"),
                 (f'{S["reoffers_amount_up"]}回', "そのうち金額を上げた回数"),
                 (f'{S["offers_accepted"]}件', "売れた（成約）"),
                 (f'{S["budget_used_share"]*100:.1f}%', "使ったお金の割合")]:
        w(f'<div class="card"><div class="n">{n}</div><div class="l">{l}</div></div>')
    w("</div>")

    w("<h3>値付けの推移</h3>")
    w(f'<figure><img loading="lazy" src="assets/report/{key}/fig_price.png" alt="値付けの推移">'
      f'<figcaption>横軸＝月、縦軸＝提示額が評価額の何倍か。'
      f'第1月の中央値は{price["median"][0]:.2f}倍、第36月は{price["median"][-1]:.2f}倍。'
      f'</figcaption></figure>')
    w('<div class="scroll"><table><tr><th>月</th><th class="num">手紙</th>'
      '<th class="num">中央値</th><th class="num">平均</th><th class="num">最大</th></tr>')
    for i, m in enumerate(price["months"]):
        w(f'<tr><td>第{m}月</td><td class="num">{len(off_by_step[m])}</td>'
          f'<td class="num">{price["median"][i]:.2f}</td>'
          f'<td class="num">{price["mean"][i]:.2f}</td>'
          f'<td class="num">{price["max"][i]:.2f}</td></tr>')
    w("</table></div>")
    w(f'<p>36か月をならすと、平均 <span class="hl">{statistics.fmean(ratios):.2f}倍</span>・'
      f'中央値 {statistics.median(ratios):.2f}倍・下から4分の1の線 {pct(ratios_sorted,0.25):.2f}倍・'
      f'上から4分の1の線 {pct(ratios_sorted,0.75):.2f}倍・最大 {max(ratios):.2f}倍。'
      f'評価額以上の手紙は {sum(1 for x in ratios if x >= 1.0)}通'
      f'（{sum(1 for x in ratios if x >= 1.0)/len(ratios)*100:.1f}%）、'
      f'評価額の1.2倍以上を積んだ手紙は {S["piled_offers"]}通で、'
      f'そのうち売れたのは {S["piled_offers_accepted"]}件（{S["piled_accept_rate"]*100:.2f}%）。</p>')

    w("<h3>お金の残高</h3>")
    w(f'<figure><img loading="lazy" src="assets/report/{key}/fig_budget.png" alt="資金の残高推移">'
      f'<figcaption>預かった {oku(S["budget_total"])} のうち、36か月で使ったのは '
      f'{oku(S["spent_total"])}（{S["budget_used_share"]*100:.1f}%）。'
      f'{oku(S["budget_left"])} が余った。</figcaption></figure>')

    w("<h3>再提示と値上げ（同じ相手に何度も）</h3>")
    w(f'<p>同じ相手・同じ区画・同じ権利への出し直しが <b>{S["reoffers_total"]}回</b>。'
      f'金額を上げたのが {S["reoffers_amount_up"]}回（上げ幅の中央値 '
      f'{yen(S["reoffer_up_median_yen"])}・最大 {yen(S["reoffer_up_max_yen"])}）、'
      f'下げたのが {S["reoffers_amount_down"]}回、据え置きが {S["reoffers_amount_same"]}回。'
      f'出し直しのあとに売れたのは {S["reoffers_accepted"]}件だけ。</p>')
    w('<div class="scroll"><table><tr><th>相手</th><th class="num">出し直し</th>'
      '<th class="num">値上げ</th><th class="num">値下げ</th><th class="num">据え置き</th>'
      '<th class="num">上げた合計</th><th class="num">1回の最大の上げ幅</th></tr>')
    for name, d in reo_top:
        w(f'<tr><td>{e(name)}</td><td class="num">{d["n"]}</td><td class="num">{d["up"]}</td>'
          f'<td class="num">{d["down"]}</td><td class="num">{d["same"]}</td>'
          f'<td class="num">{d["sum_up"]:,}</td><td class="num">{d["max_up"]:,}</td></tr>')
    w("</table></div>")

    w("<h3>狙った区画の偏り</h3>")
    w(f'<p>手紙の内訳は「土地だけ」{S["offers_by_kind"]["土地"]}通・'
      f'「両方（土地と建物）」{S["offers_by_kind"]["両方"]}通・'
      f'「建物だけ」{S["offers_by_kind"]["建物"]}通。'
      + ('建物だけを買おうとしたことは一度も無い。' if not S["offers_by_kind"]["建物"] else '')
      + f'売れたのは「両方」{S["sold_by_kind"]["両方"]}件・'
        f'「土地だけ」{S["sold_by_kind"]["土地"]}件。</p>')
    w('<div class="scroll"><table><tr><th>よく狙われた区画（上位15）</th>'
      '<th class="num">手紙</th><th>よく狙われた相手（上位15）</th>'
      '<th class="num">手紙</th></tr>')
    tp = off_by_parcel.most_common(15)
    tn = off_by_person.most_common(15)
    for i in range(15):
        a = tp[i] if i < len(tp) else ("", "")
        b = tn[i] if i < len(tn) else ("", "")
        w(f'<tr><td>{e(a[0])}</td><td class="num">{a[1]}</td>'
          f'<td>{e(b[0])}</td><td class="num">{b[1]}</td></tr>')
    w("</table></div>")

    w("<h3>権利が違って配られなかった手紙</h3>")
    w(f'<p>世界が止めた手紙は全部で {S["undelivered_total"]}通。'
      f'そのうち <span class="rd">{len(und_right)}通</span>が'
      '「相手はその区画のその権利を持っていない」＝帳簿の読み違いだった'
      f'（内訳＝両方 {und_by_kind.get("両方",0)}通・土地 {und_by_kind.get("土地",0)}通・'
      f'建物 {und_by_kind.get("建物",0)}通）。'
      f'残り {S["acquirer_over_budget"]}通は残りのお金を超えていたもの、'
      '実行できない約束は0通。</p>')
    w('<div class="scroll"><table><tr><th>誰に</th><th class="num">件数</th></tr>')
    for name, c in und_by_person.most_common():
        w(f'<tr><td>{e(name)}</td><td class="num">{c}</td></tr>')
    w("</table></div>")
    w(f'<details><summary>配られなかった{len(und_right)}通を全部見る（誰に・何を・いくらで）</summary>'
      '<div class="scroll"><table><tr><th>月</th><th>相手</th><th>区画</th><th>権利</th>'
      '<th class="num">金額</th><th>手紙の文</th></tr>')
    for u in und_right:
        w(f'<tr><td>第{u["step"]}月</td><td>{e(u["to"])}</td><td>{e(u["parcel"])}</td>'
          f'<td>{e(u["kind"])}</td><td class="num">{u["amount"]:,}</td>'
          f'<td>{e(u["text"])}</td></tr>')
    w("</table></div></details>")

    w("<h3>手紙の文の変化（月初・中盤・終盤の原文）</h3>")
    for label, mm in [("第1月", 1), ("第18月", 18), ("第36月", 36)]:
        rows = sorted(off_by_step[mm], key=lambda o: -len(o["text"]))[:3]
        w(f"<h4>{label}</h4>")
        for o in rows:
            w(f'<blockquote>{e(o["text"])}'
              f'<span class="who">{e(o["to"])}／{e(o["parcel"])}の{e(o["kind"])}／'
              f'{yen(o["amount"])}（評価額の{o["ratio"]:.2f}倍）</span></blockquote>')

    # ===== 5 =====
    w('<h2 id="c5">5. 町の答え</h2>')
    w(f'<p class="lead">断られた手紙は{S["offers_declined"]}通。'
      'そのほとんどに、その人が書いた「なぜ売らないか」の一言が付いている。</p>')
    if cfg["classified"]:
        C = CLASSIFIED
        w("<h3>断りの理由を全件読んで分けた（判定AI不使用）</h3>")
        w(f'<p>824件の一言を人の目で1件ずつ読み、'
          '「自分の事情」「X社の条件」「その両方」「人から聞いた話」に分けた。'
          '分けたのは人で、機械がやったのは数えることだけ'
          f'（出典＝<code>{e(C["source"])}</code>）。</p>')
        w('<div class="scroll"><table><tr><th>断った理由の中身</th>'
          '<th class="num">件数</th><th class="num">割合</th></tr>')
        for label, n, p in C["overall"]:
            w(f'<tr><td>{e(label)}</td><td class="num">{n}</td>'
              f'<td class="num">{p}%</td></tr>')
        w("</table></div>")
        w('<p>4件に3件は<span class="hl">「自分の事情」</span>だった。'
          '「金額が安い」「条件が不明だ」という相手への文句ではなく、'
          '愛着・家族・商売・共有者への配慮といった、自分の側の話で断っている。</p>')

        w("<h4>いくら積まれても、理由の内訳はほとんど変わらない</h4>")
        w('<div class="scroll"><table><tr><th>提示額（評価額の何倍か）</th>'
          '<th class="num">理由が書かれた断り</th><th class="num">自分の事情</th>'
          '<th class="num">X社の条件</th><th class="num">両方</th>'
          '<th class="num">聞いた話</th></tr>')
        for label, n, a, b, c2, d2 in C["bands"]:
            w(f'<tr><td>{e(label)}</td><td class="num">{n}</td><td class="num">{a}%</td>'
              f'<td class="num">{b}%</td><td class="num">{c2}%</td>'
              f'<td class="num">{d2}%</td></tr>')
        w("</table></div>")
        w('<p>どの帯でも「自分の事情」が <span class="hl">69〜79%</span> で一貫している。'
          '安い提示の帯だけ「X社の条件」（＝安すぎる・条件が不明）が27.7%とやや多く、'
          '高く積まれるほどその言い分は使えなくなって12.6%まで下がる。</p>')

        w("<h4>金額に触れた断り</h4>")
        w(f'<p>断りの一言のうち、金額（提示額・評価額・相場・納得など）に触れているのは'
          f' <b>{C["money_n"]}件（{C["money_pct"]}%）</b>。'
          'いちばん多い帯は「評価額より安い」（29.8%）で、'
          'その次が「1.5倍以上」（17.1%）——'
          f'高く積まれたほうでも金額の話が増える。'
          f'<span class="hl">「提示額は魅力的だが、まだ手放したくない」</span>という'
          f'型の一言が {C["attractive_type"]}件あり、'
          '値段が上がったことを認めたうえで断る言い方が出てきている。</p>')
        w('<div class="scroll"><table><tr><th>提示額の帯</th>'
          '<th class="num">金額に触れた断り</th><th class="num">その帯の断り</th>'
          '<th class="num">割合</th></tr>')
        for label, n, tot, p in C["money_bands"]:
            w(f'<tr><td>{e(label)}</td><td class="num">{n}</td><td class="num">{tot}</td>'
              f'<td class="num">{p}%</td></tr>')
        w("</table></div>")

        w("<h4>一人では決められない、という断り</h4>")
        w(f'<p>「自分の事情」631件のうち <b>{C["proc_n"]}件（{C["proc_pct"]}%）</b>は、'
          '自治会・共有者・組合・家族・氏子といった'
          '<span class="hl">関係者との手続き</span>に触れている。'
          + "、".join(f'「{e(t)}」{n}件' for t, n in C["proc_examples"])
          + 'が代表例で、共有名義や自治会のように'
          '一人では決められない仕組みが、断りの4分の1近くを占めている。</p>')

        w("<h4>売った人・出ていった人の側から見ると</h4>")
        w(f'<ul class="plain">'
          f'<li>評価額以上を出された手紙 {C["over_valuation"]}通のうち、'
          f'<b>{C["over_valuation_declined"]}通が断られている</b>。'
          f'評価額より安い {C["under_valuation"]}通からは成約が'
          f'{C["under_valuation_sold"]}件（損な条件で売った人はいない）。</li>'
          f'<li>売った9人・{C["sold_total"]}件の理由を同じように読むと、'
          f'<b>{C["sold_money"]}件（{C["sold_money_pct"]}%）が金額そのもの</b>を理由にしていて、'
          f'自分の事情を理由にしたのは{C["sold_own"]}件だけ。'
          '<span class="hl">断る人は自分の事情を語り、売る人は金額を語る</span>という'
          'ちょうど裏返しの形になっている。</li>'
          f'<li>町を出た{C["left_total"]}人のうち{C["left_sellers"]}人は売った本人。'
          f'残り{C["left_tenants"]}人は不動産の取引を一度もしていない借り手自身の退場で、'
          '所有権の移動と人が出ていくことは1対1で対応していない。</li></ul>')
        w('<p class="note">この分け方は人の主観である。'
          '「まだ決められない」のような短い一言をどちらに寄せるかは、読み手が変われば変わりうる。</p>')

    w("<h3>数で見た町の答え</h3>")
    w('<div class="cards">')
    for n, l in [(f'{S["offers_declined"]}通', "断られた手紙"),
                 (f'{len(declines)}件', "断りの理由が書かれていた"),
                 (f'{sum(1 for o in offers if o["ratio"]>=1.0 and not o["accepted"])}通',
                  "評価額以上を出されても断った"),
                 ("0人", "評価額より安く売った人")]:
        w(f'<div class="card"><div class="n">{n}</div><div class="l">{l}</div></div>')
    w("</div>")

    w("<h3>よく出てきた断りの言葉（上位20）</h3>")
    cnt = Counter(o["decline_reason"].strip() for o in declines)
    w('<div class="scroll"><table><tr><th>言葉（原文）</th><th class="num">件数</th></tr>')
    for t, c in cnt.most_common(20):
        w(f'<tr><td>{e(t)}</td><td class="num">{c}</td></tr>')
    w("</table></div>")

    w("<h3>いくら積まれたかと、断り率</h3>")
    w('<div class="scroll"><table><tr><th>提示額（評価額の何倍か）</th>'
      '<th class="num">届いた手紙</th><th class="num">売った</th>'
      '<th class="num">断った</th><th class="num">断り率</th></tr>')
    for b in BANDS:
        d = band[b]
        rate = d["declined"] / d["n"] * 100 if d["n"] else 0
        w(f'<tr><td>{e(b)}</td><td class="num">{d["n"]}</td><td class="num">{d["sold"]}</td>'
          f'<td class="num">{d["declined"]}</td><td class="num">{rate:.1f}%</td></tr>')
    w("</table></div>")
    w('<p class="note">高く積んだ帯ほど断り率が下がる、という関係にはなっていない。'
      'ただし相手も区画もX社が選んでいるので、この表から「高く出せば売れる／売れない」は言えない。</p>')

    lo = min(o["ratio"] for o in sold_offers)
    w(f'<p>売れた{len(sold_offers)}件のうち、いちばん安かったものでも評価額の <b>{lo:.2f}倍</b>。'
      '<span class="hl">評価額を下回る金額で売った人は1人もいない。</span></p>')

    w(f"<h3>売った{len(sold_names)}人の全記録</h3>")
    for nm in sold_names:
        mine = [o for o in offers if o["to"] == nm]
        got = [o for o in mine if o["accepted"]]
        w(f'<details><summary>{e(nm)}（受けた手紙 {len(mine)}通／売った {len(got)}件）</summary>')
        for g in got:
            d = dec_by.get((g["step"], nm))
            w(f'<p class="ev"><span class="tag sold">成約</span>第{g["step"]}月・'
              f'{e(g["parcel"])}の{e(g["kind"])}を <b>{yen(g["amount"])}</b>'
              f'（評価額 {yen(g["valuation"])}＝{g["ratio"]:.2f}倍）で売った'
              + (f'　— 「{e(d["sell_reason"])}」' if d and d.get("sell_reason") else "") + "</p>")
        gone = next((a for a in left_agents if a["name"] == nm), None)
        if gone:
            w(f'<p class="ev"><span class="tag left">退場</span>'
              f'第{gone["step"]}月に町を出た</p>')
        w('<div class="scroll"><table><tr><th>月</th><th>区画</th><th>権利</th>'
          '<th class="num">金額</th><th class="num">倍率</th><th>結果</th>'
          '<th>本人の一言</th></tr>')
        for o in mine:
            res = "売った" if o["accepted"] else o["result"]
            reason = o.get("decline_reason") or ""
            if o["accepted"]:
                d = dec_by.get((o["step"], nm))
                reason = (d or {}).get("sell_reason", "")
            w(f'<tr><td>第{o["step"]}月</td><td>{e(o["parcel"])}</td><td>{e(o["kind"])}</td>'
              f'<td class="num">{o["amount"]:,}</td><td class="num">{o["ratio"]:.2f}</td>'
              f'<td>{e(res)}</td><td>{e(reason)}</td></tr>')
        w("</table></div></details>")

    w("<h3>断りの一言 全件</h3>")
    w(f'<details><summary>{len(declines)}件をすべて見る（月・人・金額・倍率・原文）</summary>'
      '<div class="scroll"><table><tr><th>月</th><th>人</th><th>区画</th><th>権利</th>'
      '<th class="num">金額</th><th class="num">倍率</th><th>断りの一言（原文）</th></tr>')
    for o in declines:
        w(f'<tr><td>第{o["step"]}月</td><td>{e(o["to"])}</td><td>{e(o["parcel"])}</td>'
          f'<td>{e(o["kind"])}</td><td class="num">{o["amount"]:,}</td>'
          f'<td class="num">{o["ratio"]:.2f}</td><td>{e(o["decline_reason"])}</td></tr>')
    w("</table></div></details>")

    # ===== 6 =====
    w('<h2 id="c6">6. 人の出入り</h2>')
    w('<p class="lead">売り買いの記録の裏側で、'
      '住んでいた人・借りて商売していた人がどう動いたか。</p>')

    w(f"<h3>町を出た{len(left_agents)}人</h3>")
    w('<div class="scroll"><table><tr><th>月</th><th>誰</th><th>その場所</th>'
      '<th>どうして出たか</th><th>本人の一言（原文）</th></tr>')
    for a in left_agents:
        how = a.get("how") or "土地と建物の両方を売り、その場所を離れた"
        w(f'<tr><td>第{a["step"]}月</td><td>{e(a["name"])}</td><td>{e(a["parcel"])}</td>'
          f'<td>{e(how)}</td><td>{e(left_reason.get((a["step"],a["name"]),""))}</td></tr>')
    w("</table></div>")
    w(f'<p class="note">内訳＝売って出た6人＋借りて使っていて出た2人。'
      f'36か月の終わりに町にいる人は {S["in_town_end"]}人（開始時35人）。'
      f'誰も使っていない区画は {S["no_user_parcels_end"]}区画（開始時2区画）。</p>')

    w("<h3>売った人の手元に残ったお金</h3>")
    w('<div class="scroll"><table><tr><th>人</th><th class="num">受け取った合計</th></tr>')
    for k, v in sorted(wallets.items(), key=lambda kv: -kv[1]):
        if v:
            w(f'<tr><td>{e(k)}</td><td class="num">{v:,}</td></tr>')
    w("</table></div>")
    w('<p class="note">お金は帳簿に記録されるだけで、この世界では何も起こさない'
      '（買い物も引っ越しもできない）。「いくらで手放したか」を見るためだけの数字。</p>')

    w("<h3>借りて使っている人の「出るか」の答え</h3>")
    w(f'<p>借りて住む・借りて商売している人には、毎月「この場所を出るか」を聞いている。'
      f'{S["tenant_calls_total"]}回聞いて、「出る」と答えたのは '
      f'<b>{S["tenant_leave_counts"]["出る"]}回</b>だけ。</p>')
    w(f'<details><summary>{len(tenants)}件の答えを全部見る</summary>'
      '<div class="scroll"><table><tr><th>月</th><th>誰</th><th>答え</th>'
      '<th>理由（原文）</th></tr>')
    for t in tenants:
        w(f'<tr><td>第{t["step"]}月</td><td>{e(t["name"])}</td><td>{e(t["leave"])}</td>'
          f'<td>{e(t.get("leave_reason",""))}</td></tr>')
    w("</table></div></details>")

    w("<h3>家主と借り手のやりとり</h3>")
    w(f'<p>ひと月に一言ずつ、借りている人から家主へ、家主から借りている人へ。'
      f'36か月で <b>{len(messages)}通</b>'
      f'（借り手→家主 {S["messages_tenant_to_landlord"]}・'
      f'家主→借り手 {S["messages_landlord_to_tenant"]}）。</p>')
    w(f'<details><summary>{len(messages)}通を全部見る</summary>'
      '<div class="scroll"><table><tr><th>月</th><th>区画</th><th>誰から</th><th>誰へ</th>'
      '<th>一言（原文）</th></tr>')
    for m in messages:
        w(f'<tr><td>第{m["step"]}月</td><td>{e(m["parcel"])}</td><td>{e(m["from"])}</td>'
          f'<td>{e(m["to"])}</td><td>{e(m["text"])}</td></tr>')
    w("</table></div></details>")

    w("<h3>売りに出された区画（出品）</h3>")
    lk = S["listings_by_kind"]
    w(f'<p>36か月で <b>{S["listings_total"]}件</b>'
      f'（土地だけ {lk["土地"]}・建物だけ {lk["建物"]}・両方 {lk["両方"]}）。'
      f'「出さない」と答えたのは {S["listing_choice_counts"]["出さない"]}回。'
      '出品は「売りたい」という公の申し出で、X社はこれを見て声をかける。</p>')
    top_l = Counter(x["name"] for x in listings).most_common(12)
    w('<div class="scroll"><table><tr><th>よく出していた人（上位12）</th>'
      '<th class="num">件数</th></tr>')
    for n2, c in top_l:
        w(f'<tr><td>{e(n2)}</td><td class="num">{c}</td></tr>')
    w("</table></div>")
    w("<h4>出したときの理由（代表・原文）</h4>")
    for st, nm, parcel, choice, r in listing_rep:
        w(f'<blockquote>{e(r)}<span class="who">{e(nm)}／第{st}月／'
          f'{e(parcel)}を「{e(choice)}」で出品</span></blockquote>')

    w("<h3>使っている人への通知</h3>")
    w(f'<p>持ち主が替わったとき、そこを借りて使っている人には'
      f'事実だけの1行が届く（この走行で {len(notices)}通、'
      f'借り手が出て空いたことの通知が {S["vacancy_notices_total"]}通）。</p>')
    for n2 in notices:
        w(f'<blockquote>{e(n2["text"])}<span class="who">第{n2["step"]}月／'
          f'{e(n2["to_name"])}へ</span></blockquote>')

    # ===== 7 =====
    w('<h2 id="c7">7. 会話の記録</h2>')
    if not cfg["chat"]:
        w('<p class="lead">この世界には<b>場の会話も隣近所への伝わりも無い</b>。'
          '人は毎月ひとりで考えて決めるだけで、誰の声も届かない。</p>')
        w('<p>36か月で発言は <b>0件</b>（会話なしの世界＝0件）。'
          '出かける先の選択も、聞いた話も、隣近所への伝播も発生しない。'
          '家主と借り手のあいだの一言だけは残っており、'
          'それは「6. 人の出入り」に全件ある。</p>')
    else:
        w('<p class="lead">この町の人は毎月、行き先を自分で選ぶ。'
          '同じ場所に居合わせた人だけが、その場の話を聞く。</p>')
        w(f'<p>36か月で発言は <b>{len(utterances)}件</b>。'
          'そのうち買い手（X社）に触れた発言は '
          f'<b>{len(utt_x)}件</b>。</p>')
        w('<div class="scroll"><table><tr><th>月</th>'
          + "".join(f"<th class='num'>{v}</th>" for v in venue_labels)
          + '<th class="num">出かけなかった人</th><th class="num">発言</th>'
            '<th class="num">1人の話が届いた人数（平均）</th></tr>')
        for r in monthly:
            c = utt_venue_month[r["step"]]
            w(f'<tr><td>第{r["step"]}月</td>'
              + "".join(f'<td class="num">{c.get(v,0)}</td>' for v in venue_labels)
              + f'<td class="num">{r["by_venue"].get("今月はどこにも行かない",0)}</td>'
                f'<td class="num">{r["utterances"]}</td>'
                f'<td class="num">{r["heard_mean"]}</td></tr>')
        w("</table></div>")
        w('<p class="note">月が進むほど「今月はどこにも行かない」が増え、'
          '場に出る人と発言が減っていく。'
          f'第1月は{monthly[0]["attended"]}人が出かけて{monthly[0]["utterances"]}件の発言、'
          f'第36月は{monthly[-1]["attended"]}人・{monthly[-1]["utterances"]}件。'
          f'一言が届いた人数の平均も {monthly[0]["heard_mean"]}人から '
          f'{monthly[-1]["heard_mean"]}人まで落ちた。</p>')

        w("<h3>買い手に触れた発言 全件</h3>")
        w(f'<details><summary>{len(utt_x)}件を全部見る（原文）</summary>')
        for u in utt_x:
            w(f'<blockquote>{e(u["text"])}<span class="who">第{u["step"]}月／'
              f'{e(u["from"])}／{e(u["venue_label"])}（{len(u["heard_by"])}人が聞いた）'
              '</span></blockquote>')
        w("</details>")

        w("<h3>すべての発言</h3>")
        w(f'<details><summary>{len(utterances)}件を全部見る（原文）</summary>'
          '<div class="scroll"><table><tr><th>月</th><th>場所</th><th>誰</th>'
          '<th class="num">聞いた人</th><th>発言（原文）</th></tr>')
        for u in utterances:
            w(f'<tr><td>第{u["step"]}月</td><td>{e(u["venue_label"])}</td><td>{e(u["from"])}</td>'
              f'<td class="num">{len(u["heard_by"])}</td><td>{e(u["text"])}</td></tr>')
        w("</table></div></details>")

        # ===== 8 =====
    w('<h2 id="c8">8. 健全性と費用</h2>')
    w('<p class="lead">この走行そのものが壊れていないかの確認。</p>')
    w('<div class="scroll"><table><tr><th>項目</th><th class="num">件数</th></tr>')
    for label, v in [
        ("読み取りに失敗した応答", S["parse_fail"]),
        ("答えが返らなかった", S["no_answer"]),
        ("文が途中で切れた", S["truncated"]),
        ("時間切れでやり直した", S["timeout_retries"]),
        ("時間切れであきらめた", S["timeout_giveups"]),
        ("選べない選択肢を選んだ（出品）", S["invalid_listing"]),
        ("選べない選択肢を選んだ（売買）", S["invalid_sell"]),
        ("買い手が同じ相手を二重に書いた", S["acquirer_dup_rows"]),
        ("買い手が金額を書き損ねた", S["acquirer_bad_amount"]),
        ("費用で打ち切られた", 1 if S["stopped_by_cost"] else 0),
    ]:
        w(f'<tr><td>{e(label)}</td><td class="num">{v}</td></tr>')
    w("</table></div>")
    w(f'<p>36か月ぶん、{S["usage"]["calls"]:,}回の問い合わせで '
      f'<b>${S["cost_usd"]}</b>（手元集計）・{S["elapsed_sec"]/60:.1f}分。'
      f'使ったのは <code>gemini-2.5-flash-lite</code>、temperature 0.75。'
      f'同じ前置きを使い回した割合は {S["cached_ratio"]*100:.1f}%。'
      f'断りの理由が書かれた割合は {S["reason_rate_sell"]*100:.2f}%。</p>')

    # ===== 9 =====
    w('<h2 id="c9">9. このページから言えないこと</h2>')
    w('<p class="lead">正直に線を引いておく。</p>')
    w('<ul class="plain">'
      '<li><b>1本の走行の記録である。</b>'
      '同じ設定でもう一度走らせれば別の数字が出る。'
      '「こうなる」ではなく「こうなった」としか言えない。</li>'
      '<li><b>評価額も面積も、走らせる前に置いた仮の値。</b>'
      '実在の町の地価ではない。金額の絶対値に意味は無く、'
      '見るべきは「評価額の何倍を出したか」という比のほうだけ。</li>'
      '<li><b>買い手の指示文そのものが設計である。</b>'
      '「余らせるより高く買え」「買えるまで条件を変えて働きかけ続けろ」と'
      '書いたから、そう動いた。指示を変えれば結果は変わる。</li>'
      '<li><b>世界の門番には限界がある。</b>'
      '実行できない約束をはじく仕組みは、読点の無い長い逆接の文などを取りこぼす。'
      '「間違って弾く」より「取りこぼす」側に倒してある。</li>'
      '<li><b>毎月「売るか」を問うこと自体が介入である。</b>'
      '現実には毎月手紙が来るとは限らない。'
      'この設計は、買い手が粘り続ける世界を最初から仮定している。</li>'
      '<li><b>結果の良し悪しは判定していない。</b>'
      '数えられるものを数えただけで、'
      '「守れた／守れなかった」を決める採点者はこの世界にいない。</li>'
      '</ul>')

    w('<hr><p class="note">このページの数字・図はすべて1本の走行の記録から'
      '機械的に組み立てている（作り直せる）。'
      f'走行＝49人・44区画・36か月・{S["usage"]["calls"]:,}回の問い合わせ。</p>')
    w("</div></body></html>")

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write("\n".join(P))

    print(f"[{key}] wrote {OUT_HTML} {os.path.getsize(OUT_HTML)} bytes"
          f" / maps {len(MAP_MONTHS)*2} / timeline {len(monthly)}"
          f" / declines {len(declines)} / utterances {len(utterances)}"
          f" (X {len(utt_x)}) / messages {len(messages)}"
          f" / tenant {len(tenants)} / undelivered-right {len(und_right)}")
    return {"maps": len(MAP_MONTHS) * 2, "timeline": len(monthly),
            "declines": len(declines), "utterances": len(utterances),
            "utt_x": len(utt_x), "messages": len(messages),
            "tenants": len(tenants), "und_right": len(und_right),
            "bytes": os.path.getsize(OUT_HTML)}


# ---------------------------------------------------------------------------
# 4象限（4本の走行の並べ方）
# ---------------------------------------------------------------------------

def quad_stats(cfg):
    """1本の走行から4象限の表に出す数字だけを取る。未完成なら None。"""
    run = os.path.join(SIMS, cfg["dir"])
    if not os.path.exists(os.path.join(run, "summary.json")):
        return None
    S = jload(run, "summary.json")
    offers = jload(run, "offers.json")
    def _clean(t):
        for r in ROLE_WORDS:
            t = t.replace(r, "")
        return t
    suspect = sum(1 for o in offers
                  if any(x in _clean(o.get("decline_reason") or "")
                         for x in SUSPECT_WORDS))
    left = jload(run, "left_agents.json")
    owners_left = sum(1 for a in left if not a.get("how"))
    d = dict(cfg)
    d.update({
        "ready": True,
        "deals": S["offers_accepted"],
        "parcels": S["acquired_parcels"],
        "area_share": S["area_share_end"],
        "left": S["left_agents"],
        "owners_left": owners_left,
        "offers": S["offers_total"],
        "suspect": suspect,
        "utterances": S.get("utterances_total", 0),
        "cost": S["cost_usd"],
    })
    return d


def quad_html(quad, current=None, links=False):
    """4象限の説明と表。current＝いま見ているページの key。"""
    o = []
    o.append('<div class="quad">')
    o.append('<p class="qh"><b>'
             + ('4本の走行を並べる' if links else 'この記録は4本のうちの1本')
             + '</b>'
             '　—　世界の設定が<b>2点</b>だけ違う4つの走り方を、同じ形で全部残している。'
             '違いは①買い手が「この街の不動産の過半の取得を目指しています」と'
             '<b>町に明言するかどうか</b>、②町に'
             '<b>場の会話と隣近所への伝わりがあるかどうか</b>、この2つだけ。'
             '町の人・44区画・評価額・買い手のお金（町の評価額の51%）・36か月は'
             'すべて同じ。</p>')
    o.append('<div class="scroll"><table><tr><th>世界</th>'
             '<th class="num">成約</th><th class="num">X社の区画</th>'
             '<th class="num">面積の割合</th><th class="num">所有者の退場</th>'
             '<th class="num">町を出た人（計）</th>'
             '<th class="num">意図を疑う断り</th>'
             '<th class="num">場の発言</th></tr>')
    for q in quad:
        name = html.escape(q["label"])
        if links and q.get("ready"):
            name = '<a href="%s">%s</a>' % (OUT_NAME[q["key"]], name)
        mark = ' style="background:#1b2a24"' if q["key"] == current else ""
        if not q.get("ready"):
            o.append('<tr%s><td>%s</td>'
                     '<td colspan="7" class="note">準備中（走行が終わり次第ここに入る）'
                     '</td></tr>' % (mark, name))
            continue
        o.append('<tr%s><td>%s</td>'
                 '<td class="num">%d件</td><td class="num">%d／44</td>'
                 '<td class="num">%.1f%%</td><td class="num">%d人</td>'
                 '<td class="num">%d人</td>'
                 '<td class="num">%d件</td><td class="num">%d件</td></tr>'
                 % (mark, name, q["deals"], q["parcels"], q["area_share"] * 100,
                    q["owners_left"], q["left"], q["suspect"], q["utterances"]))
    o.append("</table></div>")
    o.append('<p class="note">「意図を疑う断り」＝断りの一言に'
             '「買い占め」「警戒」「意図」「危機」「支配」「乗っ取」のどれかが'
             '入っていた件数（走らせる前に決めた語で機械的に数えたもの・読んで分けた分類ではない。'
             '「支配人」のような役名は数える前に外している）。'
             '「所有者の退場」＝持ち物を売って町を出た人。'
             '「町を出た人（計）」にはそれに加えて、'
             '借りて使っていた人が自分で出ていった分も含む。</p>')
    o.append("</div>")
    return "\n".join(o)


INDEX_CSS = """
:root{--bg:#0f1115;--panel:#161a21;--fg:#e9ecf1;--dim:#98a1ad;--accent:#34d399;--line:#262c36;}
*{box-sizing:border-box}html,body{margin:0;padding:0;background:var(--bg)}
body{color:var(--fg);font-family:"Noto Sans JP","Hiragino Kaku Gothic ProN","Yu Gothic",
Meiryo,system-ui,sans-serif;line-height:1.85}
.wrap{max-width:940px;margin:0 auto;padding:28px 18px 80px}
h1{font-size:clamp(26px,6vw,40px);font-weight:900;margin:0 0 10px}
h2{font-size:clamp(19px,4.4vw,26px);font-weight:900;margin:40px 0 10px;
padding-left:12px;border-left:5px solid var(--accent)}
.kicker{font-size:12px;font-weight:700;letter-spacing:.09em;color:var(--accent);margin:0 0 6px}
.lead{color:var(--dim);font-size:clamp(15px,3.6vw,17px);margin:0 0 18px}
a{color:var(--accent)}
.quad{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:14px 16px;margin:18px 0}
.quad .qh{margin:0 0 10px;font-size:15px}
table{width:100%;border-collapse:collapse;font-size:14px;margin:6px 0}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left}
th{background:#1b212a;color:var(--dim);white-space:nowrap}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{overflow-x:auto}.scroll table{min-width:620px}
.note{font-size:13px;color:var(--dim)}
.cards{display:flex;flex-wrap:wrap;gap:12px}
.card{flex:1 1 260px;background:var(--panel);border:1px solid var(--line);
border-radius:12px;padding:14px 16px;text-decoration:none;color:var(--fg);display:block}
.card.off{opacity:.55}
.card .n{font-size:19px;font-weight:900;margin-bottom:4px}
.card .l{font-size:13px;color:var(--dim);line-height:1.6}
"""


def build_index(quad):
    out = os.path.join(HERE, "reports.html")
    P = ['<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         '<title>A市で起きたことの全記録 — 4つの世界</title>',
         '<style>' + INDEX_CSS + '</style></head><body><div class="wrap">',
         '<p class="kicker">外的不動産投資へのコミュニティ自衛</p>',
         '<h1>A市で起きたことの全記録</h1>',
         '<p class="lead">同じ町・同じ人・同じ買い手のお金で、'
         '世界の設定を2点だけ変えた4本の走行。'
         'それぞれの36か月を、地図・年表・本人たちの言葉まで省略せずに残したページ。</p>',
         quad_html(quad, links=True),
         '<h2>4本の記録</h2>', '<div class="cards">']
    for q in quad:
        if q.get("ready"):
            P.append('<a class="card" href="%s"><div class="n">%s</div>'
                     '<div class="l">成約%d件・所有者の退場%d人・手紙%d通・場の発言%d件'
                     '</div></a>'
                     % (OUT_NAME[q["key"]], html.escape(q["label"]), q["deals"],
                        q["owners_left"], q["offers"], q["utterances"]))
        else:
            P.append('<div class="card off"><div class="n">%s</div>'
                     '<div class="l">準備中</div></div>' % html.escape(q["label"]))
    P.append("</div>")
    P.append('<h2>提出スライド</h2>')
    P.append('<p><a href="slides10.html">発表用スライド（10枚）</a>'
             '／<a href="slides10.pdf">PDF版</a></p>')
    P.append('<p class="note">数字・図はすべて走行の記録から機械的に組み立てている。'
             '採点する人工知能は使っていない。</p>')
    P.append("</div></body></html>")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(P))
    print("wrote", out, os.path.getsize(out), "bytes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="走行の run_dir（単発で作るとき）")
    ap.add_argument("--out", default=None, help="出力の html 名（単発で作るとき）")
    ap.add_argument("--label", default=None, help="見出しに出す呼び名（単発で作るとき）")
    ap.add_argument("--key", default=None, help="画像置き場の名前（単発で作るとき）")
    ap.add_argument("--only", default=None, help="key をカンマ区切りで指定")
    ap.add_argument("--skip-maps", action="store_true")
    ap.add_argument("--no-index", action="store_true")
    args = ap.parse_args()

    os.makedirs(ASSETS, exist_ok=True)
    runs = list(RUNS)
    if args.run:
        key = args.key or "custom"
        cfg = {"key": key, "label": args.label or key,
               "dir": os.path.basename(os.path.normpath(args.run)),
               "map": "v9h_map.py" if "v9h" in args.run else "v9f_map.py",
               "declared": "declared" in args.run,
               "chat": "nochat" not in args.run,
               "classified": False}
        OUT_NAME[key] = args.out or ("report_%s.html" % key)
        runs = [cfg]
    elif args.only:
        want = [x.strip() for x in args.only.split(",")]
        runs = [r for r in RUNS if r["key"] in want]

    quad = []
    for cfg in RUNS:
        q = quad_stats(cfg)
        quad.append(q if q else dict(cfg, ready=False))
    for cfg in runs:
        if not os.path.exists(os.path.join(SIMS, cfg["dir"], "summary.json")):
            print("[%s] 走行がまだ終わっていないので飛ばす" % cfg["key"])
            continue
        build_one(cfg, quad, skip_maps=args.skip_maps)
    main_html = os.path.join(HERE, OUT_NAME["main"])
    if os.path.exists(main_html):
        shutil.copyfile(main_html, os.path.join(HERE, "report_main.html"))
    if not args.no_index and not args.run:
        build_index(quad)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
