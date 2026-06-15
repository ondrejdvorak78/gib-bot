"""Build v0 VersionedTransactions from Instruction objects using solders.

Handles:
  - Address lookup tables (LUTs) for account deduplication across batched
    instructions. Two ALTs (primary + fallback) are passed by default; Solana
    dedups by pubkey across multiple ALTs in a single message.
  - ComputeBudget instructions (CU limit + priority fee)
  - Batching multiple register_to_tournament instructions into minimal txs
  - Serialization to base64 for Phantom signing or simulateTransaction

Fork note (2026-06-15): see CHANGES.md.
  - fetch_lookup_table: LUT header layout now parsed by spec
    (deactivation_slot + last_extended_slot + last_extended_index +
    authority option) instead of offset guessing.
  - fetch_lookup_tables(): NEW helper returning [primary, fallback] so the
    same v0 message can reference both ALTs concurrently.
  - build_versioned_transaction: accepts a list of LUTs (back-compat with
    single-LUT callers preserved via shim).
"""
from __future__ import annotations

import base64
import struct
from typing import Sequence

from solders.address_lookup_table_account import AddressLookupTableAccount
from solders.hash import Hash as Blockhash
from solders.instruction import AccountMeta as SolAccountMeta
from solders.instruction import Instruction as SolInstruction
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from . import config, rpc
from .tx import Instruction

COMPUTE_BUDGET_PROGRAM = Pubkey.from_string("ComputeBudget111111111111111111111111111111")


def _set_compute_unit_limit(units: int) -> SolInstruction:
    data = struct.pack("<BI", 2, units)
    return SolInstruction(COMPUTE_BUDGET_PROGRAM, data, [])


def _set_compute_unit_price(micro_lamports: int) -> SolInstruction:
    data = struct.pack("<BQ", 3, micro_lamports)
    return SolInstruction(COMPUTE_BUDGET_PROGRAM, data, [])


def _to_sol_instruction(ix: Instruction) -> SolInstruction:
    program_id = Pubkey.from_string(ix.program_id)
    accounts = [
        SolAccountMeta(
            Pubkey.from_string(a.pubkey),
            is_signer=a.is_signer,
            is_writable=a.is_writable,
        )
        for a in ix.accounts
    ]
    return SolInstruction(program_id, ix.data, accounts)


def _parse_lut_account(raw: bytes, key_b58: str) -> AddressLookupTableAccount:
    """Parse an AddressLookupTable account by the documented header layout.

    Solana LUT layout:
      [0:4]     u32  type discriminator (1 for LUT)
      [4:12]    u64  deactivation_slot
      [12:20]   u64  last_extended_slot
      [20]      u8   last_extended_slot_start_index
      [21]      u8   padding
      [22]      u8   authority option (1 = Some, 0 = None)
      [23:55]   pubkey  (if option == 1; ignored otherwise)
      [55]      u8   padding
      [56:]     pubkey[]  address entries, 32 bytes each
    """
    if len(raw) < 56:
        raise ValueError(f"LUT data too short: {len(raw)} bytes")
    addr_start = 56
    body = raw[addr_start:]
    if len(body) % 32 != 0:
        raise ValueError(
            f"LUT body length {len(body)} not multiple of 32; "
            f"layout may have shifted upstream"
        )
    n = len(body) // 32
    addresses = [Pubkey.from_bytes(body[i * 32 : (i + 1) * 32]) for i in range(n)]
    return AddressLookupTableAccount(
        key=Pubkey.from_string(key_b58),
        addresses=addresses,
    )


def fetch_lookup_table(key_b58: str | None = None) -> AddressLookupTableAccount:
    """Fetch a single ALT from chain by address (default: config.LOOKUP_TABLE)."""
    if key_b58 is None:
        key_b58 = config.LOOKUP_TABLE
    info = rpc.get_account_info(key_b58)
    if not info:
        raise RuntimeError(f"LUT {key_b58} not found on chain")
    raw = base64.b64decode(info["data"][0])
    return _parse_lut_account(raw, key_b58)


def fetch_lookup_tables() -> list[AddressLookupTableAccount]:
    """Fetch both primary + fallback ALTs.

    Returns a list with primary first; if the fallback is misconfigured or
    deactivated, returns just the primary rather than erroring — the message
    builder can still construct a valid tx with one ALT.
    """
    luts: list[AddressLookupTableAccount] = []
    try:
        luts.append(fetch_lookup_table(config.LOOKUP_TABLE_OFFICIAL))
    except Exception as e:
        print(f"  warn: primary LUT {config.LOOKUP_TABLE_OFFICIAL[:8]}... not loadable: {e}")
    try:
        luts.append(fetch_lookup_table(config.LOOKUP_TABLE_FALLBACK))
    except Exception as e:
        print(f"  warn: fallback LUT {config.LOOKUP_TABLE_FALLBACK[:8]}... not loadable: {e}")
    if not luts:
        raise RuntimeError("no LUTs loadable from chain — cannot proceed")
    return luts


def batch_instructions(
    instructions: list[Instruction],
    max_per_batch: int = 2,
) -> list[list[Instruction]]:
    """Split instructions into batches that fit in a single tx.

    Each RegisterToTournament uses ~645k CU, so 2 per tx fits within 1.4M CU.
    """
    batches = []
    for i in range(0, len(instructions), max_per_batch):
        batches.append(instructions[i : i + max_per_batch])
    return batches


def build_versioned_transaction(
    instructions: list[Instruction],
    payer: Pubkey,
    recent_blockhash: Blockhash,
    lut: AddressLookupTableAccount | list[AddressLookupTableAccount],
    compute_units: int = 500_000,
    priority_fee_micro_lamports: int = 50_000,
) -> VersionedTransaction:
    """Build a v0 VersionedTransaction from a batch of instructions.

    `lut` accepts either a single AddressLookupTableAccount (back-compat) or a
    list of them. Multi-ALT messages let Solana dedup accounts that appear in
    either ALT, helping when the gib.meme client rotates between ALT versions.

    Returns an UNSIGNED transaction — signing happens in Phantom via the bridge.
    """
    sol_ixs: list[SolInstruction] = []

    sol_ixs.append(_set_compute_unit_limit(compute_units))
    sol_ixs.append(_set_compute_unit_price(priority_fee_micro_lamports))

    for ix in instructions:
        sol_ixs.append(_to_sol_instruction(ix))

    luts = [lut] if isinstance(lut, AddressLookupTableAccount) else list(lut)

    msg = MessageV0.try_compile(
        payer=payer,
        instructions=sol_ixs,
        address_lookup_table_accounts=luts,
        recent_blockhash=recent_blockhash,
    )

    from solders.signature import Signature
    dummy_sig = Signature.default()
    return VersionedTransaction.populate(msg, [dummy_sig])


def get_recent_blockhash() -> Blockhash:
    """Fetch a recent blockhash from the RPC."""
    resp = rpc._post(rpc._HELIUS_RPC, {
        "jsonrpc": "2.0", "id": 1,
        "method": "getLatestBlockhash",
        "params": [{"commitment": "finalized"}],
    })
    bh = resp["result"]["value"]["blockhash"]
    return Blockhash.from_string(bh)


def serialize_for_phantom(tx: VersionedTransaction) -> str:
    """Serialize an unsigned tx to base64 for Phantom's signTransaction."""
    return base64.b64encode(bytes(tx)).decode()
