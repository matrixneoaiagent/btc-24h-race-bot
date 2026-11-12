"""cbBTC 1-minute trading bot for the make.fun btc-race-24h competition.

Long only, one position at a time, all cash per entry. The regime is EMA(60)
above EMA(240) of the bar close: enter on a fresh up cross and take half the
position off at +0.70%, then trail the rest; a -0.60% hard stop or the regime
turning down closes whatever is left. Cash the rest of the time.
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
# Take half off here, then trail the remainder more loosely.
PARTIAL_AT = 0.0070
PARTIAL_FRACTION = 0.5
PARTIAL_GAP = 0.0050
# Enter only when the fast EMA is at least this far above the slow one: a
# 10 bp gap is a trend, not the noise around a flat pair.
TREND_GAP = 0.0010


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
_partial_done = False
_traded = False
_min_trade_units = 2_000_000  # 2 USDC: the participation trade if no regime entry came


def _cbbtc_bar(batch):
    """The batch's CBBTC bar, or None when this minute has no bar for it."""
    bar = None
    for candidate in batch["bars"]:
        if candidate["symbol"] == SYMBOL:
            bar = candidate
    return bar


def _apply_fills(batch):
    """Fold the previous reply's fills into the latch, peak and partial state."""
    global _entered, _pending_buy, _peak_ratio, _partial_done, _traded
    for fill in batch["fills"]:
        if fill["symbol"] != SYMBOL:
            continue
        if fill["status"] == "filled":
            # A filled buy opens a fresh peak; a filled sell closes or trims it.
            _peak_ratio = None
            if fill["side"] == "buy":
                _pending_buy = False
                _partial_done = False
                _traded = True
        elif fill["side"] == "buy" and _pending_buy:
            # The market refused the entry: a later bar may try again.
            _pending_buy = False
            _entered = False
        elif fill["side"] == "sell" and _partial_done:
            # The partial was refused (max_slippage); keep the whole position
            # and try the trim again on a later bar.
            _partial_done = False


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


def _sell_order(qty):
    return {
        "side": "sell",
        "symbol": SYMBOL,
        "qty": qty,
        "max_slippage_bps": MAX_SLIPPAGE_BPS,
    }


def _min_notional(state):
    """The venue's smallest entry, in quote units."""
    return int(state.hello["fees"]["min_notional_quote_units"])


def _trend_gap(fast, slow, close):
    """The fast-over-slow EMA gap as a fraction of the close; 0 if close is 0."""
    return (fast - slow) / float(close) if close else 0.0


def on_batch(state, batch):
    """Answer one minute's bar with at most one order."""
    global _entered, _pending_buy, _partial_done

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
        # Once half is banked at +0.70%, the rest may not turn the trade into
        # a loser: its stop moves to +0.10% over cost.
        stop = 0.0010 if _partial_done else STOP_LOSS
        if ratio <= stop or fast < slow:
            return [_sell_order(held.qty)]
        if not _partial_done and _peak_ratio >= PARTIAL_AT:
            trim = held.qty // 2
            if trim > 0:
                _partial_done = True
                return [_sell_order(trim)]
        gap = PARTIAL_GAP if _partial_done else TRAIL_GAP
        if _peak_ratio >= TRAIL_ARM and ratio <= _peak_ratio - gap:
            return [_sell_order(held.qty)]
        return []

    if not _pending_buy:
        cash = state.cash
        gap = _trend_gap(fast, slow, bar["c"])
        if fast > slow and gap >= TREND_GAP and not _entered:
            if cash >= _min_notional(state):
                _entered = True
                _pending_buy = True
                return [_buy_order(cash)]
        elif not _traded and batch["seq"] >= 1200 and cash >= _min_trade_units:
            # No regime entry all window: a token long keeps the entry in the
            # contest's guardrail (at least one trade) without betting the book.
            _pending_buy = True
            return [_buy_order(_min_trade_units)]
    return []


if __name__ == "__main__":
    makefun_bars.run(on_batch)
