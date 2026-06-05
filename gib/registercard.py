"""RegisterCard ix encoder for the gib.meme program (4zAxB3Q…).

Called after a Bubblegum transfer moves a cNFT into the binder PDA; this ix
writes the card's metadata into the next available binder slot.

The on-chain layout is reverse-engineered from 16 real RegisterCard txs.
Two collection variants share most of the data; only a few bytes vary
per-card. Unknown bytes that we couldn't tie to a derivation are set to 0
(simulate will reject if the program actually validates them).

Layout (variable-length around name/symbol):

  disc (8)               = 21199a6f9b1f2d24
  unknown1 (1)           = per-card, observed range 0x00–0xff (set to 0)
  collection_flag (1)    = 0x04 (Genesis) or 0x00 (GIGAPACK)
  pad1 (4)               = 01 00 00 00
  pad2 (1)               = 03
  name_len (u32 LE)
  name (N)
  fee_bps (u16 LE)       = 0000
  symbol_len (u32 LE)
  symbol (M)
  uri_len (u32 LE)       = 2b 00 00 00 (always 43)
  uri (43)               = arweave hash from content.json_uri
  vec_len (u32 LE)       = 04 00 00 00
  hash_a (32)            = collection-dependent constant
  hash_b (32)            = shared constant
  block_c (35)           = constant
  hash_d (32)            = collection-dependent constant
  block_e (32)           = constant share/seller hash
  unknown2 (1)           = per-card, observed range, set to 0
  unknown3 (1)           = collection_flag-correlated (0 GIGAPACK, 1/2 Genesis)
  pad3 (4)               = 00 00 00 02
  card_id (1)            = meme position in stats list, fits in u8
  pad4 (4)               = 00 00 00 00
"""
from __future__ import annotations

import struct
from typing import Sequence

from . import config, pdas
from .tx import AccountMeta, Instruction


REGISTER_CARD_DISC = bytes.fromhex("21199a6f9b1f2d24")

# Collection-level constants extracted from 16 real RegisterCard txs and
# verified by parsing TSLAX/AAPLX (Genesis) and MOBY/OOO/PUNCH (GIGAPACK).
HASH_B_SHARED = bytes.fromhex("6537c29b0f1e8ff73c08f142eb838b8f5c888661b0a4ae6def3f0a3d66b8f4e5")
BLOCK_C       = bytes.fromhex("100002806f18bc254102b3663688ca7c8e231fd7e7aa920d6d040ef4e4b860c5115b00")
BLOCK_E       = bytes.fromhex("00b20201005f32fdd58d2f0b7a9438959189049ee2f4422d294113e4300ad40867f70e04")

GENESIS_HASH_A  = bytes.fromhex("72ac358346f4843f93e2e7d1fce5ceec851d3cfbeeff6e57c29e1a50cf993e17")
GENESIS_HASH_D  = bytes.fromhex("4cb0c7e663cbbd61cdfc379de215d7efab1bbb8393481fce861b4a976b6f4ddc")  # last byte differs from prior typo
GIGAPACK_HASH_A = bytes.fromhex("819e647d54d0e4992b5f4bb35580a7d5012693df534c6c9b7e33bd19ee3d517a")
GIGAPACK_HASH_D = bytes.fromhex("0c6f004d5ffc150360dc6d8480f6fddde4225a1caecc67d17f11d1a4321180b2")

assert len(BLOCK_C) == 35
assert len(BLOCK_E) == 36
assert len(HASH_B_SHARED) == 32
assert len(GENESIS_HASH_A) == 32 and len(GENESIS_HASH_D) == 32
assert len(GIGAPACK_HASH_A) == 32 and len(GIGAPACK_HASH_D) == 32


def _encode_string(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


def encode_register_card_data(
    *,
    name: str,
    symbol: str,
    arweave_uri_hash: str,
    is_gigapack: bool,
    card_id: int,
    new_slot_index: int,
    unknown2: int = 0,
    unknown3: int | None = None,
) -> bytes:
    """Serialize RegisterCard args.

    `card_id`         meme's stable position (0–254). See GIGAPACK_MEME_TABLE.
    `is_gigapack`     selects which constant collection hashes to embed.
    `new_slot_index`  binder's `live_spaces` BEFORE this deposit (= the new
                      card's slot). Encoded as u16 LE at offsets 8–9.
    `unknown2/3`      bytes whose semantics aren't documented; safe to leave
                      at 0 for GIGAPACK (matches on-chain history).
    """
    if not (0 <= card_id <= 0xff):
        raise ValueError(f"card_id {card_id} doesn't fit u8")
    if not (0 <= new_slot_index <= 0xffff):
        raise ValueError(f"new_slot_index {new_slot_index} doesn't fit u16")
    if len(arweave_uri_hash) != 43:
        raise ValueError(f"uri hash must be exactly 43 chars, got {len(arweave_uri_hash)}")
    if unknown3 is None:
        unknown3 = 0 if is_gigapack else 1

    hash_a = GIGAPACK_HASH_A if is_gigapack else GENESIS_HASH_A
    hash_d = GIGAPACK_HASH_D if is_gigapack else GENESIS_HASH_D

    buf = bytearray()
    buf += REGISTER_CARD_DISC                       # 8
    buf += struct.pack("<H", new_slot_index)        # 2  (was unknown1 + collection_flag)
    buf += bytes.fromhex("01000000")                # 4
    buf += bytes([0x03])                            # 1
    buf += _encode_string(name)                     # 4 + N
    buf += bytes.fromhex("0000")                    # 2
    buf += _encode_string(symbol)                   # 4 + M
    buf += struct.pack("<I", 43) + arweave_uri_hash.encode("ascii")  # 4 + 43
    buf += bytes.fromhex("04000000")                # 4
    buf += hash_a                                   # 32
    buf += HASH_B_SHARED                            # 32
    buf += BLOCK_C                                  # 35
    buf += hash_d                                   # 32
    buf += BLOCK_E                                  # 36
    buf += bytes([unknown2, unknown3])              # 2
    buf += bytes.fromhex("00000002")                # 4
    buf += bytes([card_id])                         # 1
    buf += bytes.fromhex("00000000")                # 4
    return bytes(buf)


def build_register_card(
    *,
    creator: str,
    name: str,
    symbol: str,
    arweave_uri_hash: str,
    is_gigapack: bool,
    card_id: int,
    new_slot_index: int,
    hgtiju_pda: str,
    unknown2: int = 0,
    unknown3: int | None = None,
) -> Instruction:
    """Build a RegisterCard ix.

    `new_slot_index` must equal the binder's `live_spaces` BEFORE this deposit.
    When chaining multiple deposits in one batch, increment by 1 per card.
    `hgtiju_pda` is the per-user state account owned by the GIGAPACK program;
    auto-discover via `discover.find_recent_hgtiju_pda(creator)`."""
    binder_addr, _ = pdas.binder_pda(creator)

    accounts = (
        AccountMeta(binder_addr,          is_signer=False, is_writable=True),
        AccountMeta(config.BOARD,         is_signer=False, is_writable=True),
        AccountMeta(hgtiju_pda,           is_signer=False, is_writable=True),
        AccountMeta(creator,              is_signer=True,  is_writable=True),
        AccountMeta(config.SYSTEM_PROGRAM, is_signer=False, is_writable=False),
    )

    data = encode_register_card_data(
        name=name, symbol=symbol, arweave_uri_hash=arweave_uri_hash,
        is_gigapack=is_gigapack, card_id=card_id,
        new_slot_index=new_slot_index,
        unknown2=unknown2, unknown3=unknown3,
    )
    return Instruction(program_id=config.PROGRAM_ID, accounts=accounts, data=data)
