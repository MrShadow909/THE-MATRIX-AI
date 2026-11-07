"""Offline safety and capability tests for SATOSHI multichain watch-only CLI."""
import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from satoshi.commands import run_command
from satoshi.multichain import (
    MultiChainWallet, evm_address, keccak256, solana_address,
    SOLANA_MAINNET_GENESIS,
)
from satoshi.wallet import WatchWallet

BTC = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
EVM = "0x52908400098527886E0F7030069857D2E4169EE7"
EVM_OTHER = "0xde709f2102306220921060314715629080e2fb77"
SOL = "So11111111111111111111111111111111111111112"
SOL_2 = "83astBRguLMdt2h5U1Tpdq5tjFoJ6noeGwaY3mDLVcri"


class TestValidation(unittest.TestCase):
    def test_keccak_and_eip55(self):
        self.assertEqual(keccak256(b"").hex(), "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")
        self.assertEqual(evm_address(EVM), EVM)
        self.assertEqual(evm_address("0x5A384227B65FA093DEC03Ec34e111Db80A040615"), "0x5A384227B65FA093DEC03Ec34e111Db80A040615")
        with self.assertRaises(ValueError):
            evm_address("0x5A384227B65FA093DEC03Ec34e111Db80A040614")
        with self.assertRaises(ValueError):
            evm_address("0x1234")

    def test_solana_public_key_decoding(self):
        self.assertEqual(solana_address(SOL), SOL)
        self.assertEqual(solana_address(SOL_2), SOL_2)
        self.assertEqual(solana_address("11111111111111111111111111111111"), "11111111111111111111111111111111")
        for invalid in ["solana123", "0x123456", "O"*43, "1"*33]:
            with self.assertRaises(ValueError):
                solana_address(invalid)


class TestMultiChain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.btc = WatchWallet(Path(self.tmp.name) / "btc.json")
        self.wallet = MultiChainWallet(Path(self.tmp.name) / "multi.json", self.btc)

    def cli(self, s):
        return run_command(s, self.btc, multic=self.wallet)

    def test_add_list_remove_persist_public_only(self):
        self.assertTrue(self.cli(f"wallet add eth1 ethereum {EVM}")["ok"])
        self.assertTrue(self.cli(f"wallet add sol1 solana {SOL}")["ok"])
        self.assertTrue(self.cli(f"wallet add poly polygon {EVM}")["ok"])
        self.assertEqual(self.wallet.list()["count"], 3)
        self.assertEqual(MultiChainWallet(self.wallet.path, self.btc).list()["count"], 3)
        content = self.wallet.path.read_text()
        self.assertNotIn("private", content)
        self.assertNotIn("seed", content)
        self.assertFalse(self.cli(f"wallet add eth1 base {EVM}")["ok"])
        self.assertFalse(self.cli(f"wallet add bad-! base {EVM}")["ok"])
        self.assertFalse(self.cli(f"wallet add eth2 dogecoin {EVM}")["ok"])
        self.assertTrue(self.cli("wallet remove eth1")["ok"])
        self.assertEqual(self.wallet.list()["count"], 2)
        self.assertTrue(self.cli("wallet receive sol1")["ok"])
        self.assertEqual(self.cli("wallet receive sol1")["output"]["address"], SOL)

    def test_legacy_bitcoin_address_still_available(self):
        self.btc.set_address(BTC)
        self.assertEqual(self.wallet.list()["wallets"][0]["alias"], "btc")
        self.assertTrue(self.cli("wallet balance btc")["ok"])
        self.assertFalse(self.cli("wallet remove btc")["ok"])
        self.wallet.add("btcsecond", "bitcoin", BTC)
        with patch.dict(os.environ, {"SATOSHI_BITCOIN_RPC_URL": ""}):
            info = self.wallet.balance("btcsecond")
        self.assertIsNone(info["balance"])
        self.assertFalse(info["balance_verified"])

    def test_failed_unknown_balance_never_fabricated(self):
        self.wallet.add("eth1", "ethereum", EVM)
        with patch.dict(os.environ, {"SATOSHI_ETHEREUM_RPC_URL": ""}):
            result = self.wallet.balance("eth1")
        self.assertIsNone(result["balance"])
        self.assertFalse(result["balance_verified"])
        self.assertIn("SATOSHI_ETHEREUM_RPC_URL", result["reason"])

    def test_evm_network_identity_and_balance(self):
        self.wallet.add("eth1", "ethereum", EVM)
        with patch.dict(os.environ, {"SATOSHI_ETHEREUM_RPC_URL": "https://rpc.example.org"}):
            with patch("satoshi.multichain._rpc", side_effect=["0x1", "0xde0b6b3a7640000"]) as rpc:
                data = self.wallet.balance("eth1")
            self.assertEqual(data["balance"], "1")
            self.assertTrue(data["balance_verified"])
            self.assertEqual(rpc.call_count, 2)
            with patch("satoshi.multichain._rpc", return_value="0x89") as rpc:
                wrong = self.wallet.balance("eth1")
            self.assertIsNone(wrong["balance"])
            self.assertEqual(rpc.call_count, 1)
            self.assertIn("wrong chain", wrong["reason"])

    def test_erc20_balance_is_read_only(self):
        self.wallet.add("poly", "polygon", EVM)
        with patch.dict(os.environ, {"SATOSHI_POLYGON_RPC_URL": "https://polygon.example.com"}):
            with patch("satoshi.multichain._rpc", side_effect=["0x89", "0x"+format(1_500_000, "064x")]) as rpc:
                token = self.wallet.token_balance("poly", EVM_OTHER, 6)
            self.assertEqual(token["balance"], "1.5")
            self.assertTrue(token["balance_verified"])
            self.assertEqual(rpc.call_args[0][1], "eth_call")
            self.assertEqual(rpc.call_args[0][2][0]["data"][:10], "0x70a08231")
        with self.assertRaises(ValueError):
            self.wallet.token_balance("poly", EVM_OTHER, 99)

    def test_solana_balance_and_genesis_guard(self):
        self.wallet.add("sol1", "solana", SOL)
        with patch.dict(os.environ, {"SATOSHI_SOLANA_RPC_URL": "https://solana.example.org"}):
            with patch("satoshi.multichain._rpc", side_effect=[SOLANA_MAINNET_GENESIS, {"value": 2_500_000_000}]):
                result = self.wallet.balance("sol1")
            self.assertEqual(result["balance"], "2.5")
            with patch("satoshi.multichain._rpc", return_value="wrong-network") as rpc:
                result = self.wallet.balance("sol1")
            self.assertFalse(result["balance_verified"])
            self.assertEqual(rpc.call_count, 1)

    def test_solana_spl_and_token2022(self):
        self.wallet.add("sol1", "solana", SOL)
        def response(_, method, params):
            if method == "getGenesisHash":
                return SOLANA_MAINNET_GENESIS
            if method == "getTokenAccountsByOwner":
                atom = 1_000_000 if params[1]["programId"].startswith("Tokenkeg") else 2_000_000
                return {"value": [{"account": {"data": {"parsed": {"info": {
                    "mint": SOL, "tokenAmount": {"amount": str(atom), "decimals": 6}
                }}}}}]}
            raise AssertionError("Unexpected method")
        with patch.dict(os.environ, {"SATOSHI_SOLANA_RPC_URL": "https://solana.example.org"}):
            with patch("satoshi.multichain._rpc", side_effect=response) as rpc:
                result = self.wallet.solana_tokens("sol1")
        self.assertTrue(result["balance_verified"])
        self.assertEqual(result["tokens"][0]["amount"], "3")
        self.assertEqual(rpc.call_count, 3)

    def test_transfer_draft_no_sign_send_or_broadcast(self):
        self.wallet.add("eth1", "ethereum", EVM)
        self.wallet.add("sol1", "solana", SOL)
        self.wallet.add("btc1", "bitcoin", BTC)
        pairs = [
            ("eth1", EVM_OTHER, "0.123", "ETH", "123000000000000000"),
            ("sol1", SOL_2, "0.5", "SOL", "500000000"),
        ]
        for alias, recipient, amount, asset, units in pairs:
            draft = self.wallet.prepare(alias, recipient, amount)
            self.assertEqual(draft["asset"], asset)
            self.assertEqual(draft["base_units"], units)
            self.assertFalse(draft["signed"])
            self.assertFalse(draft["broadcast"])
            self.assertFalse(draft["balance_checked"])
            self.assertFalse(draft["transaction_built"])
        for bad in [
            f"wallet send eth1 {EVM_OTHER} 1",
            "wallet import-seed one two three",
            "wallet export-private-key eth1",
            "wallet swap 1 ETH USDT",
            "shell curl whatever",
        ]:
            self.assertFalse(self.cli(bad)["ok"], bad)
        for bad_amount in ["1e3", "-1", "0", "1.0000000000000000009", "NaN"]:
            self.assertFalse(self.cli(f"wallet prepare eth1 {EVM_OTHER} {bad_amount}")["ok"])

    def test_rpc_url_does_not_allow_unencrypted_remote(self):
        self.wallet.add("eth1", "ethereum", EVM)
        for url in ["http://rpc.example.com", "https://user:pass@rpc.example.com", "file:///secret"]:
            with patch.dict(os.environ, {"SATOSHI_ETHEREUM_RPC_URL": url}):
                data = self.wallet.balance("eth1")
                self.assertFalse(data["balance_verified"])
                self.assertIsNone(data["balance"])


if __name__ == "__main__":
    unittest.main()
