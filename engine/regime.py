"""Rezim pasar (RISK-ON / NEUTRAL / RISK-OFF) dari IHSG, breadth, volatilitas, dan rupiah."""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute(ihsg: pd.Series, F: dict, usdidr: pd.Series | None = None) -> pd.DataFrame:
    idx = F["c"].index
    px = ihsg.reindex(idx).ffill()
    ma50, ma200 = px.rolling(50, min_periods=50).mean(), px.rolling(200, min_periods=120).mean()
    liq = F["liquid"]
    breadth = ((F["c"] > F["ma50"]) & liq).sum(axis=1) / liq.sum(axis=1).replace(0, np.nan)
    vol20 = px.pct_change().rolling(20, min_periods=15).std() * np.sqrt(252)
    vol_pct = vol20.rolling(252, min_periods=60).rank(pct=True)
    fx20 = usdidr.reindex(idx).ffill().pct_change(20) if usdidr is not None else pd.Series(0.0, index=idx)
    dd = px / px.rolling(252, min_periods=60).max() - 1

    comp = pd.DataFrame({
        "ihsg_gt_ma200": (px > ma200).astype(int),
        "ma50_gt_ma200": (ma50 > ma200).astype(int),
        "breadth_strong": (breadth > 0.5).astype(int),
        "breadth_weak": -(breadth < 0.3).astype(int),
        "vol_high": -(vol_pct > 0.8).astype(int),
        "rupiah_weak": -(fx20 > 0.015).astype(int),
    }, index=idx)
    score = comp.sum(axis=1)
    label = np.where(score >= 2, "RISK-ON", np.where(score >= 0, "NEUTRAL", "RISK-OFF"))
    out = comp.copy()
    out["score"] = score
    out["label"] = label
    out["breadth"] = breadth
    out["vol20"] = vol20
    out["vol_pct"] = vol_pct
    out["fx20"] = fx20
    out["dd"] = dd
    out["ihsg"] = px
    out["ma50"] = ma50
    out["ma200"] = ma200
    return out
