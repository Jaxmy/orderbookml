"""一次性中文注释维护工具：显式功能说明映射，AST 定位插入，不修改函数业务语句。

只处理项目 root/core/tests 的 Python 源码，排除虚拟环境、数据库、历史产物及冻结权重。
已有中文说明保持原样；缺中文的函数/类用下列人工核对说明补齐，同时保留原英文文档。
执行后生成适用于 GitHub 的相对源码链接，行号以最终写回的 AST 为准。
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
M = {
'core/io.py': {
'utcnow':'生成带 UTC 时区的当前时间字符串，作为日志、清单和实验创建时间；不代表交易所事件时间。',
'sha':'以 1MB 分块读取文件并累计 SHA-256；返回十六进制摘要，避免把整个归档加载入内存。',
'dump':'创建目标父目录，把对象写为 UTF-8 JSON；禁止 NaN/Infinity，非 JSON 原生类型转字符串。会覆盖指定文件，调用方负责冻结目录保护。',
'read':'读取指定 UTF-8 JSON 并反序列化；文件不存在或格式损坏时向调用方抛错。',
'code_hash':'按文件名顺序把根目录和 core 的 Python 文件名及字节纳入摘要；注释修改也改变版本摘要。',
'manifest':'统计当前目录 Parquet/JSONL 的哈希，加入窗口、配置、版本和错误后写 manifest.json；原始来源说明属于早期采集流程。',
'verified_manifest':'读取清单并逐文件验证摘要，阻止清单路径逃出父目录；任一内容不符即拒绝继续分析。',
'log':'追加一行带 UTC 时间和事件字段的 JSON 日志，不改写既有事件；调用方不得传入敏感凭据。'},
'core/execution.py': {
'money':'把金额按既定精度量化，统一吃单报价和手续费的舍入规则。',
'levels':'将 JSON 档位转成 Decimal 价格/数量列表，检查正数和有限数；最多取前二十档作为可见执行深度。',
'validate_book':'解析买卖盘，检查排序及买一低于卖一，拒绝空簿、非法量价和交叉盘口；返回两侧 Decimal 档位。',
'mid':'校验盘口后计算买一与卖一的算术平均，作为成本比较参考价，不是可成交价。',
'sweep':'按买入吃卖盘、卖出吃买盘逐档撮合，累计金额和费率，输出明细、均价和缺量；深度不足不外推成交。',
'dex_cost':'读取已含池费的链上兑换报价，按 gas 用量、基础费及优先费折算 ETH/USDC 成本；不重复扣池费。'},
'core/quality.py': {'clean_books':'逐行检查盘口与可用时间，坏记录单独保留原因；有效记录排序并按 id 去重，返回清洗表和失败清单。',
'asof_index':'二分查找不晚于目标时刻的最后一个观测；无过去观测或超陈旧度返回 None，绝不使用未来行。',
'coverage':'以整个请求窗口的理论时间格为分母，计算被有效观测占据的格子比例；缺失窗口仍计入分母。'},
'core/orderbook.py': {'OrderBook':'维护 Bybit 快照和增量的状态机；缺快照或更新编号断档时停止输出，必须新快照恢复。',
'__init__':'初始化标的、严格连续编号策略、两侧档位、有效标记及断档/重置/重复计数。',
'apply':'按消息检查标的、时间、更新编号；快照重建，增量替换档位，零数量删除。断档或交叉时失效并返回 False。',
'row':'仅从有效簿态生成排序的前 depth 档位及事件/可用时间记录；无有效快照则抛错。'},
'core/solver.py': {'_floor_units':'用 Decimal 向下取整，将可用数量换为整数步长，保证成交不超数量精度或余额。',
'optimize_static_route':'校验盘口、方向、目标和各所余额；按含费边际价格排序逐档分配并扣减资金。返回成交分配、费用及缺量。精确性限于独立档位和线性费率，不模拟排队、gas或市场冲击。'},
'core/optimizer.py': {'causal_snapshot':'读取经哈希校验的 Bybit/OKX 同日盘口，根据事件时间加假设延迟向后查找并拒绝陈旧簿；返回两所快照和时序审计。',
'run_static_snapshot':'取得因果双所快照后调用静态分配，将配置、数据依据和结果保存到新的不可变实验目录。'},
'core/mpc.py': {
'bybit_days':'汇总旧历史目录与新市场缓存中的可用 Bybit 盘口日期；只代表本机已有数据，不保证外部所有日期可下载。',
'_path_for_day':'优先解析旧历史路径并在有清单时校验摘要，否则使用新市场适配器的已验证缓存。',
'load_bybit_timeline':'只加载单日盘口并按事件时间排序去重；事件时间加用户延迟形成可用时间，计算中间价并记录来源摘要。完整历史只供模拟器保存。',
'_at':'二分找目标时点已可知的最后盘口并检查簿龄；返回决策时刻标记或 None，不用最近未来盘口补缺。',
'_history_asof':'截断至决策时刻的历史中间价序列，形成传给特征/预测模块的信息边界。',
'_past_volatility_bps':'在过去一分钟中间价变动上计算收益标准差，换为 bps；样本不足返回零，是透明历史风险基线。',
'_expected_action_cost':'当前动作按真实可见簿吃单；未来动作使用适用范围内的冻结条件预测，否则持平基线。加入手续费和波动风险罚项；卖出目标取收入负值以统一最小化。',
'_plan':'枚举每时段整数数量动作，反向动态规划：剩余量为状态，阶段成本加后续最优值；终端必须完成。返回首步、计划和预测目标；同目标优先早执行，不代表市场全局最优。',
'_execute_child':'把单个 Bybit 子单交给静态吃单计算，按当前 USDC/ETH 余额限额执行；返回真实模拟成交量、金额、费用和逐档明细。',
'_run_replay':'按时间推进决策，仅把当前簿和过去价格传给规划器；到达时重新取簿成交，扣自有深度和更新余额。三个策略遵守同一子单上限，完成或截止后汇总。',
'run_mpc_replay':'校验数量精度、期限、资源上限和数据覆盖；阻止训练截止前使用冻结模型。隔离回放 MPC/尽早/等额方案，保存配置、来源和不可变报告。'},
'core/passive.py': {'_is_tick_multiple':'检查限价是否为价格最小跳动的整数倍，不通过舍入偷偷改变用户限价。',
'simulate_passive_limit':'在订单到达时取可见盘口并检查非主动穿价；通过反向主动成交量推进三种假设队列，输出成交轨迹及未成交量。触价不等于成交，结果不是真实成交概率。',
'run_scenario':'按时间累积符合方向和价格条件的主动成交，先扣前方队列再计自身成交，记录每笔新增量并在完成时停止。',
'load_bybit_passive_day':'按日期读取 Bybit 同日盘口和成交 Parquet，任一文件缺失直接拒绝；不把只有成交数据的场所冒充有盘口。'},
'core/conditional_model.py': {
'_top':'校验盘口并取前五档浮点价格与数量，供条件特征汇总；与成交引擎的 Decimal 计算分离。',
'_day_samples':'把一日盘口向后对齐到秒格，构造过去特征和买卖方向/数量/期限条件；未来行仅计算标签。过滤缺失、陈旧或深度不足窗口。',
'build_training_frames':'只载入预定训练日及验证日；标签终点触及分区边界的样本剔除。返回两张样本表和来源/时间边界清单，不读取最终测试日。',
'datetime_iso':'将 Unix 秒转换为明确 UTC 的 ISO 时间字符串，用于模型时间边界记录。',
'train_conditional_model':'每目标在训练集拟合 Ridge/提升树，在时间验证集与 persistence 比 MAE；选型后仅重拟合训练加验证，写新版本权重及摘要。失败模型不强行替代基线。',
'load_conditional_model':'校验模型标识、冻结状态和本地权重摘要后加载；不接受任意外部 pickle 或静默改写权重。',
'predict_conditional':'校验特征契约并使用冻结模型预测；未保留模型的目标使用当前成本/历史波动基线，输出模型版本。',
'live_feature_row':'只从当前簿与过去一分钟价格生成十二项条件特征，检查连续性、可见深度和训练期限；不能把未来标签当输入。',
'asof':'从已经截断的历史序列找不晚于目标的中间价；缺观测或间隔超过三秒返回 None。',
'predict_with_models':'按冻结特征顺序组成表格并限制线程数，批量调用各目标模型；缺模型的目标由上层补基线。',
'list_conditional_models':'枚举本地冻结版本清单并按创建时间倒序；不训练、加载全量行情或更改任何权重。'},
'core/experiment_engine.py': {
'_bytes':'累计目录文件大小，忽略遍历期间已消失的文件，供五十亿字节资源预检使用。',
'local_days':'汇总本机 Bybit 已规范化日期，返回有序去重列表供看板选择缓存。',
'probe_latest':'从最近过去日期向前检查公开 Bybit 日档 HEAD，检查长度预算并返回首个可用来源；保留失败原因，不把实时接口当历史数据。',
'_resolve_book':'定位已有旧目录或新市场缓存，核验清单与盘口哈希；已有文件不符时拒绝而非悄悄重建覆盖。',
'_prepare_day':'复用经验证的缓存或下载受大小限制日档，检查 ZIP CRC，流式应用快照/增量，每秒输出首个有效前二十档视图。进度/取消由回调与事件控制。',
'_unit_sweep':'检查正数量并调用共用逐档吃单引擎，统一数量和费率格式。',
'_budget_sweep':'在可见深度范围对整数数量步长二分，找含费不超 USDC 预算的最大买入量；预算模式不支持卖单。',
'_fill_at':'按下单时点加延迟，在事件时间序列向后查盘口；缺簿和陈旧分别返回拒单原因。',
'_simulate':'模拟立即或等额父单切片，逐切片计费用、缺量、预算余量与参考价偏差；这是旧 P1 基线，不是求解器。',
'run_experiment':'校验市场、时区、规模和最长窗口，逐日准备缓存后运行 P1 立即/分批对照并返回数据质量及完成率报告。',
'_job_path':'校验实验 id 只允许固定长度字母数字，拼接项目内运行目录，阻止路径穿越。',
'_save_job':'在锁内更新内存状态副本，再写 job.json，供看板轮询与刷新恢复。',
'_worker':'后台执行单个实验，保存结果并将成功、取消或异常明确记录到状态和事件日志。',
'progress':'将数据/下载/规范化回调映射为页面进度和提示，更新持久任务状态。',
'submit':'生成新运行 id、取消事件并提交串行线程池；返回 id，不在页面线程执行长下载。',
'get_job':'优先读内存副本，服务重启后回读 job.json；无此任务或标识非法返回 None。',
'get_result':'校验运行 id 后读取已落盘结果，缺文件返回 None。',
'cancel':'给本进程仍可控制的任务设置取消事件并更新提示；进程已丢失的任务不会伪造取消成功。',
'recent_jobs':'枚举已保存任务状态，跳过损坏记录，按创建时间返回最近记录供看板历史列表。'},
'core/cross_venue.py': {
'_digest':'分块计算文件 SHA-256，用于下载、上传和规范化来源核验。',
'_market_dir':'将标准 ETHUSDC 映射为各所原生目录名称，OKX 使用 ETH-USDC；按场所和日期隔离。',
'download_binance_trade_archive':'有界下载 Binance 官方逐笔成交 ZIP，预留存储并支持取消；不声称此档案含历史 L2。',
'normalize_binance_trades':'流式清洗官方成交日档，识别时间单位、重复和乱序，批量写 Parquet 与清单；保留主动方向，不生成盘口。',
'ingest_okx_upload':'校验看板上传的官方日档文件名和容量，流式写项目缓存，已有档案按摘要判断复用或拒绝覆盖。',
'prepare_cross_venue_data':'依次取得 Bybit L2、OKX L2及 Binance 成交的已验证同日文件和清单。',
'_book_path':'仅返回对应场所日档已规范化且摘要匹配的 L2；缺失或篡改均停止。',
'_trade_path':'核验 Binance 成交 Parquet 与来源清单，返回合法路径；不能用它代替订单簿。',
'_asof_trade_context':'把较早已知 Binance 成交向后对齐到跨所盘口时点，加入成交价参照并限制陈旧度；未来成交不可进入。',
'analyze_cross_venue':'同日 Bybit/OKX 簿按因果时间对齐，双向模拟买卖腿并各扣一次费用；输出快照机会和质量，不累计重叠时点成策略收益。',
'_job_path':'校验跨所任务标识，限制结果路径在固定运行根目录。',
'_save_job':'锁内更新跨所任务状态并写磁盘，使刷新后能继续查看。',
'_cross_worker':'串行后台完成准备和同窗分析，分别记录完成、取消和失败；结果与任务 id 绑定。',
'progress':'按阶段底线和完成数量计算跨所进度，持久化当前提示供页面轮询。',
'submit_cross_venue':'创建排队记录和取消事件，提交单线程执行器，立即向看板返回任务 id。',
'get_cross_job':'从内存或磁盘恢复指定跨所任务，非法或不存在返回 None。',
'get_cross_report':'只读取已完成任务且位于项目允许目录的报告，缺失或路径非法返回 None。',
'cancel_cross_job':'请求仍在本进程的跨所任务取消，通过事件在下载或分析检查点停止。',
'recent_cross_jobs':'读取最近跨所任务的持久状态，按创建时间倒序供看板恢复和导出。'},
'core/okx_orderbook.py': {'_tree_bytes':'统计现有数据总大小，过滤并发消失文件，用于规范化和存储预留。',
'normalize_okx_archive':'流式读取官方 tar.gz 内唯一数据流，应用快照和增量并检验有效盘口，保存每秒首个前二十档；假设接收延迟明确记录而非实测。',
'update_side':'按价格替换数量，零量删除，并校验价量合法；更新当前买侧或卖侧字典。',
'encode':'对当前侧按买降卖升排序，取前二十档转 JSON，输出标准视图。'},
'core/ledger.py': {'Ledger':'为单一场所维护资产、成本基础、费用与拒单事件；ETH/WETH与gas资产分开，不假设跨场所转移。',
'__init__':'建立 CEX 或 DEX 的演示初始资金及参考成本，记录初始权益、已处理 id 和止损暂停状态。',
'equity':'用参考价估值所有非 USDC 资产并加现金，返回 Decimal 账面权益，不代表已经卖出。',
'status':'基于当前余额和成本基础计算已实现/未实现盈亏、费用及恒等式误差，并输出库存。',
'apply':'先校验成交和去重，再检查止损、现金底线、资产余额；通过后记费用和资金变化，否则保留拒单事件且库存不变。',
'reconcile':'独立按成交方向汇总资金流与gas，不调用 Ledger.apply；检测重复和容差内余额差，返回重建账目。'},
'core/risk.py': {'reduction_proposal':'检查超额库存，只有 CEX本地库存且有新鲜深度时估算减仓。只生成建议，不执行或改账；DEX资产不能直接当CEX可卖余额。'},
'core/defi.py': {'ceildiv':'整数除法向上取整，用于链上输入和费用保守舍入。',
'v2_exact_input':'按恒定乘积池及百万分比费率计算精确输入输出，以整数原始 token 单位舍入。',
'amount0_delta':'依据两端平方根价、Q96和流动性计算 token0区间数量，按指定方向上下舍入。',
'amount1_delta':'依据平方根价差和流动性计算 token1区间数量，按指定方向舍入。',
'v3_exact_input':'逐个已知初始化边界计算输入/输出和向上舍入池费，跨 tick 更新净流动性；到最后已知边界停止，绝不虚构未知深度。',
'fee_growth_inside':'根据当前 tick位置从全球增长减去区间外增长，使用 uint256模运算还原区间内手续费累计。',
'accrued_fees':'将流动性乘区间内手续费增长差，再除 Q128；模运算处理累计值回绕。',
'lp_attribution':'将仓位资产变化、对持币差额、手续费与gas分开归因，返回总盈亏及超额收益。'},
'core/lp.py': {'single_range_swap':'单一未跨初始化tick区间的浮点兑换公式；先扣池费再更新平方根价格，不适用于跨区间执行。',
'inventory':'把价格夹在给定LP区间，计算流动性对应两种资产数量；区间外仓位变为单一资产。',
'scenario':'以参考价生成对齐tick的固定宽度演示仓位，按价格冲击计算资产、持币对照和手续费盈亏平衡；不声称历史手续费收益。'},
'core/arbitrage.py': {'opportunity':'检查 CEX/DEX报价新鲜度、方向、规模和同区块，在两条相反路线扣一次交易所费与gas。返回纸面净差，不保证非原子双腿成交。'},
'core/flow.py': {'aggregate_trades':'按时间桶汇总成交量、名义额、主动方向和RPI占比；桶结束才标为可用，避免提前读取整桶未来成交。'},
'core/proof.py': {'decode_event':'按事件签名解码 ERC20 Transfer 或 V3 Swap 的地址及有符号金额；未知事件明确未验证金额。',
'validate_receipt':'逐项检查测试网、成功状态、交易目的/发送人、区块一致性和所需日志，拒绝主网或回滚；第三方回执不证明个人操作。'},
'core/network.py': {'rest_check':'只读查询 Binance市场元数据，确认 ETH/USDC标的有效并返回交易规则。',
'book_row':'把实时深度消息转标准盘口，接收时钟作为 available_at，校验后输出唯一 id。',
'ws_check':'连接公开行情WebSocket读取一条深度并校验，超时抛错；不登录交易账户。',
'DexReader':'只读以太坊池状态和Quoter适配器，所有调用固定区块；不包含私钥、签名或提交交易。',
'__init__':'由环境变量或默认URL初始化只读RPC客户端，保留配置，池地址等待元数据验证。',
'call':'拼ABI函数选择器和参数，固定 block执行 eth_call后解码返回值，不写链上状态。',
'verify':'验证网络和合约代码，查询工厂池地址及token顺序、费率、精度和tick间距；不符合预设则拒绝。',
'sample':'同一固定最新区块读取slot0、流动性和各规模双向报价；结束复核区块hash，若重组则整组拒绝。接收后才标为可用。'},
'core/store.py': {'engine_for':'按URL缓存有界SQLAlchemy连接池，设置连接超时和健康检查；凭据只进入连接，不返回给看板。',
'Store':'保存实时观测和worker心跳的有界运行缓存；历史原始档案留在唯一文件目录。',
'__init__':'选择环境变量/本机数据库配置或SQLite后备，建立事件和状态表，设置SQLite容量和忙超时。',
'put':'单事务清理六小时前观测、检查事件大小/条数、按id去重再写入；达到上限拒绝而不是无限增长。',
'heartbeat':'事务内替换对应worker状态记录，供健康检查判断运行及数据新鲜度。',
'health':'读取状态表并反序列化为组件字典；不把数据库可用等同市场可执行。',
'latest':'按可用时间倒序取指定事件，最多一千条，返回JSON数据列表供API及页面。'},
'core/live_model.py': {'LiveModel':'只加载冻结本地模型做只读推断，不在实时循环训练或发送订单。',
'__init__':'读取旧固定规模模型清单并核验权重摘要，通过后加载模型字典。',
'predict':'用决策时刻的因果特征预测旧任务；历史不足/过期返回None，基线胜出时使用基线并报告分布偏移。'},
'core/model.py': {'features':'重建秒格的过去收益/波动、五档盘口与当前半ETH买单成本；未来六十秒成本仅作y标签。在线模式允许无标签但必须有完整过去窗口。',
'split':'按先训练、后验证、最后测试切分时间，移除未来标签跨越下一边界的锚点。',
'metrics':'计算MAE、RMSE及目标尾部误差，与持平基线比较；基线为零时改善百分比返回None而非Infinity。',
'evaluate':'用给定已训练模型和基线预测，保存逐样本结果、误差及最差案例，不重训。',
'train':'在训练区拟合候选，在验证区选参数；样本不足明确返回。先冻结权重/清单，再评价内部测试，拒绝覆盖冻结模型。',
'external':'检验外部数据类型、冻结时间/配置和摘要，拒绝重复最终评价；使用既有模型只评分，不能把合成数据当真实。'},
'core/research.py': {'partition':'同时约束特征时刻、标签终点和标签实际可用时间归属分区，剔除跨界样本。',
'candidates':'建立两种岭回归和两种提升树的固定候选，标准化随Pipeline只在拟合输入上学习。',
'build_features':'复用旧盘口特征再加入未来波动标签和过去波动基线，校验向后时间对齐；标签不进入 FEATURES。',
'score':'计算模型与基线绝对误差差值，并以小时块bootstrap生成区间，减少重叠标签造成的虚假独立性；仅限给定样本。'},
'core/reporting.py': {'comparisons':'把链上报价向后匹配新鲜CEX簿，对比含费成本并生成费率/gas敏感性；markout只供事后观察不参与选择。',
'replay':'按预设历史意图在隔离CEX/DEX账本模拟成交，扫描期间止损并保留拒单；独立对账后生成逐分钟因果权益轨迹。',
'decisions':'从场所规模、费用排序、拒单风险提取可核查决策说明；真实案例不足时明确标合成压力，不冒充市场收益。',
'report':'串联成本比较、回放、风控、LP演示和手算明细，写各报告并返回质量统计和对账结果。'},
'market_app.py': {'read':'页面读取可选JSON，文件缺失时返回None以显示待完成状态，不伪造结果。',
'cached_bybit_passive_day':'以最多两个日期的有界Streamlit缓存读取同日盘口和成交，降低页面重绘开销。',
'render_experiment_result':'读取P1实验报告，在看板展示配置、来源、费用与完成率及逐单明细，并以独立上下文key提供导出。',
'render_cross_venue_job':'根据跨所任务状态显示进度、取消或失败；完成时展示同窗来源、套利成本及导出。',
'live_experiment':'页面定时片段轮询历史执行任务，更新进度和结果，避免刷新重复提交。',
'live_cross_venue':'页面定时片段轮询跨所数据任务，把持久状态和结果渲染到当前页面。'},
'service.py': {'database_unavailable':'把数据库异常转为HTTP503及本机恢复提示，不回显连接凭据。',
'health':'读取心跳，按CEX/DEX允许年龄判断陈旧，并结合worker状态输出market_ready；API存活不等于可交易。',
'market':'只接受已知流名称，返回有界最新观测，未知kind以404拒绝。',
'research':'读取已保存冻结研究和测试指标，文件尚未生成则明确pending。',
'quality':'读取历史规范化质量清单，缺清单返回pending。'},
'worker.py': {'run':'在给定期限内并行只读采集与推断，写有界缓存和心跳，退出记录停止；不发送交易。',
'cex':'订阅公开Bybit盘口，应用快照/增量并保存有效视图；断开后重连且等待有效簿恢复。',
'dex':'循环在后台线程读取同区块链上报价，写状态及成本机会；异常只记录类型，不暴露RPC凭据。',
'infer':'从运行缓存截取因果历史并调用冻结模型，写只读预测；不足时标明模型/历史未就绪。'},
'collect.py': {'preflight':'并行检查公开REST、WebSocket及RPC，把结果和错误类型写日志；拒绝凭据URL回显。',
'check':'等待单个连通性任务，将成功结果或不含凭据的错误分类放入预检字典。',
'preflight.dex':'在后台线程核验链上元数据并读取一组同区块报价。',
'capture':'校验新窗口和项目内输出路径，预留全局容量，采集只读数据并最终保存Parquet/清单；不覆盖冻结产物。',
'save':'向raw.jsonl追加单条观测，累计字节超预留时设置停止事件，避免无界写入。',
'fail':'将组件和异常类型记录到最多一千条错误列表，避免泄露凭据和无限增长。',
'cex':'在窗口内读取公开盘口，每秒保留一条有效接收记录；断开重连并遵守停止事件。',
'capture.dex':'按一分钟时隙读取同区块报价，过窗口或容量停止则退出。',
'main':'解析采集/预检/烟测命令参数，核验外部冻结窗口，调用异步流程并返回状态码。'},
'history_dex.py': {'sqrt_tick':'以九十位Decimal计算tick平方根价边界；是数学近似而非Solidity逐位TickMath实现。',
'Archive':'在只读DexReader上加入调用节流和历史区块查找，供四小时状态采样。',
'call':'历史RPC调用前短暂停顿以限制请求速率，随后沿用固定区块ABI调用。',
'block_at':'先扩大区块范围再二分，找时间戳不晚于目标的最后区块；不伪造逐交易毫秒时间。',
'main':'按固定历史配置确定LP边界并采样四小时池状态、费用增长和报价；每组核验hash后落盘，支持检查点缓存。'},
'research.py': {'prepare':'按既定日期构造并分开保存训练/验证/测试特征及摘要，保护旧研究输入。',
'load':'读取指定已保存分区并核验特征摘要，不重新切分或偷偷改窗口。',
'train':'只用训练/验证分区比较候选和历史基线，保存冻结权重、选择结果及代码/数据摘要。',
'evaluate':'核验冻结数据/代码，先记录最终测试已打开再一次性评分和写报告；禁止反复打开测试调参。'},
'download_history.py': {'usage':'累计历史研究存储占用，供归档下载前后容量检查。',
'main':'按固定研究清单下载公开Bybit日档，流式检查长度、CRC和容量，保存来源摘要；已有冻结归档只复用。'},
'prepare_history.py': {'main':'按哈希验证原始日档，流式重建每个增量，批量输出秒级前二十档视图；不覆盖旧规范化文件。'},
'example_budget_order.py': {'main':'在预定历史时点二分求含费五千USDC可买最大数量，独立重算逐档金额；未来markout只作事后估值。'},
'analyze.py': {'run':'核验采集清单、清洗盘口、生成质量和执行报告；数据及窗口满足要求才训练或做独立外部评价，记录资源。'},
'analyze_dex_history.py': {'analyze':'核验四小时池状态摘要，重建假设LP资产及手续费，逐点对比链上和CEX报价；不是全周逐事件回放。'},
'app.py': {'read':'读取早期看板可选JSON，文件缺失返回None供页面提示。',
'frame':'读取早期看板Parquet表，文件缺失返回空表，不创造行情。'},
'paper_replay.py': {'replay':'用冻结预测和盘口运行早期纸面策略/立即基线，记资金风险与费用；不发送真实订单。'},
'make_fixture.py': {'generate':'生成明确标注的合成软件验收数据和清单，供数学/异常路径测试；不混入真实市场研究结论。'},
'probe_history.py': {'probe':'对Tardis候选档案只读探测状态和小段响应，返回可访问性及错误类型，不下载整日数据。'},
'probe_network.py': {'probe':'只读检查给定公开行情/RPC服务连通情况，将成功与失败分类供来源选择。'},
'probe_public_archive.py': {'probe':'只读检查公开档案存在性、响应长度和格式，避免把不可访问文件当可用数据。'},
'setup_native_database.py': {'command':'执行本机数据库初始化所需子命令并检查退出状态；不把密码打印到结果。'},
'verify_runtime.py': {'size':'递归统计指定运行目录文件字节，供数据库/研究空间预算核验。'},
}

# 测试模块的说明明确核验对象；测试并不被当作市场盈利证据。
TEST_WORDS = {
'book':'构造可控的买卖档位测试输入，允许价格和数量变化，避免依赖网络行情。',
'_book':'构造指定时刻及中间价的有效盘口，供因果和成本测试。',
'books':'生成确定性的盘口时间序列，便于修改未来行核验信息隔离。',
'msg':'生成Bybit测试快照/增量消息，允许编号、时间和档位覆盖。',
'tmp_path':'为测试建立工作区内唯一临时目录，避开Windows系统临时目录权限问题，不删除历史证据。',
'first_plan':'对指定时间序列只取决策时可知簿和过去历史，再计算首步动作。',
'features':'以当前时点已知盘口和历史构建条件特征，验证未来数据修改不影响输入。',
'FakeStore':'提供隔离的数据库心跳替身，避免健康测试依赖真实数据库。',
'health':'返回固定的心跳和worker状态，用于检查市场新鲜度判断。',
}
TEST_DESCRIPTIONS = {
'reconstruction_gap_resnapshot':'快照/增量删除、编号断档后失效与新快照恢复',
'v2_hand_computation':'V2恒定乘积输出与独立整数手算',
'v3_crossing_and_unknown_depth':'V3跨tick流动性更新及未知边界停止',
'fee_growth_and_attribution':'区间手续费增长和LP盈亏归因',
'partition_purges_horizon':'未来标签跨分区边界剔除',
'volatility_label_never_enters_features':'未来波动标签不得进入决策特征',
'decision_features_do_not_require_future_labels':'在线特征不需要未来标签',
'arbitrage_fees_not_double_counted':'双向套利池费不重复扣除及陈旧报价拒绝',
'store_idempotent_and_retention':'缓存id去重和六小时保留窗口',
'testnet_proof_rejects_wrong_chain_and_revert':'错误网络与回滚回执拒绝',
'market_dashboard_all_pages':'各看板页面实际渲染无异常',
'health_uses_market_freshness_and_worker_state':'API健康不能把已停worker或陈旧行情标为可执行',
'trade_flow_bucket_is_causal_and_rpi_separate':'成交聚合桶结束后才可用并单列RPI',
'proof_decodes_signed_swap_amounts':'Swap事件有符号金额解码',
'live_prediction_ignores_future_rows':'实时冻结模型不读未来记录',
'hand_buy':'逐档买入、费用和均价与手算一致',
'hand_sell':'逐档卖出、费用和净收入与手算一致',
'partial_not_extrapolated':'深度不足保留缺量而不外推',
'crossed_book_rejected':'交叉盘口拒绝进入计算',
'dex_fee_not_double_counted':'DEX已含池费报价只另加gas',
'ledger_identity_and_independent_rebuild':'账本盈亏恒等式与独立现金流重建',
'duplicate_stale_and_insufficient':'重复委托、陈旧报价和余额不足的拒单',
'dex_gas_pnl_identity':'链上原生gas消耗计入盈亏恒等式',
'loss_limit_persists':'止损一旦触发不能因价格恢复自动抹掉',
'stale_reference_does_not_trigger_loss_pause':'陈旧估值不错误触发暂停',
'lp_boundary_and_conservation':'LP区间边界资产与守恒',
'single_range_independent_answer':'单区间兑换与独立预期答案',
'real_preflight_book_against_independent_answer':'真实预检盘口逐档独立核算',
'training_freeze_and_external_guards':'训练冻结、权重防篡改与外部窗口守卫',
'mpc_plan_respects_child_cap_and_completes_by_deadline':'MPC子单上限及截止完成要求',
'mpc_first_decision_does_not_depend_on_future_book_rows':'未来盘口修改不改变过去MPC首步',
'conditional_ml_features_are_invariant_to_future_market_rows':'条件特征不受未来行修改影响',
'mpc_replay_replans_and_accounts_for_actual_fills':'MPC重规划、实际成交费用与资金更新',
'static_router_sorts_fee_adjusted_marginal_levels':'静态路由按含费边际价格分配',
'static_router_obeys_local_quote_balances_and_budget':'各所余额隔离和总预算约束',
'passive_order_reports_queue_scenarios_and_excludes_future_and_rpi':'限价队列上下界、未来与RPI排除',
'passive_order_rejects_marketable_limit_and_bad_tick':'被动模块拒绝可成交限价和非法价格步长',
'proposal_does_not_move_inventory_or_hide_remaining_depth':'减仓建议不改库存并保留深度不足风险',
'dex_balance_not_sold_on_cex':'DEX库存不得当作CEX可卖资金',
'future_changes_do_not_change_past_features':'未来行情修改不改变过去特征',
'missing_window_is_not_zero_filled':'缺失历史窗口不得零填造信号',
'purge_horizon':'切分标签期限的隔离',
'asof_never_uses_future_and_stale_rejected':'向后对齐不读未来且拒绝陈旧',
'coverage_keeps_expected_denominator':'质量覆盖率保留完整请求窗口分母',
'manifest_tampering':'来源摘要篡改拒绝',
'zero_baseline_percentage_not_infinite':'零基线百分比不输出Infinity',
'partial_last_minute_coverage_is_bounded':'尾部不完整分钟覆盖率不超一',
'three_pages_render':'早期三页看板渲染与无异常',
'okx_archive_snapshot_and_delta_rebuild':'OKX档案快照、增量与零量删除',
'cross_venue_sweep_applies_both_fees':'跨所双腿手续费分别计算',
'binance_trade_reference_never_uses_a_future_trade':'Binance参照成交严格向后匹配',
}

files = sorted([*ROOT.glob('*.py'), *ROOT.glob('core/*.py'), *ROOT.glob('tests/*.py')])
missing = []
for path in files:
    source = path.read_text(encoding='utf-8-sig')
    tree = ast.parse(source)
    module = path.relative_to(ROOT).as_posix()
    descriptions = M.get(module, {})
    names = {}
    stack = [(tree, '')]
    while stack:
        parent, prefix = stack.pop()
        for child in ast.iter_child_nodes(parent):
            qualified = prefix
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualified = prefix + '.' + child.name if prefix else child.name
                names[id(child)] = qualified
            stack.append((child, qualified))
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    edits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        previous = ast.get_docstring(node, clean=False) or ''
        if re.search('[\u4e00-\u9fff]', previous):
            continue
        desc = descriptions.get(names[id(node)], descriptions.get(node.name))
        if not desc and module.startswith('tests/'):
            desc = TEST_WORDS.get(node.name)
            if node.name.startswith('test_'):
                test = TEST_DESCRIPTIONS.get(node.name[5:])
                if test:
                    desc = '验证' + test + '；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。'
        if not desc:
            missing.append(f'{module}:{node.lineno} {names[id(node)]}')
            continue
        args = []
        if not isinstance(node, ast.ClassDef):
            args = [a.arg for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs) if a.arg not in ('self','cls')]
        document = desc + ('\n\n    输入参数：' + '、'.join(args) + '（单位和范围由下方校验及调用方契约限定）。' if args else '')
        if previous:
            document += '\n\n    原始实现说明：\n    ' + previous.strip().replace('\n', '\n    ')
        # AST列偏移是UTF-8字节；按对应行前缀转换为Python字符坐标，不能直接相加。
        lines = source.splitlines(keepends=True)
        first = node.body[0]
        prefix = lines[first.lineno-1].encode('utf-8')[:first.col_offset].decode('utf-8')
        at = offsets[first.lineno-1] + len(prefix)
        indent = ' ' * (node.col_offset + 4)
        doc = '"""' + document.replace('\n    ', '\n' + indent) + '"""'
        existing = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value,str)
        if existing:
            end_prefix = lines[first.end_lineno-1].encode('utf-8')[:first.end_col_offset].decode('utf-8')
            end = offsets[first.end_lineno-1] + len(end_prefix)
            edits.append((at,end,doc))
        elif first.lineno == node.lineno:
            edits.append((at,at,'\n' + indent + doc + '\n' + indent))
        else:
            edits.append((at,at,doc + '\n' + indent))
    for begin,end,replacement in sorted(edits,reverse=True):
        source=source[:begin]+replacement+source[end:]
    ast.parse(source)
    if edits:
        path.write_text(source,encoding='utf-8')
if missing:
    raise SystemExit('Missing explicit explanations:\n' + '\n'.join(missing))

index=['# 代码阅读索引','',
       '坐标按最终源码定义行生成。点击链接先读函数/类的中文说明，再沿内部调用追踪。',
       '只索引项目自有 Python：根目录、core、tests；不修改第三方库或冻结产物。',
       '运行脚本没有函数的，入口为文件模块顶层。方法与内嵌回调同样列出。','']
total=0
for path in files:
    source=path.read_text(encoding='utf-8-sig');tree=ast.parse(source)
    relative=path.relative_to(ROOT).as_posix()
    index+=['## '+relative,'',f'[文件入口](../{relative}#L1)','', '| 函数 / 类 | 定义行 | 中文功能说明 |','|---|---:|---|']
    stack=[(tree,'')];entries=[]
    while stack:
        parent,prefix=stack.pop()
        for child in ast.iter_child_nodes(parent):
            qualified=prefix
            if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                qualified=prefix+'.'+child.name if prefix else child.name
                desc=(ast.get_docstring(child) or '').split('\n')[0].replace('|','／')
                if not re.search('[\u4e00-\u9fff]',desc):
                    raise SystemExit(f'Chinese coverage failed: {path}:{child.lineno}')
                entries.append((child.lineno,qualified,desc));total+=1
            stack.append((child,qualified))
    for line,name,desc in sorted(entries):
        index.append(f'| [{name}](../{relative}#L{line}) | {line} | {desc} |')
    index.append('')
index.insert(5,f'覆盖：{len(files)} 个文件，{total} 个函数/类定义（包含方法和嵌套函数）。')
(ROOT/'docs'/'CODE_MAP.md').write_text('\n'.join(index),encoding='utf-8')
print(f'Chinese docstrings verified: {total} definitions in {len(files)} files; docs/CODE_MAP.md written')
