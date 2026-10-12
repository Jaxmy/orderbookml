"""组件用途：只读查询 Binance市场元数据，确认 ETH/USDC标的有效并返回交易规则。；把实时深度消息转标准盘口，接收时钟作为 available_at，校验后输出唯一 id。。

原始说明：Read-only RPC adapter. No keys, signing, transaction submission or approvals."""
import asyncio
import json
import os
import time
import urllib.request
from decimal import Decimal
from web3 import Web3
from websockets.asyncio.client import connect
from .execution import validate_book


def rest_check(config):
    """只读查询 Binance市场元数据，确认 ETH/USDC标的有效并返回交易规则。

    输入参数：config（单位和范围由下方校验及调用方契约限定）。"""
    req = urllib.request.Request(config['rest_url']+'/exchangeInfo?symbol='+config['symbol'], headers={'User-Agent':'execution-replay/1'})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    symbol = next(s for s in data['symbols'] if s['symbol'] == config['symbol'])
    if symbol['status'] != 'TRADING' or symbol['baseAsset'] != 'ETH' or symbol['quoteAsset'] != 'USDC':
        raise ValueError('Unexpected or inactive market')
    return dict(symbol=symbol['symbol'], status=symbol['status'], filters=symbol['filters'])


def book_row(payload, received):
    """把实时深度消息转标准盘口，接收时钟作为 available_at，校验后输出唯一 id。

    输入参数：payload、received（单位和范围由下方校验及调用方契约限定）。"""
    row = dict(id=f"cex-{payload['lastUpdateId']}-{received:.6f}", available_at=received,
               update_id=str(payload['lastUpdateId']), bids_json=json.dumps(payload['bids']),
               asks_json=json.dumps(payload['asks']))
    validate_book(row)
    return row


async def ws_check(config):
    """连接公开行情WebSocket读取一条深度并校验，超时抛错；不登录交易账户。

    输入参数：config（单位和范围由下方校验及调用方契约限定）。"""
    async with connect(config['ws_url'], open_timeout=20, ping_interval=20, max_size=2**20) as ws:
        row = book_row(json.loads(await asyncio.wait_for(ws.recv(), 20)), time.time())
    return dict(ok=True, sample=row)


class DexReader:
    """只读以太坊池状态和Quoter适配器，所有调用固定区块；不包含私钥、签名或提交交易。"""
    def __init__(self, config):
        """由环境变量或默认URL初始化只读RPC客户端，保留配置，池地址等待元数据验证。

        输入参数：config（单位和范围由下方校验及调用方契约限定）。"""
        self.config = config
        self.w3 = Web3(Web3.HTTPProvider(os.environ.get(config['rpc_env'], config['rpc_default']), request_kwargs={'timeout':20}))
        self.pool = None

    def call(self, address, signature, inputs, args, outputs, block):
        """拼ABI函数选择器和参数，固定 block执行 eth_call后解码返回值，不写链上状态。

        输入参数：address、signature、inputs、args、outputs、block（单位和范围由下方校验及调用方契约限定）。"""
        data = self.w3.keccak(text=signature)[:4] + self.w3.codec.encode(inputs, args)
        raw = self.w3.eth.call({'to':Web3.to_checksum_address(address),'data':data}, block_identifier=block)
        return self.w3.codec.decode(outputs, raw)

    def verify(self):
        """验证网络和合约代码，查询工厂池地址及token顺序、费率、精度和tick间距；不符合预设则拒绝。"""
        c, w = self.config, self.w3
        if w.eth.chain_id != c['chain_id']:
            raise ValueError('Wrong network')
        block = w.eth.block_number
        for name in ('factory','quoter','weth','usdc'):
            if not w.eth.get_code(Web3.to_checksum_address(c[name]), block_identifier=block):
                raise ValueError('Contract missing: '+name)
        pool = self.call(c['factory'],'getPool(address,address,uint24)', ['address','address','uint24'],
                         [c['weth'],c['usdc'],c['fee']], ['address'],block)[0]
        if int(pool,16) == 0:
            raise ValueError('Pool not found')
        self.pool = Web3.to_checksum_address(pool)
        token0 = self.call(pool,'token0()',[],[],['address'],block)[0]
        token1 = self.call(pool,'token1()',[],[],['address'],block)[0]
        if [token0.lower(),token1.lower()] != [c['usdc'].lower(),c['weth'].lower()]:
            raise ValueError('Unexpected token order')
        fee = self.call(pool,'fee()',[],[],['uint24'],block)[0]
        spacing = self.call(pool,'tickSpacing()',[],[],['int24'],block)[0]
        decimals = [self.call(c[n],'decimals()',[],[],['uint8'],block)[0] for n in ('usdc','weth')]
        if fee != c['fee'] or decimals != [6,18] or spacing != 10:
            raise ValueError('Unexpected pool metadata')
        return dict(chain_id=w.eth.chain_id, block=block, pool=self.pool, token0=token0,token1=token1,
                    fee=fee,tick_spacing=spacing,decimals=decimals)

    def sample(self):
        """同一固定最新区块读取slot0、流动性和各规模双向报价；结束复核区块hash，若重组则整组拒绝。接收后才标为可用。"""
        if self.pool is None:
            self.verify()
        c,w = self.config,self.w3
        b = w.eth.get_block('latest')
        block = b['number']
        slot = self.call(self.pool,'slot0()',[],[],['uint160','int24','uint16','uint16','uint16','uint8','bool'],block)
        liquidity = self.call(self.pool,'liquidity()',[],[],['uint128'],block)[0]
        rows = []
        for size in c['sizes']:
            amount = int(Decimal(size)*10**18)
            for side in ('buy','sell'):
                buy = side == 'buy'
                sig = ('quoteExactOutputSingle' if buy else 'quoteExactInputSingle')+'((address,address,uint256,uint24,uint160))'
                args = (c['usdc'] if buy else c['weth'], c['weth'] if buy else c['usdc'], amount,c['fee'],0)
                quoted, after, crossed, estimate = self.call(c['quoter'],sig,
                    ['(address,address,uint256,uint24,uint160)'],[args],['uint256','uint160','uint32','uint256'],block)
                rows.append(dict(id=f'dex-{block}-{side}-{size}', side=side,quantity=size,
                                 quote_usdc=str(Decimal(quoted)/10**6), quote_raw=str(quoted),
                                 sqrt_price_after=str(after), ticks_crossed=crossed,quoter_gas_estimate=estimate))
        # Reject a block hash changed during a multi-call sample; no silent reorg mixing.
        if w.eth.get_block(block)['hash'] != b['hash']:
            raise ValueError('Block changed during sample')
        received=time.time()
        for row in rows:
            row.update(available_at=received,block_number=block,block_hash=b['hash'].hex(),
                       block_time=float(b['timestamp']),base_fee_wei=str(b['baseFeePerGas']),
                       sqrt_price_x96=str(slot[0]),tick=slot[1],liquidity=str(liquidity),pool=self.pool,
                       group_id=f'dex-{block}-{received:.6f}')
        return rows
