# SATOSHI AI — Browser Wallet Connectors + Multi-Chain Wallet CLI v0.3

A localhost SATOSHI AI chat + CLI demo built against THE-MATRIX-AI's **provider interface only**. The LLM has **zero** executable tools or wallet access. Wallet actions are handled independently by an explicit command allowlist.

**This is not a custodian, exchange, trading bot, signing wallet, investment adviser, or production SaaS. No transaction broadcast or trading is implemented.** Use only PUBLIC addresses. Never enter a recovery phrase, private key, mnemonic, password or API secret into SATOSHI chat or CLI.

## Supported chains

| Chain | Symbol | Balance source | Network check |
| --- | --- | --- | --- |
| Bitcoin | BTC | local fully-synced Bitcoin Core `scantxoutset` (confirmed UTXO only) | Core `getblockchaininfo` |
| Ethereum | ETH | `eth_getBalance` | `eth_chainId == 1` |
| Polygon | POL | `eth_getBalance` | `eth_chainId == 137` |
| Base | ETH | `eth_getBalance` | `eth_chainId == 8453` |
| Arbitrum One | ETH | `eth_getBalance` | `eth_chainId == 42161` |
| OP Mainnet (Optimism) | ETH | `eth_getBalance` | `eth_chainId == 10` |
| BNB Smart Chain | BNB | `eth_getBalance` | `eth_chainId == 56` |
| Solana mainnet-beta | SOL | `getBalance` | `getGenesisHash` match |

Additionally, `wallet token` queries an **untrusted, user-specified** ERC-20 contract's `balanceOf` amount on a verified EVM chain. The operator must verify the token contract and decimal count independently. `wallet tokens` queries Solana SPL Token **and** Token-2022 accounts by owner. These features do **not** establish token authenticity, ownership of the private keys, market price, eligibility, or transferability.


## Browser wallet connectors (v0.3)

The SATOSHI dashboard now offers explicit **Connect / Refresh / Save to CLI / Disconnect** controls for:

- **MetaMask (EVM)**: detects a MetaMask EIP-6963 or injected EIP-1193 provider and asks for account permission using `eth_requestAccounts` **only when Connect is clicked**. Displays the authorized public account, current `eth_chainId`, and native-chain balance from `eth_getBalance`. Supports Ethereum, Polygon, Base, Arbitrum, OP Mainnet and BNB Chain in the CLI watchlist. Unknown EVM networks remain visible as unsupported and cannot be saved to the watchlist.
- **Phantom (Solana)**: detects `window.phantom.solana.isPhantom`, and uses `connect()` **only on click**. Displays the public key. A new localhost-only `POST /api/wallet/solana-balance` endpoint can read SOL balance using the **operator-configured** `SATOSHI_SOLANA_RPC_URL`, verifying Solana mainnet genesis before reporting any amount. Without this configuration the UI shows **balance unknown**, never a fictitious balance. This does **not** prove which network is selected inside Phantom.

**Save to CLI** is a separate, deliberate action that writes only the selected **PUBLIC** address to SATOSHI's local watchlist with a user-chosen alias. No automatic persistence on connection. Watchlist entries are not cryptographic proof of ownership. MetaMask Disconnect clears SATOSHI's browser state; to revoke the dapp's provider permission, also disconnect SATOSHI under MetaMask's connected-site permissions. Phantom Disconnect calls the provider's `disconnect()`.

The connectors **never call** `eth_sendTransaction`, `personal_sign`, `signTransaction`, `signAndSendTransaction`, `wallet_switchEthereumChain`, token approvals, swaps or trading methods. No wallet-generated secrets pass to the AI/chat. The AI agent retains zero wallet tools and zero autonomous execution capability.

**Browser requirements:** open `http://127.0.0.1:8787` with a compatible extension on desktop, or in Phantom's in-app browser for mobile Solana use. Wallet providers generally **do not inject** into `file://` previews, non-secure remote HTTP pages or cross-origin iframes. This MVP uses direct browser injection; it does **not** yet include the MetaMask Connect SDK's QR/deep-link mobile connection flow. Before production, perform real extension and mobile-wallet QA, including switching accounts and chains, error handling, authentication/CSRF review, domain verification where applicable, a wallet-focused security audit and testing with small public testnet-only samples. Do not use real funds during initial testing.

## Test the browser connector

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_wallet_connectors.cjs
```

Tests use mocked browser wallets / RPCs, **not** live installed MetaMask or Phantom. The direct-injection implementation is based on the official documentation:

- https://docs.metamask.io/metamask-connect/evm/reference/json-rpc-api/eth_accounts/
- https://docs.metamask.io/metamask-connect/evm/reference/json-rpc-api/eth_getBalance/
- https://docs.phantom.com/solana/detecting-the-provider
- https://docs.phantom.com/solana/establishing-a-connection

## Install

Copy `satoshi/` into the root of the original `THE-MATRIX-AI` repository, alongside `providers/` and `config.py`. This release is an overlay, **not** a standalone replacement for the Neo provider modules.

```bash
python -m pip install -r requirements.txt
ollama pull llama3.2
python -m satoshi.server
```

Browse to `http://127.0.0.1:8787`. The basic UI animates offline; the browser wallet connectors require localhost/HTTPS and an installed wallet extension. Live AI chat requires a configured local Ollama or BYOK provider. The microphone is a local audio-level visualizer only; no speech-to-text.

## CLI examples

All example addresses below are **public examples, NOT addresses you control**. Replace them with addresses from your own wallets; do not transfer money to example addresses.

```bash
# List commands
python -m satoshi.wallet_cli help

# Track an EVM address on two different chains
python -m satoshi.wallet_cli add maineth ethereum 0x52908400098527886E0F7030069857D2E4169EE7
python -m satoshi.wallet_cli add mainbase base 0x52908400098527886E0F7030069857D2E4169EE7

# Track a Solana public address
python -m satoshi.wallet_cli add mainsol solana So11111111111111111111111111111111111111112

# Explore balances / public addresses
python -m satoshi.wallet_cli list
python -m satoshi.wallet_cli balances
python -m satoshi.wallet_cli balance maineth
python -m satoshi.wallet_cli receive maineth

# Query ERC-20 (requires your VERIFIED contract address and its decimals)
python -m satoshi.wallet_cli token maineth 0xde709f2102306220921060314715629080e2fb77 6

# Query Solana SPL/Token-2022 accounts, if RPC supports account enumeration
python -m satoshi.wallet_cli tokens mainsol

# Prepare a *non-executable*, unsigned review draft. Does NOT check funds or gas.
python -m satoshi.wallet_cli prepare maineth 0xde709f2102306220921060314715629080e2fb77 0.005

# Remove an address from tracking (no on-chain action)
python -m satoshi.wallet_cli remove mainbase

# Legacy BTC commands still work
python -m satoshi.wallet_cli address 1BoatSLRHtKNngkdXEeobR76b53LETtpyT
python -m satoshi.wallet_cli balance
```

No automatic sends, swaps, private-key import, signing, node wallets, exchange deposits, SSH or shell execution. An external signing wallet must separately display and confirm all recipient/network/amount/fee details if the user decides to transfer funds.

## Configure verified balance readouts

The default is `balance = null` / `balance_verified = false`. No fabricated balances. SATOSHI never automatically selects a third-party RPC provider. Set URLs privately on the server machine; **HTTPS** is mandatory for remote endpoints; loopback HTTP is allowed. API tokens, if required, must be embedded in an operator-managed URL path or supplied through a secure RPC proxy — **not** pasted into SATOSHI chat, browser CLI or a published environment file. Never commit those URLs if they contain credentials.

```bash
export SATOSHI_ETHEREUM_RPC_URL='https://YOUR_PRIVATE_ETH_RPC_ENDPOINT'
export SATOSHI_POLYGON_RPC_URL='https://YOUR_PRIVATE_POLYGON_RPC_ENDPOINT'
export SATOSHI_BASE_RPC_URL='https://YOUR_PRIVATE_BASE_RPC_ENDPOINT'
export SATOSHI_ARBITRUM_RPC_URL='https://YOUR_PRIVATE_ARBITRUM_RPC_ENDPOINT'
export SATOSHI_OPTIMISM_RPC_URL='https://YOUR_PRIVATE_OPTIMISM_RPC_ENDPOINT'
export SATOSHI_BSC_RPC_URL='https://YOUR_PRIVATE_BSC_RPC_ENDPOINT'
export SATOSHI_SOLANA_RPC_URL='https://YOUR_PRIVATE_SOLANA_RPC_ENDPOINT'
```

Bitcoin Core variables: `SATOSHI_BITCOIN_RPC_URL` (localhost HTTP), `SATOSHI_BITCOIN_RPC_USER`, `SATOSHI_BITCOIN_RPC_PASSWORD`. Bitcoin Core UTXO scans are potentially slow and exclude pending transactions and spent outputs. Public addresses saved in `~/.satoshi_ai/wallets.json` or `~/.satoshi_ai/wallet.json`; they reveal your activity to any local user with access to the file or your RPC service, so protect your system and use privacy-respecting endpoints.

## Security / shipment criteria

- No seed phrase or private key storage; only public addresses. EVM mixed-case addresses require valid EIP-55 checksum; Solana base58 must decode to 32 bytes; Bitcoin legacy and segwit checksums are verified.
- RPC replies are network-checked and unverified results are never presented as balances.
- Local server binds to 127.0.0.1; strict Host/Origin validation. Never expose the demo to the internet or use on an untrusted shared machine.
- Existing Neo autonomous tools, shell/SSH, remote MCP, auto approvals, file edits remain completely disabled.
- Payment drafts are in-memory data records; no fee simulation, balance validation, signed transaction creation or broadcasting. Actual sending would require separately designed and audited adapters, human approval, secure signing, chain-specific fees and robust recovery.
- **Before sale:** independent security review, live-chain tests on safe public addresses, privacy/terms, license compliance, Windows packaging, code signing, audited wallet interactions and appropriate local legal review.

## Run tests

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

The original Neo source remains source-available under its own license, and attribution/commercial permissions must be respected. SATOSHI is a separate interface and does not represent Satoshi Nakamoto.
