"""Wallet CLI: python -m satoshi.wallet_cli [status|list|add|balance|...]"""
import json
import shlex
import sys
from .commands import run_command
from .wallet import WatchWallet


def main():
    args = sys.argv[1:] or ["help"]
    if args in (["--help"], ["-h"]):
        args = ["help"]
    if args[0] in {"status", "list", "balance", "balances", "address", "add", "remove", "receive", "prepare", "tokens", "token"}:
        args = ["wallet", *args]
    result = run_command(shlex.join(args), WatchWallet())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
