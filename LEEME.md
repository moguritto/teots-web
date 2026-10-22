# Web de TEOTS

Copia estática (HTML y CSS) de teots.org, publicada gratis con GitHub Pages.

- Dirección de prueba: https://moguritto.github.io/teots-web/
- La web final está en la carpeta **`docs/`**. Cada página es un `index.html` dentro de una carpeta con el mismo nombre que su dirección (por ejemplo, `docs/aviso-legal/index.html` es `/aviso-legal/`).
- Los colores y las letras están en **`docs/estilo.css`** (el primer bloque, `:root`).
- Las imágenes están en `docs/img/`.

## Cambiar un texto

1. Entra en https://github.com/moguritto/teots-web y abre la carpeta `docs/`.
2. Abre la página que quieras cambiar (por ejemplo `docs/index.html` es la portada).
3. Pulsa el icono del lápiz (**Edit this file**), arriba a la derecha.
4. Busca el texto (Ctrl+F) y cámbialo. Toca solo el texto entre `>` y `<`, no las etiquetas.
5. Pulsa el botón verde **Commit changes…** y, en la ventana que sale, otra vez **Commit changes**.
6. En uno o dos minutos el cambio aparece en la web.

## Cambiar una imagen

1. Entra en `docs/img/`, pulsa **Add file → Upload files** y sube la imagen nueva (mejor en .webp o .jpg, de menos de 1600 px).
2. Edita la página y cambia el nombre del archivo en `src="img/…"`. Pulsa **Commit changes**.

## Para quien mantenga la web

`scripts/` contiene las herramientas de la migración (Python: `pip install -r scripts/requirements.txt`):
`extraer.py` (descarga y limpia páginas de la web original a `contenido/`), `construir.py` (genera `docs/`; sobrescribe las páginas migradas) y `comprobar.py` (enlaces rotos e imágenes que faltan). Terminada la migración, se edita directamente `docs/`.
