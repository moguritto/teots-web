// Servidor del editor de webs (Cloudflare Worker).
// Guarda el código de GitHub de Manuel (cifrado) y deja publicar a otras personas
// solo en las páginas que él les asigna, con usuario y contraseña.
//
// Enlaces (KV «USUARIOS»):  u:<usuario>  → persona   ·   config:gh → código de GitHub cifrado
// Secretos: SECRETO (aleatorio).  Variables: ORIGEN, DUENO, GH_API (opcional, para pruebas).

const REPOS = ['espacioteots-web', 'teots-web', 'apder-web', 'ianivillage-web', 'teotsai-web', 'theswisstree-web'];
const RE_FOTO = /^docs\/(wp-content\/uploads\/editor|img\/editor|fotos-editor)\/[A-Za-z0-9._-]{1,120}\.(jpg|png)$/;
const RE_RUTA = /^([a-z0-9][a-z0-9._-]*\/)*$/;
const RIESGOS = [/<script\b/gi, /\son[a-z]+\s*=/gi, /javascript\s*:/gi, /<iframe\b/gi, /<(object|embed|form|base|meta)\b/gi, /<link\b[^>]*\bimport\b/gi];
const DIAS_SESION = 30, MAX_FALLOS = 8, ITER = 20000;

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
async function claveCifrado(env) {
  const h = await crypto.subtle.digest('SHA-256', enc.encode(env.SECRETO + ':github'));
  return crypto.subtle.importKey('raw', h, 'AES-GCM', false, ['encrypt', 'decrypt']);
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
  const ok = await crypto.subtle.verify('HMAC', await claveHmac(env), unb64url(firma), enc.encode(carga));
  if (!ok) throw new Fallo(401, 'sesion', 'Tu sesión no es válida. Vuelve a entrar.');
  const d = JSON.parse(dec.decode(unb64url(carga)));
  if (!d.exp || d.exp < Date.now()) throw new Fallo(401, 'sesion', 'Tu sesión ha caducado. Vuelve a entrar.');
  const p = await env.USUARIOS.get('u:' + d.u, 'json');
  if (!p) throw new Fallo(401, 'sesion', 'Ese usuario ya no existe. Habla con Manuel.');
  if ((p.desde || 0) > d.exp - DIAS_SESION * 864e5) throw new Fallo(401, 'sesion', 'Tu contraseña ha cambiado. Vuelve a entrar.');
  return { usuario: d.u, ...p };
}

/* ---------- GitHub ---------- */
async function gh(env, token, ruta, op = {}) {
  const r = await fetch((env.GH_API || 'https://api.github.com') + ruta, {
    method: op.method || 'GET',
    headers: { 'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + token, 'User-Agent': 'editor-webs', ...(op.body ? { 'Content-Type': 'application/json' } : {}) },
    body: op.body ? JSON.stringify(op.body) : undefined,
  });
  if (r.status === 204) return null;
  let j = null; try { j = await r.json(); } catch (e) { }
  if (!r.ok) { const e = new Fallo(r.status === 401 ? 502 : r.status, 'github', 'GitHub: ' + ((j && j.message) || r.status)); e.gh = r.status; throw e; }
  return j;
}
const cacheAdmin = new Map();
async function esAdmin(env, req) {
  const t = (req.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '');
  if (!/^(github_pat_|ghp_|gho_|ghu_)[A-Za-z0-9_]{20,}$/.test(t)) throw new Fallo(401, 'admin', 'Solo Manuel, conectado con GitHub, puede hacer esto.');
  const k = b64(new Uint8Array(await crypto.subtle.digest('SHA-256', enc.encode(t))));
  const c = cacheAdmin.get(k);
  if (c && c > Date.now()) return t;
  let u;
  try { u = await gh(env, t, '/user'); } catch (e) { throw new Fallo(401, 'admin', 'GitHub no acepta ese código de acceso.'); }
  if (String(u.login).toLowerCase() !== String(env.DUENO || 'moguritto').toLowerCase()) throw new Fallo(403, 'admin', 'Ese código de GitHub no es de la cuenta de Manuel.');
  cacheAdmin.set(k, Date.now() + 5 * 60e3);
  return t;
}
async function tokenGuardado(env) {
  const v = await env.USUARIOS.get('config:gh');
  if (!v) throw new Fallo(503, 'inactivo', 'Manuel todavía no ha activado la publicación con usuario.');
  const [iv, ct] = v.split('.');
  const p = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(iv) }, await claveCifrado(env), unb64(ct));
  return dec.decode(p);
}
async function leerArchivo(env, tk, repo, path, ref) {
  try {
    const j = await gh(env, tk, `/repos/${env.DUENO || 'moguritto'}/${repo}/contents/${path.split('/').map(encodeURIComponent).join('/')}?ref=${encodeURIComponent(ref)}`);
    let bytes = j.content && j.encoding === 'base64' ? unb64(j.content) : null;
    if (!bytes) { const b = await gh(env, tk, `/repos/${env.DUENO || 'moguritto'}/${repo}/git/blobs/${j.sha}`); bytes = unb64(b.content); }
    return { sha: j.sha, bytes };
  } catch (e) { if (e.gh === 404) return null; throw e; }
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

/* ---------- Rutas ---------- */
async function rutas(req, env) {
  const url = new URL(req.url), p = url.pathname, m = req.method;
  const cuerpo = async () => { try { return await req.json(); } catch (e) { throw new Fallo(400, 'datos', 'Petición no válida.'); } };

  if (p === '/' && m === 'GET') return json(env, { servicio: 'editor-webs', ok: true });

  // --- Manuel (con su código de GitHub) ---
  if (p === '/admin/estado' && m === 'GET') {
    await esAdmin(env, req);
    const activado = !!(await env.USUARIOS.get('config:gh'));
    const lista = await env.USUARIOS.list({ prefix: 'u:' });
    const usuarios = [];
    for (const k of lista.keys) { const d = await env.USUARIOS.get(k.name, 'json'); if (d) usuarios.push(publico(k.name.slice(2), d)); }
    usuarios.sort((a, b) => (b.actualizado || 0) - (a.actualizado || 0));
    return json(env, { activado, usuarios });
  }
  if (p === '/admin/activar' && m === 'POST') {
    const t = await esAdmin(env, req);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await claveCifrado(env), enc.encode(t)));
    await env.USUARIOS.put('config:gh', b64(iv) + '.' + b64(ct));
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
    return json(env, { usuario: s.usuario, nombre: s.nombre, permisos: s.permisos });
  }
  if (p === '/leer' && m === 'GET') {
    await leerSesion(env, req);
    const repo = url.searchParams.get('repo'), path = url.searchParams.get('path') || '';
    if (!REPOS.includes(repo) || !/^docs\/[A-Za-z0-9._\/-]+$/.test(path) || path.includes('..')) throw new Fallo(400, 'datos', 'Archivo no válido.');
    const a = await leerArchivo(env, await tokenGuardado(env), repo, path, 'main');
    if (!a) throw new Fallo(404, 'nada', 'No encuentro esa página.');
    return json(env, { sha: a.sha, contenido: b64(a.bytes) });
  }
  if (p === '/publicar' && m === 'POST') {
    const s = await leerSesion(env, req);
    const d = await cuerpo();
    const repo = d.repo, archivos = d.archivos;
    if (!REPOS.includes(repo) || !Array.isArray(archivos) || !archivos.length || archivos.length > 12) throw new Fallo(400, 'datos', 'Petición no válida.');
    const paginas = new Set(s.permisos.filter((x) => x.repo === repo).map((x) => 'docs/' + x.ruta + 'index.html'));
    if (!paginas.size) throw new Fallo(403, 'permiso', 'No tienes permiso para cambiar esta web.');
    let hayPagina = false;
    for (const a of archivos) {
      if (!a || typeof a.path !== 'string') throw new Fallo(400, 'datos', 'Petición no válida.');
      const esPag = paginas.has(a.path), esFoto = RE_FOTO.test(a.path);
      if (!esPag && !esFoto) throw new Fallo(403, 'permiso', 'No tienes permiso para cambiar ' + a.path.replace(/^docs\//, '/').replace(/index\.html$/, '') + '.');
      if (esPag) hayPagina = true;
      a.esPag = esPag;
      if (a.contenido != null) {
        a.bytes = unb64(String(a.contenido));
        if (a.bytes.length > (esPag ? 3 : 6) * 1024 * 1024) throw new Fallo(413, 'grande', 'El archivo es demasiado grande.');
        if (esFoto) {
          const png = a.bytes[0] === 0x89 && a.bytes[1] === 0x50, jpg = a.bytes[0] === 0xff && a.bytes[1] === 0xd8;
          if (!(a.path.endsWith('.png') ? png : jpg)) throw new Fallo(400, 'datos', 'La foto no es un JPG o PNG válido.');
        }
      } else if (!(a.sha === null || /^[0-9a-f]{40}$/.test(a.sha || ''))) throw new Fallo(400, 'datos', 'Petición no válida.');
      if (esPag && a.contenido == null && a.sha === null) throw new Fallo(403, 'permiso', 'No se puede borrar una página.');
    }
    if (!hayPagina) throw new Fallo(400, 'datos', 'Falta la página.');

    const tk = await tokenGuardado(env), dueno = env.DUENO || 'moguritto', base = `/repos/${dueno}/${repo}`;
    const ref = await gh(env, tk, base + '/git/ref/heads/main'); const C0 = ref.object.sha;
    const T0 = (await gh(env, tk, base + '/git/commits/' + C0)).tree.sha;
    const entradas = [];
    for (const a of archivos) {
      const actual = await leerArchivo(env, tk, repo, a.path, C0);
      if ((actual ? actual.sha : null) !== (a.previo || null)) throw new Fallo(409, 'cambio', 'Alguien ha cambiado esta página mientras editabas.');
      let sha = a.sha === undefined ? undefined : a.sha;
      if (a.bytes) {
        if (a.esPag) {
          const antes = riesgos(actual ? dec.decode(actual.bytes) : ''), despues = riesgos(dec.decode(a.bytes));
          if (despues.some((n, i) => n > antes[i])) throw new Fallo(400, 'seguridad', 'El cambio añade código (scripts o formularios) y no está permitido. Solo se pueden cambiar textos, enlaces y fotos.');
        }
        sha = (await gh(env, tk, base + '/git/blobs', { method: 'POST', body: { content: b64(a.bytes), encoding: 'base64' } })).sha;
      } else if (a.esPag && sha) {
        const vuelta = await leerBlobTexto(env, tk, base, sha);
        const antes = riesgos(actual ? dec.decode(actual.bytes) : ''), despues = riesgos(vuelta);
        if (despues.some((n, i) => n > antes[i])) throw new Fallo(400, 'seguridad', 'Ese cambio añade código y no está permitido.');
      }
      entradas.push({ path: a.path, mode: '100644', type: 'blob', sha: sha === undefined ? null : sha });
    }
    const T1 = (await gh(env, tk, base + '/git/trees', { method: 'POST', body: { base_tree: T0, tree: entradas } })).sha;
    const mensaje = String(d.mensaje || 'Cambio desde el editor').slice(0, 200) + ' · por ' + s.nombre;
    const C1 = (await gh(env, tk, base + '/git/commits', { method: 'POST', body: { message: mensaje, tree: T1, parents: [C0], author: { name: s.nombre, email: 'editor@teots.org', date: new Date().toISOString() } } })).sha;
    try { await gh(env, tk, base + '/git/refs/heads/main', { method: 'PATCH', body: { sha: C1, force: false } }); }
    catch (e) { if (e.gh === 422) throw new Fallo(409, 'carrera', 'Otra persona acaba de publicar. Vuelve a intentarlo.'); throw e; }
    return json(env, { commit: C1, archivos: entradas.map((e) => ({ path: e.path, sha: e.sha })) });
  }
  throw new Fallo(404, 'nada', 'No existe.');
}
async function leerBlobTexto(env, tk, base, sha) {
  const b = await gh(env, tk, base + '/git/blobs/' + sha); return dec.decode(unb64(b.content));
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
