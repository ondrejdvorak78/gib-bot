# gib-bot

A local tool for [gib.meme](https://gib.meme) players that automates the
tedious part of tournament prep: building decks from your binder and
submitting them all in one Phantom approval flow instead of clicking through
86 popups one at a time.

The bot does **not** try to be smart about deck construction. It sorts your
available cards by raw power (the same value gib.meme shows on each card)
and fills decks of 3 unique-meme cards from strongest down. If you want a
cleverer strategy, edit `plan.json` between `plan` and `submit`, or fork
this and write your own scorer.

## What it actually saves you

- Reads your binder on-chain in one call instead of you scrolling through
  the in-game UI to see what's available.
- Builds and pre-simulates every deck transaction before signing — txs that
  would revert get skipped automatically.
- Batches signing through Phantom's `signAllTransactions` so you confirm
  20-25 decks per popup instead of one at a time.
- Auto-retries failures at smaller batch sizes (25 → 10 → 5 → 3 → 1).
- Re-checks on-chain state between retries so it never re-submits a deck
  that just landed.

## Requirements

- Python 3.10+
- A Solana wallet that has gib.meme cards deposited into its binder (deposit
  them via the gib.meme UI first, or use the `deposit` command below if you
  have loose cards in your wallet).
- A [Helius](https://helius.dev) API key. The free tier is plenty for
  occasional tournament submission — a full 86-deck submit uses well under
  1k credits, and Helius free is 1M/month.
- A browser with the Phantom extension installed (or Phantom mobile + a way
  to open `localhost:8787` on the same device).

## Install

```bash
git clone https://github.com/YOUR-USERNAME/gib-bot.git
cd gib-bot
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env
# edit .env, paste in your Helius key and your wallet's pubkey
```

## Usage

```bash
# 1. Show what cards you have and what's free vs. locked in tournaments.
python cli.py inventory

# 2. Build decks from your free cards. Saves to state/plan.json — open it
#    and tweak if you want before submitting.
python cli.py plan

# 3. Dry-run: builds and simulates the first tx without signing anything.
python cli.py simulate

# 4. Submit for real. Opens a localhost page in your browser; click
#    "Connect" in Phantom, then approve each chunk.
python cli.py submit
```

Optional commands:

```bash
# Move loose gib.meme cards from your wallet INTO your binder so they're
# eligible for tournaments. One tx per card; requires you've previously
# deposited at least one card via the gib.meme UI (that creates the per-user
# PDA the bot needs).
python cli.py deposit

# Submit but don't auto-retry at smaller batch sizes.
python cli.py submit --no-retry

# Override the tournament index if auto-detection picks the wrong one.
python cli.py plan --tournament 84
python cli.py submit --tournament 84
```

## How submission works

1. `plan` writes `state/plan.json` — one entry per deck with the binder slot
   indices it contains. You can edit this file by hand to swap cards.
2. `submit` reads `plan.json`, builds a signed-tx-per-deck against a fresh
   blockhash, and opens `http://localhost:8787` in your browser.
3. The page connects to Phantom, fetches transactions from the bridge in
   chunks of 25, asks Phantom to sign them all at once (one popup per chunk),
   sends them in parallel, and reports per-tx success or error.
4. If anything failed, it retries at smaller chunk sizes (10 → 5 → 3 → 1)
   re-reading on-chain state between passes so already-landed decks are
   skipped.

## Limitations and disclaimers

- **No warranty.** The on-chain gib.meme program could change; the
  gib.meme stats API could change; this bot could break silently. Always
  watch the first few txs land before walking away from a 86-deck submit.
- **No strategy claims.** Power-descending is not a "good" strategy, it's
  the most common one. If you have an opinion about which cards belong
  together, edit `state/plan.json` before running `submit` — every deck is
  a JSON object with a list of binder slot indices you can swap freely.
- **Cards per deck is fixed at 3** to match the current tournament rules.
  If gib.meme changes the rule, update `CARDS_PER_DECK` in `gib/config.py`.
- **Solana RPC**: the bot only uses Helius today, but every method it calls
  (`getAccountInfo`, `simulateTransaction`, `sendTransaction`,
  `getSignatureStatuses`, `getAssetBatch`) works with any Helius-compatible
  provider that supports the DAS extension (Triton, Quicknode, Shyft).
  Swap the URL in `gib/rpc.py` if you'd rather use a different one.

## License

MIT. See [LICENSE](LICENSE).

## Contributing

PRs welcome for bug fixes and quality-of-life improvements. The maintainer
is not actively building a mobile / hosted version of this — if you want one,
fork it and ship it.
