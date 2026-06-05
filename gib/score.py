"""Card scoring — sort by power, descending.

Each card's score is its raw power value from the gib.meme stats API.
build_decks consumes the sorted list and greedily fills decks of 3 cards.
"""
from __future__ import annotations

from dataclasses import dataclass

from .binder import Card


@dataclass(frozen=True)
class ScoredCard:
    slot: int
    meme: str
    score: float
    power: float
    change_7d: float
    change_24h: float


def score_cards(cards: list[Card], include_no_stats: bool = True) -> list[ScoredCard]:
    """Score free cards by raw power, sorted descending.

    With include_no_stats=True (default) cards missing API stats are kept with
    score=0, so every available card can be used as deck filler.
    """
    if include_no_stats:
        eligible = [c for c in cards if c.is_free]
    else:
        eligible = [c for c in cards if c.is_free and c.power is not None]
    if not eligible:
        return []

    scored = [
        ScoredCard(
            slot=c.slot,
            meme=c.meme or f"???_{c.slot}",
            score=c.power or 0.0,
            power=c.power or 0.0,
            change_7d=c.change_7d or 0.0,
            change_24h=c.change_24h or 0.0,
        )
        for c in eligible
    ]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored
