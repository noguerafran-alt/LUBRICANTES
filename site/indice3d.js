// Índice en 3D: una barra por (marca, segmento+SAE), altura = $/L mediano, color = índice contra YPF.
// Se importa con import() solo al elegir «3D» en Índice: el resto del visor no paga three.js.
// El módulo solo dibuja; qué hay en cada celda (valores, textos, motivo de «sin dato») lo arma index.html.
import * as THREE from "three";

const PASO = 1.4, ANCHO = .9, ALTO = 7;

export function webgl() {
  const c = document.createElement("canvas");
  return !!(c.getContext("webgl2") || c.getContext("webgl"));
}

// host: contenedor vacío. cols: [{g, grupo, etiqueta}], marcas: [nombre] (YPF primero = adelante).
// item(marca, g) -> {altura: número|null, indice: número|null, tip: [líneas], sd: motivo si no hay dato}. onSel(marca, g, item).
// Devuelve {cerrar()}; tira Error si no hay WebGL.
export function abrir(host, { cols, marcas, item, onSel, fmt }) {
  if (!webgl()) throw new Error("este navegador no tiene WebGL");
  const caja = document.createElement("div"); caja.className = "i3";
  const canvas = document.createElement("canvas");
  canvas.tabIndex = 0; canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", `Gráfico 3D del índice: ${marcas.length} marcas por ${cols.length} segmentos y SAE. La tabla tiene los mismos datos.`);
  const rotulos = document.createElement("div"); rotulos.className = "i3-rot";
  const tip = document.createElement("div"); tip.className = "i3-tip"; tip.hidden = true;
  caja.append(canvas, rotulos, tip); host.append(caja);
  let r;
  try { r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); } catch (e) { caja.remove(); throw new Error("no se pudo crear el contexto WebGL"); }
  r.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); r.setClearColor(0x000000, 0);

  const escena = new THREE.Scene(), cam = new THREE.PerspectiveCamera(35, 1, .1, 300);
  escena.add(new THREE.AmbientLight(0xffffff, 1.6));
  const sol = new THREE.DirectionalLight(0xffffff, 1.8); sol.position.set(-6, 12, 9); escena.add(sol);

  // tokens del tema leídos en vivo: el canvas sigue al claro/oscuro sin tocar el DOM
  const tk = {};
  const leer = () => { const cs = getComputedStyle(document.documentElement); for (const k of ["caro", "barato", "mut", "borde-ctl", "acento"]) tk[k] = new THREE.Color(cs.getPropertyValue("--" + k).trim() || "#888"); tk.ypf = new THREE.Color(document.documentElement.getAttribute("data-tema") === "oscuro" ? "#4d94ff" : "#0047ba"); };
  leer();
  const color = (m, it) => {
    if (it.altura == null) return tk["borde-ctl"];
    if (m === "YPF") return tk.ypf;
    if (it.indice == null || Math.abs(it.indice - 100) < .05) return tk.mut;   // sin YPF o igual: neutro; el tooltip dice cuál
    const t = Math.min(Math.abs(it.indice - 100) / 30, 1);   // misma escala que la tabla: 70 a 130
    return tk.mut.clone().lerp(it.indice > 100 ? tk.caro : tk.barato, .2 + .8 * t);
  };

  const geo = new THREE.BoxGeometry(1, 1, 1); geo.translate(0, .5, 0);
  const n = marcas.length, m = cols.length;
  const X = i => (i - (m - 1) / 2) * PASO, Z = j => ((n - 1) / 2 - j) * PASO;   // YPF (j = 0) al frente, SAE fino a la izquierda
  const maxV = Math.max(0, ...marcas.flatMap(mk => cols.map(c => item(mk, c.g).altura ?? 0))) || 1;
  const barras = [];
  marcas.forEach((mk, j) => cols.forEach((c, i) => {
    const it = item(mk, c.g), h = it.altura == null ? .04 : Math.max(.08, it.altura / maxV * ALTO);   // sin dato: base plana, nunca una barra
    const mat = new THREE.MeshLambertMaterial({ color: color(mk, it) });
    const b = new THREE.Mesh(geo, mat); b.scale.set(ANCHO, h, ANCHO); b.position.set(X(i), 0, Z(j));
    b.userData = { mk, g: c.g, it }; escena.add(b); barras.push(b);
  }));
  // eje vertical (esquina de atrás a la izquierda) con tres marcas
  const ex = X(0) - PASO * .9, ez = Z(n - 1) - PASO * .9;
  const eje = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(ex, 0, ez), new THREE.Vector3(ex, ALTO, ez)]), new THREE.LineBasicMaterial({ color: 0x888888 }));
  escena.add(eje);

  const puntos = [];   // rótulos HTML proyectados: texto nítido y con los colores del tema por CSS
  const rot = (txt, v, cls) => { const e = document.createElement("span"); e.className = "i3-l " + (cls || ""); e.textContent = txt; rotulos.append(e); puntos.push([e, v]); };
  cols.forEach((c, i) => rot(c.etiqueta, new THREE.Vector3(X(i), 0, Z(0) + PASO * .9), "i3-x"));
  marcas.forEach((mk, j) => rot(mk, new THREE.Vector3(X(0) - PASO * .9, 0, Z(j)), "i3-y" + (mk === "YPF" ? " i3-ypf" : "")));
  [...new Set(cols.map(c => c.grupo))].forEach(gr => { const ii = cols.map((c, i) => c.grupo === gr ? i : -1).filter(i => i >= 0); rot(gr, new THREE.Vector3((X(ii[0]) + X(ii.at(-1))) / 2, 0, Z(0) + PASO * 1.8), "i3-g"); });
  [0, .5, 1].forEach(f => rot(fmt(maxV * f), new THREE.Vector3(ex, ALTO * f, ez), "i3-z"));

  // cámara orbital mínima
  const objetivo = new THREE.Vector3(0, ALTO / 4, 0);
  let theta = -.5, phi = 1.0, dist = Math.max(10, Math.max(m, n) * PASO * 1.05 + 4);   // desde el lado izquierdo: los nombres de las marcas quedan al frente
  dist *= Math.max(1, 1.7 / (Math.max(caja.clientWidth, 200) / Math.max(caja.clientHeight, 200)));   // pantalla angosta: más lejos para que entren todas las columnas
  const L = { w: 1, h: 1 };
  let pedido = 0, vivo = true;
  const dibujar = () => { pedido = 0; if (!vivo) return;
    cam.position.set(objetivo.x + dist * Math.sin(phi) * Math.sin(theta), objetivo.y + dist * Math.cos(phi), objetivo.z + dist * Math.sin(phi) * Math.cos(theta));
    cam.lookAt(objetivo); cam.updateMatrixWorld(); r.render(escena, cam);
    const v = new THREE.Vector3();
    for (const [e, p] of puntos) { v.copy(p).project(cam); const ok = v.z < 1 && v.z > -1; e.style.display = ok ? "" : "none"; if (ok) e.style.transform = `translate(${(v.x * .5 + .5) * L.w}px, ${(-v.y * .5 + .5) * L.h}px) translate(-50%, -50%)`; }
  };
  const pedir = () => { if (!pedido && vivo) pedido = requestAnimationFrame(dibujar); };
  const medir = () => { L.w = Math.max(caja.clientWidth, 200); L.h = Math.max(caja.clientHeight, 200); r.setSize(L.w, L.h, false); cam.aspect = L.w / L.h; cam.updateProjectionMatrix(); pedir(); };
  const ro = new ResizeObserver(medir); ro.observe(caja);
  medir();
  const mo = new MutationObserver(() => { leer(); barras.forEach(b => b.material.color.copy(color(b.userData.mk, b.userData.it))); pedir(); });
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-tema"] });

  const pickea = e => {
    const rc = canvas.getBoundingClientRect(), ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - rc.left) / rc.width) * 2 - 1, -((e.clientY - rc.top) / rc.height) * 2 + 1), cam);
    return ray.intersectObjects(barras, false)[0]?.object || null;
  };
  let sobre = null;
  const mostrar = (b, e) => {
    if (sobre && sobre !== b) sobre.material.emissive.setHex(0);
    sobre = b;
    if (!b) { tip.hidden = true; return pedir(); }
    b.material.emissive.setHex(0x333333);
    const { mk, g, it } = b.userData;
    tip.replaceChildren(...[it.tip.map((t, k) => { const d = document.createElement(k ? "div" : "b"); d.textContent = t; return d; }), it.sd ? [Object.assign(document.createElement("div"), { textContent: it.sd })] : []].flat());
    tip.hidden = false;
    const rc = caja.getBoundingClientRect();
    tip.style.left = Math.min(Math.max(e.clientX - rc.left + 12, 4), Math.max(rc.width - tip.offsetWidth - 4, 4)) + "px";
    tip.style.top = Math.min(Math.max(e.clientY - rc.top + 12, 4), Math.max(rc.height - tip.offsetHeight - 4, 4)) + "px";
    pedir();
  };

  const ptrs = new Map(); let mov = 0, t0 = 0, pinch = 0;
  const d2 = () => { const [a, b] = [...ptrs.values()]; return Math.hypot(a.x - b.x, a.y - b.y) || 1; };
  const girar = (dx, dy) => { theta -= dx * .008; phi = Math.min(Math.max(phi - dy * .008, .15), 1.5); };
  const mover = (dx, dy) => { const k = dist * .0016; objetivo.x -= Math.cos(theta) * dx * k; objetivo.z += Math.sin(theta) * dx * k; objetivo.y = Math.min(Math.max(objetivo.y + dy * k, -2), ALTO * 2); };
  const zoom = f => { dist = Math.min(Math.max(dist * f, 4), 90); };
  const on = (t, f, o) => { canvas.addEventListener(t, f, o); return () => canvas.removeEventListener(t, f, o); };
  const quitar = [
    on("pointerdown", e => { canvas.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY }); mov = 0; t0 = performance.now(); if (ptrs.size === 2) pinch = d2(); }),
    on("pointermove", e => {
      const p = ptrs.get(e.pointerId);
      if (!p) return e.pointerType === "mouse" ? mostrar(pickea(e), e) : 0;
      const dx = e.clientX - p.x, dy = e.clientY - p.y; mov += Math.abs(dx) + Math.abs(dy);
      p.x = e.clientX; p.y = e.clientY;
      if (ptrs.size === 1) { (e.buttons & 2 || e.shiftKey || e.ctrlKey) ? mover(dx, dy) : girar(dx, dy); }
      else if (ptrs.size === 2) { const d = d2(); zoom(pinch / d); pinch = d; mover(dx / 2, dy / 2); }
      if (mov > 8 && sobre) mostrar(null);
      pedir();
    }),
    on("pointerup", e => {
      if (ptrs.size === 1 && mov < 8 && performance.now() - t0 < 600) {   // un toque o clic sin arrastre: tooltip y panel
        const b = pickea(e); mostrar(b, e);
        if (b) onSel(b.userData.mk, b.userData.g, b.userData.it);
      }
      ptrs.delete(e.pointerId);
    }),
    on("pointercancel", e => ptrs.delete(e.pointerId)),
    on("pointerleave", e => { if (e.pointerType === "mouse" && !ptrs.size) mostrar(null); }),
    on("contextmenu", e => e.preventDefault()),
    on("wheel", e => { e.preventDefault(); zoom(Math.exp(e.deltaY * .001)); pedir(); }, { passive: false }),
    on("keydown", e => { const k = e.key; if (k === "ArrowLeft") girar(-12, 0); else if (k === "ArrowRight") girar(12, 0); else if (k === "ArrowUp") girar(0, 12); else if (k === "ArrowDown") girar(0, -12); else if (k === "+" || k === "=") zoom(.85); else if (k === "-") zoom(1.18); else return; e.preventDefault(); pedir(); }),
  ];

  return {
    cerrar() {   // todo lo de la GPU se libera: se llama al volver a la tabla, al cambiar de pestaña y antes de redibujar
      vivo = false; cancelAnimationFrame(pedido); ro.disconnect(); mo.disconnect(); quitar.forEach(q => q());
      barras.forEach(b => b.material.dispose()); geo.dispose(); eje.geometry.dispose(); eje.material.dispose();
      r.dispose(); r.forceContextLoss(); caja.remove();
    },
  };
}
