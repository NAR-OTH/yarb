"""Game configuration: project types, shop items, and auction items."""
import random

# Income tick: how often projects pay out (in seconds)
TICK_SECONDS = 5

# ---- Project upgrade tuning (moderate / light) ----
MAX_PROJECT_LEVEL = 5
# Each level adds 20% of the BASE income. So L0=100%, L5=200%.
LEVEL_INCOME_PCT_PER_STEP = 20
# Cost factor: upgrading from level L to L+1 costs base_cost * 0.5 * (L+1).
# So: L0->1 = 0.5x base, L1->2 = 1.0x, L2->3 = 1.5x, L3->4 = 2.0x, L4->5 = 2.5x
LEVEL_COST_FACTOR = 0.5


def level_income_multiplier(level: int) -> float:
    """Return income multiplier for a given level (1.0 at L0)."""
    return 1.0 + (LEVEL_INCOME_PCT_PER_STEP / 100.0) * level


def level_upgrade_cost(base_cost: int, current_level: int) -> int:
    """Cost to upgrade ONE project from current_level -> current_level+1."""
    return int(base_cost * LEVEL_COST_FACTOR * (current_level + 1))

# Project types: cost, income per tick, emoji, label.
# Players may build multiple of any type (no cap).
PROJECTS = {
    "cafe": {
        "name": "مقهى",
        "emoji": "☕",
        "cost": 500,
        "income_per_tick": 25,
    },
    "kiosk": {
        "name": "كشك",
        "emoji": "🏪",
        "cost": 1000,
        "income_per_tick": 50,
    },
    "restaurant": {
        "name": "مطعم",
        "emoji": "🍽️",
        "cost": 3000,
        "income_per_tick": 150,
    },
    "supermarket": {
        "name": "سوبرماركت",
        "emoji": "🛒",
        "cost": 5000,
        "income_per_tick": 250,
    },
    "factory": {
        "name": "مصنع",
        "emoji": "🏭",
        "cost": 8000,
        "income_per_tick": 400,
    },
    "hotel": {
        "name": "فندق",
        "emoji": "🏨",
        "cost": 15000,
        "income_per_tick": 750,
    },
    "oilwell": {
        "name": "بئر نفط",
        "emoji": "🛢️",
        "cost": 30000,
        "income_per_tick": 1500,
    },
    "bank": {
        "name": "بنك خاص",
        "emoji": "🏦",
        "cost": 60000,
        "income_per_tick": 3000,
    },
}

# Military shop items (deposited into team vault).
# Each item adds `qty` units to the matching vault_field.
SHOP_ITEMS = {
    "soldier": {
        "name": "جندي",
        "emoji": "💂",
        "cost": 100,
        "vault_field": "soldiers",
        "qty": 1,
    },
    "elite": {
        "name": "جندي نخبة (×6)",
        "emoji": "🪖",
        "cost": 550,
        "vault_field": "soldiers",
        "qty": 6,
    },
    "battalion_pack": {
        "name": "كتيبة كاملة (×60)",
        "emoji": "🎖️",
        "cost": 5000,
        "vault_field": "soldiers",
        "qty": 60,
    },
    "missile": {
        "name": "صاروخ",
        "emoji": "🚀",
        "cost": 500,
        "vault_field": "missiles",
        "qty": 1,
    },
    "supermissile": {
        "name": "صاروخ متطور (×5)",
        "emoji": "💥",
        "cost": 2200,
        "vault_field": "missiles",
        "qty": 5,
    },
    "antimissile": {
        "name": "مضاد صواريخ",
        "emoji": "🛡️",
        "cost": 400,
        "vault_field": "antimissiles",
        "qty": 1,
    },
    "shield": {
        "name": "درع شامل (×10)",
        "emoji": "🏰",
        "cost": 3500,
        "vault_field": "antimissiles",
        "qty": 10,
    },
}

# Three auction box types
AUCTION_BOXES = [
    {"key": "treasure",  "name": "💰 صندوق الكنز",          "desc": "يحتوي على مبلغ مالي عشوائي"},
    {"key": "resources", "name": "📦 صندوق موارد عشوائية", "desc": "أسلحة، جنود، أو سلاح نادر غير معروض في المتجر"},
    {"key": "mystery",   "name": "🎁 صندوق عشوائي مجهول",  "desc": "لا أحد يعرف ما بداخله — مال أو موارد!"},
]


def random_auction_box() -> dict:
    return random.choice(AUCTION_BOXES)


# ---------- Reward generation ----------

def gen_treasure_reward() -> dict:
    """Random money amount: 1,000 to 1,000,000 coins.
    Weighted heavily toward small amounts; large amounts very rare."""
    amounts = [
        1_000, 2_000, 3_500, 5_000, 7_500,
        10_000, 20_000, 50_000,
        100_000, 250_000, 500_000, 1_000_000,
    ]
    weights = [
        22, 20, 17, 14, 11,
        7, 4, 2.5,
        1.3, 0.7, 0.3, 0.1,
    ]
    coins = random.choices(amounts, weights=weights, k=1)[0]
    return {
        "type": "coins",
        "qty": coins,
        "label": f"💰 {coins:,} عملة ذهبية",
    }


def gen_resources_reward() -> dict:
    """Random weapons or soldiers, possibly a nuke (very rare).
    Luck is tuned LOW so rare items don't drop frequently."""
    pool = [
        {"kind": "soldier",     "qty": 30, "label": "💂 30 جندي نخبة"},
        {"kind": "soldier",     "qty": 50, "label": "💂 50 جندي نخبة"},
        {"kind": "missile",     "qty": 5,  "label": "🚀 5 صواريخ ثقيلة"},
        {"kind": "missile",     "qty": 10, "label": "🚀 10 صواريخ ثقيلة"},
        {"kind": "antimissile", "qty": 5,  "label": "🛡️ 5 مضادات صواريخ"},
        {"kind": "antimissile", "qty": 10, "label": "🛡️ 10 مضادات صواريخ"},
        {"kind": "nuke",        "qty": 1,  "label": "☢️ <b>قنبلة نووية!</b> (+50 صاروخ + 30 مضاد دفعة واحدة)"},
        {"kind": "battalion",   "qty": 1,  "label": "🎖️ <b>كتيبة كاملة!</b> (+100 جندي + 5 صواريخ)"},
        {"kind": "stealth",     "qty": 1,  "label": "🥷 <b>وحدة تخفّي نادرة</b> (+30 جندي + 10 صواريخ + 10 مضادات)"},
    ]
    # Common: ~97% combined. Rare: ~3% combined.
    weights = [20, 17, 18, 14, 16, 12, 1, 1, 1]
    choice = random.choices(pool, weights=weights, k=1)[0]
    return {
        "type": "resource_pack",
        "label": choice["label"],
        "kind": choice["kind"],
        "qty": choice["qty"],
    }


def gen_mystery_reward() -> dict:
    """Either treasure or resources — surprise!"""
    if random.random() < 0.5:
        return gen_treasure_reward()
    return gen_resources_reward()


def generate_reward(box_key: str) -> dict:
    if box_key == "treasure":
        return gen_treasure_reward()
    if box_key == "resources":
        return gen_resources_reward()
    return gen_mystery_reward()


# ---------- Apply rewards to a winner ----------

def apply_reward_grants(reward: dict) -> list:
    """Convert special kinds (nuke, battalion, stealth) into a list of (vault_field, qty) grants.
       For simple kinds, returns a single grant. For coin reward, returns []."""
    if reward["type"] == "coins":
        return []
    kind = reward["kind"]
    qty = reward["qty"]
    if kind == "soldier":
        return [("soldiers", qty)]
    if kind == "missile":
        return [("missiles", qty)]
    if kind == "antimissile":
        return [("antimissiles", qty)]
    if kind == "nuke":
        return [("missiles", 50), ("antimissiles", 30)]
    if kind == "battalion":
        return [("soldiers", 100), ("missiles", 5)]
    if kind == "stealth":
        return [("soldiers", 30), ("missiles", 10), ("antimissiles", 10)]
    return []
