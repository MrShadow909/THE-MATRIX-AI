"""Local-only SATOSHI interface. No remote bind, no CORS, no shell endpoint."""
from __future__ import annotations
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .commands import run_command
from .engine import SatoshiEngine
from .wallet import WatchWallet
from .multichain import MultiChainWallet

STATIC = Path(__file__).resolve().parent / "static"
UI = STATIC / "index.html"
WALLET_CONNECTORS_JS = STATIC / "wallet-connectors.js"
MAX_JSON_BYTES = 36000


def make_handler(engine=None, wallet=None, port=8787):
    engine = engine or SatoshiEngine()
    wallet = wallet or WatchWallet()
    multi = MultiChainWallet(bitcoin_wallet=wallet)
    allowed_hosts = {f"localhost:{port}", f"127.0.0.1:{port}", f"[::1]:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # No sensitive chat content in access logs.

        def reply(self, status, data):
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(raw)

        def permitted(self):
            if self.headers.get("Host") not in allowed_hosts:
                self.reply(403, {"error": "Unexpected Host"})
                return False
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc not in allowed_hosts:
                self.reply(403, {"error": "Cross-origin requests disabled"})
                return False
            return True

        def do_GET(self):
            if not self.permitted():
                return
            if self.path == "/":
                body = UI.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/wallet-connectors.js":
                body = WALLET_CONNECTORS_JS.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/status":
                self.reply(200, {"engine": engine.status(), "wallet": wallet.status()})
            elif self.path == "/api/wallet":
                self.reply(200, wallet.status())
            elif self.path == "/api/wallets":
                self.reply(200, multi.status())
            else:
                self.reply(404, {"error": "Not found"})

        def do_POST(self):
            if not self.permitted():
                return
            if self.path not in ("/api/chat", "/api/command", "/api/wallet/solana-balance"):
                self.reply(404, {"error": "Not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                self.reply(415, {"error": "JSON required"})
                return
            if not 0 < length <= MAX_JSON_BYTES:
                self.reply(413, {"error": "Invalid request size"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("JSON object required")
                if self.path == "/api/chat":
                    reply = engine.chat(payload.get("message"), payload.get("history"))
                    self.reply(200, {"reply": reply, "tools_executed": 0})
                elif self.path == "/api/wallet/solana-balance":
                    address = payload.get("address")
                    if not isinstance(address, str) or len(address) > 44 or set(payload) != {"address"}:
                        raise ValueError("Only one public Solana address is accepted")
                    self.reply(200, multi.inspect_public_solana(address))
                else:
                    self.reply(200, run_command(payload.get("command"), wallet, engine, multi))
            except (ValueError, TypeError) as exc:
                self.reply(400, {"error": str(exc)})
            except Exception:
                # Never expose API keys, raw provider errors or RPC details to browser.
                self.reply(503, {"error": "Backend unavailable or model request failed. Check local server logs/settings."})

    return Handler


def main():
    port = int(os.getenv("SATOSHI_PORT", "8787"))
    if not 1024 <= port <= 65535:
        raise ValueError("SATOSHI_PORT must be 1024–65535")
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(port=port))
    print(f"SATOSHI AI localhost interface: http://127.0.0.1:{port}")
    print("Chat uses Neo providers without autonomous tools. Multi-chain CLI is watch-only.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
