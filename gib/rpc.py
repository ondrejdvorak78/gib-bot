"""HTTP clients for Helius RPC, Helius DAS, and the gib.meme stats backend.

All stdlib-only (urllib + json). No httpx/aiohttp required until we need the
Phantom signing bridge (which is a later module).

Fork note (2026-06-15): see CHANGES.md.
  - confirm_transaction: tightened to require "confirmed" / "finalized" (was
    accepting "processed", which silently dropped reorg-impacted txs).
  - send_transaction: skipPreflight flipped to False so RPC catches expired
    blockhashes from slow Phantom approvals before they enter the mempool.
  - simulate_transaction: explicit commitment="confirmed" so the simulation
    sees state at the same point the submit will hit.
"""
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from typing import Any

_HELIUS_KEY = os.environ.get("HELIUS_API_KEY", "")
_HELIUS_RPC = f"https://mainnet.helius-rpc.com/?api-key={_HELIUS_KEY}"

GIB_STATS_URL = "https://api.gib.meme/stats/latest"
GIB_BATTLE_URL = "https://battle.gib.meme/api/gibmeme"


def _post(url: str, payload: dict, timeout: int = 30, max_retries: int = 6) -> Any:
    data = json.dumps(payload).encode()
    delay = 0.5
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=timeout)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 502, 503, 504) and attempt < max_retries - 1:
                time.sleep(delay + random.uniform(0, delay * 0.5))
                delay = min(delay * 2, 8.0)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(delay + random.uniform(0, delay * 0.5))
                delay = min(delay * 2, 8.0)
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError("unreachable")


# --- Helius Solana RPC ---

def get_account_info(pubkey: str, encoding: str = "base64") -> dict | None:
    resp = _post(_HELIUS_RPC, {
        "jsonrpc": "2.0", "id": 1,
        "method": "getAccountInfo",
        "params": [pubkey, {"encoding": encoding}],
    })
    return resp.get("result", {}).get("value")


def simulate_transaction(tx_base64: str) -> dict:
    # Explicit "confirmed" commitment so simulation reads the same state as
    # the submit will. Without this the default ("finalized" on Helius) shows
    # stale state for recently-landed-but-not-finalized accounts, which is
    # exactly the case during a mass-entry cascade pass between sub-batches.
    resp = _post(_HELIUS_RPC, {
        "jsonrpc": "2.0", "id": 1,
        "method": "simulateTransaction",
        "params": [tx_base64, {"encoding": "base64", "commitment": "confirmed"}],
    })
    return resp.get("result", {})


def send_transaction(tx_base64: str) -> str:
    # skipPreflight=False so the RPC catches expired blockhashes / closed
    # tournament windows before the tx hits the mempool. Pre-sim catches the
    # PROGRAM-logic case; preflight catches the TX-level cases (blockhash
    # window, account-not-found, signature-not-valid) which pre-sim doesn't.
    resp = _post(_HELIUS_RPC, {
        "jsonrpc": "2.0", "id": 1,
        "method": "sendTransaction",
        "params": [tx_base64, {
            "encoding": "base64",
            "skipPreflight": False,
            "preflightCommitment": "confirmed",
        }],
    })
    if "error" in resp:
        raise RuntimeError(f"sendTransaction failed: {resp['error']}")
    return resp["result"]


def confirm_transaction(signature: str, timeout: int = 30) -> bool:
    """Poll until a transaction is confirmed-and-successful, reverted, or timeout.

    Returns True only if landed AND program returned no error at "confirmed"
    or "finalized" commitment. Earlier versions of this module accepted
    "processed" status as success; reorg-impacted txs that show "processed"
    can be dropped without finalizing, which leaves the bot's submitted.json
    falsely claiming success while the on-chain registry has no entry.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = _post(_HELIUS_RPC, {
            "jsonrpc": "2.0", "id": 1,
            "method": "getSignatureStatuses",
            "params": [[signature], {"searchTransactionHistory": False}],
        })
        statuses = resp.get("result", {}).get("value", [None])
        if statuses and statuses[0]:
            status = statuses[0]
            if status.get("err"):
                raise RuntimeError(f"tx reverted on-chain: {status['err']}")
            if status.get("confirmationStatus") in ("confirmed", "finalized"):
                return True
        time.sleep(0.5)
    return False


# --- Helius DAS (Digital Asset Standard) ---

def get_asset(asset_id: str) -> dict:
    resp = _post(_HELIUS_RPC, {
        "jsonrpc": "2.0", "id": 1,
        "method": "getAsset",
        "params": {"id": asset_id},
    })
    return resp["result"]


def get_asset_batch(asset_ids: list[str]) -> list[dict]:
    resp = _post(_HELIUS_RPC, {
        "jsonrpc": "2.0", "id": 1,
        "method": "getAssetBatch",
        "params": {"ids": asset_ids},
    }, timeout=60)
    return resp["result"]


# --- gib.meme stats backend ---

def get_all_card_stats() -> list[tuple[str, str, dict]]:
    """Fetch live stats for all meme cards.

    Returns list of [meme_name, spl_mint, {price, change24h, change7d, volume, marketCap, power}].
    No auth required.
    """
    return _post(GIB_STATS_URL, {"coins": []})


def get_tournaments() -> list[dict]:
    """Fetch tournament list from the gib.meme backend.

    Returns list of tournament dicts with keys like index, state, rules, etc.
    State values: 1=registration, 2/3=battling, 4/5=claiming/ended.
    """
    resp = _post(
        f"https://{GIB_STATS_URL.split('/')[2]}/helius-sync/accounts/gib/tournaments",
        {
            "board": "BYYdh3UjeKF1Gfjb4vy2JJhjTUoQxKZ62mP9z5YA9Aou",
            "store": "HnXcGEL6KBqivrKJHSVEj26dkBoENVVXZRibHwh4RmPY",
            "network": "mainnet",
        },
    )
    return resp.get("data", {}).get("data", [])


def find_open_tournament() -> int | None:
    """Return the index of the tournament currently open for registration, or None."""
    tournaments = get_tournaments()
    for t in tournaments:
        if t.get("state") == 1:
            return t["index"]
    return None


def get_card_stats_historical(meme: str, wallet: str, date: int) -> dict | None:
    """Fetch historical card stats at a specific unix timestamp."""
    resp = _post(f"{GIB_BATTLE_URL}/history/stats", {
        "cards": {meme.lower(): {"meme": meme.lower()}},
        "wallet": wallet,
        "date": date,
    })
    return resp.get("data", {}).get("stats", {}).get(meme.lower())
