"""Sekali pakai: cek simbol Yahoo & seri FRED mana yang tersedia (log PRB|)."""
import io, urllib.request
import pandas as pd, yfinance as yf

Y = """SPY QQQ IWM ACWI EFA EEM VGK EWJ MCHI FXI INDA EIDO EWS EWM THD EPHE VNM EWY EWT EWZ
SHY IEF TLT TIP LQD HYG EMB BNDX
GLD SLV USO DBC CPER DBA PDBC URA COPX REMX PICK
XLK XLF XLE XLV XLI XLY XLP XLU XLB XLRE XLC
BTC-USD ETH-USD IBIT
^VIX ^MOVE ^IRX ^FVX ^TNX ^TYX DX-Y.NYB UUP
HG=F CL=F BZ=F GC=F MTF=F NCF=F KPO=F NG=F ZS=F
USDIDR=X EURUSD=X USDJPY=X USDCNY=X AUDUSD=X ^JKSE ^GSPC 000001.SS ^HSI ^STI ^N225""".split()
F = "T10Y2Y T10Y3M T10YIE DFII10 BAMLH0A0HYM2 WALCL M2SL CPIAUCSL UNRATE ICSA NFCI DTWEXBGS DGS10 DGS2 FEDFUNDS INDCPIALLMINMEI IRSTCB01IDM156N CCUSMA02IDM618N".split()
for s in Y:
    try:
        d = yf.download(s, period="max", interval="1d", progress=False, auto_adjust=False)
        c = d["Close"].dropna()
        c = c.iloc[:, 0] if hasattr(c, "columns") else c
        print(f"PRB|Y {s:10s} n={len(c):5d} {c.index[0].date() if len(c) else '-'} -> {c.index[-1].date() if len(c) else '-'}")
    except Exception as e:
        print(f"PRB|Y {s:10s} GAGAL {e}")
for f in F:
    try:
        u = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={f}"
        r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "idx-quant-terminal"}), timeout=30).read()
        d = pd.read_csv(io.BytesIO(r))
        print(f"PRB|F {f:22s} n={len(d):5d} {d.iloc[0,0]} -> {d.iloc[-1,0]} last={d.iloc[-1,1]}")
    except Exception as e:
        print(f"PRB|F {f:22s} GAGAL {e}")
