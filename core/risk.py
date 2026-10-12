"""组件用途：检查超额库存，只有 CEX本地库存且有新鲜深度时估算减仓。只生成建议，不执行或改账；DEX资产不能直接当CEX可卖余额。。"""
from decimal import Decimal as D
from .execution import sweep


def reduction_proposal(venue, balances, book=None, now=None, fee_bps='10'):
    """检查超额库存，只有 CEX本地库存且有新鲜深度时估算减仓。只生成建议，不执行或改账；DEX资产不能直接当CEX可卖余额。

    输入参数：venue、balances、book、now、fee_bps（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Read-only proposal. DEX assets cannot become CEX sellable inventory."""
    exposure=sum(D(str(v)) for a,v in balances.items() if a!='USDC')
    needed=max(D(0),exposure-D(1)) if exposure>D('1.2') else D(0)
    result={'venue':venue,'exposure_eth':str(exposure),'required_reduction_eth':str(needed),
            'estimated_fill_eth':'0','remaining_exposure_eth':str(exposure),'executed':False}
    if not needed:
        return {**result,'status':'within_limit'}
    if venue!='CEX':
        return {**result,'status':'requires_local_venue_action','reason':'DEX inventory is not CEX sellable balance; no transfer assumed'}
    if book is None or now is None or not 0<=now-book['available_at']<=3:
        return {**result,'status':'await_valid_depth'}
    requested=min(needed,D(str(balances.get('ETH',0))))
    if requested<=0:return {**result,'status':'no_sellable_inventory'}
    quote=sweep(book,'sell',requested,fee_bps)
    filled=D(quote['filled'])
    return {**result,'status':'proposal_only','estimated_fill_eth':str(filled),
            'remaining_exposure_eth':str(exposure-filled),'quote':quote,'source_id':book['id']}
