"""Constants for the gib.meme on-chain game.

All values extracted from https://gib.meme bundle (js/app.c2e85beb.js +
services/anchor/gibmeme.js chunk) and verified against real
register_to_tournament transactions on mainnet.

Fork note (2026-06-15): LOOKUP_TABLE updated; LOOKUP_TABLE_FALLBACK added. See
CHANGES.md.
"""

# Anchor program that owns all gib.meme state.
PROGRAM_ID = "4zAxB3Q6VVV8msirodwkjCfaeZumKitkcvR7pUveSqSR"

# Singleton accounts from app_info.gib.* (production config).
BOARD           = "BYYdh3UjeKF1Gfjb4vy2JJhjTUoQxKZ62mP9z5YA9Aou"
STORE           = "HnXcGEL6KBqivrKJHSVEj26dkBoENVVXZRibHwh4RmPY"
MASTER          = "CJJzD3cqeUEXkWB7fZ4mjKL2dFfRWwVc8dpqJ7qnu7cN"
UNIVERSE        = "66euP1cG8DAboeb87fzea3EPYZupxosc57QLKPwetPiB"
GAME_COLLECTION = "9ZKbQ7FEzWqapM2TWzw4W77u3RCpuQo5kh9WgkZ7sara"
POOL_CREATOR    = "9iygDei1FbZAwCS6xjypXhpWAECSyiEP3TukeNpBGvDw"
MASTER_MANAGER  = "5rA7d472AZBm43xJGwzcEGGRb41LPy84ARyzjCA1wBVB"

BOARD_SLOT   = 333
MASTER_SLOT  = 999
STORE_SLOT   = 0

# Address lookup tables used by the official gib.meme client. Two ALTs are
# valid concurrently and share 15/17 entries; they differ at indices 9-10.
# Empirical scan (2026-06-15) of the last 100 register_to_tournament txs on
# tournament 86 shows 97/100 using LOOKUP_TABLE_OFFICIAL, 3/100 omitting both.
# We pass BOTH in the v0 message; Solana dedups by pubkey across multiple ALTs.
LOOKUP_TABLE_OFFICIAL  = "7weLQ3qggTHc71etH4MYgSEFtRfTgMNvv9gzy2ha6bSL"
LOOKUP_TABLE_FALLBACK  = "EkBA4F2LaxQvHWL4YhAtJa4ps75Q6We7LWUF7PtHxaLX"
# Back-compat: code that pre-existed in the fork reads LOOKUP_TABLE — kept as
# the primary so a single-ALT path still works.
LOOKUP_TABLE = LOOKUP_TABLE_OFFICIAL

# Well-known system program.
SYSTEM_PROGRAM = "11111111111111111111111111111111"

# Secondary program called at the tail of each official submit tx in the OLD
# gib.meme client. Cosmetic activity-log call for the 3.land UI feeds; included
# to mirror the official client exactly. Not required for the submission itself
# to succeed.
# The CURRENT gib.meme official client (as of 2026-06-15) does NOT emit this
# ix — empirical scan shows 97/100 recent register_to_tournament txs omit it.
# We default to ENABLE_ACTIVITY_LOG = False to match the current official wire
# shape; flip True via env var only if you want compatibility with downstream
# systems that key off this ix.
import os as _os
ACTIVITY_LOG_PROGRAM = "L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95"
ENABLE_ACTIVITY_LOG  = _os.environ.get("GIB_BOT_ENABLE_ACTIVITY_LOG", "0") == "1"

# Anchor instruction discriminator for register_to_tournament.
# sha256("global:register_to_tournament")[:8]
REGISTER_TO_TOURNAMENT_DISC = bytes.fromhex("19d84691f01e600b")

# Cards per deck — bundle default is 5 but gib.meme has run with 3 for months.
# The actual value is also readable off the tournament account's TournamentRules.
CARDS_PER_DECK = 3

# Tournament duration hint (hours). Actual duration is read from the tournament
# account, this is just for forecasting horizon defaults.
DEFAULT_TOURNAMENT_DURATION_HOURS = 72
