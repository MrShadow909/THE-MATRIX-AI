"""SATOSHI multi-chain public-address book, read-only RPCs and unsigned payment drafts.

No key import, signing, transaction broadcast, trading or subprocess support.
Only public addresses are persisted. Network endpoints are supplied locally through
SATOSHI_*_RPC_URL environment variables (never from chatbot or HTTP parameters).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .wallet import B58, WatchWallet, address_network

# Immutable mainnet definitions: (native symbol, chain ID, env variable)
EVM_CHAINS = {
    "ethereum": ("ETH", 1, "SATOSHI_ETHEREUM_RPC_URL"),
    "polygon": ("POL", 137, "SATOSHI_POLYGON_RPC_URL"),
    "base": ("ETH", 8453, "SATOSHI_BASE_RPC_URL"),
    "arbitrum": ("ETH", 42161, "SATOSHI_ARBITRUM_RPC_URL"),
    "optimism": ("ETH", 10, "SATOSHI_OPTIMISM_RPC_URL"),
    "bsc": ("BNB", 56, "SATOSHI_BSC_RPC_URL"),
}
SOLANA_MAINNET_GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
SOLANA_TOKEN_PROGRAMS = (
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
)
ALL_CHAINS = ("bitcoin", *EVM_CHAINS, "solana")
MAX_RESPONSE = 512_000


def _rot(v: int, n: int) -> int:
    m = (1 << 64) - 1
    return ((v << n) | (v >> (64 - n))) & m if n else v & m


def keccak256(data: bytes) -> bytes:
    """Small dependency-free Keccak-256 for EIP-55 (not SHA3-256)."""
    # Keccak-f[1600] round constants and rho rotation offsets.
    rc = (
        0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
        0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
        0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
        0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
        0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
        0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
        0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
        0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
    )
    rho = (
        (0, 36, 3, 41, 18), (1, 44, 10, 45, 2),
        (62, 6, 43, 15, 61), (28, 55, 25, 21, 56),
        (27, 20, 39, 8, 14),
    )
    rate = 136
    pad = bytearray(data)
    pad.append(1)  # Keccak padding, *not* FIPS SHA3 suffix 0x06.
    while len(pad) % rate:
        pad.append(0)
    pad[-1] ^= 0x80
    st = [0] * 25
    mask = (1 << 64) - 1
    for at in range(0, len(pad), rate):
        block = pad[at:at + rate]
        for i in range(rate // 8):
            st[i] ^= int.from_bytes(block[8 * i:8 * (i + 1)], "little")
        for k in rc:
            col = [st[x] ^ st[x+5] ^ st[x+10] ^ st[x+15] ^ st[x+20] for x in range(5)]
            delta = [col[(x - 1) % 5] ^ _rot(col[(x + 1) % 5], 1) for x in range(5)]
            for y in range(5):
                for x in range(5):
                    st[x + 5*y] ^= delta[x]
            b = [0] * 25
            for y in range(5):
                for x in range(5):
                    b[y + 5*((2*x + 3*y) % 5)] = _rot(st[x + 5*y], rho[x][y])
            for y in range(5):
                for x in range(5):
                    st[x + 5*y] = (b[x + 5*y] ^ ((~b[(x + 1) % 5 + 5*y]) & b[(x + 2) % 5 + 5*y])) & mask
            st[0] ^= k
    return b"".join(st[i].to_bytes(8, "little") for i in range(4))


def evm_address(address: str) -> str:
    if not isinstance(address, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
        raise ValueError("Expected an EVM 0x address with exactly 40 hexadecimal digits")
    raw = address[2:]
    if not (raw.islower() or raw.isupper()):
        check = keccak256(raw.lower().encode("ascii")).hex()
        expected = "".join(c.upper() if int(check[i], 16) >= 8 else c.lower() for i, c in enumerate(raw.lower()))
        if raw != expected:
            raise ValueError("Invalid EIP-55 mixed-case checksum")
    return address


def solana_address(address: str) -> str:
    if not isinstance(address, str) or not (32 <= len(address) <= 44) or any(c not in B58 for c in address):
        raise ValueError("Invalid Solana public address")
    value = 0
    for c in address:
        value = value * 58 + B58.index(c)
    raw = b"\x00" * (len(address) - len(address.lstrip("1")))
    if value:
        raw += value.to_bytes((value.bit_length() + 7) // 8, "big")
    if len(raw) != 32:
        raise ValueError("Solana public key must decode to 32 bytes")
    return address


def validate_address(chain: str, address: str) -> str:
    if chain == "bitcoin":
        return address_network(address)
    if chain == "solana":
        solana_address(address)
        return "mainnet-beta"
    if chain in EVM_CHAINS:
        evm_address(address)
        return "mainnet"
    raise ValueError("Unknown chain. Choose: " + ", ".join(ALL_CHAINS))


def _rpc_url(environment: str) -> str | None:
    url = os.environ.get(environment, "").strip()
    if not url:
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.username or parsed.password or parsed.fragment or not parsed.hostname
                or parsed.scheme not in ("http", "https")):
            raise ValueError
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
    except ValueError as exc:
        raise RuntimeError("RPC URL must use HTTPS or loopback HTTP, without embedded credentials") from exc
    return url


def _rpc(url: str, method: str, params: list):
    """Read-only, local-operator-selected JSON RPC; no arbitrary RPC methods."""
    allowed = {"eth_chainId", "eth_getBalance", "eth_call", "getGenesisHash", "getBalance", "getTokenAccountsByOwner"}
    if method not in allowed:
        raise ValueError("RPC method not permitted")
    payload = json.dumps({"jsonrpc": "2.0", "id": "satoshi-watch", "method": method, "params": params}).encode()
    req = Request(url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "SATOSHI-watch-only/0.2"})
    with urlopen(req, timeout=10) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise RuntimeError("RPC response too large")
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("error") or "result" not in data:
        raise RuntimeError("RPC returned an error")
    return data["result"]


def _precision_amount(amount: str, decimals: int) -> tuple[str, int]:
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", amount):
        raise ValueError("Amount must be a positive decimal number (no exponent)")
    try:
        dec = Decimal(amount)
        if not dec.is_finite() or not (Decimal(0) < dec < Decimal("1e30")):
            raise ValueError("Amount must be positive and bounded")
        atoms = dec * (10 ** decimals)
        if atoms != atoms.to_integral_value():
            raise ValueError(f"Amount exceeds {decimals} decimal places")
        return format(dec, "f"), int(atoms)
    except InvalidOperation as exc:
        raise ValueError("Invalid amount") from exc


class MultiChainWallet:
    def __init__(self, path: Path | None = None, bitcoin_wallet: WatchWallet | None = None):
        self.path = Path(path or os.getenv("SATOSHI_MULTICHAIN_FILE") or Path.home()/".satoshi_ai"/"wallets.json")
        self.bitcoin_wallet = bitcoin_wallet or WatchWallet()

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("wallets"), dict):
                return {}
            # Do not return arbitrary stale input as trusted entries.
            return {k: v for k, v in raw["wallets"].items()
                    if isinstance(k, str) and re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,23}", k)
                    and isinstance(v, dict) and isinstance(v.get("chain"), str)
                    and isinstance(v.get("address"), str)
                    and self._valid_entry(v)}
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def _valid_entry(v):
        try:
            validate_address(v["chain"], v["address"])
            return True
        except ValueError:
            return False

    def _write(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.path.parent.chmod(0o700)
        # atomic replace to avoid corruption after crashes
        name = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=str(self.path.parent), encoding="utf-8", delete=False) as tmp:
                name = tmp.name
                json.dump({"version": 2, "wallets": records}, tmp, indent=2, ensure_ascii=False)
                tmp.write("\n")
                tmp.flush()
                os.fsync(tmp.fileno())
            if os.name != "nt":
                os.chmod(name, 0o600)
            os.replace(name, self.path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def list(self):
        rows = [{"alias": k, "chain": v["chain"], "address": v["address"], "watch_only": True}
                for k, v in sorted(self._load().items())]
        # Legacy BTC address from the original SATOSHI v0.1 stays available.
        btc = self.bitcoin_wallet.address()
        if btc and "btc" not in self._load():
            rows.insert(0, {"alias": "btc", "chain": "bitcoin", "address": btc, "watch_only": True, "legacy": True})
        return {"wallets": rows, "count": len(rows), "can_sign": False, "can_broadcast": False}

    def add(self, alias: str, chain: str, address: str):
        if not isinstance(alias, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,23}", alias):
            raise ValueError("Alias: 1–24 chars, starts with a letter; alphanumerics, _ or -")
        chain = chain.lower()
        network = validate_address(chain, address)
        records = self._load()
        if alias in records or (alias == "btc" and self.bitcoin_wallet.address()):
            raise ValueError("Alias already exists; remove it explicitly before replacing")
        if len(records) >= 25:
            raise ValueError("Maximum 25 tracked addresses")
        records[alias] = {"chain": chain, "address": address}
        self._write(records)
        return {"alias": alias, "chain": chain, "network": network, "address": address, "watch_only": True}

    def remove(self, alias: str):
        records = self._load()
        if alias not in records:
            raise ValueError("Alias not found in multi-chain address book")
        del records[alias]
        self._write(records)
        return {"alias": alias, "removed": True, "funds_affected": False}

    def _entry(self, alias: str):
        records = self._load()
        if alias in records:
            return records[alias]
        if alias == "btc" and self.bitcoin_wallet.address():
            return {"chain": "bitcoin", "address": self.bitcoin_wallet.address()}
        raise ValueError("Unknown wallet alias. Use: wallet list")

    def receive(self, alias: str):
        entry = self._entry(alias)
        return {"alias": alias, "chain": entry["chain"], "address": entry["address"],
                "network": validate_address(entry["chain"], entry["address"]),
                "warning": "Share only this public address; verify network and token compatibility before deposits"}

    def status(self):
        result = self.list()
        result["supported_chains"] = list(ALL_CHAINS)
        result["mode"] = "watch-only"
        result["balance_verified"] = False
        return result

    def balance(self, alias: str):
        entry = self._entry(alias)
        chain, address = entry["chain"], entry["address"]
        result = {"alias": alias, "chain": chain, "address": address, "watch_only": True,
                  "balance": None, "balance_verified": False}
        if chain == "bitcoin":
            btc = self.bitcoin_wallet.balance(address)
            return {**result, "symbol": "BTC", "balance": btc.get("balance_btc"),
                    "balance_verified": btc.get("balance_verified", False), "reason": btc.get("reason")}
        if chain in EVM_CHAINS:
            symbol, chain_id, var = EVM_CHAINS[chain]
            result["symbol"] = symbol
            try:
                url = _rpc_url(var)
                if not url:
                    return {**result, "reason": f"Configure {var} locally"}
                if int(_rpc(url, "eth_chainId", []), 16) != chain_id:
                    return {**result, "reason": "RPC returned wrong chain ID; balance not trusted"}
                wei = int(_rpc(url, "eth_getBalance", [address, "latest"]), 16)
                if wei < 0:
                    raise ValueError
                return {**result, "balance": str(Decimal(wei)/Decimal(10**18)),
                        "balance_verified": True, "chain_id": chain_id, "block": "latest",
                        "note": "Native token only; pending transactions not included"}
            except Exception:
                return {**result, "reason": "RPC unavailable or invalid response; balance unknown"}
        result["symbol"] = "SOL"
        try:
            url = _rpc_url("SATOSHI_SOLANA_RPC_URL")
            if not url:
                return {**result, "reason": "Configure SATOSHI_SOLANA_RPC_URL locally"}
            if _rpc(url, "getGenesisHash", []) != SOLANA_MAINNET_GENESIS:
                return {**result, "reason": "Solana RPC is not mainnet-beta; balance not trusted"}
            data = _rpc(url, "getBalance", [address, {"commitment": "confirmed"}])
            lamports = data["value"]
            if type(lamports) is not int or lamports < 0:
                raise ValueError
            return {**result, "balance": str(Decimal(lamports)/Decimal(10**9)),
                    "balance_verified": True, "network": "mainnet-beta", "commitment": "confirmed"}
        except Exception:
            return {**result, "reason": "Solana RPC unavailable or invalid response; balance unknown"}

    def inspect_public_solana(self, address: str):
        """Read a connected Phantom public address, without saving it.

        The user-configured RPC must match Solana mainnet-beta. No wallet
        credentials, user-supplied RPC URLs, signing or broadcasting accepted.
        """
        solana_address(address)
        result = {"chain": "solana", "network": "mainnet-beta", "address": address,
                  "symbol": "SOL", "balance": None, "balance_verified": False,
                  "watch_only": True, "source": "local_operator_rpc"}
        try:
            url = _rpc_url("SATOSHI_SOLANA_RPC_URL")
            if not url:
                return {**result, "reason": "Configure SATOSHI_SOLANA_RPC_URL locally"}
            if _rpc(url, "getGenesisHash", []) != SOLANA_MAINNET_GENESIS:
                return {**result, "reason": "RPC is not Solana mainnet-beta"}
            data = _rpc(url, "getBalance", [address, {"commitment": "confirmed"}])
            lamports = data["value"]
            if type(lamports) is not int or lamports < 0:
                raise ValueError("Invalid lamports")
            return {**result, "balance": str(Decimal(lamports) / Decimal(10**9)),
                    "balance_verified": True, "commitment": "confirmed"}
        except Exception:
            return {**result, "reason": "Solana RPC unavailable or invalid response"}

    def balances(self):
        return {"balances": [self.balance(e["alias"]) for e in self.list()["wallets"]],
                "note": "Balances are per-asset and cannot be summed without trusted pricing data"}

    def token_balance(self, alias: str, contract: str, decimals: int):
        """Read any ERC-20 balanceOf; supplied decimals are not authenticated."""
        entry = self._entry(alias)
        chain = entry["chain"]
        if chain not in EVM_CHAINS:
            raise ValueError("ERC-20 token balance is available only for EVM networks")
        evm_address(contract)
        if not isinstance(decimals, int) or not 0 <= decimals <= 36:
            raise ValueError("Decimals must be 0–36; confirm them from an official token source")
        out = {"alias": alias, "chain": chain, "token_contract": contract,
               "token_decimals_supplied": decimals, "balance": None, "balance_verified": False}
        try:
            _, expected_chain_id, var = EVM_CHAINS[chain]
            url = _rpc_url(var)
            if not url:
                return {**out, "reason": f"Configure {var} locally"}
            if int(_rpc(url, "eth_chainId", []), 16) != expected_chain_id:
                return {**out, "reason": "Wrong RPC chain ID"}
            encoded_call = "0x70a08231" + entry["address"][2:].lower().rjust(64, "0")
            response = _rpc(url, "eth_call", [{"to": contract, "data": encoded_call}, "latest"])
            if not isinstance(response, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", response):
                raise ValueError
            atoms = int(response, 16)
            return {**out, "balance": str(Decimal(atoms) / Decimal(10 ** decimals)),
                    "balance_verified": True, "chain_id": expected_chain_id,
                    "warning": "Contract and decimals are user-supplied; token identity and authenticity are NOT verified"}
        except Exception:
            return {**out, "reason": "RPC unavailable, invalid token contract, or invalid response"}

    def solana_tokens(self, alias: str):
        """Read SPL Token and Token-2022 holdings, excluding confidential amounts."""
        entry = self._entry(alias)
        if entry["chain"] != "solana":
            raise ValueError("This command is only for Solana wallets")
        out = {"alias": alias, "chain": "solana", "tokens": [], "balance_verified": False}
        try:
            url = _rpc_url("SATOSHI_SOLANA_RPC_URL")
            if not url:
                return {**out, "reason": "Configure SATOSHI_SOLANA_RPC_URL locally"}
            if _rpc(url, "getGenesisHash", []) != SOLANA_MAINNET_GENESIS:
                return {**out, "reason": "Solana RPC is not mainnet-beta"}
            collected = {}
            for program in SOLANA_TOKEN_PROGRAMS:
                info = _rpc(url, "getTokenAccountsByOwner", [entry["address"], {"programId": program},
                                                                 {"encoding": "jsonParsed", "commitment": "confirmed"}])
                if not isinstance(info, dict) or not isinstance(info.get("value"), list):
                    raise ValueError
                for row in info["value"]:
                    token = row["account"]["data"]["parsed"]["info"]
                    mint, bal = token["mint"], token["tokenAmount"]
                    solana_address(mint)
                    atoms, decimals = int(bal["amount"]), int(bal["decimals"])
                    if not 0 <= decimals <= 36 or atoms < 0:
                        raise ValueError
                    if mint not in collected:
                        collected[mint] = [0, decimals]
                    if collected[mint][1] != decimals:
                        raise ValueError
                    collected[mint][0] += atoms
            tokens = [{"mint": m, "amount": str(Decimal(a)/Decimal(10**d)), "decimals": d}
                      for m, (a, d) in sorted(collected.items()) if a]
            return {**out, "tokens": tokens[:100], "balance_verified": True,
                    "note": "Only public token-account amounts; token identity and price are not verified"}
        except Exception:
            return {**out, "reason": "Solana token RPC unavailable or unsupported response"}

    def prepare(self, alias: str, destination: str, amount: str):
        """Unsigned, in-memory review draft; not executable, no persistence."""
        entry = self._entry(alias)
        chain = entry["chain"]
        if chain in EVM_CHAINS:
            evm_address(destination)
            if int(destination[2:], 16) == 0:
                raise ValueError("Zero destination is prohibited")
            symbol, chain_id, _ = EVM_CHAINS[chain]
            decimals = 18
            network = {"chain_id": chain_id}
        elif chain == "solana":
            solana_address(destination)
            if destination == "11111111111111111111111111111111":
                raise ValueError("System address is not a valid recipient")
            symbol, decimals, network = "SOL", 9, {"network": "mainnet-beta"}
        elif chain == "bitcoin":
            network_id = address_network(destination)
            if network_id != address_network(entry["address"]):
                raise ValueError("Bitcoin recipient network does not match sender")
            symbol, decimals, network = "BTC", 8, {"network": network_id}
        else:
            raise ValueError("Unsupported chain")
        human, base_units = _precision_amount(amount, decimals)
        if destination.lower() == entry["address"].lower():
            raise ValueError("Self-transfer draft rejected")
        return {"type": "UNSIGNED_TRANSFER_PROPOSAL", "alias": alias, "chain": chain, "asset": symbol,
                "sender": entry["address"], "recipient": destination, "amount": human,
                "base_units": str(base_units), **network,
                "fee_estimated": False, "balance_checked": False, "transaction_built": False,
                "signed": False, "broadcast": False,
                "next_step": "Open your independent wallet, review network/recipient/amount/fees, then sign manually. SATOSHI cannot sign or send."}
