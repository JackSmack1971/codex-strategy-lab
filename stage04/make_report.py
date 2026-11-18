"""Builds STAGE_04_REGIME_REPORT.md and STAGE_04_HANDOFF.json from regime_results.json (no new measurement here)."""
import json, subprocess, hashlib
from pathlib import Path
R = Path(__file__).resolve().parents[1]; D = R / "docs/strategy-specs"; r = json.load(open(D / "stage04/regime_results.json"))
A = r["assets"]; B = A["BTC"]; BR = r["breadth"]; M = r["macro"]; OS = r["onchain_sentiment"]; DV = r["derivatives"]; CV = r["cross_venue"]; G = r["gates"]; TR = r["triggers_distance"]; H = r["hist_by_regime"]
SY = ["BTC", "ETH", "SOL", "XRP", "ADA", "LINK", "AVAX", "DOGE", "LTC"]
p = lambda x, d=1: f"{x*100:+.{d}f}%"; p0 = lambda x, d=1: f"{x*100:.{d}f}%"
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=R).stdout.strip()[:12]
dirty = bool(subprocess.run(["git", "status", "--porcelain", "stage04", "stage02", "stage03"], capture_output=True, text=True, cwd=R).stdout.strip())

# ---- signal agreement (BTC-anchored; stance in {-1,0,+1}; trend/price/macro vs contrarian/valuation groups)
sp, vx, dxy, t10 = M["SP500"], M["VIXCLS"], M["DTWEXBGS"], M["DGS10"]
sig = [
 ("Price", "Close vs EMA200", B["close"] and (1 if B["c_vs_ema200"] > 0 else -1), f"close {B['close']:,.0f} vs EMA200 {B['ema200']:,.0f} ({p(B['c_vs_ema200'])})", "trend"),
 ("Price", "EMA20 vs EMA50", 1 if B["ema20"] > B["ema50"] else -1, f"{B['ema20']:,.0f} vs {B['ema50']:,.0f}", "trend"),
 ("Price", "EMA50 vs EMA200", 1 if B["ema50"] > B["ema200"] else -1, f"{B['ema50']:,.0f} vs {B['ema200']:,.0f} (BTC only; every other asset has 20<50<200)", "trend"),
 ("Price", "+DI vs -DI (daily)", 1 if B["pdi"] > B["mdi"] else -1, f"+DI {B['pdi']:.1f} / -DI {B['mdi']:.1f}", "trend"),
 ("Price", "30d return", 1 if B["ret30"] > 0 else -1, p(B["ret30"]) + " (log)", "trend"),
 ("Price", "90d return", 1 if B["ret90"] > 0 else -1, p(B["ret90"]) + " (log)", "trend"),
 ("Breadth", "Assets above own EMA200", 1 if BR["share_above_ema200"] >= .6 else -1 if BR["share_above_ema200"] <= .4 else 0, f"{BR['share_above_ema200']*9:.0f} of 9", "trend"),
 ("Macro", "S&P 500 vs 50-obs mean", 1 if sp["above_50obs_mean"] else -1, f"{sp['last']:,.0f} ({sp['last_date']}); {p(sp['from_high'])} from 252d high", "macro"),
 ("Macro", "VIX level (>25 risk-off, preselected)", -1 if vx["last"] > 25 else 1 if vx["last"] < 18 else 0, f"{vx['last']:.1f} ({vx['last_date']}), 1y pctile {vx['pctile_1y']:.0f}", "macro"),
 ("Macro", "Broad USD index vs 50-obs mean", -1 if dxy["above_50obs_mean"] else 1, f"{dxy['last']:.1f} ({dxy['last_date']}, STALE >2d), 1y pctile {dxy['pctile_1y']:.0f}", "macro"),
 ("Valuation", "MVRV (Coinmetrics community, provisional)", 1, f"{OS['coinmetrics']['mvrv']:.2f}; lowest {OS['coinmetrics']['mvrv_pctile_in_window']:.0f}th pctile of only {OS['coinmetrics']['mvrv_window_n']} days", "contrarian"),
 ("Sentiment", "Fear & Greed", 1, f"{OS['fear_greed']['latest']} ({OS['fear_greed']['latest_class']}); 60d range {OS['fear_greed']['min_60d']}-{OS['fear_greed']['max_60d']}", "contrarian"),
 ("Flows", "Exchange net flow 7d (Coinmetrics, flash)", 1 if OS["coinmetrics"]["netflow_7d_usd"] < 0 else -1, f"{OS['coinmetrics']['netflow_7d_usd']/1e9:+.2f}B USD (negative = net outflow)", "contrarian"),
]
grp = lambda g: [x for x in sig if x[4] == g]
tm = [x for x in sig if x[4] in ("trend", "macro")]; bear = sum(1 for x in tm if x[2] < 0); bull = sum(1 for x in tm if x[2] > 0); neu = len(tm) - bear - bull
agree = bear / len(tm)
conf = "SUPPORTED" if agree >= 0.8 else "CONDITIONAL" if agree >= 0.6 else "UNCERTAIN"
cb = [x for x in sig if x[4] == "contrarian"]

def row(cells): return "| " + " | ".join(str(c) for c in cells) + " |"
def tbl(h, rows): return "\n".join([row(h), row(["---"] * len(h))] + [row(x) for x in rows])
st = lambda v: {1: "bull", -1: "bear", 0: "neutral"}[v]

# ---- B: threshold table
TH = r["thresholds"]
thr_rows = [
 ["Direction", "≥4 of 5 votes (close>EMA200, EMA50>EMA200, EMA20>EMA50, +DI>-DI, 30d ret>0) → Bullish; ≤-4 → Bearish; ADX<20 and |30d ret|<5% → Sideways; else Uncertain", "votes bull/bear %d/%d" % (B["votes_bull"], B["votes_bear"]), "Bearish", "vote rule + 5% REQUIRE CALIBRATION"],
 ["EMA 20/50/200 (daily, span, adjust=False)", "reported", f"{B['ema20']:,.0f} / {B['ema50']:,.0f} / {B['ema200']:,.0f}", B["ema_stack"], "PRESELECTED (task-mandated)"],
 ["ADX(14) daily (Wilder smoothing)", "≥25 Trending; <20 and ER30<0.30 Mean-reverting; else Transitioning", f"ADX {B['adx']:.1f} (5d chg {B['adx_chg5']:+.1f}), ER30 {B['er30']:.2f}", B["structure"], "25/20 PRESELECTED; ER cut REQUIRES CALIBRATION"],
 ["ATR(14)/price (daily)", "reported; percentile vs own history", f"{p0(B['atr_pct'],2)} ({B['atr_pct_pctile']:.0f}th pctile)", "—", "descriptive"],
 ["Realised vol 30d (ann.) pctile vs own history since 2021-05", "<25 Low; 25–75 Normal; 75–95 Elevated; ≥95 Extreme", f"{p0(B['rv30'],1)} ({B['rv30_pctile']:.0f}th pctile); 7d {p0(B['rv7'],1)} ({B['rv7_pctile']:.0f}th)", B["volatility"], "cuts PRESELECTED; need calibration; history includes consumed windows"],
 ["Volume vs rolling baseline", "last completed-day quote vol ÷ prior-30d median daily: ≥1.25 Strong; <0.75 Weak; else Average (rolling 24h also computed; disagreement → Average)", f"{B['vratio']:.2f}× completed day; {B['rolling24h_vratio']:.2f}× rolling 24h", B["liquidity"], "REQUIRES CALIBRATION"],
 ["Momentum", "Positive if 7/30/90d log returns all >0; Negative if all <0; else Mixed", f"{p(B['ret7'])} / {p(B['ret30'])} / {p(B['ret90'])}", B["momentum"], "PRESELECTED; not calibrated"],
 ["Relative strength", "log-return difference vs BTC (alts) / vs equal-weight alt basket (BTC)", f"BTC vs alt basket 30d {p(B['rs_ret30_vs_altbasket'])}; every alt below BTC at 30d", "—", "descriptive; benchmark choice (BTC) is a research choice"],
 ["Market-level label", "BTC label, accepted only if ≥60% of 9 assets share it; else Uncertain", f"{BR['share_bearish']*9:.0f}/9 Bearish, {BR['share_bullish']*9:.0f}/9 Bullish", "Bearish", "0.60 REQUIRES CALIBRATION"],
 ["Label confidence", "share of directional price+macro signals agreeing ≥0.8 SUPPORTED; 0.6–0.8 CONDITIONAL; <0.6 UNCERTAIN", f"{bear}/{len(tm)} bearish, {bull} bullish, {neu} neutral → {agree:.2f}", conf, "REQUIRES CALIBRATION"],
 ["Funding crowding", "|annualised funding| >30%", f"HL BTC {p(DV['hyperliquid']['BTC']['funding_ann'])}, OKX BTC {p(DV['okx']['BTC']['funding_ann'])}, OKX ETH {p(DV['okx']['ETH']['funding_ann'])}", "not crowded", "REQUIRES CALIBRATION"],
 ["Staleness / cross-venue", ">2h bar age or >30bp Binance–Coinbase gap blocks a confident label", f"max bar age {r['data_quality']['max_age_hours']:.2f}h; max basis {r['data_quality']['max_abs_basis_bp']:.1f}bp", "pass", "PRESELECTED"],
]

# ---- per-asset table
arows = []
for s in SY:
    a = A[s]
    arows.append([s, a["direction"], f"{a['votes_bull']}/{a['votes_bear']}", a["ema_stack"], f"{a['adx']:.0f}", a["structure"], f"{p0(a['atr_pct'],1)}", f"{a['rv30_pctile']:.0f}", a["volatility"], a["momentum"], p(a["ret30"], 1), f"{a['vratio']:.2f}/{a.get('rolling24h_vratio',0):.2f}", a["liquidity"] + ("*" if a["liquidity_conflict"] else ""), p(a["rs_ret30_vs_BTC"], 1) if s != "BTC" else "—"])
# cross-venue / depth table
crow = []
for s in SY:
    c = CV[s]; bk = c["binance_book"]; cbk = c["coinbase_book"]
    crow.append([s, f"{c['binance_close']:,.4g}", f"{c['basis_bp_binance_vs_coinbase']:+.1f}", f"{c['basis_bp_24h_mean_absdev_from_mean']:.1f}", f"{c['age_hours_at_fetch']:.2f}", f"{bk['spread_bp']:.2f}", f"{min(bk['bid_depth_usd_10bp'], bk['ask_depth_usd_10bp'])/1e3:,.0f}{'†' if min(bk['bid_span_bp'], bk['ask_span_bp']) < 10 else ''}", f"{cbk['spread_bp']:.2f}", f"{min(cbk['bid_depth_usd_10bp'], cbk['ask_depth_usd_10bp'])/1e3:,.0f}", f"{c['binance_24h_quote_vol_usdt']/1e6:,.0f}"])
drow = []
for s in SY:
    h = DV["hyperliquid"].get(s, {}); o = DV["okx"].get(s, {})
    drow.append([s, p(h.get("funding_ann", float("nan")), 1) if h else "n/a", p(o.get("funding_ann", float("nan")), 1) if "funding_ann" in o else "n/a", f"{h['oi_usd']/1e6:,.0f}" if h else "n/a", f"{o['oi_usd']/1e6:,.0f}" if "oi_usd" in o else "n/a",
                 p(o["oi_chg_7d"], 1) if "oi_chg_7d" in o else "—", (f"{o['liq_long_usd']/1e3:,.0f} / {o['liq_short_usd']/1e3:,.0f} ({o['liq_span_min']:.0f} min)" if "liq_long_usd" in o else "—")])

def gate_summary(sid):
    g = G[sid]; ok = [s for s in SY if g[s]["liq_gates"]]
    return g, ok
gm, okl = gate_summary("CRY-MOM-101")
def hist_line(sid, key):
    t = H[sid]["dir_x_struct"].get(key); return f"n={t['n']}, mean R {t['mean_R']:+.2f}, win {t['win_rate']*100:.0f}%" if t else "n=0 (no trades)"
cur = f"{B['direction']}|{B['structure']}"
dc = r["hist_regime_day_counts"]["dir_x_struct"]
hist_rows = []
for sid in ["CRY-MOM-101", "CRY-REV-102", "CRY-VEX-103"]:
    dd = H[sid]["direction"]; nb = dd.get("Bearish", {"n": 0})
    hist_rows.append([sid, hist_line(sid, cur), f"{nb['n']} trades (mean R {nb['mean_R']:+.2f})" if nb["n"] else "0", "; ".join(f"{k.split('|')[0][:4]}|{k.split('|')[1][:5]} n={v['n']} R{v['mean_R']:+.2f}" for k, v in sorted(H[sid]["dir_x_struct"].items(), key=lambda kv: -kv[1]["n"])[:4])])

mom_dist = TR["BTC"]; ev = "FOMC Dec 8–9 (decision Dec 9 14:00 ET); jobs report Dec 4; CPI Dec 10 (one calendar lists Dec 4 → conflict, unverified against BLS); US Thanksgiving Nov 26 (derived from the calendar: thin US-session liquidity); monthly crypto-derivatives expiry Nov 27 (derived: last Friday; venue not verified)"

trig_rows = [
 ["R1 MOM prerequisite", "BTC 4H close > 4H SMA300 (and the asset's own)", f"BTC {mom_dist['close_4h']:,.0f} vs SMA300 {mom_dist['sma300_4h']:,.0f}: needs {p(mom_dist['pct_to_sma300'])} (= {mom_dist['pct_to_sma300_in_daily_atr']:.1f} daily ATRs)", "re-enables MOM gate only; M≥1.25 also needed (BTC M={:.2f})".format(mom_dist["M"])],
 ["R2 Direction flip (BTC)", "daily close > EMA20 / EMA50 / EMA200 (≥2 more votes needed for ≥4/5 Bullish or to drop below 4/5 Bearish)", f"+{mom_dist['pct_to_ema20']*100:.1f}% / +{mom_dist['pct_to_ema50']*100:.1f}% / +{mom_dist['pct_to_ema200']*100:.1f}% away", "Bearish → Uncertain on 2 vote changes; Bullish needs ≥4"],
 ["R3 Structure", "ADX(14) < 25 (Trending→Transitioning); <20 with ER30<0.30 (→Mean-reverting)", f"ADX {B['adx']:.1f}, rising {B['adx_chg5']:+.1f} in 5d; ER30 {B['er30']:.2f}", "an ADX peak/roll-over with price still below EMAs is the usual late-trend signal [untested]"],
 ["R4 Volatility", "RV30 percentile ≥75 (≥{:.0f}% ann.) → Elevated; ≥95 (≥{:.0f}%) → Extreme; <25 (<{:.0f}%) → Low".format(r["btc_rv30_cuts"]["p75"] * 100, r["btc_rv30_cuts"]["p95"] * 100, r["btc_rv30_cuts"]["p25"] * 100), f"RV30 {p0(B['rv30'],1)}, RV7 {p0(B['rv7'],1)} ({B['rv7_pctile']:.0f}th pctile)", "RV7 is already above RV30: short-horizon vol is rising"],
 ["R5 Liquidity", "rolling-24h volume ÷ 30d median <0.75 (Weak) or >1.25 (Strong); L1–L3 gate failures", f"BTC {B['rolling24h_vratio']:.2f}×; gate failures now: {', '.join(s for s in SY if not G['CRY-MOM-101'][s]['liq_gates']) or 'none'}", "Stage 03 T8 also applies"],
 ["R6 Breadth/concentration", "share of assets Bullish ≥60% (breadth); 30d mean pairwise correlation >0.90 (Stage 03 T9)", f"{BR['share_bullish']*9:.0f}/9 Bullish; corr {BR['mean_pairwise_corr_30d']:.3f} (own daily-return definition; may differ from Stage 03's cohort measure)", "correlation is close to the T9 limit"],
 ["R7 Derivatives", "|funding| >30% annualised; OKX OI 7d change beyond ±20%; liquidation burst (no history here)", f"funding {p(DV['hyperliquid']['BTC']['funding_ann'])}/{p(DV['okx']['BTC']['funding_ann'])}; OKX BTC OI 7d {p(DV['okx']['BTC']['oi_chg_7d'])}", "deleveraging already in progress (OI falling)"],
 ["R8 Macro/sentiment", "VIX >30 or <18; S&P 500 reclaiming its 50-obs mean; Fear&Greed >25 sustained", f"VIX {vx['last']:.1f}; SPX {p(sp['from_high'])} from high; F&G {OS['fear_greed']['latest']}", "events: " + ev],
 ["R9 Data/venue", "bar age >2h; Binance–Coinbase gap >30bp; any venue/API outage; archive vs API mismatch", f"age {r['data_quality']['max_age_hours']:.2f}h; gap {r['data_quality']['max_abs_basis_bp']:.1f}bp; overlap diff {r['overlap_check']['BTC']['max_rel_close_diff']:.1e}", "label becomes UNCERTAIN on any breach"],
]

def mom_state(s):
    g = G["CRY-MOM-101"][s]; fails = [n for n, ok in (("c<SMA300", not g["c_gt_sma300"]), ("SMA300 not rising", not g["sma300_rising"]), ("BTC filter", not g["btc_filter"]), ("M<1.25", g["M"] < 1.25), ("L-gate", not g["liq_gates"])) if ok]
    return ", ".join(fails) if fails else "all pass"
suit_rows = [["CRY-MOM-101", "persistent directional; unsuited to chop/V-reversals", "Bearish/Trending/Negative = directional but in the opposite direction to a long-only rule", "**NOT SUPPORTED — gate closed** (0 of 9 assets pass; BTC filter false; M {:.2f} vs 1.25)".format(G["CRY-MOM-101"]["BTC"]["M"]), "Stand aside; paper-monitor; Stage 03 budget unchanged but unused"],
             ["CRY-REV-102", "uptrend dips, wide range, ample liquidity; unsuited to cascade/contagion crashes and structural breaks", "downtrend, 0/9 above SMA300; rsi3 {:.0f}-{:.0f} (≤8 required)".format(min(G["CRY-REV-102"][s]["rsi3"] for s in SY), max(G["CRY-REV-102"][s]["rsi3"] for s in SY)), "**NOT SUPPORTED — gate closed; stage-03 status REJECT/shadow**", "Shadow log only (no change)"],
             ["CRY-VEX-103", "quiet-to-active vol transition in liquid sessions; unsuited to thin/weekend liquidity", "Normal-vol, volume surging ({:.1f}× 168h median on BTC) but 4H close < SMA50 on all 9 → ctx filter false".format(G["CRY-VEX-103"]["BTC"]["vol_ratio"]), "**NOT SUPPORTED NOW — gate closed; conditional on 4H SMA50 reclaim**", "Shadow/paper only (Stage 03); would arm first as ctx flips"]]

md = f"""# STAGE 04 — Market regime assessment (as of {r['fetched_utc'][:16]} UTC, {r['snapshot']})

Inputs: `STAGE_03_HANDOFF.json` (eligibility, budgets, T1–T10), `STAGE_02_HANDOFF.json`, `STAGE_01_HANDOFF.v2.json` (universe, regime hypotheses). Code commit `{head}` (stage02–04 source dirty at run: {dirty}). Research only: no orders, no credentials, public GET endpoints only. The 2025-11-17..2026-11-17 window stays `CONSUMED_LEGACY`; nothing here is a holdout or a performance claim.

**Labels.** [M] measured now from a timestamped source; [H] historical/descriptive (Stage 02 trades, includes the consumed final year); [D] derived rule/heuristic; [U] unavailable/unverified.

## Headline

**Market regime (BTC-anchored, 9-asset breadth): {B['direction'].upper()} / {B['structure'].upper()} / volatility {B['volatility'].upper()} / liquidity {B['liquidity'].upper()} / momentum {B['momentum'].upper()} — label confidence {conf} ({bear} of {len(tm)} price/breadth/macro signals bearish, {bull} bullish, {neu} neutral).**

1. **A broad, accelerating downtrend.** All 9 assets are Bearish (BTC and LINK 4/5 votes, the other seven 5/5; BTC's EMA50 is still above EMA200, its one bullish vote). BTC {B['close']:,.0f} is {p(B['c_vs_ema200'])} vs EMA200, {p(B['ret30'])} over 30d; ADX {B['adx']:.1f} and rising ({B['adx_chg5']:+.1f} in 5d). [M]
2. **All three tested strategies are gated off by their own rules.** MOM needs close>SMA300(4H), BTC>SMA300 and M≥1.25 (BTC M={G['CRY-MOM-101']['BTC']['M']:.2f}; BTC must rise {p(mom_dist['pct_to_sma300'])} to reach its 4H SMA300); REV's trend filter fails everywhere; VEX's 4H>SMA50 context fails on all 9. Zero signals in the last 7 days on any asset. [M] The classification therefore supports **no new entries** in the current regime — the research-consistent action is to stay flat/paper-only, not to find a better-fitting rule.
3. **Contrarian/valuation indicators disagree with the trend and are not enough to relabel.** Fear & Greed {OS['fear_greed']['latest']} ({OS['fear_greed']['latest_class']}), MVRV {OS['coinmetrics']['mvrv']:.2f} (provisional, 78-day window only) and 7-day exchange outflow {OS['coinmetrics']['netflow_7d_usd']/1e9:+.2f}B are washed-out readings. They raise the odds of a regime change but are not part of the preselected direction rule, and none is a validated reversal signal. [D]
4. **Volatility is only 'Normal' (RV30 at percentile {B['rv30_pctile']:.0f}) despite a {p(B['ret30'])} month** — an orderly grind rather than a spike; but RV7 (percentile {B['rv7_pctile']:.0f}) is above RV30 and the S&P 500 is {p(sp['from_high'])} from its high with VIX {vx['last']:.1f}. Risk-off macro agrees with crypto. [M]
5. **Concentration is near the Stage 03 limit:** 30-day mean pairwise correlation {BR['mean_pairwise_corr_30d']:.3f} vs the 0.90 T9 threshold (definition may differ). [M]
6. **Liquidity is mixed:** LINK and DOGE Weak by the volume rule; ADA, LINK, AVAX, LTC fail the Stage-01 L1 gate ($20M median daily); BTC is Strong by the completed day (1.58×, the sell-off day) but Average on a rolling-24h basis (1.08×). [M]

## A. Timestamped regime assessment

Snapshot fetched {r['fetched_utc']} UTC. Indicators use **completed UTC days** (last completed day {B['date']}); signal-gate state uses the last completed 4H/1H bar (Binance spot, last 1H bar open {CV['BTC']['binance_last_bar_open']} UTC). The Binance spot archive used by Stage 02 and the live API agree exactly on {r['overlap_check']['BTC']['n_overlap']} overlapping BTC hours (max relative close difference {r['overlap_check']['BTC']['max_rel_close_diff']:.1e}).

{tbl(["Asset","Direction","Votes +/-","EMA stack","ADX","Structure","ATR%","RV30 pctile","Volatility","Momentum","30d ret","Vol ratio day/24h","Liquidity","30d vs BTC"], arows)}

\\* completed-day and rolling-24h volume rules disagree → reported Average. Direction votes: close>EMA200, EMA50>EMA200, EMA20>EMA50, +DI>-DI, 30d return>0.

**Market level:** Direction **Bearish** (BTC Bearish, {BR['share_bearish']*9:.0f}/9 assets Bearish ≥ 60%); Volatility **Normal** (BTC; SOL/DOGE Low; none Elevated); Liquidity **Average** with a documented conflict (see table); Momentum **Negative** (8/9 Negative, AVAX Mixed); Structure **Trending** ({BR['share_trending']*9:.0f}/9; AVAX Transitioning). Confidence **{conf}** on direction; **CONDITIONAL** on volatility and liquidity labels, whose thresholds need calibration.

**What would make this UNCERTAIN instead (checked, none triggered):** stale data (max bar age {r['data_quality']['max_age_hours']:.2f}h), venue disagreement (max Binance–Coinbase gap {r['data_quality']['max_abs_basis_bp']:.1f}bp, a stable USDT/USD basis of ~10–18bp, hourly deviation ≈1bp), or a breadth split. Two inputs are stale relative to now and are context only: S&P 500 ({sp['last_date']}) and the broad USD index ({dxy['last_date']}).

![BTC regime inputs](stage04/regime_btc.png)

### Cross-venue and liquidity detail

{tbl(["Asset","Binance last close","Binance vs Coinbase (bp)","basis σ-ish (bp)","bar age (h)","Binance spread (bp)","Binance depth ±10bp (k USD, thinner side)","Coinbase spread (bp)","Coinbase depth ±10bp (k USD)","24h quote vol (M USDT)"], crow)}

† Binance snapshot has 100 levels per side; where the book does not span ±10bp, depth is understated. Depth and spread are reported, **not used** in labels (no calibration). Single snapshot only; no depth history exists.

### Derivatives (perpetual funding, open interest, liquidations)

{tbl(["Asset","HL funding (ann.)","OKX funding (ann.)","HL OI (M USD)","OKX OI (M USD)","OKX OI 7d","OKX liquidations last window: long / short (k USD)"], drow)}

Funding is mildly positive on BTC (Hyperliquid at its {DV['hyperliquid']['BTC']['fund_pctile_31d']:.0f}th 31-day percentile; OKX at the {DV['okx']['BTC']['fund_pctile']:.0f}th percentile of the last ~33 days), slightly negative on OKX ETH ({p(DV['okx']['ETH']['funding_ann'])}). **Not crowded.** OKX BTC open interest fell {p(DV['okx']['BTC']['oi_chg_7d'])} in 7 days and ETH {p(DV['okx']['ETH']['oi_chg_7d'])}: de-leveraging, not a build-up. The OKX liquidation endpoint returns only the latest ~100 filled events (≈{DV['okx']['BTC']['liq_span_min']:.0f} min), valued with an **assumed** contract size (BTC 0.01, ETH 0.1): no cascade is visible in that window, but a 40-minute window says nothing about the past week. Binance and Bybit derivatives data are blocked from this container (HTTP 451/403) [U].

### Macro and on-chain

- **S&P 500** {sp['last']:,.0f} ({sp['last_date']}): {p(sp['pct_20obs'])} over 20 obs, {p(sp['from_high'])} from 252-obs high. **VIX** {vx['last']:.2f} ({vx['last_date']}; {vx['pctile_1y']:.0f}th 1y percentile; +{vx['chg_20obs']:.1f} in 20 obs). **US 10y** {t10['last']:.2f}% ({t10['last_date']}; {t10['pctile_1y']:.0f}th pctile). **Broad USD** {dxy['last']:.1f} ({dxy['last_date']}; at its 252-obs high). Source: FRED public CSV. [M]
- **BTC–S&P 500 correlation:** {M['corr_btc_spx_30obs']['corr']:.2f} on {M['corr_btc_spx_30obs']['n']} paired days (asynchronous closes; a coincident-risk indicator, not a tested predictor). [M]
- **Scheduled events** (secondary calendars; **not verified against federalreserve.gov/bls.gov**): {ev}. Nothing scheduled inside the next 7 days other than the derived holiday/expiry effects. October CPI was due Nov 10; its outcome and market surprise were **not retrieved** [U].
- **Sentiment:** Fear & Greed {OS['fear_greed']['latest']} ({OS['fear_greed']['latest_class']}, {OS['fear_greed']['latest_ts'][:10]}); 30-day mean {OS['fear_greed']['mean_30d']:.0f}; {OS['fear_greed']['pct_days_le20_60d']*100:.0f}% of the last 60 days ≤20. BTC dominance {OS['global']['btc_dominance']:.1f}%, total market cap {p(OS['global']['mcap_chg_24h_pct']/100)} in 24h (CoinGecko). [M]
- **On-chain (limited):** Coinmetrics community MVRV {OS['coinmetrics']['mvrv']:.2f} for {OS['coinmetrics']['last_time'][:10]} (single provider; flow fields flagged 'flash'/provisional; **no second source**), exchange netflow 7d {OS['coinmetrics']['netflow_7d_usd']/1e9:+.2f}B USD. Hashrate cross-check: blockchain.info {r['onchain_sentiment']['blockchain_info']['hash_rate_GHs']/1e9:,.0f} EH/s vs mempool.space {r['onchain_sentiment']['mempool']['current_hashrate_Hs']/1e18:,.0f} EH/s (agree within ~7%; mempool +{r['onchain_sentiment']['mempool']['chg_90d']*100:.1f}% over 90d, next difficulty adjustment {r['onchain_sentiment']['mempool']['difficulty_next_chg_pct']:+.1f}% est.) — network health is not stressed. MVRV, SOPR, realised-cap ratios, ETF flows and stablecoin supply were **not independently verified**. [U]

## B. Indicator and threshold table

{tbl(["Dimension / indicator","Rule (thresholds)","Current reading (BTC)","Label","Threshold status"], thr_rows)}

**Preselected vs requires calibration.** All thresholds were fixed in `stage04/regime.py` before the current values were computed and are conventional, not fitted. The rules marked REQUIRES CALIBRATION have never been tested for stability, sensitivity or predictive value; the Stage 02 trade split below is purely descriptive and was not used to set any cut. Percentile-based volatility labels depend on a {r['btc_rv30_hist_n']}-day history starting {r['btc_rv30_hist_start']} (which contains the 2022 bear market and the consumed final year). Cut levels for BTC RV30: 25th {p0(r['btc_rv30_cuts']['p25'],0)}, 50th {p0(r['btc_rv30_cuts']['p50'],0)}, 75th {p0(r['btc_rv30_cuts']['p75'],0)}, 95th {p0(r['btc_rv30_cuts']['p95'],0)}. In this history ADX≥25 on {r['btc_adx_hist']['share_ge25']*100:.0f}% of days, so "Trending" is not rare for BTC under this definition.

## C. Signal agreement / disagreement (BTC-anchored)

{tbl(["Group","Signal","Stance","Reading"], [[x[0], x[1], st(x[2]), x[3]] for x in sig])}

- **Agree (trend + breadth + macro):** {bear} of {len(tm)} bearish; the only bullish trend vote is BTC's EMA50>EMA200 (a lagging 200-day-scale relationship).
- **Disagree (contrarian/valuation):** 3 of 3 valuation/sentiment/flow signals are washed-out/bullish-contrarian. Treated as **regime-change risk**, not as direction, because the direction rule is trend-based and the contrarian readings are provisional, short-window, or have no tested lead time.
- **Internal tension (not a conflict in direction):** high ADX + falling OI + extreme fear is what a late-stage trend looks like, but this repository has **no tested exhaustion rule**, so the label stays Bearish/Trending [D].
- **Volume paradox:** volume on the last completed day was 1.58× its baseline (Strong) while the rolling 24h is 1.08× (Average): sell-off participation faded. Reported as Average.

## D. Strategy-to-regime suitability matrix

{tbl(["Strategy (Stage 03 eligibility)","Stage-01 regime hypothesis","Current regime vs hypothesis","Suitability now [M]","Implication"], suit_rows)}

Per-asset gate failures, last completed bar (MOM): {"; ".join(f"{s}: {mom_state(s)}" for s in SY)}.

Assets passing Stage-01 L1–L3 gates now: {", ".join(okl)}. ADA, LINK, AVAX, LTC fail ≥1 gate.

**[H] Descriptive history for the current BTC tag (Bearish|Trending), Stage 02 baseline standalone books, assumed costs, includes the consumed final year; no significance testing, no thresholds tuned on it:**

{tbl(["Strategy","Trades entered under current tag","Trades entered under any Bearish tag","Largest cells (dir|struct, n, mean R)"], hist_rows)}

The tag was assigned from the prior daily close. Days in this tag over the 5.5-year history: Bearish|Trending {dc.get('Bearish|Trending',0)} of {sum(dc.values())}. MOM and REV (long-only with SMA300 filters) almost never trade in Bearish tags by construction, so their history cannot say how they behave in this regime — it can only say the rule keeps them out. VEX did trade in Bearish|Trending (159 trades, mean R {H['CRY-VEX-103']['dir_x_struct'].get('Bearish|Trending',{}).get('mean_R',0):+.2f} at assumed costs), but the 4H SMA50 context currently blocks all signals, and a mean R of that size is within the noise Stage 03 documented (VEX cost drag ≈ gross edge). **No regime-conditioned performance claim is made.**

## E. Regime change triggers

{tbl(["#","Trigger","Current / distance","Note"], trig_rows)}

Handling rule: any of R9, or two or more of R1–R8 flipping in the same 24h, moves the label to **UNCERTAIN** until re-measured on completed bars. Re-run `PYTHONPATH=. scripts/lab python -m stage04.fetch_live` then `-m stage04.regime`. All trigger levels are measurements of distance, not forecasts; no probability of a regime change is asserted.

## F. STAGE_04_HANDOFF

See `STAGE_04_HANDOFF.json`. Key content: classification {{Direction Bearish, Volatility Normal, Liquidity Average (conflict), Momentum Negative, Structure Trending}}, confidence {conf}; strategy suitability NOT SUPPORTED NOW for all three (gates closed); eligibility unchanged from Stage 03 but with no admissible entries; evidence SHA-256 for every fetched file; limitations and unresolved items below.

## Limitations and missing inputs

- Venue is still unspecified (Stage 01). Binance spot (public mirror) is the primary price source; Coinbase and Kraken are cross-checks. Binance/Bybit perpetuals blocked; funding/OI come from Hyperliquid and OKX, which are different venues and populations.
- No options/implied-vol, spot-ETF flow, stablecoin-supply, SOPR/realised-cap or cohort-position data; liquidation history unavailable beyond ~40 minutes; macro event outcomes not retrieved; FRED combined request timed out (single-series requests used); S&P 500 and USD series 2–5 days stale.
- Percentile/threshold cuts are uncalibrated; the 5.5-year reference window contains one full cycle and the consumed final year. A single snapshot cannot show stability of the label across time.
- Contract sizes for OKX liquidation USD values are assumed. Order-book snapshots are single, 100-level and venue-specific.
- Historical regime-conditioned trade statistics are small-sample, descriptive, cost-assumed and include `CONSUMED_LEGACY` data. They are not evidence for or against any strategy.

## Sources (public, read-only)

Binance spot via data-api.binance.vision (klines, 24h ticker, depth); Coinbase Exchange API (candles, book); Kraken public Ticker; Hyperliquid info API (metaAndAssetCtxs, fundingHistory); OKX public API (funding, open interest, rubik OI, liquidation orders); alternative.me Fear & Greed; CoinGecko global; Coinmetrics community API; blockchain.info stats; mempool.space; FRED CSV (SP500, VIXCLS, DGS10, DTWEXBGS). Calendar: [Federal Reserve December 2026 page](https://www.federalreserve.gov/newsevents/2026-december.htm), [FOMC Dec 2026 (calendarx)](https://www.calendarx.com/events/fomc-meeting-december-2026), [Dec 2026 release schedule (fedratecalc)](https://fedratecalc.com/us-economic-calendar/december-2026/) — dates from search snippets, not verified at the primary source. Raw responses and SHA-256 manifest: ignored `data/s4raw/{r['snapshot']}/`; hashes embedded in the handoff.
"""
(D / "STAGE_04_REGIME_REPORT.md").write_text(md)

handoff = dict(
 handoff_type="STAGE_04_HANDOFF", schema_version="1.0", status="REGIME_CLASSIFIED_DIRECTION_SUPPORTED_THRESHOLDS_UNCALIBRATED", created=r["fetched_utc"], code_commit=head,
 inputs=dict(stage01="STAGE_01_HANDOFF.v2.json", stage02="STAGE_02_HANDOFF.json", stage03="STAGE_03_HANDOFF.json", stage03_eligibility={k: v["stage03"] for k, v in json.load(open(D / "STAGE_03_HANDOFF.json"))["eligibility"].items()}),
 constraints=dict(research_only=True, orders=False, credentials=False, consumed_window="2025-11-17..2026-11-17 CONSUMED_LEGACY, not a holdout", dispositions="only research/validation/adjudicate.py (not run here)"),
 as_of_utc=r["fetched_utc"], snapshot=r["snapshot"],
 classification=dict(market=dict(direction="Bearish", volatility="Normal", liquidity="Average", liquidity_conflict="completed-day Strong (1.58x) vs rolling-24h Average (1.08x)", momentum="Negative", structure="Trending", anchor="BTC", breadth_bearish=f"{BR['share_bearish']*9:.0f}/9", confidence=conf, agreement=dict(bearish=bear, bullish=bull, neutral=neu, total=len(tm), ratio=agree),
                     contrarian_disagreement=[x[1] for x in cb]),
                     per_asset={s: {k: A[s][k] for k in ("direction", "structure", "volatility", "momentum", "liquidity", "liquidity_conflict", "votes_bull", "votes_bear", "adx", "rv30_pctile", "ret30", "c_vs_ema200", "vratio", "rolling24h_vratio")} for s in SY}),
 measurements=dict(btc={k: B[k] for k in ("date", "close", "ema20", "ema50", "ema200", "adx", "pdi", "mdi", "atr_pct", "rv30", "rv30_pctile", "rv7", "rv7_pctile", "ret7", "ret30", "ret90", "er30", "vratio")}, breadth=BR, derivatives=DV["okx"]["BTC"] | dict(hl_funding_ann=DV["hyperliquid"]["BTC"]["funding_ann"]),
                   macro={k: M[k] for k in ("SP500", "VIXCLS", "DGS10", "DTWEXBGS", "corr_btc_spx_30obs")}, sentiment=OS["fear_greed"], onchain=OS["coinmetrics"]),
 strategy_suitability={"CRY-MOM-101": dict(now="NOT_SUPPORTED_GATE_CLOSED", assets_passing=[s for s in SY if G["CRY-MOM-101"][s]["signal_now"]], btc_M=G["CRY-MOM-101"]["BTC"]["M"], btc_pct_to_sma300=TR["BTC"]["pct_to_sma300"], action="stand aside / paper-monitor"),
                      "CRY-REV-102": dict(now="NOT_SUPPORTED_GATE_CLOSED", assets_passing=[], action="shadow log only"),
                      "CRY-VEX-103": dict(now="NOT_SUPPORTED_GATE_CLOSED_CTX_4H_SMA50", assets_passing=[], action="shadow/paper only; would arm when 4H close > SMA50")},
 eligible_universe_now_by_liquidity_gates=okl, gates=G, regime_change_triggers=[dict(id=t[0].split()[0], trigger=t[1], current=t[2], note=t[3]) for t in trig_rows],
 thresholds=dict(values={k: v for k, v in TH.items()}, status=r["threshold_status"]),
 historical_descriptive=dict(note="Stage 02 baseline standalone trades by BTC prior-close tag; assumed costs; includes consumed final year; descriptive only", by_regime=H, tag_day_counts=r["hist_regime_day_counts"]),
 data_quality=r["data_quality"], cross_venue_summary={s: dict(basis_bp=CV[s]["basis_bp_binance_vs_coinbase"], age_h=CV[s]["age_hours_at_fetch"]) for s in SY},
 evidence=dict(files=["docs/strategy-specs/stage04/regime_results.json", "docs/strategy-specs/stage04/btc_daily_indicators.csv", "docs/strategy-specs/stage04/regime_btc.png", "docs/strategy-specs/STAGE_04_REGIME_REPORT.md"], raw_sha256=r["evidence_hashes"], raw_location="data/s4raw/%s/ (gitignored)" % r["snapshot"]),
 scheduled_events_unverified=["FOMC Dec 8-9 (decision Dec 9)", "Jobs report Dec 4", "CPI Dec 10 (one calendar lists Dec 4; conflict)", "US Thanksgiving Nov 26 (derived)", "Monthly derivatives expiry Nov 27 (derived)"],
 uncertainty=dict(confident=["direction Bearish (price+breadth+macro agree)", "all three strategy gates closed (rule evaluation on measured data)"],
                  conditional=["volatility Normal (percentile cut uncalibrated; RV7>RV30)", "liquidity Average (rule disagreement; thresholds uncalibrated)", "structure Trending (ADX cut conventional; ER cut uncalibrated)"],
                  not_assessable=["probability of regime change or reversal", "regime-conditioned strategy performance", "options/IV, ETF flows, stablecoin supply, liquidation history, macro surprises", "second source for on-chain metrics"]),
 limitations=["single snapshot; label stability over time untested", "execution venue unspecified", "perp data from Hyperliquid/OKX only (Binance/Bybit blocked)", "FRED S&P500/USD series stale by 2-5 days", "OKX liquidation USD uses assumed contract sizes", "thresholds uncalibrated", "history includes consumed window"],
 unresolved=["calibrate regime thresholds on pre-registered splits (stability, sensitivity) before using labels to gate strategies", "obtain primary-source event calendar and outcomes", "specify execution venue and its derivatives data", "forward-log this classifier daily (paper) to measure label persistence", "ledger registration/preregistration and adjudicate.py still pending from Stage 02/03"],
 next_stage_guidance="Stage 05 should treat all three strategies as inactive under the current label; any regime filter derived from these labels is a NEW research hypothesis requiring registration and preregistration before test-split access.",
)
(D / "STAGE_04_HANDOFF.json").write_text(json.dumps(handoff, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
print("report", len(md), "chars; conf", conf, bear, bull, neu)
