"""Herramientas comunes para pasar una web WordPress+Elementor a HTML estático.

Se usa desde extraer.py, construir.py y comprobar.py. No hace falta tocarlo
para editar textos: los textos están en docs/.
"""
import hashlib
import io
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup, NavigableString, Comment, Tag
from PIL import Image

RAIZ_REPO = Path(__file__).resolve().parent.parent
DOCS = RAIZ_REPO / "docs"
CONTENIDO = RAIZ_REPO / "contenido"
CACHE = RAIZ_REPO / "scripts" / ".cache"
MARCA = "@RAIZ@/"   # se sustituye por ../../ etc. al construir
ANCHO_MAX = 1600
UA = {"User-Agent": "Mozilla/5.0 (migracion estatica)"}


def config():
    return json.loads((RAIZ_REPO / "scripts" / "web.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- descargas
def descargar(url, binario=False):
    """Descarga con caché local (scripts/.cache)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / hashlib.sha1(url.encode()).hexdigest()
    if f.exists():
        datos = f.read_bytes()
    else:
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
        datos = r.content
        f.write_bytes(datos)
    return datos if binario else datos.decode("utf-8", "replace")


def existe(url):
    try:
        return requests.head(url, headers=UA, timeout=30, allow_redirects=True).status_code == 200
    except requests.RequestException:
        return False


# ---------------------------------------------------------------- rutas
def ruta_de_url(url):
    """'https://x.org/a/b' -> 'a/b/'  ;  portada -> ''"""
    p = unquote(urlparse(url).path).strip("/")
    return p + "/" if p else ""


def fichero_de_ruta(ruta):
    return DOCS / ruta / "index.html"


def slug_de_ruta(ruta):
    return ruta.strip("/").replace("/", "__") or "inicio"


def prefijo(ruta):
    """Cuántos '../' hacen falta para volver a docs/ desde esta página."""
    return "../" * ruta.count("/")


# ---------------------------------------------------------------- imágenes
def nombre_limpio(texto):
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto.lower()).strip("-")
    return texto[:60] or "img"


def url_original(src):
    """Quita el sufijo de tamaño de WordPress (-1024x683) si el original existe."""
    sin = re.sub(r"-\d+x\d+(?=\.\w+$)", "", src)
    if sin != src and existe(sin):
        return sin
    return src


def guardar_imagen(src, base_url):
    """Descarga una imagen, la pasa a WebP (máx. 1600 px) y devuelve 'img/nombre.webp'."""
    if not src or src.startswith("data:"):
        return None
    src = urljoin(base_url, src.strip())
    mapa_f = CONTENIDO / "imagenes.json"
    mapa = json.loads(mapa_f.read_text()) if mapa_f.exists() else {}
    if src in mapa:
        return mapa[src]
    real = url_original(src)
    try:
        datos = descargar(real, binario=True)
    except requests.RequestException:
        try:
            datos = descargar(src, binario=True)
        except requests.RequestException:
            print("   ! imagen no descargable:", src)
            return None
    base, ext = Path(unquote(urlparse(real).path)).stem, Path(urlparse(real).path).suffix.lower()
    nombre = nombre_limpio(base)
    carpeta = DOCS / "img"
    carpeta.mkdir(parents=True, exist_ok=True)
    if ext in (".svg", ".gif", ".ico"):
        destino = f"{nombre}{ext}"
        (carpeta / destino).write_bytes(datos)
    else:
        destino = f"{nombre}.webp"
        if (carpeta / destino).exists() and destino in mapa.values():
            destino = f"{nombre}-{hashlib.sha1(real.encode()).hexdigest()[:6]}.webp"
        im = Image.open(io.BytesIO(datos))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA")
        im.thumbnail((ANCHO_MAX, ANCHO_MAX))
        im.save(carpeta / destino, "WEBP", quality=82, method=6)
    rel = f"img/{destino}"
    mapa[src] = rel
    mapa_f.parent.mkdir(parents=True, exist_ok=True)
    mapa_f.write_text(json.dumps(mapa, indent=1, ensure_ascii=False))
    return rel


def guardar_archivo(url):
    """Copia un archivo (vídeo, PDF...) a docs/archivos/ y devuelve 'archivos/nombre'."""
    nombre = Path(unquote(urlparse(url).path)).name
    destino = DOCS / "archivos" / nombre
    if not destino.exists():
        try:
            datos = descargar(url, binario=True)
        except requests.RequestException:
            print("   ! archivo no descargable:", url)
            return None
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
    return f"archivos/{nombre}"


def guardar_icono(url, nombre="favicon.png", lado=192):
    """Favicon en PNG cuadrado (los navegadores lo aceptan siempre)."""
    im = Image.open(io.BytesIO(descargar(url, binario=True))).convert("RGBA")
    im.thumbnail((lado, lado))
    (DOCS / "img").mkdir(parents=True, exist_ok=True)
    im.save(DOCS / "img" / nombre)
    return f"img/{nombre}"


def mejor_src(img):
    for attr in ("data-src", "data-lazy-src", "data-orig-file", "src"):
        v = img.get(attr)
        if v and not v.startswith("data:"):
            return v
    srcset = img.get("srcset") or img.get("data-srcset")
    if srcset:
        return srcset.split(",")[-1].strip().split(" ")[0]
    return None


# ---------------------------------------------------------------- CSS de Elementor
def reglas_css(texto):
    """Devuelve [(selector, declaraciones)] de las reglas fuera de @media."""
    texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    reglas, i, prof, inicio_sel, en_media = [], 0, 0, 0, 0
    while i < len(texto):
        c = texto[i]
        if c == "{":
            sel = texto[inicio_sel:i].strip()
            if sel.startswith("@"):
                prof += 1
                en_media += 1
                inicio_sel = i + 1
            else:
                fin = texto.index("}", i)
                if en_media == 0:
                    reglas.append((sel, texto[i + 1:fin]))
                i = fin
                inicio_sel = i + 1
        elif c == "}":
            prof -= 1
            en_media = max(0, en_media - 1)
            inicio_sel = i + 1
        i += 1
    return reglas


def css_de_pagina(soup, base_url):
    textos = []
    for l in soup.find_all("link", rel="stylesheet"):
        h = l.get("href", "")
        if "/elementor/css/post-" in h or "/elementor/css/global" in h:
            try:
                textos.append(descargar(urljoin(base_url, h)))
            except requests.RequestException:
                pass
    for st in soup.find_all("style"):
        textos.append(st.get_text())
    return reglas_css("\n".join(textos))


PROPIEDADES = ("background-color", "background-image", "color", "text-align", "font-family", "font-size",
               "font-weight", "font-style", "text-transform", "letter-spacing", "line-height",
               "min-height", "--min-height", "width", "max-width")


def estilo_de(reglas, el_id, interior=""):
    """Estilos simples (fondo, color, alineación) de un elemento de Elementor."""
    if not el_id:
        return {}
    res = {}
    patron = re.compile(r"\.elementor-element-" + re.escape(el_id) + r"(?![\w-])(?::not\([^)]*\))?" + re.escape(interior) + r"\s*$")
    for sel, decl in reglas:
        for parte in sel.split(","):
            parte = parte.strip()
            if ":hover" in parte or ("::" in parte and "::" not in interior) or not patron.search(parte):
                continue
            for d in decl.split(";"):
                if ":" in d:
                    k, v = d.split(":", 1)
                    k, v = k.strip(), v.strip()
                    if k in PROPIEDADES and v and "!important" not in v:
                        res[k] = v
    return res


# ---------------------------------------------------------------- limpieza
PERMITIDAS = {"h1", "h2", "h3", "h4", "p", "ul", "ol", "li", "a", "strong", "em", "br",
              "img", "iframe", "blockquote", "figure", "figcaption", "hr", "table",
              "thead", "tbody", "tr", "th", "td", "details", "summary", "u", "sup", "sub"}
RENOMBRAR = {"b": "strong", "i": "em", "h5": "h4", "h6": "h4"}
DESCARTAR = {"script", "style", "noscript", "svg", "form", "input", "select", "textarea",
             "button", "nav", "link", "meta", "template", "canvas", "object"}
BLOQUE = {"h1", "h2", "h3", "h4", "p", "ul", "ol", "blockquote", "figure", "hr", "table",
          "iframe", "details", "div", "section"}
VIDEO = re.compile(r"(youtube\.com|youtube-nocookie\.com|youtu\.be|vimeo\.com|google\.com/maps|maps\.google)")


def oculto_en_escritorio(el):
    return isinstance(el, Tag) and "elementor-hidden-desktop" in (el.get("class") or [])


def es_icono(el):
    cl = " ".join(el.get("class") or [])
    return bool(re.search(r"\b(fa[srbl]?|fa-[\w-]+|eicon[\w-]*|e-font-icon[\w-]*)\b", cl))


class Limpiador:
    def __init__(self, base_url, reglas=None, contacto=None):
        self.base = base_url
        self.reglas = reglas or []
        self.contacto = contacto or {}
        self.out = BeautifulSoup("", "html.parser")
        self.avisos = []

    # -- utilidades
    def nuevo(self, nombre, **attrs):
        t = self.out.new_tag(nombre)
        for k, v in attrs.items():
            if v is not None:
                t[k.rstrip("_")] = v
        return t

    def html(self, nodos):
        return "\n".join(str(n) for n in nodos if n is not None and str(n).strip())

    def imagen(self, img, alt=None):
        rel = guardar_imagen(mejor_src(img), self.base)
        if not rel:
            return None
        t = self.nuevo("img", src=MARCA + rel, alt=alt if alt is not None else (img.get("alt") or ""))
        t["loading"] = "lazy"
        return t

    def iframe(self, src):
        if not src or not VIDEO.search(src):
            return None
        envol = self.nuevo("div", class_="video")
        envol.append(self.nuevo("iframe", src=src, loading="lazy", allowfullscreen="",
                                title="Vídeo" if "map" not in src else "Mapa"))
        return envol

    def bloque_contacto(self):
        d = self.nuevo("div", class_="contacto-directo")
        p = self.nuevo("p")
        p.string = self.contacto.get("texto", "Escríbenos directamente:")
        d.append(p)
        if self.contacto.get("whatsapp"):
            a = self.nuevo("a", href="https://wa.me/" + self.contacto["whatsapp"].lstrip("+"), class_="boton")
            a.string = "WhatsApp"
            d.append(a)
        if self.contacto.get("email"):
            a = self.nuevo("a", href="mailto:" + self.contacto["email"], class_="boton boton-secundario")
            a.string = self.contacto["email"]
            d.append(a)
        return d

    # -- limpieza genérica de un fragmento HTML
    def limpiar_hijos(self, el, destino):
        for c in list(el.children):
            if isinstance(c, Comment):
                continue
            if isinstance(c, NavigableString):
                txt = re.sub(r"\s+", " ", str(c))
                if txt.strip() or (txt == " " and destino.contents):
                    destino.append(txt)
                continue
            if not isinstance(c, Tag) or oculto_en_escritorio(c):
                continue
            nombre = RENOMBRAR.get(c.name, c.name)
            if c.name in DESCARTAR:
                if c.name == "form":
                    destino.append(self.bloque_contacto())
                continue
            if c.name in ("i", "span") and es_icono(c):
                continue
            if "elementor-screen-only" in (c.get("class") or []):
                continue
            if nombre == "img" and ("emoji" in (c.get("class") or []) or "s.w.org/images/core/emoji" in (c.get("src") or "")):
                destino.append(c.get("alt") or "")
                continue
            if nombre == "img":
                t = self.imagen(c)
                if t:
                    destino.append(t)
                continue
            if nombre == "iframe":
                t = self.iframe(c.get("src") or c.get("data-src") or c.get("data-lazy-src"))
                if t:
                    destino.append(t)
                continue
            if nombre == "p":
                grande = [int(float(x)) for x in re.findall(r"font-size:\s*([\d.]+)px", str(c))]
                if grande and min(grande) >= 22 and len(c.get_text(strip=True)) < 120:
                    nombre = "h2" if min(grande) >= 28 else "h3"
            if nombre in PERMITIDAS:
                attrs = {}
                if nombre == "a":
                    href = (c.get("href") or "").strip()
                    if re.fullmatch(r"\+?\d[\d\s]{6,}", href):
                        href = "tel:" + href.replace(" ", "")
                    if href and not href.startswith(("javascript:",)):
                        attrs["href"] = urljoin(self.base, href) if not href.startswith(("#", "mailto:", "tel:")) else href
                    if c.get("target") == "_blank":
                        attrs["target"] = "_blank"
                        attrs["rel"] = "noopener"
                if nombre in ("td", "th") and c.get("colspan"):
                    attrs["colspan"] = c["colspan"]
                t = self.nuevo(nombre, **attrs)
                self.limpiar_hijos(c, t)
                destino.append(t)
            elif c.name in ("div", "section", "article") and destino.name not in ("p", "li", "h1", "h2", "h3", "h4", "a", "strong", "em", "summary", "td", "th", "figcaption") \
                    and not c.find(["p", "div", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "figure", "iframe", "section"]):
                # <div> que solo tiene texto: es un párrafo
                if c.get_text(strip=True) or c.find("img"):
                    grande = [int(float(x)) for x in re.findall(r"font-size:\s*([\d.]+)px", str(c))]
                    t = self.nuevo("p")
                    if grande and min(grande) >= 22 and len(c.get_text(strip=True)) < 120:
                        t = self.nuevo("h2" if min(grande) >= 28 else "h3")
                    self.limpiar_hijos(c, t)
                    destino.append(t)
            else:
                # div, span, etc.: se quedan solo sus hijos
                if c.name in ("div", "section", "article") and destino.contents:
                    destino.append(" ")
                self.limpiar_hijos(c, destino)

    def limpiar(self, el):
        cont = self.nuevo("div")
        self.limpiar_hijos(el, cont)
        self.ordenar(cont)
        return list(cont.children)

    def ordenar(self, cont):
        """Mete texto suelto en <p> y quita etiquetas vacías."""
        for _ in range(3):
            for t in cont.find_all(["p", "strong", "em", "li", "h1", "h2", "h3", "h4", "a", "u", "span", "blockquote"]):
                if not t.get_text(strip=True) and not t.find(["img", "iframe", "br"]):
                    t.decompose()
        # p dentro de p no es válido: desenvolver
        for p in cont.find_all("p"):
            if p.find(["p", "ul", "ol", "h1", "h2", "h3", "h4", "div", "figure", "blockquote", "table"]):
                p.unwrap()
        suelto = []

        def volcar():
            if suelto and "".join(str(x) for x in suelto).strip():
                p = self.nuevo("p")
                suelto[0].insert_before(p)
                for x in suelto:
                    p.append(x.extract())
            suelto.clear()

        for c in list(cont.children):
            if isinstance(c, Tag) and c.name in BLOQUE:
                volcar()
            else:
                suelto.append(c)
        volcar()
        for br in cont.find_all("br"):
            # <br> al principio o final de un párrafo sobra
            if br.parent and br.parent.name == "p" and (br is br.parent.contents[0] or br is br.parent.contents[-1]):
                br.decompose()

    # -- widgets de Elementor
    def widget(self, w):
        tipo = (w.get("data-widget_type") or "").split(".")[0]
        cuerpo = w.select_one(":scope > .elementor-widget-container") or w
        estilo = estilo_de(self.reglas, w.get("data-id"))
        estilo_t = estilo_de(self.reglas, w.get("data-id"), " .elementor-heading-title")
        nodos = []

        if tipo == "heading":
            tit = cuerpo.select_one(".elementor-heading-title") or cuerpo
            tag = RENOMBRAR.get(tit.name, tit.name)
            if tag not in ("h1", "h2", "h3", "h4"):
                tag = "p"
            t = self.nuevo(tag)
            self.limpiar_hijos(tit, t)
            st = {**{k: v for k, v in estilo.items() if k in ("text-align", "color")},
                  **{k: v for k, v in estilo_t.items() if k not in ("width", "max-width")}}
            self.aplicar_estilo(t, {k: v for k, v in st.items() if "min-height" not in k})
            nodos = [t]
        elif tipo == "text-editor":
            nodos = self.limpiar(cuerpo)
            estilo = {k: v for k, v in estilo.items() if k in ("color", "text-align", "font-style", "font-family",
                                                              "font-size", "font-weight", "line-height")}
            if estilo:
                envol = self.nuevo("div")
                for n in nodos:
                    envol.append(n)
                self.aplicar_estilo(envol, estilo)
                nodos = [envol]
        elif tipo in ("image", "theme-site-logo", "site-logo"):
            img = cuerpo.find("img")
            if img:
                t = self.imagen(img)
                ei = estilo_de(self.reglas, w.get("data-id"), " img")
                ei = {k: v for k, v in ei.items() if k in ("width", "max-width") and "%" in v or k == "max-width"}
                if t is not None and ei:
                    self.aplicar_estilo(t, ei)
                a = img.find_parent("a")
                if t is not None and a and a.get("href") and not a["href"].startswith("#"):
                    enl = self.nuevo("a", href=urljoin(self.base, a["href"]))
                    enl.append(t)
                    t = enl
                cap = cuerpo.find("figcaption")
                if t is not None and cap and cap.get_text(strip=True):
                    fig = self.nuevo("figure")
                    fig.append(t)
                    fc = self.nuevo("figcaption")
                    fc.string = cap.get_text(" ", strip=True)
                    fig.append(fc)
                    t = fig
                if t is not None:
                    envol = self.nuevo("p", class_="imagen")
                    envol.append(t)
                    self.aplicar_estilo(envol, {k: v for k, v in estilo.items() if k == "text-align"})
                    nodos = [envol]
        elif tipo == "button":
            a = cuerpo.find("a") or cuerpo.find("button")
            texto = cuerpo.get_text(" ", strip=True)
            if texto:
                href = a.get("href") if a else None
                b = self.nuevo("a", class_="boton", href=urljoin(self.base, href) if href and not href.startswith(("#", "mailto:", "tel:")) else (href or "#"))
                if a and a.get("target") == "_blank":
                    b["target"] = "_blank"
                    b["rel"] = "noopener"
                b.string = texto
                eb = estilo_de(self.reglas, w.get("data-id"), " .elementor-button")
                eb = {k: v for k, v in eb.items() if k in ("background-color", "color")}
                if eb:
                    self.aplicar_estilo(b, eb)
                p = self.nuevo("p", class_="botones")
                p.append(b)
                self.aplicar_estilo(p, {k: v for k, v in estilo.items() if k == "text-align"})
                nodos = [p]
        elif tipo in ("video", "video-playlist"):
            try:
                ajustes = json.loads(w.get("data-settings") or "{}")
            except ValueError:
                ajustes = {}
            url = ajustes.get("youtube_url") or ajustes.get("vimeo_url") or ""
            src = None
            m = re.search(r"(?:v=|youtu\.be/|embed/|shorts/)([\w-]{11})", url)
            if m:
                src = f"https://www.youtube-nocookie.com/embed/{m.group(1)}"
            m2 = re.search(r"vimeo\.com/(\d+)", url)
            if m2:
                src = f"https://player.vimeo.com/video/{m2.group(1)}"
            if not src:
                f = cuerpo.find("iframe")
                src = f and (f.get("src") or f.get("data-src") or f.get("data-lazy-load"))
            nodos = [self.iframe(src)] if src else []
        elif tipo in ("social-icons",):
            ul = self.nuevo("ul", class_="redes")
            for a in cuerpo.find_all("a"):
                nombre = a.get_text(" ", strip=True) or (a.get("aria-label") or "")
                nombre = nombre.replace("-f", "").replace("-in", "").replace("X-twitter", "X").strip()
                if not a.get("href"):
                    continue
                li = self.nuevo("li")
                enl = self.nuevo("a", href=a["href"], target="_blank", rel="noopener")
                enl.string = nombre or a["href"]
                li.append(enl)
                ul.append(li)
            nodos = [ul] if ul.contents else []
        elif tipo == "icon-list":
            ul = self.nuevo("ul", class_="lista-iconos")
            for item in cuerpo.select(".elementor-icon-list-item"):
                li = self.nuevo("li")
                a = item.find("a")
                texto = item.get_text(" ", strip=True)
                if not texto:
                    continue
                if a and a.get("href"):
                    enl = self.nuevo("a", href=urljoin(self.base, a["href"]))
                    enl.string = texto
                    li.append(enl)
                else:
                    li.string = texto
                ul.append(li)
            nodos = [ul] if ul.contents else []
        elif tipo in ("icon-box", "image-box", "call-to-action", "flip-box"):
            caja = self.nuevo("div", class_="caja")
            img = cuerpo.find("img")
            if img:
                t = self.imagen(img)
                if t:
                    caja.append(t)
            tit = cuerpo.select_one("[class*=title]")
            if tit and tit.get_text(strip=True):
                h = self.nuevo("h3")
                a = tit.find("a") or (tit.find_parent("a"))
                if a and a.get("href"):
                    enl = self.nuevo("a", href=urljoin(self.base, a["href"]))
                    enl.string = tit.get_text(" ", strip=True)
                    h.append(enl)
                else:
                    h.string = tit.get_text(" ", strip=True)
                caja.append(h)
            desc = cuerpo.select_one("[class*=description]")
            if desc:
                for n in self.limpiar(desc):
                    caja.append(n)
            bot = cuerpo.select_one("a[class*=button]")
            if bot and bot.get_text(strip=True):
                b = self.nuevo("a", class_="boton", href=urljoin(self.base, bot.get("href") or "#"))
                b.string = bot.get_text(" ", strip=True)
                caja.append(b)
            nodos = [caja] if caja.contents else []
        elif tipo == "wpr-team-member":
            caja = self.nuevo("div", class_="caja tarjeta")
            img = cuerpo.find("img")
            if img and self.imagen(img) is not None:
                caja.append(self.imagen(img))
            for clase, etiqueta in (("wpr-member-name", "h3"), ("wpr-member-job", "p")):
                e = cuerpo.select_one("." + clase)
                if e and e.get_text(strip=True):
                    t = self.nuevo(etiqueta, class_="cargo" if etiqueta == "p" else None)
                    t.string = e.get_text(" ", strip=True)
                    caja.append(t)
            desc = cuerpo.select_one(".wpr-member-description")
            if desc:
                for n in self.limpiar(desc):
                    caja.append(n)
            redes = self.nuevo("ul", class_="redes")
            for a in cuerpo.select(".wpr-member-social-media a, .wpr-member-social a"):
                if a.get("href"):
                    li = self.nuevo("li")
                    enl = self.nuevo("a", href=a["href"] if not re.fullmatch(r"\+?\d[\d\s]{6,}", a["href"]) else "tel:" + a["href"].replace(" ", ""),
                                     target="_blank", rel="noopener")
                    enl.string = a.get_text(" ", strip=True) or a["href"]
                    li.append(enl)
                    redes.append(li)
            if redes.contents:
                caja.append(redes)
            nodos = [caja]
        elif tipo == "wpr-promo-box":
            caja = self.nuevo("div", class_="promo")
            fondo = cuerpo.select_one(".wpr-promo-box-bg-image")
            m = re.search(r"url\(['\"]?([^'\")]+)", (fondo.get("style") or "") if fondo else "")
            if m:
                self.aplicar_estilo(caja, {"background-image": f"url({m.group(1)})"})
            interior = self.nuevo("div", class_="promo-texto")
            caja.append(interior)
            tit = cuerpo.select_one(".wpr-promo-box-title")
            if tit and tit.get_text(strip=True):
                h = self.nuevo("h3")
                h.string = tit.get_text(" ", strip=True).replace("\u200b", "")
                interior.append(h)
            desc = cuerpo.select_one(".wpr-promo-box-description")
            if desc:
                for n in self.limpiar(desc):
                    if n.name in ("h1", "h2", "h3", "h4"):
                        n.name = "p"
                    interior.append(n)
            bot = cuerpo.select_one(".wpr-promo-box-btn, a.wpr-promo-box-btn")
            if bot and bot.get("href") and bot.get_text(strip=True):
                b = self.nuevo("a", class_="boton", href=urljoin(self.base, bot["href"]))
                b.string = bot.get_text(" ", strip=True)
                interior.append(b)
            nodos = [caja]
        elif tipo in ("slides", "wpr-slider"):
            car = self.nuevo("div", class_="carrusel")
            for sl in cuerpo.select(".swiper-slide:not(.swiper-slide-duplicate)"):
                rep = [c for c in sl.get("class", []) if c.startswith("elementor-repeater-item-")]
                fondo = {}
                if rep:
                    for sel, decl in self.reglas:
                        if rep[0] in sel and "background-image" in decl:
                            m = re.search(r"background-image:\s*url\(['\"]?([^'\")]+)", decl)
                            if m:
                                fondo = m.group(1)
                img_t = None
                if fondo:
                    rel = guardar_imagen(fondo, self.base)
                    if rel:
                        img_t = self.nuevo("img", src=MARCA + rel, alt=sl.select_one(".swiper-slide-bg").get("aria-label", "") if sl.select_one(".swiper-slide-bg") else "", loading="lazy")
                elif sl.find("img"):
                    img_t = self.imagen(sl.find("img"))
                textos = sl.select_one(".swiper-slide-contents")
                fig = self.nuevo("figure")
                if img_t is not None:
                    enl = sl.select_one("a.swiper-slide-inner[href]")
                    if enl:
                        a = self.nuevo("a", href=urljoin(self.base, enl["href"]))
                        a.append(img_t)
                        img_t = a
                    fig.append(img_t)
                if textos and textos.get_text(strip=True):
                    cap = self.nuevo("figcaption")
                    for n in self.limpiar(textos):
                        cap.append(n)
                    fig.append(cap)
                if fig.contents:
                    car.append(fig)
            nodos = [car] if car.contents else []
        elif tipo in ("testimonial-carousel", "reviews"):
            car = self.nuevo("div", class_="carrusel opiniones")
            for sl in cuerpo.select(".swiper-slide:not(.swiper-slide-duplicate)"):
                txt = sl.select_one(".elementor-testimonial__text, .elementor-testimonial__content")
                if not txt or not txt.get_text(strip=True):
                    continue
                fig = self.nuevo("figure")
                bq = self.nuevo("blockquote")
                for n in self.limpiar(txt):
                    bq.append(n)
                fig.append(bq)
                nom = sl.select_one(".elementor-testimonial__name, cite")
                if nom and nom.get_text(strip=True):
                    fc = self.nuevo("figcaption")
                    fc.string = nom.get_text(" ", strip=True)
                    fig.append(fc)
                car.append(fig)
            nodos = [car] if car.contents else []
        elif tipo in ("html", "shortcode") and not cuerpo.find("iframe") and \
                len(set(re.findall(r"youtube\.com/watch\?v=([\w-]{11})", str(cuerpo)))) >= 2:
            # lista de vídeos de YouTube hecha con HTML propio: se muestran los vídeos incrustados
            ids = list(dict.fromkeys(re.findall(r"youtube\.com/watch\?v=([\w-]{11})", str(cuerpo))))[:6]
            rej = self.nuevo("div", class_="rejilla videos")
            for i in ids:
                rej.append(self.iframe(f"https://www.youtube-nocookie.com/embed/{i}"))
            nodos = [rej]
        elif tipo in ("html", "shortcode") and (cuerpo.find("script") or cuerpo.select("[class*=feed], [class*=yottie], [class*=sbi], [class*=instagram], [id*=feed]")):
            # incrustaciones con JavaScript (feeds de YouTube/Instagram...): solo se conservan los iframes de vídeo
            nodos = [self.iframe(f.get("src") or f.get("data-src")) for f in cuerpo.find_all("iframe")]
            if not any(nodos):
                self.avisos.append(f"widget '{tipo}' con JavaScript descartado")
        elif tipo in ("divider",):
            nodos = [self.nuevo("hr")]
        elif tipo in ("spacer", "nav-menu", "search-form"):
            nodos = []
        elif tipo == "menu-anchor":
            a = cuerpo.find(id=True)
            nodos = [self.nuevo("span", id=a["id"], class_="ancla")] if a else []
        elif tipo == "google_maps":
            f = cuerpo.find("iframe")
            nodos = [self.iframe(f.get("src"))] if f else []
        elif tipo in ("form", "wpforms", "contact-form-7", "shortcode") and cuerpo.find("form"):
            nodos = [self.bloque_contacto()]
            self.avisos.append("formulario sustituido por WhatsApp/correo")
        elif tipo in ("toggle", "accordion", "nested-accordion"):
            titulos = cuerpo.select(".elementor-tab-title, summary, .e-n-accordion-item-title")
            contenidos = cuerpo.select(".elementor-tab-content, .e-n-accordion-item > div[role=region], .e-n-accordion-item > .e-con")
            for t, c in zip(titulos, contenidos):
                det = self.nuevo("details")
                s = self.nuevo("summary")
                s.string = t.get_text(" ", strip=True)
                det.append(s)
                for n in self.limpiar(c):
                    det.append(n)
                nodos.append(det)
        elif tipo in ("image-carousel", "image-gallery", "gallery", "media-carousel", "nested-carousel", "wpr-image-carousel"):
            g = self.nuevo("div", class_="galeria")
            vistos = set()
            for img in cuerpo.find_all("img"):
                s = mejor_src(img)
                if s in vistos:
                    continue
                vistos.add(s)
                t = self.imagen(img)
                if t:
                    g.append(t)
            nodos = [g] if g.contents else []
        else:
            nodos = self.limpiar(cuerpo)
            if tipo and tipo not in ("html", "theme-post-content", "testimonial", "blockquote", "theme-post-title", "post-info"):
                self.avisos.append(f"widget '{tipo}' limpiado de forma genérica")
        return [n for n in nodos if n is not None]

    def aplicar_estilo(self, t, estilo):
        partes = []
        if "--min-height" in estilo:
            estilo = dict(estilo)
            estilo.setdefault("min-height", estilo.pop("--min-height"))
        for k, v in estilo.items():
            if k.startswith("--") or "var(--e-global-typography" in v or (k == "min-height" and v.startswith("0")):
                continue
            if k == "font-family":
                v = v.replace("Sans-serif", "sans-serif")
            if k == "font-size":
                m = re.fullmatch(r"([\d.]+)px", v)
                if m and float(m.group(1)) >= 26:
                    n = float(m.group(1))
                    v = f"clamp({max(22, round(n * .6))}px, {round(n / 13.66, 1)}vw, {v})"
            if k == "min-height":
                t["class"] = ((" ".join(t["class"]) if isinstance(t.get("class"), list) else t.get("class", "")) + " centrado").strip()
            if k == "background-image" and "gradient(" in v:
                partes.append(f"background-image:{v}")
            elif k == "background-image":
                m = re.search(r"url\(['\"]?([^'\")]+)", v)
                rel = guardar_imagen(m.group(1), self.base) if m else None
                if rel:
                    partes.append(f"background-image:url('{MARCA}{rel}')")
            else:
                partes.append(f"{k}:{v}")
        if partes:
            t["style"] = ";".join(partes)

    def video_fondo(self, el, caja):
        try:
            aj = json.loads(el.get("data-settings") or "{}")
        except ValueError:
            return
        url = aj.get("background_video_link")
        if aj.get("background_background") != "video" or not url or not url.endswith((".mp4", ".webm")):
            return
        rel = guardar_archivo(urljoin(self.base, url))
        if not rel:
            return
        caja["class"] = (" ".join(caja.get("class")) if isinstance(caja.get("class"), list) else caja.get("class", "")) + " con-video"
        v = self.nuevo("video", src=MARCA + rel, autoplay="", muted="", loop="", playsinline="", class_="fondo-video")
        caja.insert(0, v)
        capa = estilo_de(self.reglas, el.get("data-id"), "::before")
        if capa.get("background-color"):
            caja.insert(1, self.nuevo("div", class_="capa", style=f"background-color:{capa['background-color']}"))

    # -- estructura (secciones, columnas, contenedores)
    def hijos_estructura(self, el):
        cl = el.get("class") or []
        if "elementor-section" in cl:
            cont = el.select_one(":scope > .elementor-container") or el
            return [("col", c) for c in cont.find_all(class_="elementor-column", recursive=False)]
        if "elementor-column" in cl:
            wrap = el.select_one(":scope > .elementor-widget-wrap") or el
            return [("item", c) for c in wrap.find_all(True, recursive=False)]
        if "e-con" in cl:
            inner = el.select_one(":scope > .e-con-inner") or el
            return [("item", c) for c in inner.find_all(True, recursive=False)]
        return [("item", c) for c in el.find_all(True, recursive=False)]

    def columnas_rejilla(self, el):
        """Si el contenedor es una rejilla (display:grid), devuelve el número de columnas."""
        for sel, decl in self.reglas:
            if re.search(rf"elementor-element-{el.get('data-id')}\s*$", sel.split(",")[0]) and "--display:grid" in decl:
                m = re.search(r"--e-con-grid-template-columns:\s*repeat\(\s*(\d+)", decl)
                return int(m.group(1)) if m else 2
        return 0

    def es_fila(self, el):
        try:
            aj = json.loads(el.get("data-settings") or "{}")
        except ValueError:
            aj = {}
        if aj.get("flex_direction") in ("row", "row-reverse"):
            return True
        for sel, decl in self.reglas:
            if f"elementor-element-{el.get('data-id')}" in sel and re.search(r"--flex-direction:\s*row", decl):
                return True
        return False

    def nodo(self, el, nivel=0):
        """Convierte un elemento de Elementor en HTML limpio."""
        if oculto_en_escritorio(el):
            return []
        cl = el.get("class") or []
        if "elementor-widget" in cl:
            res = self.widget(el)
            if el.get("id"):
                res = [self.nuevo("span", id=el["id"], class_="ancla")] + res
            return res
        if "elementor-section" in cl:
            cols = [self.columna(c, nivel) for _, c in self.hijos_estructura(el) if not oculto_en_escritorio(c)]
            cols = [c for c in cols if c.strip()]
            return self.envolver(el, cols, nivel, fila=True)
        if "e-con" in cl:
            hijos = [c for _, c in self.hijos_estructura(el) if not oculto_en_escritorio(c)]
            subcon = [c for c in hijos if "e-con" in (c.get("class") or [])]
            rejilla = self.columnas_rejilla(el)
            if rejilla and len(hijos) > 1:
                partes = [self.html(self.nodo(c, nivel + 1)) for c in hijos]
                caja = self.envolver(el, ["\n".join(p for p in partes if p.strip())], nivel, fila=False)
                if caja:
                    destino = caja[0].find(class_="ancho") or caja[0]
                    destino["class"] = (" ".join(destino["class"]) if isinstance(destino.get("class"), list) else destino.get("class", "")) + " rejilla"
                    destino["style"] = (destino.get("style", "") + f";grid-template-columns:repeat({rejilla}, 1fr)").lstrip(";")
                return caja
            if self.es_fila(el) and len(hijos) > 1:
                cols = [self.html(self.nodo(c, nivel + 1)) for c in hijos]
                cols = [c for c in cols if c.strip()]
                return self.envolver(el, cols, nivel, fila=True)
            partes = [self.html(self.nodo(c, nivel + 1)) for c in hijos]
            return self.envolver(el, ["\n".join(p for p in partes if p.strip())], nivel, fila=False)
        if "elementor-column" in cl:
            return self.nodos_de(el, nivel)
        # elemento no Elementor (p. ej. contenido de una entrada normal)
        return self.limpiar(el) if el.name not in DESCARTAR else []

    def columna(self, c, nivel):
        """Contenido de una columna; si solo tiene una imagen de fondo, se convierte en <img>."""
        html = self.html(self.nodos_de(c, nivel + 1))
        fondo = {}
        for interior in (" > .elementor-element-populated", " > .elementor-widget-wrap", ""):
            fondo.update({k: v for k, v in estilo_de(self.reglas, c.get("data-id"), interior).items()
                          if k in ("background-color", "background-image")})
        m = re.search(r"url\(['\"]?([^'\")]+)", fondo.get("background-image", ""))
        if m and not html.strip():
            rel = guardar_imagen(m.group(1), self.base)
            return f'<p class="imagen imagen-columna"><img src="{MARCA}{rel}" alt="" loading="lazy"></p>' if rel else ""
        if fondo and html.strip():
            d = self.nuevo("div", class_="grupo con-fondo")
            self.aplicar_estilo(d, fondo)
            d.append(BeautifulSoup(html, "html.parser"))
            return str(d)
        return html

    def nodos_de(self, el, nivel):
        res = []
        for _, c in self.hijos_estructura(el):
            res += self.nodo(c, nivel)
        return res

    def envolver(self, el, cols, nivel, fila):
        if not any(c.strip() for c in cols):
            # contenedor vacío con imagen de fondo: se convierte en imagen
            fondo = estilo_de(self.reglas, el.get("data-id")).get("background-image", "")
            m = re.search(r"url\(['\"]?([^'\")]+)", fondo)
            rel = guardar_imagen(m.group(1), self.base) if m else None
            if rel:
                return [BeautifulSoup(f'<p class="imagen imagen-columna"><img src="{MARCA}{rel}" alt="" loading="lazy"></p>', "html.parser")]
            return []
        estilo = estilo_de(self.reglas, el.get("data-id"))
        alto = estilo_de(self.reglas, el.get("data-id"), " > .elementor-container").get("min-height")
        if alto and "min-height" not in estilo:
            estilo["min-height"] = alto
        if nivel == 0:
            caja = self.nuevo("section", class_="bloque")
            interior = self.nuevo("div", class_="ancho")
            caja.append(interior)
        else:
            caja = interior = self.nuevo("div", class_="grupo")
        if el.get("id"):
            caja["id"] = el["id"]
        self.aplicar_estilo(caja, {k: v for k, v in estilo.items() if k in ("background-color", "background-image", "color", "min-height", "--min-height")})
        self.video_fondo(el, caja)
        if fila and len(cols) > 1:
            fila_t = self.nuevo("div", class_="columnas")
            for c in cols:
                col = self.nuevo("div", class_="col")
                col.append(BeautifulSoup(c, "html.parser"))
                fila_t.append(col)
            interior.append(fila_t)
        else:
            for c in cols:
                interior.append(BeautifulSoup(c, "html.parser"))
        return [caja]


# ---------------------------------------------------------------- zona de contenido
def zona_contenido(soup):
    for sel in (".elementor-location-header", ".elementor-location-footer", "#wpadminbar",
                ".elementor-location-popup", "[data-elementor-type=popup]", ".evo_lightboxes", "#cookie-law-info-bar"):
        for e in soup.select(sel):
            e.decompose()
    for sel in ("[data-elementor-type=wp-page]", "[data-elementor-type=wp-post]",
                "[data-elementor-type=single-page]", "[data-elementor-type=single-post]",
                "[data-elementor-type=single]", "[data-elementor-type=product]",
                "main .entry-content", "main", "article", ".page-content", "#content"):
        e = soup.select_one(sel)
        if e and e.get_text(strip=True):
            return e
    for e in soup.find_all(["header", "footer"]):
        e.decompose()
    return soup.body


def meta_pagina(soup, cfg):
    titulo = (soup.find("meta", property="og:title") or {}).get("content") or (soup.title.string if soup.title else "")
    titulo = re.split(r"\s+[|\-–]\s+" + re.escape(cfg.get("nombre", "")), titulo or "")[0].strip()
    titulo = re.sub(r"\s*[|\-–]\s*$", "", titulo)
    desc = (soup.find("meta", attrs={"name": "description"}) or {}).get("content") or \
           (soup.find("meta", property="og:description") or {}).get("content") or ""
    return titulo, desc.strip()


def bloques_superiores(zona):
    """Secciones/contenedores de primer nivel de una página de Elementor."""
    res = []
    for c in zona.find_all(True, recursive=False):
        cl = c.get("class") or []
        if "elementor-section" in cl or "e-con" in cl:
            res.append(c)
        elif c.name in ("div",) and ({"elementor-section-wrap", "elementor-inner", "elementor"} & set(cl) or c.find(class_=["elementor-section", "e-con"], recursive=False)):
            res += bloques_superiores(c)
        else:
            res.append(c)
    return res


def convertir(url, zona_css=None, cfg=None):
    """Descarga una URL y devuelve (titulo, descripcion, html_limpio, avisos)."""
    cfg = cfg or config()
    soup = BeautifulSoup(descargar(url), "html.parser")
    titulo, desc = meta_pagina(soup, cfg)
    reglas = css_de_pagina(soup, url)
    if zona_css:
        zona = soup.select_one(zona_css)
    else:
        zona = zona_contenido(soup)
    lim = Limpiador(url, reglas, cfg.get("contacto"))
    partes = []
    if zona.find(class_=["elementor-section", "e-con", "elementor-widget"]):
        for b in bloques_superiores(zona):
            partes += lim.nodo(b, 0)
    else:
        sec = lim.nuevo("section", class_="bloque")
        an = lim.nuevo("div", class_="ancho")
        sec.append(an)
        for n in lim.limpiar(zona):
            an.append(n)
        partes = [sec]
    return titulo, desc, lim.html(partes), sorted(set(lim.avisos))


def datos_cabecera(soup, base_url):
    """Logo(s), menú y redes de la cabecera de Elementor de una página."""
    h = soup.select_one(".elementor-location-header")
    if not h:
        return None
    for e in h.select(".elementor-hidden-desktop"):
        e.decompose()
    imgs = [mejor_src(i) for i in h.find_all("img")]
    imgs = [i for i in dict.fromkeys(imgs) if i]
    res = {"logo": guardar_imagen(imgs[0], base_url) if imgs else None,
           "logo2": guardar_imagen(imgs[1], base_url) if len(imgs) > 1 else None}

    def arbol(ul):
        items = []
        for li in ul.find_all("li", recursive=False):
            a = li.find("a")
            if not a:
                continue
            it = {"texto": a.get_text(" ", strip=True), "url": urljoin(base_url, a.get("href") or "#")}
            sub = li.find("ul")
            if sub:
                it["hijos"] = arbol(sub)
            items.append(it)
        return items

    nav = h.select_one("nav.elementor-nav-menu--main ul, nav ul, .elementor-nav-menu")
    res["menu"] = arbol(nav) if nav else []
    redes = []
    for a in h.select(".elementor-social-icons-wrapper a, .elementor-widget-social-icons a"):
        if a.get("href"):
            redes.append({"texto": a.get_text(" ", strip=True) or a["href"], "url": a["href"]})
    res["redes"] = redes
    bot = h.select_one(".elementor-widget-button a")
    if bot and bot.get_text(strip=True):
        res["boton_cabecera"] = {"texto": bot.get_text(" ", strip=True), "url": urljoin(base_url, bot.get("href") or "#")}
    return res
