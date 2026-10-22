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
        # "enlaces" en web.json: dirección antigua -> nueva dirección, o null para quitar el enlace
        self.cambios = {}
        for k, v in cfg.get("enlaces", {}).items():
            clave = ruta_de_url(k) if k.startswith(("http", "/")) else k
            if "#" in k:
                clave += "#" + k.split("#", 1)[1]
            self.cambios[clave] = v
        # "redirecciones" en web.json: dirección antigua -> página migrada (se crean páginas que redirigen)
        self.alias_fijos = {ruta_de_url(k): ruta_de_url(v) for k, v in cfg.get("redirecciones", {}).items()}
        self.alias_usados = dict(self.alias_fijos)

    def buscar_alias(self, destino):
        """Dirección antigua -> página migrada con el mismo final (p. ej. es/soul/ -> recursos/peliculas/soul/)."""
        if destino in self.alias_fijos:
            return self.alias_fijos[destino]
        ultimo = destino.strip("/").split("/")[-1].lower()
        if not ultimo or ultimo in ("es", "en", "gl"):
            return None
        exactos = [r for r in self.rutas if r.strip("/").split("/")[-1].lower() == ultimo]
        if len(exactos) == 1:
            return exactos[0]
        prefijos = [r for r in self.rutas if r.strip("/").split("/")[-1].lower().startswith(ultimo + "-")]
        return prefijos[0] if len(prefijos) == 1 else None

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
        if href.strip() in ("", "#"):
            return None  # enlace vacío: se deja solo el texto
        if href.startswith(("mailto:", "tel:", "#", MARCA)) or not href:
            return href
        u = urlparse(href)
        if u.netloc and u.netloc not in self.dominios:
            return href
        destino = ruta_de_url(href)
        frag = ("#" + u.fragment) if u.fragment else ""
        clave = destino + frag if destino + frag in self.cambios else destino
        if clave in self.cambios:
            nuevo = self.cambios[clave]
            if nuevo is None:
                return None
            if nuevo != href:
                if frag and "#" not in nuevo and clave == destino:
                    nuevo += frag
                return self(nuevo, ruta_actual)
        if "/wp-content/uploads/" in u.path and not re.search(r"\.(jpe?g|png|webp|gif)$", u.path, re.I):
            rel = self.archivo(href if u.netloc else "https://" + next(iter(self.dominios)) + href)
            return prefijo(ruta_actual) + rel if rel else href
        if "/wp-content/uploads/" in u.path:
            from comun import guardar_imagen
            rel = guardar_imagen(href if u.netloc else "https://" + next(iter(self.dominios)) + href, href)
            if rel:
                return prefijo(ruta_actual) + rel
        if destino in self.rutas:
            if destino == ruta_actual and frag:
                return frag
            return (prefijo(ruta_actual) + destino or "./") + frag
        alias = self.buscar_alias(destino)
        if alias:
            self.alias_usados[destino] = alias
            return prefijo(ruta_actual) + alias or "./"
        return href  # página no migrada: se queda apuntando a la web antigua (lo avisa comprobar.py)


def reescribir(html, ruta, enlazar):
    def cambiar(m):
        nuevo = enlazar(m.group(2), ruta)
        return m.group(1) + (f' href="{nuevo}"' if nuevo is not None else ' data-sin-enlace=""')
    html = re.sub(r'(<a\b[^>]*?)\s+href="([^"]*)"', cambiar, html)
    # enlaces quitados: <a data-sin-enlace>texto</a> -> texto
    html = re.sub(r'<a\b[^>]*data-sin-enlace=""[^>]*>(.*?)</a>', r"\1", html, flags=re.S)
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

    pies = {f.stem[5:]: formatear(f.read_text(encoding="utf-8")) for f in CONTENIDO.glob("_pie-*.html")}

    def pagina(ruta, titulo, descripcion, contenido, tipo="normal", base_js=False, cab=None, pie_id=None):
        c = dict(cfg)
        c.update({k: v for k, v in cfg.get("cabeceras", {}).get(cab or cfg.get("cabecera_principal", ""), {}).items() if v})
        html = plantilla.render(cfg=c, R=MARCA, pie=pies.get(pie_id or cfg.get("pie_principal", ""), pie), ruta=ruta, titulo=titulo, descripcion=descripcion,
                                contenido=contenido, tipo=tipo, base_js=base_js,
                                es_portada=(ruta == ""))
        for vieja, nueva in cfg.get("sustituir_fuentes", {}).items():
            html = html.replace(vieja, nueva)
        return reescribir(html, ruta, enlazar) + "\n"

    for ruta, meta in indice.items():
        frag = (CONTENIDO / "paginas" / f"{slug_de_ruta(ruta)}.html").read_text(encoding="utf-8")
        f = fichero_de_ruta(ruta)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(pagina(ruta, meta["titulo"], meta["descripcion"], formatear(frag), meta.get("plantilla", "normal"),
                            cab=meta.get("cabecera"), pie_id=meta.get("pie")),
                     encoding="utf-8")
        print("ok  /" + ruta)

    # 404: GitHub Pages la sirve en cualquier ruta, así que fija la base con un pequeño script
    texto404 = cfg.get("texto_404", '<section class="bloque"><div class="ancho"><h1>Página no encontrada</h1>'
                                   '<p>La página que buscas no existe o ha cambiado de sitio.</p>'
                                   '<p class="botones"><a class="boton" href="@RAIZ@/./">Ir al inicio</a></p></div></section>')
    (DOCS / "404.html").write_text(pagina("", cfg.get("titulo_404", "Página no encontrada"), "", formatear(texto404), base_js=True)
                                   , encoding="utf-8")

    # páginas de redirección para direcciones antiguas
    for viejo, nuevo in sorted(enlazar.alias_usados.items()):
        f = fichero_de_ruta(viejo)
        if viejo in indice or (f.exists() and "data-redireccion" not in f.read_text(encoding="utf-8")):
            continue
        destino = prefijo(viejo) + nuevo
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f'<!DOCTYPE html>\n<html lang="{cfg["idioma"]}" data-redireccion>\n<head>\n<meta charset="utf-8">\n'
                     f'<title>Redirigiendo…</title>\n<link rel="canonical" href="https://{cfg["dominio"]}/{nuevo}">\n'
                     f'<meta http-equiv="refresh" content="0; url={destino}">\n<meta name="robots" content="noindex">\n</head>\n'
                     f'<body><p><a href="{destino}">{cfg["dominio"]}/{nuevo}</a></p></body>\n</html>\n', encoding="utf-8")
    if enlazar.alias_usados:
        print(f"{len(enlazar.alias_usados)} páginas de redirección")

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
