"""Watch-only Bitcoin wallet adapter. Never signs or broadcasts a transaction."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BC32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]


def _polymod(vals):
    chk = 1
    for v in vals:
        high = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for j in range(5):
            if (high >> j) & 1:
                chk ^= GEN[j]
    return chk


def _convertbits(data, src, dst):
    acc = bits = 0
    out = []
    for v in data:
        if v < 0 or v >> src:
            raise ValueError("Bad Bitcoin address encoding")
        acc = (acc << src) | v
        bits += src
        while bits >= dst:
            bits -= dst
            out.append((acc >> bits) & ((1 << dst) - 1))
    if bits >= src or (acc << (dst - bits)) & ((1 << dst) - 1):
        raise ValueError("Non-zero Bech32 padding")
    return bytes(out)


def address_network(address: str) -> str:
    """Validate Base58Check and segwit Bech32(m) checksums; return network."""
    if not isinstance(address, str) or len(address) > 90 or len(address) < 14:
        raise ValueError("Invalid Bitcoin address")
    if address[0] in "13mn2" and all(c in B58 for c in address):
        n = 0
        for ch in address:
            n = n * 58 + B58.index(ch)
        raw = b"\x00" * (len(address) - len(address.lstrip("1")))
        raw += n.to_bytes((n.bit_length() + 7) // 8, "big")
        if len(raw) == 25 and hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] == raw[-4:]:
            if raw[0] in (0, 5):
                return "main"
            if raw[0] in (111, 196):
                return "test"
        raise ValueError("Invalid Bitcoin Base58 checksum")
    if address.lower() != address and address.upper() != address:
        raise ValueError("Mixed-case Bitcoin address")
    val = address.lower()
    pos = val.rfind("1")
    hrp = val[:pos]
    if hrp not in ("bc", "tb", "bcrt") or pos < 1 or pos + 7 > len(val):
        raise ValueError("Unsupported Bitcoin address")
    if not all(c in BC32 for c in val[pos + 1:]):
        raise ValueError("Invalid Bech32 alphabet")
    data = [BC32.index(c) for c in val[pos + 1:]]
    chk = _polymod([ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + data)
    ver = data[0]
    if ver > 16 or chk != (1 if ver == 0 else 0x2bc830a3):
        raise ValueError("Invalid Bitcoin Bech32(m) checksum/version")
    prog = _convertbits(data[1:-6], 5, 8)
    if not 2 <= len(prog) <= 40 or (ver == 0 and len(prog) not in (20, 32)):
        raise ValueError("Invalid SegWit program")
    return {"bc": "main", "tb": "test", "bcrt": "regtest"}[hrp]


class WatchWallet:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or os.getenv("SATOSHI_WALLET_FILE") or Path.home()/".satoshi_ai"/"wallet.json")

    def address(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            candidate = data.get("public_address", "")
            address_network(candidate)
            return candidate
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def set_address(self, address: str):
        network = address_network(address)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        # Only a PUBLIC receiving address is stored. No keys or seed phrases.
        self.path.write_text(json.dumps({"public_address": address}) + "\n", encoding="utf-8")
        self.path.chmod(0o600)
        return {"address": address, "network": network, "watch_only": True}

    def status(self):
        addr = self.address()
        return {"address": addr, "network": address_network(addr) if addr else None,
                "watch_only": True, "can_sign": False, "balance_btc": None,
                "balance_verified": False}

    def balance(self):
        addr = self.address()
        if not addr:
            return {**self.status(), "reason": "Set a PUBLIC Bitcoin receiving address first"}
        url = os.getenv("SATOSHI_BITCOIN_RPC_URL", "")
        if not url:
            return {**self.status(), "reason": "Bitcoin Core RPC not configured; balance unknown"}
        parts = urlsplit(url)
        if parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost", "::1") or parts.username or parts.password:
            return {**self.status(), "reason": "Bitcoin Core RPC must use a local HTTP endpoint"}
        user, password = os.getenv("SATOSHI_BITCOIN_RPC_USER"), os.getenv("SATOSHI_BITCOIN_RPC_PASSWORD")
        if not user or not password:
            return {**self.status(), "reason": "Bitcoin Core RPC credentials not configured"}

        def rpc(method, params):
            body = json.dumps({"jsonrpc": "1.0", "id": "satoshi-readonly", "method": method, "params": params}).encode()
            auth = base64.b64encode(f"{user}:{password}".encode()).decode()
            req = Request(url, body, headers={"Content-Type": "application/json", "Authorization": "Basic " + auth})
            with urlopen(req, timeout=30) as response:
                result = json.load(response)
            if result.get("error"):
                raise RuntimeError("Bitcoin Core RPC rejected read-only query")
            return result["result"]
        try:
            info = rpc("getblockchaininfo", [])
            network = address_network(addr)
            chain = info["chain"]
            expected = {"main": {"main"}, "test": {"test", "testnet4", "signet"}, "regtest": {"regtest"}}
            if chain not in expected[network]:
                return {**self.status(), "reason": "Bitcoin Core chain differs from receiving address network"}
            scanned = rpc("scantxoutset", ["start", [f"addr({addr})"]])
            if not scanned.get("success"):
                return {**self.status(), "reason": "UTXO scan not completed"}
            return {**self.status(), "balance_btc": str(Decimal(str(scanned["total_amount"]))),
                    "balance_verified": True, "chain": chain,
                    "note": "Confirmed unspent outputs on the connected node; pending transactions excluded"}
        except Exception:
            return {**self.status(), "reason": "Bitcoin Core RPC unavailable or scan failed"}
