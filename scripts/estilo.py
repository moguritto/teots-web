"""Crea docs/estilo.css: variables de la web + base común + iconos.
Uso: python scripts/estilo.py   (no sobrescribe si ya existe; --forzar para rehacerlo)
Los valores salen de "estilo" en scripts/web.json y del kit de Elementor."""
import re
import sys
from pathlib import Path

from comun import DOCS, BeautifulSoup, config, descargar

AQUI = Path(__file__).resolve().parent


def main(forzar=False):
    cfg = config()
    destino = DOCS / "estilo.css"
    if destino.exists() and not forzar:
        print("docs/estilo.css ya existe (usa --forzar para rehacerlo)")
        return
    soup = BeautifulSoup(descargar(f"https://{cfg['dominio']}/"), "html.parser")
    kit = [c for c in soup.body.get("class", []) if c.startswith("elementor-kit-")]
    globales = ""
    if kit:
        css = descargar(f"https://{cfg['dominio']}/wp-content/uploads/elementor/css/post-{kit[0].split('-')[-1]}.css")
        vistos = {}
        for k, v in re.findall(r"(--e-global-color-[\w-]+):([^;}]+)", css):
            vistos.setdefault(k, v)
        globales = "".join(f"  {k}: {v};\n" for k, v in vistos.items())
    propias = "".join(f"  --{k}: {v};\n" for k, v in cfg.get("estilo", {}).items())
    texto = (f"/* =========================================================\n"
             f"   ESTILO DE {cfg['nombre'].upper()}\n"
             f"   Para cambiar colores o letras, toca solo este primer bloque.\n"
             f"   ========================================================= */\n"
             f":root {{\n  /* Colores del kit de Elementor de la web original */\n{globales}\n"
             f"  /* Colores y letras que usa esta web */\n{propias}}}\n\n"
             + (AQUI / "base.css").read_text(encoding="utf-8") + "\n"
             + (AQUI / "iconos.css").read_text(encoding="utf-8")
             + f"\n\n/* ===== Propio de {cfg['nombre']} ===== */\n" + cfg.get("css_extra", ""))
    for vieja, nueva in cfg.get("sustituir_fuentes", {}).items():
        texto = texto.replace(vieja, nueva)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    print("docs/estilo.css creado")


if __name__ == "__main__":
    main("--forzar" in sys.argv)
