"""cbBTC 1-minute dip-buy bot for the make.fun btc-race-24h competition.

Long only, one position, all cash per entry. The gate is the 60-minute
return: only buy dips while the last hour is up. A dip is a close at least
60 bps under the highest close of the last 30 bars. Take +0.80%, stop
-0.30%, give up after 120 bars, or leave when the hour turns down.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars  # noqa: E402

SYMBOL = "CBBTC"
MAX_SLIPPAGE_BPS = 300
GATE_BARS = 60
LOOKBACK = 30
DIP = 0.0060
TAKE = 0.0080
STOP = -0.0030
HOLD_BARS = 120
FALLBACK_UNITS = 2_000_000  # 2 USDC participation trade if no entry came

closes = []
entry_bar = None
traded = False
pending = False


def _bar(batch):
    for b in batch["bars"]:
        if b["symbol"] == SYMBOL:
            return b
    return None


def _fills(batch):
    global pending, traded, entry_bar
    for f in batch["fills"]:
        if f["symbol"] != SYMBOL:
            continue
        if f["status"] == "filled":
            if f["side"] == "buy":
                traded = True
                entry_bar = len(closes)
            pending = False
        elif f["side"] == "buy" and pending:
            pending = False


def _gate():
    return len(closes) > GATE_BARS and closes[-1] > closes[-1 - GATE_BARS]


def _dip():
    if len(closes) < LOOKBACK:
        return 0.0
    hi = max(closes[-LOOKBACK:])
    return (hi - closes[-1]) / hi if hi else 0.0


def on_batch(state, batch):
    global pending
    _fills(batch)
    bar = _bar(batch)
    if bar is None:
        return []
    closes.append(int(bar["c"]))

    held = state.positions.get(SYMBOL)
    if held is not None and held.cost > 0:
        ratio = state.value(SYMBOL, held.qty) / held.cost - 1.0
        too_long = entry_bar is not None and len(closes) - entry_bar >= HOLD_BARS
        # Any single trigger flattens the position: target hit, stop hit, held
        # too long, or the 60-minute gate flipped negative while we were in.
        if ratio >= TAKE or ratio <= STOP or too_long or not _gate():
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty, "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []

    if _gate() and _dip() >= DIP and not pending:
        cash = state.cash
        if cash >= int(state.hello["fees"]["min_notional_quote_units"]):
            pending = True
            return [{"side": "buy", "symbol": SYMBOL, "notional_quote_units": cash, "max_slippage_bps": MAX_SLIPPAGE_BPS}]

    if not traded and not pending and batch["seq"] >= 1200 and state.cash >= FALLBACK_UNITS:
        pending = True
        return [{"side": "buy", "symbol": SYMBOL, "notional_quote_units": FALLBACK_UNITS, "max_slippage_bps": MAX_SLIPPAGE_BPS}]
    return []


makefun_bars.run(on_batch)
