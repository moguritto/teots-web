#!/bin/bash
# Instala el servidor del editor de webs en Cloudflare (gratis). Lo prepara Claude.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.homebrew/bin:$PATH"
W="npx --yes wrangler@4"
echo ""
echo "  Servidor del editor de webs · instalación"
echo "  ----------------------------------------"
if ! command -v npx >/dev/null 2>&1; then
  echo "  Falta Node.js. Instalándolo con Homebrew…"
  brew install node || { echo "  No he podido instalar Node.js."; read -r -p "  Pulsa Intro para cerrar."; exit 1; }
fi
echo "  1/4 · Entrar en Cloudflare (se abre el navegador: entra o crea la cuenta y pulsa «Allow»)…"
$W whoami 2>/dev/null | grep -q "associated with" || $W login || { echo "  No se ha podido entrar en Cloudflare."; read -r -p "  Pulsa Intro para cerrar."; exit 1; }
if grep -q "__KV_ID__" wrangler.toml; then
  echo "  2/4 · Creando el almacén de usuarios…"
  ID=$($W kv namespace create USUARIOS 2>&1 | tee kv.log | grep -oE '[0-9a-f]{32}' | head -1)
  if [ -z "$ID" ]; then ID=$($W kv namespace list 2>/dev/null | tr ',' '\n' | grep -B2 -A2 'editor-webs-USUARIOS\|USUARIOS' | grep -oE '[0-9a-f]{32}' | head -1); fi
  [ -n "$ID" ] || { echo "  No se ha podido crear el almacén."; cat kv.log; read -r -p "  Pulsa Intro para cerrar."; exit 1; }
  sed -i '' "s/__KV_ID__/$ID/" wrangler.toml
fi
echo "  3/4 · Publicando el servidor…"
$W deploy 2>&1 | tee despliegue.log
URL=$(grep -oE 'https://editor-webs\.[a-z0-9-]+\.workers\.dev' despliegue.log | head -1)
[ -n "$URL" ] || { echo "  No se ha podido publicar. Mira despliegue.log."; read -r -p "  Pulsa Intro para cerrar."; exit 1; }
if [ ! -f .secreto-puesto ]; then
  echo "  4/4 · Guardando la clave interna (aleatoria)…"
  openssl rand -hex 32 | $W secret put SECRETO >/dev/null 2>&1 && touch .secreto-puesto
fi
echo "$URL" > url.txt
echo ""
echo "  ✓ Listo: $URL"
echo "  Ya puedes cerrar esta ventana. Claude se encarga del resto."
