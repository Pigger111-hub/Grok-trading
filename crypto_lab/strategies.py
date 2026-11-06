"""Textbook strategies, with the parameter defaults people usually publish.

Signals are 1 (fully long), 0 (cash), or missing during the warmup period.
A strategy that needs a state machine (enter on one rule, exit on another)
uses hysteresis: while already long, an exit wins over a fresh entry.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from crypto_lab.indicators import bollinger, donchian, macd, rsi, sma


def hysteresis(index, entry: pd.Series, exit_: pd.Series, warmup_end: int) -> pd.Series:
    position = 0
    out = np.full(len(index), np.nan)
    enter = entry.fillna(False).to_numpy(dtype=bool)
    leave = exit_.fillna(False).to_numpy(dtype=bool)
    for i in range(max(warmup_end, 0), len(index)):
        if position == 1 and leave[i]:
            position = 0
        elif position == 0 and enter[i] and not leave[i]:
            position = 1
        out[i] = float(position)
    return pd.Series(out, index=index)


def sma_cross_signal(bars: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.Series:
    fast_ma = sma(bars["close"], int(fast))
    slow_ma = sma(bars["close"], int(slow))
    long = (fast_ma > slow_ma).astype(float)
    return long.where(slow_ma.notna())


def sma_filter_signal(bars: pd.DataFrame, window: int = 200) -> pd.Series:
    average = sma(bars["close"], int(window))
    long = (bars["close"] > average).astype(float)
    return long.where(average.notna())


def rsi_signal(
    bars: pd.DataFrame,
    period: int = 14,
    oversold: float = 30,
    overbought: float = 70,
) -> pd.Series:
    values = rsi(bars["close"], int(period))
    enter = values < float(oversold)
    leave = values > float(overbought)
    return hysteresis(bars.index, enter, leave, warmup_end=int(period))


def macd_signal(bars: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    line, signal_line, _ = macd(bars["close"], int(fast), int(slow), int(signal))
    long = (line > signal_line).astype(float)
    # An EMA exists from the first row, but it is only a seed. Wait until the
    # slow average and the signal line have both had a full window.
    warmup = int(slow) + int(signal) - 1
    long.iloc[:warmup] = np.nan
    return long


def bollinger_signal(bars: pd.DataFrame, window: int = 20, nstd: float = 2.0) -> pd.Series:
    mid, _upper, lower = bollinger(bars["close"], int(window), float(nstd))
    enter = bars["close"] < lower
    leave = bars["close"] > mid
    return hysteresis(bars.index, enter, leave, warmup_end=int(window) - 1)


def donchian_signal(bars: pd.DataFrame, entry: int = 20, exit: int = 10) -> pd.Series:
    prior_high, prior_low = donchian(bars["high"], bars["low"], int(entry), int(exit))
    enter = bars["close"] > prior_high
    leave = bars["close"] < prior_low
    # The entry channel is the longer one, so it becomes valid last.
    return hysteresis(bars.index, enter, leave, warmup_end=int(entry))


def _pairs(fast_values, slow_values):
    return tuple(
        {"fast": fast, "slow": slow}
        for fast in fast_values
        for slow in slow_values
        if fast < slow
    )


@dataclass
class Strategy:
    id: str
    kind: str  # "signal" or "dca"
    name_en: str
    name_th: str
    claim_th: str
    source_th: str
    default_params: dict
    grid: tuple
    generate: callable


def _dca_unused(_bars, weeks: int = 52):
    raise RuntimeError("DCA is priced by run_dca, not by a 0/1 signal")


STRATEGIES = [
    Strategy(
        id="sma_cross",
        kind="signal",
        name_en="SMA 50/200 crossover",
        name_th="เส้นค่าเฉลี่ย 50 วันตัด 200 วัน",
        claim_th=(
            "คนมักบอกว่าเมื่อเส้นค่าเฉลี่ย 50 วันตัดขึ้นเหนือเส้น 200 วัน "
            "(เรียกว่า Golden Cross) เป็นสัญญาณตลาดกระทิง ให้ซื้อ และเมื่อตัดลง (Death Cross) ให้ขาย"
        ),
        source_th=(
            "คำจำกัดความมาตรฐานของ Golden Cross / Death Cross จาก Investopedia "
            "(https://www.investopedia.com/terms/g/goldencross.asp). "
            "บทความข่าวบิตคอยน์มักยกคู่ 50/200 วันนี้ซ้ำ ๆ เป็นกลยุทธ์ระยะยาว"
        ),
        default_params={"fast": 50, "slow": 200},
        grid=_pairs((20, 50, 100), (100, 150, 200)),
        generate=sma_cross_signal,
    ),
    Strategy(
        id="sma_filter",
        kind="signal",
        name_en="Price above 200-day SMA",
        name_th="ถือก็ต่อเมื่อราคาปิดอยู่เหนือเส้น 200 วัน",
        claim_th=(
            "คนมักบอกว่าให้ถือบิตคอยน์หรืออีเธอเรียมไว้เมื่อราคาอยู่เหนือเส้นค่าเฉลี่ย 200 วัน "
            "และถือเงินสดเมื่อราคาหลุดลงไปใต้เส้น จะได้หนีช่วงตลาดหมีและขาดทุนน้อยลง"
        ),
        source_th=(
            "แนวคิดต้นทางในบทความวิชาการคือ Meb Faber, "
            "\"A Quantitative Approach to Tactical Asset Allocation\" (2007, ปรับปรุง 2013) "
            "ซึ่งใช้เส้นค่าเฉลี่ย 10 เดือนเพื่อออกจากสินทรัพย์เสี่ยง. "
            "ชุมชนคริปโตนำแนวนี้มาใช้เป็นเส้น 200 วันบนกราฟรายวัน "
            "ซึ่งไม่ใช่การทดลองชุดเดียวกับของ Faber และไม่ได้ทดสอบกับบิตคอยน์ในเปเปอร์นั้น"
        ),
        default_params={"window": 200},
        grid=tuple({"window": window} for window in (100, 150, 200, 250)),
        generate=sma_filter_signal,
    ),
    Strategy(
        id="rsi",
        kind="signal",
        name_en="RSI 14 mean reversion",
        name_th="RSI 14 ซื้อเมื่อถูกเกินไป ขายเมื่อแพงเกินไป",
        claim_th=(
            "คนมักบอกว่า RSI ต่ำกว่า 30 แปลว่าราคาถูกเกินไป ให้ซื้อ "
            "และ RSI สูงกว่า 70 แปลว่าแพงเกินไป ให้ขาย"
        ),
        source_th=(
            "J. Welles Wilder Jr., New Concepts in Technical Trading Systems (1978) "
            "กำหนด RSI คาบ 14 และระดับ 30/70. "
            "Investopedia สรุปกติกาเดียวกันไว้ที่ https://www.investopedia.com/terms/r/rsi.asp. "
            "บทเรียนของกระดานเทรดคริปโตมักยกกติกานี้ไปใช้กับบิตคอยน์โดยตรง"
        ),
        default_params={"period": 14, "oversold": 30, "overbought": 70},
        grid=tuple(
            {"period": period, "oversold": oversold, "overbought": overbought}
            for period in (7, 14)
            for oversold in (20, 30)
            for overbought in (60, 70)
        ),
        generate=rsi_signal,
    ),
    Strategy(
        id="macd",
        kind="signal",
        name_en="MACD 12/26/9",
        name_th="MACD 12/26/9 ถือเมื่อเส้น MACD อยู่เหนือเส้นสัญญาณ",
        claim_th=(
            "คนมักบอกว่าเมื่อเส้น MACD ตัดขึ้นเหนือเส้นสัญญาณ ให้ซื้อ "
            "และเมื่อตัดลงให้ขาย เป็นเครื่องมือตามเทรนด์ที่ใช้กันแพร่หลายมากในคริปโต"
        ),
        source_th=(
            "Gerald Appel เป็นผู้เสนอ MACD และค่าเริ่มต้นที่คนใช้กันคือ 12, 26 และ 9. "
            "Investopedia สรุปไว้ที่ https://www.investopedia.com/terms/m/macd.asp. "
            "ค่าชุดนี้เป็นค่าปริยายบน TradingView และในบทเรียนวิเคราะห์ทางเทคนิคของกระดานเทรด"
        ),
        default_params={"fast": 12, "slow": 26, "signal": 9},
        grid=tuple(
            {"fast": fast, "slow": slow, "signal": 9}
            for fast in (8, 12)
            for slow in (21, 26)
            if fast < slow
        ),
        generate=macd_signal,
    ),
    Strategy(
        id="bollinger",
        kind="signal",
        name_en="Bollinger band mean reversion",
        name_th="โบลลินเจอร์แบนด์ ซื้อที่ขอบล่าง ขายที่เส้นกลาง",
        claim_th=(
            "คนมักบอกว่าเมื่อราคาหลุดต่ำกว่าขอบล่างของโบลลินเจอร์แบนด์ แปลว่าราคาถูกเกินไป ให้ซื้อ "
            "แล้วขายเมื่อราคากลับขึ้นมาที่เส้นค่าเฉลี่ยตรงกลาง"
        ),
        source_th=(
            "John Bollinger ทำให้แถบ 20 วัน กว้าง 2 เท่าของส่วนเบี่ยงเบนมาตรฐานเป็นที่รู้จัก "
            "ในหนังสือ Bollinger on Bollinger Bands. สูตรแถบอยู่ที่ "
            "https://www.investopedia.com/terms/b/bollingerbands.asp. "
            "Bollinger เองไม่ได้บอกว่าการซื้อที่ขอบล่างเป็นระบบสำเร็จรูป "
            "กติกา \"ซื้อขอบล่าง ขายเส้นกลาง\" เป็นกติกาที่นักเทรดรายย่อยเล่าต่อกัน"
        ),
        default_params={"window": 20, "nstd": 2.0},
        grid=tuple(
            {"window": window, "nstd": nstd}
            for window in (10, 20, 40)
            for nstd in (1.5, 2.0, 2.5)
        ),
        generate=bollinger_signal,
    ),
    Strategy(
        id="donchian",
        kind="signal",
        name_en="Donchian 20/10 breakout",
        name_th="ทะลุกรอบดอนเชียน 20 วัน ออกเมื่อหลุดกรอบ 10 วัน",
        claim_th=(
            "คนมักบอกว่าให้ซื้อเมื่อราคาปิดทะลุจุดสูงสุดของ 20 วันที่ผ่านมา "
            "และขายเมื่อราคาปิดหลุดจุดต่ำสุดของ 10 วันที่ผ่านมา เป็นวิธีตามเทรนด์แบบคลาสสิก"
        ),
        source_th=(
            "ช่องราคาของ Richard Donchian. กติกาเข้า 20 วัน / ออก 10 วัน คือระบบที่ 1 "
            "ของกลุ่มเต่า (Turtle Traders) ที่ Richard Dennis สอนไว้ช่วงปี 1983 "
            "และถูกเล่าไว้ใน Curtis Faith, Way of the Turtle (2007) "
            "รวมถึงเอกสาร Original Turtle Trading Rules ที่เผยแพร่ต่อสาธารณะ. "
            "บทความตามเทรนด์ในคริปโตมักยกช่องดอนเชียนมาใช้กับบิตคอยน์ในลักษณะเดียวกัน. "
            "ดูคำอธิบายช่องราคาได้ที่ https://www.investopedia.com/terms/d/donchianchannels.asp"
        ),
        default_params={"entry": 20, "exit": 10},
        grid=tuple(
            {"entry": entry, "exit": exit_n}
            for entry in (10, 20, 55)
            for exit_n in (5, 10, 20)
            if exit_n < entry
        ),
        generate=donchian_signal,
    ),
    Strategy(
        id="dca_weekly",
        kind="dca",
        name_en="52-week dollar-cost averaging",
        name_th="ทยอยซื้อทุกสัปดาห์เป็นเวลา 1 ปี แล้วถือยาว",
        claim_th=(
            "คนมักบอกว่าอย่าซื้อครั้งเดียว ให้ทยอยซื้อทีละนิด (DCA) จะปลอดภัยกว่าและได้ราคาเฉลี่ยที่ดีกว่า"
        ),
        source_th=(
            "คำแนะนำ DCA พบได้ทั่วไปในบทเรียนของกระดานเทรด เช่น Coinbase และ Binance Academy "
            "และในกลุ่มคริปโตภาษาไทย. งานวิจัยที่สวนทางกับคำแนะนำนี้คือ Vanguard, "
            "\"Dollar-cost averaging just means taking risk later\" "
            "(Anatoly Shtekhman, Christos Tasopoulos, Brian Wimmer, 2012) "
            "ซึ่งพบว่าการลงทุนก้อนเดียวครั้งเดียวชนะการทยอยซื้อประมาณสองในสามของช่วงเวลา "
            "ในตลาดหุ้นและพันธบัตรแบบดั้งเดิม ไม่ได้เป็นงานวิจัยของบิตคอยน์โดยตรง"
        ),
        default_params={"weeks": 52},
        grid=tuple({"weeks": weeks} for weeks in (12, 26, 52, 104)),
        generate=_dca_unused,
    ),
]

STRATEGIES_BY_ID = {strategy.id: strategy for strategy in STRATEGIES}
