"""Deterministic No-Lookahead Backtesting Framework for Quantitative Signals.

This module provides a minimal, deterministic, and non-lookahead evaluation framework
to evaluate the forward historical outcomes of quantitative signal recommendations produced
by VN Invest Signal Engine.

Key Architectural Principles:
1. Temporal Separation & As-Of Semantics:
   At evaluation date T, the quantitative engine strictly receives data timestamped <= T.
   Point-in-time dataset slicing strictly uses date comparison (date <= T), NOT positional iloc.
   Future data (> T) is strictly isolated and used solely for forward outcome evaluation.
   Future data quality (> T) does NOT affect signal generation at T.
   All market-level inputs (VNINDEX, VN30, and universe market breadth as-of T) are
   strictly bounded <= T before evaluating market regime and signal recommendations.
2. Forward Return Calculation:
   Forward return at horizon N (e.g., 5, 10, 20 trading sessions) is defined as:
       forward_return_N = (Price[T + N] / Price[T]) - 1.0
   If fewer than N future trading sessions exist after T or if future prices/dates are malformed,
   the outcome horizon is marked as unavailable (returns = None, availability = False).
   No extrapolation, interpolation, or fake fill values are used.
3. Direction-Aware Evaluation:
   Directional strategy return is calculated as:
       - BUY: +forward_return
       - SELL: -forward_return
       - HOLD / WATCH / AVOID: 0.0
4. Strategy Return Diagnostic Semantics:
   The metric `sum_strategy_return` represents the arithmetic sum of individual signal strategy returns.
   It serves as a simple diagnostic indicator of signal directionality, NOT a portfolio/compounded return.
5. Fail-Closed Temporal Contract & Validation:
   - `validate_backtest_dataset()` validates canonical OHLCV data-quality contracts.
   - `get_as_of_dataset()` and `evaluate_forward_outcomes()` are the temporal-sensitive entry points
     explicitly enforcing strict chronological ordering (is_monotonic_increasing) and unique dates.
   - Unsorted dates, duplicate dates, or future observations physically placed prior to T raise explicit
     ValueError exceptions rather than being silently swallowed, sorted, or positionally misindexed.
6. Framework Distinction & Disclaimers:
   This module explicitly distinguishes five separate concepts:
   1. Production Market Regime & Signal Generation: Real-time, point-in-time calculation of complete market
      regimes and stock signal recommendations using production model weights, confidence rules, and trade plans.
   2. Historical Market-Regime Validation (PR #92): Point-in-time descriptive evaluation measuring how production
      market regimes (STRONG_BULL, BULL, DEFENSIVE, BEAR, PANIC) assigned at date T map to forward market returns
      (5D, 10D, 20D) strictly without lookahead bias, threshold tuning, or model modification.
   3. Historical Component Evaluation (PR #88): Point-in-time measurement of individual signal component scores
      (Trend, Momentum, Volume, Relative Strength, Divergence) against forward historical returns
      on identical evaluation dates and horizons without model or weight modification.
   4. Execution & Liquidity Eligibility Evaluation (PR #90): Point-in-time evaluation of whether historical observable
      market liquidity timestamped <= T satisfies deterministic execution assumptions (min turnover, min volume,
      min price, max participation rate) without altering production signal scores or model weights.
   5. Portfolio Backtesting (PR #91): Simulation of portfolio-level capital allocation, position sizing,
      slippage, transaction costs, leverage, order book matching, and intraday execution dynamics
      (OUT OF SCOPE for this framework).
   6. Historical Confidence Evaluation & Calibration: Point-in-time observational measurement of production
      recommendation confidence values against observed forward outcomes (e.g., positive forward return rate,
      calibration gap) strictly without formula recomputation, probability assumptions, or model modification.

   Important Disclaimers for Historical Evaluation & Market-Regime Validation:
   - Observational evaluation layer: market regime / return association is purely descriptive and observational.
   - Does NOT demonstrate causal relationships.
   - Does NOT prove statistical significance (no p-values, hypothesis tests, or multiple-testing corrections).
   - Historical confidence calibration evaluates empirical alignment between heuristic confidence and observed forward outcomes;
     it does NOT convert confidence into a probability or establish causality or profitability.
   - Does NOT represent portfolio performance or real-world trade execution or profitability.
   - Does NOT perform parameter, model, or regime threshold optimization (no threshold tuning from historical results).
   - Does NOT automatically prove economic value of any regime or component.
   - "Executable" in this framework strictly means that observable market liquidity timestamped <= T satisfies defined assumptions;
     "Executable" trong framework này chỉ có nghĩa là thỏa execution/liquidity assumptions đã định nghĩa; nó không chứng minh rằng một lệnh thực tế chắc chắn được khớp.
   - Daily EOD OHLCV data does NOT model bid/ask spread, market impact, order book queue, intraday liquidity, trading halts, or broker/exchange execution behavior.
"""

import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from scripts.lib.recommendation import generate_recommendation
from scripts.lib.vietnam_market import get_clean_ohlcv_data, validate_ohlcv_data

DEFAULT_HORIZONS = [5, 10, 20]
DEFAULT_SIGNAL_COMPONENTS = [
    "trend",
    "momentum",
    "volume",
    "relative_strength",
    "divergence",
]
DEFAULT_CONFIDENCE_BUCKETS = [
    "[0.0, 0.1)",
    "[0.1, 0.2)",
    "[0.2, 0.3)",
    "[0.3, 0.4)",
    "[0.4, 0.5)",
    "[0.5, 0.6)",
    "[0.6, 0.7)",
    "[0.7, 0.8)",
    "[0.8, 0.9)",
    "[0.9, 1.0]",
]

# Execution Eligibility Status Constants
STATUS_EXECUTABLE = "executable"
STATUS_NOT_EXECUTABLE = "not_executable"
STATUS_INSUFFICIENT_LIQUIDITY_HISTORY = "insufficient_liquidity_history"
STATUS_INVALID_MARKET_DATA = "invalid_market_data"

# Execution Eligibility Reason Code Constants
REASON_BELOW_MIN_TRADED_VALUE = "below_min_traded_value"
REASON_BELOW_MIN_VOLUME = "below_min_volume"
REASON_BELOW_MIN_PRICE = "below_min_price"
REASON_EXCEEDS_MAX_PARTICIPATION = "exceeds_max_participation"
REASON_INSUFFICIENT_LOOKBACK_SESSIONS = "insufficient_lookback_sessions"
REASON_INVALID_OHLCV_DATA = "invalid_ohlcv_data"
REASON_ZERO_OR_NEGATIVE_LIQUIDITY = "zero_or_negative_liquidity"


def _validate_config_number(
    val: Any,
    field_name: str,
    min_val: float = 0.0,
    max_val: float | None = None,
    allow_zero: bool = True,
    strict_int: bool = False,
) -> None:
    """Validate numeric configuration parameters deterministically, raising ValueError on failure."""
    if val is None:
        return

    if isinstance(val, bool):
        raise ValueError(f"{field_name} cannot be a boolean, got {val}")  # noqa: TRY004

    if not isinstance(val, (int, float)):
        raise ValueError(f"{field_name} must be numeric, got {type(val).__name__}: {val}")  # noqa: TRY004

    if strict_int and not isinstance(val, int):
        raise ValueError(f"{field_name} must be an integer, got {type(val).__name__}: {val}")

    f = float(val)
    if math.isnan(f) or math.isinf(f):
        raise ValueError(f"{field_name} cannot be NaN or Inf, got {val}")

    if allow_zero:
        if f < min_val:
            raise ValueError(f"{field_name} must be >= {min_val}, got {val}")
    else:
        if f <= min_val:
            raise ValueError(f"{field_name} must be > {min_val}, got {val}")

    if max_val is not None and f > max_val:
        raise ValueError(f"{field_name} must be <= {max_val}, got {val}")


@dataclass
class ExecutionConfig:
    """Execution and liquidity assumption parameters for backtest signal evaluation layer.

    Parameters:
    - min_avg_traded_value_bn: Minimum average trading value over lookback window in billion VND
      (default: 1.0 billion VND = 1,000,000,000 VND).
    - min_avg_volume: Minimum average trading volume over lookback window in shares (default: 50,000 shares).
    - min_price: Minimum close price in VND/share (default: 5,000 VND/share).
    - max_participation_rate: Maximum order size participation rate ratio relative to average market volume (default: 0.10 = 10%).
    - estimated_order_size_shares: Optional estimated order size in shares for participation rate calculation.
    - estimated_order_value_vnd: Optional estimated order value in VND for participation rate calculation.
    - lookback_window: Historical session lookback window <= T used to calculate average liquidity metrics (default: 20 sessions).

    Disclaimers & Scope:
    - Conservative default thresholds are configurable and non-optimized.
    - No parameter optimization or curve-fitting based on historical returns is performed.
    - Slicing strictly enforces point-in-time rules timestamped <= T without lookahead bias.
    """

    min_avg_traded_value_bn: float | None = 1.0
    min_avg_volume: float | None = 50_000.0
    min_price: float | None = 5_000.0
    max_participation_rate: float | None = 0.10
    estimated_order_size_shares: float | None = None
    estimated_order_value_vnd: float | None = None
    lookback_window: int = 20

    def __post_init__(self) -> None:
        _validate_config_number(
            self.lookback_window,
            "lookback_window",
            min_val=1,
            allow_zero=True,
            strict_int=True,
        )
        _validate_config_number(
            self.min_avg_traded_value_bn,
            "min_avg_traded_value_bn",
            min_val=0.0,
            allow_zero=True,
        )
        _validate_config_number(
            self.min_avg_volume,
            "min_avg_volume",
            min_val=0.0,
            allow_zero=True,
        )
        _validate_config_number(
            self.min_price,
            "min_price",
            min_val=0.0,
            allow_zero=True,
        )
        _validate_config_number(
            self.max_participation_rate,
            "max_participation_rate",
            min_val=0.0,
            max_val=1.0,
            allow_zero=False,
        )
        _validate_config_number(
            self.estimated_order_size_shares,
            "estimated_order_size_shares",
            min_val=0.0,
            allow_zero=True,
        )
        _validate_config_number(
            self.estimated_order_value_vnd,
            "estimated_order_value_vnd",
            min_val=0.0,
            allow_zero=True,
        )

        if (
            self.estimated_order_size_shares is not None
            and self.estimated_order_value_vnd is not None
        ):
            raise ValueError(
                "estimated_order_size_shares and estimated_order_value_vnd cannot both be provided simultaneously."
            )


@dataclass
class ExecutionReturn:
    """Execution price and net return breakdown after transaction costs and slippage.

    Attributes:
    - entry_price: Reference EOD entry price at session T (VND/share).
    - exit_price: Reference EOD exit price at session T + N (VND/share).
    - action: Trade recommendation action ('BUY', 'SELL', 'HOLD', 'WATCH', 'AVOID').
    - entry_exec_price: Execution entry price after adverse slippage.
    - exit_exec_price: Execution exit price after adverse slippage.
    - gross_return: Reference price return before slippage and transaction costs.
    - slippage_adjusted_return: Return after adverse execution slippage, before transaction costs.
    - net_return: Final net return after execution slippage and transaction costs.
    - transaction_cost_pct: Total round-trip transaction cost ratio (e.g. 0.0030 = 0.30%).
    - slippage_pct: One-way adverse slippage ratio (e.g. 0.0010 = 0.10%).
    """

    entry_price: float
    exit_price: float
    action: str
    entry_exec_price: float
    exit_exec_price: float
    gross_return: float
    slippage_adjusted_return: float
    net_return: float
    transaction_cost_pct: float
    slippage_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "action": self.action,
            "entry_exec_price": self.entry_exec_price,
            "exit_exec_price": self.exit_exec_price,
            "gross_return": self.gross_return,
            "slippage_adjusted_return": self.slippage_adjusted_return,
            "net_return": self.net_return,
            "transaction_cost_pct": self.transaction_cost_pct,
            "slippage_pct": self.slippage_pct,
        }


def calculate_execution_return(
    entry_price: float,
    exit_price: float,
    transaction_cost_pct: float = 0.0,
    slippage_pct: float = 0.0,
    action: str = "BUY",
    cost_entry_pct: float | None = None,
    cost_exit_pct: float | None = None,
) -> ExecutionReturn:
    """Calculate deterministic execution price, slippage-adjusted return, and final net return.

    Fail-Closed Validation:
    - Rejects non-positive prices, negative costs/slippage, NaN, Inf, non-numeric types, and booleans.
    - Action must be one of ('BUY', 'SELL', 'HOLD', 'WATCH', 'AVOID').

    Slippage Semantics (Adverse Execution):
    - BUY:  entry_exec = entry_price * (1 + slippage_pct), exit_exec = exit_price * (1 - slippage_pct)
    - SELL: entry_exec = entry_price * (1 - slippage_pct), exit_exec = exit_price * (1 + slippage_pct)

    Transaction Cost Semantics:
    - Default total transaction cost is split equally across entry and exit legs unless cost_entry_pct / cost_exit_pct are supplied.
    - Net value return factor = (1 - cost_entry) * (exit_exec / entry_exec) * (1 - cost_exit) - 1.0 for BUY.
    - Zero cost and zero slippage preserves exact reference gross return.
    """
    _validate_config_number(entry_price, "entry_price", min_val=0.0, allow_zero=False)
    _validate_config_number(exit_price, "exit_price", min_val=0.0, allow_zero=False)
    _validate_config_number(
        transaction_cost_pct, "transaction_cost_pct", min_val=0.0, max_val=1.0, allow_zero=True
    )
    _validate_config_number(slippage_pct, "slippage_pct", min_val=0.0, max_val=1.0, allow_zero=True)
    _validate_config_number(
        cost_entry_pct, "cost_entry_pct", min_val=0.0, max_val=1.0, allow_zero=True
    )
    _validate_config_number(
        cost_exit_pct, "cost_exit_pct", min_val=0.0, max_val=1.0, allow_zero=True
    )

    if not isinstance(action, str) or action not in ("BUY", "SELL", "HOLD", "WATCH", "AVOID"):
        raise ValueError(f"Invalid action '{action}'. Must be one of BUY, SELL, HOLD, WATCH, AVOID")

    p_entry = float(entry_price)
    p_exit = float(exit_price)
    tc = float(transaction_cost_pct)
    slip = float(slippage_pct)

    c_entry = float(cost_entry_pct) if cost_entry_pct is not None else tc / 2.0
    c_exit = float(cost_exit_pct) if cost_exit_pct is not None else tc / 2.0

    if action == "BUY":
        entry_exec = round(p_entry * (1.0 + slip), 6)
        exit_exec = round(p_exit * (1.0 - slip), 6)
        gross_ret = round((p_exit / p_entry) - 1.0, 6)
        slip_ret = round((exit_exec / entry_exec) - 1.0, 6)
        net_ret = round((1.0 - c_entry) * (exit_exec / entry_exec) * (1.0 - c_exit) - 1.0, 6)
    elif action == "SELL":
        entry_exec = round(p_entry * (1.0 - slip), 6)
        exit_exec = round(p_exit * (1.0 + slip), 6)
        gross_ret = round(1.0 - (p_exit / p_entry), 6)
        slip_ret = round(1.0 - (exit_exec / entry_exec), 6)
        net_ret = round((1.0 - c_entry) * (1.0 + slip_ret) * (1.0 - c_exit) - 1.0, 6)
    else:  # HOLD / WATCH / AVOID
        entry_exec = p_entry
        exit_exec = p_exit
        gross_ret = 0.0
        slip_ret = 0.0
        net_ret = 0.0

    return ExecutionReturn(
        entry_price=p_entry,
        exit_price=p_exit,
        action=action,
        entry_exec_price=entry_exec,
        exit_exec_price=exit_exec,
        gross_return=gross_ret,
        slippage_adjusted_return=slip_ret,
        net_return=net_ret,
        transaction_cost_pct=tc,
        slippage_pct=slip,
    )


@dataclass
class ExecutionEligibility:
    """Execution and market-liquidity eligibility status at evaluation date T.

    Attributes:
    - status: Deterministic status identifier ('executable', 'not_executable', 'insufficient_liquidity_history', 'invalid_market_data').
    - is_executable: True if status == 'executable', False otherwise.
    - reasons: List of deterministic reason codes explaining non-executability.
    - metrics: Point-in-time liquidity metrics at signal date T over lookback window <= T.

    Disclaimer:
    "Executable" in this framework strictly means that historical observable market liquidity timestamped <= T
    satisfies the defined execution/liquidity assumptions. It does NOT guarantee or prove that a real-world market order
    would be filled at or near the evaluation price.
    """

    status: str
    is_executable: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "is_executable": self.is_executable,
            "reasons": self.reasons,
            "metrics": self.metrics,
        }


def _safe_float(val: Any) -> float | None:
    """Safely convert value to float, returning None if None, NaN, or Inf."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _find_date_column(df: pd.DataFrame) -> str | None:
    """Identify the date or time column name in a DataFrame."""
    if df is None or df.empty:
        return None
    for col in ["date", "time", "Date", "Time"]:
        if col in df.columns:
            return col
    return None


def _parse_canonical_date(eval_date: Any) -> str:
    """Parse and validate evaluation date into YYYY-MM-DD canonical format.

    Fail-Closed Validation:
    - Accepts canonical YYYY-MM-DD strings and calendar-date naive timestamps/datetimes.
    - Rejects None, booleans, timezone-aware timestamps/datetimes/strings.
    - Rejects date strings containing time components (e.g. 'YYYY-MM-DD HH:MM:SS') or timestamps with non-zero time components.
    - Rejects invalid or unparseable date strings.
    """
    if eval_date is None or isinstance(eval_date, bool):
        raise ValueError(f"Invalid evaluation date: {eval_date}")

    if hasattr(eval_date, "tzinfo") and eval_date.tzinfo is not None:
        raise ValueError(
            f"Timezone-aware evaluation date input is rejected to prevent timezone ambiguity: {eval_date}"
        )

    if isinstance(eval_date, str):
        s = eval_date.strip()
        if "+" in s or "Z" in s or "UTC" in s:
            raise ValueError(f"Timezone-aware evaluation date string is rejected: {eval_date}")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            raise ValueError(
                f"Evaluation date string must be strictly canonical 'YYYY-MM-DD', got '{eval_date}'"
            )
        try:
            ts = pd.to_datetime(s, format="%Y-%m-%d")
            if pd.isna(ts):
                raise ValueError(f"Invalid evaluation date: {eval_date}")
            return ts.strftime("%Y-%m-%d")
        except (ValueError, TypeError, OverflowError) as err:
            raise ValueError(f"Invalid evaluation date format '{eval_date}': {err}") from err

    if hasattr(eval_date, "time") and callable(eval_date.time):
        t = eval_date.time()
        if t.hour != 0 or t.minute != 0 or t.second != 0 or t.microsecond != 0:
            raise ValueError(
                f"Evaluation date containing non-zero time component is rejected: {eval_date}"
            )

    try:
        ts = pd.to_datetime(eval_date)
        if pd.isna(ts) or ts.tz is not None:
            raise ValueError(f"Invalid or timezone-aware evaluation date: {eval_date}")
        return ts.strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError) as err:
        raise ValueError(f"Invalid evaluation date format '{eval_date}': {err}") from err


@dataclass
class BacktestSignal:
    """Signal state at evaluation time T (no future information included)."""

    symbol: str
    evaluation_date: str
    action: str
    signal_score: float | None
    confidence: float
    market_regime: str
    risk_adjusted_score: float | None
    data_quality: str
    model_version: str
    entry_price: float | None
    score_components: dict[str, float | None] = field(default_factory=dict)
    execution_eligibility: ExecutionEligibility | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "evaluation_date": self.evaluation_date,
            "action": self.action,
            "signal_score": self.signal_score,
            "confidence": self.confidence,
            "market_regime": self.market_regime,
            "risk_adjusted_score": self.risk_adjusted_score,
            "data_quality": self.data_quality,
            "model_version": self.model_version,
            "entry_price": self.entry_price,
            "score_components": self.score_components,
            "execution_eligibility": self.execution_eligibility.to_dict()
            if self.execution_eligibility
            else None,
        }


@dataclass
class ForwardOutcome:
    """Future evaluation outcomes after session T (> T)."""

    evaluation_date: str
    returns: dict[int, float | None]
    availability: dict[int, bool]
    strategy_returns: dict[int, float | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_date": self.evaluation_date,
            "returns": self.returns,
            "availability": self.availability,
            "strategy_returns": self.strategy_returns,
        }


@dataclass
class BacktestResult:
    """Single signal evaluation pair (Signal at T + Forward Outcome after T)."""

    signal: BacktestSignal
    outcome: ForwardOutcome

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal.to_dict(),
            "outcome": self.outcome.to_dict(),
        }


@dataclass
class WalkForwardResult:
    """Container for walk-forward evaluation run across a sequence of evaluation dates."""

    evaluation_dates: list[str]
    results: list[BacktestResult]
    aggregate: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_dates": self.evaluation_dates,
            "results": [r.to_dict() for r in self.results],
            "aggregate": self.aggregate,
        }


@dataclass
class RegimeObservation:
    """Individual market-regime validation observation at evaluation date T.

    Represents point-in-time market regime assignment at evaluation date T
    paired with future VNINDEX forward returns strictly after T.

    Disclaimers:
    - Observational/descriptive evaluation only.
    - Does NOT prove causality, statistical significance, or profitability.
    - Does NOT perform regime parameter or threshold tuning.
    """

    evaluation_date: str
    regime: str
    regime_score: float | None
    confidence: float
    horizon: int
    forward_return: float | None
    availability: bool
    regime_metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_date": self.evaluation_date,
            "regime": self.regime,
            "regime_score": self.regime_score,
            "confidence": self.confidence,
            "horizon": self.horizon,
            "forward_return": self.forward_return,
            "availability": self.availability,
            "regime_metrics": self.regime_metrics,
        }


@dataclass
class RegimeEvaluationResult:
    """Container for historical market-regime validation results across evaluation dates.

    Contains granular observations mapping each point-in-time regime assignment and horizon
    to future market return, plus descriptive aggregate statistics grouped by (regime, horizon).
    """

    observations: list[RegimeObservation]
    aggregate: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": [o.to_dict() for o in self.observations],
            "aggregate": self.aggregate,
        }


@dataclass
class ComponentObservation:
    """Individual signal component evaluation observation at evaluation date T.

    Represents the mapping: (symbol, evaluation_date, component, horizon) -> (component_score, forward_return).

    Notice:
    Component evaluation measures point-in-time signal attribution vs forward outcomes.
    It does not demonstrate causality, statistical significance, or portfolio performance.
    """

    evaluation_date: str
    symbol: str
    component: str
    component_score: float | None
    horizon: int
    forward_return: float | None
    score_bucket: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_date": self.evaluation_date,
            "symbol": self.symbol,
            "component": self.component,
            "component_score": self.component_score,
            "horizon": self.horizon,
            "forward_return": self.forward_return,
            "score_bucket": self.score_bucket,
        }


@dataclass
class ComponentEvaluationResult:
    """Container for signal component historical evaluation across a walk-forward dataset.

    Contains raw granular observations mapping each score component and horizon to future return,
    plus aggregated neutral performance metrics grouped by component, horizon, and score bucket.
    """

    observations: list[ComponentObservation]
    aggregate: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": [o.to_dict() for o in self.observations],
            "aggregate": self.aggregate,
        }


def validate_backtest_dataset(df: pd.DataFrame, dataset_name: str = "Dataset") -> dict:
    """Validate DataFrame against canonical OHLCV data-quality contracts for backtesting.

    Contract & Scope:
    - This function checks canonical OHLCV data quality (missing required columns, non-numeric values,
      invalid OHLC relationships, non-positive prices, negative volume).
    - Temporal-sensitive entry points (`get_as_of_dataset()` and `evaluate_forward_outcomes()`)
      are explicitly responsible for enforcing strict chronological ordering (`is_monotonic_increasing`)
      and unique dates before applying date or session indexing.

    Fail-Closed Semantics:
    Raises ValueError on malformed OHLCV data rather than silently swallowing errors.
    """
    if df is None or df.empty:
        raise ValueError(f"{dataset_name} cannot be empty or None.")

    val_res = validate_ohlcv_data(df, dataset_name)
    issues = val_res["issues"]

    critical_errors = [
        "missing_required_columns",
        "missing_date_column",
        "invalid_dates",
        "duplicate_dates",
        "non_numeric_values",
        "non_positive_prices",
        "negative_volume",
        "invalid_ohlc_relationship",
    ]

    found_critical = [iss for iss in issues if iss in critical_errors]
    if found_critical:
        raise ValueError(
            f"{dataset_name} validation failed due to critical data issues: {sorted(found_critical)}"
        )

    return val_res


def get_as_of_dataset(df: pd.DataFrame, evaluation_date: str | pd.Timestamp) -> pd.DataFrame:
    """Extract a strict non-mutating point-in-time dataset containing rows with timestamp <= evaluation_date.

    Temporal Contract & Fail-Closed Validation:
    1. Parse and format target evaluation_date T as YYYY-MM-DD string.
    2. Check if exact evaluation_date T exists in dataset price history.
    3. Verify that raw input dates up to T are parseable, unique, and strictly increasing in chronological order.
       Raises ValueError if a future row (date > T) or unsorted date is physically placed prior to T.
    4. Slices raw DataFrame strictly by date comparison (row_date <= T), NEVER by positional iloc!
       Future rows (> T) with invalid dates/prices never leak into or fail signal generation at T.
    5. Validates point-in-time OHLCV data <= T strictly via validate_backtest_dataset().
    """
    if df is None or df.empty:
        raise ValueError("Cannot slice empty or None DataFrame.")

    date_col = _find_date_column(df)
    if not date_col:
        raise ValueError("DataFrame missing required 'date' or 'time' column.")

    try:
        target_date_str = pd.to_datetime(evaluation_date).strftime("%Y-%m-%d")
    except (ValueError, TypeError) as err:
        raise ValueError(f"Invalid evaluation date format '{evaluation_date}': {err}") from err

    df_temp = df.copy()
    parsed_dates = pd.to_datetime(df_temp[date_col], errors="coerce")
    formatted_dates = [d.strftime("%Y-%m-%d") if pd.notna(d) else None for d in parsed_dates]
    df_temp["_date_str"] = formatted_dates

    # Check if target evaluation_date exists in dataset
    matches = df_temp[df_temp["_date_str"] == target_date_str]
    if matches.empty:
        raise ValueError(
            f"Evaluation date '{target_date_str}' not present in dataset price history."
        )

    target_idx = matches.index[0]

    # Verify if any unparseable invalid dates occur prior to or on evaluation date (<= target_idx)
    raw_dates_up_to_t = parsed_dates.iloc[: target_idx + 1]
    if raw_dates_up_to_t.isna().any():
        raise ValueError(
            f"DataFrame column '{date_col}' contains invalid unparseable date entries prior to or on evaluation date '{target_date_str}'."
        )

    # Check if any future observation (date > T) or unsorted/duplicate date is physically placed prior to target_idx
    date_strs_up_to_t = df_temp["_date_str"].iloc[: target_idx + 1]
    if (date_strs_up_to_t > target_date_str).any():
        raise ValueError(
            f"Point-in-time dataset input contains future observations (date > '{target_date_str}') physically placed before evaluation date."
        )

    if (
        not raw_dates_up_to_t.is_monotonic_increasing
        or (raw_dates_up_to_t.diff().dt.total_seconds() <= 0).iloc[1:].any()
    ):
        if raw_dates_up_to_t.duplicated().any():
            raise ValueError(
                f"Point-in-time dataset <= '{target_date_str}' contains duplicate dates."
            )
        raise ValueError(
            f"Point-in-time dataset <= '{target_date_str}' is unsorted or not strictly increasing in chronological order."
        )

    # Point-in-time filter strictly by date comparison (date <= T), NEVER by positional iloc!
    as_of_mask = (df_temp["_date_str"].notna()) & (df_temp["_date_str"] <= target_date_str)
    as_of_raw = df_temp[as_of_mask].drop(columns=["_date_str"]).copy()

    if as_of_raw.empty:
        raise ValueError(
            f"No historical data available on or before evaluation date '{target_date_str}'."
        )

    # Validate point-in-time OHLCV data <= T
    val_res = validate_backtest_dataset(as_of_raw, "Point-in-time Dataset")
    clean_df = val_res["clean_df"]

    if clean_df.empty:
        raise ValueError("Point-in-time dataset contains no valid clean OHLCV rows.")

    return clean_df.reset_index(drop=True)


def evaluate_execution_eligibility(
    df_stock: pd.DataFrame,
    evaluation_date: str | pd.Timestamp,
    config: ExecutionConfig | None = None,
) -> ExecutionEligibility:
    """Evaluate market-liquidity execution eligibility for a signal at evaluation date T.

    Point-In-Time Contract:
    - Slices raw stock dataset strictly <= evaluation_date via `get_as_of_dataset()`.
    - Calculates average liquidity metrics (average traded value in billion VND, average volume, close price)
      strictly over the historical lookback window (last N trading sessions <= T).
    - Future observations (> T) are strictly isolated and never influence liquidity evaluation at T.

    Execution Assumptions & Deterministic Checks:
    - min_avg_traded_value_bn: checks if average daily turnover (billion VND) >= min threshold.
    - min_avg_volume: checks if average daily volume (shares) >= min threshold.
    - min_price: checks if EOD close price (VND/share) >= min threshold.
    - max_participation_rate: if estimated order size (shares or VND value) is configured, checks if order size ratio <= max participation rate.

    Status Classifications:
    - EXECUTABLE ('executable'): satisfies all execution/liquidity assumptions.
    - NOT_EXECUTABLE ('not_executable'): fails one or more execution/liquidity assumptions.
    - INSUFFICIENT_LIQUIDITY_HISTORY ('insufficient_liquidity_history'): fewer than lookback_window historical sessions exist <= T.
    - INVALID_MARKET_DATA ('invalid_market_data'): point-in-time market data <= T is missing, empty, or malformed.

    Important Disclaimer:
    "Executable" in this framework strictly means that observable market liquidity timestamped <= T
    satisfies defined assumptions. It does NOT prove or guarantee that a real-world market order would be filled.
    Daily OHLCV data does not model bid/ask spread, order book queue, market impact, intraday volatility, trading halts,
    or broker execution behavior.
    """
    if config is None:
        config = ExecutionConfig()

    # Allow get_as_of_dataset() temporal fail-closed validation errors (ValueError) to propagate
    df_as_of = get_as_of_dataset(df_stock, evaluation_date)

    df_clean, val_res = get_clean_ohlcv_data(df_as_of)
    if (
        df_clean.empty
        or "missing_required_columns" in val_res["issues"]
        or "missing_date_column" in val_res["issues"]
    ):
        return ExecutionEligibility(
            status=STATUS_INVALID_MARKET_DATA,
            is_executable=False,
            reasons=[REASON_INVALID_OHLCV_DATA],
            metrics={},
        )

    available_history_sessions = len(df_clean)
    if available_history_sessions < config.lookback_window:
        return ExecutionEligibility(
            status=STATUS_INSUFFICIENT_LIQUIDITY_HISTORY,
            is_executable=False,
            reasons=[REASON_INSUFFICIENT_LOOKBACK_SESSIONS],
            metrics={
                "available_history_sessions": available_history_sessions,
                "available_lookback_sessions": available_history_sessions,
                "lookback_window": config.lookback_window,
            },
        )

    window_df = df_clean.tail(config.lookback_window)
    available_lookback_sessions = len(window_df)
    close_price = _safe_float(window_df["close"].iloc[-1])
    avg_volume = _safe_float(window_df["volume"].mean())

    trading_value_series = window_df["close"] * window_df["volume"]
    avg_traded_value_vnd = _safe_float(trading_value_series.mean())
    avg_traded_value_bn = (
        round(avg_traded_value_vnd / 1e9, 6) if avg_traded_value_vnd is not None else None
    )

    if close_price is not None:
        close_price = round(close_price, 2)
    if avg_volume is not None:
        avg_volume = round(avg_volume, 2)
    if avg_traded_value_vnd is not None:
        avg_traded_value_vnd = round(avg_traded_value_vnd, 2)

    # Estimate participation rate if order size or order value is specified
    estimated_participation_rate = None
    if config.estimated_order_size_shares is not None and avg_volume is not None and avg_volume > 0:
        estimated_participation_rate = round(config.estimated_order_size_shares / avg_volume, 6)
    elif (
        config.estimated_order_value_vnd is not None
        and avg_traded_value_vnd is not None
        and avg_traded_value_vnd > 0
    ):
        estimated_participation_rate = round(
            config.estimated_order_value_vnd / avg_traded_value_vnd, 6
        )

    reasons = []

    if (
        close_price is None
        or avg_volume is None
        or avg_traded_value_vnd is None
        or avg_traded_value_vnd <= 0
        or avg_volume <= 0
        or close_price <= 0
    ):
        reasons.append(REASON_ZERO_OR_NEGATIVE_LIQUIDITY)

    if config.min_avg_traded_value_bn is not None and (
        avg_traded_value_bn is None or avg_traded_value_bn < config.min_avg_traded_value_bn
    ):
        reasons.append(REASON_BELOW_MIN_TRADED_VALUE)

    if config.min_avg_volume is not None and (
        avg_volume is None or avg_volume < config.min_avg_volume
    ):
        reasons.append(REASON_BELOW_MIN_VOLUME)

    if config.min_price is not None and (close_price is None or close_price < config.min_price):
        reasons.append(REASON_BELOW_MIN_PRICE)

    if (
        config.max_participation_rate is not None
        and estimated_participation_rate is not None
        and estimated_participation_rate > config.max_participation_rate
    ):
        reasons.append(REASON_EXCEEDS_MAX_PARTICIPATION)

    metrics = {
        "close_price": close_price,
        "avg_volume": avg_volume,
        "avg_traded_value_vnd": avg_traded_value_vnd,
        "avg_traded_value_bn": avg_traded_value_bn,
        "estimated_participation_rate": estimated_participation_rate,
        "available_history_sessions": available_history_sessions,
        "available_lookback_sessions": available_lookback_sessions,
        "lookback_window": config.lookback_window,
    }

    if reasons:
        status = STATUS_NOT_EXECUTABLE
        is_executable = False
    else:
        status = STATUS_EXECUTABLE
        is_executable = True

    return ExecutionEligibility(
        status=status,
        is_executable=is_executable,
        reasons=sorted(set(reasons)),
        metrics=metrics,
    )


def calculate_as_of_market_breadth(
    universe_stock_map: dict[str, pd.DataFrame],
    evaluation_date: str,
) -> float:
    """Calculate point-in-time market breadth as-of evaluation date T (ratio of stocks with close > MA20).

    Strictly slices each universe stock dataset <= T before calculating MA20.
    Fails closed on empty universe or malformed universe stock datasets (propagates ValueError).
    """
    if not universe_stock_map:
        raise ValueError("Cannot calculate market breadth: universe_stock_map is empty or None.")

    valid_entries = {k: v for k, v in universe_stock_map.items() if v is not None and not v.empty}
    if not valid_entries:
        raise ValueError(
            "Cannot calculate market breadth: universe_stock_map contains no valid non-empty stock datasets."
        )

    bullish_count = 0
    valid_stocks_count = 0

    for sym, df_stock in valid_entries.items():
        # Extract point-in-time dataset. Fails closed if data <= T is malformed or unsorted.
        try:
            df_stock_as_of = get_as_of_dataset(df_stock, evaluation_date)
        except ValueError as err:
            # Expected when stock has no history prior to evaluation date
            if "No historical data available" in str(err) or "not present in dataset" in str(err):
                continue
            raise

        df_clean, val_res = get_clean_ohlcv_data(df_stock_as_of, sym)

        if val_res["status"] != "INSUFFICIENT" and len(df_clean) >= 20:
            c = _safe_float(df_clean["close"].iloc[-1])
            ma20 = _safe_float(df_clean["close"].tail(20).mean())
            if c is not None and ma20 is not None and ma20 > 0:
                valid_stocks_count += 1
                if c > ma20:
                    bullish_count += 1

    if valid_stocks_count == 0:
        raise ValueError(
            f"Cannot calculate market breadth as-of '{evaluation_date}': zero stocks in universe had sufficient historical data (>= 20 sessions) <= T."
        )

    return round(bullish_count / valid_stocks_count, 2)


def evaluate_forward_outcomes(
    df_stock: pd.DataFrame,
    evaluation_date: str,
    horizons: list[int] | None = None,
    action: str = "BUY",
) -> ForwardOutcome:
    """Evaluate forward returns and strategy returns for specified trading session horizons after T.

    Forward return formula at T + N trading sessions:
        forward_return_N = (Price[T + N] / Price[T]) - 1.0

    Temporal Contract & Fail-Closed Validation:
    - Requires dataset dates to be parseable, unique, and strictly increasing in chronological order.
    - Requires evaluation date T to exist uniquely in price history.
    - Position T + N corresponds strictly to the N-th valid trading session observation after T.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    if df_stock is None or df_stock.empty:
        raise ValueError("Cannot evaluate outcomes on empty or None DataFrame.")

    date_col_raw = _find_date_column(df_stock)
    if not date_col_raw or "close" not in df_stock.columns:
        raise ValueError("DataFrame missing required date or 'close' column.")

    try:
        target_date_str = pd.to_datetime(evaluation_date).strftime("%Y-%m-%d")
    except (ValueError, TypeError) as err:
        raise ValueError(f"Invalid evaluation date format '{evaluation_date}': {err}") from err

    # Parse and validate dates across entire outcome dataset strictly
    parsed_dates = pd.to_datetime(df_stock[date_col_raw], errors="coerce")
    if parsed_dates.isna().any():
        raise ValueError("Outcome dataset contains unparseable or invalid date entries.")

    if parsed_dates.duplicated().any():
        raise ValueError("Outcome dataset contains duplicate date entries.")

    if (
        not parsed_dates.is_monotonic_increasing
        or (parsed_dates.diff().dt.total_seconds() <= 0).iloc[1:].any()
    ):
        raise ValueError(
            "Outcome dataset dates are unsorted or not strictly increasing in chronological order."
        )

    # Validate OHLCV quality across dataset
    validate_backtest_dataset(df_stock, "Outcome Dataset")

    df_clean, _ = get_clean_ohlcv_data(df_stock, "SYMBOL")
    if df_clean.empty:
        raise ValueError("Stock DataFrame contains no valid OHLCV data.")

    clean_date_col = _find_date_column(df_clean)
    df_clean["_date_str"] = pd.to_datetime(df_clean[clean_date_col]).dt.strftime("%Y-%m-%d")

    matches = df_clean[df_clean["_date_str"] == target_date_str]

    if matches.empty:
        raise ValueError(f"Evaluation date '{target_date_str}' not present in stock price history.")

    idx_T = matches.index[0]
    price_T = _safe_float(df_clean.iloc[idx_T]["close"])

    if price_T is None or price_T <= 0:
        raise ValueError(f"Invalid price at evaluation date '{target_date_str}': {price_T}")

    returns: dict[int, float | None] = {}
    availability: dict[int, bool] = {}
    strategy_returns: dict[int, float | None] = {}

    total_sessions = len(df_clean)

    for h in horizons:
        if h <= 0:
            raise ValueError(f"Horizon must be a positive integer, got {h}")

        future_idx = idx_T + h
        if future_idx < total_sessions:
            row_future = df_clean.iloc[future_idx]
            date_future = row_future["_date_str"]
            price_future = _safe_float(row_future["close"])

            if (
                date_future is not None
                and not pd.isna(date_future)
                and price_future is not None
                and price_future > 0
            ):
                ret_val = round((price_future / price_T) - 1.0, 6)
                returns[h] = ret_val
                availability[h] = True

                if action == "BUY":
                    strategy_returns[h] = ret_val
                elif action == "SELL":
                    strategy_returns[h] = round(-ret_val, 6)
                else:
                    strategy_returns[h] = 0.0
            else:
                returns[h] = None
                availability[h] = False
                strategy_returns[h] = None
        else:
            returns[h] = None
            availability[h] = False
            strategy_returns[h] = None

    return ForwardOutcome(
        evaluation_date=target_date_str,
        returns=returns,
        availability=availability,
        strategy_returns=strategy_returns,
    )


def run_backtest_for_symbol(
    symbol: str,
    df_stock: pd.DataFrame,
    evaluation_dates: list[str],
    company_name: str = "",
    sector: str = "",
    exchange: str = "HOSE",
    df_vnindex: pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    breadth_ratio: float | None = None,
    universe_stock_map: dict[str, pd.DataFrame] | None = None,
    horizons: list[int] | None = None,
    execution_config: ExecutionConfig | None = None,
) -> list[BacktestResult]:
    """Run point-in-time deterministic backtest for a single symbol over multiple evaluation dates.

    Guarantees strict no-lookahead bias by slicing stock data and all market-level inputs
    (VNINDEX, VN30, and universe market breadth as-of T) strictly <= T before calling production engine.
    Fails closed on malformed market datasets.
    Optionally evaluates point-in-time execution/liquidity eligibility if execution_config is supplied.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    results: list[BacktestResult] = []

    for eval_date in evaluation_dates:
        target_date_str = pd.to_datetime(eval_date).strftime("%Y-%m-%d")

        # 1. Point-in-time stock data slicing (<= T)
        df_stock_as_of = get_as_of_dataset(df_stock, target_date_str)

        # 2. Point-in-time market data slicing (<= T) for production regime inputs
        df_vnindex_clean_as_of = None
        if df_vnindex is not None and not df_vnindex.empty:
            df_vnindex_as_of = get_as_of_dataset(df_vnindex, target_date_str)
            df_vnindex_clean_as_of, val_vn = get_clean_ohlcv_data(df_vnindex_as_of, "VNINDEX")
            if val_vn["status"] == "INSUFFICIENT":
                df_vnindex_clean_as_of = None

        df_vn30_clean_as_of = None
        if df_vn30 is not None and not df_vn30.empty:
            df_vn30_as_of = get_as_of_dataset(df_vn30, target_date_str)
            df_vn30_clean_as_of, val_30 = get_clean_ohlcv_data(df_vn30_as_of, "VN30")
            if val_30["status"] == "INSUFFICIENT":
                df_vn30_clean_as_of = None

        # Point-in-time market breadth as-of T
        effective_breadth = breadth_ratio
        if effective_breadth is None and universe_stock_map:
            effective_breadth = calculate_as_of_market_breadth(universe_stock_map, target_date_str)

        # 3. Market regime evaluation at T using production regime engine
        from scripts.lib.regime import detect_market_regime

        market_regime_info = detect_market_regime(
            df_vnindex=df_vnindex_clean_as_of,
            df_vn30=df_vn30_clean_as_of,
            breadth_ratio=effective_breadth,
        )

        # 4. Recommendation generation at T using production engine
        rec = generate_recommendation(
            symbol=symbol,
            company_name=company_name,
            sector=sector,
            exchange=exchange,
            df_stock=df_stock_as_of,
            market_regime_info=market_regime_info,
            df_vnindex=df_vnindex_clean_as_of,
            data_as_of=target_date_str,
        )

        raw_entry_price = rec["trade_plan"].get("current_price")
        entry_price = _safe_float(raw_entry_price)

        exec_eligibility = None
        if execution_config is not None:
            exec_eligibility = evaluate_execution_eligibility(
                df_stock=df_stock_as_of,
                evaluation_date=target_date_str,
                config=execution_config,
            )

        signal = BacktestSignal(
            symbol=symbol,
            evaluation_date=target_date_str,
            action=rec["action"],
            signal_score=rec["signal_score"],
            confidence=rec["confidence"],
            market_regime=market_regime_info["regime"],
            risk_adjusted_score=rec["risk_adjusted_score"],
            data_quality=rec["data_quality"],
            model_version=rec["model_version"],
            entry_price=entry_price,
            score_components=rec["score_components"],
            execution_eligibility=exec_eligibility,
        )

        # 5. Forward outcome evaluation (> T)
        outcome = evaluate_forward_outcomes(
            df_stock=df_stock,
            evaluation_date=target_date_str,
            horizons=horizons,
            action=rec["action"],
        )

        results.append(BacktestResult(signal=signal, outcome=outcome))

    return results


def run_backtest_for_universe(
    universe_stock_map: dict[str, pd.DataFrame],
    evaluation_dates: list[str],
    candidate_metadata: list[dict] | None = None,
    df_vnindex: pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    horizons: list[int] | None = None,
    execution_config: ExecutionConfig | None = None,
) -> list[BacktestResult]:
    """Run point-in-time deterministic backtest across an entire stock universe.

    Computes point-in-time market breadth as-of T across all stocks in universe_stock_map.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    meta_map = {}
    if candidate_metadata:
        for item in candidate_metadata:
            meta_map[item["symbol"]] = item

    all_results: list[BacktestResult] = []

    for sym, df_stock in universe_stock_map.items():
        item = meta_map.get(sym, {})
        comp = item.get("companyName", "")
        sec = item.get("sector", "")
        ex = item.get("exchange", "HOSE")

        res_sym = run_backtest_for_symbol(
            symbol=sym,
            df_stock=df_stock,
            evaluation_dates=evaluation_dates,
            company_name=comp,
            sector=sec,
            exchange=ex,
            df_vnindex=df_vnindex,
            df_vn30=df_vn30,
            universe_stock_map=universe_stock_map,
            horizons=horizons,
            execution_config=execution_config,
        )
        all_results.extend(res_sym)

    return all_results


def calculate_return_stats(return_series: list[float]) -> dict[str, float | None]:
    """Calculate descriptive summary statistics for a list of return values."""
    if not return_series:
        return {
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
        }

    arr = np.array(return_series, dtype=float)
    return {
        "mean": round(float(np.mean(arr)), 6),
        "median": round(float(np.median(arr)), 6),
        "min": round(float(np.min(arr)), 6),
        "max": round(float(np.max(arr)), 6),
    }


def aggregate_backtest_results(
    results: list[BacktestResult], horizons: list[int] | None = None
) -> dict[str, Any]:
    """Aggregate backtest signal results into summary statistics, forward returns, and directional hit rates.

    Metrics provided:
    - Signal Statistics: total signals, action counts, valid outcome count per horizon.
    - Forward Return Statistics (for each horizon): mean, median, min, max.
    - Directional Metrics:
      - BUY hit rate: ratio of BUY signals where forward return > 0
      - SELL hit rate: ratio of SELL signals where forward return < 0
      - Combined directional hit rate: ratio of directional (BUY/SELL) signals with positive direction outcome
    - Strategy Returns:
      - mean: average directional strategy return
      - median: median directional strategy return
      - sum_strategy_return: arithmetic sum of individual signal strategy returns (diagnostic metric only)
    - Breakdown by action and market regime.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    total_signals = len(results)
    action_counts: dict[str, int] = {
        "BUY": 0,
        "HOLD": 0,
        "SELL": 0,
        "WATCH": 0,
        "AVOID": 0,
    }

    for res in results:
        act = res.signal.action
        action_counts[act] = action_counts.get(act, 0) + 1

    valid_outcome_counts: dict[int, int] = {h: 0 for h in horizons}
    horizon_metrics: dict[int, dict[str, Any]] = {}

    for h in horizons:
        fwd_returns: list[float] = []
        strat_returns: list[float] = []

        buy_hits = 0
        buy_total = 0

        sell_hits = 0
        sell_total = 0

        for res in results:
            if res.outcome.availability.get(h, False):
                fwd_ret = res.outcome.returns.get(h)
                strat_ret = res.outcome.strategy_returns.get(h)

                if fwd_ret is not None:
                    valid_outcome_counts[h] += 1
                    fwd_returns.append(fwd_ret)

                    if strat_ret is not None:
                        strat_returns.append(strat_ret)

                    if res.signal.action == "BUY":
                        buy_total += 1
                        if fwd_ret > 0:
                            buy_hits += 1
                    elif res.signal.action == "SELL":
                        sell_total += 1
                        if fwd_ret < 0:
                            sell_hits += 1

        fwd_stats = calculate_return_stats(fwd_returns)
        strat_stats = calculate_return_stats(strat_returns)

        buy_hit_rate = round(buy_hits / buy_total, 4) if buy_total > 0 else None
        sell_hit_rate = round(sell_hits / sell_total, 4) if sell_total > 0 else None

        combined_total = buy_total + sell_total
        combined_hits = buy_hits + sell_hits
        combined_hit_rate = round(combined_hits / combined_total, 4) if combined_total > 0 else None

        sum_strat_return = round(float(sum(strat_returns)), 6) if strat_returns else 0.0

        horizon_metrics[h] = {
            "valid_signals": valid_outcome_counts[h],
            "forward_return": fwd_stats,
            "strategy_return": {
                "mean": strat_stats["mean"],
                "median": strat_stats["median"],
                "sum_strategy_return": sum_strat_return,
            },
            "buy_hit_rate": buy_hit_rate,
            "buy_signals_count": buy_total,
            "sell_hit_rate": sell_hit_rate,
            "sell_signals_count": sell_total,
            "combined_directional_hit_rate": combined_hit_rate,
        }

    # Breakdown by action
    actions = sorted({res.signal.action for res in results})
    breakdown_by_action: dict[str, dict[int, dict[str, Any]]] = {}

    for act in actions:
        breakdown_by_action[act] = {}
        sub_results = [r for r in results if r.signal.action == act]

        for h in horizons:
            sub_rets = [
                r.outcome.returns[h]
                for r in sub_results
                if r.outcome.availability.get(h) and r.outcome.returns.get(h) is not None
            ]
            breakdown_by_action[act][h] = {
                "count": len(sub_rets),
                "stats": calculate_return_stats(sub_rets),
            }

    # Breakdown by market regime
    regimes = sorted({res.signal.market_regime for res in results})
    breakdown_by_regime: dict[str, dict[int, dict[str, Any]]] = {}

    for reg in regimes:
        breakdown_by_regime[reg] = {}
        sub_results = [r for r in results if r.signal.market_regime == reg]

        for h in horizons:
            sub_rets = [
                r.outcome.returns[h]
                for r in sub_results
                if r.outcome.availability.get(h) and r.outcome.returns.get(h) is not None
            ]
            breakdown_by_regime[reg][h] = {
                "count": len(sub_rets),
                "stats": calculate_return_stats(sub_rets),
            }

    # Aggregate execution summary if execution eligibility is populated across signals
    execution_evaluated_points = sum(
        1 for res in results if res.signal.execution_eligibility is not None
    )
    execution_summary: dict[str, Any] | None = None

    if execution_evaluated_points > 0:
        total_eval_points = len(results)
        exec_count = sum(
            1
            for res in results
            if res.signal.execution_eligibility and res.signal.execution_eligibility.is_executable
        )
        non_exec_count = sum(
            1
            for res in results
            if res.signal.execution_eligibility
            and res.signal.execution_eligibility.status == STATUS_NOT_EXECUTABLE
        )
        insufficient_hist_count = sum(
            1
            for res in results
            if res.signal.execution_eligibility
            and res.signal.execution_eligibility.status == STATUS_INSUFFICIENT_LIQUIDITY_HISTORY
        )
        invalid_data_count = sum(
            1
            for res in results
            if res.signal.execution_eligibility
            and res.signal.execution_eligibility.status == STATUS_INVALID_MARKET_DATA
        )

        exec_ratio = (
            round(exec_count / execution_evaluated_points, 4)
            if execution_evaluated_points > 0
            else None
        )

        traded_value_bn_list = [
            _safe_float(res.signal.execution_eligibility.metrics.get("avg_traded_value_bn"))
            for res in results
            if res.signal.execution_eligibility
            and res.signal.execution_eligibility.metrics.get("avg_traded_value_bn") is not None
        ]
        traded_value_bn_valid = [v for v in traded_value_bn_list if v is not None]

        volume_list = [
            _safe_float(res.signal.execution_eligibility.metrics.get("avg_volume"))
            for res in results
            if res.signal.execution_eligibility
            and res.signal.execution_eligibility.metrics.get("avg_volume") is not None
        ]
        volume_valid = [v for v in volume_list if v is not None]

        execution_summary = {
            "total_evaluation_points": total_eval_points,
            "execution_evaluated_points": execution_evaluated_points,
            "executable_count": exec_count,
            "non_executable_count": non_exec_count,
            "insufficient_history_count": insufficient_hist_count,
            "invalid_data_count": invalid_data_count,
            "executable_ratio": exec_ratio,
            "liquidity_summary": {
                "avg_traded_value_bn": calculate_return_stats(traded_value_bn_valid),
                "avg_volume": calculate_return_stats(volume_valid),
            },
        }

    return {
        "signal_statistics": {
            "total_signals": total_signals,
            "action_counts": action_counts,
            "valid_outcome_counts": valid_outcome_counts,
        },
        "horizon_metrics": horizon_metrics,
        "breakdown_by_action": breakdown_by_action,
        "breakdown_by_regime": breakdown_by_regime,
        "execution_summary": execution_summary,
    }


def generate_walk_forward_dates(
    df: pd.DataFrame,
    min_history: int = 50,
    step: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[str]:
    """Deterministically generate chronological evaluation dates from historical trading session data.

    Evaluation dates are selected strictly from valid, existing trading sessions in the input DataFrame:
    1. First eligible evaluation date index is `min_history - 1` (0-indexed), ensuring at least `min_history`
       trading sessions exist <= T.
    2. Subsequent evaluation dates step forward by `step` valid trading sessions.
    3. Optional `start_date` and `end_date` filter the eligible candidate dates (inclusive).

    Fail-Closed Validation:
    - Input DataFrame dates are validated for parseability, duplicates, and strictly increasing chronological order.
    - If `min_history` < 1 or `step` < 1, raises ValueError.
    - If no trading sessions satisfy the criteria, raises ValueError.
    """
    if df is None or df.empty:
        raise ValueError("Cannot generate walk-forward dates from empty or None DataFrame.")

    if min_history < 1:
        raise ValueError(f"min_history must be a positive integer >= 1, got {min_history}")

    if step < 1:
        raise ValueError(f"step must be a positive integer >= 1, got {step}")

    date_col = _find_date_column(df)
    if not date_col:
        raise ValueError("DataFrame missing required date or time column.")

    parsed_dates = pd.to_datetime(df[date_col], errors="coerce")
    if parsed_dates.isna().any():
        raise ValueError("Dataset contains invalid or unparseable date entries.")

    if parsed_dates.duplicated().any():
        raise ValueError("Dataset contains duplicate date entries.")

    if (
        not parsed_dates.is_monotonic_increasing
        or (parsed_dates.diff().dt.total_seconds() <= 0).iloc[1:].any()
    ):
        raise ValueError(
            "Dataset dates are unsorted or not strictly increasing in chronological order."
        )

    date_strs = parsed_dates.dt.strftime("%Y-%m-%d").tolist()
    total_rows = len(date_strs)

    if total_rows < min_history:
        raise ValueError(
            f"Dataset contains insufficient history ({total_rows} sessions) for min_history requirement ({min_history})."
        )

    # Step through trading sessions chronologically starting at index (min_history - 1)
    candidate_dates = [date_strs[idx] for idx in range(min_history - 1, total_rows, step)]

    # Filter by start_date and end_date if supplied
    if start_date is not None:
        try:
            start_str = pd.to_datetime(start_date).strftime("%Y-%m-%d")
            candidate_dates = [d for d in candidate_dates if d >= start_str]
        except (ValueError, TypeError) as err:
            raise ValueError(f"Invalid start_date format '{start_date}': {err}") from err

    if end_date is not None:
        try:
            end_str = pd.to_datetime(end_date).strftime("%Y-%m-%d")
            candidate_dates = [d for d in candidate_dates if d <= end_str]
        except (ValueError, TypeError) as err:
            raise ValueError(f"Invalid end_date format '{end_date}': {err}") from err

    if not candidate_dates:
        raise ValueError("No eligible walk-forward evaluation dates matched criteria.")

    return candidate_dates


def run_walk_forward_backtest(
    evaluation_dates: list[str] | None = None,
    df_stock: pd.DataFrame | None = None,
    symbol: str = "",
    universe_stock_map: dict[str, pd.DataFrame] | None = None,
    candidate_metadata: list[dict] | None = None,
    df_vnindex: pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    company_name: str = "",
    sector: str = "",
    exchange: str = "HOSE",
    horizons: list[int] | None = None,
    min_history: int = 50,
    step: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
    execution_config: ExecutionConfig | None = None,
) -> WalkForwardResult:
    """Run deterministic, no-lookahead walk-forward evaluation over a sequence of historical evaluation dates.

    Walk-Forward Principle:
    Walk-forward validation is an evaluation framework measuring historical signal quality across
    sequential evaluation dates T1, T2, ..., Tn.
    At each evaluation date T:
    - Input information supplied to the signal engine strictly satisfies: timestamp <= T.
    - Forward historical outcomes are evaluated strictly using data timestamped > T.
    - No future information (> T) is permitted in signal, confidence, action, or regime calculation.
    - Market inputs (VNINDEX, VN30, and point-in-time universe breadth) are strictly bounded <= T.
    - Strategy returns (`sum_strategy_return`) retain diagnostic semantics (sum of individual signal outcomes)
      and do NOT simulate portfolio allocation, leverage, cash management, position sizing, or transaction costs.

    API Behavior:
    - Evaluation dates may be explicitly provided (`evaluation_dates`) or deterministically generated
      from dataset history via `generate_walk_forward_dates()`.
    - `start_date` and `end_date` filter auto-generated evaluation dates. Explicit `evaluation_dates` are a caller-specified
      list and are not filtered by `start_date`/`end_date`.
    - Supports single-stock evaluation (`df_stock` and `symbol`) or universe-wide evaluation (`universe_stock_map`).
    - Explicit `evaluation_dates` must be chronologically ordered, unique, and valid dates existing in the dataset.
    - `min_history` is strictly enforced per stock participating in the evaluation for both generated evaluation dates
      and explicitly provided evaluation dates. Each evaluation date T must have at least `min_history` valid historical
      sessions <= T for every stock in the universe.

    Fail-Closed Validation:
    - Unsorted, duplicate, or invalid evaluation dates raise explicit ValueError exceptions.
    - Evaluation dates with fewer than `min_history` historical sessions <= T for any stock in the evaluation raise explicit ValueError.
    - Fails closed if required datasets are missing or invalid.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    if min_history < 1:
        raise ValueError(f"min_history must be a positive integer >= 1, got {min_history}")

    # Determine reference dataset and stock entries to validate
    stocks_to_validate: list[tuple[str, pd.DataFrame]] = []

    if universe_stock_map is not None:
        if not universe_stock_map:
            raise ValueError(
                "Cannot run universe walk-forward evaluation: universe_stock_map is empty."
            )
        for sym, df_s in universe_stock_map.items():
            if df_s is None:
                raise ValueError(
                    f"Stock '{sym}' cannot participate in walk-forward evaluation: dataset is None."
                )
            if df_s.empty:
                raise ValueError(
                    f"Stock '{sym}' cannot participate in walk-forward evaluation: dataset is empty."
                )
            stocks_to_validate.append((sym, df_s))
        ref_df = stocks_to_validate[0][1]
    elif df_stock is not None and not df_stock.empty and symbol:
        stocks_to_validate = [(symbol, df_stock)]
        ref_df = df_stock
    else:
        raise ValueError(
            "Must provide either 'universe_stock_map' or both 'symbol' and 'df_stock' for walk-forward evaluation."
        )

    # Determine evaluation_dates
    if evaluation_dates is None:
        eval_dates = generate_walk_forward_dates(
            df=ref_df,
            min_history=min_history,
            step=step,
            start_date=start_date,
            end_date=end_date,
        )
    else:
        if not evaluation_dates:
            raise ValueError("evaluation_dates list cannot be empty.")

        # Validate format and chronological order of provided evaluation_dates
        eval_dates = []
        for d in evaluation_dates:
            try:
                eval_dates.append(pd.to_datetime(d).strftime("%Y-%m-%d"))
            except (ValueError, TypeError) as err:
                raise ValueError(
                    f"Invalid evaluation date format in evaluation_dates '{d}': {err}"
                ) from err

        # Check uniqueness and chronological order
        if len(eval_dates) != len(set(eval_dates)):
            raise ValueError("Provided evaluation_dates list contains duplicate entries.")

        if sorted(eval_dates) != eval_dates:
            raise ValueError("Provided evaluation_dates list is not sorted in chronological order.")

    # Fail-closed point-in-time and min_history validation for EVERY evaluation date across ALL stocks
    for target_d in eval_dates:
        for sym, df_s in stocks_to_validate:
            try:
                df_pit = get_as_of_dataset(df_s, target_d)
            except ValueError as err:
                raise ValueError(
                    f"Stock '{sym}' on evaluation date '{target_d}' failed point-in-time validation: {err}"
                ) from err

            avail_sessions = len(df_pit)
            if avail_sessions < min_history:
                raise ValueError(
                    f"Stock '{sym}' on evaluation date '{target_d}' has insufficient history "
                    f"({avail_sessions} sessions) for min_history requirement ({min_history})."
                )

    # Execute backtest across dates
    if universe_stock_map:
        results = run_backtest_for_universe(
            universe_stock_map=universe_stock_map,
            evaluation_dates=eval_dates,
            candidate_metadata=candidate_metadata,
            df_vnindex=df_vnindex,
            df_vn30=df_vn30,
            horizons=horizons,
            execution_config=execution_config,
        )
    elif df_stock is not None and not df_stock.empty and symbol:
        results = run_backtest_for_symbol(
            symbol=symbol,
            df_stock=df_stock,
            evaluation_dates=eval_dates,
            company_name=company_name,
            sector=sector,
            exchange=exchange,
            df_vnindex=df_vnindex,
            df_vn30=df_vn30,
            horizons=horizons,
            execution_config=execution_config,
        )
    else:
        raise ValueError(
            "Must provide either 'universe_stock_map' or both 'symbol' and 'df_stock' for walk-forward evaluation."
        )

    # Compute aggregate summary statistics across all evaluation points
    aggregate_summary = aggregate_backtest_results(results, horizons=horizons)

    return WalkForwardResult(
        evaluation_dates=eval_dates,
        results=results,
        aggregate=aggregate_summary,
    )


def classify_component_score_bucket(score: float | None) -> str | None:
    """Classify a component score (0-100) into neutral directional observation buckets.

    Buckets:
    - 'negative' : score < 45.0
    - 'neutral'  : 45.0 <= score <= 55.0
    - 'positive' : score > 55.0

    Note:
    Bucket boundaries reflect neutral observation ranges without threshold optimization or curve-fitting.
    Returns None if score is None.
    """
    s = _safe_float(score)
    if s is None:
        return None
    if s < 45.0:
        return "negative"
    if s <= 55.0:
        return "neutral"
    return "positive"


def aggregate_regime_evaluation_results(
    observations: list[RegimeObservation],
    horizons: list[int] | None = None,
) -> dict[str, Any]:
    """Aggregate market-regime validation observations into descriptive metrics per (regime, horizon).

    Notice & Disclaimers:
    - Observational/descriptive evaluation layer only.
    - Does NOT establish causality, statistical significance (no p-values/hypothesis tests),
      model optimization, or portfolio returns.
    - Aggregation denominators strictly distinguish total regime observations vs observations with available forward outcomes.
    - Missing/unavailable forward returns remain None and are NOT filled or treated as zero.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    regimes = sorted({o.regime for o in observations}) if observations else []
    by_regime: dict[str, dict[int, dict[str, Any]]] = {}

    for reg in regimes:
        by_regime[reg] = {}
        for h in horizons:
            reg_h_obs = [o for o in observations if o.regime == reg and o.horizon == h]
            total_obs_count = len(reg_h_obs)

            avail_obs = [o for o in reg_h_obs if o.availability and o.forward_return is not None]
            avail_count = len(avail_obs)
            unavail_count = total_obs_count - avail_count

            valid_rets = [o.forward_return for o in avail_obs if o.forward_return is not None]
            stats = calculate_return_stats(valid_rets)

            positive_return_rate = None
            if valid_rets:
                pos_count = sum(1 for r in valid_rets if r > 0)
                positive_return_rate = round(pos_count / len(valid_rets), 4)

            std_dev = None
            if len(valid_rets) > 1:
                std_dev = round(float(np.std(valid_rets, ddof=1)), 6)
            elif len(valid_rets) == 1:
                std_dev = 0.0

            by_regime[reg][h] = {
                "observation_count": total_obs_count,
                "available_forward_outcome_count": avail_count,
                "unavailable_forward_outcome_count": unavail_count,
                "mean": stats["mean"],
                "median": stats["median"],
                "std": std_dev,
                "min": stats["min"],
                "max": stats["max"],
                "positive_return_rate": positive_return_rate,
            }

    return {
        "by_regime": by_regime,
        "total_observations": len(observations),
    }


def evaluate_market_regimes(
    df_vnindex: pd.DataFrame,
    evaluation_dates: list[str] | None = None,
    df_vn30: pd.DataFrame | None = None,
    universe_stock_map: dict[str, pd.DataFrame] | None = None,
    breadth_ratio: float | None = None,
    horizons: list[int] | None = None,
    min_history: int = 20,
    step: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
) -> RegimeEvaluationResult:
    """Evaluate historical forward outcomes associated with production market regimes assigned at evaluation dates T.

    Evaluation Framework & Point-In-Time Contract:
    1. For every evaluation date T:
       - Prepare VNINDEX data strictly <= T using `get_as_of_dataset()`.
       - Prepare VN30 data strictly <= T using `get_as_of_dataset()` if df_vn30 provided.
       - Calculate market breadth strictly as-of T using `calculate_as_of_market_breadth()` or explicit `breadth_ratio`.
       - Call production `detect_market_regime()` using only point-in-time information available at T.
       - Record observation: evaluation_date, regime, regime_score, confidence, metrics, horizon, forward_return, availability.
       - Evaluate future VNINDEX forward outcomes strictly after T using `evaluate_forward_outcomes()`.
    2. Aggregate descriptive statistics grouped by (regime, horizon).

    Disclaimers:
    - Purely descriptive historical validation layer.
    - Does NOT establish causality, statistical significance, or profitability.
    - Does NOT modify or tune production market regime formulas or thresholds.
    - Future outcomes strictly after T never influence regime assignment at T.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    if df_vnindex is None or df_vnindex.empty:
        raise ValueError("Cannot evaluate market regimes: df_vnindex is empty or None.")

    # Determine evaluation_dates
    if evaluation_dates is None:
        eval_dates = generate_walk_forward_dates(
            df=df_vnindex,
            min_history=min_history,
            step=step,
            start_date=start_date,
            end_date=end_date,
        )
    else:
        if not evaluation_dates:
            raise ValueError("evaluation_dates list cannot be empty.")

        eval_dates = []
        for d in evaluation_dates:
            eval_dates.append(_parse_canonical_date(d))

        if len(eval_dates) != len(set(eval_dates)):
            raise ValueError("Provided evaluation_dates list contains duplicate entries.")

        if sorted(eval_dates) != eval_dates:
            raise ValueError("Provided evaluation_dates list is not sorted in chronological order.")

    observations: list[RegimeObservation] = []

    for target_d in eval_dates:
        # 1. Point-in-time VNINDEX data slicing (<= T)
        df_vn_as_of = get_as_of_dataset(df_vnindex, target_d)
        df_vnindex_clean_as_of, val_vn = get_clean_ohlcv_data(df_vn_as_of, "VNINDEX")
        if val_vn["status"] == "INSUFFICIENT":
            df_vnindex_clean_as_of = None

        # 2. Point-in-time VN30 data slicing (<= T)
        df_vn30_clean_as_of = None
        if df_vn30 is not None:
            if df_vn30.empty:
                raise ValueError("Supplied df_vn30 DataFrame is empty.")
            df_vn30_as_of = get_as_of_dataset(df_vn30, target_d)
            df_vn30_clean_as_of, val_30 = get_clean_ohlcv_data(df_vn30_as_of, "VN30")
            if val_30["status"] == "INSUFFICIENT":
                df_vn30_clean_as_of = None

        # 3. Market breadth as-of T
        effective_breadth = breadth_ratio
        if effective_breadth is None and universe_stock_map:
            effective_breadth = calculate_as_of_market_breadth(universe_stock_map, target_d)

        # 4. Production regime detection at T
        from scripts.lib.regime import detect_market_regime

        regime_info = detect_market_regime(
            df_vnindex=df_vnindex_clean_as_of,
            df_vn30=df_vn30_clean_as_of,
            breadth_ratio=effective_breadth,
        )

        # 5. Future VNINDEX outcomes (> T)
        outcome = evaluate_forward_outcomes(
            df_stock=df_vnindex,
            evaluation_date=target_d,
            horizons=horizons,
            action="BUY",
        )

        # 6. Granular observations
        for h in horizons:
            fwd_ret = outcome.returns.get(h)
            is_avail = outcome.availability.get(h, False)

            obs = RegimeObservation(
                evaluation_date=target_d,
                regime=regime_info["regime"],
                regime_score=regime_info["regime_score"],
                confidence=regime_info["confidence"],
                horizon=h,
                forward_return=fwd_ret,
                availability=is_avail,
                regime_metrics=regime_info.get("metrics", {}),
            )
            observations.append(obs)

    agg_summary = aggregate_regime_evaluation_results(
        observations=observations,
        horizons=horizons,
    )

    return RegimeEvaluationResult(
        observations=observations,
        aggregate=agg_summary,
    )


@dataclass
class ConfidenceObservation:
    """Individual production recommendation confidence observation at evaluation date T.

    Represents the point-in-time recommendation output (action, confidence, signal_score, market_regime)
    at evaluation date T paired with forward returns across evaluation horizons (> T).

    Disclaimers:
    - Confidence is documented as a deterministic heuristic model-confidence score, NOT a calibrated probability.
    - A confidence value of 0.80 must NOT automatically be interpreted as an 80% probability of positive return.
    - Historical calibration measures empirical alignment between confidence and observed forward outcomes.
    - Does NOT establish causality or profitability.
    """

    evaluation_date: str
    symbol: str
    action: str
    confidence: float
    signal_score: float | None
    market_regime: str | None
    confidence_bucket: str = ""
    forward_returns: dict[int, float | None] = field(default_factory=dict)
    availability: dict[int, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        expected_bucket = classify_confidence_bucket(self.confidence)
        if self.confidence_bucket and self.confidence_bucket != expected_bucket:
            raise ValueError(
                f"Mismatched confidence_bucket '{self.confidence_bucket}' for confidence {self.confidence}. Expected '{expected_bucket}'."
            )
        self.confidence_bucket = expected_bucket

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_date": self.evaluation_date,
            "symbol": self.symbol,
            "action": self.action,
            "confidence": self.confidence,
            "signal_score": self.signal_score,
            "market_regime": self.market_regime,
            "confidence_bucket": self.confidence_bucket,
            "forward_returns": self.forward_returns,
            "availability": self.availability,
        }


@dataclass
class ConfidenceCalibrationResult:
    """Container for historical confidence calibration evaluation results.

    Contains raw granular observations mapping each recommendation to future forward returns,
    plus descriptive aggregate metrics grouped by confidence bucket, horizon, and action.
    """

    observations: list[ConfidenceObservation]
    aggregate: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": [o.to_dict() for o in self.observations],
            "aggregate": self.aggregate,
        }


def classify_confidence_bucket(confidence: Any) -> str:
    """Classify a production confidence value (0.0 to 1.0) into a canonical confidence bucket.

    Canonical Buckets:
    - '[0.0, 0.1)'
    - '[0.1, 0.2)'
    - '[0.2, 0.3)'
    - '[0.3, 0.4)'
    - '[0.4, 0.5)'
    - '[0.5, 0.6)'
    - '[0.6, 0.7)'
    - '[0.7, 0.8)'
    - '[0.8, 0.9)'
    - '[0.9, 1.0]'

    Fail-Closed Validation:
    - Rejects None, booleans, non-numeric types, NaN, Inf, and values strictly outside [0.0, 1.0].
    - Raises ValueError on invalid inputs.
    """
    if confidence is None or isinstance(confidence, bool):
        raise ValueError(f"Invalid confidence value: {confidence}")

    if not isinstance(confidence, (int, float)):
        raise TypeError(
            f"Confidence must be numeric, got {type(confidence).__name__}: {confidence}"
        )

    conf = float(confidence)
    if math.isnan(conf) or math.isinf(conf):
        raise ValueError(f"Confidence value cannot be NaN or Inf, got {confidence}")

    if conf < 0.0 or conf > 1.0:
        raise ValueError(f"Confidence value must be within [0.0, 1.0], got {confidence}")

    if conf < 0.1:
        return "[0.0, 0.1)"
    if conf < 0.2:
        return "[0.1, 0.2)"
    if conf < 0.3:
        return "[0.2, 0.3)"
    if conf < 0.4:
        return "[0.3, 0.4)"
    if conf < 0.5:
        return "[0.4, 0.5)"
    if conf < 0.6:
        return "[0.5, 0.6)"
    if conf < 0.7:
        return "[0.6, 0.7)"
    if conf < 0.8:
        return "[0.7, 0.8)"
    if conf < 0.9:
        return "[0.8, 0.9)"
    return "[0.9, 1.0]"


def aggregate_confidence_calibration_results(
    observations: list[ConfidenceObservation],
    horizons: list[int] | None = None,
) -> dict[str, Any]:
    """Aggregate confidence calibration observations into descriptive metrics.

    Metrics calculated per confidence bucket and horizon:
    - observation_count: total observations in this confidence bucket.
    - available_outcome_count: count of observations with available forward return for horizon.
    - unavailable_outcome_count: count of observations with missing/unavailable forward return.
    - mean_forward_return: arithmetic mean forward return among available outcomes (or None).
    - median_forward_return: median forward return among available outcomes (or None).
    - positive_return_rate: proportion of available outcomes with forward return > 0 (or None).
    - mean_confidence: mean predicted confidence for available outcomes (or None).
    - calibration_gap: positive_return_rate - mean_confidence (or None).

    Disclaimers & Notes:
    - Binary success definition is strictly: forward_return > 0.
    - Missing/unavailable outcomes are NOT filled with zero or treated as negative outcomes.
    - Provides descriptive action-level breakdown as a separate grouping without altering primary success definition.
    - Confidence is a heuristic model-confidence score, NOT a calibrated probability.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    total_obs_count = len(observations)

    # Bucket metrics
    by_bucket: dict[str, dict[int, dict[str, Any]]] = {}

    for b_name in DEFAULT_CONFIDENCE_BUCKETS:
        by_bucket[b_name] = {}
        b_obs = [o for o in observations if o.confidence_bucket == b_name]
        b_total_count = len(b_obs)

        for h in horizons:
            avail_obs = [
                o
                for o in b_obs
                if o.availability.get(h, False) and o.forward_returns.get(h) is not None
            ]
            avail_count = len(avail_obs)
            unavail_count = b_total_count - avail_count

            if avail_count > 0:
                rets = [o.forward_returns[h] for o in avail_obs if o.forward_returns[h] is not None]
                confs = [o.confidence for o in avail_obs]

                mean_ret = round(float(np.mean(rets)), 6)
                med_ret = round(float(np.median(rets)), 6)

                pos_hits = sum(1 for r in rets if r > 0)
                pos_rate = round(pos_hits / avail_count, 4)

                mean_conf = round(float(np.mean(confs)), 6)
                calib_gap = round(pos_rate - mean_conf, 6)
            else:
                mean_ret = None
                med_ret = None
                pos_rate = None
                mean_conf = None
                calib_gap = None

            by_bucket[b_name][h] = {
                "observation_count": b_total_count,
                "available_outcome_count": avail_count,
                "unavailable_outcome_count": unavail_count,
                "mean_forward_return": mean_ret,
                "median_forward_return": med_ret,
                "positive_return_rate": pos_rate,
                "mean_confidence": mean_conf,
                "calibration_gap": calib_gap,
            }

    # Action breakdown
    actions = sorted({o.action for o in observations}) if observations else []
    by_action: dict[str, dict[str, dict[int, dict[str, Any]]]] = {}

    for act in actions:
        by_action[act] = {}
        act_obs = [o for o in observations if o.action == act]

        for b_name in DEFAULT_CONFIDENCE_BUCKETS:
            by_action[act][b_name] = {}
            act_b_obs = [o for o in act_obs if o.confidence_bucket == b_name]
            act_b_total = len(act_b_obs)

            for h in horizons:
                avail_obs = [
                    o
                    for o in act_b_obs
                    if o.availability.get(h, False) and o.forward_returns.get(h) is not None
                ]
                avail_count = len(avail_obs)
                unavail_count = act_b_total - avail_count

                if avail_count > 0:
                    rets = [
                        o.forward_returns[h] for o in avail_obs if o.forward_returns[h] is not None
                    ]
                    confs = [o.confidence for o in avail_obs]

                    mean_ret = round(float(np.mean(rets)), 6)
                    med_ret = round(float(np.median(rets)), 6)

                    pos_hits = sum(1 for r in rets if r > 0)
                    pos_rate = round(pos_hits / avail_count, 4)

                    mean_conf = round(float(np.mean(confs)), 6)
                    calib_gap = round(pos_rate - mean_conf, 6)
                else:
                    mean_ret = None
                    med_ret = None
                    pos_rate = None
                    mean_conf = None
                    calib_gap = None

                by_action[act][b_name][h] = {
                    "observation_count": act_b_total,
                    "available_outcome_count": avail_count,
                    "unavailable_outcome_count": unavail_count,
                    "mean_forward_return": mean_ret,
                    "median_forward_return": med_ret,
                    "positive_return_rate": pos_rate,
                    "mean_confidence": mean_conf,
                    "calibration_gap": calib_gap,
                }

    # Overall summary metrics across all buckets
    overall: dict[int, dict[str, Any]] = {}
    for h in horizons:
        avail_obs = [
            o
            for o in observations
            if o.availability.get(h, False) and o.forward_returns.get(h) is not None
        ]
        avail_count = len(avail_obs)
        unavail_count = total_obs_count - avail_count

        if avail_count > 0:
            rets = [o.forward_returns[h] for o in avail_obs if o.forward_returns[h] is not None]
            confs = [o.confidence for o in avail_obs]

            mean_ret = round(float(np.mean(rets)), 6)
            med_ret = round(float(np.median(rets)), 6)

            pos_hits = sum(1 for r in rets if r > 0)
            pos_rate = round(pos_hits / avail_count, 4)

            mean_conf = round(float(np.mean(confs)), 6)
            calib_gap = round(pos_rate - mean_conf, 6)
        else:
            mean_ret = None
            med_ret = None
            pos_rate = None
            mean_conf = None
            calib_gap = None

        overall[h] = {
            "observation_count": total_obs_count,
            "available_outcome_count": avail_count,
            "unavailable_outcome_count": unavail_count,
            "mean_forward_return": mean_ret,
            "median_forward_return": med_ret,
            "positive_return_rate": pos_rate,
            "mean_confidence": mean_conf,
            "calibration_gap": calib_gap,
        }

    return {
        "by_bucket": by_bucket,
        "by_action": by_action,
        "overall": overall,
        "total_observations": total_obs_count,
    }


def evaluate_confidence_calibration(
    evaluation_dates: list[str] | None = None,
    df_stock: pd.DataFrame | None = None,
    symbol: str = "",
    universe_stock_map: dict[str, pd.DataFrame] | None = None,
    candidate_metadata: list[dict] | None = None,
    df_vnindex: pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    company_name: str = "",
    sector: str = "",
    exchange: str = "HOSE",
    horizons: list[int] | None = None,
    min_history: int = 50,
    step: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
    execution_config: ExecutionConfig | None = None,
) -> ConfidenceCalibrationResult:
    """Evaluate historical calibration between production recommendation confidence and observed forward outcomes.

    Framework & Scope:
    - Reads existing production recommendation confidence output directly without formula approximation or recomputation.
    - Evaluates empirical alignment between confidence values and observed forward returns across chronological dates.
    - Uses explicit deterministic success definition: success = forward_return > 0.
    - Bounded strictly by point-in-time dataset slicing (<= T) and forward outcome evaluation (> T).
    - Preserves all fail-closed temporal validation guarantees.

    Disclaimers:
    - Confidence is documented as a deterministic heuristic model-confidence score, NOT a calibrated probability.
    - A confidence value of 0.80 must NOT automatically be interpreted as an 80% probability of positive return.
    - Measures empirical calibration only; does NOT establish causality, profitability, or statistical significance.
    - Does NOT alter production signal formulas, confidence weights, thresholds, or trade plans.

    Returns:
    `ConfidenceCalibrationResult` containing granular observations and descriptive aggregate metrics.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    wf_res = run_walk_forward_backtest(
        evaluation_dates=evaluation_dates,
        df_stock=df_stock,
        symbol=symbol,
        universe_stock_map=universe_stock_map,
        candidate_metadata=candidate_metadata,
        df_vnindex=df_vnindex,
        df_vn30=df_vn30,
        company_name=company_name,
        sector=sector,
        exchange=exchange,
        horizons=horizons,
        min_history=min_history,
        step=step,
        start_date=start_date,
        end_date=end_date,
        execution_config=execution_config,
    )

    observations: list[ConfidenceObservation] = []

    for res in wf_res.results:
        conf = res.signal.confidence
        bucket = classify_confidence_bucket(conf)

        obs = ConfidenceObservation(
            evaluation_date=res.signal.evaluation_date,
            symbol=res.signal.symbol,
            action=res.signal.action,
            confidence=conf,
            signal_score=res.signal.signal_score,
            market_regime=res.signal.market_regime,
            confidence_bucket=bucket,
            forward_returns=res.outcome.returns,
            availability=res.outcome.availability,
        )
        observations.append(obs)

    agg_summary = aggregate_confidence_calibration_results(
        observations=observations,
        horizons=horizons,
    )

    return ConfidenceCalibrationResult(
        observations=observations,
        aggregate=agg_summary,
    )


def aggregate_component_evaluation_results(
    observations: list[ComponentObservation],
    horizons: list[int] | None = None,
    components: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate component evaluation observations into neutral performance metrics per component, horizon, and bucket.

    Notice & Assumptions:
    - Component evaluation measures point-in-time signal attribution vs forward outcomes.
    - It does NOT establish causal relationships, statistical significance (no p-values/hypothesis tests),
      model optimization, or portfolio returns.
    - Hit rate for signed component scores:
      - 'positive' bucket: hit rate = ratio of observations with forward_return > 0
      - 'negative' bucket: hit rate = ratio of observations with forward_return < 0
      - 'neutral' bucket: hit rate = ratio of observations with |forward_return| <= 0.01 (near-zero price change)
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    if components is None:
        components = DEFAULT_SIGNAL_COMPONENTS

    by_component: dict[str, dict[int, dict[str, Any]]] = {}

    for comp in components:
        by_component[comp] = {}
        for h in horizons:
            comp_h_obs = [
                o
                for o in observations
                if o.component == comp and o.horizon == h and o.forward_return is not None
            ]

            valid_rets = [o.forward_return for o in comp_h_obs if o.forward_return is not None]
            stats = calculate_return_stats(valid_rets)

            # Bucket breakdown
            bucket_metrics: dict[str, dict[str, Any]] = {}
            for b_name in ["negative", "neutral", "positive"]:
                b_obs = [o for o in comp_h_obs if o.score_bucket == b_name]
                b_rets = [o.forward_return for o in b_obs if o.forward_return is not None]
                b_stats = calculate_return_stats(b_rets)

                hit_rate = None
                if b_rets:
                    if b_name == "positive":
                        hits = sum(1 for r in b_rets if r > 0)
                    elif b_name == "negative":
                        hits = sum(1 for r in b_rets if r < 0)
                    else:  # neutral
                        hits = sum(1 for r in b_rets if abs(r) <= 0.01)
                    hit_rate = round(hits / len(b_rets), 4)

                bucket_metrics[b_name] = {
                    "count": len(b_rets),
                    "mean_return": b_stats["mean"],
                    "median_return": b_stats["median"],
                    "hit_rate": hit_rate,
                }

            by_component[comp][h] = {
                "total_observations": len(valid_rets),
                "stats": stats,
                "buckets": bucket_metrics,
            }

    return {
        "by_component": by_component,
        "total_observations": len(observations),
    }


def evaluate_signal_components(
    evaluation_dates: list[str] | None = None,
    df_stock: pd.DataFrame | None = None,
    symbol: str = "",
    universe_stock_map: dict[str, pd.DataFrame] | None = None,
    candidate_metadata: list[dict] | None = None,
    df_vnindex: pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    company_name: str = "",
    sector: str = "",
    exchange: str = "HOSE",
    horizons: list[int] | None = None,
    components: list[str] | None = None,
    min_history: int = 50,
    step: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
) -> ComponentEvaluationResult:
    """Evaluate historical performance of individual signal model components under walk-forward evaluation.

    Framework Distinction:
    - Production Signal Generation: Real-time, point-in-time calculation of complete signal
      recommendations using production model weights, confidence rules, and trade plans.
    - Historical Component Evaluation: Isolated measurement of point-in-time component scores
      (Trend, Momentum, Volume, Relative Strength, Divergence) against forward historical returns
      on identical evaluation dates and horizons without model or weight modification.
    - Portfolio Backtesting: Simulation of portfolio execution, position sizing, and transaction costs
      (NOT performed by this function).

    Explicit Disclaimers:
    - Component evaluation does NOT prove causal relationships between component scores and future returns.
    - Does NOT prove statistical significance (no p-values, hypothesis tests, or multiple-testing corrections).
    - Does NOT represent portfolio performance or trade execution.
    - Does NOT perform model, weight, or threshold optimization.
    - Does NOT automatically prove economic value of any component.

    Strict Evaluation & Temporal Guarantee:
    - Every component (Trend, Momentum, Volume, Relative Strength, Divergence) is evaluated
      on the EXACT SAME universe, EXACT SAME evaluation dates T, and EXACT SAME forward horizon outcomes.
    - Component scores are extracted directly from the production signal engine (`rec["score_components"]`)
      derived strictly from point-in-time data <= T (`get_as_of_dataset`), without score or weight modification.
    - Market inputs (VNINDEX, VN30, and universe breadth as-of T) are strictly bounded <= T.
    - Forward outcomes (> T) are evaluated using the existing deterministic forward-horizon primitive (`evaluate_forward_outcomes`).
    - Fail-closed validation rules from PR #86 / #87 are fully preserved.

    Returns:
    `ComponentEvaluationResult` containing granular component observations and aggregated metrics.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    if components is None:
        components = DEFAULT_SIGNAL_COMPONENTS

    wf_res = run_walk_forward_backtest(
        evaluation_dates=evaluation_dates,
        df_stock=df_stock,
        symbol=symbol,
        universe_stock_map=universe_stock_map,
        candidate_metadata=candidate_metadata,
        df_vnindex=df_vnindex,
        df_vn30=df_vn30,
        company_name=company_name,
        sector=sector,
        exchange=exchange,
        horizons=horizons,
        min_history=min_history,
        step=step,
        start_date=start_date,
        end_date=end_date,
    )

    observations: list[ComponentObservation] = []

    for res in wf_res.results:
        eval_d = res.signal.evaluation_date
        sym = res.signal.symbol
        score_comp_map = res.signal.score_components

        for comp_key in components:
            raw_comp_score = score_comp_map.get(comp_key)
            comp_score = _safe_float(raw_comp_score)
            bucket = classify_component_score_bucket(comp_score)

            for h in horizons:
                fwd_ret = None
                if res.outcome.availability.get(h, False):
                    fwd_ret = res.outcome.returns.get(h)

                obs = ComponentObservation(
                    evaluation_date=eval_d,
                    symbol=sym,
                    component=comp_key,
                    component_score=comp_score,
                    horizon=h,
                    forward_return=fwd_ret,
                    score_bucket=bucket,
                )
                observations.append(obs)

    agg_summary = aggregate_component_evaluation_results(
        observations=observations,
        horizons=horizons,
        components=components,
    )

    return ComponentEvaluationResult(
        observations=observations,
        aggregate=agg_summary,
    )
