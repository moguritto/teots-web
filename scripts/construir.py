"""Genera la web final en docs/ a partir de contenido/ y la plantilla.

Uso:  python scripts/construir.py
OJO: sobrescribe las páginas de docs/ que estén en contenido/paginas.json.
Una vez terminada la migración, los textos se editan directamente en docs/.
"""
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, unquote

from jinja2 import Environment, FileSystemLoader

from comun import (CONTENIDO, DOCS, MARCA, RAIZ_REPO, config, descargar,
                   fichero_de_ruta, prefijo, ruta_de_url, slug_de_ruta)

BLOQUES = r"section|div|h1|h2|h3|h4|p|ul|ol|li|figure|details|summary|hr|table|tr|blockquote|nav|header|footer"


def formatear(html):
    """Pone cada bloque en su línea para que sea fácil de editar."""
    html = re.sub(rf"\s*(<(?:{BLOQUES})[\s>/])", r"\n\1", html)
    html = re.sub(rf"(</(?:{BLOQUES})>)\s*", r"\1\n", html)
    return re.sub(r"\n\s*\n+", "\n", html).strip()


class Enlazador:
    def __init__(self, cfg, rutas):
        self.dominios = {cfg["dominio"], "www." + cfg["dominio"]}
        self.rutas = set(rutas)

    def archivo(self, url):
        """PDF u otro documento subido a WordPress: se copia a docs/archivos/."""
        nombre = Path(unquote(urlparse(url).path)).name
        destino = DOCS / "archivos" / nombre
        if not destino.exists():
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(descargar(url, binario=True))
            except Exception:
                return None
        return f"archivos/{nombre}"

    def __call__(self, href, ruta_actual):
        if href.startswith(("mailto:", "tel:", "#", MARCA)) or not href:
            return href
        u = urlparse(href)
        if u.netloc and u.netloc not in self.dominios:
            return href
        destino = ruta_de_url(href)
        frag = ("#" + u.fragment) if u.fragment else ""
        if "/wp-content/uploads/" in u.path and not re.search(r"\.(jpe?g|png|webp|gif)$", u.path, re.I):
            rel = self.archivo(href if u.netloc else "https://" + next(iter(self.dominios)) + href)
            return prefijo(ruta_actual) + rel if rel else href
        if destino in self.rutas:
            if destino == ruta_actual and frag:
                return frag
            return (prefijo(ruta_actual) + destino or "./") + frag
        return href  # página no migrada: se queda apuntando a la web antigua (lo avisa comprobar.py)


def reescribir(html, ruta, enlazar):
    html = re.sub(r'href="([^"]*)"', lambda m: f'href="{enlazar(m.group(1), ruta)}"', html)
    return html.replace(MARCA, prefijo(ruta))


def main():
    cfg = config()
    indice = json.loads((CONTENIDO / "paginas.json").read_text(encoding="utf-8"))
    env = Environment(loader=FileSystemLoader(RAIZ_REPO / "scripts"), autoescape=False,
                      trim_blocks=True, lstrip_blocks=True)
    plantilla = env.get_template("plantilla.html")
    enlazar = Enlazador(cfg, indice.keys())
    pie_f = CONTENIDO / "_pie.html"
    pie = formatear(pie_f.read_text(encoding="utf-8")) if pie_f.exists() else ""

    def pagina(ruta, titulo, descripcion, contenido, tipo="normal", base_js=False):
        html = plantilla.render(cfg=cfg, R=MARCA, ruta=ruta, titulo=titulo, descripcion=descripcion,
                                contenido=contenido, pie=pie, tipo=tipo, base_js=base_js,
                                es_portada=(ruta == ""))
        return reescribir(html, ruta, enlazar) + "\n"

    for ruta, meta in indice.items():
        frag = (CONTENIDO / "paginas" / f"{slug_de_ruta(ruta)}.html").read_text(encoding="utf-8")
        f = fichero_de_ruta(ruta)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(pagina(ruta, meta["titulo"], meta["descripcion"], formatear(frag), meta.get("plantilla", "normal")),
                     encoding="utf-8")
        print("ok  /" + ruta)

    # 404: GitHub Pages la sirve en cualquier ruta, así que fija la base con un pequeño script
    texto404 = cfg.get("texto_404", '<section class="bloque"><div class="ancho"><h1>Página no encontrada</h1>'
                                   '<p>La página que buscas no existe o ha cambiado de sitio.</p>'
                                   '<p class="botones"><a class="boton" href="@RAIZ@/">Ir al inicio</a></p></div></section>')
    (DOCS / "404.html").write_text(pagina("", "Página no encontrada", "", formatear(texto404), base_js=True)
                                   .replace('href="./"', 'href=""'), encoding="utf-8")

    hoy = date.today().isoformat()
    urls = "\n".join(f"  <url><loc>https://{cfg['dominio']}/{r}</loc><lastmod>{hoy}</lastmod></url>" for r in indice)
    (DOCS / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                      '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                      f"{urls}\n</urlset>\n", encoding="utf-8")
    (DOCS / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: https://{cfg['dominio']}/sitemap.xml\n",
                                     encoding="utf-8")
    (DOCS / ".nojekyll").touch()
    print(f"{len(indice)} páginas + 404.html, sitemap.xml y robots.txt")


if __name__ == "__main__":
    main()
