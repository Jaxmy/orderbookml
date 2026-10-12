"""组件用途：整数除法向上取整，用于链上输入和费用保守舍入。；按恒定乘积池及百万分比费率计算精确输入输出，以整数原始 token 单位舍入。。

原始说明：Integer AMM execution and V3 position accounting; raw token units throughout."""
Q96=2**96
Q128=2**128
MOD=2**256

def ceildiv(a,b):
    """整数除法向上取整，用于链上输入和费用保守舍入。

    输入参数：a、b（单位和范围由下方校验及调用方契约限定）。"""
    return (a+b-1)//b

def v2_exact_input(amount,reserve_in,reserve_out,fee_pips=3000):
    """按恒定乘积池及百万分比费率计算精确输入输出，以整数原始 token 单位舍入。

    输入参数：amount、reserve_in、reserve_out、fee_pips（单位和范围由下方校验及调用方契约限定）。"""
    if min(amount,reserve_in,reserve_out)<=0 or not 0<=fee_pips<1_000_000:
        raise ValueError('Invalid reserves/input/fee')
    weighted=amount*(1_000_000-fee_pips)
    return weighted*reserve_out//(reserve_in*1_000_000+weighted)

def amount0_delta(a,b,liquidity,round_up):
    """依据两端平方根价、Q96和流动性计算 token0区间数量，按指定方向上下舍入。

    输入参数：a、b、liquidity、round_up（单位和范围由下方校验及调用方契约限定）。"""
    a,b=sorted((a,b))
    numerator=liquidity*Q96*(b-a)
    return ceildiv(numerator,a*b) if round_up else numerator//(a*b)

def amount1_delta(a,b,liquidity,round_up):
    """依据平方根价差和流动性计算 token1区间数量，按指定方向舍入。

    输入参数：a、b、liquidity、round_up（单位和范围由下方校验及调用方契约限定）。"""
    value=liquidity*abs(b-a)
    return ceildiv(value,Q96) if round_up else value//Q96

def v3_exact_input(sqrt_price,liquidity,amount,zero_for_one,boundaries,fee_pips=500):
    """逐个已知初始化边界计算输入/输出和向上舍入池费，跨 tick 更新净流动性；到最后已知边界停止，绝不虚构未知深度。

    输入参数：sqrt_price、liquidity、amount、zero_for_one、boundaries、fee_pips（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Boundaries: [(sqrtPriceX96, liquidityNet), ...] in execution order.
    
        Must be complete up to requested price limit. Stops conservatively at last supplied
        boundary; never invents liquidity beyond known initialized ticks. Fee rounded UP."""
    if min(sqrt_price,liquidity,amount)<=0 or not 0<=fee_pips<1_000_000:
        raise ValueError('Invalid swap')
    left,output,fees,crossed=amount,0,0,0
    s,L=sqrt_price,liquidity
    for target,net in boundaries:
        if target<=0 or (target>=s if zero_for_one else target<=s):
            raise ValueError('Boundary order')
        if L<=0: break
        needed=amount0_delta(target,s,L,True) if zero_for_one else amount1_delta(s,target,L,True)
        usable=left*(1_000_000-fee_pips)//1_000_000
        if usable>=needed:
            after=target
            fee=ceildiv(needed*fee_pips,1_000_000-fee_pips)
            spent=needed+fee
        else:
            after=ceildiv(L*Q96*s,L*Q96+usable*s) if zero_for_one else s+usable*Q96//L
            spent=left
            fee=left-usable
        output += amount1_delta(after,s,L,False) if zero_for_one else amount0_delta(s,after,L,False)
        left-=spent; fees+=fee; s=after
        if after==target:
            L += -net if zero_for_one else net
            if L<0: raise ValueError('Negative liquidity after crossing')
            crossed+=1
        if left==0: break
    return dict(amount_in=amount-left,amount_out=output,fee=fees,remaining=left,
        complete=left==0,sqrt_price_after=s,liquidity_after=L,ticks_crossed=crossed)

def fee_growth_inside(global_growth,lower_outside,upper_outside,current_tick,lower_tick,upper_tick):
    """根据当前 tick位置从全球增长减去区间外增长，使用 uint256模运算还原区间内手续费累计。

    输入参数：global_growth、lower_outside、upper_outside、current_tick、lower_tick、upper_tick（单位和范围由下方校验及调用方契约限定）。"""
    if lower_tick>=upper_tick: raise ValueError('Invalid tick range')
    below=lower_outside if current_tick>=lower_tick else (global_growth-lower_outside)%MOD
    above=upper_outside if current_tick<upper_tick else (global_growth-upper_outside)%MOD
    return (global_growth-below-above)%MOD

def accrued_fees(liquidity,inside_before,inside_after):
    """将流动性乘区间内手续费增长差，再除 Q128；模运算处理累计值回绕。

    输入参数：liquidity、inside_before、inside_after（单位和范围由下方校验及调用方契约限定）。"""
    if liquidity<0: raise ValueError('Negative liquidity')
    return liquidity*((inside_after-inside_before)%MOD)//Q128

def lp_attribution(value_start,value_end,hodl_end,fees_quote,gas_quote):
    """将仓位资产变化、对持币差额、手续费与gas分开归因，返回总盈亏及超额收益。

    输入参数：value_start、value_end、hodl_end、fees_quote、gas_quote（单位和范围由下方校验及调用方契约限定）。"""
    if min(value_start,value_end,hodl_end,fees_quote,gas_quote)<0: raise ValueError('Invalid values')
    return dict(inventory_pnl=value_end-value_start,divergence_vs_hodl=value_end-hodl_end,
        fee_income=fees_quote,gas_cost=gas_quote,total_pnl=value_end-value_start+fees_quote-gas_quote,
        excess_vs_hodl=value_end-hodl_end+fees_quote-gas_quote)
