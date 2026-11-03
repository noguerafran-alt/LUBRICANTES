"""SEPA / Precios Claros: baja el zip del día, filtra lubricantes y agrega por comercio.

python sepa.py        # una corrida: escribe data/obs/AAAA-MM.csv y una fila en data/fuentes.csv
python sepa.py test   # asserts del filtro y del agregado, sin red
"""
import csv
import io
import json
import re
import shutil
import statistics
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

from normalizar import normalizar

RAIZ = Path(__file__).parent
CKAN = "https://datos.produccion.gob.ar/api/3/action/package_show?id=sepa-precios"
UA = "LUBRICANTES/1.0 (relevamiento de precios de lubricantes; github actions)"
OBS_F = "fecha,fuente,url,ean,titulo,marca,precio,precio_lista,stock,vendedor,sucursal,litros,unidades,producto_id,match".split(",")
FUE_F = "fecha,fuente,http,n_items,n_con_precio,n_sin_stock,n_sin_match,error".split(",")

YPF_EAN = "779096891"  # el prefijo YPF también trae líquido de frenos: lo saca NO
ACEITE = re.compile(r"\b(aceite|lubri\w*)\b")
MOTOR = re.compile(r"\b\d{1,2} ?w ?-? ?\d{2}\b|\b[24] ?t\b|\bmotor\b|\bsae\b")
NO = re.compile(r"multiuso|wd ?-?40|preserv|\bgel\b|\bfreno\b|refrigerante")


def bajar(url, destino=None):
    """GET con timeout 30 s y un reintento. Con destino copia en streaming y devuelve bytes bajados."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for intento in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if destino is None:
                    return r.read()
                shutil.copyfileobj(r, destino, 1 << 20)
                return destino.tell()
        except OSError:
            if intento == 2:
                raise
            if destino is not None:
                destino.seek(0)
                destino.truncate()
            time.sleep(5)


def ultimo_zip(paquete):
    """(fecha, url) del zip más nuevo. Los 7 zips rotan por día de semana; la fecha sale de la descripción."""
    mejores = []
    for r in paquete["resources"]:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", r.get("description") or "")
        if m and r.get("url", "").endswith(".zip"):
            mejores.append((m.group(1), r["url"]))
    return max(mejores)


cache = {}


def es_lubricante(ean, desc, marca):
    """Devuelve el dict de normalizar si la fila es lubricante, si no None. Cacheado: se repite por sucursal."""
    k = (ean, desc, marca)
    if k not in cache:
        t = desc.lower()
        n = None
        if not NO.search(t) and (ean.startswith(YPF_EAN) or ACEITE.search(t)):
            n = normalizar(desc, marca, ean)
            if not (ean.startswith(YPF_EAN) or MOTOR.search(t) or n["marca"]):
                n = None
        cache[k] = n
    return cache[k]


def leer_comercio(iz, grupos, cuenta):
    """Agrega las filas de lubricantes de un zip interno en grupos[(comercio, bandera, ean)]."""
    banderas = {}
    with iz.open("comercio.csv") as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace"), delimiter="|"):
            banderas[(r["id_comercio"], r.get("id_bandera"))] = (r.get("comercio_bandera_nombre") or r.get("comercio_razon_social") or "").strip()
    with iz.open("productos.csv") as f:
        lineas = io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace")
        cab = next(lineas).rstrip("\r\n").split("|")
        for linea in lineas:
            s = linea.lower()
            # filtro barato antes de partir la línea: 14 M filas por día
            if "aceit" not in s and "lubri" not in s and "|" + YPF_EAN not in s:
                continue
            r = dict(zip(cab, linea.rstrip("\r\n").split("|")))
            ean, desc = r["id_producto"].strip(), r["productos_descripcion"].strip()
            n = es_lubricante(ean, desc, r["productos_marca"].strip())
            if n is None:
                continue
            cuenta["filas"] += 1
            k = (r["id_comercio"], r["id_bandera"], ean)
            g = grupos.setdefault(k, {"titulo": desc, "n": n, "vendedor": banderas.get(k[:2], ""), "precios": []})
            try:
                g["precios"].append(float(r["productos_precio_lista"]))
            except ValueError:
                g["precios"].append(0.0)


def agregar(fecha, grupos):
    """Una fila por (comercio, bandera, EAN).

    Decisión: no se guarda una fila por sucursal. Carrefour y ChangoMás son ~1.400 filas/día
    por sucursal (~0,5 M/año) contra ~60-120 agregadas. precio = mediana de precio_lista
    entre sucursales; la dispersión queda en sucursal como "n=37;min=79999;max=82990".
    Se usa precio_lista (precio de góndola), no las promos, y precio_lista del CSV va vacío.
    Sucursales con precio <= 0 no entran a la mediana; si no queda ninguna, no hay fila.
    """
    filas, sin_precio = [], 0
    for (comercio, bandera, ean), g in sorted(grupos.items()):
        ps = sorted(p for p in g["precios"] if p > 0)
        if not ps:
            sin_precio += 1
            continue
        n = g["n"]
        filas.append({
            "fecha": fecha, "fuente": "sepa", "url": "", "ean": ean, "titulo": g["titulo"],
            "marca": n["marca"], "precio": f"{statistics.median(ps):.2f}", "precio_lista": "", "stock": "",
            "vendedor": g["vendedor"] or f"comercio {comercio}-{bandera}",
            "sucursal": f"n={len(ps)};min={ps[0]:.2f};max={ps[-1]:.2f}",
            "litros": n["litros"], "unidades": n["unidades"], "producto_id": n["producto_id"], "match": n["match"],
        })
    return filas, sin_precio


def escribir_obs(fecha, filas):
    """Reemplaza las filas sepa de esa fecha en data/obs/AAAA-MM.csv."""
    p = RAIZ / "data" / "obs" / f"{fecha[:7]}.csv"
    viejas = []
    if p.exists():
        with open(p, encoding="utf-8", newline="") as f:
            viejas = [r for r in csv.DictReader(f) if not (r["fuente"] == "sepa" and r["fecha"] == fecha)]
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OBS_F, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(viejas + filas)


def escribir_fuente(fila):
    p = RAIZ / "data" / "fuentes.csv"
    nuevo = not p.exists()
    with open(p, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FUE_F, lineterminator="\n")
        if nuevo:
            w.writeheader()
        w.writerow(fila)


def correr():
    t0 = time.time()
    try:
        fecha, url = ultimo_zip(json.loads(bajar(CKAN))["result"])
        grupos, cuenta = {}, {"filas": 0}
        # el zip externo necesita seek (directorio al final): va a un temporal que se borra solo.
        # Los zips internos vienen sin comprimir (stored), así que se abren y leen de a línea sin extraerlos.
        with tempfile.TemporaryFile() as tmp:
            mb = bajar(url, tmp) / 1e6
            with zipfile.ZipFile(tmp) as z:
                for info in z.infolist():
                    if info.filename.endswith(".zip") and info.file_size:
                        with zipfile.ZipFile(z.open(info)) as iz:
                            leer_comercio(iz, grupos, cuenta)
        filas, sin_precio = agregar(fecha, grupos)
    except Exception as e:
        http = getattr(e, "code", "")
        escribir_fuente({"fecha": date.today().isoformat(), "fuente": "sepa", "http": http, "n_items": 0,
                         "n_con_precio": 0, "n_sin_stock": 0, "n_sin_match": 0, "error": f"{type(e).__name__}: {e}"[:200]})
        raise
    escribir_obs(fecha, filas)
    escribir_fuente({"fecha": fecha, "fuente": "sepa", "http": 200, "n_items": len(grupos), "n_con_precio": len(filas),
                     "n_sin_stock": sin_precio, "n_sin_match": sum(f["match"] == "none" for f in filas),
                     "error": "" if grupos else "sin lubricantes en el zip, revisar filtro"})
    print(f"sepa {fecha}: {mb:.0f} MB, {cuenta['filas']} filas por sucursal -> {len(filas)} filas escritas, {time.time() - t0:.0f} s")


def demo():
    n = lambda ean, d, m="": es_lubricante(ean, d, m) is not None
    assert n("7790968914633", "ACEITE ELAION MI 1540 X 4", "ELAION")
    assert n("7790968914428", "AURO FE 5W30 1L", "SIN MARCA")  # YPF por prefijo, sin "aceite"
    assert n("7798056300153", "ACEITE GULF MAX 15W 40 X 4L", "GULF")
    assert n("7790627112509", "ACEITE 10W40 SEMISINTETICO 4 X 4 L", "GENERICO")
    assert n("7798095102299", "LUBRICANTE SELENIA K 15W40 1L", "PETRONAS")
    assert n("7790627701673", "ACEITE BARDAHL 4T MOTOS 20W50 X 1 L", "BARDAHL")
    assert not n("7790968912714", "LIQ FRENO DOT 3 B1L", "YPF")
    assert not n("7790272000794", "Aceite MAZOLA de maíz PET-900-cc.", "MAZOLA")
    assert not n("0079567552635", "LUBRICANTE WD 40 155 GRS", "WD-40")
    assert not n("7798194560051", "PRESERVATIVO EXTRA LUBRICADO PLAYBOY CAJA X 3 UNI", "PLAYBOY")
    assert not n("2628716000008", "LUBRICANTE CARREFOUR MULTIUSO X 160G", "CARREFOUR")
    assert not n("7790580131357", "ATUN EN ACEITE LOMITOS LA CAMPAGNOLA X 170 GRS", "LA CAMPAGNOLA")

    cab = "id_comercio|id_bandera|id_sucursal|id_producto|productos_ean|productos_descripcion|productos_cantidad_presentacion|productos_unidad_medida_presentacion|productos_marca|productos_precio_lista|productos_precio_referencia|productos_cantidad_referencia|productos_unidad_medida_referencia|productos_precio_unitario_promo1|productos_leyenda_promo1|productos_precio_unitario_promo2|productos_leyenda_promo2"
    prod = "\n".join([
        "﻿" + cab,
        "10|1|233|7790968914633|1|ACEITE ELAION MI 1540 X 4|1|UNI|ELAION|82990.00|82990.00|1|UNI||||",
        "10|1|231|7790968914633|1|ACEITE ELAION MI 1540 X 4|1|UNI|ELAION|79999.00|79999.00|1|UNI||||",
        "10|1|5|7790968914633|1|ACEITE ELAION MI 1540 X 4|1|UNI|ELAION|80500.00|80500.00|1|UNI||||",
        "10|1|6|7790968914633|1|ACEITE ELAION MI 1540 X 4|1|UNI|ELAION|0.00|0.00|1|UNI||||",
        "10|2|7|7790968914633|1|ACEITE ELAION MI 1540 X 4|1|UNI|ELAION|85000.00|85000.00|1|UNI||||",
        "10|1|5|7798056300153|1|ACEITE GULF MAX 15W 40 X 4L|1|UNI|GULF|0.00|0.00|1|UNI||||",
        "10|1|5|7790272000794|1|Aceite MAZOLA de maíz PET-900-cc.|1|UNI|MAZOLA|3000.00|3000.00|1|UNI||||",
        "10|1|5|0000000065252|1|HUEVOS C SEL X 6UN|6|EA|SIN MARCA|1099.00|1099.00|6|EA||||",
        "Ultima actualización: 2026-11-02T09:26:04-03:00",
    ])
    com = "id_comercio|id_bandera|comercio_cuit|comercio_razon_social|comercio_bandera_nombre\n10|1|1|INC S.A.|Hipermercado Carrefour\n10|2|1|INC S.A.|Carrefour Market\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("productos.csv", prod)
        z.writestr("comercio.csv", com)
    grupos, cuenta = {}, {"filas": 0}
    leer_comercio(zipfile.ZipFile(buf), grupos, cuenta)
    assert cuenta["filas"] == 6, cuenta
    filas, sin_precio = agregar("2026-11-02", grupos)
    assert sin_precio == 1  # Gulf solo con precio 0: no se escribe, se cuenta
    assert len(filas) == 2, filas
    hiper, market = filas
    assert hiper["precio"] == "80500.00" and hiper["sucursal"] == "n=3;min=79999.00;max=82990.00", hiper
    assert hiper["vendedor"] == "Hipermercado Carrefour" and hiper["fuente"] == "sepa"
    assert market["vendedor"] == "Carrefour Market" and market["sucursal"].startswith("n=1;")

    assert ultimo_zip({"resources": [
        {"url": "x/sepa_martes.zip", "description": "Precios SEPA Minoristas martes, 2026-10-27"},
        {"url": "x/sepa_lunes.zip", "description": "Precios SEPA Minoristas lunes, 2026-11-02"},
        {"url": "x/maestro.xlsx", "description": "Excel"}]}) == ("2026-11-02", "x/sepa_lunes.zip")
    print("OK")


if __name__ == "__main__":
    demo() if sys.argv[1:] == ["test"] else correr()
