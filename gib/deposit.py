"""Deposit a loose gib.meme cNFT into the user's binder PDA.

One deposit = one transaction with two instructions:
  1. Bubblegum Transfer  (cNFT wallet → binder PDA)
  2. RegisterCard        (writes the card into the binder's next slot)

GIGAPACK memes get card_id from a lookup table built from real RegisterCard
txs by other users. unk1/unk2 vary per cNFT in observed txs but their meaning
isn't documented; setting to 0 if the program accepts them. unk3 is fixed
per-meme (matches what other registerers used).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import cnft, registercard
from .pdas import binder_pda
from .tx import Instruction


# GIGAPACK meme → (card_id, unk3) — extracted from real RegisterCard txs.
# Add new entries as the GIGAPACK collection grows.
GIGAPACK_MEME_TABLE: dict[str, tuple[int, int]] = {
    "AFK":      (0,  0x00),
    "BUTTCOIN": (1,  0x00),  # verified from real tx
    "GOBLIN":   (2,  0x00),  # verified from real tx
    "MOBY":     (3,  0x00),
    "OOO":      (4,  0x00),
    "PIGEON":   (5,  0x00),
    "PUNCH":    (6,  0x00),
    "TRIPLET":  (7,  0x00),
    "TROLL":    (8,  0x00),
    "UNC":      (9,  0x01),
}


@dataclass(frozen=True)
class DepositPlan:
    asset_id: str
    meme: str
    card_id: int
    unk3: int
    detail: cnft.CnftDetails


def plan_deposit(creator: str, asset_id: str) -> DepositPlan:
    """Pull DAS data and look up the per-meme registration constants."""
    detail = cnft.fetch_cnft_details(asset_id)
    meme = detail.name
    if meme not in GIGAPACK_MEME_TABLE:
        raise RuntimeError(
            f"meme {meme!r} not in GIGAPACK_MEME_TABLE — need a real RegisterCard sample "
            f"to learn its card_id/unk3"
        )
    card_id, unk3 = GIGAPACK_MEME_TABLE[meme]
    return DepositPlan(asset_id=asset_id, meme=meme, card_id=card_id, unk3=unk3, detail=detail)


def build_deposit_instructions(
    creator: str,
    plan: DepositPlan,
    hgtiju_pda: str,
    new_slot_index: int,
) -> list[Instruction]:
    """The two ixs that move + register one cNFT.

    `hgtiju_pda` is the per-user GIGAPACK-program state account that gib.meme
    expects at RegisterCard's account[2]. Discover via
    `discover.find_recent_hgtiju_pda(creator)`.
    `new_slot_index` must equal the binder's live_spaces BEFORE this deposit.
    For a batch of N deposits, pass live_spaces, live_spaces+1, ... in order."""
    binder, _ = binder_pda(creator)

    transfer_ix = cnft.build_bubblegum_transfer(plan.detail, new_leaf_owner=binder)

    register_ix = registercard.build_register_card(
        creator=creator,
        name=plan.detail.name,
        symbol=plan.detail.name,
        arweave_uri_hash=plan.detail.arweave_uri_hash,
        is_gigapack=True,
        card_id=plan.card_id,
        new_slot_index=new_slot_index,
        hgtiju_pda=hgtiju_pda,
        unknown2=0,
        unknown3=plan.unk3,
    )

    return [transfer_ix, register_ix]
