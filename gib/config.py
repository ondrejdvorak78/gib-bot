"""Constants for the gib.meme on-chain game.

All values extracted from https://gib.meme bundle (js/app.c2e85beb.js +
services/anchor/gibmeme.js chunk) and verified against a real
register_to_tournament transaction on mainnet
(sig 2BhPioKThCtYuiMrNxKLuuLk4tUcUS8cRHyR7gNARK1GNGWeKix3SuRJCDwGU6GCiMu52Aiv7s7qZtdSmdPRP3K1).
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

# Address lookup table used by the official client. Deduplicates the
# fixed accounts (board, system program, etc.) across batched instructions.
LOOKUP_TABLE = "EkBA4F2LaxQvHWL4YhAtJa4ps75Q6We7LWUF7PtHxaLX"

# Well-known system program.
SYSTEM_PROGRAM = "11111111111111111111111111111111"

# Secondary program called at the tail of each official submit tx. Cosmetic
# activity-log call for the 3.land UI feeds; included to mirror the official
# client exactly. Not required for the submission itself to succeed.
ACTIVITY_LOG_PROGRAM = "L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95"

# Anchor instruction discriminator for register_to_tournament.
# sha256("global:register_to_tournament")[:8]
REGISTER_TO_TOURNAMENT_DISC = bytes.fromhex("19d84691f01e600b")

# Cards per deck — bundle default is 5 but gib.meme has run with 3 for months.
# The actual value is also readable off the tournament account's TournamentRules.
CARDS_PER_DECK = 3

# Tournament duration hint (hours). Actual duration is read from the tournament
# account, this is just for forecasting horizon defaults.
DEFAULT_TOURNAMENT_DURATION_HOURS = 72
