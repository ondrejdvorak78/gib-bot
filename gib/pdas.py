"""Solana Program Derived Address derivation for the gib.meme Anchor program.

Pure-Python implementation — no solders/nacl dependency so this file works
anywhere. All four derivations have been verified against a real
register_to_tournament transaction (see tests/test_pdas.py).

Seeds are taken from the JS bundle's services/anchor/gibmeme.js:

    binderPDA({creator, board}):              ["binder", creator, board]
    userTrackPDA({creator, store}):           ["user_track", creator, store]
    notificationTrackPDA({board}):            ["notification_track", board]
    tournamentPDA({board, index}):            ["tournament", board, u32_le(index)]

Gotcha: userTrackPDA is seeded by `store`, NOT `board`. The JS service wrapper
sometimes passes {board, creator} by name but the destructure ignores `board`
and falls back to app_info.gib.store for the second seed. This is easy to get
wrong — the tests exist to make sure we don't.
"""
from __future__ import annotations

import hashlib
from typing import Sequence

from . import config

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + _B58.index(c)
    leading = len(s) - len(s.lstrip("1"))
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * leading + body


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\x00"))) + out


# --- ed25519 on-curve check -------------------------------------------------
# A PDA is valid only if its 32-byte hash is *off* the Ed25519 curve, i.e. it
# cannot be decompressed to a valid curve point. We implement the decompression
# directly so this module has zero dependencies.

_P = 2**255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P


def _is_on_curve(pk: bytes) -> bool:
    if len(pk) != 32:
        return False
    y = int.from_bytes(pk, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    yy = (y * y) % _P
    num = (yy - 1) % _P
    den = (_D * yy + 1) % _P
    xx = (num * pow(den, _P - 2, _P)) % _P
    # p ≡ 5 (mod 8) sqrt shortcut
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * pow(2, (_P - 1) // 4, _P)) % _P
    if (x * x - xx) % _P != 0:
        return False
    # sign-of-x matches high bit of last byte; not actually needed to decide
    # on-curveness but we run it so a future caller can reuse this helper.
    sign = (pk[31] >> 7) & 1
    if (x & 1) != sign:
        x = _P - x
    return True


_MARKER = b"ProgramDerivedAddress"


def find_program_address(
    seeds: Sequence[bytes], program_id: str
) -> tuple[str, int]:
    """Return (pda_b58, bump) matching the on-chain findProgramAddress."""
    pid = b58decode(program_id)
    for bump in range(255, -1, -1):
        h = hashlib.sha256()
        for s in seeds:
            h.update(s)
        h.update(bytes([bump]))
        h.update(pid)
        h.update(_MARKER)
        cand = h.digest()
        if not _is_on_curve(cand):
            return b58encode(cand), bump
    raise RuntimeError("no valid PDA exists for these seeds (astronomically unlikely)")


# --- gib.meme-specific derivations -----------------------------------------

def binder_pda(creator: str, board: str = config.BOARD) -> tuple[str, int]:
    return find_program_address(
        [b"binder", b58decode(creator), b58decode(board)],
        config.PROGRAM_ID,
    )


def user_track_pda(creator: str, store: str = config.STORE) -> tuple[str, int]:
    return find_program_address(
        [b"user_track", b58decode(creator), b58decode(store)],
        config.PROGRAM_ID,
    )


def notification_track_pda(board: str = config.BOARD) -> tuple[str, int]:
    return find_program_address(
        [b"notification_track", b58decode(board)],
        config.PROGRAM_ID,
    )


def tournament_pda(index: int, board: str = config.BOARD) -> tuple[str, int]:
    return find_program_address(
        [b"tournament", b58decode(board), index.to_bytes(4, "little")],
        config.PROGRAM_ID,
    )
