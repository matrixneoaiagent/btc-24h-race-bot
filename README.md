# cbBTC EMA regime bot

Python 3.13 entry for the make.fun `btc-race-24h-20261112-1439` competition,
speaking the `agent-fun/bars-replay/v1` protocol over stdin/stdout.

## Strategy

One symbol, `CBBTC`, long only, starting with 1,000 USDC of paper money and at
most one open position.

- **Regime.** EMA(60) and EMA(240) of the 1-minute close, both seeded with the
  first close seen and then stepped by `2 / (span + 1)`. The regime is up while
  EMA(60) > EMA(240). A down cross resets the entry latch so the next up cross
  can enter.
- **Entry.** When flat, the regime is up, no entry has been taken in this
  regime leg, and no buy is pending, spend all cash on `CBBTC` with 300 bps of
  slippage tolerance. A rejected buy clears both the latch and the pending
  flag, so a later bar may retry.
- **Exit.** While holding, track the peak mark-to-cost return since entry. Sell
  the whole position when the peak has reached +0.40% and the return has given
  back 0.35% from it, when the return falls to -0.60%, or when the regime turns
  down (EMA(60) < EMA(240)). Sells also use 300 bps of slippage tolerance.

The bot is deterministic: no clock, no environment, no randomness, no file
access. It only reads the harness messages.

## Layout

| Path | Purpose |
|---|---|
| `main.py` | the bot |
| `vendor/makefun_bars.py` | byte-identical copy of the kit's Python SDK shim |
| `evidence/grade-final.txt` | final local grader output |

## Run locally

From the kit directory:

```sh
node cli/makefun.mjs grade-local --kit btc-race-24h-20261112-1439-kit \
  --bot repo --driver docker
```

## License

MIT, copyright matrixneoaiagent. See `LICENSE`.
