"""Sekali pakai: cek indeks dunia (sampai frontier), komoditas, IMF DataMapper, RSS berita global (log PRB|)."""
import json, urllib.request
import yfinance as yf, feedparser, requests

IDX = """^GSPC ^IXIC ^DJI ^RUT ^GSPTSE ^FTSE ^GDAXI ^FCHI ^STOXX50E ^AEX ^IBEX FTSEMIB.MI ^SSMI ^OMX ^OSEAX ^BFX ^ATX PSI20.LS ^ISEQ ^N225 ^AXJO ^NZ50 ^HSI ^STI ^TA125.TA
000001.SS 399001.SZ ^KS11 ^TWII ^BSESN ^NSEI ^JKSE ^KLSE ^SET.BK PSEI.PS ^BVSP ^MXX ^MERV ^IPSA ^SPBLPGPT ^COLCAP ^J203.JO ^JN0U.JO XU100.IS ^TASI.SR ^CASE30 ^QSI DFMGI.AE FADGI.FGI WIG20.WA ^BUX.BUD ^PX ^ATG GD.AT IMOEX.ME
^VNINDEX.VN VNINDEX ^KSE100 ^KSE ^CSE ^DSEX ^NGSE ^NSE20 ^MASI ^BETI.RO ^CRBEX ^SOFIX ^BLAI ^TUNINDEX ^BVL ^KWSE ^BHSE ^MSM30 ^GNA ^EGX30
EWA EWC EWG EWQ EWU EWL EWI EWP EWN EWD EIS EWH ECH EPU GXG ARGT EZA TUR EPOL KSA QAT UAE EGPT PAK GREK KWT VNM NGE FM FRN AFK""".split()
CMD = """CL=F BZ=F NG=F RB=F HO=F MTF=F GC=F SI=F PL=F PA=F HG=F ALI=F ZC=F ZW=F ZS=F ZM=F ZL=F ZO=F ZR=F KC=F SB=F CC=F CT=F OJ=F LBS=F LE=F HE=F GF=F DC=F UX=F TIO=F""".split()
for s in IDX + CMD:
    try:
        d = yf.download(s, period="10y", interval="1d", progress=False, auto_adjust=True)
        c = d["Close"].dropna(); c = c.iloc[:, 0] if hasattr(c, "columns") else c
        print(f"PRB|Y {s:12s} n={len(c):5d} {c.index[0].date() if len(c) else '-'} -> {c.index[-1].date() if len(c) else '-'}")
    except Exception as e:
        print(f"PRB|Y {s:12s} GAGAL {str(e)[:80]}")
for ind in ["NGDP_RPCH", "PCPIPCH", "LUR", "BCA_NGDPD", "GGXWDG_NGDP", "GGXCNL_NGDP", "NGDPDPC"]:
    try:
        r = requests.get(f"https://www.imf.org/external/datamapper/api/v1/{ind}?periods=2024,2025,2026,2027", timeout=40, headers={"User-Agent": "idx-quant-terminal/1.0"})
        j = r.json(); v = j.get("values", {}).get(ind, {})
        print(f"PRB|IMF {ind} status={r.status_code} negara={len(v)} IDN={v.get('IDN')} USA={v.get('USA')}")
    except Exception as e:
        print(f"PRB|IMF {ind} GAGAL {str(e)[:120]}")
try:
    r = requests.get("https://www.imf.org/external/datamapper/api/v1/countries", timeout=40); print("PRB|IMF countries", r.status_code, len(r.json().get("countries", {})))
    r = requests.get("https://www.imf.org/external/datamapper/api/v1/groups", timeout=40); print("PRB|IMF groups", r.status_code, list(r.json().get("groups", {}).keys())[:30])
except Exception as e:
    print("PRB|IMF meta GAGAL", e)
for u in ["https://api.worldbank.org/v2/country/IDN/indicator/FR.INR.LEND?format=json&per_page=5",
          "https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.KD.ZG?format=json&per_page=5&date=2024"]:
    try:
        r = requests.get(u, timeout=40); print("PRB|WB", r.status_code, str(r.json())[:200])
    except Exception as e:
        print("PRB|WB GAGAL", e)
FEEDS = ["https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
         "https://news.google.com/rss/search?q=global+markets+when:2d&hl=en-US&gl=US&ceid=US:en",
         "https://news.google.com/rss/search?q=central+bank+rate+decision+when:3d&hl=en-US&gl=US&ceid=US:en",
         "https://www.cnbc.com/id/100727362/device/rss/rss.html", "https://www.cnbc.com/id/10000664/device/rss/rss.html",
         "https://feeds.bbci.co.uk/news/business/rss.xml", "https://www.aljazeera.com/xml/rss/all.xml",
         "https://feeds.marketwatch.com/marketwatch/topstories/", "https://finance.yahoo.com/news/rssindex",
         "https://www.ft.com/world?format=rss", "https://www.investing.com/rss/news_25.rss", "https://www.theguardian.com/business/economics/rss",
         "https://www.dw.com/rss/rdf/rss-en-bus", "https://www3.nhk.or.jp/rss/news/cat5.xml", "https://www.scmp.com/rss/92/feed"]
for u in FEEDS:
    try:
        r = requests.get(u, timeout=25, headers={"User-Agent": "Mozilla/5.0 idx-quant-terminal"})
        fp = feedparser.parse(r.content)
        print(f"PRB|RSS {r.status_code} n={len(fp.entries):3d} {u[:90]} | {fp.entries[0].title[:70] if fp.entries else ''}")
    except Exception as e:
        print(f"PRB|RSS GAGAL {u[:90]} {str(e)[:80]}")
