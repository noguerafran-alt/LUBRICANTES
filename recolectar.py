"""Una corrida diaria: YPF GraphQL + 5 VTEX + Shopify D'Atri + 2 Tiendanube + ML categorías (+ ML con token si hay secrets).

python recolectar.py [--solo <fuente>] [--sin <fuente>]... [--fecha AAAA-MM-DD]
python recolectar.py --renormalizar   # recalcula el matcheo de data/obs/ sin tocar precios
python recolectar.py --podar          # deja en data/obs/ solo lo relacionado con YPF (una vez, para el histórico)
python recolectar.py test
Escribe data/obs/AAAA-MM.csv, data/fuentes.csv, data/ml_oferta.csv, data/catalogo_ypf.json y data/imagenes.csv.
Solo se guarda lo relacionado con YPF: un producto YPF o un comp_id de seed/equivalencias.csv. Lo demás se cuenta en
n_descartados de fuentes.csv y no se escribe (ni siquiera como sin_match).
"""
import csv
import hashlib
import json
import os
import sys
import re
import time
import traceback
import urllib.parse
from datetime import datetime, timedelta, timezone

import ml
import tiendas
from normalizar import ONLINE, SUBDIVISIONES, normalizar, pais_producto, texto

AQUI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(AQUI, "data")

OBS = "fecha,fuente,url,ean,titulo,marca,precio,precio_lista,stock,vendedor,sucursal,litros,unidades,producto_id,match,provincia,pais,moneda,capturado".split(",")  # única definición: sepa.py y server.py la importan
FUENTES = "fecha,fuente,http,n_items,n_con_precio,n_sin_stock,n_sin_match,error,n_descartados".split(",")
IMAGENES = "producto_id,url,fuente,fecha".split(",")
ENVIOS = "fecha,capturado,fuente,url,producto_id,litros,unidades,precio,cp_destino,provincia_destino,costo_envio,metodo,plazo_h,estado,deposito".split(",")
ENVIOS_K = 7  # rotación semanal: cada combinación se cotiza a las 24 provincias un día de cada siete
ENVIOS_SEGUNDOS = 22 * 60  # presupuesto de la cotización: el job tiene 50 min y `ml` ya usa ~14; sin tope un timeout mataría el commit del día
OFERTA = "fecha,categoria_id,categoria,total_items".split(",")

VTEX = {
    "vtex_carrefour": ("www.carrefour.com.ar", "C:/635/640/642/"),
    "vtex_masonline": ("www.masonline.com.ar", "C:/1000039/2000174/3000496/"),
    "vtex_easy": ("www.easy.com.ar", "C:/9/68/321/"),
    # C:/3/20/ = aceites sueltos. NO C:/4/24/: son combos de cambio con colocación (precio de servicio).
    # AvailableQuantity=99999 es relleno ("hay stock"), no cantidad.
    "vtex_norauto": ("www.norauto.com.ar", "C:/3/20/"),
    # Brasil: la categoría (fq=C:9317) da [] en Pitstop; se barre por texto (ft=) con las marcas del seed BR.
    # Daytona (NEUMASUR): C:/3/ = Lubricentro. Sus aceites son todos combos "Cambio de Aceite ... + Filtro" (servicios, a data/grok);
    # lo demás (refrigerantes) se descarta. Tienda Neumáticos es el mismo catálogo (mismos productId, títulos y precios): no se lee, sería doble conteo.
    "vtex_daytona": ("www.daytona.com.ar", "C:/3/"),
    "vtex_br_pitstop": ("www.pitstop.com.br", None),
    "vtex_br_altese": ("www.altese.com.br", None),
}
# AvailableQuantity que es relleno ("hay stock") y no una cantidad: la fuente guarda stock vacío. Norauto 99999 (las demás
# argentinas, igual); Pitstop y Altese también ponen 100 en casi todo.
RELLENO_STOCK = {"vtex_daytona": {99999, 100}, "vtex_br_pitstop": {99999, 100}, "vtex_br_altese": {99999, 100}}
# Lotes y kits: precio de varias unidades o de servicio con nombre de 1 L. No son $/L: no entran (ver CLAUDE.md, Brasil).
LOTE_BR = re.compile(r"\b(kit|combo|revisao)\b|^\s*\d+\s+oleo\b|\(\s*\d+\s*un\b")  # sobre texto() (sin acentos)
EXTRA_TERMINOS_BR = {"Petronas": ["oleo selenia"]}  # Selenia es la marca de Petronas en Brasil

NP_URL = "https://menorpreco.notaparana.pr.gov.br/api/v1/produtos?termo={t}&offset={o}&raio=100&data=-1&ordem=0&gtin=0&local=6gkzmg1v4"
NP_NCM = "27101932"  # lubrificantes acabados; las filas sin GTIN son de distribuidor (cajas 12X1) y no entran
NP_TOPE_PAGINAS = 25  # por término; ~30 filas por página a 1 req/s
FECHA_PROPIA = {"oficial_br_notaparana"}  # la fecha de cada fila es la de su nota fiscal, no la de la corrida

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


def ahora_utc():
    """Hora de captura de una fila nueva (ISO 8601 UTC). Las filas viejas quedan con `capturado` vacío: nunca se deriva una hora."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pais_fuente(fuente):
    """(pais, moneda) en que publica una fuente: las de Brasil llevan `_br_` en el nombre; todo lo demás es AR/ARS."""
    return ("BR", "BRL") if "_br_" in fuente else ("AR", "ARS")


def a_obs(fuente, fecha, avisos, rel=None, imgs=None):
    """Avisos crudos → (filas obs, n_sin_stock, n_sin_match, n_descartados). Sin stock o sin precio no entra.
    Con `rel` (set de producto_id), un aviso de otro producto o sin match se descarta: no se escribe, solo se cuenta.
    `imgs` (dict producto_id → (url, fuente)) junta la primera foto https de cada producto relacionado.
    Un aviso puede traer su propia `fecha` (nota fiscal), `sucursal` y `provincia`; si no, vale la de la corrida y `online`."""
    filas, sin_stock, descartados = [], 0, 0
    pais, moneda = pais_fuente(fuente)
    capturado = ahora_utc()
    for a in avisos:
        stock = a.get("stock")
        if stock == 0 or not a["precio"] or float(a["precio"]) <= 0:
            sin_stock += 1
            continue
        n = normalizar(a["titulo"], a.get("marca_cruda", ""), a.get("ean", ""), url=a["url"], pais=pais)
        if rel is not None and n["producto_id"] not in rel:
            descartados += 1
            continue
        if imgs is not None and n["producto_id"] and ml.https(a.get("imagen")):
            imgs.setdefault(n["producto_id"], (a["imagen"], fuente))
        filas.append(dict(fecha=a.get("fecha") or fecha, fuente=fuente, url=a["url"], ean=a.get("ean", ""), titulo=a["titulo"],
                          marca=n["marca"], precio=num(a["precio"]), precio_lista=num(a.get("precio_lista")),
                          stock="" if stock is None else int(stock), vendedor=a.get("vendedor", ""),
                          sucursal=a.get("sucursal", ""), litros=num(a["litros"] if "litros" in a else n["litros"]),
                          unidades=a.get("unidades") or n["unidades"],  # caja/tambor mayorista: el aviso manda
                          producto_id=n["producto_id"], match=n["match"],
                          provincia=a.get("provincia", ONLINE),  # VTEX, Shopify, Tiendanube y ML: e-commerce nacional, nunca la casa central
                          pais=pais, moneda=moneda, capturado=capturado))
    return filas, sin_stock, sum(1 for f in filas if not f["producto_id"]), descartados


def clave_fila(f):
    """Identidad de una nota fiscal: la misma fila reescrita (otra corrida) la reemplaza; otra fecha, vendedor o producto es otra fila."""
    return (f["fuente"], f["fecha"], f["ean"], f["vendedor"], f["sucursal"], f["titulo"])


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
            n = normalizar(f["titulo"], f["marca"], f["ean"], url=f["url"], pais=f.get("pais") or "AR")
            f.update(marca=n["marca"], producto_id=n["producto_id"], match=n["match"])
            if f["fuente"] not in tiendas.MAYORISTAS:  # caja/tambor sale de la variante, que el título no trae
                f.update(litros=num(n["litros"]), unidades=n["unidades"])
                e = tiendas.envase(f["titulo"]) if f["fuente"].startswith("tn_") else None  # igual que al recolectar
                if e:
                    f.update(litros=num(e[0]), unidades=1 if f["fuente"] in tiendas.PRECIO_UNITARIO else e[1])
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
            n = normalizar(f["titulo"], f["marca"], "", url=f["url"], pais=f.get("pais") or "AR")
            f.update(producto_id=n["producto_id"], match=n["match"])
        with open(ruta, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, campos, lineterminator=chr(10))
            w.writeheader()
            w.writerows(filas)
        print("grok", nombre, len(filas), "filas renormalizadas")


def terminos_br(raiz=AQUI):
    """Términos de búsqueda de las tiendas brasileñas: `elaion` y `oleo <marca>` de cada marca competidora del seed BR
    (productos con sufijo -br; más los alias de EXTRA_TERMINOS_BR) → (terminos VTEX, terminos Nota Paraná).
    Nota Paraná va más fino ("marca línea"): `lubrax` solo trae miles de filas de 2T de 200 ml."""
    prods = [p for p in leer(os.path.join(raiz, "seed", "productos.csv")) if pais_producto(p["producto_id"]) == "BR" and p["marca"] != "YPF"]
    marcas = sorted({p["marca"] for p in prods})
    vt = ["oleo elaion", "elaion"] + [t for m in marcas for t in [f"oleo {m.lower()}", *EXTRA_TERMINOS_BR.get(m, [])]]
    np_ = ["elaion"] + sorted({f"{p['marca']} {p['linea']}".lower() for p in prods})
    return vt, np_


def avisos_vtex(fuente, productos, vistos=None):
    """Productos VTEX crudos → avisos. `vistos` (set de itemId) deduplica entre términos de una misma corrida.
    En las fuentes de RELLENO_STOCK un AvailableQuantity de relleno queda como stock vacío; en Brasil, además, se saltean
    los lotes y kits (LOTE_BR) y el envase sale de tiendas.envase (24X1L = 1 L × 24)."""
    host, _ = VTEX[fuente]
    br, relleno = pais_fuente(fuente)[0] == "BR", RELLENO_STOCK.get(fuente, {99999})
    avisos = []
    for p in productos:
        for it in p.get("items", []):
            if vistos is not None:
                if it.get("itemId") in vistos:
                    continue
                vistos.add(it.get("itemId"))
            titulo = it.get("nameComplete") or p.get("productName", "")
            if br and LOTE_BR.search(texto(titulo)):
                continue
            sellers = it.get("sellers") or []
            # El vendedor con stock primero; si ninguno tiene, el default (cuenta como sin stock).
            s = next((s for s in sellers if s["commertialOffer"].get("AvailableQuantity", 0) > 0),
                     next((s for s in sellers if s.get("sellerDefault")), sellers[0] if sellers else None))
            o = s["commertialOffer"] if s else {}
            a = dict(url=p.get("link", ""), ean=it.get("ean") or "", titulo=titulo,
                     marca_cruda=p.get("brand", ""), precio=o.get("Price") or 0,
                     precio_lista=o.get("ListPrice"),
                     stock=None if o.get("AvailableQuantity") in relleno else o.get("AvailableQuantity", 0),
                     vendedor=s.get("sellerName", "") if s else "",
                     imagen=ml.https(((it.get("images") or [{}])[0]).get("imageUrl"), f"https://{host}/"))
            e = tiendas.envase(titulo) if br else None
            if e:
                a.update(litros=e[0], unidades=e[1])
            avisos.append(a)
    return avisos


def vtex(fuente):
    """→ (http, avisos, error). Todo o nada: si una página falla, la fuente cae ese día.
    Con categoría (fq) lee esa; sin ella (Brasil) barre los términos de `terminos_br` con ft= (%20, nunca '+': da 400)."""
    host, fq = VTEX[fuente]
    if fq is None:
        if not tiendas.permitido(f"https://{host}/api/catalog_system/pub/products/search"):
            return 0, [], "robots.txt no permite /api/catalog_system"
        consultas = [f"ft={urllib.parse.quote(t)}" for t in terminos_br()[0]]
    else:
        consultas = [f"fq={fq}"]
    avisos, http, vistos = [], 0, set()
    for cons in consultas:
        for desde in range(0, 2500, 50):
            http, d = ml.pedir(f"https://{host}/api/catalog_system/pub/products/search?{cons}&_from={desde}&_to={desde + 49}")
            if d is None:
                return http, [], f"HTTP {http} en {cons} _from={desde}"
            avisos += avisos_vtex(fuente, d, vistos if fq is None else None)
            if len(d) < 50:
                break
    return http, avisos, ""


# ---------- Nota Paraná (Menor Preço, Sefaz-PR): SEPA brasileño, precio de nota fiscal por establecimiento ----------
ART = timezone(timedelta(hours=-3))


def fecha_np(datahora):
    """'2026-11-05T16:43:26.555Z' (UTC) → '2026-11-05' en hora argentina; '' si no se puede leer (sin fecha no hay fila)."""
    try:
        return datetime.strptime(datahora[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).astimezone(ART).date().isoformat()
    except (TypeError, ValueError):
        return ""


def gtin13(g):
    """GTIN con ceros de más (07898245572054) → 13 dígitos. Un GTIN-14 con indicador distinto de 0 (caja) queda como viene."""
    g = re.sub(r"\D", "", g or "")
    z = g.lstrip("0")
    return z.zfill(13) if z and len(z) <= 13 else g


def avisos_np(productos, vistos=None):
    """Filas crudas de Nota Paraná → avisos. Solo NCM 27101932 y GTIN no vacío (sin GTIN son cajas de distribuidor).
    `fecha` es la de la nota; vendedor = nombre fantasía → razón social → dirección (nunca vacío); `sucursal` = dirección."""
    out = []
    for p in productos:
        if vistos is not None:
            if p.get("id") in vistos:
                continue
            vistos.add(p.get("id"))
        e = p.get("estabelecimento") or {}
        f, ean = fecha_np(p.get("datahora")), gtin13(p.get("gtin"))
        if p.get("ncm") != NP_NCM or not ean or not f:
            continue
        try:
            precio = float(p["valor"])
        except (KeyError, TypeError, ValueError):
            continue
        direccion = " ".join(x for x in (e.get("tp_logr"), e.get("nm_logr"), e.get("nr_logr")) if x) + \
            f", {e.get('bairro', '')}, {e.get('mun', '')}/{e.get('uf', '')}"
        util = lambda v: (v or "").strip() if (v or "").strip(" -") else ""
        uf = "BR-" + (e.get("uf") or "").upper()
        out.append(dict(url="", ean=ean, titulo=" ".join((p.get("desc") or "").split()), marca_cruda="", precio=precio, stock=None,
                        vendedor=util(e.get("nm_fan")) or util(e.get("nm_emp")) or direccion, sucursal=direccion, fecha=f,
                        provincia=uf if uf in SUBDIVISIONES["BR"] else ""))
    return out


def es_senuelo(ps):
    """True si la mayoría de la página no trae NCM de 8 dígitos: Nota Paraná sirve datos señuelo (ncm de 9 dígitos, gtin '0') al acceso automatizado."""
    return bool(ps) and sum(not re.fullmatch(r"\d{8}", str(p.get("ncm") or "")) for p in ps) * 2 > len(ps)


def notaparana():
    """→ (http, avisos, error). Pagina cada término por offset (suma lo devuelto: las páginas se solapan y `total` cuenta repetidas),
    deduplica por id y corta en la página vacía o en NP_TOPE_PAGINAS. Sin robots.txt (404) = permitido."""
    if not tiendas.permitido(NP_URL.format(t="elaion", o=0)):
        return 0, [], "robots.txt no permite /api/v1/produtos"
    avisos, http, vistos = [], 0, set()
    for t in terminos_br()[1]:
        o, paginas = 0, 0
        while paginas < NP_TOPE_PAGINAS:
            http, d = ml.pedir(NP_URL.format(t=urllib.parse.quote(t), o=o))
            if not isinstance(d, dict):
                return http, [], f"HTTP {http} en termo={t} offset={o}"
            ps = d.get("produtos") or []
            if es_senuelo(ps):  # no se esquiva ni se sigue paginando: se corta en la primera página
                return http, [], "respuesta señuelo: la API bloquea el acceso automatizado"
            avisos += avisos_np(ps, vistos)
            o, paginas = o + len(ps), paginas + 1
            if not ps or o >= (d.get("total") or 0):
                break
        else:
            print(f"notaparana: termo {t!r} cortado en {NP_TOPE_PAGINAS} páginas (total {d.get('total')})", flush=True)
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


# ---------- helix_api: combos de cambio de aceite Shell de helixturno.com.ar (API JSON anónima del propio sitio) ----------
HELIX_URL = "https://api-core-turnos-prod.azurewebsites.net/api/v1/combos/GetCombosWeb"
HELIX_PAGINA = "https://www.helixturno.com.ar/combos"  # misma URL que usa grok_helix: la `url` de cada fila
GROK_ALM = "fecha,fuente,url,titulo,marca,precio,precio_lista,litros,unidades,tipo,detalle,verificado,producto_id,match,cargado,provincia,pais,moneda".split(",")  # = server.GROK_ALM_F (assert en server.py test)


def fila_servicio(fuente, url, titulo, precio, detalle, fecha, cargado, litros=None, unidades=None):
    """Fila de data/grok/ (esquema GROK_ALM) de un servicio: aceite + filtro/mano de obra. Nunca va a obs ni al $/L;
    `detalle` es lo que lee server.RX_EXTRA para no calcular un precio_litro falso. producto_id/litros salen de `normalizar`."""
    n = normalizar(titulo, "", "", url=url)
    return dict(fecha=fecha, fuente=fuente, url=url, titulo=titulo, marca=n["marca"] or "", precio=num(precio), precio_lista="",
                litros=num(n["litros"] if litros is None else litros), unidades=n["unidades"] or "" if unidades is None else unidades,
                tipo="servicio", detalle=detalle, verificado="1", producto_id=n["producto_id"], match=n["match"], cargado=cargado,
                provincia="", pais="AR", moneda="ARS")


def servicios_combo(fuente, combos, fecha, cargado):
    """Avisos que son combo (tiendas.COMBO) → (filas para data/grok/, n sin stock o sin precio). El detalle sale solo de lo que dice
    el título: filtro(s); la colocación nunca se afirma (ningún sitio aclara si incluye mano de obra); si no dice nada, "KIT". Clave del día: url+título+detalle."""
    por_clave, sin = {}, 0
    for a in combos:
        if a.get("stock") == 0 or not a["precio"] or float(a["precio"]) <= 0:
            sin += 1
            continue
        t = texto(a["titulo"])
        # "cambio de aceite" no prueba mano de obra incluida: sin COLOCACIÓN en el detalle, /api/servicios no inventa un $/L de aceite + colocación
        partes = ["FILTRO ACEITE" if "filtro de aceite" in t else "FILTROS" if "filtro" in t else ""]
        detalle = ";".join(x for x in partes if x) or "KIT"
        f = fila_servicio(fuente, a["url"], a["titulo"], a["precio"], detalle, fecha, cargado,
                          litros=a.get("litros"), unidades=a.get("unidades"))
        por_clave[(f["url"], f["titulo"], f["detalle"])] = f
    return list(por_clave.values()), sin


def filas_helix(resultado, fecha, cargado):
    """result[] de GetCombosWeb → (filas para data/grok/, n sin precio). Son servicios (aceite + mano de obra), nunca $/L de bidón:
    `tipo=servicio`, así que server.py los manda a /api/servicios y no a obs. `imagenWeb` (URL firmada que vence) se ignora.
    Los ítems incluidos van a `detalle` (lo que lee server.RX_EXTRA); la clave del día es titulo+detalle, no el título solo."""
    por_clave, sin_precio = {}, 0
    for c in resultado:
        precio = c.get("precio")
        if not isinstance(precio, (int, float)) or isinstance(precio, bool) or precio <= 0:
            sin_precio += 1
            continue
        titulo = f"{c.get('titulo', '')} {c.get('descripcion', '')}".strip()
        detalle = ";".join(t for t, k in (("FILTRO AIRE", "filtroAire"), ("FILTRO ACEITE", "filtroAceite")) if c.get(k)
                           ) + (";COLOCACIÓN Y CONTROLES" if c.get("colocacion") else ";sin colocación")
        f = fila_servicio("helix_api", HELIX_PAGINA, titulo, precio, detalle.lstrip(";"), fecha, cargado)
        por_clave[(f["titulo"], f["detalle"])] = f  # mismo combo dos veces el mismo día: una fila
    return list(por_clave.values()), sin_precio


def helix_api(fecha):
    """→ (http, n_items, n_sin_precio, error). Una request; ml.pedir ya pone User-Agent honesto, timeout 30 s y un reintento.
    Escribe data/grok/AAAA-MM.csv reemplazando las filas helix_api de esa fecha. Si falla no toca nada."""
    http, d = ml.pedir(HELIX_URL)
    res = d.get("result") if isinstance(d, dict) else None
    if not isinstance(res, list):
        return http, 0, 0, f"HTTP {http}" if d is None else "respuesta sin result[]"
    if not res:
        return http, 0, 0, "API sin combos (result vacío)"
    filas, sin_precio = filas_helix([c for c in res if isinstance(c, dict)], fecha, ahora_utc())
    reemplazar(os.path.join(DATA, "grok", fecha[:7] + ".csv"), GROK_ALM, filas, lambda f: (f["fuente"], f["fecha"]))
    return http, len(res), sin_precio, ""


def correr(fuente, fecha, rel=None, imgs=None):
    """→ (fila fuentes, filas obs o None). None = no tocar obs de esa fuente (falló)."""
    fila = dict(fecha=fecha, fuente=fuente, http="", n_items=0, n_con_precio=0, n_sin_stock=0, n_sin_match=0, error="",
                n_descartados=0)
    if fuente == "helix_api":
        fila["http"], fila["n_items"], fila["n_sin_stock"], fila["error"] = helix_api(fecha)
        fila["n_con_precio"] = 0 if fila["error"] else fila["n_items"] - fila["n_sin_stock"]
        return fila, None
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
        elif fuente in tiendas.WOOCOMMERCE:
            fila["http"], avisos, fila["error"] = tiendas.woocommerce(fuente, fecha)
        elif fuente in tiendas.ODOO:
            fila["http"], avisos, fila["error"] = tiendas.odoo(fuente, fecha)
        elif fuente in tiendas.PRESTASHOP:
            fila["http"], avisos, fila["error"] = tiendas.prestashop(fuente, fecha)
        elif fuente == "oficial_br_notaparana":
            fila["http"], avisos, fila["error"] = notaparana()
        else:
            fila["http"], avisos, fila["error"] = ml.avisos(
                None if rel is None else lambda a: normalizar(a["titulo"], a["marca_cruda"], a["ean"], url=a["url"])["producto_id"] in rel)
        fila["n_items"] = len(avisos)
        obs = None
        if not fila["error"]:
            combos = [a for a in avisos if fuente in tiendas.COMBOS and tiendas.es_combo(a["titulo"])]
            # falla cerrada: en fuentes con combos, lo que no es combo pero nombra filtro/kit/service… (un servicio que es_combo no reconoce) no es un bidón
            sueltos = [a for a in avisos if a not in combos and not (fuente in tiendas.COMBOS and tiendas.NO_ACEITE.search(texto(a["titulo"])))]
            obs, fila["n_sin_stock"], fila["n_sin_match"], fila["n_descartados"] = a_obs(fuente, fecha, sueltos, rel, imgs)
            fila["n_descartados"] += len(avisos) - len(combos) - len(sueltos)
            fila["n_con_precio"] = len(obs)
            if fuente in tiendas.COMBOS:  # los combos son servicios: a data/grok, y el día queda reemplazado aunque hoy no haya ninguno
                serv, sin = servicios_combo(fuente, combos, fecha, ahora_utc())
                reemplazar(os.path.join(DATA, "grok", fecha[:7] + ".csv"), GROK_ALM, serv, lambda f: (f["fuente"], f["fecha"]), {(fuente, fecha)})
                fila["n_sin_stock"] += sin
                fila["n_con_precio"] += len(serv)
    if not fila["error"] and fila["n_items"] == 0 and fila["http"] and 200 <= int(fila["http"]) < 300:
        fila["error"] = ("API devolvió 0 productos (¿bloqueo de IP?)" if fuente == "oficial_br_notaparana"
                         else "categoria vacia, revisar fq")
    return fila, obs


# Fuentes que bloquean IP de datacenter: las corre tools/sepa_pc.py desde la PC. En GitHub Actions el recorrido por defecto las saltea
# (así no escriben una fila de error que el visor mostraría como caída aunque la PC la traiga); `--solo` las corre igual.
FUENTES_PC = {"oficial_br_notaparana"}
# Pausadas: fuera del recorrido por defecto en todos lados; `--solo` las corre para probar a mano.
PAUSADAS = {"oficial_br_notaparana"}  # desde 2026-11-18: la API devuelve datos señuelo al acceso automatizado; no se esquiva


def fuentes_por_defecto(env=os.environ):
    todas = ["ypf_gql", *VTEX, *tiendas.SHOPIFY, *tiendas.TIENDANUBE, *tiendas.WOOCOMMERCE, *tiendas.ODOO, *tiendas.PRESTASHOP, "oficial_br_notaparana", "helix_api", "ml_cat", "ml"]
    return [f for f in todas if f not in PAUSADAS and not (env.get("GITHUB_ACTIONS") == "true" and f in FUENTES_PC)]


def sin_fuentes(fuentes, args):
    """`--sin ml` (repetible) saca fuentes del recorrido: el recolector de casa nunca toca Mercado Libre."""
    fuera = {args[i + 1] for i, a in enumerate(args[:-1]) if a == "--sin"}
    return [f for f in fuentes if f not in fuera]


def grupo_envios(clave, fecha, k=ENVIOS_K):
    """¿Toca hoy cotizar esta combinación? Grupo por sha1 de la clave, hoy el `ordinal del día % k` (como la rotación de Tiendanube)."""
    return int(hashlib.sha1("|".join(clave).encode()).hexdigest(), 16) % k == datetime.fromisoformat(fecha).toordinal() % k


def envios_ml(obs, fecha, rel, tok, capitales, cotizar=ml.cotizar, reloj=time.monotonic):
    """Avisos de YPF que `ml` escribió hoy → (fila ml_envios, filas data/envios). Una combinación vendedor × producto × envase
    (con el MLA de uno de sus avisos) del grupo de hoy se cotiza a la capital de las 24 provincias. `provincia_destino` sale de la
    tabla `capitales`, nunca de la respuesta. Sin token no se pide nada."""
    fila = dict(fecha=fecha, fuente="ml_envios", http="", n_items=0, n_con_precio=0, n_sin_stock=0, n_sin_match=0, error="", n_descartados=0)
    if not tok:
        fila["error"] = "sin token"
        return fila, None
    combos = {}
    for r in sorted((r for r in obs if r["fuente"] == "ml" and r["producto_id"] in rel and r["fecha"] == fecha), key=lambda r: r["url"]):
        combos.setdefault((r["vendedor"], r["producto_id"], r["litros"], str(r["unidades"])), r)
    hoy = [r for k, r in combos.items() if grupo_envios(k, fecha)]
    capturado, filas, limite = ahora_utc(), [], reloj() + ENVIOS_SEGUNDOS
    for i, r in enumerate(hoy):
        if reloj() > limite:  # ponytail: el corte es siempre por el final de la lista; si molesta, rotar el inicio por día
            fila["error"] = f"cortado por tiempo: {i} de {len(hoy)} combinaciones"
            break
        for c in capitales:
            http, estado, ops = cotizar(r["url"], c["cp"], tok)
            fila["http"], fila["n_items"] = http, fila["n_items"] + 1
            fila["n_con_precio"] += estado == "ok"
            base = dict(fecha=fecha, capturado=capturado, fuente="ml", url=r["url"], producto_id=r["producto_id"], litros=r["litros"],
                        unidades=r["unidades"], precio=r["precio"], cp_destino=c["cp"], provincia_destino=c["provincia"], deposito="")
            filas += [dict(base, costo_envio=num(co), metodo=m, plazo_h=h, estado=estado) for m, co, h in ops] or \
                     [dict(base, costo_envio="", metodo="", plazo_h="", estado=estado)]
    if hoy and not fila["n_con_precio"] and not fila["error"]:
        fila["error"] = f"ninguna de {fila['n_items']} cotizaciones respondió"
    print(f"ml_envios: {len(hoy)} de {len(combos)} combinaciones hoy, {fila['n_items']} cotizaciones, {fila['n_con_precio']} ok", flush=True)
    return fila, filas


ENVIOS_ML = False  # apagada el 2026-11-24 por decisión del usuario: ML vuelve a pedir solo precios, como antes del 403 del 23/11
ENVIOS_VTEX = ("vtex_norauto",)  # Easy y Carrefour no (cláusulas de propiedad intelectual), Más Online no se pudo evaluar: ver docs/relevamiento/envio-por-provincia.md §4.3
ENVIOS_VTEX_SEGUNDOS = 15 * 60  # propio: cada combinación son 25 requests a 1 req/s (~25 s)
_ITEMS_VTEX = {}  # url del aviso → (itemId, sellerId) o None; un aviso se resuelve una vez por corrida


def cuerpo_simulacion(item_id, seller, cp):
    return json.dumps({"items": [{"id": item_id, "quantity": 1, "seller": seller}], "postalCode": cp, "country": "ARG"}).encode()


def plazo_vtex(s):
    """shippingEstimate VTEX → horas. Solo `Nd` (días corridos) y `Nh`; `Nbd` son días hábiles y `Nm` minutos: no se convierten, se dejan vacíos."""
    m = re.fullmatch(r"(\d+)(d|h)", s or "")
    return "" if not m else int(m.group(1)) * (24 if m.group(2) == "d" else 1)


def opciones_vtex(http, d):
    """Respuesta de `orderForms/simulation` → (estado, [(metodo, costo, plazo_h, deposito)]). Precios en centavos: costo = (sla.price + la
    ventana de entrega más barata, si hay) / 100. `pickup-in-point` = retiro, el resto domicilio; la más barata de cada método.
    200 sin slas = no_envia (el sitio dice que no lo lleva: es un dato). HTTP error o JSON que no es un orderForm = sin_cotizacion (un hueco)."""
    if http != 200 or not isinstance(d, dict) or not isinstance(d.get("logisticsInfo"), list):
        return "sin_cotizacion", []
    mejor = {}
    for li in d["logisticsInfo"]:
        for s in (li or {}).get("slas") or []:
            p = s.get("price")
            if isinstance(p, bool) or not isinstance(p, (int, float)) or p < 0:
                continue
            ventanas = [w["price"] for w in s.get("availableDeliveryWindows") or [] if isinstance(w.get("price"), (int, float)) and not isinstance(w.get("price"), bool)]
            metodo = "retiro" if s.get("deliveryChannel") == "pickup-in-point" else "domicilio"
            costo = (p + (min(ventanas) if ventanas else 0)) / 100
            dep = ((s.get("pickupStoreInfo") or {}).get("friendlyName") or s.get("name") or "").strip()
            if metodo not in mejor or costo < mejor[metodo][0]:
                mejor[metodo] = (costo, plazo_vtex(s.get("shippingEstimate")), dep)
    return ("ok", [(m, c, h, dep) for m, (c, h, dep) in sorted(mejor.items())]) if mejor else ("no_envia", [])


def cotizar_vtex(url, cp):
    """→ (http, estado, opciones). Resuelve itemId/seller por el slug de la URL (1 request por aviso, con caché) y simula el carrito a ese CP."""
    u = urllib.parse.urlsplit(url)
    base = f"{u.scheme}://{u.netloc}"
    if url not in _ITEMS_VTEX:
        slug = u.path.rstrip("/").removesuffix("/p").rsplit("/", 1)[-1]
        http, d = ml.pedir(f"{base}/api/catalog_system/pub/products/search/{urllib.parse.quote(slug)}/p")
        try:
            it = d[0]["items"][0]
            _ITEMS_VTEX[url] = (str(it["itemId"]), str(it["sellers"][0]["sellerId"]))
        except (TypeError, KeyError, IndexError):
            _ITEMS_VTEX[url] = None
        if not _ITEMS_VTEX[url]:
            return http, "sin_cotizacion", []
    if not _ITEMS_VTEX[url]:
        return 0, "sin_cotizacion", []
    http, d = ml.pedir(f"{base}/api/checkout/pub/orderForms/simulation?sc=1", data=cuerpo_simulacion(*_ITEMS_VTEX[url], cp))
    return (http, *opciones_vtex(http, d))


def envios_vtex(obs, fecha, ypf, capitales, fuente, cotizar=cotizar_vtex, reloj=time.monotonic):
    """Avisos de YPF que `fuente` escribió hoy → (fila `<fuente>_envios`, filas data/envios). Cada aviso (clave = url) del grupo de hoy
    (k=7) se cotiza a la capital de las 24 provincias. Como el envío depende del producto, se cotiza cada aviso, no cada envase."""
    fila = dict(fecha=fecha, fuente=fuente + "_envios", http="", n_items=0, n_con_precio=0, n_sin_stock=0, n_sin_match=0, error="", n_descartados=0)
    combos = {}
    for r in sorted((r for r in obs if r["fuente"] == fuente and r["producto_id"] in ypf and r["fecha"] == fecha), key=lambda r: r["url"]):
        combos.setdefault((r["url"],), r)
    hoy = [r for k, r in combos.items() if grupo_envios(k, fecha)]
    capturado, filas, limite = ahora_utc(), [], reloj() + ENVIOS_VTEX_SEGUNDOS
    for i, r in enumerate(hoy):
        if reloj() > limite:
            fila["error"] = f"cortado por tiempo: {i} de {len(hoy)} avisos"
            break
        for c in capitales:
            http, estado, ops = cotizar(r["url"], c["cp"])
            fila["http"], fila["n_items"] = http, fila["n_items"] + 1
            fila["n_con_precio"] += estado == "ok"
            base = dict(fecha=fecha, capturado=capturado, fuente=fuente, url=r["url"], producto_id=r["producto_id"], litros=r["litros"],
                        unidades=r["unidades"], precio=r["precio"], cp_destino=c["cp"], provincia_destino=c["provincia"])
            filas += [dict(base, costo_envio=num(co), metodo=m, plazo_h=h, estado=estado, deposito=dep) for m, co, h, dep in ops] or \
                     [dict(base, costo_envio="", metodo="", plazo_h="", estado=estado, deposito="")]
    if hoy and not fila["n_con_precio"] and not fila["error"] and not any(f["estado"] == "no_envia" for f in filas):
        fila["error"] = f"ninguna de {fila['n_items']} cotizaciones respondió"
    print(f"{fuente}_envios: {len(hoy)} de {len(combos)} avisos hoy, {fila['n_items']} cotizaciones, {fila['n_con_precio']} ok", flush=True)
    return fila, filas


def main(args):
    if "--renormalizar" in args:
        return renormalizar()
    if "--podar" in args:
        return podar()
    fecha = datetime.now(timezone(timedelta(hours=-3))).date().isoformat()
    fuentes = fuentes_por_defecto()
    if "--fecha" in args:
        fecha = args[args.index("--fecha") + 1]
    if "--solo" in args:
        fuentes = [args[args.index("--solo") + 1]]
    fuentes = sin_fuentes(fuentes, args)
    filas_f, obs, propias, corridas, imgs, rel = [], [], [], set(), {}, relacionados()
    for fu in fuentes:
        try:
            fila, o = correr(fu, fecha, rel, imgs)
        except Exception:  # una fuente que se rompe no tumba a las demás
            traceback.print_exc()
            fila, o = dict(fecha=fecha, fuente=fu, http="", n_items=0, n_con_precio=0, n_sin_stock=0,
                           n_sin_match=0, n_descartados=0, error="excepcion: " + traceback.format_exc().strip().splitlines()[-1][:200]), None
        print(",".join(str(fila[k]) for k in FUENTES), flush=True)
        filas_f.append(fila)
        if o is not None and fu in FECHA_PROPIA:  # precio de nota fiscal: cada fila lleva su fecha, no se reemplaza el día entero
            propias += o
        elif o is not None:  # corrió bien: sus filas del día se reemplazan aunque hoy no haya ninguna
            obs += o
            corridas.add((fecha, fu))
    clave = lambda f: (f["fecha"], f["fuente"])
    escribir_fuentes(os.path.join(DATA, "fuentes.csv"), filas_f)
    if corridas:
        reemplazar(os.path.join(DATA, "obs", fecha[:7] + ".csv"), OBS, obs, clave, corridas)
    for mes in sorted({f["fecha"][:7] for f in propias}):  # cada nota va al archivo de su mes; idempotente por fila
        reemplazar(os.path.join(DATA, "obs", mes + ".csv"), OBS, [f for f in propias if f["fecha"][:7] == mes], clave_fila)
    print("fotos nuevas o cambiadas:", guardar_imagenes(os.path.join(DATA, "imagenes.csv"), imgs, fecha), flush=True)
    ml_ = next((f for f in filas_f if f["fuente"] == "ml"), None)
    if ml_ and ENVIOS_ML:  # después de escribir todo: si la cotización se alarga o se rompe, los precios del día ya están guardados
        vacia = dict(fecha=fecha, fuente="ml_envios", http="", n_items=0, n_con_precio=0, n_sin_stock=0, n_sin_match=0, n_descartados=0)
        try:
            if ml_["error"] and ml_["error"] != "sin token":
                fila, env = dict(vacia, error="ml sin avisos: " + ml_["error"]), None
            else:
                ypf = {p["producto_id"] for p in leer(os.path.join(AQUI, "seed", "productos.csv")) if p["marca"] == "YPF"}
                fila, env = envios_ml(obs, fecha, ypf, ml.TOKEN_HOY, leer(os.path.join(AQUI, "seed", "cp_capitales.csv")))
        except Exception:
            traceback.print_exc()
            fila, env = dict(vacia, error="excepcion: " + traceback.format_exc().strip().splitlines()[-1][:200]), None
        print(",".join(str(fila[k]) for k in FUENTES), flush=True)
        escribir_fuentes(os.path.join(DATA, "fuentes.csv"), [fila])
        if env is not None:  # idempotente: reemplaza las filas de esa fuente y fecha
            reemplazar(os.path.join(DATA, "envios", fecha[:7] + ".csv"), ENVIOS, env, lambda f: (f["fuente"], f["fecha"]), {("ml", fecha)})
    for fu in ENVIOS_VTEX:  # solo fuentes que corrieron bien hoy; aislado: si falla, los precios del día ya están guardados
        if (fecha, fu) not in corridas:
            continue
        try:
            ypf = {p["producto_id"] for p in leer(os.path.join(AQUI, "seed", "productos.csv")) if p["marca"] == "YPF"}
            fila, env = envios_vtex(obs, fecha, ypf, leer(os.path.join(AQUI, "seed", "cp_capitales.csv")), fu)
        except Exception:
            traceback.print_exc()
            fila, env = dict(fecha=fecha, fuente=fu + "_envios", http="", n_items=0, n_con_precio=0, n_sin_stock=0, n_sin_match=0, n_descartados=0,
                             error="excepcion: " + traceback.format_exc().strip().splitlines()[-1][:200]), None
        print(",".join(str(fila[k]) for k in FUENTES), flush=True)
        escribir_fuentes(os.path.join(DATA, "fuentes.csv"), [fila])
        if env is not None:
            reemplazar(os.path.join(DATA, "envios", fecha[:7] + ".csv"), ENVIOS, env, lambda f: (f["fuente"], f["fecha"]), {(fu, fecha)})


def demo():
    avisos = [dict(url="u", ean="", titulo="Aceite Elaion FS 540 4 lts", marca_cruda="Elaion", precio=159999.0, precio_lista="", stock=1, vendedor="C"),
              dict(url="u", ean="", titulo="Aceite Elaion mi 1540 x 1 lt", marca_cruda="Elaion", precio=0.0, precio_lista="", stock=0, vendedor="C"),
              dict(url="u", ean="", titulo="Lubricante Helix Hx7 X1l", marca_cruda="SHELL", precio=66.29, precio_lista="", stock=0, vendedor="J"),
              dict(url="u", ean="", titulo="Aceite Gulf max 20w-50 x 1l", marca_cruda="Gulf", precio=10560.0, precio_lista=10560.0, stock=None, vendedor="C")]
    assert "oficial_br_notaparana" not in fuentes_por_defecto({}) and "oficial_br_notaparana" not in fuentes_por_defecto({"GITHUB_ACTIONS": "true"})
    assert es_senuelo([dict(ncm="320096897", desc="ELAION", gtin="0")] * 3) and not es_senuelo([dict(ncm="27101932"), dict(ncm="34011190")]) and not es_senuelo([])
    assert "ml" not in sin_fuentes(fuentes_por_defecto({}), ["--sin", "ml"]) and "ml_cat" in sin_fuentes(fuentes_por_defecto({}), ["--sin", "ml"])
    assert sin_fuentes(["ml"], ["--solo", "ml", "--sin", "ml"]) == [] and sin_fuentes(["ml"], ["--sin"]) == ["ml"]
    assert "ml" in fuentes_por_defecto({"GITHUB_ACTIONS": "true"}) and "helix_api" in fuentes_por_defecto({"GITHUB_ACTIONS": "true"})
    # combos → servicio, sueltos → obs, con títulos reales de Allende y Daytona (relevamiento 2026-11-23)
    C = tiendas.es_combo
    assert C("Kit de filtros + aceite Kwid 1.0") and C("Cambio de Aceite Semi Sintético Total Quartz 7000 10W-40 + Filtro de Aceite")
    assert not C("ACEITE ELAION 4L 10W40 SEMISINTETICO F30") and not C("Aceite ELAION AURO 5W30 sintético 4L") and not C("Botella 1 Litro Total Refrigerante Glacelf")
    assert tiendas.COMBOS == {"woo_allende", "vtex_daytona"} and "vtex_daytona" in VTEX and VTEX["vtex_daytona"][1] == "C:/3/" and "vtex_tiendaneumaticos" not in VTEX
    assert {"woo_fiatturin", "tn_comprarmarket", "odoo_performancelube", "presta_motoracing"} <= set(fuentes_por_defecto({}))
    assert "woo_allende" in tiendas.WOOCOMMERCE and "woo_allende" in fuentes_por_defecto({}) and "vtex_daytona" in fuentes_por_defecto({})
    sv, sin = servicios_combo("vtex_daytona", [
        dict(url="https://d/a/p", titulo="Cambio de Aceite Semi Sintético Total Quartz 7000 10W-40 + Filtro de Aceite", precio=122115.0, stock=None),
        dict(url="https://d/b/p", titulo="Kit de filtros + aceite Mobi 1.0", precio=0.0, stock=0)], "2026-11-23", "2026-11-23T10:00:00Z")
    assert sin == 1 and len(sv) == 1 and sv[0]["tipo"] == "servicio" and sv[0]["detalle"] == "FILTRO ACEITE" and sv[0]["verificado"] == "1"
    assert sv[0]["producto_id"] == "totalenergies-quartz-7000-10w40" and sv[0]["provincia"] == "" and len(sv[0]) == len(GROK_ALM)
    assert not C("Kit retenes de aceite motor") and not C("Kit de distribucion Gol") and not C("Combo limpieza Total") and not C("Kit de filtros Gol")
    sc, _ = servicios_combo("vtex_daytona", [dict(url="u", titulo="Cambio de Aceite Total Quartz 9000 5W-40 4L", precio=1.0, stock=None)], "2026-11-23", "t")
    assert sc[0]["detalle"] == "KIT"  # sin filtro, «cambio de aceite» no se toma como colocación
    for t in ("Service Total Quartz 9000 5W-40 4L", "Promo Total Quartz 9000 5W-40 4L con filtro de aceite"):
        assert not C(t) and tiendas.NO_ACEITE.search(texto(t))  # el ruteo de la corrida los descarta (no van a obs)
    sg, _ = servicios_combo("woo_allende", [dict(url="u", titulo="Kit aceite 4L", precio=1.0, stock=None)], "2026-11-23", "t")
    assert sg[0]["detalle"] == "KIT"
    sk, _ = servicios_combo("woo_allende", [dict(url="u", titulo="Kit de filtros + aceite Kwid 1.0", precio=79900.0, stock=None)], "2026-11-23", "t")
    assert sk[0]["detalle"] == "FILTROS" and sk[0]["producto_id"] == ""  # sin litros ni marca de aceite: nada que matchear
    wk = tiendas.avisos_woo([dict(id=1, name="Kit de filtros + aceite Kwid 1.0", prices=dict(price="7990000", regular_price="7990000", currency_minor_unit=2),
                                  is_in_stock=True, permalink="u")], True)
    assert len(wk) == 1 and not tiendas.avisos_woo([dict(id=1, name="Kit de filtros + aceite Kwid 1.0", prices=dict(price="1", currency_minor_unit=2))])  # sin combos, el kit sigue fuera
    # helix_api: JSON de ejemplo de GetCombosWeb (sin red). Servicio, no bidón; HX8 con filtros; clave titulo+detalle; sin precio no entra.
    hx = [dict(titulo="Combo Sintetico", descripcion="Shell Helix HX8 Professional AV 5W40 (4 Litros)", imagenWeb="https://x/firmada?sig=1",
               filtroAire=True, filtroAceite=True, colocacion=True, precio=239990),
          dict(titulo="Combo Semisintetico", descripcion="Shell Helix HX7 10W-40 (4 Litros)", filtroAire=False, filtroAceite=False, colocacion=True, precio=96990),
          dict(titulo="Combo Semisintetico", descripcion="Shell Helix HX7 10W-40 (4 Litros)", filtroAire=False, filtroAceite=True, colocacion=True, precio=99990),
          dict(titulo="Combo Mineral", descripcion="Shell Helix HX5 15W-40 (4 Litros)", filtroAire=False, filtroAceite=False, colocacion=False, precio=70000),
          dict(titulo="Combo roto", descripcion="Shell Helix HX7 10W-40 (4 Litros)", colocacion=True, precio=0)]
    fh, sp = filas_helix(hx, "2026-11-19", "2026-11-19T12:00:00Z")
    assert sp == 1 and len(fh) == 4 and all(f["fuente"] == "helix_api" and f["tipo"] == "servicio" and f["verificado"] == "1" and (f["pais"], f["moneda"], f["provincia"]) == ("AR", "ARS", "") for f in fh)
    assert [f for f in fh if f["precio"] == "239990"][0]["producto_id"] == "shell-helix-hx8-professional-av-5w40" and fh[0]["litros"] == "4" and fh[0]["marca"] == "Shell"
    assert fh[0]["detalle"] == "FILTRO AIRE;FILTRO ACEITE;COLOCACIÓN Y CONTROLES" and fh[1]["detalle"] == "COLOCACIÓN Y CONTROLES" and fh[3]["detalle"] == "sin colocación"
    assert len({(f["titulo"], f["detalle"]) for f in fh}) == 4 and "imagenWeb" not in str(fh) and set(fh[0]) == set(GROK_ALM)  # mismo título, otro contenido: no se pisan
    rh = os.path.join(__import__("tempfile").mkdtemp(), "g.csv")
    viejo = dict(fh[0], fuente="grok_helix", precio="1")
    reemplazar(rh, GROK_ALM, [viejo], lambda f: (f["fuente"], f["fecha"]))
    for _ in (1, 2):  # idempotente: la segunda corrida del día no duplica y no toca a grok_helix
        reemplazar(rh, GROK_ALM, fh, lambda f: (f["fuente"], f["fecha"]), {("helix_api", "2026-11-19")})
    assert [f["fuente"] for f in leer(rh)].count("helix_api") == 4 and [f["fuente"] for f in leer(rh)].count("grok_helix") == 1
    # ---- ml_envios: cotización a las 24 capitales (solo con token, rotación k=7, idempotente) ----
    caps = leer(os.path.join(AQUI, "seed", "cp_capitales.csv"))
    assert len(caps) == 24 and all(re.fullmatch(r"\d{4}", c["cp"]) for c in caps) and {c["provincia"] for c in caps} == set(__import__("normalizar").PROVINCIAS)
    PID = "ypf-elaion-ts1040-10w40"
    mk = lambda i, pid=PID: dict(fuente="ml", fecha="2026-11-23", url=f"https://articulo.mercadolibre.com.ar/MLA-{i}", vendedor=str(i),
                                 producto_id=pid, litros="4", unidades=1, precio="63355")
    flota = [mk(i) for i in range(70)]
    clave = lambda r: (r["vendedor"], r["producto_id"], r["litros"], str(r["unidades"]))
    dias = [[r["url"] for r in flota if grupo_envios(clave(r), f"2026-11-{23 + d}")] for d in range(7)]
    assert sorted(u for g in dias for u in g) == sorted(r["url"] for r in flota) and all(dias)  # 7 días seguidos = todas, cada una una vez
    pedidos = []
    def falso(url, cp, tok):
        pedidos.append((url, cp, tok))
        return {"1001": (200, "ok", [("domicilio", 0, 48)]), "8500": (200, "ok", [("domicilio", 6208, ""), ("agencia", 4500, 72)]),
                "9410": (404, "sin_cotizacion", []), "3300": (424, "sin_cotizacion", [])}[cp]
    caps_ = [c for c in caps if c["provincia"] in ("AR-C", "AR-R", "AR-V", "AR-N")]
    fx, ex = envios_ml(flota, "2026-11-23", {PID}, None, caps_, falso)
    assert fx["error"] == "sin token" and ex is None and pedidos == []  # sin token no se hace ni un request
    fx, ex = envios_ml(flota + [mk(999, "otro-producto")], "2026-11-23", {PID}, "tok", caps_, falso)
    hoy_ = [r for r in flota if grupo_envios(clave(r), "2026-11-23")]
    assert {p[2] for p in pedidos} == {"tok"} and fx["n_items"] == len(pedidos) == 4 * len(hoy_) and fx["error"] == "" and fx["n_con_precio"] == 2 * len(hoy_)
    assert {x["url"] for x in ex} == {r["url"] for r in hoy_}  # el producto ajeno no se cotiza
    pr = {x["provincia_destino"]: [y for y in ex if y["provincia_destino"] == x["provincia_destino"] and y["url"] == hoy_[0]["url"]] for x in ex}
    assert [(x["costo_envio"], x["metodo"], x["estado"]) for x in pr["AR-C"]] == [("0", "domicilio", "ok")]  # gratis = 0 declarado
    assert [(x["costo_envio"], x["metodo"], x["plazo_h"]) for x in pr["AR-R"]] == [("6208", "domicilio", ""), ("4500", "agencia", 72)]  # una fila por método
    assert [(x["costo_envio"], x["metodo"], x["estado"], x["cp_destino"]) for x in pr["AR-V"] + pr["AR-N"]] == [("", "", "sin_cotizacion", "9410"), ("", "", "sin_cotizacion", "3300")]
    assert set(ex[0]) == set(ENVIOS) and ex[0]["deposito"] == "" and ex[0]["precio"] == "63355"
    rt = os.path.join(__import__("tempfile").mkdtemp(), "e.csv")
    for _ in (1, 2):  # idempotente: la re-corrida del día reemplaza las filas de ml de esa fecha y no toca otras fechas
        reemplazar(rt, ENVIOS, ex, lambda f: (f["fuente"], f["fecha"]), {("ml", "2026-11-23")})
    reemplazar(rt, ENVIOS, [dict(ex[0], fecha="2026-11-22")], lambda f: (f["fuente"], f["fecha"]), {("ml", "2026-11-22")})
    assert len(leer(rt)) == len(ex) + 1
    t_ = iter(range(0, 10**6, 700))
    fc, ec = envios_ml(flota, "2026-11-23", {PID}, "tok", caps_, falso, lambda: next(t_))
    assert fc["error"].startswith("cortado por tiempo") and 0 < fc["n_items"] < fx["n_items"]
    fn, _ = envios_ml(flota, "2026-11-23", {PID}, "tok", caps_, lambda u, c, t: (403, "sin_cotizacion", []))
    assert fn["n_con_precio"] == 0 and fn["error"].startswith("ninguna de")
    # ---- envios_vtex: simulación de carrito de Norauto (números reales del 2026-11-24, en centavos) ----
    sla = lambda n, p, canal="delivery", est="3bd", **k: dict(name=n, price=p, deliveryChannel=canal, shippingEstimate=est, **k)
    caba = dict(logisticsInfo=[dict(slas=[sla("Envío a domicilio AMBA", 1000000, availableDeliveryWindows=[dict(price=345200), dict(price=400000)]),
                                          sla("Envío a domicilio Andreani", 2792100, est="5d"),
                                          sla("Retiro Norauto Lomas", 0, "pickup-in-point", "1h", pickupStoreInfo=dict(friendlyName="Norauto Lomas", isPickupStore=True)),
                                          sla("Retiro Norauto Tigre", 1345000, "pickup-in-point", "1bd")])], messages=[])
    assert opciones_vtex(200, caba) == ("ok", [("domicilio", 13452.0, "", "Envío a domicilio AMBA"), ("retiro", 0.0, 1, "Norauto Lomas")])  # ventana más barata sumada; 0 solo si la tienda dice 0; 3bd no se convierte
    assert opciones_vtex(200, dict(logisticsInfo=[dict(slas=[sla("Andreani", 3063100, est="5d")])])) == ("ok", [("domicilio", 30631.0, 120, "Andreani")])
    assert opciones_vtex(200, dict(logisticsInfo=[dict(slas=[])], messages=[dict(code="cannotBeDelivered")])) == ("no_envia", [])
    assert opciones_vtex(500, None) == ("sin_cotizacion", []) and opciones_vtex(200, None) == ("sin_cotizacion", []) and opciones_vtex(200, dict(items=[])) == ("sin_cotizacion", [])
    assert plazo_vtex("3bd") == "" and plazo_vtex("2d") == 48 and plazo_vtex("5h") == 5 and plazo_vtex("30m") == "" and plazo_vtex(None) == ""
    assert json.loads(cuerpo_simulacion("1292", "1", "5000")) == dict(items=[dict(id="1292", quantity=1, seller="1")], postalCode="5000", country="ARG")
    nu = lambda i, pid=PID, fu="vtex_norauto": dict(fuente=fu, fecha="2026-11-23", url=f"https://www.norauto.com.ar/helix-{i}/p", vendedor="Norauto",
                                                   producto_id=pid, litros="4", unidades=1, precio="63355")
    fnor = [nu(i) for i in range(40)]
    pv = []
    def cot(url, cp):
        pv.append((url, cp))
        return {"1001": (200, "ok", [("domicilio", 13452.0, "", "AMBA"), ("retiro", 0.0, "", "Norauto Lomas")]), "5000": (200, "ok", [("domicilio", 30631.0, 120, "Andreani")]),
                "4400": (200, "no_envia", []), "9410": (500, "sin_cotizacion", [])}[cp]
    caps4 = [c for c in caps if c["provincia"] in ("AR-C", "AR-X", "AR-A", "AR-V")]
    fv, ev = envios_vtex(fnor + [nu(99, "otro"), nu(98, fu="ml")], "2026-11-23", {PID}, caps4, "vtex_norauto", cot)
    hn = [r for r in fnor if grupo_envios((r["url"],), "2026-11-23")]
    assert fv["fuente"] == "vtex_norauto_envios" and fv["n_items"] == len(pv) == 4 * len(hn) and fv["n_con_precio"] == 2 * len(hn) and fv["error"] == "" and hn
    assert {x["url"] for x in ev} == {r["url"] for r in hn} and {x["fuente"] for x in ev} == {"vtex_norauto"} and set(ev[0]) == set(ENVIOS)  # ni el producto ajeno ni otra fuente
    pn = [(x["provincia_destino"], x["metodo"], x["costo_envio"], x["estado"], x["deposito"]) for x in ev if x["url"] == hn[0]["url"]]
    assert sorted(pn) == sorted([("AR-C", "domicilio", "13452", "ok", "AMBA"), ("AR-C", "retiro", "0", "ok", "Norauto Lomas"), ("AR-X", "domicilio", "30631", "ok", "Andreani"),
                                 ("AR-A", "", "", "no_envia", ""), ("AR-V", "", "", "sin_cotizacion", "")])
    assert [x["estado"] for x in ev if x["provincia_destino"] == "AR-A"] == ["no_envia"] * len(hn) and all(x["costo_envio"] == "" for x in ev if x["estado"] != "ok")
    assert {x["plazo_h"] for x in ev if x["provincia_destino"] == "AR-X"} == {120}
    fm, _ = envios_vtex(fnor, "2026-11-23", {PID}, caps4, "vtex_norauto", lambda u, c: (500, "sin_cotizacion", []))
    assert fm["n_con_precio"] == 0 and fm["error"].startswith("ninguna de")
    tv = iter(range(0, 10**6, 400))
    fk, _ = envios_vtex(fnor, "2026-11-23", {PID}, caps4, "vtex_norauto", cot, lambda: next(tv))
    assert fk["error"].startswith("cortado por tiempo") and 0 < fk["n_items"] < fv["n_items"]
    filas, sin_stock, _, desc = a_obs("vtex_x", "2026-11-03", avisos)
    assert sin_stock == 2 and len(filas) == 2 and desc == 0, (sin_stock, filas)
    assert filas[0]["precio"] == "159999" and filas[0]["litros"] == "4" and filas[0]["stock"] == 1
    assert all(f["provincia"] == "online" and f["pais"] == "AR" and f["moneda"] == "ARS" for f in filas) and OBS[-4:] == ["provincia", "pais", "moneda", "capturado"]
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", f["capturado"]) for f in filas)
    # ---- Brasil ----
    assert pais_fuente("vtex_br_pitstop") == ("BR", "BRL") and pais_fuente("oficial_br_notaparana") == ("BR", "BRL") and pais_fuente("vtex_easy") == ("AR", "ARS")
    # VTEX Brasil: relleno 100/99999 = stock vacío; stock 0 = sin stock; lotes/kits fuera; dedupe por itemId entre términos; 24X1L = 24 × 1 L
    def vp(item, nombre, ean, precio, q, link="https://www.pitstop.com.br/x/p"):
        return {"link": link, "brand": "Elaion", "productName": nombre, "items": [{"itemId": item, "ean": ean, "nameComplete": nombre,
                "sellers": [{"sellerName": "Pitstop", "sellerDefault": True, "commertialOffer": {"Price": precio, "ListPrice": precio, "AvailableQuantity": q}}]}]}
    pv = [vp("1", "921296 - Oleo Motor Elaion 5W30 F50J 1L - Sintetico Api / Sn Tas - Elaion", "7898245572580", 64.7, 99999),
          vp("2", "Oleo Elaion 20W50 Mineral 1l", "7898245572511", 30.9, 1),
          vp("3", "Oleo Motor Elaion 10W30 Semi Sintetico 1L", "7898245572528", 638.2, 100),
          vp("4", "Oleo Motor Elaion 5W40 Sn F50 1L", "7898245570999", 0.0, 0),
          vp("5", "Kit Revisão 4 Litros Óleo Petronas 5W30 + Filtros", "", 329.88, 5),
          vp("6", "12 ÓLEO MOTOR SINTÉTICO 5W30 API SP DEXOS1 GEN2 MOBIL", "2001086539246", 644.75, 100),
          vp("7", "Óleo Do Motor Lubrax Extremo 5W30 Sintético (24 Un)", "", 33.9, 3),
          vp("8", "Oleo Lubrax Essencial 20W50 24X1L", "", 410.0, 3)]
    vistos = set()
    av = avisos_vtex("vtex_br_pitstop", pv, vistos)
    assert [a["titulo"][:12] for a in av] == ["921296 - Ole", "Oleo Elaion ", "Oleo Motor E", "Oleo Motor E", "Oleo Lubrax "], [a["titulo"] for a in av]
    assert [a["stock"] for a in av] == [None, 1, None, 0, 3] and (av[4]["litros"], av[4]["unidades"]) == (1.0, 24) and "litros" not in av[0]
    assert avisos_vtex("vtex_br_pitstop", pv, vistos) == []  # mismo itemId en otro término: una vez
    assert avisos_vtex("vtex_norauto", [vp("9", "x", "", 1, 100)], None)[0]["stock"] == 100  # el 100 solo es relleno en Brasil
    fb, ss, sm, desc = a_obs("vtex_br_pitstop", "2026-11-18", av, relacionados())
    assert [(f["producto_id"], f["pais"], f["moneda"], f["provincia"], f["stock"]) for f in fb] == [
        ("ypf-elaion-f50j-5w30-br", "BR", "BRL", "online", ""), ("ypf-elaion-mineral-20w50-br", "BR", "BRL", "online", 1)], fb
    assert (ss, desc) == (1, 2) and fb[0]["litros"] == "1" and fb[0]["match"] == "ean"  # 10W30 (sin EAN en el seed) y Lubrax 24x1L: descartados, no entran
    # el mismo título argentino no matchea un producto brasileño y al revés (el texto respeta el país; el EAN vale en cualquiera)
    assert normalizar("Aceite Elaion F50J 5W30 1L", "Elaion", "7898245572580", pais="AR")["producto_id"] == "ypf-elaion-f50j-5w30-br"
    assert normalizar("Aceite Shell Helix HX3 20W50 1L", "Shell", pais="BR")["producto_id"] == "shell-helix-hx3-sl-20w50-br"
    assert normalizar("Aceite Shell Helix HX3 20W50 1L", "Shell", pais="AR")["producto_id"] == "shell-helix-hx3-20w50"  # el suyo, no el -br
    assert normalizar("Aceite Shell Helix HX7 10W40 1 L", "Shell", pais="BR")["producto_id"] == ""
    vt, np_ = terminos_br()
    assert vt[:2] == ["oleo elaion", "elaion"] and "oleo lubrax" in vt and "oleo selenia" in vt and "oleo ypf" not in vt, vt
    assert np_[0] == "elaion" and "lubrax valora" in np_ and "ipiranga f1 master" in np_, np_
    # Nota Paraná: solo NCM 27101932 con GTIN; fecha de la nota en hora argentina; GTIN a 13 dígitos; vendedor nunca vacío; provincia de la fila
    assert fecha_np("2026-11-05T02:43:26.555Z") == "2026-11-04" and fecha_np("2026-11-17T16:43:26.555Z") == "2026-11-17" and fecha_np("") == ""
    assert gtin13("07898245572054") == "7898245572054" and gtin13("7898245572580") == "7898245572580" and gtin13("17898245572051") == "17898245572051" and gtin13("") == ""
    est = lambda **k: {"nm_fan": "", "nm_emp": "", "tp_logr": "RUA", "nm_logr": "TIBAGI", "nr_logr": "652", "bairro": "CENTRO", "mun": "CURITIBA", "uf": "PR", **k}
    npf = [dict(id="a", desc="LUB ELAION FS530 5W30 1L", gtin="7898245572580", valor="49.90", datahora="2026-11-17T16:43:26.555Z", ncm="27101932",
                estabelecimento=est(nm_fan="B. BRANCA - AUTO POSTO")),
           dict(id="b", desc="OLEO WURTH ELAION F50J 1L", gtin="07898245572054", valor="49.90", datahora="2026-11-17T02:00:00.000Z", ncm="27101932", estabelecimento=est(nm_fan="-", nm_emp="POSTO X LTDA")),
           dict(id="c", desc="ELAION MI 2050 20W50 12X1 ", gtin="", valor="33.00", datahora="2026-11-05T16:43:26.555Z", ncm="27101932", estabelecimento=est(nm_fan="FLEX")),
           dict(id="d", desc="LUBRAX VALORA 5W30 SP 1L", gtin="7891344014630", valor="40", datahora="2026-11-17T16:00:00Z", ncm="34011190", estabelecimento=est(nm_fan="X")),
           dict(id="a", desc="repetida", gtin="7898245572580", valor="1", datahora="2026-11-17T16:43:26.555Z", ncm="27101932", estabelecimento=est()),
           dict(id="e", desc="ELAION 5W40", gtin="7898245570999", valor="69.9", datahora="2026-11-17T16:43:26.555Z", ncm="27101932", estabelecimento=est(uf="SC"))]
    an = avisos_np(npf, set())
    assert [(a["ean"], a["fecha"], a["vendedor"], a["provincia"]) for a in an] == [
        ("7898245572580", "2026-11-17", "B. BRANCA - AUTO POSTO", "BR-PR"), ("7898245572054", "2026-11-16", "POSTO X LTDA", "BR-PR"),
        ("7898245570999", "2026-11-17", "RUA TIBAGI 652, CENTRO, CURITIBA/SC", "BR-SC")], an
    assert an[0]["sucursal"] == "RUA TIBAGI 652, CENTRO, CURITIBA/PR"
    fn, _, _, desc = a_obs("oficial_br_notaparana", "2026-11-18", an, relacionados())
    assert [(f["fecha"], f["producto_id"], f["pais"], f["moneda"], f["provincia"], f["stock"], f["litros"]) for f in fn] == [
        ("2026-11-17", "ypf-elaion-f50j-5w30-br", "BR", "BRL", "BR-PR", "", "1"), ("2026-11-16", "ypf-elaion-f50j-5w30-br", "BR", "BRL", "BR-PR", "", "1")] and desc == 1, fn
    assert clave_fila(fn[0]) != clave_fila(fn[1]) and clave_fila(fn[0]) == clave_fila(dict(fn[0]))
    # una nota fiscal reescrita no se duplica y no pisa las de otras fechas ni las de otras fuentes
    rt = os.path.join(__import__("tempfile").mkdtemp(), "m.csv")
    reemplazar(rt, OBS, [dict(f, precio="50") for f in fn[:1]], clave_fila)
    reemplazar(rt, OBS, fn, clave_fila)
    assert sorted((f["fecha"], f["precio"]) for f in leer(rt)) == [("2026-11-16", "49.9"), ("2026-11-17", "49.9")]
    # fila vieja sin pais/moneda (data/obs anterior a esta columna): el lector da vacío, que server.py lee como AR/ARS
    assert "pais" not in dict(csv.DictReader(["fecha,fuente", "d,sepa"]).__next__())
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
