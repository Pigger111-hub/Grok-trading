"""Numbers the whole lab shares. Change them here, not inside each strategy.

These are assumptions, not measurements from a personal account.
"""

# 0.10% of the traded amount, charged on buys and on sells.
# Close to the standard spot fee many exchanges advertise before discounts.
FEE_RATE = 0.001

# 0.05% worse fill than the printed open: we buy slightly higher and sell slightly lower.
SLIPPAGE_RATE = 0.0005

# Pretend starting cash. Nothing is sent to an exchange.
INITIAL_CASH = 10_000.0

# Crypto trades every day, including weekends, so a year has 365 days here
# (stock research often uses 252). Cash earns nothing unless a backtest opts in
# by passing cash_annual_yield. Any non-zero rate is an assumption for that
# run, not a rate observed in a particular year.
PERIODS_PER_YEAR = 365
CASH_ANNUAL_YIELD = 0.0

# Paper book only. Research tables stay at CASH_ANNUAL_YIELD unless a caller
# opts in. This 4% is an assumption on cash actually held. It is not interest
# paid by a bank or an exchange. Buy-and-hold does not use it.
PAPER_CASH_ANNUAL_YIELD = 0.04

# First 70% of each coin's history is the "in-sample" period. The last 30%
# is "out-of-sample": we look at it only after the rules are already chosen.
IN_SAMPLE_FRACTION = 0.70

# Walk-forward: pick parameters using the previous 2 years, then trade the next year.
WALK_FORWARD_TRAIN_DAYS = 730
WALK_FORWARD_TEST_DAYS = 365

# Paper book opens on this UTC date with INITIAL_CASH. It is still a simulation.
# The scheduled job runs on the 4-hour clock. Daily strategies may change
# position only after a daily candle has closed.
PAPER_START = "2025-01-01"

# Bars per calendar day. One-hour candles are intentionally absent.
BARS_PER_DAY = {"1d": 1, "4h": 6}
