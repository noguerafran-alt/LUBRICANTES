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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=5)
    ap.add_argument("--solo", default="")
    ap.add_argument("--resolucion", type=int, default=192)
    ap.add_argument("--caras", type=int, default=20000)
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
            x = np.array(img).astype(np.float32) / 255.0
            x = x[:, :, :3] * x[:, :, 3:4] + (1 - x[:, :, 3:4]) * 0.5
            img = Image.fromarray((x * 255.0).astype(np.uint8))
            with torch.no_grad():
                codigos = modelo([img], device="cpu")
                malla = modelo.extract_mesh(codigos, True, resolution=a.resolucion)[0]
            print(f"{pid}: {len(malla.faces)} caras crudas", flush=True)
            destino = SALIDA / f"{pid}.glb"
            malla.export(destino)
            print(f"{pid}: {destino.stat().st_size / 1e6:.1f} MB en {time.time() - t0:.0f} s", flush=True)
        except Exception as e:  # una foto mala no frena la tanda
            fallas += 1
            print(f"{pid}: FALLÓ {type(e).__name__}: {e}", flush=True)
    sys.exit(1 if fallas == len(lista) else 0)


if __name__ == "__main__":
    main()
