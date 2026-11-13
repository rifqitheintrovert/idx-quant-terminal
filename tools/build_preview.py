"""Bangun satu file HTML mandiri (CSS, JS, library chart, dan data di-inline) untuk pratinjau/offline.

    python tools/build_preview.py [--out dist/preview.html]
"""
import argparse
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist" / "preview.html"))
    a = ap.parse_args()
    html = (SITE / "index.html").read_text(encoding="utf-8")
    css = (SITE / "style.css").read_text(encoding="utf-8")
    js = (SITE / "app.js").read_text(encoding="utf-8")
    lib = (SITE / "vendor" / "lightweight-charts.standalone.production.js").read_text(encoding="utf-8")
    data = json.loads((SITE / "data" / "latest.json").read_text(encoding="utf-8"))
    icon = base64.b64encode((SITE / "icons" / "icon-192.png").read_bytes()).decode()
    data_js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    html = html.replace('<link rel="manifest" href="manifest.webmanifest">\n', "")
    html = html.replace('href="icons/icon-192.png"', f'href="data:image/png;base64,{icon}"')
    html = html.replace('<link rel="stylesheet" href="style.css">', f"<style>\n{css}\n</style>")
    html = html.replace("<script>window.__DATA__ = null;</script>", f"<script>window.__DATA__ = {data_js};</script>")
    html = html.replace('<script src="vendor/lightweight-charts.standalone.production.js"></script>', f"<script>{lib}</script>")
    html = html.replace('<script src="app.js"></script>', f"<script>\n{js}\n</script>")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"OK {out} ({out.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
