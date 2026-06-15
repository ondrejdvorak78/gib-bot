# gib-bot (fork)

A local tool for [gib.meme](https://gib.meme) players that automates the
tedious part of tournament prep: building decks from your binder and
submitting them all in one Phantom approval flow instead of clicking through
one popup per deck.

This is a fork of [ForWakanda/gib-bot](https://github.com/ForWakanda/gib-bot).
See [CHANGES.md](CHANGES.md) for the diff. The upstream's behavior, CLI,
and design are preserved; this fork tightens correctness + robustness +
local-network security. Adopt if any of these matter to you:

- **Lookup-table compatibility** as gib.meme rotates its client (the
  upstream pin is one ALT version behind).
- **State-claim discipline** — under reorg or expired-blockhash conditions
  the upstream silently believed it had landed transactions that never did.
- **LAN security** — upstream bound the Phantom-signing bridge to
  `0.0.0.0`; this fork binds `127.0.0.1` by default.
- **Tournament-window race** — the upstream's submit cascade did not
  re-check the active tournament between retry passes.

If you depend on the upstream behavior exactly, do not adopt this fork.

The bot does **not** try to be smart about deck construction. It uses a
power-descending strategy: sorts your available cards by raw power (the
same value gib.meme shows on each card) and fills decks of 3 unique-meme
cards from strongest down. It submits every deck it can build, regardless
of how many cards you have.

If you have your own strategy for specific decks, **submit those decks
manually on gib.meme FIRST**, then run the bot to fill in everything else.
The bot re-checks on-chain state before each pass and automatically skips
cards that are already registered in the tournament, so your manual picks
won't be touched or duplicated.

If you'd rather automate a different ordering, edit `state/plan.json`
between `plan` and `submit`, or fork this and write your own scorer.

## What it actually saves you

- Reads your binder on-chain in one call instead of you scrolling through
  the in-game UI to see what's available.
- Builds and pre-simulates every deck transaction before signing — txs that
  would revert get skipped automatically.
- Batches signing through Phantom's `signAllTransactions` so you confirm
  20-25 decks per popup instead of one at a time.
- Auto-retries failures at smaller batch sizes (25 -> 10 -> 5 -> 3 -> 1).
- Re-checks on-chain state between retries so it never re-submits a deck
  that just landed.

## Before you start

Have these ready before installing — the install steps assume them:

- **A Solana wallet with the Phantom extension installed.** You'll need your
  wallet's **public address** (the long string Phantom shows when you click
  your account name and pick "Copy address" — also called your "pubkey").
- **gib.meme cards deposited in your binder.** Cards sitting loose in your
  wallet are not eligible for tournaments — they have to be in the binder.
  Deposit at least one card via the gib.meme UI first; that creates the
  per-user account the bot reads from and writes to. (After that, the
  `deposit` command below can move the rest in bulk.)
- **A free [Helius](https://helius.dev) API key.** Sign up, create a
  project, and copy the **API key** (the long alphanumeric string), not
  the project ID. The free tier is plenty — a full submit uses well under
  1k credits even for a large binder, and Helius free is 1M/month.
- **Chrome (or any Phantom-compatible browser).** Phantom mobile also works
  if you can open `http://localhost:8787` on the same device.

## Windows quickstart

If you don't already have a Python dev setup on Windows, install these two
once (skip if you already have them):

1. **Python 3.12, 64-bit** from
   [python.org/downloads](https://www.python.org/downloads/). On the very
   first install screen, **check the box "Add python.exe to PATH"** — if
   you miss this, every command below will fail with "python is not
   recognized."
2. **Git for Windows** from
   [git-scm.com/download/win](https://git-scm.com/download/win). Accept all
   default options. This installs **Git Bash**, the terminal you'll use to
   run the commands below.

Then open **Git Bash** (search "Git Bash" in the Start menu) and run:

```bash
git clone https://github.com/<your-username>/gib-bot.git
cd gib-bot
./setup.bat
```

The setup script creates a Python virtual environment, installs
dependencies, and opens `.env` in Notepad. Paste in your Helius API key
and wallet pubkey, then save and close Notepad.

From now on, **every time you want to run the bot**, open Git Bash,
`cd` to the `gib-bot` folder, and activate the venv first:

```bash
source .venv/Scripts/activate
```

Your prompt will start with `(.venv)`. Then run any command from the
[Usage](#usage) section below.

## macOS / Linux quickstart

```bash
git clone https://github.com/<your-username>/gib-bot.git
cd gib-bot
./setup.sh
```

The setup script creates a virtual environment, installs dependencies,
and opens `.env` in your default editor. Paste in your Helius API key
and wallet pubkey, save, and close.

Before running the bot, activate the venv:

```bash
source .venv/bin/activate
```

Then run any command from the [Usage](#usage) section below.

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

## Optional commands

```bash
# Move loose gib.meme cards from your wallet INTO your binder so they're
# eligible for tournaments. One tx per card; requires you've previously
# deposited at least one card via the gib.meme UI (that creates the per-user
# account the bot needs).
python cli.py deposit

# Submit but don't auto-retry at smaller batch sizes.
python cli.py submit --no-retry

# Override the tournament index if auto-detection picks the wrong one.
python cli.py plan --tournament 84
python cli.py submit --tournament 84
```

## Troubleshooting

- **`python` is not recognized / command not found** (Windows): Python
  isn't on your PATH. Reinstall Python and tick **"Add python.exe to
  PATH"** on the first install screen.
- **`pip install` fails with compiler / build errors**: confirm you're on
  Python 3.12 by running `python --version`. Older or very new Python
  versions may not have prebuilt wheels for every dependency.
- **`source .venv/Scripts/activate` does nothing or errors** (Windows):
  you're in the wrong terminal. Use **Git Bash**, not CMD or PowerShell.
  If you must use CMD, run `.venv\Scripts\activate.bat` instead.
- **`401 Unauthorized` from RPC**: wrong Helius key in `.env`. In the
  Helius dashboard, copy the **API key** (long alphanumeric string), not
  the project ID, not the full RPC URL.
- **Phantom popup never appears when running `submit`**: the browser
  blocked the popup, or the browser tab isn't focused. Click into the
  localhost page in your browser, then re-click "Connect Wallet."
- **`WALLET` empty / wrong wallet**: double-check `.env`. The pubkey goes
  on the `WALLET=` line, no quotes, no spaces, no trailing characters.
- **Port 8787 already in use**: another program is using it. Either close
  that program, or pass `--port 8788` to `submit` / `deposit`.
- **`blockhash not found` at submit (NEW in this fork)**: you clicked the
  Phantom approval more than ~60-90 seconds after the chunk was built. The
  blockhash window expired. Re-run `submit`; the bot builds a fresh
  blockhash for each cascade pass.
- **`tournament window changed mid-cascade` (NEW in this fork)**: gib.meme
  transitioned to a new tournament while the bot was mid-submit. Re-run
  with the printed `--tournament <N>` hint to retarget.

## How submission works

1. `plan` writes `state/plan.json` — one entry per deck with the binder slot
   indices it contains. You can edit this file by hand to swap cards.
2. `submit` reads `plan.json`, builds a signed-tx-per-deck against a fresh
   blockhash, and opens `http://localhost:8787` in your browser.
3. The page connects to Phantom, fetches transactions from the bridge in
   chunks of 25, asks Phantom to sign them all at once (one popup per chunk),
   sends them in parallel, and reports per-tx success or error.
4. If anything failed, it retries at smaller chunk sizes (10 -> 5 -> 3 -> 1)
   re-reading on-chain state between passes so already-landed decks are
   skipped.

## Limitations and disclaimers

- **No warranty.** The on-chain gib.meme program could change; the
  gib.meme stats API could change; this bot could break silently. Always
  watch the first few txs land before walking away from a large submit.
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

PRs welcome for bug fixes and quality-of-life improvements. Upstream is
[ForWakanda/gib-bot](https://github.com/ForWakanda/gib-bot); consider
opening upstream PRs there too where the fix is broadly applicable.
