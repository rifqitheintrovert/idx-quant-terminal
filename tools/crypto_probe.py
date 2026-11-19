"""Sementara: cek endpoint mana yang bisa diakses dari runner GitHub Actions."""
import json, urllib.request

H = {"User-Agent": "Mozilla/5.0 flowterm-probe"}
U = [
    ("geo", "https://ipinfo.io/json", None),
    ("bin_spot_vision", "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=2", None),
    ("bin_spot_api", "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=2", None),
    ("bin_fapi_kl", "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1d&limit=2", None),
    ("bin_fapi_taker", "https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1d&limit=2", None),
    ("bin_bulk", "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2026-11-01.zip.CHECKSUM", None),
    ("bybit", "https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=D&limit=2", None),
    ("bytick", "https://api.bytick.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=D&limit=2", None),
    ("okx_taker_c", "https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=1D", None),
    ("okx_taker_s", "https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=SPOT&period=1D", None),
    ("okx_kl", "https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT&bar=1Dutc&limit=2", None),
    ("gate", "https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=BTC_USDT&interval=1d&limit=2", None),
    ("bitget", "https://api.bitget.com/api/v2/spot/market/candles?symbol=BTCUSDT&granularity=1day&limit=2", None),
    ("bitget_taker", "https://api.bitget.com/api/v2/mix/market/taker-buy-sell?symbol=BTCUSDT&productType=usdt-futures&period=1d", None),
    ("kucoin", "https://api.kucoin.com/api/v1/market/candles?type=1day&symbol=BTC-USDT", None),
    ("mexc", "https://api.mexc.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=2", None),
    ("cb", "https://api.exchange.coinbase.com/products/BTC-USD/stats", None),
    ("hl", "https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"}),
    ("cm", "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=PriceUSD,CapMVRVCur&frequency=1d&page_size=2&paging_from=end", None),
    ("llama_cex", "https://api.llama.fi/cexs", None),
    ("llama_st", "https://stablecoins.llama.fi/stablecoinchains", None),
    ("gecko_term", "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools?page=1", None),
    ("dexs", "https://api.dexscreener.com/token-boosts/top/v1", None),
    ("cg", "https://api.coingecko.com/api/v3/global", None),
]
for k, u, post in U:
    try:
        data = json.dumps(post).encode() if post else None
        req = urllib.request.Request(u, data=data, headers={**H, **({"Content-Type": "application/json"} if post else {})})
        with urllib.request.urlopen(req, timeout=20) as r:
            b = r.read()
            print(f"OK   {k:16s} {r.status} {len(b):>8d}B  {b[:160]!r}")
    except Exception as e:
        body = b""
        try: body = e.read()[:160]
        except Exception: pass
        print(f"FAIL {k:16s} {type(e).__name__}: {e} {body!r}")
