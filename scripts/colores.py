"""Resume colores y letras de cabecera y pie de Elementor (ayuda para escribir estilo.css).
Uso: python scripts/colores.py URL"""
import sys
from comun import BeautifulSoup, css_de_pagina, descargar, estilo_de

u = sys.argv[1]
s = BeautifulSoup(descargar(u), "html.parser")
r = css_de_pagina(s, u)
for loc in ("header", "footer"):
    e = s.select_one(f".elementor-location-{loc}")
    if not e:
        continue
    print("==", loc)
    for x in [e] + e.select("[data-id]"):
        i = x.get("data-id")
        st = {}
        for interior in ("", " .elementor-heading-title", " .elementor-nav-menu--main .elementor-item", " .elementor-button",
                         " .elementor-nav-menu--dropdown a", " .elementor-social-icon", " .elementor-icon"):
            st.update({(interior.strip() or "el") + ":" + k: v for k, v in estilo_de(r, i, interior).items()})
        if st:
            print(" ", i, (x.get("data-widget_type") or " ".join(x.get("class", [])[:2])), st)
