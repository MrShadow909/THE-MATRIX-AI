"""Explicit command router; never invokes a shell or model-generated tools."""
from __future__ import annotations
import shlex
from .wallet import WatchWallet

HELP = ("Commands: help | engine status | wallet status | "
        "wallet address <PUBLIC_BTC_ADDRESS> | wallet balance. "
        "No send, signing, key import or shell execution is supported.")


def run_command(command: str, wallet: WatchWallet, engine=None):
    if not isinstance(command, str) or len(command) > 500:
        return {"ok": False, "error": "Command too long"}
    try:
        argv = shlex.split(command.strip())
    except ValueError:
        return {"ok": False, "error": "Invalid command syntax"}
    if not argv or argv == ["help"]:
        return {"ok": True, "output": HELP}
    if argv == ["wallet", "status"]:
        return {"ok": True, "output": wallet.status()}
    if argv == ["wallet", "balance"]:
        return {"ok": True, "output": wallet.balance()}
    if len(argv) == 3 and argv[:2] == ["wallet", "address"]:
        try:
            return {"ok": True, "output": wallet.set_address(argv[2])}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
    if argv == ["engine", "status"]:
        return {"ok": True, "output": engine.status() if engine else "Unavailable"}
    return {"ok": False, "error": "Command not permitted. " + HELP}
