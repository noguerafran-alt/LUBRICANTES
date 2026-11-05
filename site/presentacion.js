// Modo presentación de la Vitrina: una escena three.js por producto YPF con precio.
// Se importa con import() solo al abrir el modo: el resto del visor no paga los 690 KB de three.js.
// Usa los helpers del <script> clásico de index.html (esc, pesos, entero, dec1, TIPO, SEGMENTO, BASE, nombreVt, bloqueYpf,
// fotoOk, foto, linkUrl, icono, reducido): los const de nivel superior de un script clásico son visibles desde un módulo.
import * as THREE from "./vendor/three.module.min.js";

const DUR = 7000;  // mismo ritmo que el pase de la Vitrina
const FUENTE = 'Bahnschrift, "DIN Alternate", "Roboto Condensed", "Arial Narrow", sans-serif';
// colores de estilo para el render, no relevados del envase real
const LINEAS = [
  [/elaion/i, { cuerpo: 0xc3cbd5, metal: .55, tapa: 0x0047ba, etiqueta: "#0b3a8f" }],
  [/extravida|kilometraje/i, { cuerpo: 0xeef1f4, metal: 0, tapa: 0x0047ba, etiqueta: "#b86e00" }],
  [/r[oö]d/i, { cuerpo: 0xa8231b, metal: .05, tapa: 0x1d1d1d, etiqueta: "#5e100b" }],
  [/transmisi/i, { cuerpo: 0x39444f, metal: .2, tapa: 0xc2255c, etiqueta: "#7a1238" }],
  [/gas|gnc/i, { cuerpo: 0x1f7a4d, metal: .1, tapa: 0xeef1f4, etiqueta: "#0f4a2d" }],
];
const LINEA_DEF = { cuerpo: 0x0047ba, metal: .1, tapa: 0xeef1f4, etiqueta: "#002a70" };
const MARCA = { Shell: 0xf2c200, Castrol: 0x00843d, Mobil: 0x1c4fa1, TotalEnergies: 0xd52b1e, Elf: 0x1f3d8c, Gulf: 0xf47b20,
  Petronas: 0x00a19b, Motul: 0xc8102e, Bardahl: 0x2a2a2a, Puma: 0xb5121b, Valvoline: 0x00539b, Pennzoil: 0xf5cf00,
  "Liqui Moly": 0x0057a8, Goodyear: 0x004a97 };
const colorLinea = p => (LINEAS.find(([rx]) => rx.test(p.linea || "")) || [0, LINEA_DEF])[1];
const precio = x => typeof x?.promedio_litro === "number" ? x.promedio_litro : null;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const suave = t => 1 - Math.pow(1 - clamp(t, 0, 1), 3);

const S = { lista: [], i: 0, abierto: false, play: false, timer: null, origen: null, alCerrar: null, inertes: [] };
let dlg, escenaEl, panel, vivo, rotulosEl, btnPlay, posEl, avanceEl, notaEl;
// 3D
let R = null, escena, camara, reloj, grupo = null, rotulos = [], heroe = null, intro = 0;
const COMPARTIDAS = new Set();
const SIN_CORS = new Set();  // fotos cuyo host no permite usarlas como textura: no se vuelven a pedir en la sesión
const cam = { th: .4, ph: 1.22, r: 1, tTh: .12, tPh: 1.22, tR: 1, base: 9 };
const OBJ = new THREE.Vector3(.95, .8, 0);
const v3 = new THREE.Vector3();
let arrastre = null;

export function abrir(lista, i0, origen, alCerrar) {
  if (S.abierto || !lista.length) return;
  Object.assign(S, { lista, i: i0 || 0, abierto: true, play: false, origen, alCerrar });
  dlg = document.getElementById("pz");
  if (!dlg.dataset.listo) armar();
  dlg.hidden = false;
  // foco atrapado: todo lo demás queda inert mientras el diálogo está abierto
  S.inertes = [...document.body.children].filter(e => e !== dlg && !e.inert && e.tagName !== "SCRIPT");
  S.inertes.forEach(e => e.inert = true);
  if (R === null) R = iniciar3d() || false;
  notaEl.textContent = R ? "Arrastrá para girar la escena. Flechas o deslizar para cambiar de producto." : "Vista 2D: este navegador no tiene WebGL, se muestra la foto y la ficha completa.";
  if (R) { ajustar(); R.setAnimationLoop(document.hidden ? null : cuadro); }
  mostrar(S.i, false);
  dlg.querySelector(".pz-cerrar").focus();
}

function armar() {
  dlg.dataset.listo = "1";
  dlg.innerHTML = `
    <div class="pz-barra">
      <button type="button" class="pz-btn" data-paso="-1" aria-label="Producto anterior">${icono("prev")}</button>
      <span class="pz-pos" aria-hidden="true"></span>
      <div class="pz-avance" aria-hidden="true"><i></i></div>
      <button type="button" class="pz-btn" id="pz-play"></button>
      <button type="button" class="pz-btn" data-paso="1" aria-label="Producto siguiente">${icono("next")}</button>
      <button type="button" class="pz-cerrar" aria-label="Salir del modo presentación (Esc)">${icono("cerrar")}<span>Salir</span></button>
    </div>
    <div class="pz-escena"><div class="pz-rotulos" aria-hidden="true"></div><p class="pz-ayuda"></p></div>
    <aside class="pz-panel" tabindex="0" aria-label="Características del producto"></aside>
    <p class="sr" aria-live="polite" aria-atomic="true"></p>`;
  escenaEl = dlg.querySelector(".pz-escena"); panel = dlg.querySelector(".pz-panel"); vivo = dlg.querySelector("p.sr");
  rotulosEl = dlg.querySelector(".pz-rotulos"); btnPlay = dlg.querySelector("#pz-play"); posEl = dlg.querySelector(".pz-pos");
  avanceEl = dlg.querySelector(".pz-avance i"); notaEl = dlg.querySelector(".pz-ayuda");
  dlg.querySelectorAll("[data-paso]").forEach(b => b.onclick = () => { pausar(); paso(+b.dataset.paso); });
  btnPlay.onclick = () => { if (reducido.matches) return; S.play = !S.play; programar(); };
  dlg.querySelector(".pz-cerrar").onclick = cerrar;
  dlg.addEventListener("keydown", e => {
    if (e.key === "Escape") { e.preventDefault(); cerrar(); }
    else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !e.target.closest?.("input, select, textarea")) { e.preventDefault(); pausar(); paso(e.key === "ArrowRight" ? 1 : -1); }
  });
  // Esc con pantalla completa la cierra el navegador sin keydown: salir de pantalla completa = salir del modo
  document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && S.abierto) cerrar(); });
  document.addEventListener("visibilitychange", () => { if (!S.abierto) return; if (R) R.setAnimationLoop(document.hidden ? null : cuadro); programar(); });
  reducido.addEventListener("change", () => { if (S.abierto) { if (reducido.matches) S.play = false; programar(); } });
  // arrastre lento = girar; deslizamiento rápido horizontal = cambiar de producto (también en la vista 2D)
  escenaEl.addEventListener("pointerdown", e => { arrastre = { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, t: performance.now() }; escenaEl.setPointerCapture(e.pointerId); escenaEl.classList.add("agarra"); });
  escenaEl.addEventListener("pointermove", e => {
    if (!arrastre) return;
    cam.tTh = clamp(cam.tTh - (e.clientX - arrastre.x) * .006, -1.1, 1.3);
    cam.tPh = clamp(cam.tPh - (e.clientY - arrastre.y) * .004, .9, 1.45);
    arrastre.x = e.clientX; arrastre.y = e.clientY;
  });
  const soltarPuntero = e => {
    if (!arrastre) return;
    const dx = e.clientX - arrastre.x0, dy = e.clientY - arrastre.y0, dt = performance.now() - arrastre.t;
    arrastre = null; escenaEl.classList.remove("agarra");
    if (e.type === "pointerup" && Math.abs(dx) > 60 && dt < 350 && Math.abs(dx) > Math.abs(dy) * 1.5) { pausar(); paso(dx < 0 ? 1 : -1); }
  };
  escenaEl.addEventListener("pointerup", soltarPuntero);
  escenaEl.addEventListener("pointercancel", soltarPuntero);
  escenaEl.addEventListener("wheel", e => { if (!R) return; e.preventDefault(); cam.tR = clamp(cam.tR * (1 + e.deltaY * .001), .6, 1.4); }, { passive: false });
  new ResizeObserver(() => { if (R && S.abierto) ajustar(); }).observe(escenaEl);
}

function cerrar() {
  if (!S.abierto) return;
  S.abierto = false; S.play = false; clearTimeout(S.timer);
  if (R) { R.setAnimationLoop(null); limpiar(); }
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  dlg.hidden = true;
  S.inertes.forEach(e => e.inert = false);
  S.alCerrar?.(S.lista[S.i]);
  S.origen?.focus();
}

const pausar = () => { if (S.play) { S.play = false; programar(); } };
const paso = d => mostrar(S.i + d);

// el ícono dice lo que pasa de verdad: play si no corre, pausa si corre
function programar() {
  clearTimeout(S.timer); S.timer = null;
  const corre = S.abierto && S.play && !reducido.matches && !document.hidden && S.lista.length > 1;
  if (corre) S.timer = setTimeout(() => mostrar(S.i + 1), DUR);
  btnPlay.hidden = S.lista.length < 2;
  btnPlay.setAttribute("aria-disabled", reducido.matches);
  btnPlay.innerHTML = icono(corre ? "pausa" : "play");
  const txt = reducido.matches ? "Pase automático desactivado: el sistema pide reducir el movimiento" : corre ? "Pausar el pase automático" : "Pasar los productos solos cada 7 segundos";
  btnPlay.setAttribute("aria-label", txt); btnPlay.title = txt;
  dlg.classList.toggle("corre", corre);
  vivo.setAttribute("aria-live", corre ? "off" : "polite");
}

function mostrar(i, animar = true) {
  const n = S.lista.length;
  S.i = ((i % n) + n) % n;
  const p = S.lista[S.i];
  posEl.textContent = `${S.i + 1} de ${n}`;
  avanceEl.style.width = ((S.i + 1) / n * 100) + "%";
  panel.innerHTML = ficha(p);
  panel.scrollTop = 0;
  vivo.textContent = `${S.i + 1} de ${n}: ${nombreVt(p)}`;
  if (R) escena3d(p, animar && !reducido.matches);
  else {
    escenaEl.querySelector(".pz-2d")?.remove();
    escenaEl.insertAdjacentHTML("afterbegin", `<figure class="pz-2d">${foto(p.imagen, nombreVt(p), true)}</figure>`);
  }
  programar();
}

// ---------- panel: todas las características ----------
function ficha(p) {
  const s = p.specs, nom = nombreVt(p), c = p.competencia || {}, eqs = c.equivalentes || [];
  const sd = v => v ? esc(v) : `<span class="vacio">sin dato en el catálogo</span>`;
  const chips = [p.sae && `<li class="sae">${esc(p.sae)}</li>`, BASE[p.base] && `<li>${BASE[p.base]}</li>`, p.segmento && `<li>${esc(SEGMENTO[p.segmento] || p.segmento)}</li>`].filter(Boolean).join("");
  const oem = s?.oem?.length ? `<ul class="pz-oem">${s.oem.map(o => `<li>${esc(o)}</li>`).join("")}</ul>` : `<span class="vacio">sin homologaciones OEM en el catálogo</span>`;
  const specs = !s ? `<p class="vt-vacio">La API no trajo la especificación técnica de este producto.</p>`
    : `<dl class="pz-dl">
        <dt>API</dt><dd>${sd(s.api)}</dd><dt>ACEA</dt><dd>${sd(s.acea)}</dd><dt>ILSAC</dt><dd>${sd(s.ilsac)}</dd><dt>JASO</dt><dd>${sd(s.jaso)}</dd>
        <dt>OEM</dt><dd>${oem}</dd>
        <dt>Datos técnicos</dt><dd>${s.verificado === "confirmado" ? '<span class="badge confirmada">confirmados en ficha</span>' : s.verificado === "inferido" ? '<span class="badge">inferidos, sin ficha confirmada</span>' : '<span class="vacio">sin estado de verificación</span>'}${s.fuente_specs ? ` ${linkUrl(s.fuente_specs, "ver fuente")}` : ""}</dd>
      </dl>`;
  const pc = precio(c), d = p.dif_pct;
  const comp = !eqs.some(e => e.tipo !== "no_equivalente") ? `<p class="vt-vacio">Sin equivalentes cargados para este producto.</p>`
    : pc === null ? `<p class="vt-vacio">Sin precio de competencia hoy: ningún equivalente apareció con stock en los últimos 3 días.</p>`
    : `<p class="vt-precio">${porL(pc)}</p><p class="vt-rango">Promedio por litro de ${entero.format(c.n)} observaciones. De ${pesos.format(c.min_litro)} a ${pesos.format(c.max_litro)}.</p>
      ${typeof d !== "number" ? `<p class="vt-vacio">Sin diferencia: falta el precio YPF de hoy.</p>` : Math.abs(d) < .05 ? `<p class="vt-dif">Mismo precio por litro que YPF</p>`
        : `<p class="vt-dif ${d > 0 ? "barato" : "caro"}">${d > 0 ? `YPF ${dec1.format(d)} % más barato` : `YPF ${dec1.format(-d)} % más caro`}</p>`}`;
  const fuera = e => e.tipo === "no_equivalente" ? "no equivalente, fuera del promedio" : e.excluido === "fuera_de_rango" ? "precio fuera de rango, fuera del promedio" : "";
  const filas = eqs.map(e => `<tr${e.en_promedio === false ? ' class="fuera"' : ""}><td>${esc(e.marca)} ${esc(e.nombre)}${fuera(e) ? `<span class="mut">${fuera(e)}</span>` : ""}</td>
      <td>${esc(TIPO[e.tipo] || e.tipo)}</td><td>${esc(e.evidencia)}</td>
      <td class="n">${typeof e.promedio_litro === "number" ? `${pesos.format(e.promedio_litro)}<span class="mut">${entero.format(e.n)} obs.</span>` : '<span class="vacio">sin precio hoy</span>'}</td></tr>`).join("");
  return `<p class="pz-linea">${esc(p.linea || "")}</p>
    <h2 class="pz-nombre">${esc(nom)}</h2>
    ${chips ? `<ul class="vt-specs" aria-label="Especificación">${chips}</ul>` : ""}
    <div class="pz-sec">${bloqueYpf(p.ypf)}</div>
    <div class="pz-sec"><div class="vt-bloque comp"><h4>Competencia equivalente</h4>${comp}</div></div>
    <div class="pz-sec"><h3>Especificación técnica</h3>${specs}</div>
    ${eqs.length ? `<div class="pz-sec"><h3>Equivalentes</h3><div class="pz-tabla"><table class="pz-eqs"><tr><th>Producto</th><th>Tipo</th><th>Evidencia</th><th class="n">$/L hoy</th></tr>${filas}</table></div></div>` : ""}`;
}

// ---------- 3D ----------
function iniciar3d() {
  const prueba = document.createElement("canvas");
  if (!(prueba.getContext("webgl2") || prueba.getContext("webgl"))) return null;
  const canvas = document.createElement("canvas");
  canvas.setAttribute("role", "img");
  let r;
  try { r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" }); }
  catch { return null; }
  escenaEl.prepend(canvas);
  r.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = 1.05;
  r.outputColorSpace = THREE.SRGBColorSpace;
  r.setClearColor(0x000000, 0);
  escena = new THREE.Scene();
  camara = new THREE.PerspectiveCamera(30, 1, .1, 60);
  reloj = new THREE.Clock();
  const pm = new THREE.PMREMGenerator(r), est = estudio();
  escena.environment = pm.fromScene(est, .04).texture;
  pm.dispose(); soltar(est);
  const llave = new THREE.DirectionalLight(0xffffff, 1.5); llave.position.set(-3, 6, 5); escena.add(llave);
  const borde = new THREE.DirectionalLight(0x9cc0ff, 1.4); borde.position.set(4, 3, -5); escena.add(borde);
  const pisoTex = radial(256, [[0, "#fff"], [.5, "#888"], [1, "#000"]]);
  COMPARTIDAS.add(pisoTex);
  const piso = new THREE.Mesh(new THREE.CircleGeometry(7, 64), new THREE.MeshStandardMaterial({ color: 0x1a4488, roughness: .9, alphaMap: pisoTex, transparent: true, depthWrite: false }));
  piso.rotation.x = -Math.PI / 2; piso.position.x = OBJ.x;
  escena.add(piso);
  S.sombra = radial(128, [[0, "#c8c8c8"], [.45, "#5a5a5a"], [1, "#000"]]);
  COMPARTIDAS.add(S.sombra);
  return r;
}

// ambiente de estudio (como RoomEnvironment): caja oscura con softboxes emisivos, solo para el PMREM
function estudio() {
  const s = new THREE.Scene();
  s.add(new THREE.Mesh(new THREE.BoxGeometry(12, 12, 12), new THREE.MeshBasicMaterial({ color: 0x14223c, side: THREE.BackSide })));
  for (const [w, h, col, k, pos] of [[5, 3, 0xffffff, 5, [0, 5.5, 1]], [1.4, 6, 0xffffff, 3.5, [-5.5, 1, 2]], [1.4, 6, 0xcfe0ff, 3, [5.5, 1, -1]], [8, 1.2, 0xffffff, 1.6, [0, .6, -5.8]]]) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(col).multiplyScalar(k), side: THREE.DoubleSide }));
    m.position.set(...pos); m.lookAt(0, 0, 0); s.add(m);
  }
  return s;
}

function radial(n, stops) {
  const c = document.createElement("canvas"); c.width = c.height = n;
  const x = c.getContext("2d"); x.fillStyle = "#000"; x.fillRect(0, 0, n, n);
  const g = x.createRadialGradient(n / 2, n / 2, 0, n / 2, n / 2, n / 2);
  stops.forEach(([o, col]) => g.addColorStop(o, col));
  x.fillStyle = g; x.fillRect(0, 0, n, n);
  return new THREE.CanvasTexture(c);
}

// silueta frontal del bidón: 4 L con manija (agujero en la silueta), 1 L sin manija y hombro inclinado
function silueta(o) {
  const { w, h, nx, nr, asa } = o, r = w * .2, s = new THREE.Shape();
  s.moveTo(-w + r, 0); s.lineTo(w - r, 0); s.quadraticCurveTo(w, 0, w, r);
  if (asa) { s.lineTo(w, h - r); s.quadraticCurveTo(w, h, w - r, h); s.lineTo(nx + nr, h); }
  else { s.lineTo(w, h * .74); s.quadraticCurveTo(w, h, nx + nr, h); }
  s.lineTo(nx - nr, h);
  s.quadraticCurveTo(-w, h, -w, h * .76);
  s.lineTo(-w, r); s.quadraticCurveTo(-w, 0, -w + r, 0);
  if (asa) {
    const x0 = nx + nr + .14, x1 = w - .17, y0 = h * .6, y1 = h - .15, q = .07, a = new THREE.Path();
    a.moveTo(x0 + q, y0); a.lineTo(x1 - q, y0); a.quadraticCurveTo(x1, y0, x1, y0 + q); a.lineTo(x1, y1 - q); a.quadraticCurveTo(x1, y1, x1 - q, y1);
    a.lineTo(x0 + q, y1); a.quadraticCurveTo(x0, y1, x0, y1 - q); a.lineTo(x0, y0 + q); a.quadraticCurveTo(x0, y0, x0 + q, y0);
    s.holes.push(a);
  }
  return s;
}

function envase(litros, col, conEtiqueta) {
  const o = litros >= 3 ? { w: .62, h: 1.62, d: .62, nx: -.3, nr: .13, asa: true } : { w: .44, h: 1.42, d: .42, nx: -.12, nr: .1, asa: false };
  const b = .05, prof = o.d - 2 * b, g = new THREE.Group();
  const geo = new THREE.ExtrudeGeometry(silueta(o), { depth: prof, bevelEnabled: true, bevelThickness: b, bevelSize: b, bevelSegments: 4, curveSegments: 18 });
  geo.translate(0, b, -prof / 2);
  const mat = new THREE.MeshPhysicalMaterial({ color: col.cuerpo, metalness: col.metal, roughness: .3, clearcoat: .7, clearcoatRoughness: .22 });
  g.add(new THREE.Mesh(geo, mat));
  const tope = o.h + 2 * b;
  const cuello = new THREE.Mesh(new THREE.CylinderGeometry(o.nr * .92, o.nr, .1, 28), mat);
  cuello.position.set(o.nx, tope + .03, 0); g.add(cuello);
  const tapa = new THREE.Mesh(new THREE.CylinderGeometry(o.nr * 1.12, o.nr * 1.16, .2, 28), new THREE.MeshPhysicalMaterial({ color: col.tapa, roughness: .45, clearcoat: .4 }));
  tapa.position.set(o.nx, tope + .17, 0); g.add(tapa);
  if (conEtiqueta) g.userData.etiqueta = { lw: o.w * 1.72, lh: o.h * .52, y: o.h * .37 + b, z: o.d / 2 + .004 };
  const so = new THREE.Mesh(new THREE.PlaneGeometry(o.w * 3.4, o.d * 3.6), new THREE.MeshBasicMaterial({ color: 0x000000, alphaMap: S.sombra, transparent: true, depthWrite: false, opacity: .85 }));
  so.rotation.x = -Math.PI / 2; so.position.y = .003; g.add(so);
  return g;
}

// etiqueta del envase YPF: nombre, SAE, base y la foto real si el host permite CORS (si no, va sin foto)
function etiqueta(p, col, lw, lh) {
  const W = 1024, H = Math.round(W * lh / lw), c = document.createElement("canvas");
  c.width = W; c.height = H;
  const x = c.getContext("2d"), t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = Math.min(8, R.capabilities.getMaxAnisotropy());
  const ajustarTxt = (txt, peso, tam, ancho) => { do x.font = `${peso} ${tam}px ${FUENTE}`; while (x.measureText(txt).width > ancho && (tam -= 2) > 10); };
  const dibujar = img => {
    x.fillStyle = col.etiqueta; x.fillRect(0, 0, W, H);
    x.fillStyle = "rgba(255,255,255,.08)"; x.fillRect(0, H * .78, W, H * .22);
    const pad = W * .06, fw = img ? H * .7 : 0, ancho = W - pad * 2 - (fw ? fw + pad : 0);
    x.fillStyle = "#fff"; x.textBaseline = "alphabetic";
    x.font = `700 ${H * .12}px ${FUENTE}`; x.fillText("YPF", pad, pad + H * .1);
    ajustarTxt(p.linea || "", 600, H * .13, ancho); x.fillText(p.linea || "", pad, H * .36);
    ajustarTxt(p.nombre || "", 500, H * .1, ancho); x.globalAlpha = .9; x.fillText(p.nombre || "", pad, H * .5); x.globalAlpha = 1;
    if (p.sae) { ajustarTxt(p.sae, 700, H * .2, ancho); x.fillText(p.sae, pad, H * .73); }
    x.font = `500 ${H * .075}px ${FUENTE}`; x.globalAlpha = .85;
    x.fillText([BASE[p.base], SEGMENTO[p.segmento]].filter(Boolean).join(", "), pad, H * .92); x.globalAlpha = 1;
    if (img) {
      const fx = W - pad - fw, fy = (H * .78 - fw) / 2 + H * .02;
      x.fillStyle = "#fff"; x.beginPath(); x.roundRect(fx, fy, fw, fw, 18); x.fill();
      const k = Math.min((fw - 24) / img.naturalWidth, (fw - 24) / img.naturalHeight), iw = img.naturalWidth * k, ih = img.naturalHeight * k;
      x.drawImage(img, fx + (fw - iw) / 2, fy + (fw - ih) / 2, iw, ih);
    }
    t.needsUpdate = true;
  };
  dibujar(null);
  if (fotoOk(p.imagen) && !SIN_CORS.has(p.imagen)) {
    const im = new Image();
    im.crossOrigin = "anonymous"; im.referrerPolicy = "no-referrer";
    im.onload = () => { if (!t.userData.muerta) try { dibujar(im); } catch { dibujar(null); } };
    im.onerror = () => SIN_CORS.add(p.imagen);
    im.src = p.imagen;
  }
  return t;
}

function soltar(o) {
  o.traverse(m => {
    m.geometry?.dispose();
    for (const mt of [].concat(m.material || [])) {
      for (const k of ["map", "alphaMap"]) if (mt[k] && !COMPARTIDAS.has(mt[k])) { mt[k].userData.muerta = true; mt[k].dispose(); }
      mt.dispose();
    }
  });
}

function limpiar() {
  if (grupo) { escena.remove(grupo); soltar(grupo); grupo = null; }
  rotulosEl.innerHTML = ""; rotulos = []; heroe = null;
}

function escena3d(p, animar) {
  limpiar();
  grupo = new THREE.Group();
  const col = colorLinea(p), litros = p.ypf?.presentacion_comun_l || 1;
  heroe = envase(litros, col, true);
  const e = heroe.userData.etiqueta;
  const lbl = new THREE.Mesh(new THREE.PlaneGeometry(e.lw, e.lh), new THREE.MeshStandardMaterial({ map: etiqueta(p, col, e.lw, e.lh), roughness: .5 }));
  lbl.position.set(0, e.y, e.z); heroe.add(lbl);
  heroe.position.set(-1.35, 0, .7);
  heroe.rotation.y = .35;
  grupo.add(heroe);

  // rótulos al pie de cada podio (misma línea de base para todos); cuadro() los reparte en filas para que no se pisen
  // podios: YPF y cada equivalente que entra al promedio; altura proporcional al $/L, sin precio = sin podio
  const eqs = (p.competencia?.equivalentes || []).filter(q => q.tipo !== "no_equivalente" && !q.excluido);
  const items = [{ ypf: true, marca: "YPF", nombre: nombreVt(p), v: precio(p.ypf) }, ...eqs.map(q => ({ marca: q.marca, nombre: q.nombre, v: precio(q) }))]
    .sort((a, b) => (a.v ?? Infinity) - (b.v ?? Infinity));
  const max = Math.max(...items.map(q => q.v || 0)) || 1, n = items.length, apretado = n > (escenaEl.clientWidth < 600 ? 3 : 5);
  const x0 = .15, x1 = 3.5, xc = (x0 + x1) / 2, sep = n > 1 ? (x1 - x0) / (n - 1) : 0;
  items.forEach((q, k) => {
    const x = n > 1 ? x0 + sep * k : xc, u = n > 1 ? (x - xc) / ((x1 - x0) / 2) : 0, z = -.75 + .4 * u * u;
    const h = q.v ? q.v / max * 1.15 : 0, ancla = new THREE.Group();
    ancla.position.set(x, 0, z);
    let barra = null;
    if (h) {
      barra = new THREE.Mesh(new THREE.BoxGeometry(.34, 1, .34).translate(0, .5, 0), q.ypf
        ? new THREE.MeshPhysicalMaterial({ color: 0x0047ba, emissive: 0x0a3aa0, emissiveIntensity: .55, roughness: .28, clearcoat: .8 })
        : new THREE.MeshPhysicalMaterial({ color: 0x8794a5, roughness: .38, metalness: .25, clearcoat: .4 }));
      ancla.add(barra);
    }
    const chico = envase(1, q.ypf ? col : { cuerpo: MARCA[q.marca] ?? 0x9aa4ae, metal: .1, tapa: 0x1d1d1d }, false);
    chico.scale.setScalar(.36); chico.rotation.y = -.25;
    ancla.add(chico);
    grupo.add(ancla);
    const div = document.createElement("div");
    div.className = "pz-rot" + (q.ypf ? " ypf" : "") + (apretado ? " apretado" : "");
    div.innerHTML = `<b>${esc(q.marca)}</b><span>${esc(q.nombre)}</span>${q.v ? `<span class="v">${pesos.format(q.v)}/L</span>` : '<span class="sin">sin precio hoy</span>'}`;
    rotulosEl.append(div);
    rotulos.push({ div, ancla, barra, chico, h, k, sx: 0, sy: 0, w: 0, alto: 0 });
  });
  escena.add(grupo);
  const conPrecio = items.filter(q => q.v).length;
  R.domElement.setAttribute("aria-label", `Envase de ${nombreVt(p)} en primer plano y ${n} podios de precio por litro (${conPrecio} con precio hoy), de menor a mayor.`);
  intro = animar ? performance.now() : -1e6;
  if (animar) { cam.th = cam.tTh + .45; cam.r = cam.tR * 1.12; }
}

function ajustar() {
  const w = escenaEl.clientWidth, h = escenaEl.clientHeight;
  if (!w || !h) return;
  R.setSize(w, h, false);
  camara.aspect = w / h; camara.updateProjectionMatrix();
  const tv = Math.tan(THREE.MathUtils.degToRad(camara.fov / 2)), th = tv * camara.aspect;
  cam.base = Math.max(3.3 / th, 1.5 / tv);  // que entren el envase y todos los podios, a lo ancho y a lo alto
}

function cuadro() {
  const dt = Math.min(.05, reloj.getDelta()), k = 1 - Math.exp(-dt * 5);
  cam.th += (cam.tTh - cam.th) * k; cam.ph += (cam.tPh - cam.ph) * k; cam.r += (cam.tR - cam.r) * k;
  const r = cam.base * cam.r;
  camara.position.set(OBJ.x + r * Math.sin(cam.ph) * Math.sin(cam.th), OBJ.y + r * Math.cos(cam.ph), OBJ.z + r * Math.sin(cam.ph) * Math.cos(cam.th));
  camara.lookAt(OBJ);
  const t = performance.now() - intro;
  if (heroe) {
    if (!reducido.matches && !arrastre) heroe.rotation.y += dt * .3;
    const a = suave(t / 700);
    heroe.scale.setScalar(.9 + .1 * a); heroe.position.y = .3 * (1 - a);
  }
  const w = escenaEl.clientWidth, h = escenaEl.clientHeight;
  for (const q of rotulos) {
    const a = suave((t - 150 - q.k * 90) / 650), alto = q.h * a;
    if (q.barra) q.barra.scale.y = Math.max(.001, alto);
    q.chico.position.y = alto;
    v3.set(0, 0, .3); q.ancla.localToWorld(v3); v3.project(camara);
    q.div.style.opacity = v3.z > 1 || a <= 0 ? 0 : a;
    q.sx = (v3.x + 1) / 2 * w; q.sy = (1 - v3.y) / 2 * h;
    v3.set(0, alto + .5, 0); q.ancla.localToWorld(v3); v3.project(camara); q.arriba = (1 - v3.y) / 2 * h;  // tope del envase chico
    if (!q.w) { q.w = q.div.offsetWidth; q.alto = q.div.offsetHeight; }  // tamaño fijo por escena: se mide una vez
  }
  // al girar la cámara los podios se juntan en pantalla (y por la perspectiva cada uno cae a otra altura): de izquierda a derecha,
  // cada rótulo baja de a una fila hasta que su caja no toque ninguna de las ya ubicadas
  // si abajo no hay lugar (se saldría de la escena o taparía la ayuda), prueba hacia arriba desde el tope de su envase
  const puestas = [], piso = h - (notaEl?.offsetHeight || 0) - 14;
  const choca = (x0, x1, y, alto) => puestas.some(b => x0 < b.x1 && b.x0 < x1 && y < b.y1 + 2 && b.y0 < y + alto + 2);
  for (const q of [...rotulos].sort((a, b) => a.sx - b.sx)) {
    const x0 = q.sx - q.w / 2 - 3, x1 = q.sx + q.w / 2 + 3, paso = q.alto + 4;
    let y = q.sy;
    while (choca(x0, x1, y, q.alto) && y + paso + q.alto <= piso) y += paso;
    if (choca(x0, x1, y, q.alto) || y + q.alto > piso) {
      y = q.arriba - q.alto - 4;
      while (choca(x0, x1, y, q.alto) && y - paso >= 0) y -= paso;
    }
    puestas.push({ x0, x1, y0: y, y1: y + q.alto });
    q.div.style.transform = `translate(${q.sx.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, 0)`;
  }
  R.render(escena, camara);
}
