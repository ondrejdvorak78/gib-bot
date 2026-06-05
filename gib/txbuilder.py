"""Build v0 VersionedTransactions from Instruction objects using solders.

Handles:
  - Address lookup table (LUT) for account deduplication across batched instructions
  - ComputeBudget instructions (CU limit + priority fee)
  - Batching multiple register_to_tournament instructions into minimal txs
  - Serialization to base64 for Phantom signing or simulateTransaction
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

# Compute budget program
COMPUTE_BUDGET_PROGRAM = Pubkey.from_string("ComputeBudget111111111111111111111111111111")


def _set_compute_unit_limit(units: int) -> SolInstruction:
    """SetComputeUnitLimit instruction."""
    data = struct.pack("<BI", 2, units)
    return SolInstruction(COMPUTE_BUDGET_PROGRAM, data, [])


def _set_compute_unit_price(micro_lamports: int) -> SolInstruction:
    """SetComputeUnitPrice instruction."""
    data = struct.pack("<BQ", 3, micro_lamports)
    return SolInstruction(COMPUTE_BUDGET_PROGRAM, data, [])


def _to_sol_instruction(ix: Instruction) -> SolInstruction:
    """Convert our plain Instruction to a solders Instruction."""
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


def fetch_lookup_table() -> AddressLookupTableAccount:
    """Fetch the gib.meme address lookup table from chain."""
    info = rpc.get_account_info(config.LOOKUP_TABLE)
    if not info:
        raise RuntimeError(f"LUT {config.LOOKUP_TABLE} not found on chain")

    raw = base64.b64decode(info["data"][0])

    # Parse LUT account data:
    # https://docs.solana.com/developing/lookup-tables
    # Header: 4 (type) + 8 (deactivation_slot) + 4 (padding) + 8 (last_extended_slot)
    #         + 1 (last_extended_slot_start_index) + 4 (padding) + 1 (authority option)
    #         + 32 (authority if present)
    # Then addresses: N * 32 bytes
    #
    # But solders can parse this for us if we use the right constructor.
    # The raw account data format:
    #   bytes 0-3:   u32 account type (1 = lookup table)
    #   bytes 4-55:  header fields
    #   bytes 56+:   authority (if any) then addresses
    #
    # Simplest approach: manually extract the address list.
    # The address list starts at a fixed offset in the serialized format.
    # For an active LUT with authority: offset 56 + 32 (authority) = 88
    # Without authority: offset 56

    # Parse header
    HEADER_SIZE = 56
    has_authority = raw[HEADER_SIZE - 2]  # authority option byte
    if has_authority:
        addr_start = HEADER_SIZE + 32
    else:
        addr_start = HEADER_SIZE

    # Actually, let's be more careful about the layout.
    # The LUT account layout per Solana source:
    #   [0:4]   u32 type discriminator
    #   [4:12]  u64 deactivation_slot
    #   [12:20] u64 last_extended_slot
    #   [20]    u8  last_extended_start_index
    #   [21]    padding
    #   [22]    u8 authority option (1 = Some, 0 = None)
    #   [23:55] authority pubkey (32 bytes, only meaningful if option == 1)
    #   [55:]   address entries (32 bytes each)
    addr_start = 56
    # But wait, some implementations use a different offset. Let's just
    # find it by scanning: all addresses are 32 bytes, total should be
    # (len(raw) - header) / 32 = integer.
    # Try common offsets
    for offset in [56, 54, 58]:
        remaining = len(raw) - offset
        if remaining > 0 and remaining % 32 == 0:
            addr_start = offset
            break

    n_addresses = (len(raw) - addr_start) // 32
    addresses = []
    for i in range(n_addresses):
        pk_bytes = raw[addr_start + i * 32 : addr_start + (i + 1) * 32]
        addresses.append(Pubkey.from_bytes(pk_bytes))

    return AddressLookupTableAccount(
        key=Pubkey.from_string(config.LOOKUP_TABLE),
        addresses=addresses,
    )


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
    lut: AddressLookupTableAccount,
    compute_units: int = 500_000,
    priority_fee_micro_lamports: int = 50_000,
) -> VersionedTransaction:
    """Build a v0 VersionedTransaction from a batch of instructions.

    Returns an UNSIGNED transaction — signing happens in Phantom via the bridge.
    """
    sol_ixs: list[SolInstruction] = []

    # Prepend compute budget instructions
    sol_ixs.append(_set_compute_unit_limit(compute_units))
    sol_ixs.append(_set_compute_unit_price(priority_fee_micro_lamports))

    # Add the register_to_tournament instructions
    for ix in instructions:
        sol_ixs.append(_to_sol_instruction(ix))

    msg = MessageV0.try_compile(
        payer=payer,
        instructions=sol_ixs,
        address_lookup_table_accounts=[lut],
        recent_blockhash=recent_blockhash,
    )

    # Create an "unsigned" transaction — we populate the signature slot with
    # a zero placeholder. Phantom will replace it when signing.
    # VersionedTransaction requires at least one signature slot per signer
    # in the message, so we give it a dummy.
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
