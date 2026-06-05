"""cNFT helpers — Bubblegum Transfer ix + DAS proof fetch.

For the gib.meme tournaments, this is what powers moving a loose cNFT from
the wallet into the binder PDA (so the existing register_to_tournament call
can see it). Once a card is in the binder it's never moved by us again.
"""
from __future__ import annotations

import base64
import struct
from dataclasses import dataclass
from typing import Sequence

from . import config, rpc
from .pdas import b58decode
from .tx import AccountMeta, Instruction


BUBBLEGUM_PROGRAM = "BGUMAp9Gq7iTEuizy4pqaxsTyUCBK68MDfK752saRPUY"
SPL_ACCOUNT_COMPRESSION = "cmtDvXumGCrqC1Age74AVPhSRVXJMd8PJS91L8KbNCK"
SPL_NOOP = "noopb9bkMVfRPU8AsbpTUg8AQkHtKwMYZiFUjNRtMmV"

# Anchor disc for `global:transfer` on Bubblegum
TRANSFER_DISC = bytes.fromhex("a334c8e78c0345ba")

# Proof hashes to include in the ix (max_depth=16, canopy_depth=8, so 8 hashes pass).
PROOF_LEN = 8


@dataclass(frozen=True)
class CnftDetails:
    asset_id: str
    tree: str
    leaf_id: int                   # also used as nonce + index
    data_hash: str                 # base58
    creator_hash: str              # base58
    root: str                      # base58
    proof: tuple[str, ...]         # full proof (we pass first PROOF_LEN of these)
    name: str
    symbol: str
    arweave_uri_hash: str          # the 43-char path under arweave.net (no query string)
    owner: str
    json_uri_full: str
    leaf_owner: str
    leaf_delegate: str


def _arweave_hash(json_uri: str) -> str:
    """Extract the 43-char arweave hash from a json_uri like
    'https://arweave.net/<hash>?query=stuff'."""
    if "arweave.net/" not in json_uri:
        raise ValueError(f"json_uri is not arweave: {json_uri!r}")
    after = json_uri.split("arweave.net/", 1)[1]
    # strip query string
    if "?" in after:
        after = after.split("?", 1)[0]
    return after


def fetch_cnft_details(asset_id: str) -> CnftDetails:
    """Pull all the data we need for one cNFT: identity, proof, metadata."""
    asset = rpc.get_asset(asset_id)
    proof = rpc._post(rpc._HELIUS_RPC, {
        "jsonrpc": "2.0", "id": 1, "method": "getAssetProof",
        "params": {"id": asset_id},
    })["result"]

    comp = asset["compression"]
    content = asset.get("content", {})
    md = content.get("metadata", {})

    return CnftDetails(
        asset_id=asset_id,
        tree=comp["tree"],
        leaf_id=int(comp["leaf_id"]),
        data_hash=comp["data_hash"],
        creator_hash=comp["creator_hash"],
        root=proof["root"],
        proof=tuple(proof["proof"]),
        name=md.get("name", ""),
        symbol=md.get("symbol", ""),
        arweave_uri_hash=_arweave_hash(content["json_uri"]),
        owner=asset["ownership"]["owner"],
        json_uri_full=content["json_uri"],
        leaf_owner=asset["ownership"]["owner"],
        leaf_delegate=asset["ownership"].get("delegate") or asset["ownership"]["owner"],
    )


def tree_authority_pda(tree: str) -> str:
    """Derive the Bubblegum tree_authority PDA: PDA([tree_pubkey], BUBBLEGUM_PROGRAM)."""
    from .pdas import find_program_address
    addr, _ = find_program_address([b58decode(tree)], BUBBLEGUM_PROGRAM)
    return addr


def build_bubblegum_transfer(
    asset: CnftDetails,
    new_leaf_owner: str,
) -> Instruction:
    """Build a Bubblegum `transfer` ix moving a cNFT from its current owner
    to `new_leaf_owner`. The current leaf_owner signs the tx."""
    root = b58decode(asset.root)
    data_hash = b58decode(asset.data_hash)
    creator_hash = b58decode(asset.creator_hash)
    if not (len(root) == len(data_hash) == len(creator_hash) == 32):
        raise ValueError("hash decode error")

    data = bytearray(TRANSFER_DISC)
    data += root
    data += data_hash
    data += creator_hash
    data += struct.pack("<Q", asset.leaf_id)  # nonce u64
    data += struct.pack("<I", asset.leaf_id)  # index u32

    tree_auth = tree_authority_pda(asset.tree)

    accounts = [
        AccountMeta(tree_auth,                is_signer=False, is_writable=False),
        AccountMeta(asset.leaf_owner,         is_signer=True,  is_writable=False),
        AccountMeta(asset.leaf_delegate,      is_signer=False, is_writable=False),
        AccountMeta(new_leaf_owner,           is_signer=False, is_writable=False),
        AccountMeta(asset.tree,               is_signer=False, is_writable=True),
        AccountMeta(SPL_NOOP,                 is_signer=False, is_writable=False),
        AccountMeta(SPL_ACCOUNT_COMPRESSION,  is_signer=False, is_writable=False),
        AccountMeta(config.SYSTEM_PROGRAM,    is_signer=False, is_writable=False),
    ]
    # The first PROOF_LEN proof hashes are passed as remaining accounts.
    for hash_b58 in asset.proof[:PROOF_LEN]:
        accounts.append(AccountMeta(hash_b58, is_signer=False, is_writable=False))

    return Instruction(
        program_id=BUBBLEGUM_PROGRAM,
        accounts=tuple(accounts),
        data=bytes(data),
    )
