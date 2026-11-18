"""Foto → modelo 3D (GLB) con Blender, un archivo por producto en site/modelos/.

Se corre con el Python de Blender (no con el del server, que sigue siendo stdlib):
    blender -b --factory-startup -P tools/modelos3d.py -- [--limite N] [--solo ID] [--forzar] [--fotos DIR]
    blender -b --factory-startup -P tools/modelos3d.py -- test

La forma sale de la silueta de la foto: se separa el envase del fondo, se infla con los bordes
redondeados (profundidad proporcional al ancho) y se espeja atrás. La foto es la textura, proyectada
de frente: la etiqueta queda exacta; el dorso repite el frente sin espejar.
Orientación del GLB (glTF, Y arriba): frente mirando a +Z, base en y=0, alto 1.
"""
import argparse
import collections
import csv
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "site" / "modelos"
UA = "LUBRICANTES/1.0 (modelos 3D de envases)"
FILAS = 200          # resolución vertical de la grilla de la máscara (antes de diezmar)
CARAS = 9000         # triángulos objetivo por modelo
TEX = 1024           # lado mayor de la textura
TOPE = 450_000       # bytes por GLB: más que esto es un error del generador
# Baldes de 20 L: cilindro (la silueta de frente no distingue un balde de un bidón chato).
BALDES = ("ypf-extravida-", "ypf-elaion-nautico-2t", "ypf-super-20w50", "ypf-transferencia-termica",
          "shell-rimula-r3-l-", "shell-rimula-r6-lm-", "shell-rimula-r6-ms-")
# Fotos que no muestran un solo envase: mejor el bidón genérico del visor que un modelo falso.
DESCARTES = {
    "motul-moto-mineral-20w50": "pack de 12 botellas",
    "puma-2t-semisintetico": "envase con su caja",
    "totalenergies-quartz-9000-future-gf6-0w20": "dos envases",
    "totalenergies-quartz-ineo-long-life-5w30": "dos envases",
    "valvoline-moto-4t-10w40": "foto ambientada, fondo no liso",
    "ypf-gnc-super-20w50": "envase blanco sobre fondo blanco: no se separa",
    "ypf-rod-2t": "familia de envases",
    "ypf-rod-4t-10w30": "dos envases",
    "ypf-rod-4t-10w40": "dos envases",
    "ypf-rod-4t-20w50": "dos envases",
}


# ---------------------------------------------------------------- imagen → máscara

def leer(ruta):
    """RGBA float [0,1], fila 0 arriba."""
    import bpy
    im = bpy.data.images.load(str(ruta))
    w, h = im.size
    a = np.empty(w * h * 4, np.float32)
    im.pixels.foreach_get(a)
    bpy.data.images.remove(im)
    return a.reshape(h, w, 4)[::-1].copy()


def reducir(a, filas):
    """Promedio por bloques hasta ~`filas` de alto (sin dependencias)."""
    h, w = a.shape[:2]
    k = max(1, h // filas)
    h2, w2 = h // k, w // k
    return a[:h2 * k, :w2 * k].reshape(h2, k, w2, k, -1).mean(axis=(1, 3))


def componentes(m):
    """Etiquetas 4-conexas de una máscara booleana (BFS; las máscaras son chicas)."""
    h, w = m.shape
    et = np.zeros((h, w), np.int32)
    n = 0
    for y0, x0 in zip(*np.nonzero(m)):
        if et[y0, x0]:
            continue
        n += 1
        et[y0, x0] = n
        q = collections.deque([(y0, x0)])
        while q:
            y, x = q.popleft()
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < h and 0 <= xx < w and m[yy, xx] and not et[yy, xx]:
                    et[yy, xx] = n
                    q.append((yy, xx))
    return et, n


def fondo_conectado(rgb, cerca):
    """Fondo = lo que se alcanza desde el borde pasando por píxeles del color del fondo, o por degradés suaves
    y grises (sombra apoyada): el contorno del envase corta el paso aunque el envase sea blanco."""
    h, w = cerca.shape
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    suave = (cerca < .3) & (sat < .1)
    f = np.zeros((h, w), bool)
    q = collections.deque()
    for y, x in [(0, x) for x in range(w)] + [(h - 1, x) for x in range(w)] + [(y, 0) for y in range(h)] + [(y, w - 1) for y in range(h)]:
        if cerca[y, x] < .1 and not f[y, x]:
            f[y, x] = True
            q.append((y, x))
    while q:
        y, x = q.popleft()
        for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= yy < h and 0 <= xx < w and not f[yy, xx] and (
                    cerca[yy, xx] < .04 or (suave[yy, xx] and np.abs(rgb[yy, xx] - rgb[y, x]).max() < .012)):
                f[yy, xx] = True
                q.append((yy, xx))
    return f


def mascara(a, huecos=True):
    """→ (máscara del envase, motivo de descarte o None). `a` RGBA chica, fila 0 arriba.
    `huecos`: recortar el hueco de la manija (no en baldes, cuya tapa gris se confunde con el fondo)."""
    rgb, al = a[..., :3], a[..., 3]
    if (al < .5).mean() > .02:  # PNG/WebP con transparencia real
        fondo = al < .5
    else:
        borde = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
        med = np.median(borde, axis=0)
        cerca = np.abs(rgb - med).max(axis=2)
        if (np.abs(borde - med).max(axis=1) < .08).mean() < .6:
            return None, "fondo no liso"
        # fondo = lo parecido al color del borde y conectado al borde (las partes blancas de la etiqueta no)
        parecido = cerca < .07
        fondo = fondo_conectado(rgb, cerca)
        # hueco de la manija: zona encerrada, del color del fondo, chica y lisa, en la mitad de arriba
        et2, n2 = componentes(parecido & ~fondo)
        env = ~fondo
        ys = np.nonzero(env.any(axis=1))[0]
        y_tope = ys[0] + .4 * (ys[-1] - ys[0])  # las manijas van arriba; un óvalo blanco de etiqueta, más abajo
        area = env.sum()
        for i in range(1, n2 + 1 if huecos else 1):
            r = et2 == i
            yy = np.nonzero(r)[0]
            if .004 * area < r.sum() < .15 * area and yy.mean() < y_tope and cerca[r].std() < .03:
                fondo |= r
    env = ~fondo
    et, n = componentes(env)
    if not n:
        return None, "sin envase"
    tam = np.bincount(et.ravel())[1:]
    orden = np.argsort(tam)[::-1]
    if n > 1 and tam[orden[1]] > .45 * tam[orden[0]]:
        return None, "varios envases"
    env = et == orden[0] + 1
    # agujeros chicos (ruido) adentro del envase se rellenan; los grandes (manija) quedan
    et3, n3 = componentes(~env)
    for i in range(1, n3 + 1):
        r = et3 == i
        if r.sum() < .004 * env.sum() and not (r[0].any() or r[-1].any() or r[:, 0].any() or r[:, -1].any()):
            env |= r
    return env, None


# ---------------------------------------------------------------- máscara → alturas

def corridas(m):
    """Distancia (en px, +.5) al fondo más cercano hacia cada lado, por fila: izquierda, derecha."""
    h, w = m.shape
    izq = np.zeros((h, w), np.float32)
    der = np.zeros((h, w), np.float32)
    c = np.zeros(h, np.float32)
    for x in range(w):
        c = np.where(m[:, x], c + 1, 0)
        izq[:, x] = c
    c = np.zeros(h, np.float32)
    for x in range(w - 1, -1, -1):
        c = np.where(m[:, x], c + 1, 0)
        der[:, x] = c
    return izq - .5, der - .5


def perfil(d, prof, r):
    """Media profundidad a distancia `d` del borde: pared, canto redondeado de radio `r`, frente plano."""
    d = np.minimum(d, r)
    return prof - r + np.sqrt(np.maximum(r * r - (r - d) ** 2, 0))


def alturas(m, balde=False):
    """Media profundidad por píxel (en px). Clase: balde (cilindro), bidón con manija o botella."""
    h, w = m.shape
    ys, xs = np.nonzero(m)
    alto, ancho = np.ptp(ys) + 1, np.ptp(xs) + 1
    huecos_cerrados = componentes(~m)[1] > 1
    # ponytail: tres proporciones fijas de profundidad/ancho (bidón .42, balde 1, botella .55); la foto no dice
    # la profundidad real. Si un envase se ve muy chato o muy gordo, sumar la proporción por producto acá.
    if balde:
        prop, ry = 1.0, .06
    elif huecos_cerrados:
        prop, ry = .42, .3
    else:
        prop, ry = .55, .3
    prof = prop * ancho / 2
    il, ir = corridas(m)
    dh = np.minimum(il, ir)
    medio = (il + ir) / 2  # media anchura de la corrida: lo angosto (tapa, manija) queda cilíndrico
    loc = np.minimum(prof, medio)
    rx = np.where(medio <= prof, loc, .35 * prof)
    zh = perfil(dh, loc, np.maximum(rx, .5))
    it, ib = corridas(m.T)
    dv = np.minimum(it, ib).T
    zv = perfil(dv, prof, max(ry * prof, 1.0))
    z = np.minimum(zh, zv)
    for _ in range(2):  # suaviza los quiebres entre corridas (bordes de la manija)
        p = np.pad(z, 1)
        z = np.where(m, (p[1:-1, 1:-1] * 4 + p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]) / 8, 0)
    return z.astype(np.float32)


# ---------------------------------------------------------------- textura

def textura(rgb, m, ruta):
    """Foto recortada al envase, con el fondo rellenado por los colores del borde (sin halo blanco)."""
    import bpy
    rgb = rgb.copy()
    lleno = m.copy()
    for _ in range(12):
        p = np.pad(rgb * lleno[..., None], ((1, 1), (1, 1), (0, 0)))
        q = np.pad(lleno.astype(np.float32), 1)
        s = p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]
        n = q[:-2, 1:-1] + q[2:, 1:-1] + q[1:-1, :-2] + q[1:-1, 2:]
        nuevo = ~lleno & (n > 0)
        rgb[nuevo] = s[nuevo] / n[nuevo][:, None]
        lleno |= nuevo
    h, w = m.shape
    im = bpy.data.images.new("etiqueta", w, h)
    im.pixels.foreach_set(np.dstack([rgb, np.ones((h, w))])[::-1].astype(np.float32).ravel())
    k = TEX / max(w, h)
    if k < 1:
        im.scale(max(1, round(w * k)), max(1, round(h * k)))
    esc = bpy.context.scene
    esc.render.image_settings.file_format = "JPEG"
    esc.render.image_settings.quality = 85
    im.save_render(str(ruta), scene=esc)
    bpy.data.images.remove(im)
    return bpy.data.images.load(str(ruta))


# ---------------------------------------------------------------- malla

def malla(m, z):
    """Grilla sobre la máscara: vértices en centros de píxel, borde en z=0, contorno suavizado."""
    h, w = m.shape
    idx = -np.ones((h, w), np.int64)
    ys, xs = np.nonzero(m)
    idx[ys, xs] = np.arange(len(ys))
    q = m[:-1, :-1] & m[1:, :-1] & m[:-1, 1:] & m[1:, 1:]
    qy, qx = np.nonzero(q)
    caras = np.stack([idx[qy + 1, qx], idx[qy + 1, qx + 1], idx[qy, qx + 1], idx[qy, qx]], 1)  # normal hacia -Y (frente)
    usados = np.unique(caras)
    # aristas de borde = usadas por una sola cara
    ar = np.concatenate([caras[:, [0, 1]], caras[:, [1, 2]], caras[:, [2, 3]], caras[:, [3, 0]]])
    ar.sort(axis=1)
    u, c = np.unique(ar, axis=0, return_counts=True)
    borde = u[c == 1]
    pos = np.stack([xs, ys], 1).astype(np.float64)
    zz = z[ys, xs].astype(np.float64)
    eb = np.unique(borde)
    zz[eb] = 0
    vec = collections.defaultdict(list)
    for a, b in borde:
        vec[a].append(b)
        vec[b].append(a)
    for _ in range(4):  # escalones de píxel → contorno liso (solo en el plano)
        nuevo = pos.copy()
        for v, ns in vec.items():
            nuevo[v] = .5 * pos[v] + .5 * pos[ns].mean(axis=0)
        pos = nuevo
    # se compacta a los vértices usados
    mapa = -np.ones(len(ys), np.int64)
    mapa[usados] = np.arange(len(usados))
    return pos[usados], zz[usados], mapa[caras]


def armar(pid, foto, carpeta):
    """→ ruta del GLB o (None, motivo)."""
    import bmesh
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    a = leer(foto)
    chica = reducir(a, FILAS * 2)
    balde = pid.startswith(BALDES)
    m, motivo = mascara(chica, huecos=not balde)
    if m is None:
        return None, motivo
    m = reducir(m[..., None].astype(np.float32), FILAS)[..., 0] > .5
    et, n = componentes(m)  # al reducir puede quedar una isla suelta: se queda la mayor
    if not n:
        return None, "sin envase"
    m = et == np.bincount(et.ravel())[1:].argmax() + 1
    if balde:  # la sombra apoyada ensancha la base: cada fila se recorta al ancho del cuerpo
        filas = np.nonzero(m.any(axis=1))[0]
        medio = filas[len(filas) // 4: 3 * len(filas) // 4]
        izq = np.median([np.argmax(m[y]) for y in medio])
        der = np.median([m.shape[1] - 1 - np.argmax(m[y, ::-1]) for y in medio])
        m[:, :max(0, int(izq) - 1)] = False
        m[:, int(der) + 2:] = False
    ys, xs = np.nonzero(m)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    m = np.pad(m[y0:y1, x0:x1], 1)
    h, w = m.shape
    z = alturas(m, balde)
    pos, zz, caras = malla(m, z)
    # textura: la foto en resolución completa, recortada a la misma caja (k = píxeles de foto por celda)
    k = max(1, a.shape[0] // (FILAS * 2)) * max(1, chica.shape[0] // FILAS)
    fy0, fx0 = (y0 - 1) * k, (x0 - 1) * k
    rec = a[max(0, fy0):fy0 + h * k, max(0, fx0):fx0 + w * k]
    mg = np.repeat(np.repeat(m, k, 0), k, 1)[:rec.shape[0], :rec.shape[1]]
    img = textura(rec[..., :3], mg, carpeta / f"{pid}.jpg")
    # coordenadas: X derecha, Z arriba (alto 1, base en 0), -Y frente
    esc = 1.0 / (y1 - y0)
    vx = (pos[:, 0] - w / 2) * esc
    vz = (h - 1 - pos[:, 1] - 1) * esc
    vy = -zz * esc
    uv_u = (pos[:, 0] + .5) / w
    uv_v = 1 - (pos[:, 1] + .5) / h
    me = bpy.data.meshes.new(pid)
    bm = bmesh.new()
    vs = [bm.verts.new((float(a_), float(b_), float(c_))) for a_, b_, c_ in zip(vx, vy, vz)]
    bm.verts.ensure_lookup_table()
    uvl = bm.loops.layers.uv.new("UVMap")
    for f in caras:
        cara = bm.faces.new([vs[i] for i in f])
        for lo, i in zip(cara.loops, f):  # los vértices nuevos de bmesh no tienen índice todavía
            lo[uvl].uv = (uv_u[i], uv_v[i])
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(pid, me)
    bpy.context.scene.collection.objects.link(ob)
    for p in me.polygons:
        p.use_smooth = True
    mi = ob.modifiers.new("dorso", "MIRROR")
    mi.use_axis = (False, True, False)
    mi.use_mirror_merge = True
    mi.merge_threshold = 1e-5
    mi.use_mirror_u = True  # el dorso lee la etiqueta al derecho
    de = ob.modifiers.new("liviano", "DECIMATE")
    de.ratio = min(1.0, CARAS / (len(caras) * 4))
    mat = bpy.data.materials.new("envase")
    if bpy.app.version < (5, 0):
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Metallic"].default_value = 0
    bsdf.inputs["Roughness"].default_value = .5
    tx = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tx.image = img
    tx.extension = "EXTEND"
    mat.node_tree.links.new(tx.outputs["Color"], bsdf.inputs["Base Color"])
    me.materials.append(mat)
    destino = carpeta / f"{pid}.glb"
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.export_scene.gltf(filepath=str(destino), export_format="GLB", use_selection=True, export_apply=True,
                              export_image_format="AUTO", export_yup=True, export_texcoords=True, export_normals=True,
                              export_materials="EXPORT", export_animations=False)
    return destino, None


# ---------------------------------------------------------------- lista y bajada

def pendientes(solo=None, forzar=False):
    with open(RAIZ / "data" / "imagenes.csv", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    filas.sort(key=lambda r: (not r["producto_id"].startswith("ypf-"), r["producto_id"]))
    return [r for r in filas if (not solo or r["producto_id"] == solo)
            and (forzar or not (SALIDA / f"{r['producto_id']}.glb").exists())]


def bajar(url, destino):
    p = urllib.parse.urlsplit(url)  # hay URLs de VTEX con espacios en el nombre del archivo
    url = urllib.parse.urlunsplit(p._replace(path=urllib.parse.quote(p.path)))
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
        destino.write_bytes(r.read())


def main(args):
    ap = argparse.ArgumentParser(prog="modelos3d")
    ap.add_argument("--limite", type=int, default=200)
    ap.add_argument("--solo", default="")
    ap.add_argument("--forzar", action="store_true", help="regenera aunque el GLB ya exista")
    ap.add_argument("--fotos", default="", help="carpeta con fotos ya bajadas (<producto_id>.<ext>)")
    ap.add_argument("--salida", default=str(SALIDA))
    a = ap.parse_args(args)
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    lista = pendientes(a.solo, a.forzar)[:a.limite]
    print(f"{len(lista)} modelos a generar", flush=True)
    fallas = 0
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for r in lista:
            t0, pid = time.time(), r["producto_id"]
            viejo = salida / f"{pid}.glb"
            if pid in DESCARTES:
                print(f"{pid}: descartado ({DESCARTES[pid]})", flush=True)
                viejo.unlink(missing_ok=True)
                continue
            try:
                cache = list(Path(a.fotos).glob(f"{pid}.*")) if a.fotos else []
                foto = cache[0] if cache else td / f"{pid}{Path(urllib.parse.urlsplit(r['url']).path).suffix or '.img'}"
                if not cache:
                    bajar(r["url"], foto)
                glb, motivo = armar(pid, foto, td)
                if glb is None:
                    print(f"{pid}: sin modelo ({motivo})", flush=True)
                    viejo.unlink(missing_ok=True)
                    continue
                peso = glb.stat().st_size
                assert peso < TOPE, f"{peso} bytes"
                glb.replace(viejo)
                print(f"{pid}: {peso / 1e3:.0f} KB en {time.time() - t0:.1f} s", flush=True)
            except Exception as e:  # una foto mala no frena la tanda
                fallas += 1
                print(f"{pid}: FALLÓ {type(e).__name__}: {e}", flush=True)
    sys.exit(1 if lista and fallas == len(lista) else 0)


def demo():
    """Máscara, hueco de manija y alturas sobre una foto sintética."""
    a = np.ones((120, 100, 4), np.float32)
    a[20:110, 20:80, :3] = (.1, .2, .7)          # envase azul sobre blanco
    a[30:50, 30:50, :3] = 1.0                    # hueco de manija (arriba, color del fondo)
    a[70:90, 35:65, :3] = (.98, .98, .98)        # blanco de etiqueta, encerrado y abajo: no es hueco
    m, motivo = mascara(a)
    assert motivo is None and m[60, 50] and not m[5, 5]
    assert not m[40, 40], "el hueco de arriba se recorta"
    assert m[80, 50], "lo blanco de la etiqueta en la mitad de abajo no es hueco"
    z = alturas(m)
    assert z[5, 5] == 0 and z[60, 50] > 10 and z[60, 21] < z[60, 50]
    pos, zz, caras = malla(m, z)
    assert len(caras) and zz.min() == 0 and caras.max() < len(pos)
    b = a.copy()
    b[:, :, :3] = 1.0
    b[10:50, 10:40, :3] = .2
    b[60:110, 55:90, :3] = .3
    assert mascara(b) == (None, "varios envases")
    print("OK")


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if args[:1] == ["test"]:
        demo()
    else:
        main(args)
