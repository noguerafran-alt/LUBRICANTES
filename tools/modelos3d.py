"""Foto → modelo 3D (GLB) con TripoSR, un archivo por producto en site/modelos/.

Corre solo en la Action modelos3d.yml (PyTorch y TripoSR no entran en el server ni en la
corrida diaria, que siguen siendo stdlib). Genera únicamente lo que todavía no tiene modelo:
primero YPF, después sus equivalentes. Una foto que falla se saltea y queda en el log.
"""
import argparse
import csv
import io
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "site" / "modelos"
UA = "LUBRICANTES/1.0 (modelos 3D de envases)"


def pendientes(solo=None):
    with open(RAIZ / "data" / "imagenes.csv", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    filas.sort(key=lambda r: (not r["producto_id"].startswith("ypf-"), r["producto_id"]))
    return [r for r in filas if (not solo or r["producto_id"] == solo)
            and not (SALIDA / f"{r['producto_id']}.glb").exists()]


def bajar(url):
    # Hay URLs de VTEX con espacios en el nombre del archivo.
    p = urllib.parse.urlsplit(url)
    url = urllib.parse.urlunsplit(p._replace(path=urllib.parse.quote(p.path)))
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
        return r.read()


def con_foto(malla, foto):
    """Proyecta la foto sobre la cara que TripoSR vio: el color por vértice deja la etiqueta borrosa.
    El lado y el sentido se eligen comparando con esos colores, así no depende de la convención de cámara.
    → trimesh.Scene, o None si ningún candidato coincide (queda solo el color por vértice)."""
    import numpy as np
    import trimesh
    from trimesh.visual.material import PBRMaterial
    from trimesh.visual.texture import TextureVisuals

    a = np.array(foto)
    ys, xs = np.nonzero(a[:, :, 3] > 128)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    alto, ancho = a.shape[:2]
    v, col = malla.vertices, malla.visual.vertex_colors[:, :3].astype(float)
    mejor = None
    for lado in (1, -1):
        d = 1.9 - lado * v[:, 0]  # perspectiva de la cámara de condicionamiento de TripoSR
        for sentido in (1, -1):
            px, pz = sentido * v[:, 1] / d, v[:, 2] / d
            vis = lado * malla.vertex_normals[:, 0] > 0.3
            fx = (px - px[vis].min()) / np.ptp(px[vis])
            fz = (pz - pz[vis].min()) / np.ptp(pz[vis])
            cx = np.clip(x0 + fx * (x1 - x0), 0, ancho - 1)
            cy = np.clip(y1 - fz * (y1 - y0), 0, alto - 1)
            err = np.abs(a[cy.astype(int), cx.astype(int), :3] - col)[vis].mean()
            if mejor is None or err < mejor[0]:
                mejor = (err, lado, cx / ancho, 1 - cy / alto)
    err, lado, u, w = mejor
    print(f"  proyección: error de color {err:.0f}/255, lado {lado}", flush=True)
    if err > 60:
        return None
    frente = lado * malla.face_normals[:, 0] > 0.25
    adelante = malla.submesh([np.nonzero(frente)[0]], append=True)
    atras = malla.submesh([np.nonzero(~frente)[0]], append=True)
    idx = malla.faces[frente].reshape(-1)
    # submesh reindexa los vértices: se recuperan sus UV por posición
    orden = {tuple(p): i for i, p in zip(idx, malla.vertices[idx])}
    sel = [orden[tuple(p)] for p in adelante.vertices]
    fondo = a[:, :, :3][a[:, :, 3] > 128].mean(axis=0)
    rgb = a[:, :, :3] * (a[:, :, 3:4] / 255.0) + fondo * (1 - a[:, :, 3:4] / 255.0)
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(rgb.astype("uint8")).resize((1024, 1024)).save(buf, "JPEG", quality=85)
    buf.seek(0)
    tex = Image.open(buf)  # con format=JPEG trimesh lo embebe así; sin él usa PNG y el modelo pesa el triple
    adelante.visual = TextureVisuals(uv=np.c_[u[sel], w[sel]], material=PBRMaterial(
        baseColorTexture=tex, metallicFactor=0.0, roughnessFactor=0.55))
    if lado < 0:  # el frente siempre mira a +x: el visor no tiene que saber de qué lado salió
        giro = trimesh.transformations.rotation_matrix(np.pi, [0, 0, 1])
        adelante.apply_transform(giro)
        atras.apply_transform(giro)
    return trimesh.Scene([adelante, atras])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=5)
    ap.add_argument("--solo", default="")
    ap.add_argument("--resolucion", type=int, default=144)  # el frente lo da la foto: la malla puede ser liviana
    a = ap.parse_args()

    lista = pendientes(a.solo)[:a.limite]
    print(f"{len(lista)} modelos a generar", flush=True)
    if not lista:
        return

    import numpy as np
    import rembg
    import torch
    from PIL import Image
    from tsr.system import TSR
    from tsr.utils import remove_background, resize_foreground

    modelo = TSR.from_pretrained("stabilityai/TripoSR", config_name="config.yaml", weight_name="model.ckpt")
    modelo.renderer.set_chunk_size(8192)
    modelo.to("cpu")
    sesion = rembg.new_session()
    SALIDA.mkdir(parents=True, exist_ok=True)

    fallas = 0
    for r in lista:
        t0, pid = time.time(), r["producto_id"]
        try:
            img = Image.open(io.BytesIO(bajar(r["url"]))).convert("RGBA")
            img = resize_foreground(remove_background(img, sesion), 0.85)
            recorte = img
            x = np.array(img).astype(np.float32) / 255.0
            x = x[:, :, :3] * x[:, :, 3:4] + (1 - x[:, :, 3:4]) * 0.5
            img = Image.fromarray((x * 255.0).astype(np.uint8))
            with torch.no_grad():
                codigos = modelo([img], device="cpu")
                malla = modelo.extract_mesh(codigos, True, resolution=a.resolucion)[0]
            print(f"{pid}: {len(malla.faces)} caras crudas", flush=True)
            destino = SALIDA / f"{pid}.glb"
            (con_foto(malla, recorte) or malla).export(destino, file_type="glb")
            print(f"{pid}: {destino.stat().st_size / 1e6:.1f} MB en {time.time() - t0:.0f} s", flush=True)
        except Exception as e:  # una foto mala no frena la tanda
            fallas += 1
            print(f"{pid}: FALLÓ {type(e).__name__}: {e}", flush=True)
    sys.exit(1 if fallas == len(lista) else 0)


if __name__ == "__main__":
    main()
