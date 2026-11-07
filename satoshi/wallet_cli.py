"""Use: python -m satoshi.wallet_cli status|address ADDRESS|balance"""
import json
import sys
from .commands import run_command
from .wallet import WatchWallet


def main():
    args = sys.argv[1:]
    if not args or args == ["--help"]:
        args = ["help"]
    if args[0] == "status":
        args = ["wallet", "status"]
    elif args[0] == "balance":
        args = ["wallet", "balance"]
    elif args[0] == "address":
        args = ["wallet", *args]
    result = run_command(" ".join(args), WatchWallet())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
