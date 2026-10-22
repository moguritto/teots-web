"""Extrae páginas de la web original y guarda su contenido limpio en contenido/.

Uso:
  python scripts/extraer.py https://dominio/pagina/ [otra URL ...]
  python scripts/extraer.py --lista contenido/seleccion.txt
  python scripts/extraer.py --pie https://dominio/pagina-con-pie/
  python scripts/extraer.py --sola https://dominio/   (página sin cabecera ni pie)
"""
import json
import re
import sys

from comun import CONTENIDO, config, convertir, ruta_de_url, slug_de_ruta


def main(args):
    cfg = config()
    indice_f = CONTENIDO / "paginas.json"
    indice = json.loads(indice_f.read_text(encoding="utf-8")) if indice_f.exists() else {}
    (CONTENIDO / "paginas").mkdir(parents=True, exist_ok=True)
    plantilla = "normal"
    urls = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--lista":
            urls += [l.split("\t")[-1].strip() for l in open(args[i + 1], encoding="utf-8") if l.strip() and not l.startswith("#")]
            i += 1
        elif a == "--pie":
            t, d, html, av = convertir(args[i + 1], zona_css=".elementor-location-footer", cfg=cfg)
            html = re.sub(r'<h2 style="color:#0+">.*?</h2>', "", html)          # separadores invisibles
            html = re.sub(r"<(/?)h[1-4]([ >])", r"<\1p\2", html)              # en el pie, sin títulos
            (CONTENIDO / "_pie.html").write_text(html + "\n", encoding="utf-8")
            print("pie guardado en contenido/_pie.html", av)
            i += 1
        elif a == "--sola":
            plantilla = "sola"
        else:
            urls.append(a)
        i += 1
    for url in urls:
        ruta = ruta_de_url(url)
        titulo, desc, html, avisos = convertir(url, cfg=cfg)
        slug = slug_de_ruta(ruta)
        (CONTENIDO / "paginas" / f"{slug}.html").write_text(html + "\n", encoding="utf-8")
        previa = indice.get(ruta, {})
        indice[ruta] = {"titulo": titulo, "descripcion": desc, "origen": url,
                        "plantilla": previa.get("plantilla", plantilla) if plantilla == "normal" else plantilla,
                        "avisos": avisos}
        print(f"/{ruta}  ->  {titulo!r}  ({len(html)} caracteres)" + (f"  avisos: {avisos}" if avisos else ""))
    indice_f.write_text(json.dumps(indice, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
