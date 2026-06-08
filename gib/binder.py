"""Read and parse the on-chain binder account, resolve card metadata via DAS,
and join with live stats from the gib.meme backend.

The binder account layout (verified against real on-chain binder accounts):

    Header (65 bytes):
        disc                8   Anchor discriminator
        version             1
        skip                8
        skip                8
        owner              32   creator pubkey
        flag                1
        flag                1
        live_spaces         2   u16 — allocated card slots
        stored_cards        2   u16 — filled card slots
        skip                2

    Cards (152 bytes each × stored_cards):
        available           1   u8  bool
        status              1   u8  bool
        asset_hash         32   cNFT asset ID
        extra_u16           2
        extra_u8            1
        tournament_slots   35   7 × (u8 state + u32 tournament_index)
        traits             40
        random              8
        counter1            4
        counter2            4
        counter3            4
        counter4            4
        big_counter1        8
        flags               8
"""
from __future__ import annotations

import base64
import struct
from dataclasses import dataclass, field

from . import config, pdas, rpc


CARD_SIZE = 152
HEADER_SIZE = 65
MAX_TOURNEY_SLOTS = 7


@dataclass
class TournamentLock:
    state: int
    tournament_index: int


@dataclass
class Card:
    slot: int
    asset_hash: str
    available: bool
    status: bool
    tournament_locks: list[TournamentLock] = field(default_factory=list)
    meme: str | None = None
    # Live stats (populated by join_stats)
    power: float | None = None
    price: float | None = None
    change_24h: float | None = None
    change_7d: float | None = None
    market_cap: float | None = None
    volume_24h: float | None = None
    spl_mint: str | None = None

    @property
    def is_locked_on_marketplace(self) -> bool:
        """Card can't be sold/listed on ME while in an active tournament."""
        return any(t.state for t in self.tournament_locks)

    def is_in_tournament(self, tournament_index: int) -> bool:
        """Check if this card is already registered in a specific tournament.

        The binder stores tournament_index as API_index + 1 (1-based internally),
        so we check both the exact value and +1 to handle the offset.
        """
        return any(
            t.tournament_index in (tournament_index, tournament_index + 1) and t.state != 0
            for t in self.tournament_locks
        )

    @property
    def is_free(self) -> bool:
        """Card is available for tournament submission.

        Cards CAN be entered into multiple tournaments simultaneously (up to 7
        slots tracked in the binder). The 'lock' only prevents marketplace
        actions (selling/listing on ME), NOT new tournament registrations.
        """
        return self.available


def parse_binder_account(data: bytes) -> list[Card]:
    """Parse raw binder account bytes into a list of Card objects."""
    stored_cards = struct.unpack_from("<H", data, 61)[0]
    cards: list[Card] = []

    for slot in range(stored_cards):
        off = HEADER_SIZE + slot * CARD_SIZE
        raw = data[off : off + CARD_SIZE]

        available = bool(raw[0])
        status = bool(raw[1])
        asset_hash = pdas.b58encode(raw[2:34])

        locks = []
        for j in range(MAX_TOURNEY_SLOTS):
            ts_off = 37 + j * 5
            state = raw[ts_off]
            tidx = struct.unpack_from("<I", raw, ts_off + 1)[0]
            if state or tidx:
                locks.append(TournamentLock(state=state, tournament_index=tidx))

        cards.append(Card(
            slot=slot,
            asset_hash=asset_hash,
            available=available,
            status=status,
            tournament_locks=locks,
        ))

    return cards


def fetch_binder(creator: str) -> list[Card]:
    """Fetch the binder account from chain and parse it."""
    binder_addr, _ = pdas.binder_pda(creator)
    info = rpc.get_account_info(binder_addr)
    if not info:
        raise RuntimeError(f"binder account {binder_addr} not found")
    raw = base64.b64decode(info["data"][0])
    return parse_binder_account(raw)


def resolve_meme_names(cards: list[Card]) -> None:
    """Batch-fetch DAS metadata and set card.meme for each card."""
    asset_ids = [c.asset_hash for c in cards if c.available]
    if not asset_ids:
        return
    das_entries = rpc.get_asset_batch(asset_ids)

    hash_to_meme: dict[str, str] = {}
    for entry in das_entries:
        aid = entry.get("id", "")
        for attr in entry.get("content", {}).get("metadata", {}).get("attributes", []):
            if attr.get("trait_type") == "Meme":
                hash_to_meme[aid] = attr["value"]

    for card in cards:
        card.meme = hash_to_meme.get(card.asset_hash)


def join_stats(cards: list[Card]) -> None:
    """Fetch live stats and attach power/market data to each card."""
    stats_list = rpc.get_all_card_stats()

    by_meme: dict[str, tuple[str, dict]] = {}
    for name, mint, stats in stats_list:
        by_meme[name.upper()] = (mint, stats)

    for card in cards:
        if not card.meme:
            continue
        entry = by_meme.get(card.meme.upper())
        if not entry:
            continue
        mint, s = entry
        card.spl_mint = mint
        card.power = s.get("power", 0)
        card.price = s.get("price", 0)
        card.change_24h = s.get("change24h", 0)
        card.change_7d = s.get("change7d", 0)
        card.market_cap = s.get("marketCap", 0)
        card.volume_24h = s.get("volume", 0)


def get_registered_slots(cards: list[Card], tournament_index: int) -> set[int]:
    """Return binder slot indices already registered in the given tournament."""
    return {c.slot for c in cards if c.is_in_tournament(tournament_index)}


def load_full_inventory(creator: str) -> list[Card]:
    """One-shot: fetch binder → resolve memes → join stats."""
    cards = fetch_binder(creator)
    resolve_meme_names(cards)
    join_stats(cards)
    return cards
