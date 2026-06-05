"""Find loose gib.meme cNFTs in a wallet that aren't in the binder yet, and
auto-discover the per-user HgtiJu PDA the gib.meme backend currently uses."""
from __future__ import annotations

import json

from . import config, pdas, rpc

# gib.meme collections we know about.
GENESIS_COLLECTION  = "8H8GQpBgEy1A4TkDfQvYvcDXQaaFCp6pPs3WzgMfe6LW"
GIGAPACK_COLLECTION = "12TCHn5MB1TnyWC8dmUThgVHYPSQNVbG7mj6fxV1KhwR"

REGISTER_CARD_DISC_HEX = "21199a6f9b1f2d24"


def find_recent_hgtiju_pda(wallet: str, max_scan: int = 200) -> str | None:
    """Scan the user's binder PDA for a recent RegisterCard tx signed by
    `wallet`; return account[2] (the per-user HgtiJu PDA). None if no
    RegisterCard found in `max_scan` recent sigs."""
    binder_addr, _ = pdas.binder_pda(wallet)
    body = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getSignaturesForAddress",
        "params": [binder_addr, {"limit": max_scan}],
    }
    sigs = [s["signature"] for s in rpc._post(rpc._HELIUS_RPC, body).get("result", [])]
    for sig in sigs:
        body = {
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
            "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"}],
        }
        try:
            tx = rpc._post(rpc._HELIUS_RPC, body).get("result")
        except Exception:
            continue
        if not tx or (tx.get("meta") or {}).get("err"):
            continue
        keys = tx["transaction"]["message"]["accountKeys"]
        if keys[0]["pubkey"] != wallet:
            continue
        for ix in tx["transaction"]["message"]["instructions"]:
            if ix.get("programId") != config.PROGRAM_ID:
                continue
            data = ix.get("data", "")
            try:
                raw = pdas.b58decode(data)
            except Exception:
                continue
            if raw[:8].hex() != REGISTER_CARD_DISC_HEX:
                continue
            accs = ix.get("accounts", [])
            if len(accs) >= 5:
                return accs[2]
    return None


def find_loose_cards(wallet: str, collections: tuple[str, ...] = (GIGAPACK_COLLECTION,)) -> list[dict]:
    """Return cNFT entries directly owned by `wallet` that belong to one of
    the given collections. Cards inside the binder PDA do NOT show up here —
    they're owned by the PDA, not the wallet."""
    out: list[dict] = []
    page = 1
    while True:
        resp = rpc._post(rpc._HELIUS_RPC, {
            "jsonrpc": "2.0", "id": 1, "method": "getAssetsByOwner",
            "params": {"ownerAddress": wallet, "page": page, "limit": 1000,
                       "displayOptions": {"showCollectionMetadata": False}},
        })
        items = resp.get("result", {}).get("items", []) or []
        if not items:
            break
        for a in items:
            for g in a.get("grouping", []) or []:
                if g.get("group_value") in collections:
                    out.append(a)
                    break
        if len(items) < 1000:
            break
        page += 1
    return out
