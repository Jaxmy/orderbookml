"""把计算失败转换成可读原因；不向界面输出堆栈、工程路径或连接凭据。"""
import re


def describe_failure(error, chinese=False):
    """接收异常或任务保存的错误文本，翻译常见原因；未识别错误保留原因正文而非只显示失败。"""
    message = str(error or '').strip()
    message = re.sub(r'^\w*(?:Error|Exception):\s*', '', message)
    day = re.search(r'\b\d{4}-\d{2}-\d{2}\b', message)
    date_label = day.group() if day else ('所选日期' if chinese else 'the selected date')
    if 'Upload the official OKX' in message:
        return (f'缺少 {date_label}（UTC）的 OKX 历史盘口。请先在“交易所比较”页上传该日档案。' if chinese else
                f'OKX historical order books are missing for {date_label} (UTC). Upload that day’s archive on Exchange comparison first.')
    translations = {
        'Historical pool events are unavailable from this RPC; use an archive RPC supporting eth_getLogs or supply an event file': '当前节点不能提供该窗口的历史池事件，需要支持历史日志查询的归档节点或事件文件。',
        'Code changed after submission; repeat with the current version': '提交后程序版本已改变。请使用当前版本复跑，原实验记录会保留。',
        'Previous worker stopped before the experiment finished': '后台进程在实验完成前停止。原参数已保存，可创建新的实验继续。',
        'Explicitly accept WETH settlement to compare Uniswap; ETH wrapping is not included': '请先确认接受 Uniswap 使用 WETH 结算；此处不计算 ETH 包装或解包。',
        'Invalid order amount mode or side': '订单方向或金额单位无效，请重新选择买卖方向及 USDC 预算／ETH 数量。',
        'Invalid date range or increment': '日期范围或数量步长无效，请选择最多七天的日期范围及正数步长。',
        'Sell orders require an ETH quantity': '卖单需要填写 ETH 数量。',
        'Selected start time is outside the available historical observations': '开始时间超出已有历史数据范围，请选择有数据的时刻。',
        'Selected execution horizon extends beyond available data; shorten the horizon': '执行期限超过历史数据覆盖范围，请缩短期限或补充后续日期的数据。',
        'No reconstructed book records in selected dates': '所选日期没有可用于模拟的历史盘口。',
        'Execution window must be fully covered by the selected historical day': '执行窗口必须完整落在所选日期的历史数据范围内。',
        'Choose a positive ETH quantity exactly divisible by the quantity step': 'ETH 数量必须大于零，并且是数量步长的整数倍。',
        'No causal, fresh Bybit/OKX book pairs overlap on the selected date': '所选日期没有可同时比较的新鲜 Bybit 与 OKX 盘口，请更换日期或调整报价有效时间。',
        'Frozen model can only be applied after its validation-label cutoff; use persistence fallback for earlier dates.': '该预测模型只能用于训练验证结束之后的日期；较早日期请选择“延续近期行情”。',
        'Base quantity is too small for the selected number of slices at this precision': 'ETH 数量过小，无法按当前数量步长分成这么多批次，请减少分批次数或调整数量。',
    }
    if chinese and message in translations:
        return translations[message]
    if not message:
        return ('任务没有记录具体原因，请重新运行；若仍失败，请提供所选日期和订单参数。' if chinese else
                'No reason was recorded. Try again; if it fails, provide the selected date and order parameters.')
    # 未知错误仍显示原因；仅屏蔽内部路径、网址凭据/查询参数和可能的口令，不吞掉实际错误信息。
    message = re.sub(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\n\r\s\'\"]+', '[local file]', message)
    message = re.sub(r'(https?://)([^/\s@]+@)', r'\1', message)
    message = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1', message)
    message = re.sub(r'(?i)(password|api[_-]?key|token|secret)\s*[=:]\s*[^\s,;]+', r'\1=[hidden]', message)
    return message.splitlines()[0]
