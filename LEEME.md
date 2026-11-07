# Web de teots.org

Copia **calcada** de teots.org (26/10/2026): la web original de WordPress guardada tal cual con el plugin Simply Static, solo con las páginas elegidas. Se ve igual que la original en ordenador y en móvil.

- Dirección de prueba: https://moguritto.github.io/teots-web/
- La web está en **`docs/`**. Cada página es un `index.html` dentro de una carpeta con el nombre de su dirección (`docs/index.html` es la portada).
- Estilos, letras, fotos y vídeos están en `docs/wp-content/` y `docs/wp-includes/`, como en WordPress. No hace falta tocarlos.

## Cambiar un texto (lo más fácil)

Abre el **editor visual**: https://teots.org/editor/ — sirve para las cinco webs (Espacio TEOTS, TEOTS, APDER, Iani Village y TEOTS AI). Pincha un texto, una foto o un enlace en la página, cámbialo y pulsa **Publicar**. La primera vez en cada dispositivo pide conectar con GitHub (los pasos están en el propio editor).

## Cambiar un texto a mano en GitHub

1. Entra en https://github.com/moguritto/teots-web y abre `docs/`.
2. Abre la página (por ejemplo `docs/index.html`) y pulsa el lápiz (**Edit this file**).
3. Busca el texto (Ctrl+F) y cámbialo. Toca solo el texto entre `>` y `<`.
4. Pulsa **Commit changes…** y otra vez **Commit changes**. En uno o dos minutos está en la web.

## Para quien mantenga la web

- `scripts/calcada/build.py` + `cfg_*.py`: generan `docs/` desde el ZIP de Simply Static (direcciones relativas, sin rastreadores, formularios y widgets que necesitan servidor cambiados por WhatsApp/correo, redirecciones desde direcciones antiguas).
- `scripts/calcada/test.cjs` y `extra.txt`: comprobación con Playwright y archivos que Elementor carga a demanda.
- El resto de `scripts/` y `contenido/` es de la primera copia (reconstruida), ya sustituida.
- `docs/editor/index.html`: el editor visual (una sola página, no indexada). Publica con la API de GitHub usando el código de acceso que se guarda en el navegador de quien edita.
