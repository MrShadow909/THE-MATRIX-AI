/* SATOSHI AI — explicit browser wallet connectors, read-only v0.3.
 * No signing, sendTransaction, seed import, authorization delegation, swaps, or AI tools.
 * EVM balances come from the user's MetaMask EIP-1193 provider.
 * Solana mainnet balances come from SATOSHI localhost's verified, read-only RPC.
 */
(function (root) {
  'use strict';

  const EVM_NETWORKS = Object.freeze({
    '0x1': {name: 'Ethereum', chain: 'ethereum', symbol: 'ETH'},
    '0x89': {name: 'Polygon', chain: 'polygon', symbol: 'POL'},
    '0x2105': {name: 'Base', chain: 'base', symbol: 'ETH'},
    '0xa4b1': {name: 'Arbitrum One', chain: 'arbitrum', symbol: 'ETH'},
    '0xa': {name: 'OP Mainnet', chain: 'optimism', symbol: 'ETH'},
    '0x38': {name: 'BNB Chain', chain: 'bsc', symbol: 'BNB'}
  });
  const EVM_RE = /^0x[0-9a-fA-F]{40}$/;
  const SOL_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
  const ALIAS_RE = /^[A-Za-z][A-Za-z0-9_-]{0,23}$/;

  function formatNativeAmount(value, scale = 18, places = 6) {
    if (typeof value !== 'string' || !/^0x[0-9a-fA-F]+$/.test(value)) throw Error('Invalid hexadecimal balance');
    const atoms = BigInt(value);
    const unit = 10n ** BigInt(scale);
    const major = (atoms / unit).toString();
    const minor = (atoms % unit).toString().padStart(scale, '0').slice(0, places).replace(/0+$/, '');
    if (atoms > 0n && major === '0' && minor === '') return '<0.' + '0'.repeat(Math.max(0, places - 1)) + '1';
    return minor ? major + '.' + minor : major;
  }

  function chainInfo(chainHex) {
    if (typeof chainHex !== 'string' || !/^0x[0-9a-fA-F]+$/.test(chainHex)) throw Error('Invalid EVM chain ID');
    return EVM_NETWORKS['0x' + BigInt(chainHex).toString(16)] || null;
  }

  function errorMessage(error) {
    if (error && (error.code === 4001 || error.code === '4001')) return 'Request rejected in wallet';
    return error instanceof Error ? error.message.slice(0, 180) : 'Wallet request failed';
  }

  function shortAddress(address) {
    return address ? address.slice(0, 8) + '…' + address.slice(-6) : 'NOT CONNECTED';
  }

  // An EIP-6963 provider may be announced by multiple wallets. Prefer explicit MetaMask rdns.
  // This flag is a discovery hint, not a cryptographic identity guarantee.
  const announced = [];
  function announcedProvider(event) {
    const detail = event && event.detail;
    if (detail && detail.provider && typeof detail.provider.request === 'function' &&
        (detail.info?.rdns === 'io.metamask' || detail.provider.isMetaMask === true) &&
        !announced.some(item => item.provider === detail.provider)) {
      announced.push({provider: detail.provider, rdns: detail.info?.rdns});
    }
  }
  function metaMaskProvider(view = root) {
    const preferred = announced.find(item => item.rdns === 'io.metamask');
    if (preferred) return preferred.provider;
    if (view.ethereum?.isMetaMask && typeof view.ethereum.request === 'function') return view.ethereum;
    return announced.find(item => item.provider.isMetaMask)?.provider || null;
  }
  function phantomProvider(view = root) {
    const p = view.phantom?.solana;
    return p?.isPhantom === true && typeof p.connect === 'function' ? p : null;
  }

  // Pure reader; callers do not have a path to execute or sign anything in a wallet.
  async function readEvmBalance(provider, account) {
    if (!EVM_RE.test(account)) throw Error('Invalid EVM account');
    const chainId = await provider.request({method: 'eth_chainId'});
    const network = chainInfo(chainId);
    const balanceHex = await provider.request({method: 'eth_getBalance', params: [account, 'latest']});
    return {
      account,
      chainId,
      chain: network?.chain || null,
      networkName: network?.name || 'UNSUPPORTED NETWORK',
      symbol: network?.symbol || 'native token',
      balance: formatNativeAmount(balanceHex, 18),
      // Wallet RPC is not an independent on-chain audit.
      source: 'MetaMask RPC',
      supported: Boolean(network)
    };
  }

  async function initConnectorUI({doc = root.document, view = root, log = () => {}} = {}) {
    if (!doc) return;
    const byId = (name) => doc.getElementById(name);
    let meta = {provider: null, address: '', chain: null, generation: 0};
    let phantom = {provider: null, address: '', generation: 0};
    const setText = (id, value) => {if (byId(id)) byId(id).textContent = value;};
    const button = (id, callback) => byId(id)?.addEventListener('click', callback);
    const busy = (ids, value) => ids.forEach(id => {if (byId(id)) byId(id).disabled = value;});
    const metaButtons = ['connectMeta', 'refreshMeta', 'saveMeta', 'disconnectMeta'];
    const phantomButtons = ['connectPhantom', 'refreshPhantom', 'savePhantom', 'disconnectPhantom'];
    const metaEvents = () => {
      if (!meta.provider?.on) return;
      meta.provider.on('accountsChanged', onMetaAccounts);
      meta.provider.on('chainChanged', onMetaChain);
      meta.provider.on('disconnect', onMetaProviderDisconnect);
    };
    function removeMetaEvents() {
      if (!meta.provider?.removeListener) return;
      meta.provider.removeListener('accountsChanged', onMetaAccounts);
      meta.provider.removeListener('chainChanged', onMetaChain);
      meta.provider.removeListener('disconnect', onMetaProviderDisconnect);
    }
    function showMetaDisconnected(status = 'NOT CONNECTED') {
      setText('metaStatus', status);
      setText('metaAddress', '—');
      setText('metaNetwork', 'NO NETWORK');
      setText('metaBalance', '—');
      byId('saveMeta').disabled = true;
      byId('refreshMeta').disabled = true;
      byId('disconnectMeta').disabled = true;
    }
    function showPhantomDisconnected(status = 'NOT CONNECTED') {
      setText('phantomStatus', status);
      setText('phantomAddress', '—');
      setText('phantomBalance', '— SOL');
      byId('savePhantom').disabled = true;
      byId('refreshPhantom').disabled = true;
      byId('disconnectPhantom').disabled = true;
    }
    function clearMeta(status) {
      ++meta.generation;
      removeMetaEvents();
      meta.provider = null;
      meta.address = '';
      meta.chain = null;
      showMetaDisconnected(status);
    }
    function clearPhantom(status) {
      ++phantom.generation;
      if (phantom.provider?.removeListener) {
        phantom.provider.removeListener('accountChanged', onPhantomAccount);
        phantom.provider.removeListener('disconnect', onPhantomProviderDisconnect);
      }
      phantom.provider = null;
      phantom.address = '';
      showPhantomDisconnected(status);
    }
    function onMetaAccounts(accounts) {
      if (!meta.provider) return;
      if (!Array.isArray(accounts) || !accounts[0] || !EVM_RE.test(accounts[0])) {
        clearMeta('ACCOUNT DISCONNECTED'); return;
      }
      meta.address = accounts[0];
      void refreshMeta();
    }
    function onMetaChain() {if (meta.provider) void refreshMeta();}
    function onMetaProviderDisconnect() {clearMeta('WALLET OFFLINE');}
    async function refreshMeta() {
      const provider = meta.provider;
      if (!provider || !meta.address) return;
      const generation = ++meta.generation;
      setText('metaStatus', 'READING WALLET RPC…');
      try {
        const accounts = await provider.request({method: 'eth_accounts'});
        if (!Array.isArray(accounts) || !EVM_RE.test(accounts[0] || '')) {
          if (generation === meta.generation) clearMeta('ACCOUNT DISCONNECTED');
          return;
        }
        const result = await readEvmBalance(provider, accounts[0]);
        if (generation !== meta.generation || provider !== meta.provider) return;
        meta.address = result.account;
        meta.chain = result.chain;
        setText('metaStatus', result.supported ? 'CONNECTED · READ-ONLY' : 'CONNECTED · UNSUPPORTED CHAIN');
        setText('metaAddress', shortAddress(result.account));
        byId('metaAddress').title = result.account;
        setText('metaNetwork', result.networkName + ' · ' + result.chainId);
        setText('metaBalance', result.balance + ' ' + result.symbol);
        byId('saveMeta').disabled = !result.supported;
        byId('refreshMeta').disabled = false;
        byId('disconnectMeta').disabled = false;
      } catch (err) {
        if (generation !== meta.generation) return;
        meta.chain = null;
        setText('metaStatus', 'CONNECTED · BALANCE UNAVAILABLE');
        setText('metaAddress', shortAddress(meta.address));
        setText('metaNetwork', 'CHECK WALLET NETWORK');
        setText('metaBalance', '—');
        byId('saveMeta').disabled = true;
        log('[METAMASK] ' + errorMessage(err), 'warn');
      }
    }
    async function connectMeta() {
      const provider = metaMaskProvider(view);
      if (!provider) {
        log('[METAMASK] No extension found. Install MetaMask or use a supported wallet browser.', 'warn');
        setText('metaStatus', 'EXTENSION NOT DETECTED');
        return;
      }
      byId('connectMeta').disabled = true;
      setText('metaStatus', 'AWAITING PERMISSION…');
      try {
        const accounts = await provider.request({method: 'eth_requestAccounts'});
        if (!Array.isArray(accounts) || !EVM_RE.test(accounts[0] || '')) throw Error('No valid EVM account authorized');
        clearMeta('CONNECTING');
        meta.provider = provider;
        meta.address = accounts[0];
        metaEvents();
        byId('refreshMeta').disabled = false;
        byId('disconnectMeta').disabled = false;
        await refreshMeta();
        log('[METAMASK] Account connected (read-only, no signing).', 'ok');
      } catch (err) {
        setText('metaStatus', 'NOT CONNECTED');
        log('[METAMASK] ' + errorMessage(err), 'warn');
      } finally {byId('connectMeta').disabled = false;}
    }
    function disconnectMeta() {
      // EIP-1193 does not guarantee that dapps can revoke wallet permissions.
      // Local UI disconnect only; revoke SATOSHI in MetaMask Connected Sites for full revocation.
      clearMeta('DISCONNECTED LOCALLY');
      log('[METAMASK] Local session cleared. Revoke SATOSHI in MetaMask Connected Sites to remove wallet permission.', 'warn');
    }
    function onPhantomAccount(key) {
      if (!phantom.provider) return;
      const addr = key?.toBase58?.() || key?.toString?.() || '';
      if (!SOL_RE.test(addr)) {clearPhantom('ACCOUNT DISCONNECTED'); return;}
      phantom.address = addr;
      void refreshPhantom();
    }
    function onPhantomProviderDisconnect() {clearPhantom('WALLET DISCONNECTED');}
    async function refreshPhantom() {
      const provider = phantom.provider;
      if (!provider || !phantom.address) return;
      const generation = ++phantom.generation;
      setText('phantomStatus', 'READING MAINNET RPC…');
      setText('phantomAddress', shortAddress(phantom.address));
      byId('phantomAddress').title = phantom.address;
      setText('phantomNetwork', 'SOLANA MAINNET · RPC CHECK');
      try {
        const response = await view.fetch('/api/wallet/solana-balance', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({address: phantom.address})
        });
        if (!response.ok) throw Error('SATOSHI local RPC endpoint unavailable');
        const result = await response.json();
        if (generation !== phantom.generation || provider !== phantom.provider) return;
        if (result.balance_verified) {
          setText('phantomStatus', 'CONNECTED · MAINNET RPC VERIFIED');
          setText('phantomBalance', result.balance + ' SOL');
        } else {
          setText('phantomStatus', 'CONNECTED · BALANCE UNKNOWN');
          setText('phantomBalance', '— SOL');
          log('[PHANTOM] ' + (result.reason || 'Configure SATOSHI_SOLANA_RPC_URL to read SOL balance'), 'warn');
        }
      } catch (err) {
        if (generation !== phantom.generation) return;
        setText('phantomStatus', 'CONNECTED · BALANCE UNKNOWN');
        setText('phantomBalance', '— SOL');
        log('[PHANTOM] ' + errorMessage(err), 'warn');
      }
    }
    async function connectPhantom() {
      const provider = phantomProvider(view);
      if (!provider) {
        setText('phantomStatus', 'EXTENSION NOT DETECTED');
        log('[PHANTOM] Phantom Solana extension not detected. On mobile, open SATOSHI in Phantom in-app browser.', 'warn');
        return;
      }
      byId('connectPhantom').disabled = true;
      setText('phantomStatus', 'AWAITING PERMISSION…');
      try {
        const response = await provider.connect();
        const addr = response?.publicKey?.toBase58?.() || response?.publicKey?.toString?.() || '';
        if (!SOL_RE.test(addr)) throw Error('Invalid Solana public key');
        clearPhantom('CONNECTING');
        phantom.provider = provider;
        phantom.address = addr;
        if (provider.on) {
          provider.on('accountChanged', onPhantomAccount);
          provider.on('disconnect', onPhantomProviderDisconnect);
        }
        byId('refreshPhantom').disabled = false;
        byId('savePhantom').disabled = false;
        byId('disconnectPhantom').disabled = false;
        await refreshPhantom();
        log('[PHANTOM] Connected public Solana address; SATOSHI does not know wallet network selection.', 'ok');
      } catch (err) {
        setText('phantomStatus', 'NOT CONNECTED');
        log('[PHANTOM] ' + errorMessage(err), 'warn');
      } finally {byId('connectPhantom').disabled = false;}
    }
    async function disconnectPhantom() {
      const p = phantom.provider;
      clearPhantom('DISCONNECTED');
      if (p?.disconnect) {
        try {await p.disconnect();} catch (err) {log('[PHANTOM] ' + errorMessage(err), 'warn');}
      }
      log('[PHANTOM] Connection closed.', 'warn');
    }
    async function saveAddress(kind) {
      const isMeta = kind === 'meta';
      const chain = isMeta ? meta.chain : 'solana';
      const address = isMeta ? meta.address : phantom.address;
      if (!chain || !address) return;
      const initial = (isMeta ? 'mm_' : 'ph_') + address.slice(2, 9).replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
      const alias = view.prompt('Save PUBLIC address to SATOSHI CLI watchlist. Enter alias (1-24 characters):', initial);
      if (alias === null) return;
      if (!ALIAS_RE.test(alias)) {log('[WALLET] Invalid alias. Use letters, digits, _ or -; 1–24 chars.', 'warn'); return;}
      // Save only after explicit user action. Treat this as a public watchlist, NOT proof of ownership.
      const id = isMeta ? 'saveMeta' : 'savePhantom';
      byId(id).disabled = true;
      try {
        const response = await view.fetch('/api/command', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({command: 'wallet add ' + alias + ' ' + chain + ' ' + address})
        });
        if (!response.ok) throw Error('SATOSHI CLI server unavailable');
        const result = await response.json();
        if (!result.ok) throw Error(result.error || 'Watchlist import refused');
        log('[WALLET] Saved public ' + chain + ' address as alias ' + alias + '.', 'ok');
      } catch (err) {
        log('[WALLET] ' + errorMessage(err), 'warn');
      } finally {byId(id).disabled = !isMeta ? !phantom.address : !(meta.address && meta.chain);}
    }

    showMetaDisconnected();
    showPhantomDisconnected();
    button('connectMeta', connectMeta);
    button('refreshMeta', refreshMeta);
    button('disconnectMeta', disconnectMeta);
    button('saveMeta', () => saveAddress('meta'));
    button('connectPhantom', connectPhantom);
    button('refreshPhantom', refreshPhantom);
    button('disconnectPhantom', disconnectPhantom);
    button('savePhantom', () => saveAddress('phantom'));
    if (view.addEventListener) {
      view.addEventListener('eip6963:announceProvider', announcedProvider);
      view.dispatchEvent?.(new Event('eip6963:requestProvider'));
    }
    if (!view.isSecureContext && view.location?.hostname !== 'localhost' && view.location?.hostname !== '127.0.0.1') {
      log('[WALLET] Browser extensions require localhost or HTTPS; file:// preview cannot connect.', 'warn');
    }
    return {connectMeta, connectPhantom, refreshMeta, refreshPhantom, disconnectMeta, disconnectPhantom};
  }

  const api = {formatNativeAmount, chainInfo, readEvmBalance, metaMaskProvider, phantomProvider, initConnectorUI, announcedProvider};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root.document && typeof module === 'undefined') {
    // SATOSHI main UI initializes after body scripts have run; safe on DOMContentLoaded as well.
    const run = () => {initConnectorUI({log: (message, cls) => root.satoshiLog?.(message, cls)}).catch(() => {});};
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', run, {once:true});
    else run();
  }
})(typeof window !== 'undefined' ? window : globalThis);
