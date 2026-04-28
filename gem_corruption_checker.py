"""
Gem corruption profit checker for Path of Exile.

Looks up current trade prices for support gems, then calculates whether
it's profitable to buy them, level them up, and corrupt them with a
Lapidary Lens. For each gem it checks the buy price (uncorrupted lvl 1)
and all three corruption outcomes (+1 level, same level, -1 level),
then spits out EV, ROI, and how many failed corruptions one hit covers.

Usage:
    python gem_corruption_checker.py [all|multi|eclipse|comp|echo|enlighten|empower|enhance]
"""

import os
import requests
import time
import json
import sys
from datetime import datetime

# -- Config --
# Swap these values as prices shift throughout the league.

LEAGUE = "Mirage"
DELAY_SECONDS = 10          # seconds between API searches — 10 is safe, don't go below 5
RESULTS_TO_CHECK = 5        # listings to pull per search
DIVINE_RATE = 340           # current divine-to-chaos ratio
LAPIDARY_COST = 1           # divine cost for a Lapidary Lens service
LEVELING_COST = 0.5         # rough divine cost to level + quality a gem via beastcraft


def load_session_id():
    """Pull POESESSID from .env file, environment, or CLI arg."""
    # check .env file in same directory
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("POESESSID=") and not line.startswith("#"):
                    val = line.split("=", 1)[1].strip()
                    if val and val != "your_session_id_here":
                        return val

    # fall back to environment variable
    if os.environ.get("POESESSID"):
        return os.environ["POESESSID"]

    # or a long-ish CLI argument (session IDs are 32+ chars)
    for arg in sys.argv[1:]:
        if len(arg) > 10:
            return arg

    print("ERROR: No POESESSID found.")
    print("  1. Copy .env.example to .env")
    print("  2. Paste your session ID after POESESSID=")
    print("  (find it: pathofexile.com → F12 → Application → Cookies)")
    sys.exit(1)


# -- Gems to evaluate --
# (name, max_uncorrupted_level, shortcut, quality_matters_for_pricing)
#
# max level is the level you buy at before corrupting — 3 for exceptional gems, 4 for awakened.
# quality_matters means the 20q and 23q corrupted versions trade at different prices,
# so we filter sell lookups to 20q specifically.

GEMS = [
    ("Greater Multistrike Support", 3, "multi", True),
    ("Eclipse Support",             3, "eclipse", False),
    ("Companionship Support",       3, "comp", True),
    ("Greater Spell Echo Support",  3, "echo", True),
    ("Awakened Enlighten Support",  4, "enlighten", False),
    ("Awakened Empower Support",    4, "empower", False),
    ("Awakened Enhance Support",    4, "enhance", False),
]


# -- Trade API helpers --

BASE_URL = "https://www.pathofexile.com"
SEARCH_URL = f"{BASE_URL}/api/trade/search/{LEAGUE}"
FETCH_URL = f"{BASE_URL}/api/trade/fetch"


def build_session(sessid):
    s = requests.Session()
    s.cookies.set("POESESSID", sessid, domain="www.pathofexile.com")
    s.headers.update({
        "User-Agent": "GemCorruptionChecker/1.0 (personal use)",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    return s


def to_divine(amount, currency):
    """Convert any listing price to divines."""
    if currency == "divine":
        return amount
    elif currency == "chaos":
        return amount / DIVINE_RATE
    elif currency == "exalted":
        return amount * 12 / DIVINE_RATE
    return amount / DIVINE_RATE


def fmt(divs):
    """Pretty-print a divine value. Shows chaos for tiny amounts."""
    if divs < 0.1:
        return f"{divs * DIVINE_RATE:.0f}c"
    return f"{divs:.2f}div"


def search_gem(session, name, level, corrupted, quality=None):
    """Hit the trade API for a specific gem at a given level/corruption/quality."""
    filters = {
        "gem_level": {"min": level, "max": level},
        "corrupted": {"option": "true" if corrupted else "false"},
    }
    if quality is not None:
        filters["quality"] = {"min": quality, "max": quality}

    query = {
        "query": {
            "status": {"option": "securable"},  # instant buyout only
            "type": name,
            "filters": {
                "misc_filters": {"filters": filters},
                "type_filters": {"filters": {"category": {"option": "gem"}}},
                "trade_filters": {"filters": {"sale_type": {"option": "priced"}}},
            },
        },
        "sort": {"price": "asc"},
    }

    try:
        r = session.post(SEARCH_URL, json=query, timeout=15)

        if r.status_code == 429:
            print("      ⚠ Rate limited, waiting 120s...")
            time.sleep(120)
            r = session.post(SEARCH_URL, json=query, timeout=15)

        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:200]}"

        data = r.json()
        ids = data.get("result", [])
        total = data.get("total", 0)

        if total == 0 or not ids:
            return {"total": 0, "prices": []}, None

        # grab the first batch of listings
        to_fetch = ids[:RESULTS_TO_CHECK]
        listings = []
        for i in range(0, len(to_fetch), 10):
            batch = to_fetch[i:i + 10]
            resp = session.get(f"{FETCH_URL}/{','.join(batch)}?query={data['id']}", timeout=15)
            if resp.status_code == 429:
                print("      ⚠ Rate limited on fetch, waiting 60s...")
                time.sleep(60)
                resp = session.get(f"{FETCH_URL}/{','.join(batch)}?query={data['id']}", timeout=15)
            if resp.status_code == 200:
                listings.extend(resp.json().get("result", []))

        prices = []
        for item in listings:
            info = item.get("listing", {}).get("price", {})
            prices.append({
                "amount": info.get("amount", 0),
                "currency": info.get("currency", ""),
                "account": item.get("listing", {}).get("account", {}).get("name", "?"),
            })

        # if any results are priced in divines, grab more listings to make sure
        # we're not missing cheaper chaos-priced ones hidden by GGG's stale sort rate
        if any(p["currency"] == "divine" for p in prices):
            extras = ids[len(to_fetch):len(to_fetch) + 10]
            if extras:
                resp = session.get(f"{FETCH_URL}/{','.join(extras)}?query={data['id']}", timeout=15)
                if resp.status_code == 200:
                    for item in resp.json().get("result", []):
                        info = item.get("listing", {}).get("price", {})
                        prices.append({
                            "amount": info.get("amount", 0),
                            "currency": info.get("currency", ""),
                            "account": item.get("listing", {}).get("account", {}).get("name", "?"),
                        })

        return {"total": total, "prices": prices}, None

    except Exception as e:
        return None, str(e)


def cheapest(prices):
    """Return the cheapest listing price in divines."""
    if not prices:
        return 0, 0
    by_div = sorted([(to_divine(p["amount"], p["currency"]), p) for p in prices], key=lambda x: x[0])
    return by_div[0][0], len(by_div)


def avg_cheapest_5(prices):
    """Average the 5 cheapest listings (for bulk buying)."""
    if not prices:
        return 0, 0
    by_div = sorted([(to_divine(p["amount"], p["currency"]), p) for p in prices], key=lambda x: x[0])
    top = by_div[:5]
    return sum(x[0] for x in top) / len(top), len(by_div)


def lookup(session, name, level, corrupted, label, quality=None, is_buy=False):
    """Search for a gem and return its price in divines."""
    corr = "corrupted" if corrupted else "uncorrupted"
    q = f" {quality}q" if quality else ""
    print(f"    {label}: {name} Lvl{level}{q} {corr}...", end="", flush=True)

    data, err = search_gem(session, name, level, corrupted, quality=quality)
    if err:
        print(f" ✗ {err}")
        return 0, 0
    if data["total"] == 0:
        print(f" ○ no listings")
        return 0, 0

    if is_buy:
        price, supply = avg_cheapest_5(data["prices"])
        print(f" ✓ {fmt(price)} avg5 ({supply} listed)")
    else:
        price, supply = cheapest(data["prices"])
        print(f" ✓ {fmt(price)} ({supply} listed)")
    return price, supply


# -- Main --

def main():
    sessid = load_session_id()
    session = build_session(sessid)

    # figure out which gems to check
    gem_filter = "all"
    for arg in sys.argv[1:]:
        if len(arg) < 10:
            gem_filter = arg.lower()

    if gem_filter == "all":
        active = GEMS
    else:
        active = [g for g in GEMS if g[2] == gem_filter]
        if not active:
            print(f"Unknown filter: {gem_filter}")
            print(f"Options: all, {', '.join(g[2] for g in GEMS)}")
            sys.exit(1)

    total_lookups = len(active) * 4  # buy + hit + stay + drop per gem

    print("=" * 70)
    print("  PoE Gem Corruption Profit Checker")
    print(f"  League: {LEAGUE}  |  Divine: {DIVINE_RATE}c")
    print(f"  Lapidary: {LAPIDARY_COST} div  |  Leveling: {LEVELING_COST} div")
    print(f"  Checking {len(active)} gem(s), {total_lookups} lookups (~{total_lookups * DELAY_SECONDS / 60:.0f} min)")
    print(f"  Usage: python gem_corruption_checker.py [all|{' |'.join(g[2] for g in GEMS)}]")
    print("=" * 70)

    results = []

    for gem_name, max_level, category, quality_matters in active:
        print(f"\n{'─' * 50}")
        print(f"  {gem_name}{' (20q pricing)' if quality_matters else ''}")
        print(f"{'─' * 50}")

        sell_q = 20 if quality_matters else None

        # four lookups: what you pay, and the three corruption outcomes
        buy_price, buy_supply = lookup(session, gem_name, 1, False, "BUY ", quality=None, is_buy=True)
        time.sleep(DELAY_SECONDS)

        hit_price, _ = lookup(session, gem_name, max_level + 1, True, "HIT ", quality=sell_q)
        time.sleep(DELAY_SECONDS)

        stay_price, _ = lookup(session, gem_name, max_level, True, "STAY", quality=sell_q)
        time.sleep(DELAY_SECONDS)

        drop_price, _ = lookup(session, gem_name, max_level - 1, True, "DROP", quality=sell_q)
        if active[-1] != (gem_name, max_level, category, quality_matters):
            time.sleep(DELAY_SECONDS)

        # crunch the numbers
        total_cost = buy_price + LAPIDARY_COST + LEVELING_COST
        ev = (0.25 * hit_price) + (0.50 * stay_price) + (0.25 * drop_price)
        profit = ev - total_cost
        roi = (profit / total_cost * 100) if total_cost > 0 else 0
        loss_stay = total_cost - stay_price
        loss_drop = total_cost - drop_price
        gain = hit_price - total_cost
        avg_loss = (loss_stay + loss_drop) / 2
        hits_per_miss = gain / avg_loss if avg_loss > 0 else 0

        print(f"\n  ┌─ RESULTS {'─' * 38}")
        print(f"  │ Cost: {fmt(buy_price)} + {fmt(LAPIDARY_COST)} lap + {fmt(LEVELING_COST)} lvl = {fmt(total_cost)}")
        print(f"  │ Hit (25%):  {fmt(hit_price):>10}  →  +{fmt(gain)}")
        print(f"  │ Stay (50%): {fmt(stay_price):>10}  →  -{fmt(loss_stay)}")
        print(f"  │ Drop (25%): {fmt(drop_price):>10}  →  -{fmt(loss_drop)}")
        print(f"  │")
        print(f"  │ EV: {fmt(ev)} | Profit: {'+' if profit >= 0 else ''}{fmt(abs(profit))} | ROI: {roi:.0f}%")
        print(f"  │ 1 hit covers {hits_per_miss:.1f} misses")
        print(f"  └{'─' * 48}")

        results.append({
            "name": gem_name,
            "category": category,
            "cost": total_cost,
            "hit": hit_price,
            "stay": stay_price,
            "drop": drop_price,
            "ev": ev,
            "profit": profit,
            "roi": roi,
            "hit_gain": gain,
            "miss_loss": avg_loss,
            "misses_covered": hits_per_miss,
            "buy_supply": buy_supply,
        })

    # -- Rankings --

    print("\n\n" + "=" * 70)
    print("  FINAL RANKING (sorted by ROI)")
    print("=" * 70)
    print(f"  {'Gem':<30} {'Entry':>6} {'Profit':>8} {'ROI':>6} {'Miss':>6} {'Hit covers':>11} {'Supply':>7}")
    print(f"  {'─' * 30} {'─' * 6} {'─' * 8} {'─' * 6} {'─' * 6} {'─' * 11} {'─' * 7}")

    for r in sorted(results, key=lambda x: -x["roi"]):
        p = f"+{r['profit']:.1f}" if r["profit"] >= 0 else f"{r['profit']:.1f}"
        print(f"  {r['name']:<30} {r['cost']:>5.1f}d {p:>7}d {r['roi']:>5.0f}% {r['miss_loss']:>5.1f}d {r['misses_covered']:>9.1f}x  {r['buy_supply']:>5}")

    # batch analysis for the top pick
    if results:
        best = max(results, key=lambda x: x["roi"])
        if best["roi"] > 0:
            print(f"\n{'─' * 50}")
            print(f"  BATCH ANALYSIS: {best['name']}")
            print(f"{'─' * 50}")
            for n in [6, 8, 10, 15, 20]:
                inv = n * best["cost"]
                if inv > 1200:
                    continue
                exp = n * best["profit"]
                p0 = (0.75 ** n) * 100
                p1 = n * 0.25 * (0.75 ** (n - 1)) * 100
                p2 = 100 - p0 - p1
                print(f"\n  Batch of {n}: {inv:.0f} div invested")
                print(f"    Expected profit: +{exp:.1f} div")
                print(f"    0 hits: {p0:.0f}% (lose ~{n * best['miss_loss']:.0f} div)")
                print(f"    1 hit:  {p1:.0f}%")
                print(f"    2+ hits: {p2:.0f}% ")

    # save results to disk
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = f"gem_corruption_{ts}.json"
    with open(outfile, "w") as f:
        json.dump({
            "league": LEAGUE,
            "divine_rate": DIVINE_RATE,
            "note": "all prices in divines",
            "timestamp": ts,
            "results": results,
        }, f, indent=2)
    print(f"\n  Saved to {outfile}")
    print(f"  Done (~{total_lookups * DELAY_SECONDS / 60:.0f} min)")


if __name__ == "__main__":
    main()
