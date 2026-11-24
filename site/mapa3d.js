// Mapa 3D del precio puesto: cada provincia (path de AR_GEO) extruida; altura = $/L mínimo puesto, color = el de la capa plana.
// Se importa con import() solo al elegir «3D»: el resto del visor no paga three.js. Solo dibuja; los valores y motivos los arma index.html.
import * as THREE from "three";
import { webgl, controles } from "./indice3d.js";

export { webgl };
const ALTO = 9, S = .01;   // las coordenadas de AR_GEO son centésimas de grado: 1 unidad de escena = 1 grado

// "M x,yL x,y…Z" -> anillos [[x,y]…]. Un anillo por M (islas incluidas); AR_GEO no trae huecos.
const anillos = d => (d.match(/[MLZ][^MLZ]*/g) || []).reduce((a, t) => {
  if (t[0] === "M") a.push([]);
  if (t[0] !== "Z") a.at(-1).push(t.slice(1).split(",").map(Number));
  return a;
}, []).filter(r => r.length > 2);

// items: [{iso, d, altura: número|null, color: css, tip: [líneas], sd: motivo si no hay precio}].
// Devuelve {cerrar(), marcar(iso)}; tira Error si no hay WebGL.
export function abrir(host, { items, sel, onSel, etiqueta }) {
  if (!webgl()) throw new Error("este navegador no tiene WebGL");
  const caja = document.createElement("div"); caja.className = "i3";
  const canvas = document.createElement("canvas");
  canvas.tabIndex = 0; canvas.setAttribute("role", "img"); canvas.setAttribute("aria-label", etiqueta);
  const tip = document.createElement("div"); tip.className = "i3-tip"; tip.hidden = true;
  caja.append(canvas, tip); host.replaceChildren(caja);
  let r;
  try { r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); } catch (e) { caja.remove(); throw new Error("no se pudo crear el contexto WebGL"); }
  r.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); r.setClearColor(0x000000, 0);
  const escena = new THREE.Scene(), cam = new THREE.PerspectiveCamera(35, 1, .1, 400);
  escena.add(new THREE.AmbientLight(0xffffff, 1.6));
  const sol = new THREE.DirectionalLight(0xffffff, 1.8); sol.position.set(-10, 25, 20); escena.add(sol);

  // textura rayada de «sin precio»: la misma que el SVG plano
  const cv = document.createElement("canvas"); cv.width = cv.height = 64;
  const g = cv.getContext("2d"); g.fillStyle = "#eef0f3"; g.fillRect(0, 0, 64, 64); g.strokeStyle = "#b8bec7"; g.lineWidth = 16;
  for (const k of [-64, 0, 64]) { g.beginPath(); g.moveTo(k, 64); g.lineTo(k + 64, 0); g.stroke(); }
  const raya = new THREE.CanvasTexture(cv); raya.wrapS = raya.wrapT = THREE.RepeatWrapping; raya.repeat.set(.7, .7);

  const maxV = Math.max(0, ...items.map(i => i.altura ?? 0)) || 1;
  const cx = -5686 + 1625 / 2, cy = 2128 + 3427 / 2;   // centro del viewBox
  const mats = [], geos = [], mallas = [];
  for (const it of items) {
    const mat = new THREE.MeshLambertMaterial(it.altura == null ? { map: raya } : { color: new THREE.Color(it.color) });
    if (it.iso === "AR-C") { mat.polygonOffset = true; mat.polygonOffsetFactor = mat.polygonOffsetUnits = -2; }   // CABA queda dentro de Buenos Aires: que no pelee la profundidad
    mats.push(mat);
    const h = it.altura == null ? .05 : Math.max(.12, it.altura / maxV * ALTO);   // sin precio: placa plana, nunca una altura inventada
    for (const ring of anillos(it.d)) {
      const sh = new THREE.Shape(ring.map(([x, y]) => new THREE.Vector2((x - cx) * S, -(y - cy) * S)));
      const ge = new THREE.ExtrudeGeometry(sh, { depth: 1, bevelEnabled: false }); geos.push(ge);
      const m = new THREE.Mesh(ge, mat); m.rotation.x = -Math.PI / 2; m.scale.z = h; m.userData = { it }; escena.add(m); mallas.push(m);
    }
  }

  const o = { objetivo: new THREE.Vector3(0, 2, 0), theta: 0, phi: .85, dist: 52, ymax: ALTO * 2 };
  let pedido = 0, vivo = true, w = 1, hh = 1;
  const dibujar = () => { pedido = 0; if (!vivo) return;
    cam.position.set(o.objetivo.x + o.dist * Math.sin(o.phi) * Math.sin(o.theta), o.objetivo.y + o.dist * Math.cos(o.phi), o.objetivo.z + o.dist * Math.sin(o.phi) * Math.cos(o.theta));
    cam.lookAt(o.objetivo); r.render(escena, cam);
  };
  const pedir = () => { if (!pedido && vivo) pedido = requestAnimationFrame(dibujar); };
  const medir = () => { w = Math.max(caja.clientWidth, 200); hh = Math.max(caja.clientHeight, 200); r.setSize(w, hh, false); cam.aspect = w / hh; cam.updateProjectionMatrix(); pedir(); };
  const ro = new ResizeObserver(medir); ro.observe(caja); medir();

  let sobre = null, marcada = sel || null;
  const brillo = () => mallas.forEach(m => m.material.emissive.setHex(m.userData.it.iso === sobre ? 0x444444 : m.userData.it.iso === marcada ? 0x2a2a2a : 0));
  const pickea = e => {
    const rc = canvas.getBoundingClientRect(), ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - rc.left) / rc.width) * 2 - 1, -((e.clientY - rc.top) / rc.height) * 2 + 1), cam);
    return ray.intersectObjects(mallas, false)[0]?.object.userData.it || null;
  };
  const mostrar = (it, e) => {
    sobre = it?.iso || null; brillo();
    if (!it) { tip.hidden = true; return pedir(); }
    tip.replaceChildren(...[...it.tip.map((t, k) => { const d = document.createElement(k ? "div" : "b"); d.textContent = t; return d; }), ...(it.sd ? [Object.assign(document.createElement("div"), { textContent: it.sd })] : [])]);
    tip.hidden = false;
    const rc = caja.getBoundingClientRect();
    tip.style.left = Math.min(Math.max(e.clientX - rc.left + 12, 4), Math.max(rc.width - tip.offsetWidth - 4, 4)) + "px";
    tip.style.top = Math.min(Math.max(e.clientY - rc.top + 12, 4), Math.max(rc.height - tip.offsetHeight - 4, 4)) + "px";
    pedir();
  };
  brillo();
  const quitar = controles(canvas, o, { pedir, pickea, hover: mostrar, clic: (it, e) => { mostrar(it, e); if (it) { marcada = it.iso; brillo(); onSel(it.iso); } } });

  return {
    marcar(iso) { marcada = iso; brillo(); pedir(); },
    cerrar() {   // libera la GPU: al volver a Plano, al cambiar de capa o de pestaña y antes de redibujar
      vivo = false; cancelAnimationFrame(pedido); ro.disconnect(); quitar();
      mats.forEach(m => m.dispose()); geos.forEach(x => x.dispose()); raya.dispose();
      r.dispose(); r.forceContextLoss(); caja.remove();
    },
  };
}
