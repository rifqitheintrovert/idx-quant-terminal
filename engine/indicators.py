"""Indikator teknikal & money flow. Semua fungsi menerima Series ATAU panel DataFrame
(index = tanggal, kolom = ticker) sehingga bisa dipakai untuk sinyal harian maupun backtest."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(x, n):
    return x.rolling(n, min_periods=n).mean()


def ema(x, n):
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0)


def true_range(h, l, c):
    pc = c.shift(1)
    return np.maximum(np.maximum(h - l, (h - pc).abs()), (l - pc).abs())


def atr(h, l, c, n=14):
    return true_range(h, l, c).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def clv(h, l, c):
    """Close Location Value: +1 tutup di high (tekanan beli), -1 tutup di low (tekanan jual)."""
    rng = h - l
    v = ((c - l) - (h - c)) / rng.replace(0, np.nan)
    return v.fillna(0.0)


def cmf(h, l, c, v, n=20):
    """Chaikin Money Flow."""
    mfv = clv(h, l, c) * v
    return mfv.rolling(n, min_periods=n).sum() / v.rolling(n, min_periods=n).sum().replace(0, np.nan)


def mfi(h, l, c, v, n=14):
    """Money Flow Index (RSI berbobot volume)."""
    tp = (h + l + c) / 3
    rmf = tp * v
    pos = rmf.where(tp > tp.shift(1), 0.0)
    neg = rmf.where(tp < tp.shift(1), 0.0)
    ps = pos.rolling(n, min_periods=n).sum()
    ns = neg.rolling(n, min_periods=n).sum()
    out = 100 - 100 / (1 + ps / ns.replace(0, np.nan))
    return out.where(ns != 0, 100.0)


def obv(c, v):
    return (np.sign(c.diff()).fillna(0) * v).cumsum()


def obv_momentum(c, v, n=20):
    """Perubahan OBV n hari dinormalisasi oleh total volume n hari (range -1..+1)."""
    o = obv(c, v)
    return (o - o.shift(n)) / v.rolling(n, min_periods=n).sum().replace(0, np.nan)


def net_flow_value(h, l, c, v):
    """Estimasi net money flow harian (Rp) = CLV x nilai transaksi."""
    return clv(h, l, c) * c * v


def pct_rank_xs(panel: pd.DataFrame) -> pd.DataFrame:
    """Peringkat persentil cross-sectional per tanggal (0..100)."""
    return panel.rank(axis=1, pct=True) * 100
