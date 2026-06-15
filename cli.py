#!/usr/bin/env python3
"""gib-bot CLI — local tool for gib.meme tournament deck submission.

Usage:
    python cli.py inventory              # show your cards + lock status + power
    python cli.py plan [--champs N]      # score cards and build decks -> plan.json
    python cli.py simulate               # dry-run txs against mainnet (no signing)
    python cli.py submit                 # open Phantom bridge and submit for real

Set HELIUS_API_KEY and WALLET in .env or as env vars.

Fork note (2026-06-15): see CHANGES.md.
  - submit: tournament index is re-resolved at the top of every cascade pass
    so a tournament-window transition mid-batch does NOT silently land tail
    txs on the wrong (now-closed) tournament.
  - simulate / submit / deposit: txbuilder.fetch_lookup_tables() returns both
    primary + fallback ALTs; the v0 message references both concurrently.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Load .env if present
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from gib import binder, config, decks, deposit, discover, rpc, score, tx


STATE_DIR = Path(__file__).parent / "state"


def cmd_inventory(args: argparse.Namespace) -> None:
    wallet = os.environ.get("WALLET", "")
    if not wallet:
        print("error: set WALLET env var or in .env", file=sys.stderr)
        sys.exit(1)

    print(f"loading inventory for {wallet}...")
    cards = binder.load_full_inventory(wallet)

    available = [c for c in cards if c.is_free]
    in_tourney = [c for c in cards if c.is_locked_on_marketplace]

    print(f"\ntotal cards:      {len(cards)}")
    print(f"available:        {len(available)}")
    print(f"in tournament(s): {len(in_tourney)} (still submittable to new tourneys)")
    print(f"max decks:        {len(available) // config.CARDS_PER_DECK}")

    if available:
        with_stats = [c for c in available if c.power is not None]
        with_stats.sort(key=lambda c: c.power or 0, reverse=True)

        print(f"\n{'SLOT':>4} {'MEME':20s} {'POWER':>10} {'7d%':>8} {'24h%':>8} {'MC':>14}")
        print("-" * 70)
        for c in with_stats[:40]:
            print(
                f"{c.slot:4d} {c.meme or '???':20s} "
                f"{c.power or 0:10.2f} "
                f"{c.change_7d or 0:8.2f} "
                f"{c.change_24h or 0:8.2f} "
                f"{c.market_cap or 0:14,.0f}"
            )
        if len(with_stats) > 40:
            print(f"  ... and {len(with_stats) - 40} more")

    STATE_DIR.mkdir(exist_ok=True)
    inv = []
    for c in cards:
        inv.append({
            "slot": c.slot,
            "meme": c.meme,
            "power": c.power,
            "change_7d": c.change_7d,
            "change_24h": c.change_24h,
            "market_cap": c.market_cap,
            "volume_24h": c.volume_24h,
            "spl_mint": c.spl_mint,
            "in_tournament": c.is_locked_on_marketplace,
            "asset_hash": c.asset_hash,
        })
    out = STATE_DIR / "inventory.json"
    out.write_text(json.dumps(inv, indent=2))
    print(f"\nsaved to {out}")


def cmd_plan(args: argparse.Namespace) -> None:
    wallet = os.environ.get("WALLET", "")
    if not wallet:
        print("error: set WALLET env var or in .env", file=sys.stderr)
        sys.exit(1)

    print(f"loading inventory for {wallet}...")
    cards = binder.load_full_inventory(wallet)

    free = [c for c in cards if c.is_free]
    print(f"free cards: {len(free)}")

    if len(free) < config.CARDS_PER_DECK:
        print("not enough free cards to build any decks.")
        sys.exit(0)

    scored = score.score_cards(free, include_no_stats=args.include_zero)
    positive = [s for s in scored if s.score > 0]
    skipped = len(scored) - len(positive)
    print(f"scored cards: {len(scored)} ({len(positive)} with power, {skipped} zero)")

    tournament_index = _resolve_tournament(args.tournament)
    registered = binder.get_registered_slots(cards, tournament_index)
    exclude_slots: set[int] = set(registered)
    if registered:
        print(f"{len(registered)} cards already registered in tournament {tournament_index}, excluding")

    start_index = len(registered) // config.CARDS_PER_DECK
    if registered:
        print(f"starting deck index at {start_index}")

    if args.exclude:
        exclude_path = Path(args.exclude)
        if not exclude_path.exists():
            print(f"error: exclude file not found: {args.exclude}", file=sys.stderr)
            sys.exit(1)
        prior = json.loads(exclude_path.read_text())
        for d in prior:
            for slot in d["cards"]:
                exclude_slots.add(slot)
        prior_max = max(d["index"] for d in prior) + 1
        start_index = max(start_index, prior_max)
        print(f"also excluding {len(set(s for d in prior for s in d['cards']))} slots from prior plan")

    if args.start_index > 0:
        start_index = args.start_index

    built = decks.build_decks(scored,
                              start_index=start_index, exclude_slots=exclude_slots,
                              include_zero=args.include_zero)
    print(f"built {len(built)} decks")

    if built:
        print(f"\n{'IDX':>3} {'TOTAL':>8} {'MIN':>8}  {'CARDS'}")
        print("-" * 75)
        for d in built:
            print(f"{d.index:3d} {d.deck_score:8.1f} {d.min_score:8.1f}  {d.label}")

        totals = sorted([d.deck_score for d in built])
        median = totals[len(totals) // 2]
        spread = (totals[-1] - totals[0]) / median * 100 if median else 0
        print(f"\ndeck distribution:")
        print(f"  strongest: {totals[-1]:.1f}  weakest: {totals[0]:.1f}")
        print(f"  median:    {median:.1f}  spread: {spread:.0f}%")

    STATE_DIR.mkdir(exist_ok=True)
    plan = []
    for d in built:
        plan.append({
            "index": d.index,
            "cards": list(d.cards),
            "min_score": round(d.min_score, 4),
            "deck_score": round(d.deck_score, 4),
            "label": d.label,
        })
    out = STATE_DIR / "plan.json"
    out.write_text(json.dumps(plan, indent=2))
    print(f"\nsaved to {out}")
    print("edit plan.json if you want to override any deck, then run `simulate`.")


def _resolve_tournament(args_tournament: int | None) -> int:
    """Get tournament index from --tournament flag or auto-detect from the API."""
    if args_tournament is not None:
        return args_tournament
    print("auto-detecting open tournament...")
    idx = rpc.find_open_tournament()
    if idx is None:
        print("error: no tournament currently open for registration.", file=sys.stderr)
        sys.exit(1)
    print(f"found tournament {idx} (registration open)")
    return idx


def _build_all_instructions(plan: list[dict], wallet: str, tournament_index: int) -> list:
    instructions = []
    for d in plan:
        ix = tx.build_register_to_tournament(
            creator=wallet,
            tournament_index=tournament_index,
            deck_index=d["index"],
            cards=d["cards"],
        )
        instructions.append(ix)
    return instructions


def cmd_simulate(args: argparse.Namespace) -> None:
    wallet = os.environ.get("WALLET", "")
    plan_file = STATE_DIR / "plan.json"
    if not plan_file.exists():
        print("error: run `plan` first to generate plan.json", file=sys.stderr)
        sys.exit(1)

    plan = json.loads(plan_file.read_text())
    print(f"loaded {len(plan)} decks from plan.json")

    tournament_index = _resolve_tournament(args.tournament)

    print(f"building {len(plan)} instructions for tournament {tournament_index}...")
    instructions = _build_all_instructions(plan, wallet, tournament_index)
    print(f"all {len(instructions)} instructions built.")

    try:
        from gib import txbuilder
        from solders.pubkey import Pubkey

        print("fetching lookup tables (primary + fallback)...")
        luts = txbuilder.fetch_lookup_tables()
        for l in luts:
            print(f"  LUT {str(l.key)[:8]}...: {len(l.addresses)} addresses")

        print("fetching recent blockhash...")
        blockhash = txbuilder.get_recent_blockhash()
        payer = Pubkey.from_string(wallet)

        batches = txbuilder.batch_instructions(instructions, max_per_batch=1)
        print(f"batched into {len(batches)} transactions (1 deck per tx)")

        for i, batch in enumerate(batches):
            vtx = txbuilder.build_versioned_transaction(
                batch, payer, blockhash, luts,
                compute_units=1_400_000,
            )
            tx_b64 = txbuilder.serialize_for_phantom(vtx)
            size = len(tx_b64) * 3 // 4
            print(f"  tx {i}: {len(batch)} decks, ~{size} bytes serialized")

            if i == 0:
                print(f"\nsimulating tx 0 against mainnet...")
                result = rpc.simulate_transaction(tx_b64)
                err = result.get("value", {}).get("err")
                logs = result.get("value", {}).get("logs", [])
                cu = result.get("value", {}).get("unitsConsumed", 0)
                if err:
                    print(f"  simulation FAILED: {err}")
                    for log_line in logs[-5:]:
                        print(f"    {log_line}")
                else:
                    print(f"  simulation OK — {cu} CU consumed")
                    reg_logs = [l for l in logs if "RegisterToTournament" in l or "c 0" in l]
                    if reg_logs:
                        print(f"  program logs confirm {len([l for l in logs if 'c 0' in l])} card validations")

        print(f"\nall {len(batches)} txs built successfully. ready for `submit`.")

    except ImportError:
        print("\nsolders not available — install deps with `pip install -e .`")
        print(f"instruction count: {len(instructions)}, ~{len(instructions)//10 + 1} Phantom popups")


def cmd_deposit(args: argparse.Namespace) -> None:
    """Move loose gib.meme cNFTs from the wallet into the binder PDA so they
    become eligible for register_to_tournament. One tx per card: Bubblegum
    Transfer + RegisterCard."""
    wallet = os.environ.get("WALLET", "")
    if not wallet:
        print("error: set WALLET env var or in .env", file=sys.stderr)
        sys.exit(1)

    print(f"scanning wallet {wallet} for loose gib.meme cards...")
    loose = discover.find_loose_cards(wallet, collections=(discover.GIGAPACK_COLLECTION,))
    print(f"found {len(loose)} loose GIGAPACK cards")
    if not loose:
        print("nothing to deposit.")
        return

    plans = []
    for a in loose:
        try:
            p = deposit.plan_deposit(wallet, a["id"])
            plans.append(p)
            print(f"  {p.asset_id[:12]}...  meme={p.meme:10s}  card_id={p.card_id}")
        except Exception as e:
            print(f"  {a['id'][:12]}...  ERROR: {e}")

    if not plans:
        print("no depositable cards.")
        return

    print("\ndiscovering per-user HgtiJu PDA from recent RegisterCard tx...")
    hgtiju_pda = discover.find_recent_hgtiju_pda(wallet)
    if not hgtiju_pda:
        print("error: no past RegisterCard tx found for this wallet — deposit at least", file=sys.stderr)
        print("       one card via the gib.meme UI first so the per-user PDA exists on-chain.", file=sys.stderr)
        sys.exit(1)
    print(f"  using hgtiju_pda = {hgtiju_pda}")

    import struct, base64
    from gib.pdas import binder_pda
    binder_addr, _ = binder_pda(wallet)
    binder_info = rpc.get_account_info(binder_addr)
    if not binder_info:
        print(f"error: binder account {binder_addr} not found — deposit one card via the gib.meme UI first", file=sys.stderr)
        sys.exit(1)
    binder_raw = base64.b64decode(binder_info["data"][0])
    starting_slot = struct.unpack_from("<H", binder_raw, 59)[0]
    print(f"  binder live_spaces = {starting_slot}  (deposits will fill slots {starting_slot}..{starting_slot + len(plans) - 1})")

    if args.only is not None:
        idx = args.only
        if idx >= len(plans):
            print(f"error: --only={idx} out of range (have {len(plans)} plans)", file=sys.stderr); sys.exit(1)
        plans = [plans[idx]]
        print(f"\nlimiting to plan[{args.only}] = {plans[0].meme}")

    from gib import txbuilder, sign_server
    from solders.pubkey import Pubkey
    from concurrent.futures import ThreadPoolExecutor

    print("\nfetching lookup tables (primary + fallback) + blockhash...")
    luts = txbuilder.fetch_lookup_tables()
    payer = Pubkey.from_string(wallet)

    def build_chunk(start: int, count: int) -> dict:
        end = min(start + count, len(plans))
        blockhash = txbuilder.get_recent_blockhash()

        def build_one(i: int) -> dict:
            plan = plans[i]
            ixs = deposit.build_deposit_instructions(
                wallet, plan, hgtiju_pda, new_slot_index=starting_slot + i,
            )
            vtx = txbuilder.build_versioned_transaction(
                ixs, payer, blockhash, luts, compute_units=400_000,
            )
            tx_b64 = txbuilder.serialize_for_phantom(vtx)
            label = f"deposit {plan.meme} {plan.asset_id[:8]}"
            sim = rpc.simulate_transaction(tx_b64).get("value", {})
            err = sim.get("err")
            if err:
                logs = sim.get("logs", [])
                tail = "\n      ".join(logs[-6:])
                return {"skip": True, "label": label, "reason": f"pre-sim failed: {err}\n      {tail}", "plan_idx": i}
            cu = sim.get("unitsConsumed", 0)
            return {"base64": tx_b64, "label": label + f" ({cu} CU)", "index": i, "plan_idx": i}

        with ThreadPoolExecutor(max_workers=4) as ex:
            built = list(ex.map(build_one, range(start, end)))
        txs = [b for b in built if not b.get("skip")]
        skipped = [{"label": b["label"], "reason": b["reason"]} for b in built if b.get("skip")]
        return {"txs": txs, "skipped": skipped}

    if args.simulate_only:
        print("\nSIMULATE ONLY — building first tx and running simulateTransaction...")
        chunk = build_chunk(0, 1)
        if chunk["skipped"]:
            for s in chunk["skipped"]:
                print(f"  SKIP {s['label']}: {s['reason']}")
            sys.exit(2)
        for t in chunk["txs"]:
            print(f"  OK   {t['label']}")
        print("\nsimulate looks good. Re-run without --simulate-only to actually sign.")
        return

    chunk_size = args.chunk_size
    print(f"\n{len(plans)} deposits in chunks of {chunk_size} -> ~{(len(plans)+chunk_size-1)//chunk_size} popup(s)")
    results = sign_server.run_bridge(
        port=args.port, total=len(plans),
        chunk_size=chunk_size, build_chunk=build_chunk,
    )
    successes = sum(1 for r in results if "signature" in r)
    print(f"\n--- deposits: {successes}/{len(plans)} landed ---")
    if successes:
        first_sig = next((r["signature"] for r in results if "signature" in r), None)
        if first_sig:
            print(f"first signature: {first_sig}")


def _run_submit_pass(
    *,
    plan_decks: list[dict],
    wallet: str,
    tournament_index: int,
    chunk_size: int,
    port: int,
    open_browser: bool = True,
) -> list[dict]:
    """One bridge session signing+broadcasting the given decks. Returns
    per-deck results from the bridge."""
    from concurrent.futures import ThreadPoolExecutor
    from gib import txbuilder, sign_server
    from solders.pubkey import Pubkey

    instructions = _build_all_instructions(plan_decks, wallet, tournament_index)
    luts = txbuilder.fetch_lookup_tables()
    payer = Pubkey.from_string(wallet)

    def build_chunk(start: int, count: int) -> dict:
        end = min(start + count, len(plan_decks))
        blockhash = txbuilder.get_recent_blockhash()

        def build_one(i: int) -> dict:
            vtx = txbuilder.build_versioned_transaction(
                [instructions[i]], payer, blockhash, luts, compute_units=1_400_000,
            )
            tx_b64 = txbuilder.serialize_for_phantom(vtx)
            label = f"deck {plan_decks[i]['index']}: {plan_decks[i]['label']}"
            sim = rpc.simulate_transaction(tx_b64).get("value", {})
            err = sim.get("err")
            if err:
                return {"skip": True, "label": label, "reason": f"pre-sim failed: {err}", "plan_idx": i}
            return {"base64": tx_b64, "label": label, "index": plan_decks[i]["index"], "plan_idx": i}

        with ThreadPoolExecutor(max_workers=8) as ex:
            built = list(ex.map(build_one, range(start, end)))
        txs = [b for b in built if not b.get("skip")]
        skipped = [{"label": b["label"], "reason": b["reason"]} for b in built if b.get("skip")]
        return {"txs": txs, "skipped": skipped}

    return sign_server.run_bridge(
        port=port, total=len(plan_decks),
        chunk_size=chunk_size, build_chunk=build_chunk,
        open_browser=open_browser,
    )


def cmd_submit(args: argparse.Namespace) -> None:
    wallet = os.environ.get("WALLET", "")
    plan_file = STATE_DIR / "plan.json"
    if not plan_file.exists():
        print("error: run `plan` first to generate plan.json", file=sys.stderr)
        sys.exit(1)

    full_plan = json.loads(plan_file.read_text())
    # Initial tournament resolution; we re-check at every cascade pass.
    initial_tournament_index = _resolve_tournament(args.tournament)

    if args.no_retry:
        cascade = [args.chunk_size]
    else:
        cascade = [args.chunk_size] + [s for s in (10, 5, 3, 1) if s < args.chunk_size]

    history_file = STATE_DIR / "submitted.json"
    STATE_DIR.mkdir(exist_ok=True)

    total_landed = 0
    total_pass = 0
    session_locked: set[int] = set()
    for chunk_size in cascade:
        print(f"\n=== pass {total_pass + 1}/{len(cascade)} (chunk-size {chunk_size}) ===")

        # Re-resolve tournament if not user-pinned. If the active tournament
        # changed since the prior pass, abort — the new tail won't make it
        # into the previous tournament's bracket and shouldn't silently land
        # in a different one.
        if args.tournament is None:
            current = rpc.find_open_tournament()
            if current is None:
                print("no tournament currently open for registration — stopping cascade.")
                break
            if current != initial_tournament_index:
                print(f"tournament window changed mid-cascade: was {initial_tournament_index}, "
                      f"now {current}. Stopping. Re-run with --tournament {current} to retarget.")
                break
            tournament_index = current
        else:
            tournament_index = initial_tournament_index

        print("checking on-chain state for already-registered cards...")
        all_cards = binder.fetch_binder(wallet)
        registered = binder.get_registered_slots(all_cards, tournament_index) | session_locked
        pending = [d for d in full_plan if not any(s in registered for s in d["cards"])]
        if not pending:
            print("all decks already registered — nothing more to submit.")
            break
        print(f"{len(pending)} decks pending  ({len(full_plan) - len(pending)} already landed)")

        results = _run_submit_pass(
            plan_decks=pending, wallet=wallet, tournament_index=tournament_index,
            chunk_size=chunk_size, port=args.port,
            open_browser=(total_pass == 0),
        )
        sent = sum(1 for r in results if "signature" in r)
        total_landed += sent
        total_pass += 1
        print(f"pass {total_pass} result: {sent} landed, {len(results) - sent} failed/skipped")

        landed_labels = {r["label"] for r in results if "signature" in r}
        for d in pending:
            label = f"deck {d['index']}: {d['label']}"
            if label in landed_labels:
                for s in d["cards"]:
                    session_locked.add(s)

        history = json.loads(history_file.read_text()) if history_file.exists() else []
        timestamp = datetime.now(timezone.utc).isoformat()
        by_label = {r.get("label"): r for r in results}
        for d in pending:
            label = f"deck {d['index']}: {d['label']}"
            r = by_label.get(label, {})
            history.append({
                "index": d["index"], "cards": d["cards"], "label": d["label"],
                "tournament": tournament_index,
                "signature": r.get("signature"), "error": r.get("error"),
                "timestamp": timestamp, "pass": total_pass, "chunk_size": chunk_size,
            })
        history_file.write_text(json.dumps(history, indent=2))

        if sent == 0:
            print("pass made zero progress — stopping cascade.")
            break

    print(f"\n--- Cascade complete ---")
    print(f"total landed across {total_pass} pass(es): {total_landed}")
    print(f"submission history: {history_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="gib-bot — gib.meme tournament deck tool")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("inventory", help="Show your cards, lock status, and power")

    plan_p = sub.add_parser("plan", help="Score cards and build decks")
    plan_p.add_argument("--start-index", type=int, default=0, help="First deck index (default 0, auto-detected from on-chain state)")
    plan_p.add_argument("--exclude", type=str, default=None, help="Path to prior plan.json to also exclude those cards")
    plan_p.add_argument("--tournament", type=int, default=None, help="Override tournament index (auto-detected if omitted)")
    plan_p.add_argument("--include-zero", action=argparse.BooleanOptionalAction, default=True,
                        help="Use every card regardless of score sign (default True; --no-include-zero to filter)")

    sim_p = sub.add_parser("simulate", help="Dry-run tx building")
    sim_p.add_argument("--tournament", type=int, default=None, help="Override tournament index (auto-detected if omitted)")

    dep_p = sub.add_parser("deposit", help="Move loose gib.meme cards from wallet into binder")
    dep_p.add_argument("--port", type=int, default=8787, help="Localhost port for Phantom bridge")
    dep_p.add_argument("--chunk-size", type=int, default=25, help="Transactions per Phantom popup")
    dep_p.add_argument("--simulate-only", action="store_true", help="Build + simulate first tx, don't sign")
    dep_p.add_argument("--only", type=int, default=None, help="Restrict to plan index N (for testing)")

    sub_p = sub.add_parser("submit", help="Open Phantom bridge and submit decks")
    sub_p.add_argument("--tournament", type=int, default=None, help="Override tournament index (auto-detected if omitted)")
    sub_p.add_argument("--port", type=int, default=8787, help="Localhost port for Phantom bridge")
    sub_p.add_argument("--chunk-size", type=int, default=25, help="First-pass tx-per-popup count (default 25). Cascade then drops to 10->5->3->1 unless --no-retry is set.")
    sub_p.add_argument("--no-retry", action="store_true", help="Disable the 25->10->5->3->1 auto-retry cascade; only run the initial chunk-size pass.")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    {"inventory": cmd_inventory, "plan": cmd_plan, "simulate": cmd_simulate, "deposit": cmd_deposit, "submit": cmd_submit}[args.command](args)


if __name__ == "__main__":
    main()
