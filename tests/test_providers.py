"""Offline / mocked tests for SATOSHI multi-provider support."""
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from satoshi.engine import DEFAULT_MODELS, PROVIDERS, SatoshiEngine
from satoshi.providers_ext import CompatibleProvider, provider_base_url
from satoshi.server import make_handler
from satoshi.wallet import WatchWallet
from satoshi.coder import SatoshiCoder
from satoshi.coder_tools import WorkspaceTools


class TestProviderConfiguration(unittest.TestCase):
    def test_seven_options(self):
        self.assertEqual(set(PROVIDERS), {
            "ollama", "openai", "anthropic", "deepseek", "gemini", "qwen", "mistral"})
        options = SatoshiEngine.provider_options()
        self.assertEqual(len(options["providers"]), 7)
        self.assertEqual({x["id"] for x in options["providers"]}, set(PROVIDERS))

    def test_defaults_and_switch(self):
        engine = SatoshiEngine("ollama")
        self.assertEqual(engine.configure("GEMINI")["model"], DEFAULT_MODELS["gemini"])
        self.assertEqual(engine.configure("qwen", "qwen-plus")["model"], "qwen-plus")
        self.assertEqual(engine.configure("mistral", "mistral-small-latest")["model"], "mistral-small-latest")
        with self.assertRaises(ValueError):
            engine.configure("malicious_provider")
        with self.assertRaises(ValueError):
            engine.configure("qwen", "bad model\nX: 123")

    def test_keys_server_only_and_no_live_claim(self):
        for provider, env in [("gemini", "GEMINI_API_KEY"),
                              ("qwen", "DASHSCOPE_API_KEY"),
                              ("mistral", "MISTRAL_API_KEY")]:
            with self.subTest(provider=provider), patch.dict(os.environ, {env: "dummy-test-secret"}):
                eng = SatoshiEngine(provider)
                status = eng.status()
                self.assertNotIn("dummy-test-secret", json.dumps(status))
                self.assertFalse(status["verified_live"])
        self.assertNotIn("api_key", json.dumps(SatoshiEngine.provider_options()))

    def test_qwen_endpoint_is_restricted(self):
        with patch.dict(os.environ, {"SATOSHI_QWEN_BASE_URL": "http://localhost:8123/compatible-mode/v1"}):
            with self.assertRaises(ValueError):
                provider_base_url("qwen")
        with patch.dict(os.environ, {"SATOSHI_QWEN_BASE_URL": "https://evil.example/compatible-mode/v1"}):
            with self.assertRaises(ValueError):
                provider_base_url("qwen")
        with patch.dict(os.environ, {"SATOSHI_QWEN_BASE_URL": "https://work01.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"}):
            self.assertIn("work01.ap-southeast-1.maas.aliyuncs.com", provider_base_url("qwen"))

    def test_openai_compatible_tool_calls_offline(self):
        captures = []
        class FakeCompletions:
            def create(self, **kwargs):
                captures.append(kwargs)
                func = types.SimpleNamespace(name="write_file", arguments='{"path":"ok.py","content":"hello"}')
                msg = types.SimpleNamespace(content="Planning", tool_calls=[types.SimpleNamespace(id="call_01", function=func)])
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="tool_calls")])
        class FakeSDK:
            def __init__(self, **kwargs):
                captures.append({"client_config": kwargs})
                self.chat = types.SimpleNamespace(completions=FakeCompletions())
        module = types.ModuleType("openai")
        module.OpenAI = FakeSDK
        with patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"}), patch.dict(sys.modules, {"openai": module}):
            provider = CompatibleProvider("mistral", "mistral-small-latest")
            response = provider.complete("SYSTEM", [{"role": "user", "content": "Create file"}],
                                         [{"name": "write_file", "description": "write", "input_schema": {"type": "object"}}])
        self.assertEqual(response.tool_calls[0].name, "write_file")
        self.assertEqual(response.tool_calls[0].arguments["path"], "ok.py")
        self.assertEqual(captures[0]["client_config"]["base_url"], "https://api.mistral.ai/v1")
        self.assertEqual(captures[1]["tools"][0]["function"]["name"], "write_file")


class TestProviderRoute(unittest.TestCase):
    def test_switch_rejects_keys_and_clears_pending(self):
        with tempfile.TemporaryDirectory() as work:
            engine = SatoshiEngine("ollama")
            wallet = WatchWallet(Path(work) / "watch.json")
            coder = SatoshiCoder(engine=engine, tools=WorkspaceTools(Path(work) / "workspace"))
            coder._session()  # create a session to check reset
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), lambda *a, **kw: None)
            port = httpd.server_port
            httpd.server_close()
            httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(engine, wallet, port, coder))
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                def req(method, path, obj=None):
                    c = HTTPConnection("127.0.0.1", port, timeout=3)
                    c.request(method, path, body=json.dumps(obj) if obj is not None else None,
                              headers={"Content-Type": "application/json"})
                    r = c.getresponse()
                    code = r.status
                    data = json.loads(r.read())
                    c.close()
                    return code, data
                code, out = req("GET", "/api/providers")
                self.assertEqual(code, 200)
                self.assertEqual(len(out["providers"]), 7)
                code, _ = req("POST", "/api/provider", {"provider": "qwen", "api_key": "exfiltrate"})
                self.assertEqual(code, 400)
                code, out = req("POST", "/api/provider", {"provider": "gemini", "model": "gemini-2.5-flash"})
                self.assertEqual(code, 200)
                self.assertEqual(out["selected"]["provider"], "gemini")
                self.assertEqual(len(coder.sessions), 0)
            finally:
                httpd.shutdown()
                httpd.server_close()
                t.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
