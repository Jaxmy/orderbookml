# CEX / DEX Order Execution Research Engine

[**English**](README.md) | [简体中文](README.zh-CN.md)

Review historical markets and compare execution plans for an order under the same budget, fees, and time constraints. The engine brings centralized-exchange books and trades, Uniswap V3 pool states, machine-learning estimates, and execution solvers into one research workflow. All parameters and results are handled in the Streamlit dashboard.

![Project status](https://img.shields.io/badge/status-P5%20in%20progress-orange) ![Python](https://img.shields.io/badge/Python-3.14-blue) ![License](https://img.shields.io/badge/license-MIT-green)

> This project is for local research and paper execution. It does not sign or submit live orders, and it has not established a profitable strategy. The project uses the MIT license already present in the target repository; see [LICENSE](LICENSE).

## Contents

- [What the project does](#what-the-project-does)
- [Components, technology, and limitations](#components-technology-and-limitations)
- [Data sources and coverage](#data-sources-and-coverage)
- [Installation](#installation)
- [Example workflow](#example-workflow)
- [Current progress and next steps](#current-progress-and-next-steps)
- [Engineering references](#engineering-references)
- [Development and contribution](#development-and-contribution)
- [License](#license)

## What the project does

Provide a market and time window, trading pair, side, order size or budget, and constraints such as fees, balances, latency, and deadline. The system reconstructs available historical books, calculates aggressive execution costs, compares static venue allocation, limit-order scenarios, or dynamic execution plans, and saves a reproducible experiment report.

The research engine and its information boundary are fixed; market data, dates, orders, and fees are supplied for each experiment. Historical data must come from a supported adapter. If a source cannot provide the requested date, the run reports why instead of fabricating missing observations.

## Components, technology, and limitations

### Dashboard and experiment service

**Purpose:** Enter parameters, start or cancel experiments, follow progress, review past runs, repeat the same settings, download results, and import personal execution records.

**Implementation:** Python, Streamlit, and Plotly; the internal research API uses FastAPI. The dashboard defaults to English and can switch to Chinese. SQLite stores research jobs, while a separate serial worker runs long tasks so closing the page does not discard a job.

**Data:** Local input and uploaded files, experiment result folders, and the job database. The API does not provide market data of its own.

**Current limitations:** Jobs and results are stored locally, with no shared queue across hosts. Imported fills show what actually executed but cannot reconstruct unfilled orders or the original order intent.

**Possible extensions:** Import original orders, cancellations, and partial fills, then compare the actual plan with an optimized one under matching constraints. Validate a multi-user service and centralized task queue afterward.

### Market data ingestion and order-book reconstruction

**Purpose:** Acquire or import market archives, validate timestamps, update sequence, and archive completeness, then build historical order-book views.

**Implementation:** A Bybit snapshot/delta state machine maintains price levels and checks update identifiers, crossed books, and gaps. The OKX adapter extracts official historical archives and normalizes them to a shared book format. Processed observations are stored internally as Parquet, with a configured cap for large files.

**Data:** Bybit ETHUSDC spot archives from the [Bybit historical order-book directory](https://quote-saver.bycsi.com/orderbook/spot/ETHUSDC/). For OKX ETH-USDC historical L2, users download an archive from the [OKX historical data page](https://www.okx.com/en-us/historical-data) and upload it in the dashboard. Existing research windows cover 2026-09-01 through 2026-09-07 UTC; these market files are not included in the source package.

**Current limitations:** Strategies use price-level aggregated L2 data. They do not know each order's queue position at a price level or model the impact of the simulated order on the market. OKX historical coverage depends on the archive supplied by the user.

**Possible extensions:** Add validated historical L2 adapters for more venues, preserve raw-data versions and clock semantics, and calibrate queue models when finer-grained data is available.

### Binance market reference and cross-venue comparison

**Purpose:** Align Bybit and OKX books over the same historical window and compare aggressive execution costs in both directions; Binance trade prices can serve as an additional reference.

**Implementation:** Causal alignment uses event time and assumed latency. A shared level-by-level matching calculation compares venues and applies each venue's fees separately.

**Data:** Daily Binance ETHUSDC trade ZIP archives from [Binance Vision spot trades](https://data.binance.vision/data/spot/daily/trades/ETHUSDC). Real-time depth checks use Binance public REST/WebSocket endpoints. Historical trade-price references are not historical Binance order books.

**Current limitations:** The validated Binance adapter provides trade archives, not historical L2 depth suitable for execution simulation. Binance therefore cannot participate in current static executable routing. A quoted cross-venue spread is not guaranteed arbitrage profit; funds must already be available at each venue.

**Possible extensions:** Add Binance to executable book comparison and static routing only after obtaining and validating contemporaneous historical L2. Model transfer time, fees, and risks separately afterward.

### Execution costs and static venue allocation

**Purpose:** Calculate level-by-level costs for buying from asks or selling into bids, and allocate one aggressive order across available venue books.

**Implementation:** Decimal-precision matching. Static routing sorts fee-adjusted marginal prices and constrains each venue by its balance and visible depth. Under linear fee rates and independent price-level assumptions, the allocation is exact for the supplied books.

**Data:** Historical Bybit/OKX L2, user-entered size or budget, fees, latency, and balances at each venue.

**Current limitations:** Static routing covers Bybit and OKX only. It excludes Uniswap, inter-venue transfers, market impact, and passive-order fill probability. Visible book depth does not guarantee that the full order will execute.

**Possible extensions:** Add verifiable DEX paths, gas, ETH/WETH wrapping, and asset-balance constraints to a common optimizer. Reject a path whenever required cost or balance information is missing.

### MPC dynamic execution and passive limits

**Purpose:** Compare immediate execution, slicing, and waiting within an execution deadline. The Bybit limit module also evaluates a finite set of placement, cancel/replace, and remainder-taking scenarios.

**Implementation:** Model Predictive Control (MPC) plans the remaining steps at each point, executes only the current step, and replans using information available at that time. S3 searches a declared finite candidate set. Passive fills are replayed under conservative, middle, and optimistic queue assumptions, including cancellation confirmation and remainder handling.

**Data:** Bybit ETHUSDC L2 and trades, historical prices from the same window, assumed fees, latency, balances, and order deadline.

**Current limitations:** MPC currently covers Bybit alone, and future book depth is approximated. L2 does not reveal queue order, so the limit module returns scenario ranges rather than calibrated fill probabilities. Forecast error can make a plan worse than an immediate-execution baseline under the same constraints.

**Possible extensions:** Add other venues' books and independent balance states for cross-venue dynamic MPC. Report passive fill probabilities only after reliable queue labels are available.

### Machine learning

**Purpose:** Estimate short-term execution-price changes, book execution costs, and volatility risk as inputs to MPC's future-cost estimates.

**Implementation:** Python and scikit-learn. Ridge, histogram gradient-boosted trees, and recent-market baselines are compared using time-ordered validation error. Features are constructed from current and past books, trades, and prices. Training, validation, and a sealed test are separated in time; predictions are checked against their supported side, size, and horizon.

**Data:** The current frozen study is mainly based on Bybit ETHUSDC historical order-book and trade windows. Local archives and trained weights are not included in the source package.

**Current limitations:** The sample covers a limited number of dates, venues, and market conditions. In the existing sealed evaluation, the adverse-price-change model did not outperform a simple baseline; the volatility task may also fall back to a baseline. Predictions are not trading direction or a guarantee of returns.

**Possible extensions:** Evaluate generalization across more market conditions and held-out dates, add quantile-risk estimates and fill-probability labels, and keep recording training data, model applicability, and sealed test dates separately.

### Uniswap V3 and on-chain costs

**Purpose:** Read a pool state at a fixed historical block and obtain a swap quote, then compare a WETH/USDC pool quote with exchange books, pool fees, and estimated gas in a single-order cost view.

**Implementation:** Python, Web3.py, and read-only Ethereum `eth_call`. The comparison fixes a block, records its hash, and states WETH/USDC settlement and gas assumptions. Pool quotes already include the swap fee, so the report does not deduct it a second time.

**Data:** The Ethereum mainnet Uniswap V3 ETH/USDC pool (the assets are WETH/USDC). Historical state and Quoter calls use the default public RPC `https://eth.drpc.org`; a local node can be selected with the `ETH_RPC_URL` environment variable.

**Current limitations:** A quote comparison is not a jointly optimized cross-venue route. The current model excludes approvals, wrapping/unwrapping, failed-transaction fees, transaction ordering, and atomic execution. A historical Swap/Mint/Burn log downloader exists, but the public node tested could not serve historical event logs for the target window; the full tick state has not been reconstructed. Each on-chain event has a block timestamp and an order within the block, but no independently observed millisecond timestamp.

**Possible extensions:** Use an archive RPC that supports historical event queries or verifiable event files, restore the complete initial tick/liquidity state, and replay events individually. Then include realistic gas ranges, wrapping costs, and non-atomic execution exposure.

### LP analysis, ledger, risk, and order flow

**Purpose:** Analyze LP asset changes and fees from pool states, summarize aggressive buy/sell flow, update paper balances after simulated fills, and independently reconcile fees and cash flows.

**Implementation:** Uniswap V3 multi-range tick math, fee-growth attribution, historical benchmark comparison, and independent ledger/reconciliation calculations. The dashboard displays price history, trade volume, order-flow imbalance, and reports.

**Data:** Local Uniswap V3 historical pool states, Bybit public trades, and reconstructed order books.

**Current limitations:** Pool history is sparse, and LP results are historical estimates for a small hypothetical position. They ignore the effect of simulated capital on the pool and do not represent actual wallet returns. The paper ledger is not an exchange account statement.

**Possible extensions:** Add finer pool events when needed, reconcile real account fills and fees, extend the historical period, and report inventory, unfinished orders, and risks across assets.

### Experiment records and resilience

**Purpose:** Keep parameters, model/code version summaries, results, failure reasons, and runtime resources. Long tasks can be queued or cancelled and can recover from an interrupted process.

**Implementation:** Persistent SQLite job queue, PostgreSQL or SQLite runtime cache, Parquet history files, JSON reports, and structured logs. A read-only single-venue shadow run on 2026-10-06 recorded 236 samples; after a controlled disconnect, market reconnection and collector restart recovery were observed. This does not count as a full-component stress test.

**Data:** Public market heartbeats, job state, local disk/memory metrics, and immutable experiment directories.

**Current limitations:** The service is intended for local research, with no cross-host queue or full production deployment. The one-hour shadow check covered only Bybit market data and Uniswap quote reads, and submitted no live orders.

**Possible extensions:** Build combined failure tests for supported venues, improve multi-user deployment, and add automated build and long-term resource alerts.

## Data sources and coverage

| Market | Data read by this project | Suitable for | Not sufficient for |
|---|---|---|---|
| Bybit ETHUSDC spot | Historical book archives, public trades, and read-only real-time book | Historical book reconstruction, level-by-level aggressive cost, MPC/S3 replay | Inspecting every individual order or its true queue position |
| OKX ETH-USDC spot | User-uploaded and validated historical L2 archives; public market checks | Same-window static cost comparison with Bybit | Inventing a book when an archive for the date is unavailable |
| Binance ETHUSDC spot | Official daily trade archives; public real-time depth endpoint | Trade-price reference and real-time connectivity checks | Executable historical cost routing using historical L2 today |
| Ethereum mainnet Uniswap V3 WETH/USDC | Pool state and Quoter at fixed historical blocks; historical log access depends on RPC | Single-swap historical quote comparison including assumed gas, and limited LP history analysis | Treating a quote as an execution or assuming ETH/WETH are interchangeable without wrapping cost |

Raw market data, training files, generated models, and runtime reports stay in local `data/` and are not part of the source package. The project's total research-data write budget is 5 GB. On first use, the dashboard can probe or download available Bybit daily archives. Users obtain OKX historical files from the official page and upload them. Date availability depends on what each source actually provides.

## Installation

The local dashboard targets Windows and Python 3.14. SQLite works for the first run; no account or PostgreSQL setup is required:

```powershell
# First, change to the extracted project directory
$projectPath = Read-Host 'Project folder path'
Set-Location -LiteralPath $projectPath

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$databasePath = (Join-Path $PWD 'data\operations.db').Replace('\', '/')
$env:DATABASE_URL = "sqlite:///$databasePath"
.\start_local.ps1
```

After startup, open [http://127.0.0.1:8502](http://127.0.0.1:8502). API documentation is available at [http://127.0.0.1:8010/docs](http://127.0.0.1:8010/docs); normal research workflows are completed in the dashboard. The PowerShell environment variable applies only to the current terminal session. PostgreSQL can also be configured through `DATABASE_URL`; set database credentials securely on the local machine and do not commit them.

## Example workflow

1. Open **Execution Research Workbench**, find the latest available Bybit date, and select a timestamp with a completed archive.
2. Choose buy or sell, enter an ETH quantity or USDC budget, and set fees, latency, deadline, and available balances.
3. Submit the run and review book levels, average execution price, fees, net spend or proceeds, completion, and sliced-order scenarios. Download the report when ready.
4. To compare Bybit with OKX, select the same date in **Cross-Venue Data & Arbitrage**. If the OKX archive is missing, download it from the official historical-data page and upload it there.
5. To assess Uniswap, compare a WETH-settled pool quote and state the gas limit and priority fee. Compare it with an exchange book available at the same time.
6. If you have actual fills, import a CSV, map its columns, and specify the timezone for timestamps without timezone information. The current import reports fill cash flows; it does not replace analysis of original orders and unfilled quantity.

Book depth, fees, and latency are model inputs. Check the report's data time, visible depth, completion ratio, and venue balance assumptions before interpreting cost figures.

## Current progress and next steps

As of 2026-10-12, the project supports parameterized aggressive CEX orders, Bybit MPC, Bybit passive-limit queue scenarios, Bybit/OKX static allocation, conditional machine learning, historical fill imports, Uniswap fixed-block quotes, LP analysis, a unified background job service, and a bilingual dashboard. Component tests and a short read-only connection-recovery check have been run. The latter covered only a limited set of venues and conditions and does not establish production reliability.

Overall, P5 is still in progress. Historical pool-event download and full tick reconstruction, executable Binance historical L2, joint CEX/DEX static routing, cross-venue dynamic MPC, reliable passive-fill probabilities, and attribution using original orders and trades under matching constraints remain incomplete. The project is for research and historical execution simulation; limited historical samples should not be read as proof of a live strategy. Public source code excludes local runtime logs, data, databases, and status files.

## Engineering references

- [Pipeline component guide and source locations](docs/COMPONENT_GUIDE.md)
- [Python functions, classes, and Chinese comment index](docs/CODE_MAP.md)
- [Supported scope and limitations](README.md#current-progress-and-next-steps)

## Development and contribution

Before changing a component, review its purpose, time semantics, and fee units. When adding a data source or strategy, record its source, information availability time, supported size, fee assumptions, and what it cannot simulate. A book being touched does not mean an order filled, and future prices must not be used to select historical actions.

Before submitting a change, run the following in the Windows project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:tmpdir -p no:cacheprovider -p tests.pytest_workspace_tmp
```

Include the change's purpose, supported market/window, command used, and result limitations. Large historical archives, private keys, `.env`, `.runtime`, SQLite/PostgreSQL databases, and generated runtime files must not be committed.

## License

This project is distributed under the target repository's existing [MIT License](LICENSE). Keep the license text and copyright notice when using, modifying, or redistributing it.
