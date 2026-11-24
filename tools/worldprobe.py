import requests, yfinance as yf
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) idx-quant-terminal", "Accept": "application/json"}
for u in ["https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH", "https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH/IDN",
          "https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH/IDN/USA?periods=2025,2026", "https://www.imf.org/external/datamapper/api/v1/indicators",
          "https://www.imf.org/external/datamapper/api/NGDP_RPCH", "https://api.worldbank.org/v2/country/IDN/indicator/FP.CPI.TOTL.ZG?format=json&per_page=3"]:
    try:
        r = requests.get(u, timeout=60, headers=H); print("PRB|URL", r.status_code, r.headers.get("content-type"), len(r.content), u, "|", r.text[:220].replace("\n", " "))
    except Exception as e:
        print("PRB|URL GAGAL", u, e)
for s in "EWK EWO EIRL ENZL EWW EDEN NORW EFNL COLO ICOL EPHE THD EWM KAZ NGE FLN GLIN EMFM FRN".split():
    try:
        d = yf.download(s, period="2y", progress=False, auto_adjust=True); c = d["Close"].dropna()
        print("PRB|Y", s, len(c))
    except Exception as e:
        print("PRB|Y", s, "GAGAL")
