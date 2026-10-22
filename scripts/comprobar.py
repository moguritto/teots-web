"""Busca enlaces rotos e imágenes que faltan en docs/.

Uso:  python scripts/comprobar.py            (solo enlaces internos)
      python scripts/comprobar.py --externos (también comprueba enlaces a otras webs; tarda más)
"""
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests

from comun import DOCS, UA, config

AJENOS_LEGALES = ("elarbolsuizo.com",)
DOMINIOS_ANTIGUOS = ("espacioteots.org", "apder.org", "teots.org", "ianivillage.com", "teotsai.com")


def main(externos=False):
    cfg = config()
    problemas, externos_vistos = [], {}
    for f in sorted(DOCS.rglob("*.html")):
        if f.name == "404.html":
            continue
        rel = f.relative_to(DOCS)
        html = f.read_text(encoding="utf-8")
        for attr, url in re.findall(r'(href|src)="([^"]*)"', html):
            if url.startswith(("mailto:", "tel:", "data:")):
                continue
            if url in ("", "#"):
                problemas.append((rel, "enlace vacío o '#'", url))
                continue
            if url.startswith("#"):
                if not re.search(rf'id="{re.escape(url[1:])}"', html):
                    problemas.append((rel, "ancla que no existe en la página", url))
                continue
            u = urlparse(url)
            if u.scheme in ("http", "https") or url.startswith("//"):
                host = u.netloc.removeprefix("www.")
                if any(d in host for d in AJENOS_LEGALES):
                    problemas.append((rel, "TEXTO LEGAL: apunta a un dominio ajeno", url))
                elif host == cfg["dominio"]:
                    problemas.append((rel, "apunta a la web antigua (página no migrada)", url))
                elif externos and "fonts.g" not in host:
                    if url not in externos_vistos:
                        try:
                            r = requests.head(url, headers=UA, timeout=20, allow_redirects=True)
                            if r.status_code in (405, 403):
                                r = requests.get(url, headers=UA, timeout=20, stream=True)
                            externos_vistos[url] = r.status_code
                        except requests.RequestException as e:
                            externos_vistos[url] = type(e).__name__
                    if externos_vistos[url] not in (200,):
                        problemas.append((rel, f"enlace externo responde {externos_vistos[url]}", url))
                continue
            destino = (f.parent / unquote(u.path)).resolve()
            if u.path.endswith("/") or u.path in ("", ".", "./") or destino.is_dir():
                destino = destino / "index.html"
            if not destino.exists():
                tipo = "imagen que falta" if attr == "src" else "enlace roto"
                problemas.append((rel, tipo, url))
    if not problemas:
        print("Sin problemas.")
    for rel, tipo, url in problemas:
        print(f"{rel}: {tipo}: {url}")
    return len(problemas)


if __name__ == "__main__":
    sys.exit(1 if main("--externos" in sys.argv) else 0)
