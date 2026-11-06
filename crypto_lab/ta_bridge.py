"""pandas-ta is available for indicator checks. Strategy signals stay on our own functions.

Our RSI is Wilder's version and is covered by hand-calculated tests. pandas-ta is
used to confirm the simple moving average, which has one definition.
"""

from __future__ import annotations

import pandas as pd


def sma_pandas_ta(close: pd.Series, window: int) -> pd.Series:
    import pandas_ta as ta

    return ta.sma(close, length=int(window))
