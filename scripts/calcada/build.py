#!/usr/bin/env python3
"""Copia calcada de espacioteots.org a partir del ZIP de Simply Static.
Uso: python3 build.py ZIPDIR OUTDIR [extra_files.txt] [config.py]
config.py (opcional) redefine DOMAIN, PAGES, REDIRECTS, EXTERNAL, INSTAGRAM, INSTAGRAM_TXT,
EVENTON_STATIC, SUBS (lista de (regex, sustitución)) y OLD_REDIRECTS_DIR.
"""
import os, re, sys, shutil, json
from urllib.parse import unquote

SRC, OUT = sys.argv[1], sys.argv[2]
EXTRA = set(open(sys.argv[3]).read().split()) if len(sys.argv) > 3 and os.path.exists(sys.argv[3]) else set()

# página destino -> carpeta en el ZIP
PAGES = {
    "": "", "terapias/": "terapias/", "salas/": "salas/", "coworking/": "coworking/",
    "coworking/tarifas/": "coworking/tarifas/", "coworking/coruna/": "coworking/coruna/",
    "manuel-lameiro/": "manuel-lameiro/", "tarifas-2026-manuel/": "tarifas-2026-manuel/",
    "ana-andrade/": "ana-andrade/", "lucia-martinez/": "lucia-martinez/",
    "yoga-barbara-carbajal/": "yoga-barbara-carbajal/", "hayat-lanouar/": "hayat-lanouar/",
    "maria-sonoterapia/": "maria-sonoterapia/", "roberto-linares/": "roberto-linares/",
    "aviso-legal/": "aviso-legal/", "politica-de-privacidad/": "politica-de-privacidad/",
}
# direcciones antiguas o no migradas -> página migrada más cercana
REDIRECTS = {
    "alquiler/coruna/": "coworking/coruna/",
    "coworking/coruna-old/": "coworking/coruna/",
    "coworking/tarifas-2/": "coworking/tarifas/",
    "tarifas-2/": "coworking/tarifas/",
    "salas-copy/": "salas/",
    "espacio-teots-salas-en-lugo/": "salas/",
    "espacio-teots-one-page/": "coworking/",
    "info/": "coworking/",
    "eventos/": "terapias/",
    "events/": "terapias/",
    "masaje-jhon-fernando-hidalgo-zapata/": "terapias/",
    "videos/": "",
    "alquiler/": "coworking/",
    "tarifas/": "coworking/tarifas/",
    "patricia-albarran/": "terapias/",
    "events/relaciones-de-pareja-taller-grupal/": "ana-andrade/",
}
EXTERNAL = {"recursos/": "https://teots.org/recursos/"}
DOMAIN = "espacioteots.org"
INSTAGRAM = "https://www.instagram.com/espacioteots/"
INSTAGRAM_TXT = "Ver Espacio Teots en Instagram"
SUBS = []
OLD_REDIRECTS_DIR = None
LIVE_JSON = None  # HTML descargado tal cual de la web (sin sesión); si está, manda sobre el del ZIP
EXTRA_PAGES = []  # páginas que se añaden aparte (p. ej. textos legales de la copia anterior)
PHONE = re.compile(r"^/[\w-]+/(?:34)?(\d{9})/?$")
UNWANTED_SCRIPT = re.compile(r"pixelyoursite|pys[-_]|fbq\(|googletagmanager|gtag\(|google-analytics|xmlrpc", re.I)

def norm_page(p):
    p = unquote(p.split("#")[0].split("?")[0]).lstrip("/")
    if p and not p.endswith("/") and "." not in p.rsplit("/", 1)[-1]:
        p += "/"
    return p

def page_target(p):
    p = norm_page(p)
    if p in PAGES or p in EXTRA_PAGES: return p
    if p in REDIRECTS: return REDIRECTS[p]
    return None

unknown_links = {}
deps = set()

def rel_prefix(dest):
    d = dest.count("/")
    return "../" * d if d else "./"

EVENTON_STATIC = """<div class="elementor-widget-container"><div class="evo-estatico" style="max-width:800px;margin:0 auto;font-family:Poppins,sans-serif">
<p style="font-family:Poppins,sans-serif;font-weight:800;font-size:30px;color:#202124;margin:0 0 12px">CADA JUEVES</p>
<div style="background:#ECECEC;border-radius:10px;padding:16px 20px;color:#fff">
<div style="display:flex;gap:16px;align-items:baseline;flex-wrap:wrap"><span style="font-weight:800;font-size:22px">19:00 – 20:00</span><span style="font-weight:800;font-size:20px;text-transform:uppercase">Meditación</span></div>
<p style="color:#6b6b6b;margin:10px 0 0;font-size:14px;line-height:1.6">Un espacio de pausa, conexión y escucha interior. A través de la respiración consciente y el silencio compartido, abrimos la puerta a un estado de presencia profunda. No se requiere experiencia previa. Solo traer ropa cómoda y disposición a estar.<br><strong>Espacio Teots</strong> · Rúa Anduriñas, 17, entresuelo. 27004 Lugo</p>
</div></div></div>"""

WIDGETS = {}  # clase del widget de Elementor -> HTML fijo que sustituye su contenido

def replace_widget(html, cls, new):
    out, pos = [], 0
    for m in re.finditer(r'<div class="elementor-element[^"]*\b' + re.escape(cls) + r'\b[^"]*"[^>]*>', html):
        if m.start() < pos: continue
        i, depth = m.end(), 1
        for t in re.finditer(r"<(/?)div\b[^>]*>", html[i:]):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                end = i + t.start()
                out.append(html[pos:m.end()]); out.append(new); pos = end
                break
    out.append(html[pos:])
    return "".join(out)

REMOVE_IF_CONTAINS = []  # quita el widget entero si contiene alguno de estos textos

def remove_widgets(html):
    if not REMOVE_IF_CONTAINS:
        return html
    out, pos = [], 0
    for m in re.finditer(r'<div class="elementor-element[^"]*\belementor-widget\b[^"]*"[^>]*>', html):
        if m.start() < pos: continue
        i, depth = m.end(), 1
        for t in re.finditer(r"<(/?)div\b[^>]*>", html[i:]):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                end = i + t.end()
                block = html[m.start():end]
                if any(k in block for k in REMOVE_IF_CONTAINS):
                    out.append(html[pos:m.start()]); pos = end
                break
    out.append(html[pos:])
    return "".join(out)

def replace_eventon(html):
    w = dict(WIDGETS)
    if EVENTON_STATIC:
        w.setdefault("elementor-widget-EventON", EVENTON_STATIC)
    for cls, new in w.items():
        html = replace_widget(html, cls, new)
    return html

def clean_html(html):
    # quitar scripts de seguimiento (PixelYourSite, Google)
    def drop_script(m):
        return "" if UNWANTED_SCRIPT.search(m.group(0)) else m.group(0)
    html = re.sub(r"<script\b[^>]*>.*?</script>", drop_script, html, flags=re.S | re.I)
    html = re.sub(r"<link\b[^>]*(?:xmlrpc|wp-json|EditURI|shortlink|alternate\" type=\"application/(?:rss|json)|oembed)[^>]*>", "", html, flags=re.I)
    html = re.sub(r"<link\b[^>]*pixelyoursite[^>]*>", "", html, flags=re.I)
    # enlaces sobrantes a royal-elementor-addons
    html = re.sub(r'<a\b[^>]*href="https?://royal-elementor-addons\.com[^"]*"[^>]*>(.*?)</a>', r"\1", html, flags=re.S | re.I)
    # feed de Instagram (necesita servidor) -> enlace al perfil
    html = re.sub(r'<div id="instagram-gallery-feed-\d+" class="instagram-gallery-feed"[^>]*>\s*<!-- <FeedContainer/> -->',
                  lambda m: '<div class="instagram-gallery-feed" style="text-align:center;padding:24px 0">'
                  '<a href="' + INSTAGRAM + '" target="_blank" rel="noopener" '
                  'style="display:inline-block;padding:12px 26px;border-radius:6px;background:#F5F5F5;color:#A29171;'
                  'font-family:Poppins,sans-serif;font-weight:600;font-size:15px;text-decoration:none">'
                  + INSTAGRAM_TXT + '</a>', html)
    html = replace_eventon(html)
    html = remove_widgets(html)
    html = re.sub(r"<script\b[^>]*insta-gallery[^>]*></script>", "", html, flags=re.I)
    html = re.sub(r"<link\b[^>]*(?:insta-gallery|youtube-feed-pro/css/(?:https|/|\.\./))[^>]*>", "", html, flags=re.I)
    for a, b in SUBS:
        html = re.sub(a, b, html, flags=re.S)
    return html

def rewrite_html(html, dest, src_page):
    rp = rel_prefix(dest)
    rpe = rp.replace("/", "\\/")
    # recursos: /wp-content, /wp-includes (normales y escapados en JSON)
    for m in re.finditer(r"(?<![\w/.])/(wp-content|wp-includes)/[^\s\"'()<>\\,&]+", html):
        deps.add(unquote(m.group(0)[1:].split("?")[0].split("#")[0]))
    for m in re.finditer(r"\\/(wp-content|wp-includes)\\/[^\s\"'()<>,&]+", html):
        deps.add(unquote(m.group(0).replace("\\/", "/")[1:].split("?")[0]))
    html = re.sub(r"(?<![\w/.])/(wp-content|wp-includes)/", lambda m: rp + m.group(1) + "/", html)
    html = re.sub(r"(?<![\w.\\])\\/(wp-content|wp-includes)\\/", lambda m: rpe + m.group(1) + "\\/", html)

    # enlaces a páginas
    def fix_link(m):
        attr, q, url = m.group(1), m.group(2), m.group(3)
        if url.startswith("//"):
            return m.group(0)
        frag = "#" + url.split("#", 1)[1] if "#" in url else ""
        if url.split("#")[0] == "" :
            return m.group(0)
        if attr == "action":
            return f'{attr}={q}#{q}'
        ph = PHONE.match(url.split("#")[0])
        if ph:
            return f'{attr}={q}tel:+34{ph.group(1)}{q}'
        if norm_page(url) in EXTERNAL:
            return f'{attr}={q}{EXTERNAL[norm_page(url)]}{q}'
        t = page_target(url)
        if t is None:
            unknown_links.setdefault(norm_page(url), set()).add(src_page)
            t = ""  # a la portada
        return f'{attr}={q}{rp}{t}{frag}{q}'
    html = re.sub(r'(href|action)=(["\'])(/(?!/)[^"\']*)\2', fix_link, html)
    # canonical/og a dominio final
    html = re.sub(r'(<link rel="canonical" href=")([^"]*)(")', lambda m: m.group(1) + f"https://{DOMAIN}/" + dest + m.group(3), html)
    html = re.sub(r'(<meta property="og:url" content=")([^"]*)(")', lambda m: m.group(1) + f"https://{DOMAIN}/" + dest + m.group(3), html)
    return html

def css_deps_and_rewrite(path_rel):
    p = os.path.join(SRC, path_rel)
    try:
        css = open(p, encoding="utf-8", errors="replace").read()
    except FileNotFoundError:
        return None, []
    base = os.path.dirname(path_rel)
    found = []
    def fix(m):
        u = m.group(2).strip()
        if u.startswith(("data:", "http:", "https:", "#")) or u.startswith("//"):
            return m.group(0)
        clean = unquote(u.split("?")[0].split("#")[0])
        if clean.startswith("/"):
            target = clean[1:]
            newu = os.path.relpath(target, base or ".") + (u[len(u.split("?")[0].split("#")[0]):])
            found.append(target)
            return f"url({m.group(1)}{newu}{m.group(1)})"
        target = os.path.normpath(os.path.join(base, clean))
        found.append(target)
        return m.group(0)
    css2 = re.sub(r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)", fix, css)
    for m in re.finditer(r"@import\s+['\"]([^'\"]+)['\"]", css2):
        u = m.group(1)
        if not u.startswith("http"):
            found.append(os.path.normpath(os.path.join(base, u.lstrip("/") if u.startswith("/") else u)))
    return css2, found

def redirect_page(target, dest):
    rp = rel_prefix(dest)
    url = rp + target
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Redirigiendo…</title>
<meta name="robots" content="noindex"><link rel="canonical" href="https://{DOMAIN}/{target}">
<meta http-equiv="refresh" content="0; url={url}"><script>location.replace({json.dumps(url)}+location.hash)</script></head>
<body><a href="{url}">Continuar</a></body></html>"""

if len(sys.argv) > 4:
    exec(open(sys.argv[4], encoding="utf-8").read(), globals())

if os.path.exists(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)

LIVE = json.load(open(LIVE_JSON, encoding="utf-8")) if LIVE_JSON else {}
def live_norm(h):
    for pre in ("https://", "http://", "//"):
        h = h.replace(pre + DOMAIN + "/", "/").replace(pre.replace("/", "\\/") + DOMAIN + "\\/", "\\/")
    return h.replace('href="https://' + DOMAIN + '"', 'href="/"')

for dest, src in PAGES.items():
    f = os.path.join(SRC, src, "index.html")
    if src in LIVE and LIVE[src].get("status") == 200:
        html = live_norm(LIVE[src]["html"])
    else:
        html = open(f, encoding="utf-8").read()
    html = clean_html(html)
    html = rewrite_html(html, dest, "/" + dest)
    os.makedirs(os.path.join(OUT, dest), exist_ok=True)
    open(os.path.join(OUT, dest, "index.html"), "w", encoding="utf-8").write(html)

for dest, target in REDIRECTS.items():
    os.makedirs(os.path.join(OUT, dest), exist_ok=True)
    open(os.path.join(OUT, dest, "index.html"), "w", encoding="utf-8").write(redirect_page(target, dest))

# redirecciones de la copia anterior (direcciones antiguas)
if OLD_REDIRECTS_DIR:
    for dp, _, fs in os.walk(OLD_REDIRECTS_DIR):
        for fn in fs:
            if fn != "index.html": continue
            src = os.path.join(dp, fn)
            if "data-redireccion" not in open(src, encoding="utf-8").read(): continue
            rel = os.path.relpath(src, OLD_REDIRECTS_DIR)
            dst = os.path.join(OUT, rel)
            if not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(src, dst)

# dependencias (con CSS recursivo)
todo = list(deps | EXTRA)
done = set()
missing = []
while todo:
    d = os.path.normpath(todo.pop())
    if d in done: continue
    done.add(d)
    sp = os.path.join(SRC, d)
    if not os.path.isfile(sp):
        missing.append(d); continue
    op = os.path.join(OUT, d)
    os.makedirs(os.path.dirname(op), exist_ok=True)
    if d.endswith(".css"):
        css, found = css_deps_and_rewrite(d)
        open(op, "w", encoding="utf-8").write(css)
        todo.extend(found)
    else:
        shutil.copy2(sp, op)

open(os.path.join(OUT, ".nojekyll"), "w").write("")
open(os.path.join(OUT, "robots.txt"), "w").write("User-agent: *\nAllow: /\nSitemap: https://{DOMAIN}/sitemap.xml\n".format(DOMAIN=DOMAIN))
sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
sm += [f"  <url><loc>https://{DOMAIN}/{p}</loc></url>" for p in PAGES]
sm.append("</urlset>")
open(os.path.join(OUT, "sitemap.xml"), "w").write("\n".join(sm) + "\n")

json.dump({"missing": sorted(set(missing)), "unknown_links": {k: sorted(v) for k, v in unknown_links.items()}},
          open(os.path.join(os.path.dirname(OUT.rstrip("/")) or ".", "informe_build.json"), "w"), ensure_ascii=False, indent=1)
print("archivos:", sum(len(f) for _, _, f in os.walk(OUT)), "faltan:", len(set(missing)), "enlaces desconocidos:", len(unknown_links))
