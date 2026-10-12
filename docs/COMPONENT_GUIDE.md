# 按流水线阅读组件代码

从看板参数进入，依次看数据准备、因果簿态、预测、求解、模拟、账本及报告。函数开头的中文说明解释输入与职责，正文说明具体分支。

| 组件 | 工程文件与入口坐标 | 入口职责 |
|---|---|---|
| 持久串行任务队列 | [core/task_manager.py:66 · submit_task](../core/task_manager.py#L66) | 参数先入SQLite再执行；独立进程只领取一份任务，错误与结果持久保存。复跑创建新标识，封存测试不重试。 |
| 后台执行与恢复 | [core/task_manager.py:218 · run_worker](../core/task_manager.py#L218) | 文件锁防止重复工作者；接管时仅标记前次中断，后续任务串行领取；默认常驻、不依赖页面。 |
| 实际成交映射与复盘 | [core/order_review.py:36 · review_fills](../core/order_review.py#L36) | 校验上传时区、方向、数量、价格和USDC费用，按方向核算均价及资产现金流；不臆测原委托或未成交部分。 |
| 链上逐事件历史接口 | [core/chain_history.py:45 · extract_events](../core/chain_history.py#L45) | 有界获取单池Swap/Mint/Burn与起始状态、验证区块hash、保存区块内事件顺序；公共历史日志暂不可用，不宣称全tick重建。 |
| 交易所与池单笔报价比较 | [core/chain_history.py:91 · compare_channels](../core/chain_history.py#L91) | 读取过去已可知区块及盘口，比较固定数量含费/gas金额；ETH/WETH明确区分，池费不重复算，不使用未来报价选场所。 |
| 一小时只读稳定性审计 | [stability_audit.py:42 · run_audit](../stability_audit.py#L42) | 记录资源和数据新鲜度，主动断开自己的行情socket并重启自己的采集进程；时长及有效率不足即不通过。 |
| 本机实验服务接口 | [service.py:51 · experiments](../service.py#L51) | 与看板共用持久任务；提交、查询和取消只操作研究任务，不创建真实订单。 |
| 看板失败原因解说 | [core/dashboard_errors.py:5 · describe_failure](../core/dashboard_errors.py#L5) | 翻译常见原因，保留未知错误正文，屏蔽工程地址和口令。 |
| 看板交互与实验入口 | [market_app.py:132 · render_experiment_result](../market_app.py#L132) | 以中英文展示订单模拟结果、费用与完成比例，提供成交表及完整结果下载。 |
| 参数校验、数据准备与后台编排 | [core/experiment_engine.py:442 · run_experiment](../core/experiment_engine.py#L442) | 校验市场、时区、规模和最长窗口，逐日准备缓存后运行 P1 立即/分批对照并返回数据质量及完成率报告。 |
| Bybit 快照/增量重建 | [core/orderbook.py:7 · OrderBook](../core/orderbook.py#L7) | 维护 Bybit 快照和增量的状态机；缺快照或更新编号断档时停止输出，必须新快照恢复。 |
| OKX 历史订单簿重建 | [core/okx_orderbook.py:39 · normalize_okx_archive](../core/okx_orderbook.py#L39) | 流式读取官方 tar.gz 内唯一数据流，应用快照和增量并检验有效盘口，保存每秒首个前二十档；假设接收延迟明确记录而非实测。 |
| Binance 成交及跨所因果对齐 | [core/cross_venue.py:347 · analyze_cross_venue](../core/cross_venue.py#L347) | 同日 Bybit/OKX 簿按因果时间对齐，双向模拟买卖腿并各扣一次费用；输出快照机会和质量，不累计重叠时点成策略收益。 |
| 数据质量和过去时点查找 | [core/quality.py:27 · asof_index](../core/quality.py#L27) | 二分查找不晚于目标时刻的最后一个观测；无过去观测或超陈旧度返回 None，绝不使用未来行。 |
| 逐档主动成交与费用 | [core/execution.py:52 · sweep](../core/execution.py#L52) | 按买入吃卖盘、卖出吃买盘逐档撮合，累计金额和费率，输出明细、均价和缺量；深度不足不外推成交。 |
| 静态多场所路由 | [core/solver.py:20 · optimize_static_route](../core/solver.py#L20) | 校验盘口、方向、目标和各所余额；按含费边际价格排序逐档分配并扣减资金。返回成交分配、费用及缺量。精确性限于独立档位和线性费率，不模拟排队、gas或市场冲击。 |
| 静态求解服务 | [core/optimizer.py:57 · run_static_snapshot](../core/optimizer.py#L57) | 取得因果双所快照后调用静态分配，将配置、数据依据和结果保存到新的不可变实验目录。 |
| 条件机器学习与因果特征 | [core/conditional_model.py:272 · live_feature_row](../core/conditional_model.py#L272) | 只从当前簿与过去一分钟价格生成十二项条件特征，检查连续性、可见深度和训练期限；不能把未来标签当输入。 |
| 条件模型训练与冻结 | [core/conditional_model.py:156 · train_conditional_model](../core/conditional_model.py#L156) | 每目标在训练集拟合 Ridge/提升树，在时间验证集与 persistence 比 MAE；选型后仅重拟合训练加验证，写新版本权重及摘要。失败模型不强行替代基线。 |
| MPC 反向动态规划 | [core/mpc.py:162 · _plan](../core/mpc.py#L162) | 枚举每时段整数数量动作，反向动态规划：剩余量为状态，阶段成本加后续最优值；终端必须完成。返回首步、计划和预测目标；同目标优先早执行，不代表市场全局最优。 |
| MPC 历史回放与基线比较 | [core/mpc.py:331 · run_mpc_replay](../core/mpc.py#L331) | 校验数量精度、期限、资源上限和数据覆盖；阻止训练截止前使用冻结模型。隔离回放 MPC/尽早/等额方案，保存配置、来源和不可变报告。 |
| 自有盘口深度消耗 | [core/liquidity.py:6 · DepthConsumption](../core/liquidity.py#L6) | 为一个方案隔离深度账本；外生盘口内容改变后才重新建立可用深度。 |
| 被动队列情景及逐笔成交轨迹 | [core/passive.py:25 · simulate_passive_limit](../core/passive.py#L25) | 在订单到达时取可见盘口并检查非主动穿价；通过反向主动成交量推进三种假设队列，输出成交轨迹及未成交量。触价不等于成交，结果不是真实成交概率。 |
| S3 事前限价方案选择 | [core/limit_optimizer.py:29 · choose_limit_plan](../core/limit_optimizer.py#L29) | 只用决策前一分钟成交和当前盘口评分；未来成交绝不参与候选选择。 |
| S3 撤改、撤单确认与主动补单 | [core/limit_optimizer.py:85 · replay_limit_plan](../core/limit_optimizer.py#L85) | 执行已选方案：挂单→可选撤改→撤单确认→补单；完整轨迹只供事后核验。 |
| S3 参数服务与原方案比较 | [core/limit_optimizer.py:172 · run_limit_optimization](../core/limit_optimizer.py#L172) | 看板服务入口：校验参数→读同日簿/成交→事前选方案→三情景回放→保存不可变报告。 |
| 封存窗口预登记 | [core/acceptance.py:20 · register_acceptance](../core/acceptance.py#L20) | 在读取测试行情前锁定日期、模型、代码和八个固定订单场景；已缓存/已注册日期拒绝。 |
| 封存样本外验收 | [core/acceptance.py:57 · evaluate_acceptance](../core/acceptance.py#L57) | 一次性打开已登记日：先写 opened，再下载/核验、预测评分与八场景回放，绝不重新训练。 |
| 后台封存任务与取消 | [core/acceptance.py:126 · submit_acceptance](../core/acceptance.py#L126) | 看板先登记再提交串行后台验收，返回id以便页面刷新后轮询，不阻塞页面下载。 |
| 隔离账本与风控 | [core/ledger.py:8 · Ledger](../core/ledger.py#L8) | 为单一场所维护资产、成本基础、费用与拒单事件；ETH/WETH与gas资产分开，不假设跨场所转移。 |
| 独立资金核对 | [core/ledger.py:86 · reconcile](../core/ledger.py#L86) | 独立按成交方向汇总资金流与gas，不调用 Ledger.apply；检测重复和容差内余额差，返回重建账目。 |
| 库存减仓建议 | [core/risk.py:6 · reduction_proposal](../core/risk.py#L6) | 检查超额库存，只有 CEX本地库存且有新鲜深度时估算减仓。只生成建议，不执行或改账；DEX资产不能直接当CEX可卖余额。 |
| 链上只读状态与报价 | [core/network.py:48 · DexReader](../core/network.py#L48) | 只读以太坊池状态和Quoter适配器，所有调用固定区块；不包含私钥、签名或提交交易。 |
| AMM 跨 tick 数学 | [core/defi.py:38 · v3_exact_input](../core/defi.py#L38) | 逐个已知初始化边界计算输入/输出和向上舍入池费，跨 tick 更新净流动性；到最后已知边界停止，绝不虚构未知深度。 |
| LP 仓位与敏感性 | [core/lp.py:35 · scenario](../core/lp.py#L35) | 以参考价生成对齐tick的固定宽度演示仓位，按价格冲击计算资产、持币对照和手续费盈亏平衡；不声称历史手续费收益。 |
| 成交订单流分析 | [core/flow.py:7 · aggregate_trades](../core/flow.py#L7) | 按时间桶汇总成交量、名义额、主动方向和RPI占比；桶结束才标为可用，避免提前读取整桶未来成交。 |
| CEX/DEX 报价机会 | [core/arbitrage.py:5 · opportunity](../core/arbitrage.py#L5) | 检查 CEX/DEX报价新鲜度、方向、规模和同区块，在两条相反路线扣一次交易所费与gas。返回纸面净差，不保证非原子双腿成交。 |
| 实时缓存与数据库 | [core/store.py:18 · Store](../core/store.py#L18) | 保存实时观测和worker心跳的有界运行缓存；历史原始档案留在唯一文件目录。 |
| 实时行情后台 | [worker.py:17 · run](../worker.py#L17) | 在给定期限内并行只读采集与推断，写有界缓存和心跳，退出记录停止；不发送交易。 |
| 冻结模型只读推断 | [core/live_model.py:12 · LiveModel](../core/live_model.py#L12) | 只加载冻结本地模型做只读推断，不在实时循环训练或发送订单。 |
| FastAPI 健康与行情接口 | [service.py:19 · health](../service.py#L19) | 读取心跳，按CEX/DEX允许年龄判断陈旧，并结合worker状态输出market_ready；API存活不等于可交易。 |
| 历史报告与成本归因 | [core/reporting.py:173 · report](../core/reporting.py#L173) | 串联成本比较、回放、风控、LP演示和手算明细，写各报告并返回质量统计和对账结果。 |
| 证据摘要与运行日志 | [core/io.py:81 · log](../core/io.py#L81) | 追加一行带 UTC 时间和事件字段的 JSON 日志，不改写既有事件；调用方不得传入敏感凭据。 |
| 测试网回执验证 | [core/proof.py:27 · validate_receipt](../core/proof.py#L27) | 逐项检查测试网、成功状态、交易目的/发送人、区块一致性和所需日志，拒绝主网或回滚；第三方回执不证明个人操作。 |

```mermaid
flowchart LR
  A[看板输入] --> B[参数与来源检查] --> C[数据规范化与因果回放]
  C --> D[条件预测或透明基线] --> E[静态 / MPC / S3 求解]
  E --> F[主动或队列情景模拟] --> G[资产与费用核对] --> H[方案对比与导出]
  F --> C
```

静态直接使用当前盘口；MPC 的未来成本由预测或基线估计；S3 首版使用过去成交量外推，不使用未来真实成交选择方案。

完整函数、方法和嵌套回调列表见 [CODE_MAP.md](CODE_MAP.md)。

运行启动脚本：[start_local.ps1](../start_local.ps1#L1)；本机端口判断函数带中文说明。当前支持范围与未完成能力见[项目概览](../README.md)。
