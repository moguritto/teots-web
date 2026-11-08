// Servidor del editor de webs (Cloudflare Worker).
// Las personas con usuario y contraseña NO publican: envían su cambio como «propuesta».
// Manuel las revisa en su editor y, si las aprueba, las publica él con su propio GitHub.
// Este servidor no guarda ni usa ningún código de GitHub de Manuel.
//
// KV «USUARIOS»:  u:<usuario> → persona  ·  f:<usuario> → intentos fallidos
//                 p:<usuario>|<repo>|<archivo> → propuesta  ·  n:<usuario> → avisos para la persona
// Secretos: SECRETO (aleatorio).  Variables: ORIGEN, DUENO, GH_API y RAW (opcionales, para pruebas).

const REPOS = ['espacioteots-web', 'teots-web', 'apder-web', 'ianivillage-web', 'teotsai-web', 'theswisstree-web'];
const RE_FOTO = /^docs\/(wp-content\/uploads\/editor|img\/editor|fotos-editor)\/[A-Za-z0-9._-]{1,120}\.(jpg|png)$/;
const RE_RUTA = /^([a-z0-9][a-z0-9._-]*\/)*$/;
const RIESGOS = [/<script\b/gi, /[\s\/"']on[a-z]+\s*=/gi, /javascript\s*:/gi, /<iframe\b/gi, /<(object|embed|form|base|meta)\b/gi, /<link\b[^>]*\bimport\b/gi];
const DIAS_SESION = 30, MAX_FALLOS = 8, ITER = 20000, MAX_PROPUESTA = 20 * 1024 * 1024;

const enc = new TextEncoder(), dec = new TextDecoder();
const b64 = (u8) => { let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s); };
const unb64 = (s) => { const b = atob(s.replace(/\s+/g, '')); const u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; };
const b64url = (u8) => b64(u8).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const unb64url = (s) => unb64(s.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((s.length + 3) % 4));

class Fallo extends Error { constructor(status, codigo, mensaje) { super(mensaje); this.status = status; this.codigo = codigo; } }

function cors(env) {
  return {
    'Access-Control-Allow-Origin': env.ORIGEN || 'https://teots.org',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
    'Access-Control-Max-Age': '86400', 'Vary': 'Origin',
  };
}
function json(env, datos, status = 200) {
  return new Response(JSON.stringify(datos), { status, headers: { ...cors(env), 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' } });
}

/* ---------- Criptografía ---------- */
async function claveHmac(env) {
  return crypto.subtle.importKey('raw', enc.encode(env.SECRETO), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
}
async function hashClave(clave, sal) {
  const k = await crypto.subtle.importKey('raw', enc.encode(clave), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: sal, iterations: ITER }, k, 256);
  return new Uint8Array(bits);
}
function iguales(a, b) { if (a.length !== b.length) return false; let d = 0; for (let i = 0; i < a.length; i++) d |= a[i] ^ b[i]; return d === 0; }
async function crearSesion(env, usuario) {
  const carga = b64url(enc.encode(JSON.stringify({ u: usuario, exp: Date.now() + DIAS_SESION * 864e5 })));
  const firma = new Uint8Array(await crypto.subtle.sign('HMAC', await claveHmac(env), enc.encode(carga)));
  return carga + '.' + b64url(firma);
}
async function leerSesion(env, req) {
  const t = (req.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '');
  const [carga, firma] = t.split('.');
  if (!carga || !firma) throw new Fallo(401, 'sesion', 'Tienes que entrar con tu usuario y contraseña.');
  let ok = false; try { ok = await crypto.subtle.verify('HMAC', await claveHmac(env), unb64url(firma), enc.encode(carga)); } catch (e) { }
  if (!ok) throw new Fallo(401, 'sesion', 'Tu sesión no es válida. Vuelve a entrar.');
  const d = JSON.parse(dec.decode(unb64url(carga)));
  if (!d.exp || d.exp < Date.now()) throw new Fallo(401, 'sesion', 'Tu sesión ha caducado. Vuelve a entrar.');
  const p = await env.USUARIOS.get('u:' + d.u, 'json');
  if (!p) throw new Fallo(401, 'sesion', 'Ese usuario ya no existe. Habla con Manuel.');
  if ((p.desde || 0) > d.exp - DIAS_SESION * 864e5) throw new Fallo(401, 'sesion', 'Tu contraseña ha cambiado. Vuelve a entrar.');
  return { usuario: d.u, ...p };
}

/* ---------- Manuel: se comprueba su código de GitHub preguntando a GitHub (no se guarda) ---------- */
const cacheAdmin = new Map();
async function esAdmin(env, req) {
  const t = (req.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '');
  if (!/^(github_pat_|ghp_|gho_|ghu_)[A-Za-z0-9_]{20,}$/.test(t)) throw new Fallo(401, 'admin', 'Solo Manuel, conectado con GitHub, puede hacer esto.');
  const k = b64(new Uint8Array(await crypto.subtle.digest('SHA-256', enc.encode(t))));
  const c = cacheAdmin.get(k);
  if (c && c > Date.now()) return;
  let u = null;
  try {
    const r = await fetch((env.GH_API || 'https://api.github.com') + '/user', { headers: { 'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + t, 'User-Agent': 'editor-webs' } });
    if (r.ok) u = await r.json();
  } catch (e) { }
  if (!u) throw new Fallo(401, 'admin', 'GitHub no acepta ese código de acceso.');
  if (String(u.login).toLowerCase() !== String(env.DUENO || 'moguritto').toLowerCase()) throw new Fallo(403, 'admin', 'Ese código de GitHub no es de la cuenta de Manuel.');
  cacheAdmin.set(k, Date.now() + 5 * 60e3);
}

/* ---------- Validación ---------- */
function limpiarPermisos(lista) {
  if (!Array.isArray(lista) || lista.length > 200) throw new Fallo(400, 'datos', 'Lista de páginas no válida.');
  const vistos = new Set(), out = [];
  for (const p of lista) {
    if (!p || !REPOS.includes(p.repo) || typeof p.ruta !== 'string' || !RE_RUTA.test(p.ruta) || p.ruta.length > 200) throw new Fallo(400, 'datos', 'Hay una página no válida en la lista.');
    const k = p.repo + '|' + p.ruta; if (!vistos.has(k)) { vistos.add(k); out.push({ repo: p.repo, ruta: p.ruta }); }
  }
  return out;
}
function publico(usuario, p) { return { usuario, nombre: p.nombre, permisos: p.permisos, creado: p.creado, actualizado: p.actualizado }; }
function riesgos(t) { return RIESGOS.map((re) => (t.match(re) || []).length); }
async function textoPublicado(env, repo, path) {
  try {
    const r = await fetch(`${env.RAW || 'https://raw.githubusercontent.com/' + (env.DUENO || 'moguritto')}/${repo}/main/${path.split('/').map(encodeURIComponent).join('/')}`);
    return r.ok ? await r.text() : null;
  } catch (e) { return null; }
}
const idDe = (usuario, repo, path) => `${usuario}|${repo}|${path}`;
async function avisar(env, usuario, aviso) {
  const lista = (await env.USUARIOS.get('n:' + usuario, 'json')) || [];
  lista.unshift(aviso);
  await env.USUARIOS.put('n:' + usuario, JSON.stringify(lista.slice(0, 10)), { expirationTtl: 60 * 864e2 });
}
async function listarPropuestas(env, prefijo) {
  const out = []; let cursor;
  do {
    const l = await env.USUARIOS.list({ prefix: 'p:' + (prefijo || ''), cursor });
    for (const k of l.keys) out.push({ id: k.name.slice(2), ...(k.metadata || {}) });
    cursor = l.list_complete === false ? l.cursor : null;
  } while (cursor);
  return out.sort((a, b) => (b.fecha || 0) - (a.fecha || 0));
}

/* ---------- Rutas ---------- */
async function rutas(req, env) {
  const url = new URL(req.url), p = url.pathname, m = req.method;
  const cuerpo = async () => { try { return await req.json(); } catch (e) { throw new Fallo(400, 'datos', 'Petición no válida.'); } };

  if (p === '/' && m === 'GET') return json(env, { servicio: 'editor-webs', ok: true });

  // --- Manuel (con su código de GitHub) ---
  if (p === '/admin/estado' && m === 'GET') {
    await esAdmin(env, req);
    if (await env.USUARIOS.get('config:gh')) await env.USUARIOS.delete('config:gh');  // de la versión anterior: ya no hace falta
    const lista = await env.USUARIOS.list({ prefix: 'u:' });
    const usuarios = [];
    for (const k of lista.keys) { const d = await env.USUARIOS.get(k.name, 'json'); if (d) usuarios.push(publico(k.name.slice(2), d)); }
    usuarios.sort((a, b) => (b.actualizado || 0) - (a.actualizado || 0));
    return json(env, { usuarios, propuestas: await listarPropuestas(env) });
  }
  if (p === '/admin/propuesta' && m === 'GET') {
    await esAdmin(env, req);
    const d = await env.USUARIOS.get('p:' + (url.searchParams.get('id') || ''), 'json');
    if (!d) throw new Fallo(404, 'nada', 'Esa propuesta ya no existe (puede que la hayan retirado).');
    return json(env, d);
  }
  if (p === '/admin/resolver' && m === 'POST') {
    await esAdmin(env, req);
    const d = await cuerpo();
    const id = String(d.id || ''), estado = d.estado === 'aprobado' ? 'aprobado' : 'rechazado';
    const prop = await env.USUARIOS.get('p:' + id, 'json');
    if (!prop) throw new Fallo(404, 'nada', 'Esa propuesta ya no existe.');
    await env.USUARIOS.delete('p:' + id);
    await avisar(env, prop.usuario, { estado, repo: prop.repo, path: prop.archivos.find((a) => a.esPag).path, fecha: Date.now(), motivo: String(d.motivo || '').slice(0, 300) });
    return json(env, { ok: true });
  }
  if (p === '/admin/usuario' && m === 'POST') {
    await esAdmin(env, req);
    const d = await cuerpo();
    const usuario = String(d.usuario || '').toLowerCase().trim();
    if (!/^[a-z0-9._-]{2,30}$/.test(usuario)) throw new Fallo(400, 'datos', 'El usuario solo puede llevar letras sin acentos, números, puntos y guiones (2 a 30).');
    const nombre = String(d.nombre || '').trim().slice(0, 60);
    if (!nombre) throw new Fallo(400, 'datos', 'Falta el nombre.');
    const permisos = limpiarPermisos(d.permisos || []);
    const previo = await env.USUARIOS.get('u:' + usuario, 'json');
    const ahora = Date.now();
    const p2 = { ...(previo || { creado: ahora }), nombre, permisos, actualizado: ahora };
    if (d.clave != null) {
      const clave = String(d.clave);
      if (clave.length < 8 || clave.length > 200) throw new Fallo(400, 'datos', 'La contraseña tiene que tener al menos 8 caracteres.');
      const sal = crypto.getRandomValues(new Uint8Array(16));
      p2.sal = b64(sal); p2.hash = b64(await hashClave(clave, sal)); p2.desde = ahora;
    } else if (!previo) throw new Fallo(400, 'datos', 'Falta la contraseña.');
    await env.USUARIOS.put('u:' + usuario, JSON.stringify(p2));
    await env.USUARIOS.delete('f:' + usuario);
    return json(env, { ok: true, usuario: publico(usuario, p2) });
  }
  if (p === '/admin/usuario' && m === 'DELETE') {
    await esAdmin(env, req);
    const u = String(url.searchParams.get('u') || '').toLowerCase();
    await env.USUARIOS.delete('u:' + u);
    await env.USUARIOS.delete('n:' + u);
    for (const x of await listarPropuestas(env, u + '|')) await env.USUARIOS.delete('p:' + x.id);
    return json(env, { ok: true });
  }

  // --- Personas con usuario ---
  if (p === '/entrar' && m === 'POST') {
    const d = await cuerpo();
    const usuario = String(d.usuario || '').toLowerCase().trim(), clave = String(d.clave || '');
    const kf = 'f:' + usuario;
    const fallos = parseInt((await env.USUARIOS.get(kf)) || '0', 10);
    if (fallos >= MAX_FALLOS) throw new Fallo(429, 'bloqueo', 'Demasiados intentos. Espera 15 minutos y vuelve a probar.');
    const per = /^[a-z0-9._-]{2,30}$/.test(usuario) ? await env.USUARIOS.get('u:' + usuario, 'json') : null;
    const hash = await hashClave(clave, per ? unb64(per.sal) : new Uint8Array(16));
    if (!per || !iguales(hash, unb64(per.hash))) {
      if (/^[a-z0-9._-]{2,30}$/.test(usuario)) await env.USUARIOS.put(kf, String(fallos + 1), { expirationTtl: 900 });
      throw new Fallo(401, 'clave', 'Usuario o contraseña incorrectos.');
    }
    if (fallos) await env.USUARIOS.delete(kf);
    return json(env, { sesion: await crearSesion(env, usuario), usuario, nombre: per.nombre, permisos: per.permisos });
  }
  if (p === '/yo' && m === 'GET') {
    const s = await leerSesion(env, req);
    const avisos = (await env.USUARIOS.get('n:' + s.usuario, 'json')) || [];
    if (avisos.length) await env.USUARIOS.delete('n:' + s.usuario);  // se enseñan una vez
    const pendientes = (await listarPropuestas(env, s.usuario + '|')).map((x) => ({ repo: x.repo, path: x.path, fecha: x.fecha }));
    return json(env, { usuario: s.usuario, nombre: s.nombre, permisos: s.permisos, pendientes, avisos });
  }
  if (p === '/mia' && (m === 'GET' || m === 'DELETE')) {
    const s = await leerSesion(env, req);
    const id = idDe(s.usuario, url.searchParams.get('repo') || '', url.searchParams.get('path') || '');
    if (m === 'DELETE') { await env.USUARIOS.delete('p:' + id); return json(env, { ok: true }); }
    const d = await env.USUARIOS.get('p:' + id, 'json');
    return json(env, d ? { propuesta: d } : { propuesta: null });
  }
  if (p === '/proponer' && m === 'POST') {
    const s = await leerSesion(env, req);
    const d = await cuerpo();
    const repo = d.repo, archivos = d.archivos;
    if (!REPOS.includes(repo) || !Array.isArray(archivos) || !archivos.length || archivos.length > 12) throw new Fallo(400, 'datos', 'Petición no válida.');
    const paginas = new Set(s.permisos.filter((x) => x.repo === repo).map((x) => 'docs/' + x.ruta + 'index.html'));
    if (!paginas.size) throw new Fallo(403, 'permiso', 'No tienes permiso para cambiar esta web.');
    const limpios = []; let pag = null;
    for (const a of archivos) {
      if (!a || typeof a.path !== 'string' || typeof a.contenido !== 'string') throw new Fallo(400, 'datos', 'Petición no válida.');
      const esPag = paginas.has(a.path), esFoto = RE_FOTO.test(a.path);
      if (!esPag && !esFoto) throw new Fallo(403, 'permiso', 'No tienes permiso para cambiar ' + a.path.replace(/^docs\//, '/').replace(/index\.html$/, '') + '.');
      if (esPag && pag) throw new Fallo(400, 'datos', 'Solo se puede enviar una página cada vez.');
      const bytes = unb64(a.contenido);
      if (bytes.length > (esPag ? 3 : 6) * 1024 * 1024) throw new Fallo(413, 'grande', 'El archivo es demasiado grande.');
      if (esFoto) {
        const png = bytes[0] === 0x89 && bytes[1] === 0x50, jpg = bytes[0] === 0xff && bytes[1] === 0xd8;
        if (!(a.path.endsWith('.png') ? png : jpg)) throw new Fallo(400, 'datos', 'La foto no es un JPG o PNG válido.');
      }
      const x = { path: a.path, contenido: b64(bytes), previo: esPag ? (/^[0-9a-f]{40}$/.test(a.previo || '') ? a.previo : null) : null, esPag };
      if (esPag) { if (!x.previo) throw new Fallo(400, 'datos', 'Falta la versión de la página.'); pag = { ...x, texto: dec.decode(bytes) }; }
      limpios.push(x);
    }
    if (!pag) throw new Fallo(400, 'datos', 'Falta la página.');
    // Primer filtro: no se puede añadir código. (La revisión de Manuel comprueba además toda la estructura.)
    const actual = await textoPublicado(env, repo, pag.path);
    if (actual != null) {
      const antes = riesgos(actual), despues = riesgos(pag.texto);
      if (despues.some((n, i) => n > antes[i])) throw new Fallo(400, 'seguridad', 'El cambio añade código (scripts o formularios) y no está permitido. Solo se pueden cambiar textos, enlaces y fotos.');
    }
    const id = idDe(s.usuario, repo, pag.path);
    const anterior = await env.USUARIOS.get('p:' + id, 'json');
    if (anterior) {  // conserva las fotos del envío anterior que la página sigue usando
      for (const f of anterior.archivos) if (!f.esPag && !limpios.some((x) => x.path === f.path) && pag.texto.includes(f.path.split('/').pop())) limpios.push(f);
    }
    const fecha = Date.now();
    const prop = { id, usuario: s.usuario, nombre: s.nombre, repo, mensaje: String(d.mensaje || 'Cambio desde el editor').slice(0, 200), fecha, archivos: limpios };
    const texto = JSON.stringify(prop);
    if (texto.length > MAX_PROPUESTA) throw new Fallo(413, 'grande', 'El envío es demasiado grande. Prueba con menos fotos.');
    await env.USUARIOS.put('p:' + id, texto, { metadata: { usuario: s.usuario, nombre: s.nombre, repo, path: pag.path, fecha, mensaje: prop.mensaje, fotos: limpios.length - 1 } });
    return json(env, { ok: true, id, fecha });
  }
  throw new Fallo(404, 'nada', 'No existe.');
}

export default {
  async fetch(req, env) {
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors(env) });
    try { return await rutas(req, env); }
    catch (e) {
      if (e instanceof Fallo) return json(env, { error: e.codigo, mensaje: e.message }, e.status);
      return json(env, { error: 'interno', mensaje: 'Error en el servidor del editor: ' + (e && e.message) }, 500);
    }
  },
};
