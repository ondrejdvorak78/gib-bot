"""Verify register_to_tournament instruction encoding against the real mainnet tx.

Tx 2BhPio... registered cards [36, 141, 161] into deck slot 0 of tournament 71.
The raw ix data was base58 "MtFPnpFAqaSJYAQGQBdNs5X7U9M" which decodes to:
    19d84691f01e600b   disc
    0000               u16 index = 0
    03000000           u32 vec len = 3
    2400               u16 = 36
    8d00               u16 = 141
    a100               u16 = 161
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gib import config, tx


CREATOR = "8Dn6vs56fX9MWbbcLKX39jvwvjkSJakjoEsVCb6EqmKS"
EXPECTED_DATA_HEX = "19d84691f01e600b00000300000024008d00a100"

# Account order and values from the decoded tx.
EXPECTED_ACCOUNTS = [
    ("8uhLJUCVLrtoYbfzixQp4Pyf1otn9FEMTc4oo91Unqxw", False, True),   # binder
    ("6vJLspUHFwiMKc8yVVEBKHJ4mbbbW9GA6onWnhtdjGc8", False, True),   # user_track
    ("7GRa49VUSyUZKSd6ZWC7111ncZhCmoBSRwrJst7C7XQt", False, True),   # tournament (71)
    ("BYYdh3UjeKF1Gfjb4vy2JJhjTUoQxKZ62mP9z5YA9Aou", False, True),   # board
    ("8Dn6vs56fX9MWbbcLKX39jvwvjkSJakjoEsVCb6EqmKS", True,  True),   # creator (signer)
    ("11111111111111111111111111111111",             False, False),  # system program
    ("4iCtLBxdJBWdqC9gBYC9GtV7DhPh8um5WXx9qRwXxUPc", False, False),  # notification_track
]


def main() -> int:
    ix = tx.build_register_to_tournament(
        creator=CREATOR,
        tournament_index=71,
        deck_index=0,
        cards=[36, 141, 161],
    )

    ok = True

    # data check
    got_hex = ix.data.hex()
    mark = "✅" if got_hex == EXPECTED_DATA_HEX else "❌"
    print(f"  {mark} ix.data  {got_hex}")
    if got_hex != EXPECTED_DATA_HEX:
        print(f"     expected {EXPECTED_DATA_HEX}")
        ok = False

    # program id check
    mark = "✅" if ix.program_id == config.PROGRAM_ID else "❌"
    print(f"  {mark} program  {ix.program_id}")
    if ix.program_id != config.PROGRAM_ID:
        ok = False

    # account check
    print("  accounts:")
    for i, (want_pk, want_signer, want_writable) in enumerate(EXPECTED_ACCOUNTS):
        got = ix.accounts[i]
        pk_ok   = got.pubkey == want_pk
        sig_ok  = got.is_signer == want_signer
        wr_ok   = got.is_writable == want_writable
        all_ok  = pk_ok and sig_ok and wr_ok
        mark = "✅" if all_ok else "❌"
        flags = ("s" if got.is_signer else "-") + ("w" if got.is_writable else "-")
        print(f"    {mark} [{i}] {got.pubkey}  {flags}")
        if not all_ok:
            exp_flags = ("s" if want_signer else "-") + ("w" if want_writable else "-")
            print(f"       expected {want_pk}  {exp_flags}")
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
