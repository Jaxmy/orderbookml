from core.risk import reduction_proposal


def test_proposal_does_not_move_inventory_or_hide_remaining_depth():
    """验证减仓建议不改库存并保留深度不足风险；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    balances={'USDC':'10000','ETH':'1.5'}
    b={'id':'x','available_at':10,'bids_json':'[["100","0.2"]]','asks_json':'[["101","1"]]'}
    r=reduction_proposal('CEX',balances,b,10)
    assert r['estimated_fill_eth']=='0.2'
    assert r['remaining_exposure_eth']=='1.3'
    assert balances['ETH']=='1.5' and not r['executed']
    assert reduction_proposal('CEX',balances,b,14)['status']=='await_valid_depth'


def test_dex_balance_not_sold_on_cex():
    """验证DEX库存不得当作CEX可卖资金；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    r=reduction_proposal('DEX',{'WETH':'1.5','ETH':'.02','USDC':'10000'})
    assert r['estimated_fill_eth']=='0'
    assert r['remaining_exposure_eth']=='1.52'
    assert r['status']=='requires_local_venue_action'
