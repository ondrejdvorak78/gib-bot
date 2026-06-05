"""Construct register_to_tournament instructions for the gib.meme Anchor program.

This module is deliberately dependency-free: it produces plain dataclasses
describing the instruction bytes and account metas. A higher layer (which
*does* depend on solders) wraps these into signed transactions and broadcasts
them. Keeping this split means the test suite for PDA + instruction encoding
stays fast and offline.

Instruction layout (verified against tx 2BhPio... on mainnet):

    disc      : 8 bytes  = sha256("global:register_to_tournament")[:8]
                           = 19d84691f01e600b
    index     : u16 LE   = deck slot in this tournament (0, 1, 2, …)
    cards_len : u32 LE   = len(cards), borsh Vec length prefix
    cards     : u16 LE * cards_len
                           = binder slot indices, one per card in the deck

Account order on the on-chain struct:

    [0] binder             PDA(["binder", creator, board])            writable
    [1] user_track         PDA(["user_track", creator, store])        writable
    [2] tournament         PDA(["tournament", board, u32_le(index)])  writable
    [3] board              fixed constant                             writable
    [4] creator            wallet                                     signer+writable
    [5] system_program     11111111111111111111111111111111           readonly
    [6] notification_track PDA(["notification_track", board])         readonly
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Sequence

from . import config, pdas


@dataclass(frozen=True)
class AccountMeta:
    pubkey: str
    is_signer: bool
    is_writable: bool


@dataclass(frozen=True)
class Instruction:
    program_id: str
    accounts: tuple[AccountMeta, ...]
    data: bytes


def encode_register_to_tournament_data(deck_index: int, cards: Sequence[int]) -> bytes:
    """Serialize the borsh args for register_to_tournament.

    Args:
        deck_index: Which deck slot in the tournament (0-based, unique per caller).
        cards: Binder slot indices for the cards in the deck. Length must match
               the tournament's cardsPerDeck rule (3 for gib.meme mainline).
    """
    if not (0 <= deck_index <= 0xFFFF):
        raise ValueError(f"deck_index {deck_index} out of u16 range")
    for c in cards:
        if not (0 <= c <= 0xFFFF):
            raise ValueError(f"card slot {c} out of u16 range")
    if len(cards) != config.CARDS_PER_DECK:
        raise ValueError(
            f"cards_per_deck mismatch: got {len(cards)}, expected {config.CARDS_PER_DECK}"
        )

    buf = bytearray(config.REGISTER_TO_TOURNAMENT_DISC)
    buf += struct.pack("<H", deck_index)
    buf += struct.pack("<I", len(cards))
    for c in cards:
        buf += struct.pack("<H", c)
    return bytes(buf)


def build_register_to_tournament(
    creator: str,
    tournament_index: int,
    deck_index: int,
    cards: Sequence[int],
) -> Instruction:
    """Build a single register_to_tournament instruction.

    Returns an Instruction ready to be wrapped into a v0 Transaction by a
    higher-level module (which handles solders, the lookup table, signing,
    and broadcast).
    """
    binder_addr, _      = pdas.binder_pda(creator)
    user_track_addr, _  = pdas.user_track_pda(creator)
    tournament_addr, _  = pdas.tournament_pda(tournament_index)
    notification_addr, _ = pdas.notification_track_pda()

    accounts = (
        AccountMeta(binder_addr,              is_signer=False, is_writable=True),
        AccountMeta(user_track_addr,          is_signer=False, is_writable=True),
        AccountMeta(tournament_addr,          is_signer=False, is_writable=True),
        AccountMeta(config.BOARD,             is_signer=False, is_writable=True),
        AccountMeta(creator,                  is_signer=True,  is_writable=True),
        AccountMeta(config.SYSTEM_PROGRAM,    is_signer=False, is_writable=False),
        AccountMeta(notification_addr,        is_signer=False, is_writable=False),
    )

    return Instruction(
        program_id=config.PROGRAM_ID,
        accounts=accounts,
        data=encode_register_to_tournament_data(deck_index, cards),
    )
