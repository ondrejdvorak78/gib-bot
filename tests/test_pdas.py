"""Verify PDA derivations against a real mainnet register_to_tournament tx.

Tx: 2BhPioKThCtYuiMrNxKLuuLk4tUcUS8cRHyR7gNARK1GNGWeKix3SuRJCDwGU6GCiMu52Aiv7s7qZtdSmdPRP3K1
Tournament index: 71
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gib import pdas


CREATOR = "8Dn6vs56fX9MWbbcLKX39jvwvjkSJakjoEsVCb6EqmKS"

EXPECTED = {
    "binder":       ("8uhLJUCVLrtoYbfzixQp4Pyf1otn9FEMTc4oo91Unqxw", 254),
    "user_track":   ("6vJLspUHFwiMKc8yVVEBKHJ4mbbbW9GA6onWnhtdjGc8", 255),
    "notification": ("4iCtLBxdJBWdqC9gBYC9GtV7DhPh8um5WXx9qRwXxUPc", 255),
    "tournament71": ("7GRa49VUSyUZKSd6ZWC7111ncZhCmoBSRwrJst7C7XQt", 255),
}


def main() -> int:
    results = [
        ("binder",       pdas.binder_pda(CREATOR),         EXPECTED["binder"]),
        ("user_track",   pdas.user_track_pda(CREATOR),     EXPECTED["user_track"]),
        ("notification", pdas.notification_track_pda(),    EXPECTED["notification"]),
        ("tournament71", pdas.tournament_pda(71),          EXPECTED["tournament71"]),
    ]
    ok = True
    for name, got, want in results:
        mark = "✅" if got == want else "❌"
        print(f"  {mark} {name:14s}  {got[0]}  bump={got[1]}")
        if got != want:
            print(f"     expected {want[0]}  bump={want[1]}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
