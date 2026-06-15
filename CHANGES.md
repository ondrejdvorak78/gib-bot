# Changes in this fork

Fork date: 2026-06-15. Forked from
[ForWakanda/gib-bot](https://github.com/ForWakanda/gib-bot).

The motivation for this fork is a set of correctness, robustness, and
security improvements that surfaced during a code review of the upstream
codebase plus an on-chain investigation of register-tournament transactions
on a recent gib.meme tournament. Two of the fixes address failure modes that
were observed empirically (stale lookup-table reference; tournament-window
race during cascade retries); the rest are defense-in-depth.

The bot's strategy (greedy power-descending), the user-facing CLI shape, the
binder-account parser, and the PDA derivations are unchanged. If you depend
on the upstream behavior exactly, do not adopt this fork.

The changes are listed in roughly descending order of impact.

---

## 1. Lookup-table reference is multi-ALT + fetched fresh

`gib/config.py`, `gib/txbuilder.py`, `cli.py`.

The upstream config pins one address lookup table (ALT) as "the official
client's ALT". A scan of the most recent 100 register-tournament transactions
on tournament 86 (2026-06-15) showed that 97 of them used a *different* ALT,
and the upstream's pinned ALT differs from the now-canonical one at indices
9-10. The two ALTs are valid concurrently — they share 15/17 entries — but
the upstream pin is behind the current client.

This fork:

- Renames the pinned ALT to `LOOKUP_TABLE_OFFICIAL` and adds
  `LOOKUP_TABLE_FALLBACK` for the upstream's prior value.
- Adds `txbuilder.fetch_lookup_tables()` that pulls both from chain and
  returns a list.
- Passes the list of ALTs to `MessageV0.try_compile`. Solana deduplicates
  account references across multiple ALTs in a single v0 message, so this
  gracefully degrades when gib.meme retires one of the two.
- Back-compat for callers passing a single ALT is preserved at
  `build_versioned_transaction(... lut=alt_or_list_of_alts)`.

If you need to force a specific ALT, set `LOOKUP_TABLE` in `gib/config.py`
and call `fetch_lookup_table(LOOKUP_TABLE)` directly.

## 2. ALT header parsing is by spec, not by offset guessing

`gib/txbuilder.py:_parse_lut_account`.

Upstream tries to detect the ALT layout offset by "find the offset where
(len(raw) - offset) % 32 == 0", trying `[56, 54, 58]`. This works for the
current state of the upstream's pinned ALT, but is brittle if Solana
deactivates the ALT, the authority is removed, or padding shifts in a future
runtime upgrade.

This fork parses the layout per the documented Solana address-lookup-table
account format (type discriminator + deactivation_slot + last_extended_slot +
last_extended_start_index + padding + authority option + authority +
addresses) and raises if the body length isn't a multiple of 32.

## 3. `confirm_transaction` no longer accepts `"processed"`

`gib/rpc.py:confirm_transaction`.

Upstream docstring stated: *"Accepts processed as confirmation since pre-sim
guarantees the tx will succeed."* This conflates pre-simulation passes (a
program-logic check) with on-chain finalization. A `processed` transaction
has been seen by one validator but is not yet confirmed across the cluster
and can be dropped on a reorg.

The cost of accepting `processed` is silent under-submission: the bot's
state file records a signature claim that the on-chain registry does not
back, and the within-session `session_locked` set blocks the cascade from
re-submitting the same deck. The user sees a "success" in the bot's log but
their deck is missing in the tournament.

This fork accepts only `confirmed` or `finalized` from `getSignatureStatuses`.
The confirm timeout also defaults to 30s (up from 12s) to reduce false
negatives at high cluster load.

## 4. `send_transaction` no longer skips preflight

`gib/rpc.py:send_transaction`.

Upstream sent transactions with `skipPreflight: True`, on the theory that
pre-simulation upstream of submit catches the failure modes. Pre-sim catches
program-logic reverts; it does NOT catch transaction-level issues like
expired blockhash, recent state changes that invalidate account references,
or signer-mismatch — and these are exactly the failure modes you hit when a
user clicks Phantom approval 60+ seconds after the chunk was built (the
default Solana blockhash window is ~150 slots, ~60-90s of clock time).

Skipping preflight means an expired-blockhash transaction enters the mempool
and silently expires without ever landing; the bot's `confirm_transaction`
sees no status and reports timeout, but `session_locked` already believes
the slot landed.

This fork sends with `skipPreflight: False, preflightCommitment: confirmed`.
You will see fewer silent-expiry failure modes; you will see more "preflight
failed: blockhash not found" errors at submit time. The latter are real
signals — re-build the chunk with a fresh blockhash and retry.

## 5. Signing bridge binds to `127.0.0.1`

`gib/sign_server.py:run_bridge`.

Upstream bound `0.0.0.0`, making the bridge reachable from other machines on
the LAN. The bridge:

- Serves the user's wallet public key in `/api/meta` and the planned-deck
  list via `/api/chunk` (leaks of planned deck composition to anyone on the
  LAN).
- Accepts `signed: [base64...]` at `/api/signed_chunk` and broadcasts them
  unconditionally — a malicious user on the LAN cannot produce valid
  Phantom signatures from someone else's wallet, but they CAN drain the
  bot's RPC budget by submitting garbage repeatedly.

This fork binds `127.0.0.1` by default. The `run_bridge(..., bind_host=...)`
parameter lets you opt into `0.0.0.0` explicitly if you understand the
implication (e.g., bot running on a Raspberry Pi, browser on a separate
desktop on a trusted home network).

## 6. Cascade re-resolves the tournament index per pass

`cli.py:cmd_submit`.

Upstream resolves `tournament_index` once at the top of the submit command
and reuses it across the 25 -> 10 -> 5 -> 3 -> 1 cascade. If the gib.meme
tournament window transitions mid-batch (T#N closes registration, T#N+1
opens), the tail of the cascade still targets T#N. Submissions fail at the
preflight or pre-sim — but the user has no clear signal that the rest of
their decks will not land.

This fork:

- Re-checks `find_open_tournament()` at the top of every cascade pass.
- If the open tournament has changed since the initial resolution, aborts
  the cascade cleanly and prints a `re-run with --tournament <new>` hint.
- Users who pinned `--tournament N` explicitly are unaffected.

## 7. Duplicate-card-slot validation at instruction encoder

`gib/tx.py:encode_register_to_tournament_data`.

The README documents that users can hand-edit `state/plan.json` between
`plan` and `submit`. A hand edit can easily produce a deck like
`[5, 5, 7]`. Upstream validates the card count and each slot's u16 range
but not slot uniqueness; the on-chain program rejects with an "all-cards
must be distinct" error in pre-sim, so the bot catches it — but the user
loses a Phantom approval cycle.

This fork rejects duplicate-slot inputs at encode time:
`if len(set(cards)) != len(cards): raise ValueError(...)`.

## 8. Binder parse has an explicit bounds check

`gib/binder.py:parse_binder_account`.

Upstream reads `stored_cards` from the binder header and loops without
checking that the per-card region actually fits the data buffer. On a
truncated or partial-resize binder read (mostly hypothetical, but observed
in past Solana runtime migrations), the loop walks off the end and either
crashes with an opaque slice error or reads garbage card hashes that fail
DAS resolution.

This fork raises a clear `binder truncated` error when
`stored_cards * 152 + 65 > len(data)`.

## 9. `is_in_tournament` uses an explicit tournament-index offset

`gib/binder.py:Card.is_in_tournament`.

Upstream comment: *"The binder stores tournament_index as API_index + 1
(1-based internally), so we check both the exact value and +1 to handle
the offset."* The OR semantics mask bugs at the boundary: a card with state
zero at one index but state nonzero at the other passes both checks, and a
future schema change to a 0-based convention would silently break the
matching.

This fork:

- Replaces the OR check with an explicit offset: `target =
  tournament_index + TOURNAMENT_INDEX_OFFSET` where `TOURNAMENT_INDEX_OFFSET`
  is `1` by default.
- Exposes the offset as the env var `GIB_BOT_TOURNAMENT_INDEX_OFFSET` so a
  future gib.meme schema change can be accommodated without a code edit.

## 10. Binder-account-not-found errors are friendlier

`gib/binder.py:fetch_binder`, `cli.py:cmd_deposit`.

Upstream raised `RuntimeError(f"binder account {binder_addr} not found")` in
`fetch_binder` (good) but separately raised a bare `KeyError: 'data'` in
`cmd_deposit` when reading binder live_spaces on a fresh wallet (less good).
Both paths now produce the same clear message: *"deposit one card via the
gib.meme UI first"*.

## 11. `simulate_transaction` uses explicit `confirmed` commitment

`gib/rpc.py:simulate_transaction`.

Upstream called `simulateTransaction` without specifying commitment, which
inherits the RPC's default (`finalized` on Helius). Finalized-state sim
during a mass-entry cascade pass can miss recently-landed-but-not-finalized
accounts and report errors that the real submit (running at `confirmed` or
`processed`) would not encounter.

This fork passes `commitment: "confirmed"` explicitly so the simulation
sees the same state the submit will hit.

## 12. Cross-platform browser auto-open

`gib/sign_server.py:run_bridge`.

Upstream spawned `cmd.exe /c start "" chrome <url>` on every platform —
worked on Windows + Chrome, fell through to "open manually" on macOS /
Linux. This fork uses `webbrowser.open(url)` from the stdlib, which is
cross-platform.

## 13. Activity-log instruction is now opt-in

`gib/config.py`.

Upstream defined `ACTIVITY_LOG_PROGRAM` as a constant and commented that the
old gib.meme client appended a tail instruction to that program for the
3.land UI feeds. The bot did not actually emit the instruction. A scan of
recent register-tournament transactions shows the *current* gib.meme client
also omits it (97/100), so the default in this fork remains "do not emit".

For users who want compatibility with downstream systems that key off this
instruction (if you discover one), set the env var
`GIB_BOT_ENABLE_ACTIVITY_LOG=1`. The instruction encoding is intentionally
not implemented in this fork yet — it would need the program's
instruction-discriminator + arg layout, which is not in the published
gib.meme bundle. Open a PR if you reverse-engineer it.

## 14. Dependency cleanup

`pyproject.toml`.

`httpx` and `aiohttp` were declared but unused (`rpc.py` and `sign_server.py`
use stdlib `urllib` and `http.server`). Removed.

---

## What did NOT change

- **Strategy.** Power-descending greedy deck construction is unchanged. If
  you wanted a different strategy, the upstream README's pointer at
  `gib/score.py` still applies.
- **PDA derivations.** All four PDA seed schemes are bit-identical.
- **Instruction layout for `register_to_tournament`.** Unchanged.
- **Bubblegum Transfer + RegisterCard for the deposit path.** Unchanged.
- **CLI surface.** All commands, all flags, all defaults preserved.
- **Phantom-only browser detection.** Still Phantom-only in the bridge HTML;
  if you want to use Backpack or Solflare, contributions welcome.
- **Cards-per-deck = 3.** Hardcoded; the upstream README's comment on
  `CARDS_PER_DECK` in `gib/config.py` still applies.

---

## Migration notes for users upgrading from upstream

1. Re-install: `pip install -e .` to pick up the dropped `httpx` / `aiohttp`
   deps.
2. If you had `LOOKUP_TABLE` referenced in any custom scripts, it still
   resolves to a valid ALT; the new `LOOKUP_TABLE_OFFICIAL` is also
   exported.
3. If you ran with `--no-retry` and relied on `skipPreflight: True` to land
   blockhash-stale txs anyway, behavior changes: you will see
   `blockhash not found` errors that did not surface before. Re-running
   `submit` after the initial cascade lets the new pass build with a fresh
   blockhash.
4. If the gib.meme schema changes the tournament-index offset, set
   `GIB_BOT_TOURNAMENT_INDEX_OFFSET` rather than waiting for a code update.
