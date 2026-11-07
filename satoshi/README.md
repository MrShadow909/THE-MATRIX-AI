# SATOSHI AI — Neo Matrix provider-powered MVP (watch-only BTC)

This is a **local demonstration**, not a custody service, financial product, exchange, automated trader, or production-ready SaaS.

## What is real

- The chat calls the actual **THE-MATRIX-AI** provider abstraction: Ollama, OpenAI, Anthropic or DeepSeek (bring your own key).
- The Neo **autonomous Agent, ToolRegistry, SSH, filesystem, shell, self-improvement and auto-approval are NOT loaded by SATOSHI**. Responses are text-only.
- Separate Bitcoin watch-only CLI validates a PUBLIC receiving address (including checksum). No seed phrase, signing, sending, or broadcasts. A true balance remains **unknown** unless an explicitly configured local Bitcoin Core node returns a successful `scantxoutset` UTXO scan.
- Web UI includes a locally reactive particle-field simulation and optional microphone amplitude visualization (no transcription / speech-to-text in MVP). No voice data is submitted to the AI backend.

## Install in THE-MATRIX-AI repo

Copy `satoshi/` into the root of `THE-MATRIX-AI` (same level as `config.py`, `providers/`). Then:

```bash
python -m pip install -r requirements.txt
# Recommended no-cost local model:
ollama pull llama3.2
# Start Ollama in another terminal if it is not already running
python -m satoshi.server
```

Open **http://127.0.0.1:8787**. The HTML preview can open without a backend, but chat and wallet commands require the local server.

Provider selection (examples):

```bash
# Ollama (default)
export SATOSHI_PROVIDER=ollama
export SATOSHI_MODEL=llama3.2
# OpenAI example: use a real supported model and your own key
export SATOSHI_PROVIDER=openai
export OPENAI_API_KEY=YOUR_OWN_KEY_HERE
# NEVER paste API keys, passwords or wallet secrets into the browser.
python -m satoshi.server
```

Windows PowerShell uses `$env:SATOSHI_PROVIDER="ollama"` and `$env:SATOSHI_MODEL="llama3.2"` instead of `export`.

## Bitcoin CLI

```bash
python -m satoshi.wallet_cli status
python -m satoshi.wallet_cli address 1BoatSLRHtKNngkdXEeobR76b53LETtpyT
python -m satoshi.wallet_cli balance
```

The address above is a **public example**, not a wallet you own. Replace it with an address obtained from your own noncustodial Bitcoin wallet. Only the public address is stored in `~/.satoshi_ai/wallet.json`.

For optional verified confirmed UTXO balance, run your own *fully synchronized* Bitcoin Core node on localhost and configure `SATOSHI_BITCOIN_RPC_URL`, `SATOSHI_BITCOIN_RPC_USER`, and `SATOSHI_BITCOIN_RPC_PASSWORD` in the **server's environment**. Never put RPC credentials in browser fields or source files. The wallet calls only `getblockchaininfo` and `scantxoutset`; large scans may take time.

## Security boundaries / ship blockers

- Loopback-only web server, strict Host and Origin restrictions, JSON/body-size checks, no remote shell, no tool execution from LLM output, no automatic wallet transactions.
- Never market this prototype as real custody, trading, a functioning wallet balance without RPC, autonomous swarm, financial advice, or a ready-to-deploy public SaaS.
- Before selling: independent code/security audit, packaging, installer signing, error UX, auth/access control for remote use, opt-in privacy disclosures, robust provider error handling, rate limiting, license fulfillment, payment/refund policy, and jurisdiction-specific legal review. Do not expose this server to the internet.
- Respect repository's source-available license. Commercial redistribution needs explicit copyright-holder permission; verify ownership and permissions before distributing derivatives.

## Tests

```bash
python -m unittest discover -s tests -p 'test_satoshi.py' -v
```

SATOSHI frontend copyright and product branding require separate commercial terms; this MVP does not assert exclusive rights to the name "Satoshi Nakamoto".
