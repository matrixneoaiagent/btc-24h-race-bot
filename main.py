"""cbBTC 1-minute trading bot for the make.fun btc-race-24h competition.

Long only, one position at a time, all cash per entry. The regime is the
EMA(60) above the EMA(240) of the bar close; entries happen only on the first
bar of an up regime, and exits are a trailing stop, a hard stop, or the
regime turning down.
"""

import os
import sys

# The harness runs `python3 -P -s /bot/main.py`, so the script directory is not
# on sys.path. Put the vendored shim's directory there ourselves.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars  # noqa: E402

SYMBOL = "CBBTC"
FAST_SPAN = 60
SLOW_SPAN = 240
MAX_SLIPPAGE_BPS = 300

# Exit thresholds, as fractions of the position's cost.
TRAIL_ARM = 0.0040
TRAIL_GAP = 0.0035
STOP_LOSS = -0.0060


class Ema:
    """Exponential moving average seeded with the first close it sees."""

    __slots__ = ("alpha", "value")

    def __init__(self, span):
        self.alpha = 2.0 / (span + 1.0)
        self.value = None

    def update(self, close):
        close = float(close)
        if self.value is None:
            self.value = close
        else:
            self.value += self.alpha * (close - self.value)
        return self.value


_fast = Ema(FAST_SPAN)
_slow = Ema(SLOW_SPAN)
_entered = False
_pending_buy = False
_peak_ratio = None


def _cbbtc_bar(batch):
    """The batch's CBBTC bar, or None when this minute has no bar for it."""
    bar = None
    for candidate in batch["bars"]:
        if candidate["symbol"] == SYMBOL:
            bar = candidate
    return bar


def _apply_fills(batch):
    """Fold the previous reply's fills into the latch and peak state."""
    global _entered, _pending_buy, _peak_ratio
    for fill in batch["fills"]:
        if fill["symbol"] != SYMBOL:
            continue
        if fill["status"] == "filled":
            # A filled buy opens a fresh peak; a filled sell closes the old one.
            _peak_ratio = None
            if fill["side"] == "buy":
                _pending_buy = False
        elif fill["side"] == "buy" and _pending_buy:
            # The market refused the entry: a later bar may try again.
            _pending_buy = False
            _entered = False


def _mark_ratio(state, held):
    """The position's return over cost at the latest close, with its running peak."""
    global _peak_ratio
    ratio = state.value(SYMBOL, held.qty) / held.cost - 1.0
    if _peak_ratio is None or ratio > _peak_ratio:
        _peak_ratio = ratio
    return ratio


def _buy_order(cash):
    return {
        "side": "buy",
        "symbol": SYMBOL,
        "notional_quote_units": cash,
        "max_slippage_bps": MAX_SLIPPAGE_BPS,
    }


def _sell_order(held):
    return {
        "side": "sell",
        "symbol": SYMBOL,
        "qty": held.qty,
        "max_slippage_bps": MAX_SLIPPAGE_BPS,
    }


def on_batch(state, batch):
    """Answer one minute's bar with at most one order."""
    global _entered, _pending_buy

    _apply_fills(batch)
    bar = _cbbtc_bar(batch)
    if bar is None:
        return []

    fast = _fast.update(int(bar["c"]))
    slow = _slow.update(int(bar["c"]))
    if fast < slow:
        # A down cross ends the regime leg; only a fresh up cross may enter.
        _entered = False

    held = state.positions.get(SYMBOL)
    if held is not None and held.cost > 0:
        ratio = _mark_ratio(state, held)
        trailing = _peak_ratio >= TRAIL_ARM and ratio <= _peak_ratio - TRAIL_GAP
        if trailing or ratio <= STOP_LOSS or fast < slow:
            return [_sell_order(held)]
        return []

    if fast > slow and not _entered and not _pending_buy:
        cash = state.cash
        if cash >= int(state.hello["fees"]["min_notional_quote_units"]):
            _entered = True
            _pending_buy = True
            return [_buy_order(cash)]
    return []


if __name__ == "__main__":
    makefun_bars.run(on_batch)
