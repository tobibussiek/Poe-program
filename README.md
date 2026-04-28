# PoE Trade Tools

Two scripts that query the official Path of Exile trade API to find profitable gem gambling and corruption opportunities.

## Setup

```
pip install requests
cp .env.example .env
```

Edit `.env` and paste your `POESESSID` (find it at pathofexile.com → F12 → Application → Cookies).

## Scripts

### Divination Card Checker

Calculates the expected value of turning in divination card sets by pricing every possible gem outcome.

```
python poe_price_checker.py volatile    # Volatile Power (49 vaal gems, ~12 min)
python poe_price_checker.py wilted      # The Wilted Rose (27 aura gems, ~7 min)
python poe_price_checker.py mercy       # Gemcutter's Mercy (3 gems, ~45 sec)
python poe_price_checker.py bitter      # The Bitter Blossom (34 chaos gems, ~8 min)
python poe_price_checker.py all         # Everything (~28 min)
```

### Gem Corruption Checker

Checks whether buying a gem, leveling it, and hitting it with a Lapidary Lens is profitable. Looks up buy price (uncorrupted level 1) and all three corruption outcomes.

```
python gem_corruption_checker.py multi      # Greater Multistrike
python gem_corruption_checker.py eclipse    # Eclipse
python gem_corruption_checker.py comp       # Companionship
python gem_corruption_checker.py echo       # Greater Spell Echo
python gem_corruption_checker.py enlighten  # Awakened Enlighten
python gem_corruption_checker.py empower    # Awakened Empower
python gem_corruption_checker.py enhance    # Awakened Enhance
python gem_corruption_checker.py all        # Everything (~5 min)
```

## Config

Both scripts have config values at the top of the file. Update `DIVINE_RATE` as the exchange rate shifts, and adjust card/gem costs as prices change through the league.

## Rate Limiting

Both scripts default to 10-15 seconds between searches. This is well within GGG's acceptable use — community tools like Awakened PoE Trade hit the same API much harder. Don't set the delay below 5 seconds.
