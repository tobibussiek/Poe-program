"""
Divination card gambling EV checker for Path of Exile.

Looks up the sell price for every possible gem outcome of a div card set,
then calculates the expected value of turning in a full set. Helps figure
out which div cards are actually profitable to gamble vs. which ones are traps.

Currently tracks: Volatile Power, Gemcutter's Mercy, The Wilted Rose, The Bitter Blossom.

Usage:
    python poe_price_checker.py [volatile|wilted|mercy|bitter|all]
"""

import os
import requests
import time
import json
import sys
from datetime import datetime

# -- Config --

LEAGUE = "Mirage"
DELAY_SECONDS = 15          # seconds between searches — 10-15 is safe
RESULTS_TO_CHECK = 20       # pull extra listings to work around GGG's stale divine sort rate
DIVINE_RATE = 185           # current divine-to-chaos ratio

VENDOR_FLOOR = 2.4          # what a junk gem is worth if you vendor it for a GCP
SELL_THRESHOLD = 12         # gems below this price get vendored instead of listed


def load_session_id():
    """Pull POESESSID from .env file, environment, or CLI arg."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("POESESSID=") and not line.startswith("#"):
                    val = line.split("=", 1)[1].strip()
                    if val and val != "your_session_id_here":
                        return val

    if os.environ.get("POESESSID"):
        return os.environ["POESESSID"]

    for arg in sys.argv[1:]:
        if len(arg) > 10:
            return arg

    print("ERROR: No POESESSID found.")
    print("  1. Copy .env.example to .env")
    print("  2. Paste your session ID after POESESSID=")
    print("  (find it: pathofexile.com → F12 → Application → Cookies)")
    sys.exit(1)


# -- Gem outcome pools for each card --
# (gem_name, level, quality, corrupted, card_category)

LOOKUPS = [
    # Volatile Power — 20/20 corrupted vaal gems
    ("Vaal Summon Skeletons", 1, 20, True, "volatile_power"),
    ("Vaal Molten Shell", 1, 20, True, "volatile_power"),
    ("Vaal Haste", 1, 20, True, "volatile_power"),
    ("Vaal Ground Slam", 1, 20, True, "volatile_power"),
    ("Vaal Domination", 1, 20, True, "volatile_power"),
    ("Vaal Absolution", 1, 20, True, "volatile_power"),
    ("Vaal Arc", 1, 20, True, "volatile_power"),
    ("Vaal Earthquake", 1, 20, True, "volatile_power"),
    ("Vaal Grace", 1, 20, True, "volatile_power"),
    ("Vaal Discipline", 1, 20, True, "volatile_power"),
    ("Vaal Reap", 1, 20, True, "volatile_power"),
    ("Vaal Flameblast", 1, 20, True, "volatile_power"),
    ("Vaal Flicker Strike", 1, 20, True, "volatile_power"),
    ("Vaal Cyclone", 1, 20, True, "volatile_power"),
    ("Vaal Righteous Fire", 1, 20, True, "volatile_power"),
    ("Vaal Lightning Arrow", 1, 20, True, "volatile_power"),
    ("Vaal Burning Arrow", 1, 20, True, "volatile_power"),
    ("Vaal Firestorm", 1, 20, True, "volatile_power"),
    ("Vaal Impurity of Lightning", 1, 20, True, "volatile_power"),
    ("Vaal Impurity of Ice", 1, 20, True, "volatile_power"),
    ("Vaal Impurity of Fire", 1, 20, True, "volatile_power"),
    ("Vaal Ice Shot", 1, 20, True, "volatile_power"),
    ("Vaal Animate Weapon", 1, 20, True, "volatile_power"),
    ("Vaal Spark", 1, 20, True, "volatile_power"),
    ("Vaal Blade Vortex", 1, 20, True, "volatile_power"),
    ("Vaal Ice Nova", 1, 20, True, "volatile_power"),
    ("Vaal Blight", 1, 20, True, "volatile_power"),
    ("Vaal Rain of Arrows", 1, 20, True, "volatile_power"),
    ("Vaal Lightning Trap", 1, 20, True, "volatile_power"),
    ("Vaal Cold Snap", 1, 20, True, "volatile_power"),
    ("Vaal Storm Call", 1, 20, True, "volatile_power"),
    ("Vaal Detonate Dead", 1, 20, True, "volatile_power"),
    ("Vaal Arctic Armour", 1, 20, True, "volatile_power"),
    ("Vaal Clarity", 1, 20, True, "volatile_power"),
    ("Vaal Fireball", 1, 20, True, "volatile_power"),
    ("Vaal Power Siphon", 1, 20, True, "volatile_power"),
    ("Vaal Spectral Throw", 1, 20, True, "volatile_power"),
    ("Vaal Glacial Hammer", 1, 20, True, "volatile_power"),
    ("Vaal Cleave", 1, 20, True, "volatile_power"),
    ("Vaal Molten Strike", 1, 20, True, "volatile_power"),
    ("Vaal Double Strike", 1, 20, True, "volatile_power"),
    ("Vaal Blade Flurry", 1, 20, True, "volatile_power"),
    ("Vaal Reave", 1, 20, True, "volatile_power"),
    ("Vaal Smite", 1, 20, True, "volatile_power"),
    ("Vaal Rejuvenation Totem", 1, 20, True, "volatile_power"),
    ("Vaal Lightning Strike", 1, 20, True, "volatile_power"),
    ("Vaal Venom Gyre", 1, 20, True, "volatile_power"),
    ("Vaal Caustic Arrow", 1, 20, True, "volatile_power"),
    ("Vaal Volcanic Fissure", 1, 20, True, "volatile_power"),

    # Gemcutter's Mercy — uncorrupted Empower/Enlighten/Enhance
    ("Empower Support", 1, 0, False, "gemcutters_mercy"),
    ("Enlighten Support", 1, 0, False, "gemcutters_mercy"),
    ("Enhance Support", 1, 0, False, "gemcutters_mercy"),

    # The Wilted Rose — level 21 corrupted aura gems
    ("Determination", 21, 0, True, "wilted_rose"),
    ("Grace", 21, 0, True, "wilted_rose"),
    ("Hatred", 21, 0, True, "wilted_rose"),
    ("Discipline", 21, 0, True, "wilted_rose"),
    ("Wrath", 21, 0, True, "wilted_rose"),
    ("Anger", 21, 0, True, "wilted_rose"),
    ("Zealotry", 21, 0, True, "wilted_rose"),
    ("Malevolence", 21, 0, True, "wilted_rose"),
    ("Pride", 21, 0, True, "wilted_rose"),
    ("Clarity", 21, 0, True, "wilted_rose"),
    ("Vitality", 21, 0, True, "wilted_rose"),
    ("Purity of Elements", 21, 0, True, "wilted_rose"),
    ("Purity of Fire", 21, 0, True, "wilted_rose"),
    ("Purity of Ice", 21, 0, True, "wilted_rose"),
    ("Purity of Lightning", 21, 0, True, "wilted_rose"),
    ("Haste", 21, 0, True, "wilted_rose"),
    ("War Banner", 21, 0, True, "wilted_rose"),
    ("Smite", 21, 0, True, "wilted_rose"),
    ("Precision", 21, 0, True, "wilted_rose"),
    ("Pyroclast Mine", 21, 0, True, "wilted_rose"),
    ("Flesh and Stone", 21, 0, True, "wilted_rose"),
    ("Dread Banner", 21, 0, True, "wilted_rose"),
    ("Stormblast Mine", 21, 0, True, "wilted_rose"),
    ("Rejuvenation Totem", 21, 0, True, "wilted_rose"),
    ("Summon Skitterbots", 21, 0, True, "wilted_rose"),
    ("Defiance Banner", 21, 0, True, "wilted_rose"),
    ("Icicle Mine", 21, 0, True, "wilted_rose"),

    # The Bitter Blossom — 21/23 corrupted chaos-tagged gems
    ("Viper Strike", 21, 23, True, "bitter_blossom"),
    ("Desecrate", 21, 23, True, "bitter_blossom"),
    ("Voltaxic Burst", 21, 23, True, "bitter_blossom"),
    ("Void Manipulation Support", 21, 23, True, "bitter_blossom"),
    ("Essence Drain", 21, 23, True, "bitter_blossom"),
    ("Wither", 21, 23, True, "bitter_blossom"),
    ("Contagion", 21, 23, True, "bitter_blossom"),
    ("Soulrend", 21, 23, True, "bitter_blossom"),
    ("Scourge Arrow", 21, 23, True, "bitter_blossom"),
    ("Despair", 21, 23, True, "bitter_blossom"),
    ("Cobra Lash", 21, 23, True, "bitter_blossom"),
    ("Chance to Poison Support", 21, 23, True, "bitter_blossom"),
    ("Blight", 21, 23, True, "bitter_blossom"),
    ("Toxic Rain", 21, 23, True, "bitter_blossom"),
    ("Alchemist's Mark", 21, 23, True, "bitter_blossom"),
    ("Vicious Projectiles Support", 21, 23, True, "bitter_blossom"),
    ("Forbidden Rite", 21, 23, True, "bitter_blossom"),
    ("Sacrifice Support", 21, 23, True, "bitter_blossom"),
    ("Poisonous Concoction", 21, 23, True, "bitter_blossom"),
    ("Dark Pact", 21, 23, True, "bitter_blossom"),
    ("Withering Step", 21, 23, True, "bitter_blossom"),
    ("Withering Touch Support", 21, 23, True, "bitter_blossom"),
    ("Impending Doom Support", 21, 23, True, "bitter_blossom"),
    ("Plague Bearer", 21, 23, True, "bitter_blossom"),
    ("Venom Gyre", 21, 23, True, "bitter_blossom"),
    ("Bane", 21, 23, True, "bitter_blossom"),
    ("Caustic Arrow", 21, 23, True, "bitter_blossom"),
    ("Void Sphere", 21, 23, True, "bitter_blossom"),
    ("Hexblast", 21, 23, True, "bitter_blossom"),
    ("Added Chaos Damage Support", 21, 23, True, "bitter_blossom"),
    ("Decay Support", 21, 23, True, "bitter_blossom"),
    ("Pestilent Strike", 21, 23, True, "bitter_blossom"),
    ("Herald of Agony", 21, 23, True, "bitter_blossom"),
    ("Summon Chaos Golem", 21, 23, True, "bitter_blossom"),
]

# -- Set costs per card (stack_size × card_price) --
# Update these as card prices change.

CARD_COSTS = {
    "volatile_power": {"label": "2.5c/card", "set_cost": 22.5, "stack": 9},
    "gemcutters_mercy": {"label": "41c/card", "set_cost": 123, "stack": 3},
    "wilted_rose": {"label": "3c/card", "set_cost": 21, "stack": 7},
    "bitter_blossom": {"label": "8c/card", "set_cost": 24, "stack": 3},
}


# -- Trade API helpers --

BASE_URL = "https://www.pathofexile.com"
SEARCH_URL = f"{BASE_URL}/api/trade/search/{LEAGUE}"
FETCH_URL = f"{BASE_URL}/api/trade/fetch"


def build_session(sessid):
    s = requests.Session()
    s.cookies.set("POESESSID", sessid, domain="www.pathofexile.com")
    s.headers.update({
        "User-Agent": "DivCardProfitChecker/1.0 (personal use)",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    return s


def to_chaos(amount, currency, divine_rate):
    """Convert any listing price to chaos."""
    if currency == "chaos":
        return amount
    elif currency == "divine":
        return amount * divine_rate
    elif currency == "exalted":
        return amount * 12
    elif currency in ("fusing", "fuse"):
        return amount * 0.5
    elif currency in ("alch", "alchemy"):
        return amount * 0.5
    elif currency == "vaal":
        return amount * 1.5
    return amount


def search_gem(session, name, level, quality, corrupted):
    """Query the trade API for a specific gem outcome."""
    filters = {
        "gem_level": {"min": level, "max": level},
        "corrupted": {"option": "true" if corrupted else "false"},
    }
    if quality > 0:
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
            print("    ⚠ Rate limited, waiting 120s...")
            time.sleep(120)
            r = session.post(SEARCH_URL, json=query, timeout=15)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:200]}"

        data = r.json()
        ids = data.get("result", [])
        total = data.get("total", 0)

        if total == 0 or not ids:
            return {"total": 0, "prices": []}, None

        # grab listings in batches of 10 (API limit)
        to_fetch = ids[:RESULTS_TO_CHECK]
        listings = []
        for i in range(0, len(to_fetch), 10):
            batch = to_fetch[i:i + 10]
            resp = session.get(f"{FETCH_URL}/{','.join(batch)}?query={data['id']}", timeout=15)
            if resp.status_code == 429:
                print("    ⚠ Rate limited on fetch, waiting 60s...")
                time.sleep(60)
                resp = session.get(f"{FETCH_URL}/{','.join(batch)}?query={data['id']}", timeout=15)
            if resp.status_code != 200:
                print(f"    ⚠ Fetch batch failed: HTTP {resp.status_code}")
                continue
            listings.extend(resp.json().get("result", []))

        prices = []
        for item in listings:
            info = item.get("listing", {}).get("price", {})
            prices.append({
                "amount": info.get("amount", 0),
                "currency": info.get("currency", ""),
                "account": item.get("listing", {}).get("account", {}).get("name", "?"),
            })

        # if we see divine-priced listings, fetch more — GGG's stale sort rate
        # can hide cheaper chaos-listed gems further down the results
        if any(p["currency"] == "divine" for p in prices):
            extras = ids[len(to_fetch):len(to_fetch) + 10]
            if extras:
                print(f"    ↳ divine prices found, pulling more listings...")
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


def format_price(prices, divine_rate):
    """Figure out what this gem would realistically sell for.

    Low supply (≤5 listings): use the cheapest price.
    High supply (>5): skip the cheapest (likely a price fixer) and use the 2nd.
    Gems priced below SELL_THRESHOLD get valued at VENDOR_FLOOR (GCP vendor price).
    """
    if not prices:
        return f"No listings (vendor: {VENDOR_FLOOR}c)", VENDOR_FLOOR

    chaos_entries = []
    for p in prices:
        c = to_chaos(p["amount"], p["currency"], divine_rate)
        if p["currency"] == "divine":
            label = f"{p['amount']}div"
        elif p["currency"] == "chaos":
            label = f"{int(p['amount'])}c"
        else:
            label = f"{p['amount']} {p['currency']}"
        chaos_entries.append((c, label, p.get("account", "?")))

    chaos_entries.sort(key=lambda x: x[0])
    n = len(chaos_entries)

    if n == 1:
        sell_price = chaos_entries[0][0]
        display = chaos_entries[0][1]
    elif n <= 5:
        sell_price = chaos_entries[0][0]
        display = " / ".join(x[1] for x in chaos_entries[:3])
    else:
        sell_price = chaos_entries[1][0]
        display = " / ".join(x[1] for x in chaos_entries[:3])
        if chaos_entries[0][0] < chaos_entries[1][0] * 0.5:
            print(f"    ⚠ likely fixer skipped: {chaos_entries[0][1]} by {chaos_entries[0][2]}")

    if sell_price < SELL_THRESHOLD:
        display += f" → vendor {VENDOR_FLOOR}c"
        sell_price = VENDOR_FLOOR

    return f"{display} → sell at: {sell_price:.0f}c", sell_price


# -- Main --

def main():
    sessid = load_session_id()
    session = build_session(sessid)

    # parse which card to check
    card_filter = "all"
    for arg in sys.argv[1:]:
        if arg.lower() in ("volatile", "vp", "v"):
            card_filter = "volatile_power"
        elif arg.lower() in ("wilted", "rose", "wr", "w"):
            card_filter = "wilted_rose"
        elif arg.lower() in ("mercy", "gem", "gm", "g", "m"):
            card_filter = "gemcutters_mercy"
        elif arg.lower() in ("bitter", "blossom", "bb", "b"):
            card_filter = "bitter_blossom"
        elif arg.lower() == "all":
            card_filter = "all"

    if card_filter == "all":
        active = LOOKUPS
    else:
        active = [l for l in LOOKUPS if l[4] == card_filter]

    names = {
        "all": "All Cards",
        "volatile_power": "Volatile Power",
        "wilted_rose": "Wilted Rose",
        "gemcutters_mercy": "Gemcutter's Mercy",
        "bitter_blossom": "Bitter Blossom",
    }

    print("=" * 70)
    print("  PoE Divination Card Profit Checker")
    print(f"  League: {LEAGUE}  |  Divine: {DIVINE_RATE}c")
    print(f"  Card: {names.get(card_filter, card_filter)}")
    print(f"  Gems to check: {len(active)} (~{len(active) * DELAY_SECONDS / 60:.0f} min)")
    print(f"  Usage: python poe_price_checker.py [volatile|wilted|mercy|bitter|all]")
    print("=" * 70)

    results = {}
    categories = {}

    for i, (name, level, quality, corrupted, category) in enumerate(active):
        corr_str = "corrupted" if corrupted else ""
        qual_str = f"{quality}q" if quality > 0 else ""
        print(f"\n[{i+1}/{len(active)}] {name} Lvl{level} {qual_str} {corr_str} ({category})")

        data, err = search_gem(session, name, level, quality, corrupted)

        if err:
            print(f"    ✗ Error: {err}")
            results[name] = {"chaos": 0, "total": 0, "error": err, "category": category}
        elif data["total"] == 0:
            print(f"    ○ No listings found")
            results[name] = {"chaos": 0, "total": 0, "error": None, "category": category}
        else:
            price_str, sell_price = format_price(data["prices"], DIVINE_RATE)
            print(f"    ✓ {data['total']} listed — {price_str}")
            results[name] = {
                "chaos": sell_price,
                "total": data["total"],
                "error": None,
                "category": category,
            }

        categories.setdefault(category, []).append({
            "name": name,
            "chaos": results[name]["chaos"],
            "total": results[name]["total"],
        })

        if i < len(active) - 1:
            print(f"    ⏳ {DELAY_SECONDS}s...")
            time.sleep(DELAY_SECONDS)

    # -- Summary --

    print("\n\n" + "=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)

    for cat, gems in categories.items():
        print(f"\n{'─' * 50}")
        print(f"  {cat.upper().replace('_', ' ')}")
        print(f"{'─' * 50}")

        total_ev = 0
        count = 0
        vendored = 0

        for g in sorted(gems, key=lambda x: -x["chaos"]):
            if g["chaos"] <= VENDOR_FLOOR:
                status = f"  vendor {VENDOR_FLOOR}c"
                vendored += 1
            else:
                status = f"{g['chaos']:>8.0f}c"
            supply = f"({g['total']} listed)" if g["total"] > 0 else "(no listings)"
            print(f"  {g['name']:<35} {status}  {supply}")
            total_ev += g["chaos"]
            count += 1

        if count > 0:
            ev = total_ev / count
            print(f"\n  Pool: {count} gems ({vendored} vendored at {VENDOR_FLOOR}c)")
            print(f"  EV per turn-in: {ev:.0f}c")

            # show profit at the configured card cost
            if cat in CARD_COSTS:
                info = CARD_COSTS[cat]
                cost = info["set_cost"]
                winners = sum(1 for g in gems if g["chaos"] > cost)
                profit = ev - cost
                roi = (profit / cost * 100) if cost > 0 else 0
                print(f"\n  At {info['label']} (set = {cost}c):")
                print(f"    Profit/set: {profit:.0f}c | ROI: {roi:.0f}%")
                print(f"    Winners: {winners}/{count} ({winners/count*100:.0f}% win rate)")

    # save raw data
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = f"poe_prices_{ts}.json"
    with open(outfile, "w") as f:
        json.dump({
            "league": LEAGUE,
            "divine_rate": DIVINE_RATE,
            "timestamp": ts,
            "results": {k: {kk: vv for kk, vv in v.items() if kk != "prices"} for k, v in results.items()},
            "categories": categories,
        }, f, indent=2)

    print(f"\n  Saved to {outfile}")
    print(f"  Done (~{len(active) * DELAY_SECONDS / 60:.0f} min)")


if __name__ == "__main__":
    main()
