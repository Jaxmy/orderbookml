"""组件用途：检查 CEX/DEX报价新鲜度、方向、规模和同区块，在两条相反路线扣一次交易所费与gas。返回纸面净差，不保证非原子双腿成交。。"""
from decimal import Decimal as D
from .execution import sweep

def opportunity(book,dex_sell,dex_buy,quantity,now,fee_bps=10,max_age=3,max_dex_age=30,gas_usdc='0'):
    """检查 CEX/DEX报价新鲜度、方向、规模和同区块，在两条相反路线扣一次交易所费与gas。返回纸面净差，不保证非原子双腿成交。

    输入参数：book、dex_sell、dex_buy、quantity、now、fee_bps、max_age、max_dex_age、gas_usdc（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Executable quote already includes pool fees/price impact. Charge gas only once."""
    if not 0<=now-book['available_at']<=max_age:
        return {'status':'rejected','reason':'cex_stale_or_future'}
    if any(not 0<=now-r['available_at']<=max_dex_age for r in [dex_sell,dex_buy]):
        return {'status':'rejected','reason':'dex_stale_or_future'}
    if any(D(str(r['quantity']))!=D(str(quantity)) for r in [dex_sell,dex_buy]):
        raise ValueError('Quote size mismatch')
    if dex_sell['side']!='sell' or dex_buy['side']!='buy': raise ValueError('Wrong quote side')
    if dex_sell.get('block_hash')!=dex_buy.get('block_hash'): raise ValueError('Mixed blocks')
    buy,sell=sweep(book,'buy',quantity,fee_bps),sweep(book,'sell',quantity,fee_bps)
    if not buy['complete'] or not sell['complete']:
        return {'status':'rejected','reason':'insufficient_visible_depth'}
    routes={
      'buy_cex_sell_dex':D(dex_sell['quote_usdc'])-D(buy['quote'])-D(buy['fee'])-D(gas_usdc),
      'buy_dex_sell_cex':D(sell['quote'])-D(sell['fee'])-D(dex_buy['quote_usdc'])-D(gas_usdc)}
    return dict(status='quoted',net_usdc={k:str(v) for k,v in routes.items()},
        cex_buy=buy,cex_sell=sell,gas_usdc=str(gas_usdc),
        execution='paper only; requires prefunded balances on each venue and non-atomic leg risk')
