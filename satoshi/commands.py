"""Explicit SATOSHI CLI router. No shell, private keys, signing or broadcasting."""
from __future__ import annotations

import shlex
from .wallet import WatchWallet
from .multichain import MultiChainWallet, ALL_CHAINS

HELP = ("""SATOSHI WALLET CLI (watch-only, MAINNET)
  help | engine status
  wallet status | wallet list | wallet balances
  wallet add <ALIAS> <CHAIN> <PUBLIC_ADDRESS>
  wallet remove <ALIAS> | wallet receive <ALIAS>
  wallet balance <ALIAS> | wallet tokens <SOL_ALIAS>
  wallet token <EVM_ALIAS> <ERC20_CONTRACT> <DECIMALS>
  wallet prepare <ALIAS> <RECIPIENT> <AMOUNT>  [unsigned review draft only]
  wallet address <PUBLIC_BTC_ADDRESS> | wallet balance  [legacy BTC]
Supported: """ + ", ".join(ALL_CHAINS) + "\n"
        "No send, swap, signing, seed import, private key access, or shell execution.")


def run_command(command: str, wallet: WatchWallet, engine=None, multic: MultiChainWallet | None = None):
    if not isinstance(command, str) or len(command) > 800:
        return {"ok": False, "error": "Command too long or missing"}
    try:
        argv = shlex.split(command.strip())
    except ValueError:
        return {"ok": False, "error": "Invalid command syntax"}
    if not argv or argv == ["help"]:
        return {"ok": True, "output": HELP}
    if argv == ["engine", "status"]:
        return {"ok": True, "output": engine.status() if engine else "Unavailable"}
    if not argv or argv[0] != "wallet":
        return {"ok": False, "error": "Command not permitted. Run: help"}
    multi = multic or MultiChainWallet(bitcoin_wallet=wallet)
    try:
        if argv == ["wallet", "status"]:
            return {"ok": True, "output": {**multi.status(), "legacy_btc": wallet.status()}}
        if argv == ["wallet", "list"]:
            return {"ok": True, "output": multi.list()}
        if argv == ["wallet", "balances"]:
            return {"ok": True, "output": multi.balances()}
        if len(argv) == 5 and argv[:2] == ["wallet", "add"]:
            return {"ok": True, "output": multi.add(argv[2], argv[3], argv[4])}
        if len(argv) == 3 and argv[:2] == ["wallet", "remove"]:
            return {"ok": True, "output": multi.remove(argv[2])}
        if len(argv) == 3 and argv[:2] == ["wallet", "receive"]:
            return {"ok": True, "output": multi.receive(argv[2])}
        if len(argv) == 3 and argv[:2] == ["wallet", "balance"]:
            return {"ok": True, "output": multi.balance(argv[2])}
        if argv == ["wallet", "balance"]:
            return {"ok": True, "output": wallet.balance()}
        if len(argv) == 3 and argv[:2] == ["wallet", "address"]:
            return {"ok": True, "output": wallet.set_address(argv[2])}
        if len(argv) == 3 and argv[:2] == ["wallet", "tokens"]:
            return {"ok": True, "output": multi.solana_tokens(argv[2])}
        if len(argv) == 5 and argv[:2] == ["wallet", "token"]:
            if not argv[4].isdigit():
                raise ValueError("Token decimals must be an integer")
            return {"ok": True, "output": multi.token_balance(argv[2], argv[3], int(argv[4]))}
        if len(argv) == 5 and argv[:2] == ["wallet", "prepare"]:
            return {"ok": True, "output": multi.prepare(argv[2], argv[3], argv[4])}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "Command not permitted. Run: help"}
