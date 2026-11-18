"""Genera site/vendor/ar-provincias.js (las 24 jurisdicciones de Argentina como paths SVG) desde Natural Earth.

Fuente: Natural Earth 1:10m Admin 1 - States, Provinces (dominio público), archivo
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson
Uso: python tools/geo_provincias.py <ruta al geojson>      (solo para regenerar; el visor no lo corre)
Proyección: equirectangular con la longitud escalada por cos(40°) (error de forma < 3 % en todo el país), 1 unidad = 0,01°.
Simplificación: Douglas-Peucker a 0,03°, descarta islas de menos de 0,1 grados cuadrados (salvo que sea lo único de la provincia).
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from normalizar import PROVINCIAS, REGIONES  # nombre y región salen de la única tabla del repo

TOL, K = 0.03, math.cos(math.radians(40))


def simplificar(pts, tol):
    """Douglas-Peucker iterativo sobre una lista de (x, y)."""
    if len(pts) < 4:
        return pts
    marca, pila = [False] * len(pts), [(0, len(pts) - 1)]
    marca[0] = marca[-1] = True
    while pila:
        a, b = pila.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        largo = math.hypot(dx, dy) or 1e-12
        mejor, im = 0, None
        for i in range(a + 1, b):
            dist = abs(dy * (pts[i][0] - ax) - dx * (pts[i][1] - ay)) / largo
            if dist > mejor:
                mejor, im = dist, i
        if im is not None and mejor > tol:
            marca[im] = True
            pila += [(a, im), (im, b)]
    return [p for p, m in zip(pts, marca) if m]


def area(pts):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2


def main(ruta):
    g = json.load(open(ruta, encoding="utf-8"))
    fs = [f for f in g["features"] if f["properties"].get("admin") == "Argentina"]
    assert len(fs) == 24, len(fs)
    out, minx, maxx, miny, maxy = {}, 1e9, -1e9, 1e9, -1e9
    for f in fs:
        geo = f["geometry"]
        polys = geo["coordinates"] if geo["type"] == "MultiPolygon" else [geo["coordinates"]]
        anillos = [[(lon * K, -lat) for lon, lat in poly[0]] for poly in polys]  # solo el anillo exterior
        grandes = [a for a in anillos if area(a) >= 0.1] or [max(anillos, key=area)]
        d = ""
        for a in grandes:
            m = max(range(len(a)), key=lambda i: math.hypot(a[i][0] - a[0][0], a[i][1] - a[0][1]))  # el anillo es cerrado: se parte en dos tramos
            s = simplificar(a[:m + 1], TOL)[:-1] + simplificar(a[m:], TOL)[:-1]
            d += "M" + "L".join(f"{round(x * 100)},{round(y * 100)}" for x, y in s) + "Z"
            for x, y in s:
                minx, maxx, miny, maxy = min(minx, x), max(maxx, x), min(miny, y), max(maxy, y)
        cx, cy = (sum(x for x, _ in grandes[0]) / len(grandes[0]), sum(y for _, y in grandes[0]) / len(grandes[0]))
        iso = f["properties"]["iso_3166_2"]
        out[iso] = {"n": PROVINCIAS[iso], "r": REGIONES[iso], "d": d, "c": [round(cx * 100), round(cy * 100)]}
    caja = [math.floor(minx * 100) - 50, math.floor(miny * 100) - 50, math.ceil((maxx - minx) * 100) + 100, math.ceil((maxy - miny) * 100) + 100]
    dest = Path(__file__).resolve().parent.parent / "site" / "vendor" / "ar-provincias.js"
    cab = ("// Natural Earth 1:10m Admin 1 (dominio público), simplificado con tools/geo_provincias.py. Ver site/vendor/ar-provincias.LICENSE.\n"
           "// Clave = ISO 3166-2:AR. n = nombre, r = región, d = path SVG, c = centro del anillo mayor. viewBox en centésimas de grado (longitud x cos 40°).\n")
    dest.write_text(cab + "window.AR_GEO = " + json.dumps({"viewBox": caja, "provincias": out}, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(dest, dest.stat().st_size, "bytes", caja)


if __name__ == "__main__":
    main(sys.argv[1])
