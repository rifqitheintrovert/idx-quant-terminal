import requests
H = {"User-Agent": "idx-quant-terminal/1.0", "Accept": "application/json"}
U = ["https://api.worldbank.org/v2/sources?format=json&per_page=100",
     "https://api.worldbank.org/v2/sources/27/indicators?format=json&per_page=60",
     "https://api.worldbank.org/v2/country/IDN;USA;CHN/indicator/NYGDPMKTPKDZ?source=27&format=json&per_page=60&date=2023:2028",
     "https://api.worldbank.org/v2/country/IDN/indicator/NYGDPMKTPKDZ?source=27&format=json&mrv=6",
     "https://sdmx.oecd.org/public/rest/dataflow/OECD.ECO.MAD/DSD_EO@DF_EO/latest",
     "https://sdmx.oecd.org/public/rest/data/OECD.ECO.MAD,DSD_EO@DF_EO,/IDN+USA.GDPV_ANNPCT+CPI_YTYPCT.A?startPeriod=2024&format=csvfilewithlabels"]
for u in U:
    try:
        r = requests.get(u, timeout=60, headers=H if "oecd" not in u else {"User-Agent": "idx-quant-terminal/1.0"})
        t = r.text
        if "sources?format" in u:
            import json; j = r.json(); t = " ; ".join(f"{s['id']}:{s['name']}" for s in j[1])
        elif "indicators?" in u:
            j = r.json(); t = " ; ".join(f"{s['id']}:{s['name'][:40]}" for s in j[1])
        print("PRB|URL", r.status_code, len(r.content), u[:110], "|", t[:2500].replace("\n", " ⏎ "))
    except Exception as e:
        print("PRB|URL GAGAL", u, e)
