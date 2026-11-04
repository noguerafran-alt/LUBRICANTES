"""Una corrida diaria: YPF GraphQL + 5 VTEX + Shopify D'Atri + 2 Tiendanube + ML categorías (+ ML con token si hay secrets).

python recolectar.py [--solo <fuente>] [--fecha AAAA-MM-DD]
python recolectar.py --renormalizar   # recalcula el matcheo de data/obs/ sin tocar precios
python recolectar.py --podar          # deja en data/obs/ solo lo relacionado con YPF (una vez, para el histórico)
python recolectar.py test
Escribe data/obs/AAAA-MM.csv, data/fuentes.csv, data/ml_oferta.csv, data/catalogo_ypf.json y data/imagenes.csv.
Solo se guarda lo relacionado con YPF: un producto YPF o un comp_id de seed/equivalencias.csv. Lo demás se cuenta en
n_descartados de fuentes.csv y no se escribe (ni siquiera como sin_match).
"""
import csv
import json
import os
import sys
import re
import traceback
from datetime import datetime, timedelta, timezone

import ml
import tiendas
from normalizar import normalizar, texto

AQUI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(AQUI, "data")

OBS = "fecha,fuente,url,ean,titulo,marca,precio,precio_lista,stock,vendedor,sucursal,litros,unidades,producto_id,match".split(",")
FUENTES = "fecha,fuente,http,n_items,n_con_precio,n_sin_stock,n_sin_match,error,n_descartados".split(",")
IMAGENES = "producto_id,url,fuente,fecha".split(",")
OFERTA = "fecha,categoria_id,categoria,total_items".split(",")

VTEX = {
    "vtex_carrefour": ("www.carrefour.com.ar", "C:/635/640/642/"),
    "vtex_masonline": ("www.masonline.com.ar", "C:/1000039/2000174/3000496/"),
    "vtex_easy": ("www.easy.com.ar", "C:/9/68/321/"),
    "vtex_jumbo": ("www.jumbo.com.ar", "C:/16/126/412/"),
    # C:/3/20/ = aceites sueltos. NO C:/4/24/: son combos de cambio con colocación (precio de servicio).
    # AvailableQuantity=99999 es relleno ("hay stock"), no cantidad.
    "vtex_norauto": ("www.norauto.com.ar", "C:/3/20/"),
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


def escribir_fuentes(ruta, filas):
    """Una fila por (fecha, fuente): la nueva reemplaza a la vieja, salvo que la nueva traiga error y la vieja no.
    Una re-corrida fallida del mismo día no borra las obs buenas, así que tampoco puede pisar la fila que las describe."""
    clave = lambda f: (f["fecha"], f["fuente"])
    ok_previas = {clave(f) for f in leer(ruta) if not f["error"]} if os.path.exists(ruta) else set()
    reemplazar(ruta, FUENTES, [f for f in filas if not (f["error"] and clave(f) in ok_previas)], clave)


def num(x):
    return "" if x in (None, "") else f"{float(x):g}"


def relacionados(raiz=AQUI):
    """producto_id que se recolectan: los YPF de seed/productos.csv y todo comp_id de seed/equivalencias.csv (cualquier tipo)."""
    ypf = {p["producto_id"] for p in leer(os.path.join(raiz, "seed", "productos.csv")) if p["marca"] == "YPF"}
    return ypf | {e["comp_id"] for e in leer(os.path.join(raiz, "seed", "equivalencias.csv"))}


def a_obs(fuente, fecha, avisos, rel=None, imgs=None):
    """Avisos crudos → (filas obs, n_sin_stock, n_sin_match, n_descartados). Sin stock o sin precio no entra.
    Con `rel` (set de producto_id), un aviso de otro producto o sin match se descarta: no se escribe, solo se cuenta.
    `imgs` (dict producto_id → (url, fuente)) junta la primera foto https de cada producto relacionado."""
    filas, sin_stock, descartados = [], 0, 0
    for a in avisos:
        stock = a.get("stock")
        if stock == 0 or not a["precio"] or float(a["precio"]) <= 0:
            sin_stock += 1
            continue
        n = normalizar(a["titulo"], a.get("marca_cruda", ""), a.get("ean", ""), url=a["url"])
        if rel is not None and n["producto_id"] not in rel:
            descartados += 1
            continue
        if imgs is not None and n["producto_id"] and ml.https(a.get("imagen")):
            imgs.setdefault(n["producto_id"], (a["imagen"], fuente))
        filas.append(dict(fecha=fecha, fuente=fuente, url=a["url"], ean=a.get("ean", ""), titulo=a["titulo"],
                          marca=n["marca"], precio=num(a["precio"]), precio_lista=num(a.get("precio_lista")),
                          stock="" if stock is None else int(stock), vendedor=a.get("vendedor", ""),
                          sucursal="", litros=num(a["litros"] if "litros" in a else n["litros"]),
                          unidades=a.get("unidades") or n["unidades"],  # caja/tambor mayorista: el aviso manda
                          producto_id=n["producto_id"], match=n["match"]))
    return filas, sin_stock, sum(1 for f in filas if not f["producto_id"]), descartados


def podar():
    """Una vez: reescribe data/obs/*.csv dejando solo lo relacionado con YPF. Imprime filas antes/después."""
    rel, t0, t1 = relacionados(), 0, 0
    for nombre in sorted(os.listdir(os.path.join(DATA, "obs"))):
        ruta = os.path.join(DATA, "obs", nombre)
        filas = leer(ruta)
        quedan = [f for f in filas if f["producto_id"] in rel]
        with open(ruta, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, OBS, lineterminator=chr(10), extrasaction="ignore")
            w.writeheader()
            w.writerows(quedan)
        print(f"{nombre}: {len(filas)} -> {len(quedan)} filas")
        t0, t1 = t0 + len(filas), t1 + len(quedan)
    print(f"total: {t0} -> {t1} filas ({len(rel)} producto_id relacionados)")


def renormalizar():
    """Recalcula marca/litros/unidades/producto_id/match de todas las filas de data/obs/, sin tocar precios."""
    for nombre in sorted(os.listdir(os.path.join(DATA, "obs"))):
        ruta = os.path.join(DATA, "obs", nombre)
        filas = leer(ruta)
        for f in filas:
            n = normalizar(f["titulo"], f["marca"], f["ean"], url=f["url"])
            f.update(marca=n["marca"], producto_id=n["producto_id"], match=n["match"])
            if f["fuente"] not in tiendas.MAYORISTAS:  # caja/tambor sale de la variante, que el título no trae
                f.update(litros=num(n["litros"]), unidades=n["unidades"])
                e = tiendas.envase(f["titulo"]) if f["fuente"].startswith("tn_") else None  # igual que al recolectar
                if e:
                    f.update(litros=num(e[0]), unidades=e[1])
        with open(ruta, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, OBS, lineterminator=chr(10), extrasaction="ignore")
            w.writeheader()
            w.writerows(filas)
        print(nombre, len(filas), "filas renormalizadas")
    # Grok: solo producto_id/match (litros y unidades los manda la carga); mismo encabezado que trae el archivo.
    carpeta = os.path.join(DATA, "grok")
    for nombre in sorted(os.listdir(carpeta)) if os.path.isdir(carpeta) else []:
        ruta = os.path.join(carpeta, nombre)
        with open(ruta, encoding="utf-8", newline="") as fh:
            lector = csv.DictReader(fh)
            campos, filas = lector.fieldnames, list(lector)
        for f in filas:
            n = normalizar(f["titulo"], f["marca"], "", url=f["url"])
            f.update(producto_id=n["producto_id"], match=n["match"])
        with open(ruta, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, campos, lineterminator=chr(10))
            w.writeheader()
            w.writerows(filas)
        print("grok", nombre, len(filas), "filas renormalizadas")


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
                                   stock=None if o.get("AvailableQuantity") == 99999 else o.get("AvailableQuantity", 0),
                                   vendedor=s.get("sellerName", "") if s else "",
                                   imagen=ml.https(((it.get("images") or [{}])[0]).get("imageUrl"), f"https://{host}/")))
        if len(d) < 50:
            break
    return http, avisos, ""


def extracto(cuerpo, n=120):
    """Resumen corto y sin saltos del cuerpo de una respuesta rara: mensajes de "errors" GraphQL o los primeros n caracteres."""
    if isinstance(cuerpo, dict):
        cuerpo = "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in cuerpo.get("errors") or []) \
            or json.dumps(cuerpo, ensure_ascii=False)
    return " ".join((cuerpo or "(cuerpo vacío)").split())[:n]


def alnum(s):
    return re.sub(r"[^a-z0-9]", "", texto(s))


def pid_catalogo(item, ypf):
    """Producto YPF de seed al que corresponde un ítem del catálogo oficial, o None si no es uno solo (no se adivina).
    Compara el título (sin la palabra EXTRAVIDA) contra nombre, nombre+SAE y línea+nombre(+SAE), sin espacios ni signos."""
    t = alnum(item["titulo"])
    claves = {t, t.removeprefix("extravida")}
    c = [p["producto_id"] for p in ypf
         if claves & {k for n in (alnum(p["nombre"]), alnum(p["linea"] + p["nombre"]))
                      for k in (n, n + alnum(p["sae"]))}]
    return c[0] if len(c) == 1 else None


def ypf_gql(imgs=None):
    """Foto del catálogo oficial. Una línea por ítem, ordenado, para que el diff de git se lea.
    `imgs` (dict producto_id → (url, fuente)) recibe la imagen oficial de cada ítem que corresponde a un producto del seed."""
    q = json.dumps({"query": "{getMetadataGlobal(type:PRODUCTION){title structure data props}}"}).encode()
    http, cuerpo = ml.pedir(YPF_GQL, data=q, texto=True)
    try:
        d = json.loads(cuerpo)
    except (TypeError, ValueError):
        d = None
    if not isinstance(d, dict) or not d.get("data"):
        return http, 0, f"HTTP {http} sin data: {extracto(d if isinstance(d, dict) else cuerpo)}"
    items = []
    for lista in d["data"]["getMetadataGlobal"]:
        if lista["title"] not in YPF_LISTAS:
            continue
        for it in lista["data"] or []:
            p = it.get("props") or {}
            docs = sorted(c["props"]["url"] for c in it.get("children", []) if (c.get("props") or {}).get("url"))
            items.append(dict(lista=lista["title"][6:], categoria=p.get("categoria", ""),
                              titulo=p.get("titulo", ""), docs=docs,
                              imagen=ml.https(p.get("imagen"), "https://lubricantes.ypf.com/") or ""))
    items.sort(key=lambda x: (x["lista"], x["categoria"], x["titulo"]))
    if imgs is not None:
        ypf = [p for p in leer(os.path.join(AQUI, "seed", "productos.csv")) if p["marca"] == "YPF"]
        for it in items:
            pid = pid_catalogo(it, ypf) if it["imagen"] else None
            if pid:
                imgs[pid] = (it["imagen"], "ypf_oficial")
    with open(os.path.join(DATA, "catalogo_ypf.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write("[\n" + ",\n".join(json.dumps(i, ensure_ascii=False, sort_keys=True) for i in items) + "\n]\n")
    return http, len(items), ""


def guardar_imagenes(ruta, nuevas, fecha):
    """data/imagenes.csv: una foto por producto_id. Se escribe si no había, o si llega la oficial de YPF y es otra.
    `nuevas`: dict producto_id → (url, fuente). → cantidad de fotos nuevas o cambiadas."""
    hoy = {f["producto_id"]: f for f in leer(ruta)}
    cambios = 0
    for pid, (url, fuente) in nuevas.items():
        v = hoy.get(pid)
        if v is None or (fuente == "ypf_oficial" and v["url"] != url):
            hoy[pid] = dict(producto_id=pid, url=url, fuente=fuente, fecha=fecha)
            cambios += 1
    if cambios:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, IMAGENES, lineterminator=chr(10))
            w.writeheader()
            w.writerows(hoy[k] for k in sorted(hoy))
    return cambios


def correr(fuente, fecha, rel=None, imgs=None):
    """→ (fila fuentes, filas obs o None). None = no tocar obs de esa fuente (falló)."""
    fila = dict(fecha=fecha, fuente=fuente, http="", n_items=0, n_con_precio=0, n_sin_stock=0, n_sin_match=0, error="",
                n_descartados=0)
    if fuente == "ypf_gql":
        fila["http"], fila["n_items"], fila["error"] = ypf_gql(imgs)
        obs = None
    elif fuente == "ml_cat":
        fila["http"], oferta, fila["error"] = ml.categorias(fecha)
        fila["n_items"] = len(oferta)
        if oferta:
            reemplazar(os.path.join(DATA, "ml_oferta.csv"), OFERTA, oferta, lambda f: (f["fecha"], f["categoria_id"]))
        obs = None
    else:
        if fuente in VTEX:
            fila["http"], avisos, fila["error"] = vtex(fuente)
        elif fuente in tiendas.SHOPIFY:
            fila["http"], avisos, fila["error"] = tiendas.shopify(fuente)
        elif fuente in tiendas.TIENDANUBE:
            fila["http"], avisos, fila["error"] = tiendas.tiendanube(fuente, fecha)
        else:
            fila["http"], avisos, fila["error"] = ml.avisos(
                None if rel is None else lambda a: normalizar(a["titulo"], a["marca_cruda"], a["ean"], url=a["url"])["producto_id"] in rel)
        fila["n_items"] = len(avisos)
        obs = None
        if not fila["error"]:
            obs, fila["n_sin_stock"], fila["n_sin_match"], fila["n_descartados"] = a_obs(fuente, fecha, avisos, rel, imgs)
            fila["n_con_precio"] = len(obs)
    if not fila["error"] and fila["n_items"] == 0 and fila["http"] and 200 <= int(fila["http"]) < 300:
        fila["error"] = "categoria vacia, revisar fq"
    return fila, obs


def main(args):
    if "--renormalizar" in args:
        return renormalizar()
    if "--podar" in args:
        return podar()
    fecha = datetime.now(timezone(timedelta(hours=-3))).date().isoformat()
    fuentes = ["ypf_gql", *VTEX, *tiendas.SHOPIFY, *tiendas.TIENDANUBE, "ml_cat", "ml"]
    if "--fecha" in args:
        fecha = args[args.index("--fecha") + 1]
    if "--solo" in args:
        fuentes = [args[args.index("--solo") + 1]]
    filas_f, obs, corridas, imgs, rel = [], [], set(), {}, relacionados()
    for fu in fuentes:
        try:
            fila, o = correr(fu, fecha, rel, imgs)
        except Exception:  # una fuente que se rompe no tumba a las demás
            traceback.print_exc()
            fila, o = dict(fecha=fecha, fuente=fu, http="", n_items=0, n_con_precio=0, n_sin_stock=0,
                           n_sin_match=0, n_descartados=0, error="excepcion: " + traceback.format_exc().strip().splitlines()[-1][:200]), None
        print(",".join(str(fila[k]) for k in FUENTES), flush=True)
        filas_f.append(fila)
        if o is not None:  # corrió bien: sus filas del día se reemplazan aunque hoy no haya ninguna
            obs += o
            corridas.add((fecha, fu))
    clave = lambda f: (f["fecha"], f["fuente"])
    escribir_fuentes(os.path.join(DATA, "fuentes.csv"), filas_f)
    if corridas:
        reemplazar(os.path.join(DATA, "obs", fecha[:7] + ".csv"), OBS, obs, clave, corridas)
    print("fotos nuevas o cambiadas:", guardar_imagenes(os.path.join(DATA, "imagenes.csv"), imgs, fecha), flush=True)


def demo():
    avisos = [dict(url="u", ean="", titulo="Aceite Elaion FS 540 4 lts", marca_cruda="Elaion", precio=159999.0, precio_lista="", stock=1, vendedor="C"),
              dict(url="u", ean="", titulo="Aceite Elaion mi 1540 x 1 lt", marca_cruda="Elaion", precio=0.0, precio_lista="", stock=0, vendedor="C"),
              dict(url="u", ean="", titulo="Lubricante Helix Hx7 X1l", marca_cruda="SHELL", precio=66.29, precio_lista="", stock=0, vendedor="J"),
              dict(url="u", ean="", titulo="Aceite Gulf max 20w-50 x 1l", marca_cruda="Gulf", precio=10560.0, precio_lista=10560.0, stock=None, vendedor="C")]
    filas, sin_stock, _, desc = a_obs("vtex_x", "2026-11-03", avisos)
    assert sin_stock == 2 and len(filas) == 2 and desc == 0, (sin_stock, filas)
    assert filas[0]["precio"] == "159999" and filas[0]["litros"] == "4" and filas[0]["stock"] == 1
    assert filas[1]["stock"] == "" and filas[1]["precio_lista"] == "10560" and filas[1]["marca"] == "Gulf"
    assert extracto({"errors": [{"message": "x\ny"}, {"message": "z"}]}) == "x y; z"
    assert extracto("<html>\n  <b>Just a moment</b>").startswith("<html> <b>Just") and len(extracto("a" * 300)) == 120
    assert extracto(None) == "(cuerpo vacío)" and extracto({"data": None}) == '{"data": null}'
    import tempfile
    # solo lo relacionado: lo ajeno y lo sin match no se escribe, se cuenta; la foto https del primero que la trae queda
    av = [dict(url="u1", ean="", titulo="Aceite Elaion FS 540 4 lts", marca_cruda="Elaion", precio=1, stock=1, imagen="https://a.com/1.jpg"),
          dict(url="u2", ean="", titulo="Aceite Elaion FS 540 4 lts", marca_cruda="Elaion", precio=2, stock=1, imagen="https://a.com/2.jpg"),
          dict(url="u3", ean="", titulo="Aceite Gulf max 20w-50 x 1l", marca_cruda="Gulf", precio=3, stock=1, imagen="https://a.com/3.jpg"),
          dict(url="u4", ean="", titulo="Aceite raro sin marca", marca_cruda="", precio=4, stock=1, imagen="https://a.com/4.jpg"),
          dict(url="u5", ean="", titulo="Aceite Elaion FS 540 4 lts", marca_cruda="Elaion", precio=0, stock=1)]
    pid = normalizar(av[0]["titulo"], "Elaion", "", url="u1")["producto_id"]
    assert pid
    imgs = {}
    f, ss, sm, desc = a_obs("x", "d", av, {pid}, imgs)
    assert (len(f), ss, sm, desc) == (2, 1, 0, 2) and imgs == {pid: ("https://a.com/1.jpg", "x")}, (f, ss, sm, desc, imgs)
    assert a_obs("x", "d", av[:1], {pid}, {})[0] and a_obs("x", "d", av[:1], set())[3] == 1
    i2 = {}
    a_obs("x", "d", [dict(av[0], imagen="http://a.com/1.jpg")], {pid}, i2)
    assert i2 == {}  # solo https
    # fotos: una por producto; la oficial de YPF pisa, otra fuente no
    ri = os.path.join(tempfile.mkdtemp(), "imagenes.csv")
    assert guardar_imagenes(ri, {"p": ("https://a/1", "vtex_x"), "q": ("https://a/q", "ml")}, "d1") == 2
    assert guardar_imagenes(ri, {"p": ("https://a/2", "ml")}, "d2") == 0
    assert guardar_imagenes(ri, {"p": ("https://y/1", "ypf_oficial")}, "d3") == 1
    assert guardar_imagenes(ri, {"p": ("https://y/1", "ypf_oficial")}, "d4") == 0
    assert [(x["producto_id"], x["url"], x["fuente"], x["fecha"]) for x in leer(ri)] == [("p", "https://y/1", "ypf_oficial", "d3"), ("q", "https://a/q", "ml", "d1")]
    # catálogo oficial → producto del seed, solo si es uno
    yp = [dict(producto_id="a", linea="Elaion Auro Hybrid", nombre="D1 530", sae="5W-30"),
          dict(producto_id="b", linea="Extravida", nombre="XVT 550", sae="10W-40"),
          dict(producto_id="c", linea="Extravida", nombre="XVT 550", sae="5W-30"),
          dict(producto_id="d", linea="Röd", nombre="4T 10W-30", sae="10W-30")]
    assert pid_catalogo(dict(titulo="D1 530"), yp) == "a" and pid_catalogo(dict(titulo="EXTRAVIDA XVT550 5W-30"), yp) == "c"
    assert pid_catalogo(dict(titulo="RÖD 4T 10W-30"), yp) == "d" and pid_catalogo(dict(titulo="Calcio"), yp) is None
    assert pid_catalogo(dict(titulo="XVT 550"), yp) is None  # ambiguo: dos SAE
    assert a_obs("x", "d", [dict(url="https://e.com/aceite-gulf-max-20w-50-4l/p", ean="", titulo="Aceite Gulf max 20w-50 x 1l",
                                 marca_cruda="Gulf", precio=1, stock=1)])[0][0]["litros"] == "1"  # el título manda en litros
    r = os.path.join(tempfile.mkdtemp(), "x.csv")
    reemplazar(r, OFERTA, [dict(fecha="d1", categoria_id="A", categoria="a", total_items=1),
                           dict(fecha="d2", categoria_id="A", categoria="a", total_items=2)], lambda f: (f["fecha"], f["categoria_id"]))
    reemplazar(r, OFERTA, [dict(fecha="d2", categoria_id="A", categoria="a", total_items=3)], lambda f: (f["fecha"], f["categoria_id"]))
    assert [x["total_items"] for x in leer(r)] == ["1", "3"]
    # fuentes.csv: una re-corrida con error no pisa la fila buena del día; una buena sí reemplaza; nunca duplica
    fu = os.path.join(tempfile.mkdtemp(), "fuentes.csv")
    f_ = lambda fu_, n, err="": dict(fecha="d", fuente=fu_, http="200" if not err else "", n_items=str(n), n_con_precio=str(n),
                                     n_sin_stock="0", n_sin_match="0", error=err)
    escribir_fuentes(fu, [f_("ml", 2385), f_("sepa", 111)])
    escribir_fuentes(fu, [f_("ml", 0, "sin token"), f_("sepa", 114), f_("x", 0, "HTTP 403")])
    escribir_fuentes(fu, [f_("x", 0, "HTTP 500")])
    assert [(x["fuente"], x["n_items"], x["error"]) for x in leer(fu)] == [("ml", "2385", ""), ("sepa", "114", ""), ("x", "0", "HTTP 500")]
    print("OK")


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        demo()
    else:
        main(sys.argv[1:])
