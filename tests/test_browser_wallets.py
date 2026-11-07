"""Offline tests for the browser wallet bridge (no live wallet/network)."""
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from satoshi.server import make_handler
from satoshi.multichain import MultiChainWallet, SOLANA_MAINNET_GENESIS
from satoshi.wallet import WatchWallet

SOL = 'So11111111111111111111111111111111111111112'


class FakeEngine:
    def status(self):
        return {'connected': False, 'provider': 'mock', 'model': 'mock', 'autonomous_tools': False}


class BrowserWalletHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.wallet = WatchWallet(Path(self.tmp.name) / 'btc.json')
        self.port_reserver = ThreadingHTTPServer(('127.0.0.1', 0), lambda *args: None)
        self.port = self.port_reserver.server_port
        self.port_reserver.server_close()
        self.server = ThreadingHTTPServer(('127.0.0.1', self.port), make_handler(FakeEngine(), self.wallet, self.port))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.clean)

    def clean(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def request(self, method, route, payload=None, headers=None):
        conn = HTTPConnection('127.0.0.1', self.port, timeout=3)
        h = {'Content-Type': 'application/json', **(headers or {})}
        conn.request(method, route, json.dumps(payload) if payload is not None else None, headers=h)
        res = conn.getresponse()
        raw = res.read()
        status = res.status
        content_type = res.getheader('Content-Type')
        conn.close()
        return status, raw, content_type

    def test_connector_js_served_on_same_origin(self):
        status, body, typ = self.request('GET', '/wallet-connectors.js')
        self.assertEqual(status, 200)
        self.assertIn('javascript', typ)
        self.assertIn(b'eth_requestAccounts', body)
        self.assertNotIn(b'eth_sendTransaction', body)
        self.assertNotIn(b'privateKey', body)
        status, body, _ = self.request('GET','/wallet-connectors.js',headers={'Host':'evil.example'})
        self.assertEqual(status,403)

    def test_solana_rpc_validated_and_no_persistence(self):
        with patch.dict('os.environ', {'SATOSHI_SOLANA_RPC_URL': 'https://rpc.example.org'}):
            with patch('satoshi.multichain._rpc', side_effect=[SOLANA_MAINNET_GENESIS, {'value':1_500_000_000}]) as rpc:
                code, raw, _ = self.request('POST','/api/wallet/solana-balance',{'address':SOL})
            response = json.loads(raw)
            self.assertEqual(code,200)
            self.assertEqual(response['balance'],'1.5')
            self.assertTrue(response['balance_verified'])
            self.assertEqual(rpc.call_count,2)
        # Requesting a public balance never writes to watchlist.
        self.assertFalse((Path(self.tmp.name)/'multi.json').exists())

    def test_solana_no_rpc_does_not_fabricate_balance(self):
        with patch.dict('os.environ', {'SATOSHI_SOLANA_RPC_URL': ''}):
            code,raw,_=self.request('POST','/api/wallet/solana-balance',{'address':SOL})
        response=json.loads(raw)
        self.assertEqual(code,200)
        self.assertIsNone(response['balance'])
        self.assertFalse(response['balance_verified'])

    def test_origin_validation_and_extraneous_inputs_rejected(self):
        for payload in [{'address':'bad'}, {'address':SOL,'private_key':'abc'}, {'address':SOL, 'network':'testnet'},
                        {'address':1234}, {'address':SOL, 'rpc_url':'http://other.example.com'}]:
            status,_,_=self.request('POST','/api/wallet/solana-balance',payload)
            self.assertEqual(status,400,payload)
        status,_,_=self.request('POST','/api/wallet/solana-balance',{'address':SOL},{'Origin':'https://other.example'})
        self.assertEqual(status,403)
        status,_,_=self.request('POST','/api/wallet/solana-balance',{'address':SOL},{'Host':'evil.example'})
        self.assertEqual(status,403)

    def test_wrong_chain_untrusted_and_no_third_party_rpc(self):
        multi=MultiChainWallet(Path(self.tmp.name)/'multi.json',self.wallet)
        with patch.dict('os.environ',{'SATOSHI_SOLANA_RPC_URL':'https://rpc.example.org'}):
            with patch('satoshi.multichain._rpc',return_value='not-mainnet') as rpc:
                result=multi.inspect_public_solana(SOL)
        self.assertFalse(result['balance_verified'])
        self.assertIsNone(result['balance'])
        self.assertEqual(rpc.call_count,1)
        self.assertFalse((Path(self.tmp.name)/'multi.json').exists())


if __name__ == '__main__':
    unittest.main()
