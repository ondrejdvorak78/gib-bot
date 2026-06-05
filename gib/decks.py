"""Deck construction — pure greedy by score.

Sort cards by score descending, then take the next 3 unique-meme cards as
each deck. Repeat until fewer than 3 cards remain. Strongest cards land in
the lowest-indexed deck, next strongest in the second, and so on.

IMPORTANT: The on-chain program enforces "no duplicate memes in one deck"
(error 6024: TooManyOfTheSameMeme). Every card in a deck must represent a
different memecoin, so the picker skips cards whose meme is already in the
deck under construction.
"""
from __future__ import annotations

from dataclasses import dataclass

from .score import ScoredCard


@dataclass(frozen=True)
class Deck:
    index: int
    cards: tuple[int, int, int]  # binder slot indices
    min_score: float             # weakest card's score
    deck_score: float            # total deck score (sum of card scores)
    label: str                   # human-readable description


def build_decks(
    scored: list[ScoredCard],
    cards_per_deck: int = 3,
    start_index: int = 0,
    exclude_slots: set[int] | None = None,
    include_zero: bool = True,
) -> list[Deck]:
    """Build decks greedily from the strongest cards down.

    With include_zero=True (default), every available card is used regardless
    of score sign — zero-power cards become filler decks (still cheap lottery
    tickets at the cost of one tx). With include_zero=False, only positive-
    score cards are eligible.
    """
    if include_zero:
        eligible = [s for s in scored
                    if exclude_slots is None or s.slot not in exclude_slots]
    else:
        eligible = [s for s in scored
                    if (exclude_slots is None or s.slot not in exclude_slots)
                    and s.score > 0]
    eligible.sort(key=lambda s: s.score, reverse=True)

    if len(eligible) < cards_per_deck:
        return []

    used: set[int] = set()
    decks: list[Deck] = []
    deck_idx = start_index

    while True:
        pick = _pick_unique_meme_deck(eligible, used, cards_per_deck)
        if not pick:
            break
        for s in pick:
            used.add(s.slot)
        slots = tuple(s.slot for s in pick)
        label = " + ".join(s.meme for s in pick)
        total = sum(s.score for s in pick)
        decks.append(Deck(
            index=deck_idx,
            cards=slots,
            min_score=min(s.score for s in pick),
            deck_score=total,
            label=label,
        ))
        deck_idx += 1

    return decks


def _pick_unique_meme_deck(
    pool: list[ScoredCard],
    used: set[int],
    size: int,
) -> list[ScoredCard] | None:
    """Greedily pick `size` cards from pool with all-different memes.

    Takes the highest-scored available card, then the next highest with a
    different meme, etc. Returns None if not enough distinct memes remain.
    """
    pick: list[ScoredCard] = []
    memes_in_deck: set[str] = set()

    for s in pool:
        if s.slot in used:
            continue
        if s.meme in memes_in_deck:
            continue
        pick.append(s)
        memes_in_deck.add(s.meme)
        if len(pick) == size:
            return pick

    return None
