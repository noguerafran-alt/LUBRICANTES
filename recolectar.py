"""Una corrida diaria: YPF GraphQL + 4 VTEX + ML categorías (+ ML con token si hay secrets).

python recolectar.py [--solo <fuente>] [--fecha AAAA-MM-DD]
python recolectar.py --renormalizar   # recalcula el matcheo de data/obs/ sin tocar precios
python recolectar.py test
Escribe data/obs/AAAA-MM.csv, data/fuentes.csv, data/ml_oferta.csv y data/catalogo_ypf.json.
"""
import csv
import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

import ml
from normalizar import normalizar

AQUI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(AQUI, "data")

OBS = "fecha,fuente,url,ean,titulo,marca,precio,precio_lista,stock,vendedor,sucursal,litros,unidades,producto_id,match".split(",")
FUENTES = "fecha,fuente,http,n_items,n_con_precio,n_sin_stock,n_sin_match,error".split(",")
OFERTA = "fecha,categoria_id,categoria,total_items".split(",")

VTEX = {
    "vtex_carrefour": ("www.carrefour.com.ar", "C:/635/640/642/"),
    "vtex_masonline": ("www.masonline.com.ar", "C:/1000039/2000174/3000496/"),
    "vtex_easy": ("www.easy.com.ar", "C:/9/68/321/"),
    "vtex_jumbo": ("www.jumbo.com.ar", "C:/16/126/412/"),
}
CENCOSUD = {"vtex_jumbo"}  # ListPrice inflado ~82 veces: no se guarda

YPF_GQL = "https://magui.ypf.com/shp/yforms-lists/Metadata/"
YPF_LISTAS = ("PyS - Lubricantes ELAION", "PyS - Lubricantes Extravida", "PyS - Lubricantes ROD",
              "PyS - Otros lubricantes", "PyS - Azul 32")


def leer(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def reemplazar(ruta, campos, filas, clave, nuevas=None):
    """Reescribe `ruta` sacando las filas viejas con clave en `nuevas` (por defecto, las de `filas`)."""
    nuevas = {clave(f) for f in filas} if nuevas is None else nuevas
    viejas = [f for f in leer(ruta) if clave(f) not in nuevas]
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, campos, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(viejas + filas)


def num(x):
    return "" if x in (None, "") else f"{float(x):g}"


def a_obs(fuente, fecha, avisos):
    """Avisos crudos → (filas obs, n_sin_stock, n_sin_match). Sin stock o sin precio no entra."""
    filas, sin_stock = [], 0
    for a in avisos:
        stock = a.get("stock")
        if stock == 0 or not a["precio"] or float(a["precio"]) <= 0:
            sin_stock += 1
            continue
        n = normalizar(a["titulo"], a.get("marca_cruda", ""), a.get("ean", ""), url=a["url"])
        filas.append(dict(fecha=fecha, fuente=fuente, url=a["url"], ean=a.get("ean", ""), titulo=a["titulo"],
                          marca=n["marca"], precio=num(a["precio"]), precio_lista=num(a.get("precio_lista")),
                          stock="" if stock is None else int(stock), vendedor=a.get("vendedor", ""),
                          sucursal="", litros=num(n["litros"]), unidades=n["unidades"],
                          producto_id=n["producto_id"], match=n["match"]))
    return filas, sin_stock, sum(1 for f in filas if not f["producto_id"])


def renormalizar():
    """Recalcula marca/litros/unidades/producto_id/match de todas las filas de data/obs/, sin tocar precios."""
    for nombre in sorted(os.listdir(os.path.join(DATA, "obs"))):
        ruta = os.path.join(DATA, "obs", nombre)
        filas = leer(ruta)
        for f in filas:
            n = normalizar(f["titulo"], f["marca"], f["ean"], url=f["url"])
            f.update(marca=n["marca"], litros=num(n["litros"]), unidades=n["unidades"],
                     producto_id=n["producto_id"], match=n["match"])
        with open(ruta, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, OBS, lineterminator=chr(10), extrasaction="ignore")
            w.writeheader()
            w.writerows(filas)
        print(nombre, len(filas), "filas renormalizadas")


def vtex(fuente):
    """→ (http, avisos, error). Todo o nada: si una página falla, la fuente cae ese día."""
    host, fq = VTEX[fuente]
    avisos, http = [], 0
    for desde in range(0, 2500, 50):
        http, d = ml.pedir(f"https://{host}/api/catalog_system/pub/products/search?fq={fq}&_from={desde}&_to={desde + 49}")
        if d is None:
            return http, [], f"HTTP {http} en _from={desde}"
        for p in d:
            for it in p.get("items", []):
                sellers = it.get("sellers") or []
                # El vendedor con stock primero; si ninguno tiene, el default (cuenta como sin stock).
                s = next((s for s in sellers if s["commertialOffer"].get("AvailableQuantity", 0) > 0),
                         next((s for s in sellers if s.get("sellerDefault")), sellers[0] if sellers else None))
                o = s["commertialOffer"] if s else {}
                avisos.append(dict(url=p.get("link", ""), ean=it.get("ean") or "",
                                   titulo=it.get("nameComplete") or p.get("productName", ""),
                                   marca_cruda=p.get("brand", ""), precio=o.get("Price") or 0,
                                   precio_lista="" if fuente in CENCOSUD else o.get("ListPrice"),
                                   stock=o.get("AvailableQuantity", 0), vendedor=s.get("sellerName", "") if s else ""))
        if len(d) < 50:
            break
    return http, avisos, ""


def ypf_gql():
    """Foto del catálogo oficial. Una línea por ítem, ordenado, para que el diff de git se lea."""
    q = json.dumps({"query": "{getMetadataGlobal(type:PRODUCTION){title structure data props}}"}).encode()
    http, d = ml.pedir(YPF_GQL, data=q)
    if not d or "data" not in d:
        return http, 0, f"HTTP {http} sin data"
    items = []
    for lista in d["data"]["getMetadataGlobal"]:
        if lista["title"] not in YPF_LISTAS:
            continue
        for it in lista["data"] or []:
            p = it.get("props") or {}
            docs = sorted(c["props"]["url"] for c in it.get("children", []) if (c.get("props") or {}).get("url"))
            items.append(dict(lista=lista["title"][6:], categoria=p.get("categoria", ""),
                              titulo=p.get("titulo", ""), docs=docs))
    items.sort(key=lambda x: (x["lista"], x["categoria"], x["titulo"]))
    with open(os.path.join(DATA, "catalogo_ypf.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write("[\n" + ",\n".join(json.dumps(i, ensure_ascii=False, sort_keys=True) for i in items) + "\n]\n")
    return http, len(items), ""


def correr(fuente, fecha):
    """→ (fila fuentes, filas obs o None). None = no tocar obs de esa fuente (falló)."""
    fila = dict(fecha=fecha, fuente=fuente, http="", n_items=0, n_con_precio=0, n_sin_stock=0, n_sin_match=0, error="")
    if fuente == "ypf_gql":
        fila["http"], fila["n_items"], fila["error"] = ypf_gql()
        obs = None
    elif fuente == "ml_cat":
        fila["http"], oferta, fila["error"] = ml.categorias(fecha)
        fila["n_items"] = len(oferta)
        if oferta:
            reemplazar(os.path.join(DATA, "ml_oferta.csv"), OFERTA, oferta, lambda f: (f["fecha"], f["categoria_id"]))
        obs = None
    else:
        fila["http"], avisos, fila["error"] = vtex(fuente) if fuente in VTEX else ml.avisos()
        fila["n_items"] = len(avisos)
        obs = None
        if not fila["error"]:
            obs, fila["n_sin_stock"], fila["n_sin_match"] = a_obs(fuente, fecha, avisos)
            fila["n_con_precio"] = len(obs)
    if not fila["error"] and fila["n_items"] == 0 and fila["http"] and 200 <= int(fila["http"]) < 300:
        fila["error"] = "categoria vacia, revisar fq"
    return fila, obs


def main(args):
    if "--renormalizar" in args:
        return renormalizar()
    fecha = datetime.now(timezone(timedelta(hours=-3))).date().isoformat()
    fuentes = ["ypf_gql", *VTEX, "ml_cat", "ml"]
    if "--fecha" in args:
        fecha = args[args.index("--fecha") + 1]
    if "--solo" in args:
        fuentes = [args[args.index("--solo") + 1]]
    filas_f, obs, corridas = [], [], set()
    for fu in fuentes:
        try:
            fila, o = correr(fu, fecha)
        except Exception:  # una fuente que se rompe no tumba a las demás
            traceback.print_exc()
            fila, o = dict(fecha=fecha, fuente=fu, http="", n_items=0, n_con_precio=0, n_sin_stock=0,
                           n_sin_match=0, error="excepcion: " + traceback.format_exc().strip().splitlines()[-1][:200]), None
        print(",".join(str(fila[k]) for k in FUENTES), flush=True)
        filas_f.append(fila)
        if o is not None:  # corrió bien: sus filas del día se reemplazan aunque hoy no haya ninguna
            obs += o
            corridas.add((fecha, fu))
    clave = lambda f: (f["fecha"], f["fuente"])
    reemplazar(os.path.join(DATA, "fuentes.csv"), FUENTES, filas_f, clave)
    if corridas:
        reemplazar(os.path.join(DATA, "obs", fecha[:7] + ".csv"), OBS, obs, clave, corridas)


def demo():
    avisos = [dict(url="u", ean="", titulo="Aceite Elaion FS 540 4 lts", marca_cruda="Elaion", precio=159999.0, precio_lista="", stock=1, vendedor="C"),
              dict(url="u", ean="", titulo="Aceite Elaion mi 1540 x 1 lt", marca_cruda="Elaion", precio=0.0, precio_lista="", stock=0, vendedor="C"),
              dict(url="u", ean="", titulo="Lubricante Helix Hx7 X1l", marca_cruda="SHELL", precio=66.29, precio_lista="", stock=0, vendedor="J"),
              dict(url="u", ean="", titulo="Aceite Gulf max 20w-50 x 1l", marca_cruda="Gulf", precio=10560.0, precio_lista=10560.0, stock=None, vendedor="C")]
    filas, sin_stock, _ = a_obs("vtex_x", "2026-11-03", avisos)
    assert sin_stock == 2 and len(filas) == 2, (sin_stock, filas)
    assert filas[0]["precio"] == "159999" and filas[0]["litros"] == "4" and filas[0]["stock"] == 1
    assert filas[1]["stock"] == "" and filas[1]["precio_lista"] == "10560" and filas[1]["marca"] == "Gulf"
    import tempfile
    assert a_obs("x", "d", [dict(url="https://e.com/aceite-gulf-max-20w-50-4l/p", ean="", titulo="Aceite Gulf max 20w-50 x 1l",
                                 marca_cruda="Gulf", precio=1, stock=1)])[0][0]["litros"] == "1"  # el título manda en litros
    r = os.path.join(tempfile.mkdtemp(), "x.csv")
    reemplazar(r, OFERTA, [dict(fecha="d1", categoria_id="A", categoria="a", total_items=1),
                           dict(fecha="d2", categoria_id="A", categoria="a", total_items=2)], lambda f: (f["fecha"], f["categoria_id"]))
    reemplazar(r, OFERTA, [dict(fecha="d2", categoria_id="A", categoria="a", total_items=3)], lambda f: (f["fecha"], f["categoria_id"]))
    assert [x["total_items"] for x in leer(r)] == ["1", "3"]
    print("OK")


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        demo()
    else:
        main(sys.argv[1:])
