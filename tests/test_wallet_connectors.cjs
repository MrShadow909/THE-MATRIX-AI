'use strict';
const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const {formatNativeAmount, chainInfo, readEvmBalance, metaMaskProvider, phantomProvider, initConnectorUI, announcedProvider} = require('../satoshi/static/wallet-connectors.js');

const ETH = '0x52908400098527886E0F7030069857D2E4169EE7';
const SOL = 'So11111111111111111111111111111111111111112';

function makeDom() {
  const ids = ['connectMeta', 'refreshMeta', 'saveMeta', 'disconnectMeta', 'metaAddress', 'metaBalance', 'metaNetwork', 'metaStatus',
               'connectPhantom', 'refreshPhantom', 'savePhantom', 'disconnectPhantom', 'phantomAddress', 'phantomNetwork', 'phantomBalance', 'phantomStatus'];
  const elements = Object.fromEntries(ids.map(id => [id,{id,textContent:'',disabled:false,title:'',listeners:{},addEventListener(event, cb){this.listeners[event] = cb;},click(){return this.listeners.click?.();}}]));
  return {elements, getElementById(id){assert.ok(elements[id],id);return elements[id];}};
}
function provider() {
  const emitter = new EventEmitter();
  const calls = [];
  let currentAddress = ETH;
  let chain = '0x1';
  const p = {
    isMetaMask: true,
    on: emitter.on.bind(emitter),
    removeListener: emitter.removeListener.bind(emitter),
    emit: emitter.emit.bind(emitter),
    async request({method,params}) {
      calls.push(method);
      if (method === 'eth_requestAccounts' || method === 'eth_accounts') return [currentAddress];
      if (method === 'eth_chainId') return chain;
      if (method === 'eth_getBalance') {assert.equal(params[0],currentAddress);return '0xde0b6b3a7640000';}
      throw Error('Unexpected wallet method: ' + method);
    }
  };
  return {p,calls,setChain:next=>chain=next,setAddress:next=>currentAddress=next};
}
function makeView(metaProvider, phantomP, options={}) {
  const calls = [];
  const view = {
    ethereum: metaProvider,
    phantom: phantomP ? {solana:phantomP} : undefined,
    isSecureContext:true,
    location:{hostname:'localhost'},
    addEventListener(){},dispatchEvent(){},
    prompt(label, def){calls.push(['prompt',label,def]);return options.alias || 'wallet1';},
    async fetch(url, options){
      const request = JSON.parse(options.body);
      calls.push([url,request]);
      if (url === '/api/wallet/solana-balance') {
        assert.equal(request.address,SOL);
        return {ok:true,async json(){return {balance:'2.25',balance_verified:true};}};
      }
      if (url === '/api/command'){
        assert.match(request.command,/^wallet add (\w+) (solana|ethereum|base|arbitrum|polygon|optimism|bsc) /);
        return {ok:true,async json(){return {ok:true,output:{watch_only:true}};}};
      }
      throw Error('Unexpected browser fetch '+url);
    }
  };
  return {view,calls};
}
async function main() {
  assert.equal(formatNativeAmount('0x1',9,9), '0.000000001');
  assert.equal(formatNativeAmount('0xde0b6b3a7640000'), '1');
  assert.equal(formatNativeAmount('0x3635c9adc5dea00000'), '1000');
  assert.equal(formatNativeAmount('0x0'), '0');
  assert.equal(formatNativeAmount('0x1'), '<0.000001');
  assert.equal(chainInfo('0x2105').chain, 'base');
  assert.equal(chainInfo('0x89').symbol, 'POL');
  assert.equal(chainInfo('0x9999999'), null);
  assert.throws(()=>chainInfo('0xnot-hex'));
  assert.throws(()=>formatNativeAmount('12.0'));

  const mock=provider();
  assert.equal(metaMaskProvider({ethereum:mock.p}), mock.p);
  assert.equal(phantomProvider({phantom:{solana:{isPhantom:true,connect(){}}}}).isPhantom,true);
  const result=await readEvmBalance(mock.p,ETH);
  assert.equal(result.balance,'1');
  assert.deepEqual(mock.calls,['eth_chainId','eth_getBalance']);
  await assert.rejects(readEvmBalance(mock.p,'notAnAddress'));

  const fake = makeDom();
  const logs=[];
  const {view,calls}=makeView(mock.p,null,{alias:'mm_current'});
  const ui=await initConnectorUI({doc:fake,view,log:(message,cls)=>logs.push([message,cls])});
  assert.ok(fake.elements.saveMeta.disabled,'save disabled until owner clicks Connect');
  assert.equal(calls.length,0,'no RPC / persistence on page load');
  await fake.elements.connectMeta.click();
  assert.equal(fake.elements.metaStatus.textContent,'CONNECTED · READ-ONLY');
  assert.equal(fake.elements.metaBalance.textContent,'1 ETH');
  assert.equal(fake.elements.metaAddress.textContent,ETH.slice(0,8)+'…'+ETH.slice(-6));
  assert.equal(calls.length,0,'connecting alone must not persist addresses');
  await fake.elements.saveMeta.click();
  assert.ok(calls.some(x=>x[0]==='/api/command' && x[1].command===`wallet add mm_current ethereum ${ETH}`));
  mock.setChain('0x999999');
  mock.p.emit('chainChanged','0x999999');
  await new Promise(r=>setImmediate(r));
  assert.equal(fake.elements.saveMeta.disabled,true,'unknown EVM chains cannot save to CLI');
  assert.equal(fake.elements.metaStatus.textContent,'CONNECTED · UNSUPPORTED CHAIN');
  await ui.disconnectMeta();
  assert.equal(fake.elements.metaAddress.textContent,'—');
  assert.equal(fake.elements.refreshMeta.disabled,true);
  assert.ok(mock.calls.every(method=>!method.includes('sign')&&!method.includes('send')&&!method.includes('revoke')));

  const emitter=new EventEmitter();
  const phantomCalls=[];
  const phantomP={
    isPhantom:true,
    on:emitter.on.bind(emitter),
    removeListener:emitter.removeListener.bind(emitter),
    async connect(){phantomCalls.push('connect');return {publicKey:{toString:()=>SOL}};},
    async disconnect(){phantomCalls.push('disconnect');emitter.emit('disconnect');}
  };
  const phantomDom=makeDom();
  const phantomView=makeView(null,phantomP,{alias:'phantom_main'});
  const phantomUi=await initConnectorUI({doc:phantomDom,view:phantomView.view,log:(msg)=>logs.push(msg)});
  await phantomDom.elements.connectPhantom.click();
  assert.equal(phantomDom.elements.phantomBalance.textContent,'2.25 SOL');
  assert.equal(phantomDom.elements.phantomStatus.textContent,'CONNECTED · MAINNET RPC VERIFIED');
  assert.equal(phantomView.calls.filter(x=>x[0]==='/api/wallet/solana-balance').length,1);
  assert.equal(phantomView.calls.filter(x=>x[0]==='/api/command').length,0,'no automatic watchlist write');
  await phantomDom.elements.savePhantom.click();
  assert.ok(phantomView.calls.some(x=>x[0]==='/api/command' && x[1].command===`wallet add phantom_main solana ${SOL}`));
  await phantomUi.disconnectPhantom();
  assert.deepEqual(phantomCalls,['connect','disconnect']);
  assert.equal(phantomDom.elements.phantomBalance.textContent,'— SOL');

  const none = makeDom();
  const missingUi=await initConnectorUI({doc:none,view:makeView(null,null).view});
  await missingUi.connectMeta();
  await missingUi.connectPhantom();
  assert.equal(none.elements.metaStatus.textContent,'EXTENSION NOT DETECTED');
  assert.equal(none.elements.phantomStatus.textContent,'EXTENSION NOT DETECTED');
  const rejecting=provider();
  rejecting.p.request=async ()=>{throw Object.assign(Error('No'),{code:4001});};
  const rejectDoc=makeDom();
  const rejectUi=await initConnectorUI({doc:rejectDoc,view:makeView(rejecting.p,null).view});
  await rejectUi.connectMeta();
  assert.equal(rejectDoc.elements.metaStatus.textContent,'NOT CONNECTED');

  announcedProvider({detail:{info:{rdns:'io.metamask'},provider:mock.p}});
  assert.equal(metaMaskProvider({}), mock.p);
  console.log('Wallet Connector JavaScript tests: PASS (format, discovery, connect, read balance, chain events, save on click, disconnect, reject, no signing).');
}
main().catch(err=>{console.error(err);process.exit(1);});
