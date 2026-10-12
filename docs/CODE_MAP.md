# 代码阅读索引

坐标按最终源码定义行生成。点击链接先读函数/类的中文说明，再沿内部调用追踪。
只索引项目自有 Python：根目录、core、tests；不修改第三方库或冻结产物。
运行脚本没有函数的，入口为文件模块顶层。方法与内嵌回调同样列出。
覆盖：84 个文件，376 个函数/类定义（包含方法和嵌套函数）。

## analyze.py

[文件入口](../analyze.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [run](../analyze.py#L14) | 14 | 核验采集清单、清洗盘口、生成质量和执行报告；数据及窗口满足要求才训练或做独立外部评价，记录资源。 |

## analyze_dex_history.py

[文件入口](../analyze_dex_history.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [analyze](../analyze_dex_history.py#L11) | 11 | 核验四小时池状态摘要，重建假设LP资产及手续费，逐点对比链上和CEX报价；不是全周逐事件回放。 |

## analyze_trades.py

[文件入口](../analyze_trades.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## app.py

[文件入口](../app.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [read](../app.py#L18) | 18 | 读取早期看板可选JSON，文件缺失返回None供页面提示。 |
| [frame](../app.py#L24) | 24 | 读取早期看板Parquet表，文件缺失返回空表，不创造行情。 |

## audit_results.py

[文件入口](../audit_results.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## collect.py

[文件入口](../collect.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [preflight](../collect.py#L17) | 17 | 并行检查公开REST、WebSocket及RPC，把结果和错误类型写日志；拒绝凭据URL回显。 |
| [preflight.check](../collect.py#L22) | 22 | 等待单个连通性任务，将成功结果或不含凭据的错误分类放入预检字典。 |
| [preflight.dex](../collect.py#L32) | 32 | 在后台线程核验链上元数据并读取一组同区块报价。 |
| [capture](../collect.py#L42) | 42 | 校验新窗口和项目内输出路径，预留全局容量，采集只读数据并最终保存Parquet/清单；不覆盖冻结产物。 |
| [capture.save](../collect.py#L65) | 65 | 向raw.jsonl追加单条观测，累计字节超预留时设置停止事件，避免无界写入。 |
| [capture.fail](../collect.py#L76) | 76 | 将组件和异常类型记录到最多一千条错误列表，避免泄露凭据和无限增长。 |
| [capture.cex](../collect.py#L84) | 84 | 在窗口内读取公开盘口，每秒保留一条有效接收记录；断开重连并遵守停止事件。 |
| [capture.dex](../collect.py#L101) | 101 | 按一分钟时隙读取同区块报价，过窗口或容量停止则退出。 |
| [main](../collect.py#L127) | 127 | 解析采集/预检/烟测命令参数，核验外部冻结窗口，调用异步流程并返回状态码。 |

## core/__init__.py

[文件入口](../core/__init__.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## core/acceptance.py

[文件入口](../core/acceptance.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [register_acceptance](../core/acceptance.py#L20) | 20 | 在读取测试行情前锁定日期、模型、代码和八个固定订单场景；已缓存/已注册日期拒绝。 |
| [evaluate_acceptance](../core/acceptance.py#L57) | 57 | 一次性打开已登记日：先写 opened，再下载/核验、预测评分与八场景回放，绝不重新训练。 |
| [list_acceptance](../core/acceptance.py#L115) | 115 | 列出登记、是否打开及结果/失败状态供看板检索；不会重新评价已打开的窗口。 |
| [submit_acceptance](../core/acceptance.py#L126) | 126 | 看板先登记再提交串行后台验收，返回id以便页面刷新后轮询，不阻塞页面下载。 |
| [_acceptance_worker](../core/acceptance.py#L135) | 135 | 后台执行已锁验收，将下载进度、结果、取消或失败写到本次独立job.json。 |
| [_acceptance_worker.progress](../core/acceptance.py#L138) | 138 | 把下载/样本/回放阶段进度持久化；只含运行状态，不写RPC凭据或模型输入标签。 |
| [acceptance_job](../core/acceptance.py#L151) | 151 | 校验标识后回读后台状态，供Streamlit定时片段显示；不存在则返回None。 |
| [cancel_acceptance](../core/acceptance.py#L159) | 159 | 对本进程中的验收设置取消事件；已打开的测试不因此恢复为未使用日期。 |

## core/arbitrage.py

[文件入口](../core/arbitrage.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [opportunity](../core/arbitrage.py#L5) | 5 | 检查 CEX/DEX报价新鲜度、方向、规模和同区块，在两条相反路线扣一次交易所费与gas。返回纸面净差，不保证非原子双腿成交。 |

## core/chain_history.py

[文件入口](../core/chain_history.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [block_at](../core/chain_history.py#L15) | 15 | 二分查找时间戳不晚于指定 UTC 秒的最后区块；仅访问公共区块，不插值交易时间。 |
| [decode_event](../core/chain_history.py#L26) | 26 | 解码一次 Swap/Mint/Burn，保存交易与日志顺序；Swap 数量是池资金变化，不冒充用户净钱包变化。 |
| [extract_events](../core/chain_history.py#L45) | 45 | 下载最多一小时的单池 Swap/Mint/Burn 和起始池状态；分批读日志，区块 hash 对照，受全局容量限制。 |
| [compare_channels](../core/chain_history.py#L91) | 91 | 比较固定数量的 CEX 主动成交和 Uniswap WETH 兑换含 gas 成本；固定过去区块，不把历史未来区块当已知。 |

## core/conditional_model.py

[文件入口](../core/conditional_model.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [_top](../core/conditional_model.py#L38) | 38 | 校验盘口并取前五档浮点价格与数量，供条件特征汇总；与成交引擎的 Decimal 计算分离。 |
| [_day_samples](../core/conditional_model.py#L47) | 47 | 把一日盘口向后对齐到秒格，构造过去特征和买卖方向/数量/期限条件；未来行仅计算标签。过滤缺失、陈旧或深度不足窗口。 |
| [build_training_frames](../core/conditional_model.py#L127) | 127 | 只载入预定训练日及验证日；标签终点触及分区边界的样本剔除。返回两张样本表和来源/时间边界清单，不读取最终测试日。 |
| [datetime_iso](../core/conditional_model.py#L149) | 149 | 将 Unix 秒转换为明确 UTC 的 ISO 时间字符串，用于模型时间边界记录。 |
| [train_conditional_model](../core/conditional_model.py#L156) | 156 | 每目标在训练集拟合 Ridge/提升树，在时间验证集与 persistence 比 MAE；选型后仅重拟合训练加验证，写新版本权重及摘要。失败模型不强行替代基线。 |
| [load_conditional_model](../core/conditional_model.py#L234) | 234 | 校验模型标识、冻结状态和本地权重摘要后加载；不接受任意外部 pickle 或静默改写权重。 |
| [predict_conditional](../core/conditional_model.py#L250) | 250 | 校验特征契约并使用冻结模型预测；未保留模型的目标使用当前成本/历史波动基线，输出模型版本。 |
| [live_feature_row](../core/conditional_model.py#L272) | 272 | 只从当前簿与过去一分钟价格生成十二项条件特征，检查连续性、可见深度和训练期限；不能把未来标签当输入。 |
| [live_feature_row.asof](../core/conditional_model.py#L296) | 296 | 从已经截断的历史序列找不晚于目标的中间价；缺观测或间隔超过三秒返回 None。 |
| [predict_with_models](../core/conditional_model.py#L330) | 330 | 按冻结特征顺序组成表格并限制线程数，批量调用各目标模型；缺模型的目标由上层补基线。 |
| [list_conditional_models](../core/conditional_model.py#L339) | 339 | 枚举本地冻结版本清单并按创建时间倒序；不训练、加载全量行情或更改任何权重。 |

## core/cross_venue.py

[文件入口](../core/cross_venue.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [_digest](../core/cross_venue.py#L38) | 38 | 分块计算文件 SHA-256，用于下载、上传和规范化来源核验。 |
| [_market_dir](../core/cross_venue.py#L49) | 49 | 将标准 ETHUSDC 映射为各所原生目录名称，OKX 使用 ETH-USDC；按场所和日期隔离。 |
| [download_binance_trade_archive](../core/cross_venue.py#L57) | 57 | 有界下载 Binance 官方逐笔成交 ZIP，预留存储并支持取消；不声称此档案含历史 L2。 |
| [normalize_binance_trades](../core/cross_venue.py#L121) | 121 | 流式清洗官方成交日档，识别时间单位、重复和乱序，批量写 Parquet 与清单；保留主动方向，不生成盘口。 |
| [ingest_okx_upload](../core/cross_venue.py#L230) | 230 | 校验看板上传的官方日档文件名和容量，流式写项目缓存，已有档案按摘要判断复用或拒绝覆盖。 |
| [prepare_cross_venue_data](../core/cross_venue.py#L282) | 282 | 依次取得 Bybit L2、OKX L2及 Binance 成交的已验证同日文件和清单。 |
| [_book_path](../core/cross_venue.py#L295) | 295 | 仅返回对应场所日档已规范化且摘要匹配的 L2；缺失或篡改均停止。 |
| [_trade_path](../core/cross_venue.py#L310) | 310 | 核验 Binance 成交 Parquet 与来源清单，返回合法路径；不能用它代替订单簿。 |
| [_asof_trade_context](../core/cross_venue.py#L324) | 324 | 把较早已知 Binance 成交向后对齐到跨所盘口时点，加入成交价参照并限制陈旧度；未来成交不可进入。 |
| [analyze_cross_venue](../core/cross_venue.py#L347) | 347 | 同日 Bybit/OKX 簿按因果时间对齐，双向模拟买卖腿并各扣一次费用；输出快照机会和质量，不累计重叠时点成策略收益。 |
| [_job_path](../core/cross_venue.py#L506) | 506 | 校验跨所任务标识，限制结果路径在固定运行根目录。 |
| [_save_job](../core/cross_venue.py#L515) | 515 | 锁内更新跨所任务状态并写磁盘，使刷新后能继续查看。 |
| [_cross_worker](../core/cross_venue.py#L526) | 526 | 串行后台完成准备和同窗分析，分别记录完成、取消和失败；结果与任务 id 绑定。 |
| [_cross_worker.progress](../core/cross_venue.py#L539) | 539 | 按阶段底线和完成数量计算跨所进度，持久化当前提示供页面轮询。 |
| [submit_cross_venue](../core/cross_venue.py#L594) | 594 | 创建排队记录和取消事件，提交单线程执行器，立即向看板返回任务 id。 |
| [get_cross_job](../core/cross_venue.py#L610) | 610 | 从内存或磁盘恢复指定跨所任务，非法或不存在返回 None。 |
| [get_cross_report](../core/cross_venue.py#L624) | 624 | 只读取已完成任务且位于项目允许目录的报告，缺失或路径非法返回 None。 |
| [cancel_cross_job](../core/cross_venue.py#L639) | 639 | 请求仍在本进程的跨所任务取消，通过事件在下载或分析检查点停止。 |
| [recent_cross_jobs](../core/cross_venue.py#L655) | 655 | 读取最近跨所任务的持久状态，按创建时间倒序供看板恢复和导出。 |

## core/dashboard_errors.py

[文件入口](../core/dashboard_errors.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [describe_failure](../core/dashboard_errors.py#L5) | 5 | 接收异常或任务保存的错误文本，翻译常见原因；未识别错误保留原因正文而非只显示失败。 |

## core/defi.py

[文件入口](../core/defi.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [ceildiv](../core/defi.py#L8) | 8 | 整数除法向上取整，用于链上输入和费用保守舍入。 |
| [v2_exact_input](../core/defi.py#L14) | 14 | 按恒定乘积池及百万分比费率计算精确输入输出，以整数原始 token 单位舍入。 |
| [amount0_delta](../core/defi.py#L23) | 23 | 依据两端平方根价、Q96和流动性计算 token0区间数量，按指定方向上下舍入。 |
| [amount1_delta](../core/defi.py#L31) | 31 | 依据平方根价差和流动性计算 token1区间数量，按指定方向舍入。 |
| [v3_exact_input](../core/defi.py#L38) | 38 | 逐个已知初始化边界计算输入/输出和向上舍入池费，跨 tick 更新净流动性；到最后已知边界停止，绝不虚构未知深度。 |
| [fee_growth_inside](../core/defi.py#L76) | 76 | 根据当前 tick位置从全球增长减去区间外增长，使用 uint256模运算还原区间内手续费累计。 |
| [accrued_fees](../core/defi.py#L85) | 85 | 将流动性乘区间内手续费增长差，再除 Q128；模运算处理累计值回绕。 |
| [lp_attribution](../core/defi.py#L92) | 92 | 将仓位资产变化、对持币差额、手续费与gas分开归因，返回总盈亏及超额收益。 |

## core/execution.py

[文件入口](../core/execution.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [money](../core/execution.py#L11) | 11 | 把金额按既定精度量化，统一吃单报价和手续费的舍入规则。 |
| [levels](../core/execution.py#L18) | 18 | 将指定方向的 JSON 档位转成 Decimal 价格/数量列表；合法性和二十档上限由 validate_book 检查。 |
| [validate_book](../core/execution.py#L26) | 26 | 解析买卖盘，检查排序及买一低于卖一，拒绝空簿、非法量价和交叉盘口；返回两侧 Decimal 档位。 |
| [mid](../core/execution.py#L44) | 44 | 校验盘口后计算买一与卖一的算术平均，作为成本比较参考价，不是可成交价。 |
| [sweep](../core/execution.py#L52) | 52 | 按买入吃卖盘、卖出吃买盘逐档撮合，累计金额和费率，输出明细、均价和缺量；深度不足不外推成交。 |
| [dex_cost](../core/execution.py#L77) | 77 | 读取已含池费的链上兑换报价，按 gas 用量、基础费及优先费折算 ETH/USDC 成本；不重复扣池费。 |

## core/experiment_engine.py

[文件入口](../core/experiment_engine.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [_bytes](../core/experiment_engine.py#L43) | 43 | 累计目录文件大小，忽略遍历期间已消失的文件，供五十亿字节资源预检使用。 |
| [local_days](../core/experiment_engine.py#L58) | 58 | 汇总本机 Bybit 已规范化日期，返回有序去重列表供看板选择缓存。 |
| [probe_latest](../core/experiment_engine.py#L68) | 68 | 从最近过去日期向前检查公开 Bybit 日档 HEAD，检查长度预算并返回首个可用来源；保留失败原因，不把实时接口当历史数据。 |
| [_resolve_book](../core/experiment_engine.py#L91) | 91 | 定位已有旧目录或新市场缓存，核验清单与盘口哈希；已有文件不符时拒绝而非悄悄重建覆盖。 |
| [_prepare_day](../core/experiment_engine.py#L119) | 119 | 复用经验证的缓存或下载受大小限制日档，检查 ZIP CRC，流式应用快照/增量，每秒输出首个有效前二十档视图。进度/取消由回调与事件控制。 |
| [_unit_sweep](../core/experiment_engine.py#L272) | 272 | 检查正数量并调用共用逐档吃单引擎，统一数量和费率格式。 |
| [_budget_sweep](../core/experiment_engine.py#L281) | 281 | 在可见深度范围对整数数量步长二分，找含费不超 USDC 预算的最大买入量；预算模式不支持卖单。 |
| [_fill_at](../core/experiment_engine.py#L310) | 310 | 按下单时点加延迟，在事件时间序列向后查盘口；缺簿和陈旧分别返回拒单原因。 |
| [_simulate](../core/experiment_engine.py#L326) | 326 | 模拟立即或等额父单切片，逐切片计费用、缺量、预算余量与参考价偏差；这是旧 P1 基线，不是求解器。 |
| [run_experiment](../core/experiment_engine.py#L442) | 442 | 校验市场、时区、规模和最长窗口，逐日准备缓存后运行 P1 立即/分批对照并返回数据质量及完成率报告。 |
| [_job_path](../core/experiment_engine.py#L533) | 533 | 校验实验 id 只允许固定长度字母数字，拼接项目内运行目录，阻止路径穿越。 |
| [_save_job](../core/experiment_engine.py#L542) | 542 | 在锁内更新内存状态副本，再写 job.json，供看板轮询与刷新恢复。 |
| [_worker](../core/experiment_engine.py#L553) | 553 | 后台执行单个实验，保存结果并将成功、取消或异常明确记录到状态和事件日志。 |
| [_worker.progress](../core/experiment_engine.py#L562) | 562 | 将数据/下载/规范化回调映射为页面进度和提示，更新持久任务状态。 |
| [submit](../core/experiment_engine.py#L603) | 603 | 生成新运行 id、取消事件并提交串行线程池；返回 id，不在页面线程执行长下载。 |
| [get_job](../core/experiment_engine.py#L615) | 615 | 优先读内存副本，服务重启后回读 job.json；无此任务或标识非法返回 None。 |
| [get_result](../core/experiment_engine.py#L629) | 629 | 校验运行 id 后读取已落盘结果，缺文件返回 None。 |
| [cancel](../core/experiment_engine.py#L640) | 640 | 给本进程仍可控制的任务设置取消事件并更新提示；进程已丢失的任务不会伪造取消成功。 |
| [recent_jobs](../core/experiment_engine.py#L656) | 656 | 枚举已保存任务状态，跳过损坏记录，按创建时间返回最近记录供看板历史列表。 |

## core/flow.py

[文件入口](../core/flow.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [aggregate_trades](../core/flow.py#L7) | 7 | 按时间桶汇总成交量、名义额、主动方向和RPI占比；桶结束才标为可用，避免提前读取整桶未来成交。 |

## core/io.py

[文件入口](../core/io.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [utcnow](../core/io.py#L11) | 11 | 生成带 UTC 时区的当前时间字符串，作为日志、清单和实验创建时间；不代表交易所事件时间。 |
| [sha](../core/io.py#L16) | 16 | 以 1MB 分块读取文件并累计 SHA-256；返回十六进制摘要，避免把整个归档加载入内存。 |
| [dump](../core/io.py#L27) | 27 | 创建目标父目录，把对象写为 UTF-8 JSON；禁止 NaN/Infinity，非 JSON 原生类型转字符串。会覆盖指定文件，调用方负责冻结目录保护。 |
| [read](../core/io.py#L36) | 36 | 读取指定 UTF-8 JSON 并反序列化；文件不存在或格式损坏时向调用方抛错。 |
| [code_hash](../core/io.py#L43) | 43 | 按文件名顺序把根目录和 core 的 Python 文件名及字节纳入摘要；注释修改也改变版本摘要。 |
| [manifest](../core/io.py#L53) | 53 | 统计当前目录 Parquet/JSONL 的哈希，加入窗口、配置、版本和错误后写 manifest.json；原始来源说明属于早期采集流程。 |
| [verified_manifest](../core/io.py#L68) | 68 | 读取清单并逐文件验证摘要，阻止清单路径逃出父目录；任一内容不符即拒绝继续分析。 |
| [log](../core/io.py#L81) | 81 | 追加一行带 UTC 时间和事件字段的 JSON 日志，不改写既有事件；调用方不得传入敏感凭据。 |

## core/ledger.py

[文件入口](../core/ledger.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [Ledger](../core/ledger.py#L8) | 8 | 为单一场所维护资产、成本基础、费用与拒单事件；ETH/WETH与gas资产分开，不假设跨场所转移。 |
| [Ledger.__init__](../core/ledger.py#L10) | 10 | 建立 CEX 或 DEX 的演示初始资金及参考成本，记录初始权益、已处理 id 和止损暂停状态。 |
| [Ledger.equity](../core/ledger.py#L26) | 26 | 用参考价估值所有非 USDC 资产并加现金，返回 Decimal 账面权益，不代表已经卖出。 |
| [Ledger.status](../core/ledger.py#L32) | 32 | 基于当前余额和成本基础计算已实现/未实现盈亏、费用及恒等式误差，并输出库存。 |
| [Ledger.apply](../core/ledger.py#L45) | 45 | 先校验成交和去重，再检查止损、现金底线、资产余额；通过后记费用和资金变化，否则保留拒单事件且库存不变。 |
| [reconcile](../core/ledger.py#L86) | 86 | 独立按成交方向汇总资金流与gas，不调用 Ledger.apply；检测重复和容差内余额差，返回重建账目。 |

## core/limit_optimizer.py

[文件入口](../core/limit_optimizer.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [_limit](../core/limit_optimizer.py#L19) | 19 | 从当前可知最优同侧报价向外偏移整数 tick，生成不会主动穿价的候选限价。 |
| [choose_limit_plan](../core/limit_optimizer.py#L29) | 29 | 只用决策前一分钟成交和当前盘口评分；未来成交绝不参与候选选择。 |
| [replay_limit_plan](../core/limit_optimizer.py#L85) | 85 | 执行已选方案：挂单→可选撤改→撤单确认→补单；完整轨迹只供事后核验。 |
| [run_limit_optimization](../core/limit_optimizer.py#L172) | 172 | 看板服务入口：校验参数→读同日簿/成交→事前选方案→三情景回放→保存不可变报告。 |

## core/liquidity.py

[文件入口](../core/liquidity.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [DepthConsumption](../core/liquidity.py#L6) | 6 | 为一个方案隔离深度账本；外生盘口内容改变后才重新建立可用深度。 |
| [DepthConsumption.__init__](../core/liquidity.py#L9) | 9 | 初始化最近簿态签名和逐方向、逐价格已消耗量，不与其他方案共享。 |
| [DepthConsumption.available](../core/liquidity.py#L14) | 14 | 扣掉本方案在同一簿态吃掉的量，返回副本；任一侧耗尽时返回 None。 |
| [DepthConsumption.consume](../core/liquidity.py#L35) | 35 | 按真实模拟成交明细扣减买单所吃的卖盘或卖单所吃的买盘，不扣计划量。 |

## core/live_model.py

[文件入口](../core/live_model.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [LiveModel](../core/live_model.py#L12) | 12 | 只加载冻结本地模型做只读推断，不在实时循环训练或发送订单。 |
| [LiveModel.__init__](../core/live_model.py#L14) | 14 | 读取旧固定规模模型清单并核验权重摘要，通过后加载模型字典。 |
| [LiveModel.predict](../core/live_model.py#L21) | 21 | 用决策时刻的因果特征预测旧任务；历史不足/过期返回None，基线胜出时使用基线并报告分布偏移。 |

## core/lp.py

[文件入口](../core/lp.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [single_range_swap](../core/lp.py#L5) | 5 | 单一未跨初始化tick区间的浮点兑换公式；先扣池费再更新平方根价格，不适用于跨区间执行。 |
| [inventory](../core/lp.py#L24) | 24 | 把价格夹在给定LP区间，计算流动性对应两种资产数量；区间外仓位变为单一资产。 |
| [scenario](../core/lp.py#L35) | 35 | 以参考价生成对齐tick的固定宽度演示仓位，按价格冲击计算资产、持币对照和手续费盈亏平衡；不声称历史手续费收益。 |

## core/model.py

[文件入口](../core/model.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [features](../core/model.py#L24) | 24 | 重建秒格的过去收益/波动、五档盘口与当前半ETH买单成本；未来六十秒成本仅作y标签。在线模式允许无标签但必须有完整过去窗口。 |
| [split](../core/model.py#L56) | 56 | 按先训练、后验证、最后测试切分时间，移除未来标签跨越下一边界的锚点。 |
| [metrics](../core/model.py#L67) | 67 | 计算MAE、RMSE及目标尾部误差，与持平基线比较；基线为零时改善百分比返回None而非Infinity。 |
| [evaluate](../core/model.py#L81) | 81 | 用给定已训练模型和基线预测，保存逐样本结果、误差及最差案例，不重训。 |
| [train](../core/model.py#L103) | 103 | 在训练区拟合候选，在验证区选参数；样本不足明确返回。先冻结权重/清单，再评价内部测试，拒绝覆盖冻结模型。 |
| [external](../core/model.py#L156) | 156 | 检验外部数据类型、冻结时间/配置和摘要，拒绝重复最终评价；使用既有模型只评分，不能把合成数据当真实。 |

## core/mpc.py

[文件入口](../core/mpc.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [bybit_days](../core/mpc.py#L28) | 28 | 汇总旧历史目录与新市场缓存中的可用 Bybit 盘口日期；只代表本机已有数据，不保证外部所有日期可下载。 |
| [_path_for_day](../core/mpc.py#L37) | 37 | 通过共用缓存适配器定位日期并强制核验规范化清单摘要；旧目录缺清单也拒绝使用。 |
| [load_bybit_timeline](../core/mpc.py#L45) | 45 | 只加载单日盘口并按事件时间排序去重；事件时间加用户延迟形成可用时间，计算中间价并记录来源摘要。完整历史只供模拟器保存。 |
| [_at](../core/mpc.py#L74) | 74 | 二分找目标时点已可知的最后盘口并检查簿龄；返回决策时刻标记或 None，不用最近未来盘口补缺。 |
| [_history_asof](../core/mpc.py#L87) | 87 | 截断至决策时刻的历史中间价序列，形成传给特征/预测模块的信息边界。 |
| [_past_volatility_bps](../core/mpc.py#L95) | 95 | 在过去一分钟中间价变动上计算收益标准差，换为 bps；样本不足返回零，是透明历史风险基线。 |
| [_expected_action_cost](../core/mpc.py#L106) | 106 | 当前动作按真实可见簿吃单；未来动作使用适用范围内的冻结条件预测，否则持平基线。加入手续费和波动风险罚项；卖出目标取收入负值以统一最小化。 |
| [_plan](../core/mpc.py#L162) | 162 | 枚举每时段整数数量动作，反向动态规划：剩余量为状态，阶段成本加后续最优值；终端必须完成。返回首步、计划和预测目标；同目标优先早执行，不代表市场全局最优。 |
| [_execute_child](../core/mpc.py#L215) | 215 | 把单个 Bybit 子单交给静态吃单计算，按当前 USDC/ETH 余额限额执行；返回真实模拟成交量、金额、费用和逐档明细。 |
| [_run_replay](../core/mpc.py#L234) | 234 | 按时间推进决策，仅把当前簿和过去价格传给规划器；到达时重新取簿成交，扣自有深度和更新余额。三个策略遵守同一子单上限，完成或截止后汇总。 |
| [run_mpc_replay](../core/mpc.py#L331) | 331 | 校验数量精度、期限、资源上限和数据覆盖；阻止训练截止前使用冻结模型。隔离回放 MPC/尽早/等额方案，保存配置、来源和不可变报告。 |

## core/network.py

[文件入口](../core/network.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [rest_check](../core/network.py#L15) | 15 | 只读查询 Binance市场元数据，确认 ETH/USDC标的有效并返回交易规则。 |
| [book_row](../core/network.py#L28) | 28 | 把实时深度消息转标准盘口，接收时钟作为 available_at，校验后输出唯一 id。 |
| [ws_check](../core/network.py#L39) | 39 | 连接公开行情WebSocket读取一条深度并校验，超时抛错；不登录交易账户。 |
| [DexReader](../core/network.py#L48) | 48 | 只读以太坊池状态和Quoter适配器，所有调用固定区块；不包含私钥、签名或提交交易。 |
| [DexReader.__init__](../core/network.py#L50) | 50 | 由环境变量或默认URL初始化只读RPC客户端，保留配置，池地址等待元数据验证。 |
| [DexReader.call](../core/network.py#L58) | 58 | 拼ABI函数选择器和参数，固定 block执行 eth_call后解码返回值，不写链上状态。 |
| [DexReader.verify](../core/network.py#L66) | 66 | 验证网络和合约代码，查询工厂池地址及token顺序、费率、精度和tick间距；不符合预设则拒绝。 |
| [DexReader.sample](../core/network.py#L92) | 92 | 同一固定最新区块读取slot0、流动性和各规模双向报价；结束复核区块hash，若重组则整组拒绝。接收后才标为可用。 |

## core/okx_orderbook.py

[文件入口](../core/okx_orderbook.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [_tree_bytes](../core/okx_orderbook.py#L24) | 24 | 统计现有数据总大小，过滤并发消失文件，用于规范化和存储预留。 |
| [normalize_okx_archive](../core/okx_orderbook.py#L39) | 39 | 流式读取官方 tar.gz 内唯一数据流，应用快照和增量并检验有效盘口，保存每秒首个前二十档；假设接收延迟明确记录而非实测。 |
| [normalize_okx_archive.update_side](../core/okx_orderbook.py#L86) | 86 | 按价格替换数量，零量删除，并校验价量合法；更新当前买侧或卖侧字典。 |
| [normalize_okx_archive.encode](../core/okx_orderbook.py#L99) | 99 | 对当前侧按买降卖升排序，取前二十档转 JSON，输出标准视图。 |

## core/optimizer.py

[文件入口](../core/optimizer.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [causal_snapshot](../core/optimizer.py#L19) | 19 | 读取经哈希校验的 Bybit/OKX 同日盘口，根据事件时间加假设延迟向后查找并拒绝陈旧簿；返回两所快照和时序审计。 |
| [run_static_snapshot](../core/optimizer.py#L57) | 57 | 取得因果双所快照后调用静态分配，将配置、数据依据和结果保存到新的不可变实验目录。 |

## core/order_review.py

[文件入口](../core/order_review.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [normalize_fills](../core/order_review.py#L7) | 7 | 映射时间/方向/ETH量/USDC价格/USDC费用，拒绝非有限数、非法方向、重复成交与缺列。 |
| [review_fills](../core/order_review.py#L36) | 36 | 按用户提供的成交量、价格和USDC费计算分方向均价与资金流；不推断未上传订单或钱包盈亏。 |

## core/orderbook.py

[文件入口](../core/orderbook.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [OrderBook](../core/orderbook.py#L7) | 7 | 维护 Bybit 快照和增量的状态机；缺快照或更新编号断档时停止输出，必须新快照恢复。 |
| [OrderBook.__init__](../core/orderbook.py#L9) | 9 | 初始化标的、严格连续编号策略、两侧档位、有效标记及断档/重置/重复计数。 |
| [OrderBook.apply](../core/orderbook.py#L19) | 19 | 按消息检查标的、时间、更新编号；快照重建，增量替换档位，零数量删除。断档或交叉时失效并返回 False。 |
| [OrderBook.row](../core/orderbook.py#L65) | 65 | 仅从有效簿态生成排序的前 depth 档位及事件/可用时间记录；无有效快照则抛错。 |

## core/passive.py

[文件入口](../core/passive.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [_is_tick_multiple](../core/passive.py#L18) | 18 | 检查限价是否为价格最小跳动的整数倍，不通过舍入偷偷改变用户限价。 |
| [simulate_passive_limit](../core/passive.py#L25) | 25 | 在订单到达时取可见盘口并检查非主动穿价；通过反向主动成交量推进三种假设队列，输出成交轨迹及未成交量。触价不等于成交，结果不是真实成交概率。 |
| [simulate_passive_limit.run_scenario](../core/passive.py#L85) | 85 | 按时间累积符合方向和价格条件的主动成交，先扣前方队列再计自身成交，记录每笔新增量并在完成时停止。 |
| [load_bybit_passive_day](../core/passive.py#L138) | 138 | 按日期读取 Bybit 同日盘口和成交 Parquet，任一文件缺失直接拒绝；不把只有成交数据的场所冒充有盘口。 |

## core/proof.py

[文件入口](../core/proof.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [decode_event](../core/proof.py#L6) | 6 | 按事件签名解码 ERC20 Transfer 或 V3 Swap 的地址及有符号金额；未知事件明确未验证金额。 |
| [validate_receipt](../core/proof.py#L27) | 27 | 逐项检查测试网、成功状态、交易目的/发送人、区块一致性和所需日志，拒绝主网或回滚；第三方回执不证明个人操作。 |

## core/quality.py

[文件入口](../core/quality.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [clean_books](../core/quality.py#L8) | 8 | 逐行检查盘口与可用时间，坏记录单独保留原因；有效记录排序并按 id 去重，返回清洗表和失败清单。 |
| [asof_index](../core/quality.py#L27) | 27 | 二分查找不晚于目标时刻的最后一个观测；无过去观测或超陈旧度返回 None，绝不使用未来行。 |
| [coverage](../core/quality.py#L35) | 35 | 以整个请求窗口的理论时间格为分母，计算被有效观测占据的格子比例；缺失窗口仍计入分母。 |

## core/reporting.py

[文件入口](../core/reporting.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [comparisons](../core/reporting.py#L15) | 15 | 把链上报价向后匹配新鲜CEX簿，对比含费成本并生成费率/gas敏感性；markout只供事后观察不参与选择。 |
| [replay](../core/reporting.py#L53) | 53 | 按预设历史意图在隔离CEX/DEX账本模拟成交，扫描期间止损并保留拒单；独立对账后生成逐分钟因果权益轨迹。 |
| [decisions](../core/reporting.py#L112) | 112 | 从场所规模、费用排序、拒单风险提取可核查决策说明；真实案例不足时明确标合成压力，不冒充市场收益。 |
| [report](../core/reporting.py#L173) | 173 | 串联成本比较、回放、风控、LP演示和手算明细，写各报告并返回质量统计和对账结果。 |

## core/research.py

[文件入口](../core/research.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [partition](../core/research.py#L13) | 13 | 同时约束特征时刻、标签终点和标签实际可用时间归属分区，剔除跨界样本。 |
| [candidates](../core/research.py#L20) | 20 | 建立两种岭回归和两种提升树的固定候选，标准化随Pipeline只在拟合输入上学习。 |
| [build_features](../core/research.py#L29) | 29 | 复用旧盘口特征再加入未来波动标签和过去波动基线，校验向后时间对齐；标签不进入 FEATURES。 |
| [score](../core/research.py#L50) | 50 | 计算模型与基线绝对误差差值，并以小时块bootstrap生成区间，减少重叠标签造成的虚假独立性；仅限给定样本。 |

## core/risk.py

[文件入口](../core/risk.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [reduction_proposal](../core/risk.py#L6) | 6 | 检查超额库存，只有 CEX本地库存且有新鲜深度时估算减仓。只生成建议，不执行或改账；DEX资产不能直接当CEX可卖余额。 |

## core/solver.py

[文件入口](../core/solver.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [_floor_units](../core/solver.py#L13) | 13 | 用 Decimal 向下取整，将可用数量换为整数步长，保证成交不超数量精度或余额。 |
| [optimize_static_route](../core/solver.py#L20) | 20 | 校验盘口、方向、目标和各所余额；按含费边际价格排序逐档分配并扣减资金。返回成交分配、费用及缺量。精确性限于独立档位和线性费率，不模拟排队、gas或市场冲击。 |

## core/store.py

[文件入口](../core/store.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [engine_for](../core/store.py#L11) | 11 | 按URL缓存有界SQLAlchemy连接池，设置连接超时和健康检查；凭据只进入连接，不返回给看板。 |
| [Store](../core/store.py#L18) | 18 | 保存实时观测和worker心跳的有界运行缓存；历史原始档案留在唯一文件目录。 |
| [Store.__init__](../core/store.py#L20) | 20 | 选择环境变量/本机数据库配置或SQLite后备，建立事件和状态表，设置SQLite容量和忙超时。 |
| [Store.put](../core/store.py#L39) | 39 | 单事务清理六小时前观测、检查事件大小/条数、按id去重再写入；达到上限拒绝而不是无限增长。 |
| [Store.heartbeat](../core/store.py#L53) | 53 | 事务内替换对应worker状态记录，供健康检查判断运行及数据新鲜度。 |
| [Store.health](../core/store.py#L61) | 61 | 读取状态表并反序列化为组件字典；不把数据库可用等同市场可执行。 |
| [Store.latest](../core/store.py#L66) | 66 | 按可用时间倒序取指定事件，最多一千条，返回JSON数据列表供API及页面。 |

## core/task_manager.py

[文件入口](../core/task_manager.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [connect](../core/task_manager.py#L20) | 20 | 创建 SQLite 连接与任务表，使用事务和忙等待保护多页面并发读写。 |
| [unpack](../core/task_manager.py#L35) | 35 | 解码保存的配置和结果，并兼容旧看板需要的创建时间及进度字段。 |
| [get_task](../core/task_manager.py#L45) | 45 | 按标识读取任务；SQL 参数绑定防止标识被当作查询语句执行。 |
| [list_tasks](../core/task_manager.py#L50) | 50 | 按创建时间列出统一实验历史，可按类型过滤，最多返回一百条。 |
| [ensure_worker](../core/task_manager.py#L58) | 58 | 启动独立后台队列进程；进程内部文件锁保证只有一个工作者，窗口关闭不杀任务。 |
| [submit_task](../core/task_manager.py#L66) | 66 | 先持久化参数后入队；每次提交创建新标识，旧结果不覆盖，串行执行防止内存并发峰值。 |
| [cancel_task](../core/task_manager.py#L84) | 84 | 持久化取消请求；队列中直接取消，运行中在当前计算步骤结束或数据检查点响应。 |
| [retry_task](../core/task_manager.py#L91) | 91 | 复制原配置创建新实验并关联原任务；一次性封存测试禁止重试，避免再次打开同一测试集。 |
| [Cancellation](../core/task_manager.py#L100) | 100 | 通过数据库读取取消标记，支持看板和独立后台进程之间协作，不依赖页面内存事件。 |
| [Cancellation.__init__](../core/task_manager.py#L102) | 102 | 保留当前任务标识，后续每个检查点读取最新取消状态。 |
| [Cancellation.is_set](../core/task_manager.py#L105) | 105 | 返回是否已请求取消；未知任务按取消处理，避免孤立执行。 |
| [update_progress](../core/task_manager.py#L111) | 111 | 保存阶段及有界进度；同时检查取消，令已有下载循环能及时结束。 |
| [dispatch](../core/task_manager.py#L123) | 123 | 根据类型调用现有计算组件；未来行情仍由模拟器读取，任务编排不改变策略信息边界。 |
| [dispatch.progress](../core/task_manager.py#L127) | 127 | 把现有组件的阶段回调写入统一任务，并在回调时响应取消。 |
| [execute_task](../core/task_manager.py#L171) | 171 | 执行已领取任务，分别保存完成、取消或失败；取消后不将生成的中间产物伪装成成功。 |
| [worker_lock](../core/task_manager.py#L187) | 187 | 尝试占有工作者文件锁；进程崩溃时操作系统释放锁，新进程才可接管。 |
| [recover_interrupted](../core/task_manager.py#L202) | 202 | 仅持有工作者锁时调用：标记前次崩溃遗留任务，不自动重跑或重复打开封存测试。 |
| [claim_next](../core/task_manager.py#L208) | 208 | 在单个事务中领取最早的等待任务，防止重复执行同一份实验。 |
| [run_worker](../core/task_manager.py#L218) | 218 | 独立串行工作者：恢复崩溃状态、执行排队任务；默认常驻，测试可指定空闲退出时间，不依赖页面。 |
| [submit_execution](../core/task_manager.py#L230) | 230 | 把单笔订单模拟提交到统一队列，配置单位由计算组件验证。 |
| [get_execution_job](../core/task_manager.py#L235) | 235 | 优先查询统一队列，找不到时读取旧订单任务，不改写旧记录。 |
| [get_execution_result](../core/task_manager.py#L241) | 241 | 读取新任务结果或旧不可变订单报告，兼容原结果展示组件。 |
| [execution_history](../core/task_manager.py#L249) | 249 | 合并新旧订单实验，按时间排序供原工作台历史查看。 |
| [submit_cross](../core/task_manager.py#L255) | 255 | 将同窗跨所分析提交至共享串行队列，避免与模型训练同时占用内存。 |
| [cross_job](../core/task_manager.py#L260) | 260 | 读取新跨所任务状态，保留旧任务标识兼容性。 |
| [cross_result](../core/task_manager.py#L266) | 266 | 读取新跨所结果或旧报告，不再要求页面知道存储形式。 |
| [cross_history](../core/task_manager.py#L274) | 274 | 汇总新旧跨所历史实验，报告内容和旧标识保持不变。 |
| [cancel_any](../core/task_manager.py#L280) | 280 | 统一任务优先使用持久取消；旧任务仍调用其原取消入口。 |
| [submit_sealed](../core/task_manager.py#L288) | 288 | 在入队前锁定未观察日期与代码/模型，再由独立进程一次性打开评估。 |

## download_history.py

[文件入口](../download_history.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [usage](../download_history.py#L11) | 11 | 累计历史研究存储占用，供归档下载前后容量检查。 |
| [main](../download_history.py#L15) | 15 | 按固定研究清单下载公开Bybit日档，流式检查长度、CRC和容量，保存来源摘要；已有冻结归档只复用。 |

## download_trades.py

[文件入口](../download_trades.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## evaluate_live_smoke.py

[文件入口](../evaluate_live_smoke.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## example_budget_order.py

[文件入口](../example_budget_order.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [main](../example_budget_order.py#L10) | 10 | 在预定历史时点二分求含费五千USDC可买最大数量，独立重算逐档金额；未来markout只作事后估值。 |

## history_dex.py

[文件入口](../history_dex.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [sqrt_tick](../history_dex.py#L20) | 20 | 以九十位Decimal计算tick平方根价边界；是数学近似而非Solidity逐位TickMath实现。 |
| [Archive](../history_dex.py#L29) | 29 | 在只读DexReader上加入调用节流和历史区块查找，供四小时状态采样。 |
| [Archive.call](../history_dex.py#L31) | 31 | 历史RPC调用前短暂停顿以限制请求速率，随后沿用固定区块ABI调用。 |
| [Archive.block_at](../history_dex.py#L36) | 36 | 先扩大区块范围再二分，找时间戳不晚于目标的最后区块；不伪造逐交易毫秒时间。 |
| [main](../history_dex.py#L49) | 49 | 按固定历史配置确定LP边界并采样四小时池状态、费用增长和报价；每组核验hash后落盘，支持检查点缓存。 |

## make_fixture.py

[文件入口](../make_fixture.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [generate](../make_fixture.py#L13) | 13 | 生成明确标注的合成软件验收数据和清单，供数学/异常路径测试；不混入真实市场研究结论。 |

## market_app.py

[文件入口](../market_app.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [t](../market_app.py#L29) | 29 | 选择对应语言的界面文字；首次访问默认使用英语。 |
| [word](../market_app.py#L34) | 34 | 把后台方向、状态与方案标识转成业务名称，原报告不变。 |
| [table](../market_app.py#L62) | 62 | 只选业务列并翻译列名与状态，隐藏嵌套报告、代码地址和工程字段。 |
| [chart](../market_app.py#L72) | 72 | 在副本中翻译曲线名称及坐标轴，绘制曲线或柱图，不改动历史数据。 |
| [download](../market_app.py#L80) | 80 | 下载完整结果文件；不把 JSON 或指令直接渲染在页面上。 |
| [read](../market_app.py#L85) | 85 | 读取可选历史报告，缺失时返回空值，让页面提示暂无结果。 |
| [cached_bybit_passive_day](../market_app.py#L91) | 91 | 缓存最多两个日期的盘口和成交，减少限价表单重复读盘。 |
| [error_message](../market_app.py#L96) | 96 | 显示实际失败原因及常见问题的双语建议，完整异常仅保存在后台日志。 |
| [progress](../market_app.py#L103) | 103 | 把后台任务阶段归纳为进度说明，内部处理日志不放到看板。 |
| [render_experiment_result](../market_app.py#L132) | 132 | 轮询实验并展示即时／分批执行的完成量、费用及逐次成交，支持取消和下载。 |
| [render_cross_venue_job](../market_app.py#L182) | 182 | 展示跨所进度与双向扣费价差；Binance 仅作成交价参照，不作为盘口执行报价。 |
| [render_static_report](../market_app.py#L216) | 216 | 展示已保存的跨所分配结果，语言切换只重绘表格，不重新求解。 |
| [render_mpc_report](../market_app.py#L227) | 227 | 展示已保存的动态执行比较与逐次决策，切换语言不触发回放。 |
| [render_passive_report](../market_app.py#L239) | 239 | 展示已保存的三种限价队列结果，语言切换保持模拟输出。 |
| [render_background_task](../market_app.py#L247) | 247 | 轮询独立后台任务，页面重绘不再次提交；显示取消、失败原因和完成结果。 |
| [render_channel_report](../market_app.py#L269) | 269 | 展示单笔跨交易所／池报价与 gas 成本，不把 WETH 与原生 ETH 默认为同一结算资产。 |
| [render_chain_report](../market_app.py#L279) | 279 | 展示逐事件下载摘要和有限预览，时间戳按区块展示，不制造区块内每笔独立时间。 |
| [live_experiment](../market_app.py#L329) | 329 | 只轮询当前实验，不在刷新时重复提交订单。 |
| [live_cross_venue](../market_app.py#L366) | 366 | 轮询所选跨所任务，完成后显示同日比较图表。 |
| [show_acceptance_progress](../market_app.py#L421) | 421 | 只展示新日期评估的进度和取消入口，不渲染任务字典或运行日志。 |
| [saved_label](../market_app.py#L531) | 531 | 以日期、时间、方向和数量标记历史实验，隐藏内部运行标识。 |

## native_database.py

[文件入口](../native_database.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## paper_replay.py

[文件入口](../paper_replay.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [replay](../paper_replay.py#L19) | 19 | 用冻结预测和盘口运行早期纸面策略/立即基线，记资金风险与费用；不发送真实订单。 |

## prepare_history.py

[文件入口](../prepare_history.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [main](../prepare_history.py#L13) | 13 | 按哈希验证原始日档，流式重建每个增量，批量输出秒级前二十档视图；不覆盖旧规范化文件。 |

## probe_archive_rpc.py

[文件入口](../probe_archive_rpc.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## probe_bybit.py

[文件入口](../probe_bybit.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## probe_history.py

[文件入口](../probe_history.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [probe](../probe_history.py#L6) | 6 | 对Tardis候选档案只读探测状态和小段响应，返回可访问性及错误类型，不下载整日数据。 |

## probe_network.py

[文件入口](../probe_network.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [probe](../probe_network.py#L10) | 10 | 只读检查给定公开行情/RPC服务连通情况，将成功与失败分类供来源选择。 |

## probe_public_archive.py

[文件入口](../probe_public_archive.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [probe](../probe_public_archive.py#L7) | 7 | 只读检查公开档案存在性、响应长度和格式，避免把不可访问文件当可用数据。 |

## research.py

[文件入口](../research.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [prepare](../research.py#L15) | 15 | 按既定日期构造并分开保存训练/验证/测试特征及摘要，保护旧研究输入。 |
| [load](../research.py#L34) | 34 | 读取指定已保存分区并核验特征摘要，不重新切分或偷偷改窗口。 |
| [train](../research.py#L52) | 52 | 只用训练/验证分区比较候选和历史基线，保存冻结权重、选择结果及代码/数据摘要。 |
| [evaluate](../research.py#L87) | 87 | 核验冻结数据/代码，先记录最终测试已打开再一次性评分和写报告；禁止反复打开测试调参。 |

## service.py

[文件入口](../service.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [database_unavailable](../service.py#L12) | 12 | 把数据库异常转为HTTP503及本机恢复提示，不回显连接凭据。 |
| [health](../service.py#L19) | 19 | 读取心跳，按CEX/DEX允许年龄判断陈旧，并结合worker状态输出market_ready；API存活不等于可交易。 |
| [market](../service.py#L29) | 29 | 只接受已知流名称，返回有界最新观测，未知kind以404拒绝。 |
| [research](../service.py#L37) | 37 | 读取已保存冻结研究和测试指标，文件尚未生成则明确pending。 |
| [quality](../service.py#L44) | 44 | 读取历史规范化质量清单，缺清单返回pending。 |
| [experiments](../service.py#L51) | 51 | 本机内部接口列出统一队列历史；结果与状态从持久数据库读取，不重复执行计算。 |
| [experiment](../service.py#L58) | 58 | 读取指定实验配置、进度及报告；不存在时返回404，保留历史失败原因。 |
| [create_experiment](../service.py#L67) | 67 | 只创建本机研究任务，不创建交易所真实订单；一次性验收必须走预登记入口。 |
| [cancel_experiment](../service.py#L77) | 77 | 向持久队列提交协作取消；后台组件到检查点停止，不伪装立即中断。 |

## setup_native_database.py

[文件入口](../setup_native_database.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [command](../setup_native_database.py#L14) | 14 | 执行本机数据库初始化所需子命令并检查退出状态；不把密码打印到结果。 |

## setup_postgres_runtime.py

[文件入口](../setup_postgres_runtime.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## stability_audit.py

[文件入口](../stability_audit.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [launch_feed](../stability_audit.py#L16) | 16 | 创建本次审计专属只读采集进程，保留 Popen 身份；不接管或停止其他用户进程。 |
| [snapshot](../stability_audit.py#L24) | 24 | 记录本进程及其专属采集进程的内存、研究数据与数据库/WAL占用；心跳只保存业务状态，不记录凭据。 |
| [run_audit](../stability_audit.py#L42) | 42 | 运行一次不可覆盖的影子验收；断连后等待重连，并在中段终止自己创建的工作者再重启，最终按证据判断通过。 |

## task_worker.py

[文件入口](../task_worker.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## tests/pytest_workspace_tmp.py

[文件入口](../tests/pytest_workspace_tmp.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [tmp_path](../tests/pytest_workspace_tmp.py#L11) | 11 | 为测试建立工作区内唯一临时目录，避开Windows系统临时目录权限问题，不删除历史证据。 |

## tests/test_acceptance.py

[文件入口](../tests/test_acceptance.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [setup_acceptance](../tests/test_acceptance.py#L7) | 7 | 隔离验收目录和冻结模型，并把下载及行情样本替换为确定输入，测试无需外网。 |
| [setup_acceptance.missing](../tests/test_acceptance.py#L14) | 14 | 模拟本机没有观察过该日期，允许登记但不真实请求来源。 |
| [test_once_only_and_code_change_guard](../tests/test_acceptance.py#L26) | 26 | 登记后代码变化必须拒绝打开；正常打开后禁止二次评价，避免封存测试反复调参。 |
| [test_failed_cases_remain_in_acceptance_denominator](../tests/test_acceptance.py#L44) | 44 | 某些订单失败不能从报告删除，整体必须标未完成，而不是只展示成功样本。 |
| [test_failed_cases_remain_in_acceptance_denominator.replay](../tests/test_acceptance.py#L47) | 47 | 只让卖单失败，检查八个预定场景是否完整保留。 |

## tests/test_bilingual_ui.py

[文件入口](../tests/test_bilingual_ui.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [assert_business_ui](../tests/test_bilingual_ui.py#L12) | 12 | 检查所有可见业务文字和图表，防止工程报告、代码和错误重新进入看板。 |
| [test_bilingual_pages_and_analysis_choices](../tests/test_bilingual_ui.py#L34) | 34 | 逐页检查中英文渲染，并确认删除的模块不在导航且四个订单分析入口均正常。 |
| [test_language_switch_keeps_order_values_and_executes_static_and_mpc](../tests/test_bilingual_ui.py#L51) | 51 | 切换语言保留已提交的参数，并通过真实缓存验证静态、动态和限价模拟仍能运行。 |

## tests/test_chain_history.py

[文件入口](../tests/test_chain_history.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [test_decode_signed_swap_and_liquidity_events](../tests/test_chain_history.py#L12) | 12 | 手工编码买入兑换与正负流动性事件，验证精度、符号、区块内位置和负 tick。 |
| [test_block_lookup_handles_missed_slot_without_future_block](../tests/test_chain_history.py#L30) | 30 | 人为设置漏槽，验证查找只返回过去区块，不能用下一块补齐目标时刻。 |
| [test_chain_comparison_rejects_implicit_wrapping_and_bad_fees](../tests/test_chain_history.py#L40) | 40 | 网络调用前拒绝未经同意的 WETH 结算及 NaN 手续费，不把参数错误展示成市场缺数据。 |
| [test_channel_comparison_gas_and_future_book_exclusion](../tests/test_chain_history.py#L46) | 46 | 手算池费用已含750、gas1；未来便宜盘口不应影响当时渠道报价，交易所只加一次手续费。 |
| [test_channel_comparison_gas_and_future_book_exclusion.Reader](../tests/test_chain_history.py#L50) | 50 | 给出固定历史区块与可手算报价的测试只读节点。 |
| [test_channel_comparison_gas_and_future_book_exclusion.Reader.__init__](../tests/test_chain_history.py#L52) | 52 | 保存代币配置及固定区块查询，避免测试接触公网。 |
| [test_channel_comparison_gas_and_future_book_exclusion.Reader.verify](../tests/test_chain_history.py#L55) | 55 | 测试中省略网络验证，固定元数据由夹具负责。 |
| [test_channel_comparison_gas_and_future_book_exclusion.Reader.call](../tests/test_chain_history.py#L58) | 58 | 返回池已含费报价或 sqrt 价格20000倍 Q96，对应2500USDC。 |

## tests/test_cross_venue.py

[文件入口](../tests/test_cross_venue.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [tmp_path](../tests/test_cross_venue.py#L16) | 16 | 为测试建立工作区内唯一临时目录，避开Windows系统临时目录权限问题，不删除历史证据。 |
| [test_okx_archive_snapshot_and_delta_rebuild](../tests/test_cross_venue.py#L30) | 30 | 验证OKX档案快照、增量与零量删除；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_cross_venue_sweep_applies_both_fees](../tests/test_cross_venue.py#L67) | 67 | 验证跨所双腿手续费分别计算；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_binance_trade_reference_never_uses_a_future_trade](../tests/test_cross_venue.py#L107) | 107 | 验证Binance参照成交严格向后匹配；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |

## tests/test_dashboard.py

[文件入口](../tests/test_dashboard.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [test_three_pages_render](../tests/test_dashboard.py#L5) | 5 | 验证早期三页看板渲染与无异常；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |

## tests/test_full_platform.py

[文件入口](../tests/test_full_platform.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [msg](../tests/test_full_platform.py#L9) | 9 | 生成Bybit测试快照/增量消息，允许编号、时间和档位覆盖。 |
| [test_reconstruction_gap_resnapshot](../tests/test_full_platform.py#L15) | 15 | 验证快照/增量删除、编号断档后失效与新快照恢复；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_v2_hand_computation](../tests/test_full_platform.py#L26) | 26 | 验证V2恒定乘积输出与独立整数手算；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_v3_crossing_and_unknown_depth](../tests/test_full_platform.py#L30) | 30 | 验证V3跨tick流动性更新及未知边界停止；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_fee_growth_and_attribution](../tests/test_full_platform.py#L41) | 41 | 验证区间手续费增长和LP盈亏归因；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_partition_purges_horizon](../tests/test_full_platform.py#L47) | 47 | 验证未来标签跨分区边界剔除；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_volatility_label_never_enters_features](../tests/test_full_platform.py#L52) | 52 | 验证未来波动标签不得进入决策特征；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_decision_features_do_not_require_future_labels](../tests/test_full_platform.py#L62) | 62 | 验证在线特征不需要未来标签；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_arbitrage_fees_not_double_counted](../tests/test_full_platform.py#L71) | 71 | 验证双向套利池费不重复扣除及陈旧报价拒绝；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_store_idempotent_and_retention](../tests/test_full_platform.py#L81) | 81 | 验证缓存id去重和六小时保留窗口；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_testnet_proof_rejects_wrong_chain_and_revert](../tests/test_full_platform.py#L94) | 94 | 验证错误网络与回滚回执拒绝；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_market_dashboard_all_pages](../tests/test_full_platform.py#L105) | 105 | 验证各看板页面实际渲染无异常；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_health_uses_market_freshness_and_worker_state](../tests/test_full_platform.py#L121) | 121 | 验证API健康不能把已停worker或陈旧行情标为可执行；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_health_uses_market_freshness_and_worker_state.FakeStore](../tests/test_full_platform.py#L126) | 126 | 提供隔离的数据库心跳替身，避免健康测试依赖真实数据库。 |
| [test_health_uses_market_freshness_and_worker_state.FakeStore.health](../tests/test_full_platform.py#L128) | 128 | 返回固定的心跳和worker状态，用于检查市场新鲜度判断。 |
| [test_trade_flow_bucket_is_causal_and_rpi_separate](../tests/test_full_platform.py#L137) | 137 | 验证成交聚合桶结束后才可用并单列RPI；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_proof_decodes_signed_swap_amounts](../tests/test_full_platform.py#L148) | 148 | 验证Swap事件有符号金额解码；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_live_prediction_ignores_future_rows](../tests/test_full_platform.py#L158) | 158 | 验证实时冻结模型不读未来记录；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |

## tests/test_limit_optimizer.py

[文件入口](../tests/test_limit_optimizer.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [market](../tests/test_limit_optimizer.py#L9) | 9 | 构造每秒时间戳更新但档位不变的簿态，便于核验队列和自有深度。 |
| [tape](../tests/test_limit_optimizer.py#L15) | 15 | 在撤单延迟窗口和确认后各放一笔主动卖出，区分可计入的成交边界。 |
| [args](../tests/test_limit_optimizer.py#L21) | 21 | 提供买单测试的同一资金、精度、手续费和撤单延迟，避免对照条件漂移。 |
| [test_selection_cannot_see_future_tape](../tests/test_limit_optimizer.py#L28) | 28 | 改变决策后的成交不应改变候选评分或选中方案，未来仅供回放使用。 |
| [test_selection_cannot_see_future_tape.choose](../tests/test_limit_optimizer.py#L30) | 30 | 调用与看板相同的选择器，故意传完整数据以验证内部时间隔离。 |
| [test_cancel_latency_fill_then_taker_and_independent_accounting](../tests/test_limit_optimizer.py#L39) | 39 | 撤单确认前的两笔可成交，确认后成交被排除，余量按主动费率补齐并对账。 |
| [test_amendment_requires_cancel_ack_and_new_queue](../tests/test_limit_optimizer.py#L53) | 53 | 改价只能在旧单撤单确认之后提交；两段不能重复使用同一成交。 |
| [test_sell_partial_preserves_balance](../tests/test_limit_optimizer.py#L63) | 63 | 卖出库存不足时只能部分完成，不能通过负持仓或虚构成交满足目标。 |
| [test_all_mpc_baselines_obey_cap_and_unchanged_depth_is_not_reused](../tests/test_limit_optimizer.py#L72) | 72 | 三个方案均遵守单次上限，时间戳刷新不能补回已经吃完的同一档位。 |
| [test_ml_horizon_outside_support_uses_explicit_fallback](../tests/test_limit_optimizer.py#L84) | 84 | 超过训练期限的动作不调用模型，也不把 120 秒悄悄截为 60 秒。 |
| [test_s3_dashboard_selects_new_report_and_preserves_reference_on_rerun](../tests/test_limit_optimizer.py#L91) | 91 | 从看板输入并运行真实缓存案例，确认页面展示新报告且历史复跑保留撤改原方案。 |

## tests/test_math_ledger.py

[文件入口](../tests/test_math_ledger.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [book](../tests/test_math_ledger.py#L10) | 10 | 构造可控的买卖档位测试输入，允许价格和数量变化，避免依赖网络行情。 |
| [test_hand_buy](../tests/test_math_ledger.py#L16) | 16 | 验证逐档买入、费用和均价与手算一致；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_hand_sell](../tests/test_math_ledger.py#L26) | 26 | 验证逐档卖出、费用和净收入与手算一致；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_partial_not_extrapolated](../tests/test_math_ledger.py#L35) | 35 | 验证深度不足保留缺量而不外推；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_crossed_book_rejected](../tests/test_math_ledger.py#L43) | 43 | 验证交叉盘口拒绝进入计算；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_dex_fee_not_double_counted](../tests/test_math_ledger.py#L51) | 51 | 验证DEX已含池费报价只另加gas；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_ledger_identity_and_independent_rebuild](../tests/test_math_ledger.py#L57) | 57 | 验证账本盈亏恒等式与独立现金流重建；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_duplicate_stale_and_insufficient](../tests/test_math_ledger.py#L69) | 69 | 验证重复委托、陈旧报价和余额不足的拒单；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_dex_gas_pnl_identity](../tests/test_math_ledger.py#L79) | 79 | 验证链上原生gas消耗计入盈亏恒等式；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_loss_limit_persists](../tests/test_math_ledger.py#L89) | 89 | 验证止损一旦触发不能因价格恢复自动抹掉；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_stale_reference_does_not_trigger_loss_pause](../tests/test_math_ledger.py#L96) | 96 | 验证陈旧估值不错误触发暂停；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_lp_boundary_and_conservation](../tests/test_math_ledger.py#L103) | 103 | 验证LP区间边界资产与守恒；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_single_range_independent_answer](../tests/test_math_ledger.py#L113) | 113 | 验证单区间兑换与独立预期答案；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_real_preflight_book_against_independent_answer](../tests/test_math_ledger.py#L122) | 122 | 验证真实预检盘口逐档独立核算；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |

## tests/test_model_freeze.py

[文件入口](../tests/test_model_freeze.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [test_training_freeze_and_external_guards](../tests/test_model_freeze.py#L8) | 8 | 验证训练冻结、权重防篡改与外部窗口守卫；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |

## tests/test_mpc.py

[文件入口](../tests/test_mpc.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [_book](../tests/test_mpc.py#L8) | 8 | 构造指定时刻及中间价的有效盘口，供因果和成本测试。 |
| [test_mpc_plan_respects_child_cap_and_completes_by_deadline](../tests/test_mpc.py#L18) | 18 | 验证MPC子单上限及截止完成要求；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_mpc_first_decision_does_not_depend_on_future_book_rows](../tests/test_mpc.py#L32) | 32 | 验证未来盘口修改不改变过去MPC首步；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_mpc_first_decision_does_not_depend_on_future_book_rows.first_plan](../tests/test_mpc.py#L40) | 40 | 对指定时间序列只取决策时可知簿和过去历史，再计算首步动作。 |
| [test_conditional_ml_features_are_invariant_to_future_market_rows](../tests/test_mpc.py#L53) | 53 | 验证条件特征不受未来行修改影响；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_conditional_ml_features_are_invariant_to_future_market_rows.features](../tests/test_mpc.py#L61) | 61 | 以当前时点已知盘口和历史构建条件特征，验证未来数据修改不影响输入。 |
| [test_mpc_replay_replans_and_accounts_for_actual_fills](../tests/test_mpc.py#L71) | 71 | 验证MPC重规划、实际成交费用与资金更新；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |

## tests/test_optimization_components.py

[文件入口](../tests/test_optimization_components.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [book](../tests/test_optimization_components.py#L8) | 8 | 构造可控的买卖档位测试输入，允许价格和数量变化，避免依赖网络行情。 |
| [test_static_router_sorts_fee_adjusted_marginal_levels](../tests/test_optimization_components.py#L16) | 16 | 验证静态路由按含费边际价格分配；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_static_router_obeys_local_quote_balances_and_budget](../tests/test_optimization_components.py#L30) | 30 | 验证各所余额隔离和总预算约束；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_passive_order_reports_queue_scenarios_and_excludes_future_and_rpi](../tests/test_optimization_components.py#L45) | 45 | 验证限价队列上下界、未来与RPI排除；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_passive_order_rejects_marketable_limit_and_bad_tick](../tests/test_optimization_components.py#L66) | 66 | 验证被动模块拒绝可成交限价和非法价格步长；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |

## tests/test_risk.py

[文件入口](../tests/test_risk.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [test_proposal_does_not_move_inventory_or_hide_remaining_depth](../tests/test_risk.py#L4) | 4 | 验证减仓建议不改库存并保留深度不足风险；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_dex_balance_not_sold_on_cex](../tests/test_risk.py#L15) | 15 | 验证DEX库存不得当作CEX可卖资金；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |

## tests/test_task_manager.py

[文件入口](../tests/test_task_manager.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [isolated_queue](../tests/test_task_manager.py#L14) | 14 | 将任务数据库隔离在测试目录，禁止单元测试启动真实后台进程。 |
| [test_persistent_restart_marks_interrupted_without_reexecuting](../tests/test_task_manager.py#L22) | 22 | 重启接管仅标记中断，不重新执行旧任务，原配置可复制成新任务。 |
| [test_cancel_and_failure_and_single_use_evaluation](../tests/test_task_manager.py#L35) | 35 | 排队取消不执行，错误原因完整保存，封存测试禁止复制重试。 |
| [test_cancel_and_failure_and_single_use_evaluation.fail](../tests/test_task_manager.py#L41) | 41 | 返回有明确原因的可控异常，核验失败状态和错误文本持久化。 |
| [test_queue_success_is_atomic_and_parameters_are_preserved](../tests/test_task_manager.py#L52) | 52 | 任务结果以事务提交，复制实验不修改原始金额或完成报告。 |
| [test_trade_import_timezone_fees_and_conservation](../tests/test_task_manager.py#L63) | 63 | 真实成交映射时区、双方向费用与资金流，独立手算验证，不把现金流当收益。 |
| [test_real_worker_process_crash_lock_and_recovery](../tests/test_task_manager.py#L78) | 78 | 启动真实独立 Python 进程，验证排他锁、进程崩溃接管和新任务完成；只终止本测试自己创建的进程。 |
| [test_cancel_running_at_progress_checkpoint](../tests/test_task_manager.py#L102) | 102 | 运行途中取消由数据库跨检查点传递，不发布伪造成功结果。 |
| [test_cancel_running_at_progress_checkpoint.cancelled_compute](../tests/test_task_manager.py#L105) | 105 | 模拟用户在计算阶段发出取消，下一进度检查应中断。 |

## tests/test_task_service.py

[文件入口](../tests/test_task_service.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [test_task_api_persistence_cancel_and_sealed_guard](../tests/test_task_service.py#L8) | 8 | 验证提交后查询到同一参数、持久取消、未知标识404及拒绝绕过封存预登记。 |

## tests/test_time_integrity.py

[文件入口](../tests/test_time_integrity.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [books](../tests/test_time_integrity.py#L11) | 11 | 生成确定性的盘口时间序列，便于修改未来行核验信息隔离。 |
| [test_future_changes_do_not_change_past_features](../tests/test_time_integrity.py#L19) | 19 | 验证未来行情修改不改变过去特征；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_missing_window_is_not_zero_filled](../tests/test_time_integrity.py#L27) | 27 | 验证缺失历史窗口不得零填造信号；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_purge_horizon](../tests/test_time_integrity.py#L34) | 34 | 验证切分标签期限的隔离；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_asof_never_uses_future_and_stale_rejected](../tests/test_time_integrity.py#L42) | 42 | 验证向后对齐不读未来且拒绝陈旧；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_coverage_keeps_expected_denominator](../tests/test_time_integrity.py#L50) | 50 | 验证质量覆盖率保留完整请求窗口分母；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_manifest_tampering](../tests/test_time_integrity.py#L56) | 56 | 验证来源摘要篡改拒绝；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_zero_baseline_percentage_not_infinite](../tests/test_time_integrity.py#L67) | 67 | 验证零基线百分比不输出Infinity；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |
| [test_partial_last_minute_coverage_is_bounded](../tests/test_time_integrity.py#L73) | 73 | 验证尾部不完整分钟覆盖率不超一；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。 |

## tests/test_workbench_rejection.py

[文件入口](../tests/test_workbench_rejection.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [test_rejection_has_complete_financial_fields](../tests/test_workbench_rejection.py#L12) | 12 | 无过去盘口或盘口过期时，返回零成交、零费用和全部余量；价格成本不可计算。 |
| [test_invalid_display_text_rejected_before_loading_data](../tests/test_workbench_rejection.py#L21) | 21 | 未知输入单位在读数据前被拒绝，不能把预算文案当 ETH 数量继续成交。 |
| [test_workbench_old_rejection_and_budget_submission](../tests/test_workbench_rejection.py#L28) | 28 | 复现缺 fee_quote 的旧未成交报告，同时检查预算和 ETH 切换提交正确内部单位及金额。 |
| [test_workbench_old_rejection_and_budget_submission.capture](../tests/test_workbench_rejection.py#L35) | 35 | 记录看板传来的参数，返回本地测试标识，避免触发网络下载。 |
| [test_failed_simulation_displays_reason_in_active_and_history](../tests/test_workbench_rejection.py#L55) | 55 | 失败任务的当前结果和历史结果都显示缺少哪天的 OKX 数据以及上传建议。 |
| [test_failure_formatter_preserves_unknown_reason_and_hides_private_fields](../tests/test_workbench_rejection.py#L73) | 73 | 未识别原因仍展示具体说明，屏蔽本机地址和连接口令，不输出堆栈。 |

## tests/ui_queue.py

[文件入口](../tests/ui_queue.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [use_inline_queue](../tests/ui_queue.py#L5) | 5 | 让 AppTest 在一次提交后看到结果；不启动真实后台进程，不影响非测试看板。 |
| [use_inline_queue.submit](../tests/ui_queue.py#L10) | 10 | 持久化真实配置后执行领取的任务，模拟后台完成，错误仍进入持久失败记录。 |

## verify_database_recovery.py

[文件入口](../verify_database_recovery.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## verify_historical_swap.py

[文件入口](../verify_historical_swap.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## verify_proof.py

[文件入口](../verify_proof.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## verify_public_testnet_sample.py

[文件入口](../verify_public_testnet_sample.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|

## verify_runtime.py

[文件入口](../verify_runtime.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [size](../verify_runtime.py#L12) | 12 | 递归统计指定运行目录文件字节，供数据库/研究空间预算核验。 |

## worker.py

[文件入口](../worker.py#L1)

| 函数 / 类 | 定义行 | 中文功能说明 |
|---|---:|---|
| [run](../worker.py#L17) | 17 | 在给定期限内并行只读采集与推断，写有界缓存和心跳，退出记录停止；不发送交易。 |
| [run.cex](../worker.py#L24) | 24 | 订阅公开Bybit盘口，应用快照/增量并保存有效视图；断开后重连且等待有效簿恢复。 |
| [run.dex](../worker.py#L57) | 57 | 循环在后台线程读取同区块链上报价，写状态及成本机会；异常只记录类型，不暴露RPC凭据。 |
| [run.infer](../worker.py#L81) | 81 | 从运行缓存截取因果历史并调用冻结模型，写只读预测；不足时标明模型/历史未就绪。 |
