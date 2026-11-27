"""Visor y API de LUBRICANTES: sirve site/index.html y calcula /api/* desde seed/ y data/.

Los datos se leen al arrancar y, fuera de Render, se recargan solos (hilo cada LUB_RECARGA_MIN minutos, 5 por defecto, 0 = no)
cuando cambia el commit de HEAD del clon; también cambian con POST /api/cargar (relevamientos de Grok).
Uso: python server.py         (PORT, LUB_CLAVE, LUB_DATOS, LUB_RECARGA_MIN opcionales; siempre 127.0.0.1 salvo en Render)
     python server.py test    (asserts, tiene que dar OK)
"""
import base64
import csv
import gzip
import hashlib
import hmac
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import median, quantiles
from urllib.parse import parse_qs, urlsplit

import macro
import normalizar
from ml import UA
from recolectar import OBS as OBS_F, pais_fuente, relacionados  # mismo filtro "solo lo relacionado con YPF" que el recolector
from tiendas import MAYORISTAS  # fuentes de precio mayorista: fuera del índice salvo ?mayoristas=1

RAIZ = Path(__file__).resolve().parent
SITE = RAIZ / "site"
INDEX = SITE / "index.html"
MODELOS = SITE / "modelos"  # GLB por producto_id: submódulo LUB-MODELOS3D (sin él, modelo() = None y no hay 3D)

PRODUCTOS_F = "producto_id,marca,linea,nombre,segmento,sae,base,api,acea,ilsac,jaso,oem,fuente_specs,verificado".split(",")
EQUIV_F = "eq_id,ypf_id,comp_id,tipo,criterio,evidencia,fuente".split(",")
FUENTES_F = "fecha,fuente,http,n_items,n_con_precio,n_sin_stock,n_sin_match,error,n_descartados".split(",")
OFERTA_F = "fecha,categoria_id,categoria,total_items".split(",")
GROK_F = "fecha,fuente,url,titulo,marca,precio,precio_lista,litros,unidades,tipo,detalle".split(",")  # lo que devuelve la Task de Grok
GROK_PROV_F = GROK_F + ["provincia"]  # encabezado nuevo que también acepta /api/cargar (el de 11 columnas sigue valiendo)
GROK_PAIS_F = GROK_PROV_F + ["pais", "moneda"]  # el encabezado nuevo: /api/cargar acepta los de 11, 12 y 14 columnas
GROK_ALM_F = GROK_F + ["verificado", "producto_id", "match", "cargado", "provincia", "pais", "moneda"]  # lo que se guarda en data/grok/
# País = ISO 3166-1 alfa-2 y moneda = ISO 4217 de PUBLICACIÓN (Benco publica en USD en UY). Los países con respuesta propia en la API son PAISES.
PAISES = {"AR": ("Argentina", "ARS"), "BR": ("Brasil", "BRL")}
MONEDA_DEFECTO = {"AR": "ARS", "BR": "BRL", "CL": "CLP", "UY": "UYU", "PY": "PYG", "BO": "BOB"}  # países del relevamiento de limítrofes
MONEDAS = {"ARS", "BRL", "CLP", "UYU", "PYG", "BOB", "USD"}
# Decisión del usuario 2026-11-24: estas cargas de Grok reemplazan a la API de ML solo los días en que `ml` no tiene ninguna observación.
RESPALDO_GROK = {"grok_mercadolibre": "ml", "grok_mercadolibre_www": "ml"}
_NOTA_RESPALDO = "respaldo de la API de Mercado Libre: cuenta solo los días en que la API no trajo datos; precios sin verificar"
NOTAS_FUENTE = {
    **dict.fromkeys(RESPALDO_GROK, _NOTA_RESPALDO),
    "ml_envios": "pausada desde 2026-11-24 por decisión del usuario: Mercado Libre vuelve a pedir solo precios",
    "oficial_br_notaparana": "pausada desde 2026-11-18: la API devuelve datos señuelo al acceso automatizado; no se esquiva",
    "helix_api": "automática: combos Shell de helixturno.com.ar por su API JSON (servicios con mano de obra, no $/L de bidón)",
    "casa": "servidor FLN Data Analysis (celular o PC): SEPA, la SE y el resto; GitHub corre Mercado Libre y hace de respaldo",
    "fx_bcb_ptax": "tipo de cambio oficial PTAX (venta) del Banco Central do Brasil: solo para mostrar en USD",
    "fx_bcra": "cotización del dólar publicada por el BCRA (Estadísticas Cambiarias): solo para mostrar en USD",
}
SITIOS_F = ["fuente", "host", "descripcion"]
VITRINA_F = ("fecha,producto_id,nombre,linea,segmento,sae,base,imagen,imagen_fuente,ypf_n,ypf_promedio_litro,ypf_min_litro,"
             "ypf_max_litro,ypf_mediana_litro,presentacion_comun_l,promedio_presentacion,ypf_mas_barato_fuente,"
             "ypf_mas_barato_vendedor,ypf_mas_barato_precio_litro,ypf_mas_barato_url,comp_n,comp_promedio_litro,comp_min_litro,"
             "comp_max_litro,n_equivalentes,dif_pct,indice30_indice,indice30_mediana_ypf_litro,indice30_mediana_comp_litro,"
             "indice30_n_ypf,indice30_n_comp,indice30_desde,indice30_hasta,pais,moneda").split(",")
# Sanidad del $/L en la vitrina: un aviso a más de SANIDAD veces la mediana de su producto es un envase mal leído (caja
# como bidón, "R3" como 3 L), y un equivalente cuya mediana está a más de RANGO_EQ veces la del YPF no promedia.
# ponytail: umbrales fijos a ojo sobre noviembre 2026; si aparecen premium reales a más de 3x, revisar RANGO_EQ.
SANIDAD, RANGO_EQ = 2.5, 3
MOTIVO_CHICOS = "solo envases de menos de 0,5 L en la ventana"
LITROS_MIN_INDICE = 0.5  # los envases de menos de 0,5 L por unidad (sachets, 100 mL de 2T) no entran a ningún índice; siguen en obs, comparador, /api/producto y vitrina
VENTANA_DIAS = 3  # vitrina: solo avisos vistos en los últimos 3 días (el último día con datos y los 2 anteriores)
SERVICIOS_F = [c for c in GROK_ALM_F if c not in ("tipo", "producto_id", "match")] + ["solo_aceite", "precio_litro"]
# Un combo con cualquiera de estos ítems en `detalle` no es "aceite + colocación": su precio no se divide por litro.
# ponytail: lista negra de palabras; un repuesto que no esté acá se dividiría. Sumarlo si aparece.
RX_EXTRA = re.compile(r"filtro|kit|aditiv|refrigerante|lavado|buj[ií]a|pastilla|l[ií]quido|limpi|alineaci|balanceo|neum[aá]tic|"
                      r"escobill|l[aá]mpara|bater[ií]a|correa|flushing|repuesto|sin colocaci", re.I)  # "sin colocación" (helix_api): no es aceite + colocación
MAX_FILAS, MAX_CARGAS_DIA, MAX_BYTES = 500, 30, 2_000_000
RX_FUENTE = re.compile(r"grok_[a-z0-9_]{2,30}")
RX_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")

CAMPOS = {
    "productos": PRODUCTOS_F,
    "equivalencias": EQUIV_F + ["ypf_marca", "ypf_nombre", "comp_marca", "comp_nombre"],
    "ultimo": ["producto_id", "fuente", "litros", "fecha", "precio", "precio_litro", "n", "url", "verificado", "pais", "moneda"],
    "grok": GROK_ALM_F,
    "servicios": SERVICIOS_F,
    "grok_sitios": SITIOS_F,
    "obs": OBS_F,
    "serie": ["fecha", "fuente", "precio_litro", "n", "pais", "moneda"],
    "indice": ["fecha", "segmento", "sae", "marca", "mediana_litro", "n", "indice", "pais", "moneda"],
    "fuentes": FUENTES_F + ["ultimo_ok", "dias_sin_datos", "dias_sin_correr", "pais", "nota"],
    "sin_match": ["fuente", "titulo", "ean", "marca", "precio", "litros", "unidades", "url", "primera", "ultima", "veces"],
    "oferta_ml": OFERTA_F,
    "vitrina": VITRINA_F,
}
CAMPOS["bi_precios"] = ["fecha", "capturado", "producto_id", "fuente", "canal", "vendedor", "sucursal", "provincia", "pais", "moneda", "precio", "litros", "unidades",
                        "precio_litro", "precio_usd_litro", "url", "match", "verificado"]
CAMPOS["bi_indice"] = ["fecha", "pais", "moneda", "segmento", "sae", "marca", "mediana_litro", "mediana_ypf_litro", "indice", "n"]
CAMPOS["bi_indice_competencia"] = ["fecha", "producto_id", "pais", "moneda", "indice", "mediana_ypf_litro", "mediana_comp_litro", "n_ypf", "n_comp"]
CAMPOS["bi_productos"] = PRODUCTOS_F + ["es_ypf"]
CAMPOS["bi_equivalencias"] = EQUIV_F[1:]  # ypf_id, comp_id, tipo, criterio, evidencia, fuente
CAMPOS["bi_fuentes"] = ["fuente", "canal", "pais", "tipo", "ultima_fecha"]
CAMPOS["bi_provincias"] = ["codigo", "nombre", "region", "pais", "online"]
CAMPOS["puesto"] = ["producto_id", "provincia", "cp", "fuente", "precio_puesto", "precio", "envio", "metodo", "vendedor", "url", "fecha",
                    "minimo_litro_puesto", "mediana_litro_puesto", "n", "n_no_envia", "n_sin_cotizacion", "pais", "moneda", "deposito", "origen_provincia", "origen_fuente", "plazo"]
CAMPOS["indice_con_mayoristas"] = CAMPOS["indice"]
CAMPOS["indice/pares"] = ["producto_id", "nombre", "linea", "segmento", "sae", "base", "indice", "mediana_ypf_litro", "mediana_comp_litro", "n_ypf", "n_comp", "motivo", "pais", "moneda", "desde", "hasta"]
CAMPOS["indice_celdas"] = ["segmento", "sae", "marca", "mediana_litro", "indice", "n", "fecha_min", "fecha_max", "productos", "pais", "moneda", "desde", "hasta", "dias"]
CAMPOS["macro"] = MACRO_F = ["fecha", "id", "valor", "signo"]
CAMPOS["mercado_share"] = ["mes", "empresa", "volumen", "total", "share"]
CAMPOS["mercado_filas"] = ["mes", "empresa", "producto", "canal", "provincia", "cantidad"]


def pais_r(r):
    """País de una observación: las filas viejas (sin la columna) son Argentina."""
    return r.get("pais") or "AR"


def moneda_r(r):
    return r.get("moneda") or MONEDA_DEFECTO.get(pais_r(r), "ARS")


def de_pais(d, pais):
    """Una vista de `d` con solo las observaciones de un país: nada se calcula mezclando países ni monedas."""
    return {**d, "obs": [r for r in d["obs"] if pais_r(r) == pais]}


def subdivisiones(pais):
    """Provincias/estados válidos de un país (ISO 3166-2), sin `online`."""
    return normalizar.SUBDIVISIONES.get(pais, {})


def tabla_fx(d):
    """{(moneda, AAAA-MM-DD): (unidades por USD, fuente)}. BRL sale de data/fx.csv (PTAX); ARS de fx.csv (BCRA, Estadísticas Cambiarias) y, solo en las
    fechas sin esa fila, de series.csv (BCRA, valuación, histórico). Cada cotización lleva su fuente. Un día sin fila no existe."""
    t = {(r["moneda"], r["fecha"]): (num(r["por_usd"]), r["fuente"]) for r in d.get("fx", []) if num(r["por_usd"])}
    for pt in d.get("macro_series", {}).get(ID_TC, []):
        if pt["valor"]:
            t.setdefault(("ARS", pt["fecha"][:10]), (pt["valor"], "BCRA (datos.gob.ar)"))
    return t


USD_CAMPOS = ("precio", "precio_litro", "mediana_litro", "mediana_ypf_litro", "mediana_comp_litro", "promedio_litro", "min_litro", "max_litro", "promedio_presentacion")


ID_TC = "92.2_TIPO_CAMBIION_0_0_21_24"
FX_FUENTES = {"bcra_cambiarias": ("BCRA, cotización de divisas (Estadísticas Cambiarias)", "https://www.bcra.gob.ar/documentacion-apis/?fileName=estadisticascambiarias-v1"),
              "bcb_ptax": ("BCB PTAX (venta)", "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/aplicacao#!/recursos"),
              "BCRA (datos.gob.ar)": ("BCRA, tipo de cambio de valuación (datos.gob.ar)", "https://datos.gob.ar/series/api/series/?ids=" + ID_TC)}


def fx_lista(tabla, moneda):
    """Cotizaciones reales de una moneda, la más reciente primero: alimenta el selector de /api/fx."""
    return [{"fecha": f, "por_usd": v[0], "fuente": v[1], "fuente_nombre": FX_FUENTES.get(v[1], (v[1], ""))[0], "fuente_url": FX_FUENTES.get(v[1], ("", ""))[1]}
            for (m, f), v in sorted(tabla.items(), reverse=True) if m == moneda]


def fx_fecha_error(tabla, moneda, fx_fecha):
    """None si fx_fecha es AAAA-MM-DD con cotización de esa moneda; si no, el mensaje de 400 (con las fechas cercanas que sí existen; nunca se interpola)."""
    try:
        date.fromisoformat(fx_fecha)
    except ValueError:
        return {"error": "fx_fecha tiene que ser AAAA-MM-DD"}
    if (moneda, fx_fecha) in tabla:
        return None
    fs = sorted(f for (m, f) in tabla if m == moneda)
    cerca = [f for f in fs if f < fx_fecha][-3:] + [f for f in fs if f > fx_fecha][:3]
    return {"error": f"sin cotización de {moneda} el {fx_fecha}", "fechas_cercanas": cerca}


USD_CAMPOS = ("precio", "precio_litro", "mediana_litro", "mediana_ypf_litro", "mediana_comp_litro", "promedio_litro", "min_litro", "max_litro", "promedio_presentacion")


def con_usd(o, moneda, tabla, fecha="", fx_fecha=""):
    """?usd=1: agrega `<campo>_usd` junto a cada precio, con `fx_fecha` y `fx_fuente` de ESE día exacto (sin cotización ese día = null, nunca el
    día anterior). La fecha es la del propio objeto o, si no tiene, la del que lo contiene. Con `fx_fecha` (?fx_fecha=) todo usa esa cotización.
    Solo para visualizar: lo guardado sigue en su moneda."""
    if isinstance(o, list):
        return [con_usd(x, moneda, tabla, fecha, fx_fecha) for x in o]
    if not isinstance(o, dict):
        return o
    f = o["fecha"] if isinstance(o.get("fecha"), str) else fecha
    m = o.get("moneda") or moneda
    out = {k: con_usd(v, m, tabla, f, fx_fecha) for k, v in o.items()}
    campos = [k for k in USD_CAMPOS if k in o and not isinstance(o[k], (dict, list))]
    if campos:
        kd = fx_fecha or f
        fx = tabla.get((m, kd)) if m != "USD" else (1.0, "USD")
        for k in campos:
            out[k + "_usd"] = round(o[k] / fx[0], 3) if fx and isinstance(o[k], (int, float)) else None
        out["fx_fecha"], out["fx_fuente"] = (kd, fx[1]) if fx else (None, None)
    return out


def leer_csv(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def precio_litro(r):
    precio, litros = num(r.get("precio")), num(r.get("litros"))
    unidades = num(r.get("unidades")) or 1
    if not precio or not litros or precio <= 0 or litros <= 0:
        return None
    return precio / (litros * unidades)


def cargar(raiz):
    raiz = Path(raiz)
    meses = {p.stem: leer_csv(p) for p in sorted((raiz / "data" / "obs").glob("*.csv"))}
    d = {
        "productos": leer_csv(raiz / "seed" / "productos.csv"),
        "equivalencias": leer_csv(raiz / "seed" / "equivalencias.csv"),
        "meses": meses,
        "obs_base": [r for filas in meses.values() for r in filas],
        "fuentes": leer_csv(raiz / "data" / "fuentes.csv"),
        "oferta_ml": leer_csv(raiz / "data" / "ml_oferta.csv"),
        "grok_meses": {p.stem: leer_csv(p) for p in sorted((raiz / "data" / "grok").glob("*.csv"))},
        "grok_sitios": leer_csv(raiz / "seed" / "grok_sitios.csv"),
        "imagenes": leer_csv(raiz / "data" / "imagenes.csv"),
        "macro": leer_csv(raiz / "data" / "macro" / "series.csv"),
        "macro_seed": leer_csv(raiz / "seed" / "macro_series.csv"),
        "marcas_seed": leer_csv(raiz / "seed" / "marcas_empresas.csv"),
        "energia": leer_energia(raiz / "data" / "macro" / "energia.csv"),
        "fx": leer_csv(raiz / "data" / "fx.csv"),
        "envios": [r for p in sorted((raiz / "data" / "envios").glob("*.csv")) for r in leer_csv(p)],
        "cp": leer_csv(raiz / "seed" / "cp_capitales.csv"),
        "correo": [r for p in sorted((raiz / "data" / "correo").glob("*.csv")) for r in leer_csv(p)],
        "envases_correo": leer_csv(raiz / "seed" / "envases_correo.csv"),
        "origen_fuentes": leer_csv(raiz / "seed" / "origen_fuentes.csv"),
    }
    integrar_grok(d)
    d["energia_por_producto"] = defaultdict(list)
    for f in d["energia"]:
        if not f[2].startswith("Gasoil"):
            d["energia_por_producto"][f[2]].append(f)
    d["macro_meta"], d["macro_series"] = series_macro(d)
    d["fx_tabla"] = tabla_fx(d)
    return d


def firma_datos(raiz):
    """Qué versión de data/ hay en disco: el commit de HEAD del clon; sin git (o sin repo), el mtime de data/fuentes.csv.
    Con git no se mira el mtime: mientras el recolector escribe a medias no cambia el commit, así no se recarga un estado a medio escribir."""
    try:
        p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=raiz, capture_output=True, text=True, timeout=10)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return "mtime:" + str(int((Path(raiz) / "data" / "fuentes.csv").stat().st_mtime))
    except OSError:
        return ""


def recargar(raiz):
    """Construye el estado nuevo completo y recién ahí reemplaza las referencias; si algo falla sigue sirviendo lo anterior.
    Devuelve True si recargó. ponytail: datos y calc se asignan en dos pasos; un pedido en ese instante puede ver datos nuevos con calc viejo (una vez, sin daño)."""
    firma = firma_datos(raiz)
    if firma == Handler.firma:
        return False
    try:
        d = cargar(raiz)
        c = calcular(d)
    except Exception as e:
        print(f"recarga fallida, sigo con los datos anteriores: {e!r}", file=sys.stderr, flush=True)
        return False
    Handler.datos, Handler.calc, Handler.firma = d, c, firma
    print(f"datos recargados ({firma[:12]}): {len(d['obs'])} observaciones", flush=True)
    return True


def vigilar(raiz, minutos):
    """Recarga los datos si cambió el commit. El redeploy del código en el celu lo hace el vigía de CELU-SERVIDOR (`sv restart lub-server`)."""
    while True:
        time.sleep(minutos * 60)
        recargar(raiz)


def salud():
    """Sin secretos: qué versión de datos se sirve y la fecha de la última observación. El estado del equipo vive en CELU-SERVIDOR."""
    obs = (Handler.datos or {}).get("obs") or []
    f = Handler.firma or ""
    return {"ok": True, "commit": "" if f.startswith("mtime:") else f[:12],
            "ultimo_dato": max((r["fecha"] for r in obs), default="")}


def integrar_grok(d):
    """Las filas Grok de tipo producto entran a `obs` como cualquier fuente; los servicios nunca (no son $/L)."""
    d["grok"] = [r for filas in d["grok_meses"].values() for r in filas]
    d["obs"] = d["obs_base"] + [
        {**dict.fromkeys(OBS_F, ""), **{k: r.get(k) or "" for k in GROK_ALM_F if k in OBS_F or k in ("verificado", "cargado")}}
        for r in d["grok"] if r["tipo"] == "producto"]
    dias = defaultdict(set)  # fechas con obs de cada fuente cubierta (antes de sumar Grok)
    for r in d["obs_base"]:
        if r["fuente"] in RESPALDO_GROK.values():
            dias[r["fuente"]].add(r["fecha"])
    for r in d["obs"][len(d["obs_base"]):]:
        r["capturado"] = r.get("cargado", "")  # hora del POST de /api/cargar (ya viene ISO UTC); las filas viejas sin hora quedan vacías
        cubre = RESPALDO_GROK.get(r["fuente"])
        if cubre and r.get("verificado") == "0" and r["fecha"] not in dias[cubre]:
            r["verificado"] = "respaldo"  # la API no trajo nada ese día: cuenta en los cálculos, rotulada


def clave_grok(r):
    """Una fila Grok es la misma solo si coincide también `detalle`, `provincia`, `pais` y `moneda`: combos de una URL que cambian solo por filtro, vehículo, zona o país son filas distintas."""
    return r["fuente"], r["fecha"], r["url"], r["titulo"], r["detalle"], r.get("provincia") or "", pais_r(r), moneda_r(r)


def litro_servicio(r):
    """Combo de solo aceite + colocación → $/L (con la mano de obra adentro). Con filtros u otro repuesto, o sin litros → vacío."""
    litros = pos(r["litros"])
    if not litros or RX_EXTRA.search(r["detalle"]):
        return "0", ""
    return "1", round(float(r["precio"]) / (litros * (pos(r["unidades"]) or 1)), 2)


def servicios(grok):
    ult = {}
    for r in sorted(grok, key=lambda r: r["fecha"]):
        if r["tipo"] == "servicio":
            ult[clave_grok(r)[:1] + clave_grok(r)[2:]] = r
    out = []
    for r in ult.values():
        solo, pl = litro_servicio(r)
        out.append({**r, "solo_aceite": solo, "precio_litro": pl})
    return sorted(out, key=lambda r: (r["fuente"], r["titulo"]))


def equivalencias(d):
    prod = {p["producto_id"]: p for p in d["productos"]}
    out = []
    for e in d["equivalencias"]:
        y, c = prod.get(e["ypf_id"], {}), prod.get(e["comp_id"], {})
        out.append({**e, "ypf_marca": y.get("marca", ""), "ypf_nombre": y.get("nombre", ""),
                    "comp_marca": c.get("marca", ""), "comp_nombre": c.get("nombre", "")})
    return out


def ultimo(obs, pais="AR"):
    grupos = defaultdict(list)
    for r in obs:
        pl = precio_litro(r)
        if r["producto_id"] and pl is not None and pais_r(r) == pais:
            grupos[(r["producto_id"], r["fuente"], num(r["litros"]), moneda_r(r))].append((r["fecha"], pl, num(r["precio"]), r["url"], r.get("verificado") or ""))
    out = []
    for (pid, fuente, litros, moneda), xs in sorted(grupos.items()):
        fecha = max(x[0] for x in xs)
        dia = [x for x in xs if x[0] == fecha]  # varias sucursales/vendedores el mismo día → mediana
        out.append({"producto_id": pid, "fuente": fuente, "litros": litros, "fecha": fecha,
                    "precio": round(median(x[2] for x in dia), 2),
                    "precio_litro": round(median(x[1] for x in dia), 2), "n": len(dia), "url": dia[0][3],
                    "verificado": "" if not dia[0][4] else "1" if all(x[4] == "1" for x in dia) else "respaldo" if all(x[4] == "respaldo" for x in dia) else "0",
                    "pais": pais, "moneda": moneda})
    return out


def serie(obs, pid, pais="AR"):
    grupos = defaultdict(list)
    for r in obs:
        pl = precio_litro(r)
        if r["producto_id"] == pid and pl is not None and pais_r(r) == pais:
            grupos[(r["fecha"], r["fuente"], moneda_r(r))].append(pl)
    return [{"fecha": f, "fuente": fu, "precio_litro": round(median(v), 2), "n": len(v), "pais": pais, "moneda": mo}
            for (f, fu, mo), v in sorted(grupos.items())]


def indice(d, mayoristas=False, pais="AR"):
    """Índice YPF = 100 DENTRO de un país y una moneda. Para cada fecha F con datos: los avisos de la ventana de VENTANA_DIAS días que termina en F
    (cada aviso una vez, con su observación más reciente de la ventana; la misma regla que la vitrina, /api/producto e /api/indice/celdas: `_clave_aviso(r, None)`,
    `_validos`, `cuerdos`), mediana de $/L por (segmento, SAE, marca) y contra la de YPF del mismo grupo. `n` = avisos. Nunca más de VENTANA_DIAS días de arrastre.
    Barrido incremental (como bi_indice_competencia): se mantiene el último aviso vivo de cada clave y salen los que pasan de la ventana."""
    prod = {p["producto_id"]: p for p in d["productos"]}
    obs = [r for r in d["obs"] if pais_r(r) == pais and r["producto_id"] in prod]
    por_dia = defaultdict(list)
    for r in obs:
        por_dia[r["fecha"]].append(r)
    vivos, out = {}, []
    for fecha in sorted(por_dia):
        for r in por_dia[fecha]:
            k = _clave_aviso(r, None)
            if k not in vivos or r["fecha"] >= vivos[k]["fecha"]:
                vivos[k] = {**r, "pl": precio_litro(r)}
        ini = (date.fromisoformat(fecha) - timedelta(days=VENTANA_DIAS - 1)).isoformat()
        vivos = {k: r for k, r in vivos.items() if r["fecha"] >= ini}
        por = defaultdict(list)
        for r in vivos.values():
            por[r["producto_id"]].append(r)
        grupos = defaultdict(list)
        for pid, rs in por.items():
            xs = _validos_indice(rs, mayoristas)
            for pl, r in cuerdos(xs) if xs else []:
                p = prod[pid]
                grupos[(p["segmento"], p["sae"], p["marca"], moneda_r(r))].append(pl)
        med = {k: median(v) for k, v in grupos.items()}
        for (seg, sae, marca, mo), m in sorted(med.items()):
            ypf = med.get((seg, sae, "YPF", mo))
            out.append({"fecha": fecha, "segmento": seg, "sae": sae, "marca": marca, "mediana_litro": round(m, 2),
                        "n": len(grupos[(seg, sae, marca, mo)]), "indice": round(m / ypf * 100, 1) if ypf else None, "pais": pais, "moneda": mo})
    return out


def indice_celdas(d, dias=30, hasta=None, mayoristas=False, pais="AR"):
    """/api/indice/celdas: una celda por (segmento, SAE, marca) con la mediana de $/L de los avisos de la ventana de `dias` que termina en `hasta`
    (default: el último día con datos) y los $/L de cada aviso (para la distribución). Misma definición de aviso, sanidad y exclusiones que la vitrina
    y /api/producto (`_avisos`, `_validos`, `cuerdos`). `indice` = mediana de la marca / mediana de YPF del mismo segmento y SAE × 100; null sin YPF."""
    d = de_pais(d, pais)
    prod = {p["producto_id"]: p for p in d["productos"]}
    h, por = _avisos(d, dias, set(prod), None, None, hasta)
    desde, _ = desde_hasta(d, dias, None, hasta)
    celdas, chicos = defaultdict(list), Counter()
    for pid, rs in por.items():
        p = prod[pid]
        chicos[(p["segmento"], p["sae"], p["marca"])] += sum(_chico(r) for _, r in _validos(rs, mayoristas))
        xs = _validos_indice(rs, mayoristas)
        for pl, r in cuerdos(xs) if xs else []:  # cuerdos no admite lista vacía (producto con avisos solo sin litros / mayoristas / envases chicos)
            celdas[(p["segmento"], p["sae"], p["marca"])].append((pl, r["fecha"], pid))
    med = {k: median(x[0] for x in v) for k, v in celdas.items()}
    out = []
    for (seg, sae, marca), v in sorted(celdas.items()):
        ypf = med.get((seg, sae, "YPF"))
        m = med[(seg, sae, marca)]
        out.append({"segmento": seg, "sae": sae, "marca": marca, "mediana_litro": round(m, 2), "indice": round(m / ypf * 100, 1) if ypf else None,
                    "n": len(v), "fecha_min": min(x[1] for x in v), "fecha_max": max(x[1] for x in v),
                    "precios_litro": sorted(round(x[0], 2) for x in v), "productos": sorted({x[2] for x in v})})
    sin_dato = [{"segmento": seg, "sae": sae, "marca": marca, "n_chicos": n, "motivo": MOTIVO_CHICOS}
                for (seg, sae, marca), n in sorted(chicos.items()) if n and (seg, sae, marca) not in celdas]
    return {"pais": pais, "moneda": PAISES[pais][1], "desde": desde or None, "hasta": h or None, "dias": dias,
            "sin_dato": sin_dato,
            "nota": f"Mediana de $/L de los avisos de los últimos {dias} días que terminan el {h}: cada aviso cuenta una vez, con su observación más reciente de la ventana "
                    "(no es el índice de un solo día de /api/indice). Sin mayoristas ni Grok sin verificar, salvo mayoristas=1, y sin envases de menos de {LITROS_MIN_INDICE:g} L por unidad (sachets): "
                    "una celda que solo tiene esos avisos va en `sin_dato` con su motivo. Una celda ausente es sin dato, no cero.",
            "celdas": out}


def celdas_usd(v, tabla, fx_fecha=""):
    """?usd=1 de /api/indice/celdas: `mediana_litro_usd` y `precios_litro_usd` con la cotización de la fecha `hasta` (o `fx_fecha`); sin cotización, null."""
    o = con_usd(v, v["moneda"], tabla, fecha=v["hasta"] or "", fx_fecha=fx_fecha)
    for c in o["celdas"]:
        fx = c["fx_fecha"] and tabla.get((v["moneda"], c["fx_fecha"]))
        c["precios_litro_usd"] = [round(p / fx[0], 3) for p in c["precios_litro"]] if fx else None
    return o


def pais_de_fuente(f):
    return "BR" if f.startswith("fx_bcb") else pais_fuente(f)[0]


# Fuentes que se dejaron de recolectar para siempre (distinto de PAUSADAS, que se muestran): fuente → (fecha, motivo). No salen en /api/fuentes ni en avisos.
BAJA = {"vtex_jumbo": ("2026-11-19", "Jumbo ya no vende aceite de motor online: la categoría son fichas discontinuadas, siempre sin stock y con precios basura")}


def fuentes(d, hoy):
    por_fuente = defaultdict(list)
    for r in d["fuentes"]:
        por_fuente[r["fuente"]].append(r)
    out = []
    for fuente, filas in sorted(por_fuente.items()):
        if fuente in BAJA:
            continue  # dada de baja: ni fila en Fuentes ni aviso; su histórico queda en data/
        filas.sort(key=lambda r: r["fecha"])  # estable: la última corrida del día queda al final
        # error vacío = corrida OK (recolectar.py ya marca n_items == 0 con HTTP 200 como error)
        oks = [r["fecha"] for r in filas if not r["error"]]
        ultimo_ok = oks[-1] if oks else None
        dias = (hoy - date.fromisoformat(ultimo_ok)).days if ultimo_ok else None
        out.append({**{k: filas[-1].get(k, "") for k in FUENTES_F}, "ultimo_ok": ultimo_ok, "dias_sin_datos": dias,
                    "dias_sin_correr": (hoy - date.fromisoformat(filas[-1]["fecha"])).days,  # contra la última fila, con o sin error (aviso de la fila `casa`)
                    "pais": pais_de_fuente(fuente), "nota": NOTAS_FUENTE.get(fuente, "")})
    return avisos(sorted(out + fuentes_grok(d, hoy), key=lambda r: r["fuente"]), d["fuentes"], hoy)


# Cadencia esperada de cada fuente: lo que no está acá es diaria. `pausada` = decisión documentada, no falla; `manual` = carga a mano.
CADENCIA = {"macro_energia": "mensual", "oficial_br_notaparana": "pausada", "ml_envios": "pausada"}
MENSUAL_DIAS, MANUAL_DIAS = 45, 30  # tope de antigüedad de la última bajada buena (la SE publica una vez por mes) / de una carga manual
# fuente → la que la cubre: si la cubridora está al día, la cubierta no es un aviso (la carga manual alternativa, la serie que ya no es la fuente del dato)
CUBIERTA = {"grok_helix": "helix_api", "macro_92_2_tipo_cambiion_0_0_21_24": "fx_bcra",
            # sitios que Grok cargaba y desde 2026-11-21 lee el recolector: su histórico grok_* no alerta a los 30 días
            **{f"grok_{s}": f"tn_{s}" for s in ("rano", "olafil", "lubrimaster", "lubricentrodg", "exporepuestos", "netrenault", "gramaglia", "torooils")},
            "grok_larutaok": "woo_larutaok", "grok_ceridono": "woo_ceridono",
            # 2026-11-23: Allende y Daytona; Tienda Neumáticos es el mismo catálogo VTEX que Daytona (misma cubridora)
            "grok_motoracing": "presta_motoracing", "grok_allende": "woo_allende", "grok_daytona": "vtex_daytona", "grok_tiendaneumaticos": "vtex_daytona"}


def cadencia(f):
    if f in CADENCIA:
        return CADENCIA[f]
    return "manual" if f.startswith("grok_") else "serie" if f.startswith("macro_") and f != "macro_series" else "diaria"


def avisos(rows, filas, hoy):
    """Agrega a cada fila `cadencia`, `alerta` (bool: hay algo que arreglar), `motivo` (por qué; "" si no alerta) y `aviso`
    (nota informativa que no es falla: pausada, cubierta, sin primera carga). El visor usa esto y no recalcula.
    Una `macro_<id>` sin error propio toma su edad de la última corrida de `macro_series` sin error (solo escribe fila al fallar o recuperarse);
    `macro_energia` (mensual, hoy solo en casa) alerta por antigüedad de la bajada o porque el paso `energia` de `casa` falló después de ella,
    no por una fila vieja de una ruta que ya no corre (GitHub)."""
    ms = max((r["fecha"] for r in filas if r["fuente"] == "macro_series" and not r["error"]), default=None)
    por = {r["fuente"]: r for r in rows}
    for r in rows:
        f, c, mot, av = r["fuente"], cadencia(r["fuente"]), "", ""
        r["cadencia"], dias, nunca = c, r["dias_sin_datos"], r["ultimo_ok"] is None
        if f == "casa":
            pass  # su aviso (más de 2 días sin correr) lo arma el visor con dias_sin_correr
        elif c == "pausada":
            av = "pausada por decisión documentada" if nunca else ""
        elif c == "serie":
            if ms and not r["error"]:
                r["ultimo_ok"], r["dias_sin_datos"] = ms, (hoy - date.fromisoformat(ms)).days
            if r["error"]:
                mot = f"falló: {r['error']}"
            elif not ms:
                mot = "macro_series nunca corrió bien"
            elif r["dias_sin_datos"] > 1:
                mot = f"macro_series sin correr bien hace {r['dias_sin_datos']} días"
        elif c == "mensual":
            malo = [x for x in filas if x["fuente"] == "casa" and "energia" in x["error"].split(":", 1)[-1] and (nunca or x["fecha"] > r["ultimo_ok"])]
            if nunca:
                mot = "nunca hubo una bajada buena"
            elif dias > MENSUAL_DIAS:
                mot = f"última bajada buena hace {dias} días (la SE publica una vez por mes)"
            elif malo:
                mot = f"el servidor FLN Data Analysis falló en el paso energia el {malo[-1]['fecha']}, después de la última bajada buena"
        elif c == "manual":
            if nunca:
                av = "habilitado, todavía sin su primera carga"
            elif dias > MANUAL_DIAS:
                mot = f"carga manual con {dias} días"
        elif r["error"] or nunca or dias > 1:
            mot = f"falló: {r['error']}" if r["error"] else "nunca trajo datos" if nunca else f"sin datos hace {dias} días"
        r["alerta"], r["motivo"], r["aviso"] = bool(mot), mot, av
    for f, cub in CUBIERTA.items():  # la cubridora al día = la cubierta no alerta
        if f in por and cub in por and por[f]["alerta"] and not por[cub]["alerta"] and (por[cub]["dias_sin_datos"] or 0) <= 1:
            por[f].update(alerta=False, motivo="", aviso=f"cubierto por {cub}")
    return rows


def fuentes_grok(d, hoy):
    """Una fila por grok_*: la 'corrida' es la última carga; días sin datos = hoy - fecha del último dato."""
    por = defaultdict(list)
    for r in d["grok"]:
        if r["fuente"].startswith("grok_"):  # helix_api también escribe en data/grok/, pero su estado ya está en fuentes.csv
            por[r["fuente"]].append(r)
    out = []
    for f in sorted({s["fuente"] for s in d["grok_sitios"]} | set(por)):
        filas = por.get(f, [])
        base = {"fecha": "", "fuente": f, "http": "", "n_items": 0, "n_con_precio": 0, "n_sin_stock": 0, "n_sin_match": 0,
                "n_descartados": 0, "error": "sin cargas todavía", "ultimo_ok": None, "dias_sin_datos": None, "dias_sin_correr": None, "pais": "AR", "nota": NOTAS_FUENTE.get(f, "")}
        if filas:
            ult = max(r["fecha"] for r in filas)
            n = [r for r in filas if r["fecha"] == ult]
            base.update(pais=pais_r(filas[-1]), fecha=max(r["cargado"] for r in filas)[:10], n_items=len(n), n_con_precio=len(n), error="",
                        n_sin_match=sum(not r["producto_id"] for r in n), ultimo_ok=ult,
                        dias_sin_datos=(hoy - date.fromisoformat(ult)).days)
        out.append(base)
    return out


def _stats(xs):
    """xs: [(precio_litro, aviso)] → n, promedio, min, max y mediana por litro; None si no hay datos (nunca 0)."""
    if not xs:
        return dict(n=0, promedio_litro=None, min_litro=None, max_litro=None, mediana_litro=None)
    v = [x[0] for x in xs]
    return dict(n=len(v), promedio_litro=round(sum(v) / len(v), 2), min_litro=round(min(v), 2), max_litro=round(max(v), 2),
                mediana_litro=round(median(v), 2))


def _litros(r):
    return round(num(r["litros"]) * (num(r["unidades"]) or 1), 3)  # del envase completo: caja 12x1 L = 12


def _barato(xs):
    if not xs:
        return None
    pl, r = min(xs, key=lambda x: x[0])
    return {"fuente": r["fuente"], "vendedor": r["vendedor"] or None, "precio": num(r["precio"]),
            "litros": _litros(r), "precio_litro": round(pl, 2), "url": r["url"] or None}


def specs(p):
    """Ficha técnica de un producto del seed para el modo presentación: vacío = null (oem: lista, [] si no hay)."""
    g = lambda k: (p.get(k) or "").strip() or None
    return {**{k: g(k) for k in ("api", "acea", "ilsac", "jaso", "base", "sae", "segmento")},
            "oem": [o.strip() for o in (p.get("oem") or "").split(";") if o.strip()],
            "verificado": g("verificado"), "fuente_specs": g("fuente_specs")}


def productos_de(d, pais):
    """Productos YPF que se muestran en un país: los del seed de ese país (sufijo -br = Brasil) o con alguna observación en él."""
    con_obs = {r["producto_id"] for r in d["obs"] if r["producto_id"]}
    return [p for p in d["productos"] if p["marca"] == "YPF" and (normalizar.pais_producto(p["producto_id"]) == pais or p["producto_id"] in con_obs)]


def cuerdos(xs):
    """xs: [(precio_litro, aviso)] de un producto → los que están dentro de [mediana / SANIDAD, mediana × SANIDAD] (el resto es un envase mal leído)."""
    m = median(pl for pl, _ in xs)
    return [x for x in xs if m / SANIDAD <= x[0] <= m * SANIDAD]


_HASH_GLB = {}  # (ruta, mtime, tamaño) → sha1 corto: no se relee el archivo en cada pedido


def modelo(pid):
    """URL relativa al sitio del GLB del producto con `?v=<hash del contenido>` (la URL cambia cuando se regenera el
    archivo, así el navegador no muestra uno viejo), o None si todavía no se generó (nunca se inventa)."""
    f = MODELOS / f"{pid}.glb"
    if not f.is_file():
        return None
    st = f.stat()
    k = (str(f), st.st_mtime_ns, st.st_size)
    if k not in _HASH_GLB:
        _HASH_GLB[k] = hashlib.sha1(f.read_bytes()).hexdigest()[:10]
    return f"modelos/{pid}.glb?v={_HASH_GLB[k]}"


def vitrina(d, mayoristas=False, pais="AR"):
    """YPF vs competencia por producto: precios por litro del último relevamiento de cada aviso (ver CLAUDE.md, /api/vitrina).
    Cada aviso (fuente+url+ean+titulo+vendedor+envase) cuenta una vez, con su observación más reciente de los últimos
    VENTANA_DIAS días contados desde el último día con datos. Sin mayoristas (salvo flag), sin Grok sin verificar.
    Solo avisos de `pais` y en su moneda: nunca se mezclan países. La sanidad (SANIDAD) es la de siempre: con menos de 3 avisos de un
    producto no protege (un lote de R$ 600 con nombre de 1 L, solo en el seed, entraría): por eso un producto sale al seed con su EAN verificado."""
    d = de_pais(d, pais)
    # misma definición de aviso, ventana y sanidad que /api/producto (`_avisos`, `_validos`): los números de las dos pantallas coinciden
    ult, por = _avisos(d, VENTANA_DIAS, {r["producto_id"] for r in d["obs"]} - {""}, None)
    por_pid = {pid: cuerdos(xs) for pid, rs in por.items() if (xs := _validos(rs, mayoristas))}
    ult = ult or None
    prod = {p["producto_id"]: p for p in d["productos"]}
    foto = {f["producto_id"]: f for f in d.get("imagenes", [])}

    def datos_ypf(xs):
        out = {**_stats(xs), "presentacion_comun_l": None, "promedio_presentacion": None, "mas_barato": _barato(xs), "por_fuente": []}
        pres = Counter(_litros(r) for _, r in xs)
        if pres:
            l = min(pres, key=lambda k: (-pres[k], k))  # la más frecuente; empate: la más chica
            ps = [num(r["precio"]) for _, r in xs if _litros(r) == l]
            out.update(presentacion_comun_l=l, promedio_presentacion=round(sum(ps) / len(ps), 2))
        for f in sorted({r["fuente"] for _, r in xs}):
            s = _stats([x for x in xs if x[1]["fuente"] == f])
            out["por_fuente"].append({"fuente": f, "n": s["n"], "promedio_litro": s["promedio_litro"]})
        return out

    eq = defaultdict(dict)
    for e in d["equivalencias"]:
        eq[e["ypf_id"]].setdefault(e["comp_id"], e)
    productos, i30 = [], indices_30d(d)
    for p in productos_de(d, pais):
        pid, ypf = p["producto_id"], datos_ypf(por_pid.get(p["producto_id"], []))
        eqs, en_prom = [], []
        for cid, e in eq.get(pid, {}).items():
            c, xs = prod.get(cid, {}), por_pid.get(cid, [])
            s = _stats(xs)
            excluido = "no_equivalente" if e["tipo"] == "no_equivalente" else None  # se listan pero no promedian
            if not excluido and s["mediana_litro"] and ypf["mediana_litro"] and                     not 1 / RANGO_EQ <= s["mediana_litro"] / ypf["mediana_litro"] <= RANGO_EQ:
                excluido = "fuera_de_rango"
            entra = excluido is None
            if entra:
                en_prom += xs
            eqs.append({"producto_id": cid, "marca": c.get("marca", ""), "nombre": c.get("nombre", ""), "tipo": e["tipo"],
                        "evidencia": e["evidencia"], "specs": specs(c), "en_promedio": entra, "excluido": excluido, "imagen": (foto.get(cid) or {}).get("url"), "modelo": modelo(cid),
                        "n": s["n"], "promedio_litro": s["promedio_litro"], "min_litro": s["min_litro"], "mas_barato": _barato(xs)})
        eqs.sort(key=lambda x: (not x["en_promedio"], -x["n"], x["producto_id"]))
        comp = _stats(en_prom)
        productos.append({
            "producto_id": pid, "nombre": p["nombre"], "linea": p["linea"], "segmento": p["segmento"], "sae": p["sae"], "base": p["base"],
            "imagen": (foto.get(pid) or {}).get("url"), "modelo": modelo(pid), "imagen_fuente": (foto.get(pid) or {}).get("fuente"), "specs": specs(p),
            "indice_30d": i30.get(pid) or {"indice": None, "mediana_ypf_litro": None, "mediana_comp_litro": None, "n_ypf": 0, "n_comp": 0, "desde": None, "hasta": None},
            "ypf": ypf, "competencia": {**{k: comp[k] for k in ("n", "promedio_litro", "min_litro", "max_litro")}, "equivalentes": eqs},
            "dif_pct": round((comp["promedio_litro"] / ypf["promedio_litro"] - 1) * 100, 1)
            if comp["promedio_litro"] and ypf["promedio_litro"] else None})
    productos.sort(key=lambda x: (x["ypf"]["n"] == 0, -x["ypf"]["n"], x["linea"], x["nombre"]))
    return {"fecha": ult, "pais": pais, "moneda": PAISES[pais][1], "productos": productos}


def aplanar_vitrina(v):
    """/api/vitrina?formato=csv: una fila por producto YPF, sin las listas anidadas."""
    out = []
    for p in v["productos"]:
        y, c, b = p["ypf"], p["competencia"], p["ypf"]["mas_barato"] or {}
        out.append({"fecha": v["fecha"], "pais": v["pais"], "moneda": v["moneda"], **{k: p[k] for k in ("producto_id", "nombre", "linea", "segmento", "sae", "base", "imagen", "imagen_fuente", "dif_pct")},
                    "ypf_n": y["n"], "ypf_promedio_litro": y["promedio_litro"], "ypf_min_litro": y["min_litro"], "ypf_max_litro": y["max_litro"],
                    "ypf_mediana_litro": y["mediana_litro"], "presentacion_comun_l": y["presentacion_comun_l"],
                    "promedio_presentacion": y["promedio_presentacion"], "ypf_mas_barato_fuente": b.get("fuente"),
                    "ypf_mas_barato_vendedor": b.get("vendedor"), "ypf_mas_barato_precio_litro": b.get("precio_litro"),
                    "ypf_mas_barato_url": b.get("url"), "comp_n": c["n"], "comp_promedio_litro": c["promedio_litro"],
                    "comp_min_litro": c["min_litro"], "comp_max_litro": c["max_litro"], "n_equivalentes": len(c["equivalentes"]),
                    **{"indice30_" + k: v for k, v in p["indice_30d"].items()}})
    return out


def sin_match(obs):
    grupos = {}
    for r in obs:
        if r["producto_id"]:
            continue
        k = (r["fuente"], r["titulo"], r["ean"])
        g = grupos.get(k)
        if g is None:
            grupos[k] = g = {"fuente": r["fuente"], "titulo": r["titulo"], "ean": r["ean"], "primera": r["fecha"], "veces": 0}
        g["veces"] += 1
        g["primera"] = min(g["primera"], r["fecha"])
        if r["fecha"] >= g.get("ultima", ""):
            g.update(ultima=r["fecha"], marca=r["marca"], precio=r["precio"], litros=r["litros"],
                     unidades=r["unidades"], url=r["url"])
    return sorted(grupos.values(), key=lambda g: (g["ultima"], g["fuente"], g["titulo"]), reverse=True)


# ---------- Mercado: share oficial (Secretaría de Energía), actividad (datos.gob.ar) y compuestos propios ----------
# ---------- precio de reventa por provincia y región, reventa y cobertura ----------
PROVINCIAS, REGIONES, ONLINE = normalizar.PROVINCIAS, normalizar.REGIONES, normalizar.ONLINE
NOTA_FRESCURA = ("No es tiempo real: la recolección es diaria y SEPA (Precios Claros) llega con ~1 día de atraso. "
                 "Cada número lleva la fecha de su última observación.")
CELDA_F = ["fuente", "canal", "precio_litro", "precio", "n", "fecha", "vendedores", "url", "verificado", "cargado"]
REVENTA_OBS_F = ["fecha", "fuente", "canal", "vendedor", "provincia", "region", "url", "precio", "precio_litro", "litros", "unidades",
                 "verificado", "cargado"]
CAMPOS["provincias"] = ["producto_id", "provincia", "region", "provincias", "nombre"] + CELDA_F + ["pais", "moneda"]
CAMPOS["reventa"] = ["rol", "producto_id", "marca", "nombre", "tipo"] + REVENTA_OBS_F + ["pais", "moneda"]
CAMPOS["cobertura"] = ["producto_id", "nombre", "linea", "segmento", "sae", "equivalencias", "tiene_equivalencia", "fuentes_7d",
                       "provincias_7d", "ultima_fecha", "pais", "moneda"]


def canal(fuente):
    """Canal derivado de la fuente (no hay columna): mayorista, grok (relevamiento cargado por la Task) o publico."""
    return "mayorista" if fuente in MAYORISTAS else "grok" if fuente.startswith("grok_") else "publico"


def tipo_fuente(f):
    """Tipo de fuente para la dimensión de Power BI. Las `oficial_*` (nota fiscal de Brasil) se tratan como SEPA."""
    return "grok" if f.startswith("grok_") else "sepa" if f == "sepa" or f.startswith("oficial_") else "ml" if f.startswith("ml") else "mayorista" if f in MAYORISTAS else "tienda"


VENTANA_INDICE = 30  # índice según la competencia: siempre 30 días, aparte de la ventana de la vitrina y de los filtros de fecha


def _equivs(d):
    """{ypf_id: {comp_id: equivalencia}}: una por competidor (la primera), como la vitrina y /api/producto."""
    eq = defaultdict(dict)
    for e in d["equivalencias"]:
        eq[e["ypf_id"]].setdefault(e["comp_id"], e)
    return eq


def _indice_par(por, eqs, pid, mayoristas=False):
    """Índice según la competencia de UN producto YPF sobre sus avisos `por` (de `_avisos`): mediana $/L YPF / mediana $/L de la competencia × 100 (competencia = 100;
    menos de 100 = YPF más barato). Misma regla que `producto()`: sanidad `cuerdos`, sin no_equivalente, equivalente fuera de RANGO_EQ no cuenta. Un lado sin datos = None."""
    def cuerdas(p):
        c = _validos_indice(por.get(p, []), mayoristas)
        return [pl for pl, _ in cuerdos(c)] if c else []
    y = cuerdas(pid)
    my = round(median(y), 2) if y else None
    pool = []
    for cid, e in eqs.items():
        xs = cuerdas(cid)
        if xs and e["tipo"] != "no_equivalente" and not (my and not 1 / RANGO_EQ <= round(median(xs), 2) / my <= RANGO_EQ):
            pool += [round(x, 2) for x in xs]
    mc = round(median(pool), 2) if pool else None
    return {"indice": round(my / mc * 100, 1) if my and mc else None, "mediana_ypf_litro": my, "mediana_comp_litro": mc, "n_ypf": len(y), "n_comp": len(pool)}


def indices_30d(d):
    """{producto_id YPF: indice_30d} (nunca con mayoristas: cotizan por caja o tambor, igual que /api/bi/indice_competencia) con la ventana de 30 días que termina en el último día con datos de `d` (ya de un solo país)."""
    eq, ypf = _equivs(d), [p["producto_id"] for p in d["productos"] if p["marca"] == "YPF"]
    hasta, por = _avisos(d, VENTANA_INDICE, set(ypf) | {c for y in ypf for c in eq.get(y, {})}, None)
    desde, _ = desde_hasta(d, VENTANA_INDICE)
    return {pid: {**_indice_par(por, eq.get(pid, {}), pid), "desde": desde or None, "hasta": hasta or None} for pid in ypf}


def indice_pares(d, pais="AR"):
    """/api/indice/pares: el índice principal (competencia = 100, ventana de 30 días que termina en el último día con datos), una fila por producto YPF del país,
    con su motivo cuando no hay índice. Los números son los de `_indice_par` (los de /api/vitrina `indice_30d` y /api/bi/indice_competencia): acá solo se suman los datos
    del producto y el porqué de un vacío (nunca 0 ni un guion mudo). `d` ya es de un solo país."""
    eq = _equivs(d)
    ypf = productos_de(d, pais)
    hasta, por = _avisos(d, VENTANA_INDICE, {p["producto_id"] for p in ypf} | {c for p in ypf for c in eq.get(p["producto_id"], {})}, None)
    desde, _ = desde_hasta(d, VENTANA_INDICE)
    todos = lambda q: _validos(por.get(q, []), False)
    solo_chicos = lambda ids: any(todos(q) for q in ids) and all(_chico(r) for q in ids for _, r in todos(q))
    out = []
    for p in ypf:
        pid = p["producto_id"]
        x = _indice_par(por, eq.get(pid, {}), pid)
        motivo = None
        if x["indice"] is None:
            if not x["n_ypf"]:
                motivo = ("YPF: " + MOTIVO_CHICOS) if solo_chicos([pid]) else "sin avisos de YPF en la ventana"
            elif not eq.get(pid):
                motivo = "sin equivalencias cargadas"
            elif solo_chicos(list(eq[pid])):
                motivo = "competencia: " + MOTIVO_CHICOS
            elif any(todos(q) for q in eq[pid]):
                motivo = "los avisos de la competencia no son comparables (no equivalente o fuera de rango)"
            else:
                motivo = "sin avisos de la competencia en la ventana"
        out.append({"producto_id": pid, "nombre": p["nombre"], "linea": p["linea"], "segmento": p["segmento"], "sae": p["sae"], "base": p["base"] or None, **x, "motivo": motivo})
    return {"pais": pais, "moneda": PAISES[pais][1], "desde": desde or None, "hasta": hasta or None, "dias": VENTANA_INDICE, "productos": out,
            "nota": "Índice por pares de equivalencias, competencia = 100: mediana $/L de YPF / mediana $/L de la competencia equivalente × 100 sobre los avisos de los últimos 30 días "
                    f"(más de 100 = YPF más caro). Sin mayoristas, sin Grok sin verificar y sin envases de menos de {LITROS_MIN_INDICE:g} L por unidad (sachets). Vacío = sin dato, con su motivo."}


def bi_indice_competencia(d, desde=""):
    """/api/bi/indice_competencia: el índice de 30 días para cada fecha con datos (ventana móvil que termina ahí), una fila por producto YPF con datos en la ventana.
    Barrido incremental: se mantiene el último aviso vivo de cada clave y se descartan los que salen de la ventana. Cacheado por estado de datos (`d` se rearma al recargar)."""
    cache = d.setdefault("_cache_bi_indice", {})
    # ponytail: barrido completo = fechas × avisos vivos (~0,1-0,2 s por fecha en la PC); `calcular` lo precalienta al cargar, fuera del pedido. Con años de historia:
    # persistir los cortes cerrados y recalcular solo los últimos 30 días.
    if "filas" not in cache:
        filas = []
        eq = _equivs(d)
        ypf = [p["producto_id"] for p in d["productos"] if p["marca"] == "YPF"]
        pids = set(ypf) | {c for y in ypf for c in eq.get(y, {})}
        for pais in PAISES:
            obs = [r for r in d["obs"] if pais_r(r) == pais and moneda_r(r) == PAISES[pais][1]]  # una moneda distinta (p. ej. USD) no se mezcla en la mediana
            por_dia, vivos = defaultdict(list), {}
            for r in obs:
                if r["producto_id"] in pids:
                    por_dia[r["fecha"]].append(r)
            for fecha in sorted({r["fecha"] for r in obs}):
                for r in por_dia.get(fecha, []):
                    k = _clave_aviso(r, None)
                    if k not in vivos or r["fecha"] >= vivos[k]["fecha"]:
                        vivos[k] = {**r, "pl": precio_litro(r)}
                ini = (date.fromisoformat(fecha) - timedelta(days=VENTANA_INDICE - 1)).isoformat()
                vivos = {k: r for k, r in vivos.items() if r["fecha"] >= ini}
                por = defaultdict(list)
                for r in vivos.values():
                    por[r["producto_id"]].append(r)
                for pid in ypf:
                    x = _indice_par(por, eq.get(pid, {}), pid)
                    if x["n_ypf"] or x["n_comp"]:
                        filas.append({"fecha": fecha, "producto_id": pid, "pais": pais, "moneda": PAISES[pais][1], **x})
        cache["filas"] = filas
    return [f for f in cache["filas"] if f["fecha"] >= desde]


def bi_indice(calc, desde="", mayoristas=False, pais=""):
    """/api/bi/indice: lo mismo que /api/indice (YPF = 100) de todos los países, en filas largas; `mediana_ypf_litro` es la del grupo (fecha × segmento × SAE) en esa moneda."""
    out = []
    for p, cp in calc["_paises"].items():
        if pais and p != pais:
            continue
        filas = cp["indice_con_mayoristas" if mayoristas else "indice"]
        ypf = {(r["fecha"], r["segmento"], r["sae"], r["moneda"]): r["mediana_litro"] for r in filas if r["marca"] == "YPF"}
        out += [{**r, "mediana_ypf_litro": ypf.get((r["fecha"], r["segmento"], r["sae"], r["moneda"]), "")} for r in filas if r["fecha"] >= desde]
    return out


def bi_precios(d, desde=""):
    """/api/bi/precios: una fila por observación con producto_id (incluye Grok con su `verificado`, como /api/reventa: se marca, no se oculta;
    el filtro lo hace el modelo). `capturado` vacío = fila anterior a esa columna: no se inventa una hora."""
    out = []
    for r in d["obs"]:
        if not r["producto_id"] or r["fecha"] < desde:
            continue
        pl, m = precio_litro(r), moneda_r(r)
        usd = con_usd({"fecha": r["fecha"], "moneda": m, "precio_litro": pl}, m, d["fx_tabla"])["precio_litro_usd"]
        out.append({**r, "capturado": r.get("capturado") or "", "canal": canal(r["fuente"]), "pais": pais_r(r), "moneda": m,
                    "precio_litro": "" if pl is None else round(pl, 4), "precio_usd_litro": "" if usd is None else usd, "verificado": r.get("verificado") or ""})
    return out


def bi_fuentes(d):
    ult = {}
    for r in d["obs"]:
        ult[r["fuente"]] = max(ult.get(r["fuente"], ""), r["fecha"])
    return [{"fuente": f, "canal": canal(f), "pais": pais_de_fuente(f), "tipo": tipo_fuente(f), "ultima_fecha": u} for f, u in sorted(ult.items())]


def bi_provincias():
    """Código ISO, nombre, región y `online` (1 solo en la fila `online`: e-commerce nacional, no es una provincia). Otros países: solo código y nombre."""
    filas = [{"codigo": c, "nombre": n, "region": normalizar.REGIONES.get(c, ""), "pais": p, "online": 0}
             for p, sub in normalizar.SUBDIVISIONES.items() for c, n in sub.items()]
    return filas + [{"codigo": normalizar.ONLINE, "nombre": "Online (e-commerce nacional)", "region": "", "pais": "", "online": 1}]


def bi_tabla(d, nombre, q):
    """→ filas de una tabla del modelo estrella (None si no existe)."""
    if nombre == "precios":
        return bi_precios(d, q.get("desde", ""))
    if nombre == "productos":
        return [{**p, "es_ypf": int(p["marca"] == "YPF")} for p in d["productos"]]
    if nombre == "equivalencias":
        return d["equivalencias"]
    if nombre == "fx":
        return bi_fx(d)
    if nombre == "diccionario":
        return bi_diccionario()
    return {"fuentes": lambda: bi_fuentes(d), "provincias": bi_provincias}.get(nombre, lambda: None)()


# ---------- paquete para SharePoint / Power BI / Copilot ----------
# Una fila por columna de cada tabla del paquete: "columna|tipo|unidad|descripción|ejemplo". La descripción la lee Copilot como descripción de columna
# del modelo semántico: dice qué es, en qué unidad y cuándo viene vacío. El `demo()` verifica que cubra exactamente CAMPOS["bi_*"].
DICCIONARIO = {
    "precios": """
fecha|fecha||Día de la observación del precio (AAAA-MM-DD, hora argentina).|2026-11-26
capturado|fecha_hora|UTC|Hora en que se capturó la observación (ISO 8601, UTC). Vacía en las filas anteriores a esa columna: nunca se inventa una hora.|2026-11-26T14:05:00Z
producto_id|texto||Identificador del producto del catálogo (marca-línea-nombre-SAE). Se relaciona con productos[producto_id].|ypf-elaion-ts1040-10w40
fuente|texto||Sitio o relevamiento de donde sale el precio (sepa, ml, vtex_carrefour, tn_spch, grok_…). Se relaciona con fuentes[fuente].|vtex_carrefour
canal|texto||Canal de la fuente: publico (tienda o supermercado), mayorista (precio por caja o tambor, fuera del índice por defecto) o grok (relevamiento cargado a mano).|publico
vendedor|texto||Comercio o vendedor del aviso; vacío si la fuente no lo informa.|Carrefour
sucursal|texto||Sucursal o resumen de sucursales (SEPA: n=cantidad;min=;max= dentro de la provincia); vacío si no aplica.|n=12;min=40900;max=45999
provincia|texto||Código ISO 3166-2 de la provincia donde se vende (AR-X Córdoba), online (e-commerce de alcance nacional, no es una provincia) o vacío (sin dato). Se relaciona con provincias[codigo].|AR-X
pais|texto||País del precio, ISO 3166-1 alfa-2 (AR, BR). Nunca se mezclan países al promediar.|AR
moneda|texto||Moneda en que se publicó el precio, ISO 4217 (ARS, BRL, USD). Nunca se mezclan monedas al promediar.|ARS
precio|decimal|moneda de la fila|Precio del aviso en su moneda, tal como lo publica la fuente (por envase, o por caja o tambor en los mayoristas).|156900
litros|decimal|litros|Litros por unidad de venta (un bidón de 4 L = 4); vacío si no se pudo leer el envase.|4
unidades|decimal|unidades|Unidades de la caja o pack (1 si es un envase suelto).|1
precio_litro|decimal|moneda de la fila por litro|Precio por litro = precio / (litros × unidades). Vacío si falta el envase. Una mediana sobre esta columna repite el sesgo de SEPA (una fila por provincia): para el índice usar la tabla indice.|39225
precio_usd_litro|decimal|USD por litro|Precio por litro convertido a dólares con la cotización oficial de ese mismo día (tabla fx). Vacío si ese día no hay cotización; no se arrastra otra.|0.027
url|texto||Link al aviso; vacío en SEPA.|https://www.carrefour.com.ar/aceite-elaion/p
match|texto||Cómo se asignó el producto: ean (código de barras exacto) o texto (título, con un único candidato).|ean
verificado|texto||Solo en las filas de Grok: 1 = el precio apareció en la página, 0 = no se pudo verificar; vacío en el resto; respaldo = Grok de Mercado Libre sin verificar que cuenta en los días en que la API de ML no tiene datos. El índice excluye los 0.|1
""",
    "indice": """
fecha|fecha||Día del índice. Cada día usa los avisos de los 3 días que terminan en esa fecha.|2026-11-26
pais|texto||País del índice (AR, BR). YPF = 100 se calcula solo dentro de un país y una moneda.|AR
moneda|texto||Moneda de la celda, ISO 4217.|ARS
segmento|texto||Segmento del producto: pcmo (autos), hddo (pesados), moto4t, moto2t, transmision, grasa, industrial, marino, gas, otro.|pcmo
sae|texto||Viscosidad SAE (5W-30, 15W-40, SAE 40); vacío si el segmento no tiene.|5W-30
marca|texto||Marca del aviso. YPF es la referencia (100).|Shell
mediana_litro|decimal|moneda por litro|Mediana del precio por litro de los avisos de esa marca, segmento y SAE en la ventana de 3 días (cada aviso cuenta una vez, con precios cuerdos).|41250
mediana_ypf_litro|decimal|moneda por litro|Mediana del precio por litro de YPF en el mismo segmento, SAE y fecha; vacía si YPF no tiene avisos en la ventana.|38500
indice|decimal|puntos (YPF = 100)|Mediana de la marca / mediana de YPF × 100. 110 = la marca es 10 % más cara que YPF; 90 = 10 % más barata. Vacío si no hay YPF en el grupo (nunca 0).|107.1
n|entero|avisos|Cantidad de avisos (uno por publicación o comercio) que entran en la mediana de la marca. Con n chico (1 o 2) la mediana es poco confiable.|18
""",
    "indice_competencia": """
fecha|fecha||Día del índice; cada fecha usa una ventana móvil de 30 días que termina en ella.|2026-11-26
producto_id|texto||Producto YPF evaluado. Se relaciona con productos[producto_id].|ypf-elaion-ts1040-10w40
pais|texto||País (AR, BR).|AR
moneda|texto||Moneda de las medianas, ISO 4217.|ARS
indice|decimal|puntos (competencia = 100)|Mediana YPF / mediana de la competencia equivalente × 100. Menos de 100 = YPF más barato que la competencia; más de 100 = más caro. Vacío si falta YPF o competencia. Atención: la base es la competencia, al revés que en la tabla indice. Es el índice principal («Por producto» en la pestaña Índice); no incluye envases de menos de 0,5 L por unidad.|92.4
mediana_ypf_litro|decimal|moneda por litro|Mediana del precio por litro del producto YPF en la ventana.|36368
mediana_comp_litro|decimal|moneda por litro|Mediana del precio por litro de todos los avisos de los equivalentes (sin los no equivalentes) en la ventana.|39350
n_ypf|entero|avisos|Cantidad de avisos del producto YPF en la ventana.|14
n_comp|entero|avisos|Cantidad de avisos de los equivalentes en la ventana.|40
""",
    "productos": """
producto_id|texto||Identificador único del producto (marca-línea-nombre-SAE; el sufijo -br es un producto de Brasil). Clave de la tabla.|ypf-elaion-ts1040-10w40
marca|texto||Marca canónica (YPF, Shell, Castrol, Mobil, TotalEnergies, Gulf, …).|YPF
linea|texto||Línea comercial del producto (Elaion, Helix, Magnatec, …).|Elaion
nombre|texto||Nombre del producto dentro de la línea.|TS 1040
segmento|texto||Segmento: pcmo (autos), hddo (pesados), moto4t, moto2t, transmision, grasa, industrial, marino, gas, otro.|pcmo
sae|texto||Viscosidad SAE; vacío si no aplica.|10W-40
base|texto||Base del aceite: mineral, semisintetico o sintetico; vacío si no se sabe.|semisintetico
api|texto||Especificación API (calidad del aceite); vacío si no se verificó.|SN
acea|texto||Especificación ACEA; vacío si no se verificó.|A3/B4
ilsac|texto||Especificación ILSAC; vacío si no se verificó.|GF-6A
jaso|texto||Especificación JASO (motos); vacío si no aplica.|MA2
oem|texto||Homologaciones de fabricantes de autos separadas por punto y coma.|VW 502.00;MB 229.5
fuente_specs|texto||De dónde salen las especificaciones (ficha técnica o inferencia).|ficha YPF
verificado|texto||confirmado (sale de una ficha) o inferido (deducido).|confirmado
es_ypf|entero|0 o 1|1 si el producto es de marca YPF, 0 si es de la competencia.|1
""",
    "equivalencias": """
ypf_id|texto||Producto YPF. Se relaciona con productos[producto_id].|ypf-elaion-ts1040-10w40
comp_id|texto||Producto de la competencia equivalente. Se relaciona con productos[producto_id].|shell-helix-hx7-10w40
tipo|texto||Qué tan comparables son: match_total, match_total_probable, match_parcial, sustituto_comercial o no_equivalente (este último no se promedia).|match_total_probable
criterio|texto||Criterio con el que se declaró la equivalencia (SAE, base, especificaciones).|mismo SAE, base y API
evidencia|texto||confirmada (sale de una ficha) o inferida.|inferida
fuente|texto||Fuente en que se apoya la equivalencia.|fichas técnicas
""",
    "fuentes": """
fuente|texto||Identificador de la fuente. Clave de la tabla.|vtex_carrefour
canal|texto||publico, mayorista o grok.|publico
pais|texto||País de la fuente (AR, BR).|AR
tipo|texto||tienda, mayorista, grok, sepa (Precios Claros y notas fiscales de Brasil) o ml (Mercado Libre).|tienda
ultima_fecha|fecha||Último día con observaciones de la fuente: sirve para ver qué fuentes están atrasadas.|2026-11-26
""",
    "provincias": """
codigo|texto||Código ISO 3166-2 de la provincia o estado (AR-X) o online (e-commerce nacional). Clave de la tabla.|AR-X
nombre|texto||Nombre de la provincia.|Córdoba
region|texto||Región según INDEC (NOA, NEA, Cuyo, Pampeana, Patagonia); vacía fuera de Argentina y en online.|Pampeana
pais|texto||País de la provincia (AR, BR); vacío en la fila online.|AR
online|entero|0 o 1|1 solo en la fila online (no es una provincia).|0
""",
    "fx": """
fecha|fecha||Día de la cotización.|2026-11-26
moneda|texto||Moneda cotizada contra el dólar: ARS o BRL.|ARS
por_usd|decimal|unidades de la moneda por 1 USD|Cuántos pesos (o reales) vale un dólar ese día.|1450.5
fuente|texto||Fuente de la cotización (bcra_cambiarias = BCRA Estadísticas Cambiarias; bcb_ptax = PTAX venta del BCB de Brasil; BCRA (datos.gob.ar) = tipo de cambio de valuación, solo fechas anteriores).|bcra_cambiarias
""",
}
CAMPOS["bi_fx"] = ["fecha", "moneda", "por_usd", "fuente"]
CAMPOS["bi_diccionario"] = ["tabla", "columna", "tipo", "unidad", "descripcion", "ejemplo"]
TABLAS_BI = ["precios", "indice", "indice_competencia", "productos", "equivalencias", "fuentes", "provincias", "fx"]  # el orden del paquete
PUBLICA_URL = os.environ.get("LUB_URL_PUBLICA", "https://lubricantes.fln-data-analysis.com")  # solo para el LEEME del paquete


def bi_diccionario():
    """/api/bi/diccionario: tabla,columna,tipo,unidad,descripcion,ejemplo, una fila por columna de cada tabla del paquete."""
    out = []
    for t in TABLAS_BI:
        for linea in DICCIONARIO[t].strip().splitlines():
            col, tipo, unidad, desc, ej = linea.split("|")
            out.append({"tabla": t, "columna": col, "tipo": tipo, "unidad": unidad, "descripcion": desc, "ejemplo": ej})
    return out


def bi_fx(d):
    """/api/bi/fx: cotizaciones por fecha y moneda (BCRA/BCB; las ARS anteriores a esa fuente salen de datos.gob.ar, con su fuente)."""
    return [{"fecha": f, "moneda": m, "por_usd": v, "fuente": fu} for (m, f), (v, fu) in sorted(d.get("fx_tabla", {}).items(), key=lambda kv: (kv[0][1], kv[0][0]))]


def bi_paquete(d, calc):
    """/api/bi/paquete.zip: un CSV por tabla del modelo (UTF-8 con BOM) + diccionario.csv + LEEME.txt, con nombres fijos (sin fecha) para que el reemplazo
    manual en SharePoint no rompa las consultas de Power BI. Sin secretos ni rutas locales."""
    import zipfile
    filas = {"precios": bi_precios(d), "indice": bi_indice(calc), "indice_competencia": bi_indice_competencia(d), "fx": bi_fx(d),
             **{t: bi_tabla(d, t, {}) for t in ("productos", "equivalencias", "fuentes", "provincias")}}
    s = salud()
    leeme = ("LUBRICANTES - paquete de datos para Power BI\n\n"
             f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
             f"Ultimo dato (ultima observacion de precio): {s['ultimo_dato']}\n"
             f"Commit de datos servido: {s['commit'] or 'sin dato'}\n"
             f"Origen: {PUBLICA_URL}/api/bi/paquete.zip (lectura abierta, sin clave)\n\n"
             "Contenido: un CSV por tabla (UTF-8 con BOM, coma, punto decimal): " + ", ".join(t + ".csv" for t in TABLAS_BI) + ", diccionario.csv.\n"
             "Los nombres son fijos: reemplace los archivos de la carpeta de SharePoint sin cambiarles el nombre.\n"
             "Los datos son diarios; no es tiempo real. indice_competencia.csv (competencia = 100, por producto YPF, 30 dias) es el indice principal e indice.csv (YPF = 100, por segmento, SAE y marca) la vista secundaria. Ninguno incluye envases de menos de 0,5 L por unidad (sachets): siguen en precios.csv.\n"
             "Guia de conexion y medidas: docs/powerbi.md del repositorio.\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for t in TABLAS_BI:
            z.writestr(t + ".csv", chr(0xFEFF).encode() + a_csv("bi_" + t, filas[t]))
        z.writestr("diccionario.csv", chr(0xFEFF).encode() + a_csv("bi_diccionario", bi_diccionario()))
        z.writestr("LEEME.txt", chr(0xFEFF).encode() + leeme.encode())
    return buf.getvalue()


def desde_hasta(d, dias, desde=None, hasta=None):
    """Ventana de `dias` días que termina en el último día con datos (no en hoy: si la Action se atrasa, no queda vacía).
    `desde`/`hasta` (AAAA-MM-DD, ya validados) la fijan: ambos = ese rango; solo `desde` = hasta el último día con datos; solo `hasta` = `dias` días hacia atrás."""
    ult = max((r["fecha"] for r in d["obs"]), default="")
    if not ult:
        return "", ""
    hasta = hasta or ult
    if desde:
        return desde, hasta
    return (date.fromisoformat(hasta) - timedelta(days=dias - 1)).isoformat(), hasta


def _clave_aviso(r, prov_en_url):
    prov = "" if prov_en_url is None or r["url"] and not prov_en_url and canal(r["fuente"]) != "grok" else r.get("provincia", "")
    return (r["producto_id"], r["fuente"], r["url"], r["ean"], r["titulo"], r["vendedor"], r["litros"], r["unidades"], prov)


def _avisos(d, dias, pids, prov_en_url=True, desde=None, hasta=None):
    """→ (hasta, {producto_id: avisos}): cada aviso una vez, con su observación más reciente de la ventana.
    prov_en_url=True (/api/provincias, /api/reventa): la provincia entra en la clave (SEPA trae un aviso por comercio × bandera × provincia × EAN).
    None (vitrina y /api/producto): la provincia nunca entra, un aviso es el mismo en todo el país (ML pasó de vacía a 'online' y contaba doble).
    False: solo cuenta con url y que no es Grok; sin url (SEPA) y Grok la provincia distingue."""
    desde, hasta = desde_hasta(d, dias, desde, hasta)
    ult = {}
    for r in d["obs"]:
        if r["producto_id"] in pids and desde <= r["fecha"] <= hasta:
            k = _clave_aviso(r, prov_en_url)
            if k not in ult or r["fecha"] >= ult[k]["fecha"]:
                ult[k] = r
    por = defaultdict(list)
    for r in ult.values():
        por[r["producto_id"]].append({**r, "pl": precio_litro(r)})
    return hasta, por


def _filtrar(rs, fuente, mayoristas):
    """Con la fuente pedida explícitamente se devuelve esa aunque sea mayorista; si no, los mayoristas solo con ?mayoristas=1."""
    return [r for r in rs if r["pl"] is not None and (r["fuente"] == fuente if fuente else mayoristas or r["fuente"] not in MAYORISTAS)]


def _validos(rs, mayoristas):
    """Avisos de UN producto que cuentan para el $/L (con litros, sin mayoristas salvo flag, sin Grok sin verificar) → [(precio_litro, aviso)]; la sanidad la aplica `cuerdos`."""
    return [(r["pl"], r) for r in _filtrar(rs, "", mayoristas) if r.get("verificado") != "0"]


def _chico(r):
    """Envase de menos de LITROS_MIN_INDICE litros por unidad (el $/L de un sachet no es comparable con el de un bidón)."""
    return num(r["litros"]) < LITROS_MIN_INDICE


def _validos_indice(rs, mayoristas):
    """`_validos` sin los envases chicos: lo que cuenta para los índices (por segmento/SAE/marca, celdas y pares)."""
    return [x for x in _validos(rs, mayoristas) if not _chico(x[1])]


def _celda(rs, **clave):
    """Mediana de $/L y de precio de avisos de UNA sola fuente. Grok lleva url, verificado y cargado de su observación más nueva."""
    ult = max(rs, key=lambda r: (r["fecha"], r.get("cargado") or ""))
    f = rs[0]["fuente"]
    grok = canal(f) == "grok"
    return {**clave, "fuente": f, "canal": canal(f), "precio_litro": round(median(r["pl"] for r in rs), 2),
            "precio": round(median(num(r["precio"]) for r in rs), 2), "n": len(rs), "fecha": ult["fecha"],
            "vendedores": [v for v, _ in Counter(r["vendedor"] for r in rs if r["vendedor"]).most_common(5)],
            "url": ult["url"] if grok else "", "verificado": ("1" if all(r.get("verificado") == "1" for r in rs) else "respaldo" if all(r.get("verificado") == "respaldo" for r in rs) else "0") if grok else "",
            "cargado": (ult.get("cargado") or "") if grok else ""}


def rango_pedido(d, dias, q):
    """?desde/?hasta (AAAA-MM-DD, opcionales, mandan sobre `dias`) de /api/producto, /api/provincias y /api/reventa → (desde, hasta, error del 400 o None).
    Los extremos que falten se resuelven como en `desde_hasta`; el rango resuelto no puede invertirse ni pasar de 366 días."""
    desde, hasta = q.get("desde") or None, q.get("hasta") or None
    for nombre_, f in (("desde", desde), ("hasta", hasta)):
        try:
            if f and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", f):
                raise ValueError
            f and date.fromisoformat(f)
        except ValueError:
            return None, None, f"{nombre_} tiene que ser una fecha AAAA-MM-DD válida"
    if desde or hasta:
        rd, rh = desde_hasta(d, dias, desde, hasta)
        if rd and rh:
            if rd > rh:
                return None, None, f"desde ({rd}) no puede ser posterior a hasta ({rh})"
            if (date.fromisoformat(rh) - date.fromisoformat(rd)).days + 1 > 366:
                return None, None, "el rango no puede pasar de 366 días"
    return desde, hasta, None


def _rango(dias, desde, hasta):
    """`dias` (largo real del rango, inclusive), `desde` y `hasta` de la respuesta: con rango explícito `dias` es su largo, igual que /api/producto."""
    if desde and hasta:
        dias = (date.fromisoformat(hasta) - date.fromisoformat(desde)).days + 1
    return {"dias": dias, "desde": desde, "hasta": hasta}


def provincias(d, pid, dias=30, fuente="", mayoristas=False, pais="AR", desde=None, hasta=None):
    """Celdas por (provincia, fuente) y por (región, fuente) de un producto. Una celda nunca mezcla fuentes; `online` no es provincia
    (va en `celdas` con region vacía y no entra a `regiones`); los avisos sin provincia solo se cuentan en `n_sin_provincia`."""
    d, validas = de_pais(d, pais), subdivisiones(pais)
    desde, hasta = desde_hasta(d, dias, desde, hasta)
    hasta, por = _avisos(d, dias, {pid}, True, desde, hasta)
    rs = _filtrar(por.get(pid, []), fuente, mayoristas)
    por_prov, por_reg = defaultdict(list), defaultdict(list)
    for r in rs:
        prov = r.get("provincia", "")
        if prov in validas or prov == ONLINE:
            por_prov[(prov, r["fuente"])].append(r)
        if prov in REGIONES and pais == "AR":  # las regiones INDEC son solo argentinas: Brasil no tiene regiones acá
            por_reg[(REGIONES[prov], r["fuente"])].append(r)
    return {"producto_id": pid, "pais": pais, "moneda": PAISES[pais][1], **_rango(dias, desde, hasta), "nota": NOTA_FRESCURA,
            "celdas": [_celda(g, provincia=p, region=REGIONES.get(p, "")) for (p, _), g in sorted(por_prov.items())],
            "regiones": [_celda(g, region=rg, provincias=sorted({r["provincia"] for r in g})) for (rg, _), g in sorted(por_reg.items())],
            "n_sin_provincia": sum(1 for r in rs if r.get("provincia", "") not in validas and r.get("provincia", "") != ONLINE)}


NOTA_PUESTO = ("Precio puesto = precio del aviso + envío cotizado a la capital de cada provincia (CP de la capital), el mismo día. Fuentes: Mercado Libre (con la cuenta de la app; logueado o con Mercado Puntos puede ser más barato) y Norauto (simulación de carrito de la tienda, sin usuario); "
               "el interior puede costar distinto. «Retiro» es retiro en sucursal, no entrega en la provincia. No es tiempo real: cada aviso se cotiza en rotación semanal, por eso la ventana es de al menos 7 días. "
               "Sin cotización no hay precio (nunca se arrastra ni se toma el de la vecina). Correo Argentino: tarifa de MiCorreo de capital a capital con peso y medidas aproximadas del envase; el origen es la provincia del aviso (SEPA = sucursal física) o la declarada por la tienda. Estimado: el comercio puede no enviar.")

CORREO_VENCE_DIAS = 14  # una tarifa más vieja que esto (contra el último día con datos) no se usa: no se arrastra
CORREO_METODOS = {"domicilio": "domicilio", "retiro": "sucursal"}  # método de puesto → `metodo` de data/correo (la API: D / S)


def _idx_correo(d):
    """{(cp_origen, cp_destino, litros, metodo_correo): [(fecha, precio, producto, plazo_min, plazo_max)]} de las tarifas ok; se arma una vez por carga de datos."""
    if "_cache_correo" not in d:
        idx = defaultdict(list)
        for r in d.get("correo", []):
            if r["estado"] == "ok" and num(r["precio"]) is not None:
                idx[(r["cp_origen"], r["cp_destino"], num(r["litros"]), r["metodo"])].append(
                    (r["fecha"], num(r["precio"]), r["producto"], num(r["plazo_min"]), num(r["plazo_max"])))
        d["_cache_correo"] = idx
    return d["_cache_correo"]


def _plazo_correo(mn, mx):
    if mn is None and mx is None:
        return None
    mn = mx if mn is None else mn
    mx = mn if mx is None else mx
    return f"{int(mn)} días" if mn == mx else f"{int(mn)} a {int(mx)} días"


def puesto_correo(d, pid, dias, metodo):
    """Celdas `correo_ar` de /api/puesto: cada aviso con origen conocido (provincia ISO de obs; o, si es `online`, la que declara seed/origen_fuentes.csv)
    y un envase de seed/envases_correo.csv sale de la capital de SU provincia; a cada destino se le suma la tarifa más reciente (≤ 14 días) del par
    capital → capital. Por destino queda la opción más barata por $/L puesto. Online sin origen o envase fuera de la tabla no participan (nunca se inventan).
    → (celdas, hasta, {avisos, sin_origen, sin_envase})."""
    idx = _idx_correo(d)
    cp = {c["provincia"]: c["cp"] for c in d.get("cp", [])}
    info = {"avisos": 0, "sin_origen": 0, "sin_envase": 0}
    if not idx or metodo == "agencia" or not cp:
        return [], "", info
    envases = {num(e["litros"]): e for e in d.get("envases_correo", [])}
    declarado = {o["fuente"]: o["provincia"] for o in d.get("origen_fuentes", [])}
    hasta, por = _avisos(d, dias, {pid}, True)
    if not hasta:
        return [], "", info
    vence = (date.fromisoformat(hasta) - timedelta(days=CORREO_VENCE_DIAS)).isoformat()
    xs = _validos(por.get(pid, []), False)
    xs = cuerdos(xs) if xs else []
    por_dest = defaultdict(lambda: {"opts": [], "sin": 0})
    for _, r in xs:
        if r.get("pais", "AR") not in ("", "AR"):
            continue
        prov = r.get("provincia", "")
        decl = False
        if prov not in cp:
            if prov == ONLINE and r["fuente"] in declarado and declarado[r["fuente"]] in cp:
                prov, decl = declarado[r["fuente"]], True
            else:
                info["sin_origen"] += 1
                continue
        lit = round((num(r["litros"]) or 0) * (num(r.get("unidades")) or 1), 3)
        if lit not in envases:
            info["sin_envase"] += 1
            continue
        info["avisos"] += 1
        precio = num(r["precio"])
        for dest, cpd in cp.items():
            mejor = None
            for mp, mc in CORREO_METODOS.items():
                if metodo and metodo != mp:
                    continue
                tf = [t for t in idx.get((cp[prov], cpd, lit, mc), []) if t[0] >= vence]
                if not tf:
                    continue
                f0 = max(t[0] for t in tf)
                t = min((t for t in tf if t[0] == f0), key=lambda t: t[1])
                pl = (precio + t[1]) / lit
                if mejor is None or pl < mejor["pl"]:
                    mejor = {"pl": pl, "envio": t[1], "metodo": mp, "deposito": t[2] if t[2].startswith("Correo Argentino") else f"Correo Argentino {t[2]}".strip(),  # la API ya nombra «Correo Argentino Clasico»
                             "plazo": _plazo_correo(t[3], t[4]),
                             "plazo_h": t[4] * 24 if t[4] is not None else None, "tarifa_fecha": f0, "vendedor": r["vendedor"] or None, "url": r["url"], "fecha": r["fecha"],
                             "precio": precio, "origen_provincia": prov, "origen_fuente": r["fuente"], "origen_declarado": decl}
            if mejor:
                por_dest[dest]["opts"].append(mejor)
            else:
                por_dest[dest]["sin"] += 1
    out = []
    for dest, c in sorted(por_dest.items()):
        o = sorted(c["opts"], key=lambda a: a["pl"])
        m = o[0] if o else None
        out.append({"provincia": dest, "cp": cp[dest], "fuente": "correo_ar",
                    "minimo": m and {"precio_puesto": round(m["precio"] + m["envio"], 2),
                                     **{k: m[k] for k in ("precio", "envio", "vendedor", "url", "fecha", "metodo", "deposito", "plazo", "tarifa_fecha", "origen_provincia", "origen_fuente", "origen_declarado")}},
                    "minimo_litro_puesto": m and round(m["pl"], 2), "mediana_litro_puesto": round(median(a["pl"] for a in o), 2) if o else None,
                    "n": len(o), "n_no_envia": 0, "n_sin_cotizacion": c["sin"], "fecha": max((a["fecha"] for a in o), default=None),
                    "avisos": [{"vendedor": a["vendedor"], "url": a["url"], "fecha": a["fecha"], "precio": a["precio"], "envio": a["envio"], "metodo": a["metodo"], "deposito": a["deposito"],
                                "plazo": a["plazo"], "plazo_h": a["plazo_h"], "precio_puesto": round(a["precio"] + a["envio"], 2), "precio_litro_puesto": round(a["pl"], 2),
                                "origen_provincia": a["origen_provincia"], "origen_fuente": a["origen_fuente"], "origen_declarado": a["origen_declarado"]} for a in o]})
    return out, hasta, info


METODOS_PUESTO = ("domicilio", "retiro", "agencia")


def puesto(d, pid, dias=7, metodo=None):
    """Precio puesto en cada provincia de un producto: por (provincia, fuente), el mínimo y la mediana de $/L puesto sobre los avisos
    de la ventana (cada aviso una vez, con su cotización `ok` más reciente; precio y envío del MISMO día). Una mediana nunca mezcla fuentes.
    No toca obs, índice, vitrina ni comparador. Provincia sin cotización ok: celda con minimo null y sus contadores (n_no_envia, n_sin_cotizacion).
    `metodo` (domicilio|retiro|agencia): solo cuentan las cotizaciones ok de ese método (un retiro a $0 no se lee como envío gratis)."""
    envios = d.get("envios", [])
    hasta = max((r["fecha"] for r in envios), default="")
    desde = (date.fromisoformat(hasta) - timedelta(days=dias - 1)).isoformat() if hasta else ""
    cp = {c["provincia"]: c["cp"] for c in d.get("cp", [])}
    vend = {(r["fuente"], r["url"], r["fecha"]): r["vendedor"] for r in d["obs"] if r["fuente"] in {e["fuente"] for e in envios}}
    ok, otros = {}, defaultdict(set)
    for r in envios:
        if r["producto_id"] != pid or not desde <= r["fecha"] <= hasta:
            continue
        k = (r["fuente"], r["url"], r["provincia_destino"])
        if metodo and r["estado"] == "ok" and r["metodo"] != metodo:
            continue
        if r["estado"] == "ok" and num(r["costo_envio"]) is not None:
            if k not in ok or (r["fecha"], -num(r["costo_envio"])) > (ok[k]["fecha"], -num(ok[k]["costo_envio"])):  # la más reciente; ese día, el método más barato
                ok[k] = r
        else:
            otros[k].add(r["estado"])
    avisos = []
    for k, r in ok.items():
        env = num(r["costo_envio"])
        pl = precio_litro({**r, "precio": (num(r["precio"]) or 0) + env}) if num(r["precio"]) else None
        if pl is not None:
            avisos.append({**r, "pl": pl, "envio": env, "vendedor": vend.get((r["fuente"], r["url"], r["fecha"]), "")})
    por_fuente = defaultdict(list)
    for a in avisos:
        por_fuente[a["fuente"]].append((a["pl"], a))
    cuerdo = {id(a) for xs in por_fuente.values() for _, a in cuerdos(xs)}  # sanidad de la vitrina, por fuente y sobre todas las provincias
    avisos = [a for a in avisos if id(a) in cuerdo]
    celdas = defaultdict(lambda: {"avisos": [], "no_envia": 0, "sin_cotizacion": 0})
    for a in avisos:
        celdas[(a["provincia_destino"], a["fuente"])]["avisos"].append(a)
    for k, est in otros.items():  # avisos sin cotización ok en la ventana: no_envia (un dato) o sin_cotizacion (un hueco)
        if k not in ok:
            celdas[(k[2], k[0])]["no_envia" if "no_envia" in est else "sin_cotizacion"] += 1
    out = []
    for (pv, fu), c in sorted(celdas.items()):
        xs = sorted(c["avisos"], key=lambda a: a["pl"])
        m = xs[0] if xs else None
        out.append({"provincia": pv, "cp": cp.get(pv, ""), "fuente": fu,
                    "minimo": m and {"precio_puesto": round(num(m["precio"]) + m["envio"], 2), "precio": num(m["precio"]), "envio": m["envio"], "vendedor": m["vendedor"] or None,
                                     "url": m["url"], "fecha": m["fecha"], "metodo": m["metodo"], "deposito": m.get("deposito") or None},
                    "minimo_litro_puesto": m and round(m["pl"], 2), "mediana_litro_puesto": round(median(a["pl"] for a in xs), 2) if xs else None,
                    "n": len(xs), "n_no_envia": c["no_envia"], "n_sin_cotizacion": c["sin_cotizacion"], "fecha": max((a["fecha"] for a in xs), default=None),
                    "avisos": [{"vendedor": a["vendedor"] or None, "url": a["url"], "fecha": a["fecha"], "precio": num(a["precio"]), "envio": a["envio"], "metodo": a["metodo"], "deposito": a.get("deposito") or None,
                                "plazo_h": num(a["plazo_h"]), "precio_puesto": round(num(a["precio"]) + a["envio"], 2), "precio_litro_puesto": round(a["pl"], 2)} for a in xs]})
    cc, h_obs, info = puesto_correo(d, pid, dias, metodo)
    if not hasta and cc:  # sin envíos de ML/Norauto pero con tarifas de Correo: la ventana es la de los avisos
        hasta = h_obs
        desde = (date.fromisoformat(hasta) - timedelta(days=dias - 1)).isoformat()
    out = sorted(out + cc, key=lambda c: (c["provincia"], c["fuente"]))
    return {"producto_id": pid, "pais": "AR", "moneda": "ARS", "dias": dias, "metodo": metodo, "desde": desde or None, "hasta": hasta or None, "nota": NOTA_PUESTO, "celdas": out,
            "correo": info}


def aplanar_puesto(v):
    return [{"producto_id": v["producto_id"], **{k: c[k] for k in ("provincia", "cp", "fuente", "minimo_litro_puesto", "mediana_litro_puesto", "n", "n_no_envia", "n_sin_cotizacion", "fecha")},
             **(c["minimo"] or {}), "pais": "AR", "moneda": "ARS"} for c in v["celdas"]]


def provincias_resumen(d, dias=30, fuente="", mayoristas=False, pais="AR", desde=None, hasta=None):
    """Sin producto_id: por cada producto YPF y fuente, $/L mediano, avisos, cuántas provincias distintas y fecha (sin detalle por provincia)."""
    d = de_pais(d, pais)
    ypf = productos_de(d, pais)
    desde, hasta = desde_hasta(d, dias, desde, hasta)
    hasta, por = _avisos(d, dias, {p["producto_id"] for p in ypf}, True, desde, hasta)
    out = []
    for p in ypf:
        rs = _filtrar(por.get(p["producto_id"], []), fuente, mayoristas)
        out.append({"producto_id": p["producto_id"], "nombre": p["nombre"], "fuentes": [
            _celda(g, provincias=len({r.get("provincia") for r in g} & set(subdivisiones(pais))))
            for f in sorted({r["fuente"] for r in rs}) for g in [[r for r in rs if r["fuente"] == f]]]})
    return {"pais": pais, "moneda": PAISES[pais][1], **_rango(dias, desde, hasta), "nota": NOTA_FRESCURA, "productos": out}


def reventa(d, pid, dias=30, pais="AR", desde=None, hasta=None):
    """Observaciones del período (todas, no solo la última por aviso) del producto YPF y de cada equivalente que no sea no_equivalente."""
    d = de_pais(d, pais)
    desde, hasta = desde_hasta(d, dias, desde, hasta)
    prod = {p["producto_id"]: p for p in d["productos"]}
    eqs = [e for e in d["equivalencias"] if e["ypf_id"] == pid and e["tipo"] != "no_equivalente"]
    ids = {pid} | {e["comp_id"] for e in eqs}
    por = defaultdict(list)
    for r in d["obs"]:
        if r["producto_id"] in ids and desde <= r["fecha"] <= hasta:
            pl, prov = precio_litro(r), r.get("provincia", "")
            por[r["producto_id"]].append({
                "fecha": r["fecha"], "fuente": r["fuente"], "canal": canal(r["fuente"]), "vendedor": r["vendedor"], "provincia": prov,
                "region": REGIONES.get(prov, ""), "url": r["url"], "precio": num(r["precio"]), "precio_litro": round(pl, 2) if pl else None,
                "litros": num(r["litros"]), "unidades": num(r["unidades"]) or 1,
                "verificado": r.get("verificado") or "", "cargado": r.get("cargado") or "", "moneda": moneda_r(r)})
    obs = lambda i: sorted(por.get(i, []), key=lambda o: (o["fecha"], o["fuente"]), reverse=True)
    ficha = lambda i: {"producto_id": i, "marca": prod.get(i, {}).get("marca", ""), "nombre": prod.get(i, {}).get("nombre", ""), "observaciones": obs(i)}
    return {"producto_id": pid, "pais": pais, "moneda": PAISES[pais][1], **_rango(dias, desde, hasta), "nota": NOTA_FRESCURA, "ypf": ficha(pid),
            "equivalentes": [{**ficha(e["comp_id"]), "tipo": e["tipo"], "evidencia": e["evidencia"]} for e in eqs]}


def aplanar_reventa(v):
    fichas = [("ypf", v["ypf"], "")] + [("equivalente", e, e["tipo"]) for e in v["equivalentes"]]
    return [{"rol": rol, "producto_id": f["producto_id"], "marca": f["marca"], "nombre": f["nombre"], "tipo": tipo, "pais": v["pais"], **o}
            for rol, f, tipo in fichas for o in f["observaciones"]]


# ---------- /api/producto: lo que muestra la página de producto del visor (y lo que consume el agente de sobreprecios) ----------
NOMBRE_FUENTE = {"ypf_gql": "YPF catálogo", "vtex_carrefour": "Carrefour", "vtex_masonline": "Masonline", "vtex_easy": "Easy", "vtex_jumbo": "Jumbo",
                 "vtex_norauto": "Norauto", "shopify_datri": "Tienda D'Atri", "tn_lspalermo": "LS Palermo", "tn_spch": "Casa González",
                 "tn_rano": "Repuestos Rano", "tn_olafil": "Olafil", "tn_lubrimaster": "Lubrimaster", "tn_lubricentrodg": "Lubricentro DG",
                 "tn_exporepuestos": "Exporepuestos", "tn_netrenault": "Net Renault", "tn_gramaglia": "Gramaglia Repuestos", "tn_torooils": "Toro Oils",
                 "woo_larutaok": "Neumáticos La Ruta OK", "woo_ceridono": "Ceridono", "woo_fiatturin": "Fiatturin", "tn_comprarmarket": "Comprar Market",
                 "odoo_performancelube": "Performance Lube", "presta_motoracing": "Motoracing",
                 "sepa": "Precios Claros (SEPA)", "ml": "Mercado Libre", "ml_envios": "Mercado Libre (cotización de envíos)", "correo_ar": "Correo Argentino (estimado desde la provincia del aviso)",
                 "vtex_norauto_envios": "Norauto (cotización de envíos)", "vtex_br_pitstop": "Pitstop (Brasil)", "vtex_br_altese": "Altese (Brasil)",
                 "oficial_br_notaparana": "Nota Paraná (Brasil, notas fiscales)"}
METODO = ("Misma lógica que la vitrina (/api/vitrina). Cada aviso (fuente + url + ean + título + vendedor + envase; la provincia no entra) cuenta una vez, con su observación más reciente de la ventana "
          f"(por defecto {VENTANA_DIAS} días, termina en el último día con datos; con dias/desde/hasta se amplía). precio_litro = precio / (litros × unidades). Quedan fuera del cálculo (en_calculo=false, con motivo_exclusion): "
          "avisos sin litros (sin_litros), mayoristas (mayorista, salvo ?mayoristas=1), Grok no verificado (grok_sin_verificar) y los que caen fuera de "
          f"[mediana / {SANIDAD:g}, mediana × {SANIDAD:g}] del producto (fuera_de_sanidad: envase mal leído). Los servicios (combos con mano de obra) nunca entran. "
          "resumen usa solo los avisos en cálculo; el promedio es la media simple y la mediana es el valor central (no la distorsionan los extremos). "
          "desvio_pct_vs_mediana = (precio_litro / mediana_litro - 1) × 100 contra la mediana del propio producto. "
          "comparacion: dif_pct_promedio_comp_vs_ypf = (promedio de todos los avisos de los equivalentes incluidos / promedio YPF - 1) × 100 (el de la vitrina) y dif_pct_mediana_comp_vs_ypf con medianas; positivo = la competencia es más cara; "
          f"no entran los no_equivalente ni los equivalentes cuya mediana está a más de {RANGO_EQ} veces la de YPF. "
          "Las url son publicaciones de terceros; SEPA no trae url. Sin umbral de sobreprecio: lo decide quien consume el dato.")
PUBLICACION_F = ["fuente", "fuente_nombre", "canal", "vendedor", "sucursal", "provincia", "fecha", "capturado", "precio", "litros", "unidades",
                 "precio_litro", "desvio_pct_vs_mediana", "url", "verificado", "respaldo", "en_calculo", "motivo_exclusion", "sobre_umbral"]
CAMPOS["producto"] = ["rol", "producto_id", "marca", "nombre", "tipo", "evidencia"] + PUBLICACION_F + ["pais", "moneda"]


def nombre_fuente(d, f):
    if f.startswith("grok_"):
        host = next((s["host"] for s in d.get("grok_sitios", []) if s["fuente"] == f), "")
        return "Grok · " + (host or f)
    return NOMBRE_FUENTE.get(f, f) + (" (mayorista)" if f in MAYORISTAS else "")


def _cuartiles(xs):
    if len(xs) < 2:
        return xs[0], xs[0]
    q = quantiles(xs, n=4, method="inclusive")
    return q[0], q[2]


def _publicaciones(d, rs, mayoristas, umbral):
    """rs: los avisos (de `_avisos`) de UN producto → (resumen de los que cuentan, publicaciones[] con en_calculo y motivo_exclusion)."""
    cand = _validos(rs, mayoristas)
    dentro = {id(r) for _, r in cuerdos(cand)} if cand else set()
    pls = sorted(pl for pl, r in cand if id(r) in dentro)
    res = _stats([(pl, None) for pl in pls])
    med = res["mediana_litro"]
    res["p25_litro"], res["p75_litro"] = (round(x, 2) for x in _cuartiles(pls)) if pls else (None, None)
    pubs = []
    for r in rs:
        pl, f = r["pl"], r["fuente"]
        motivo = (None if id(r) in dentro else "sin_litros" if pl is None else "mayorista" if f in MAYORISTAS and not mayoristas
                  else "grok_sin_verificar" if r.get("verificado") == "0" else "fuera_de_sanidad")
        desvio = round((pl / med - 1) * 100, 1) if pl is not None and med else None
        pub = {"fuente": f, "fuente_nombre": nombre_fuente(d, f), "canal": canal(f), "vendedor": r["vendedor"] or None, "sucursal": r.get("sucursal") or None,
               "provincia": r.get("provincia") or None, "fecha": r["fecha"], "capturado": r.get("capturado") or None, "precio": num(r["precio"]),
               "litros": num(r["litros"]), "unidades": num(r["unidades"]) or 1, "precio_litro": round(pl, 2) if pl is not None else None,
               "desvio_pct_vs_mediana": desvio, "url": r["url"] or None, "verificado": {"1": True, "0": False, "respaldo": False}.get(r.get("verificado") or ""),
               "respaldo": r.get("verificado") == "respaldo", "en_calculo": motivo is None, "motivo_exclusion": motivo}
        if umbral is not None:
            pub["sobre_umbral"] = desvio is not None and desvio >= umbral
        pubs.append(pub)
    pubs.sort(key=lambda p: (not p["en_calculo"], -(p["precio_litro"] or 0), p["fuente"], p["url"] or ""))
    return res, pubs


def producto(d, pid, dias=VENTANA_DIAS, mayoristas=False, umbral=None, pais="AR", desde=None, hasta=None):
    """Todo lo que muestra la página de un producto: sus publicaciones (una por aviso, con link y desvío contra la mediana), las de cada equivalente
    y la comparación YPF vs competencia. Reusa `_avisos` (clave de aviso), `cuerdos` (sanidad) y `precio_litro`. No decide qué es un sobreprecio."""
    d = de_pais(d, pais)
    prod = {p["producto_id"]: p for p in d["productos"]}
    foto = {f["producto_id"]: f for f in d.get("imagenes", [])}
    eqs = list({e["comp_id"]: e for e in reversed(d["equivalencias"]) if e["ypf_id"] == pid}.values())[::-1]  # una por competidor (la primera), como la vitrina
    hasta, por = _avisos(d, dias, {pid} | {e["comp_id"] for e in eqs}, None, desde, hasta)
    desde, _ = desde_hasta(d, dias, desde, hasta)
    if desde and hasta:
        dias = (date.fromisoformat(hasta) - date.fromisoformat(desde)).days + 1  # con rango explícito `dias` es el largo real
    res, pubs = _publicaciones(d, por.get(pid, []), mayoristas, umbral)
    p = prod[pid]
    equivalentes, pool, pool_raw = [], [], []
    for e in eqs:
        c = prod.get(e["comp_id"], {})
        r, ps = _publicaciones(d, por.get(e["comp_id"], []), mayoristas, umbral)
        motivo = "no_equivalente" if e["tipo"] == "no_equivalente" else None
        if not motivo and r["mediana_litro"] and res["mediana_litro"] and not 1 / RANGO_EQ <= r["mediana_litro"] / res["mediana_litro"] <= RANGO_EQ:
            motivo = "fuera_de_rango"
        if not motivo:
            pool += [x["precio_litro"] for x in ps if x["en_calculo"]]
            cand = _validos(por.get(e["comp_id"], []), mayoristas)
            pool_raw += [pl for pl, _ in cuerdos(cand)] if cand else []  # sin redondear: el promedio sale igual que en la vitrina
        equivalentes.append({"producto_id": e["comp_id"], "marca": c.get("marca", ""), "nombre": c.get("nombre", ""), "tipo": e["tipo"], "evidencia": e["evidencia"],
                             "specs": specs(c), "imagen": (foto.get(e["comp_id"]) or {}).get("url"), "en_comparacion": motivo is None,
                             "motivo_exclusion": motivo, "resumen": r, "publicaciones": ps})
    mc = round(median(pool), 2) if pool else None
    pc = round(sum(pool_raw) / len(pool_raw), 2) if pool_raw else None
    return {"producto": {"producto_id": pid, "marca": p["marca"], "linea": p["linea"], "nombre": p["nombre"], "segmento": p["segmento"], "sae": p["sae"],
                         "base": p["base"], "es_ypf": p["marca"] == "YPF", "specs": specs(p), "imagen": (foto.get(pid) or {}).get("url"),
                         "imagen_fuente": (foto.get(pid) or {}).get("fuente"), "modelo": modelo(pid)},
            "pais": pais, "moneda": PAISES[pais][1], "ventana": {"dias": dias, "desde": desde, "hasta": hasta}, "nota": NOTA_FRESCURA, "metodo": METODO,
            "datos": {"desde": min((r["fecha"] for r in d["obs"]), default=""), "hasta": max((r["fecha"] for r in d["obs"]), default="")},  # límites del calendario del visor
            "mayoristas_incluidos": mayoristas, **({"umbral_pct": umbral} if umbral is not None else {}),
            "resumen": res, "publicaciones": pubs, "equivalentes": equivalentes,
            "comparacion": {"mediana_ypf_litro": res["mediana_litro"], "mediana_comp_litro": mc, "n_comp": len(pool),
                            "dif_pct_mediana_comp_vs_ypf": round((mc / res["mediana_litro"] - 1) * 100, 1) if mc and res["mediana_litro"] else None,
                            # el mismo número que la vitrina (promedio de la competencia contra el promedio YPF)
                            "promedio_ypf_litro": res["promedio_litro"], "promedio_comp_litro": pc,
                            "dif_pct_promedio_comp_vs_ypf": round((pc / res["promedio_litro"] - 1) * 100, 1) if pc and res["promedio_litro"] else None}}


def aplanar_producto(v):
    pais, moneda = v["pais"], v["moneda"]
    fichas = [("ypf" if v["producto"]["es_ypf"] else "producto", v["producto"], "", "", v["publicaciones"])] + [
        ("equivalente", e, e["tipo"], e["evidencia"], e["publicaciones"]) for e in v["equivalentes"]]
    return [{"rol": rol, "producto_id": f["producto_id"], "marca": f["marca"], "nombre": f["nombre"], "tipo": tipo, "evidencia": ev, "pais": pais, "moneda": moneda, **x}
            for rol, f, tipo, ev, ps in fichas for x in ps]


def cobertura(d, pais="AR"):
    """Por producto YPF del seed: equivalencias (sin no_equivalente), fuentes y provincias con precio en los últimos 7 días y última fecha.
    Cuenta solo el precio del propio producto YPF; Grok sin verificar no cuenta."""
    d = de_pais(d, pais)
    desde, hasta = desde_hasta(d, 7)
    neq = Counter(e["ypf_id"] for e in d["equivalencias"] if e["tipo"] != "no_equivalente")
    fu, pr, ult = defaultdict(set), defaultdict(set), {}
    for r in d["obs"]:
        pid = r["producto_id"]
        if pid and (num(r["precio"]) or 0) > 0 and r.get("verificado") != "0":
            ult[pid] = max(ult.get(pid, ""), r["fecha"])
            if r["fecha"] >= desde:
                fu[pid].add(r["fuente"])
                if r.get("provincia") in subdivisiones(pais):
                    pr[pid].add(r["provincia"])
    prods = [{"producto_id": p["producto_id"], "nombre": p["nombre"], "linea": p["linea"], "segmento": p["segmento"], "sae": p["sae"],
              "equivalencias": neq[p["producto_id"]], "tiene_equivalencia": neq[p["producto_id"]] > 0,
              "fuentes_7d": len(fu[p["producto_id"]]), "provincias_7d": len(pr[p["producto_id"]]),
              "ultima_fecha": ult.get(p["producto_id"])} for p in productos_de(d, pais)]
    return {"pais": pais, "moneda": PAISES[pais][1], "hasta": hasta, "nota": NOTA_FRESCURA,
            "total": {"productos_ypf": len(prods), "con_equivalencia": sum(p["tiene_equivalencia"] for p in prods),
                      "con_precio_7d": sum(p["fuentes_7d"] > 0 for p in prods)},
            "productos": prods}


PRODUCTOS_SHARE = {"automotrices": "Lubricantes automotrices(m3)", "industriales": "Lubricantes industriales(m3)",
                   "marinos": "Lubricantes marinos(m3)", "grasas": "Grasas(Ton)"}
TOP_EMPRESAS, MESES_SHARE, PUNTOS_ACTIVIDAD = 7, 36, 60
ID_PEAJES, ID_AGRO, ID_IPC = "302.3_S_ORIGINALJES_0_S_17", "11.3_ISOM_2004_M_39", "148.3_INIVELNAL_DICI_M_26"
ID_SALARIO = "149.1_SOR_PRIADO_OCTU_0_25"
ID_GASOIL_CARGA = "se_gasoil_carga"
# ponytail: pesos supuestos del relevamiento, sin calibrar contra el volumen de la SE (regresión pendiente).
PESOS_IDP = {ID_PEAJES: 0.5, ID_GASOIL_CARGA: 0.3, ID_AGRO: 0.2}
FUENTE_SE = "Secretaría de Energía, SESCO Downstream (datos.energia.gob.ar)"
# Series que salen de data/macro/energia.csv: (id, nombre, grupo, prefijo de producto, canal o None = todos)
DERIVADAS = [
    ("se_lub_automotrices", "Lubricantes automotrices vendidos", "demanda", "Lubricantes automotrices", None),
    ("se_lub_industriales", "Lubricantes industriales vendidos", "demanda", "Lubricantes industriales", None),
    (ID_GASOIL_CARGA, "Gasoil vendido a Transporte de Carga", "pesado", "Gasoil", "Transporte de Carga"),
    ("se_gasoil_agro", "Gasoil vendido al Agro", "agro", "Gasoil", "Agro"),
]
NOTA_SHARE = ("Share entre las empresas que declaran a la Secretaría de Energía (SESCO): Mobil, Castrol, Motul, Liqui Moly y los importadores chicos no figuran. "
              "Es el volumen que vende la empresa (sell-in), no lo que compra el consumidor final, y viene por empresa, no por marca "
              "comercial (Elaion, Helix). Una empresa sin fila ese mes se muestra sin dato, no como 0.")


def leer_energia(path):
    """data/macro/energia.csv → tuplas (mes, empresa, producto, canal, provincia, cantidad). Las repetidas se internan: son ~200 mil filas."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        lector = csv.reader(f)
        next(lector, None)
        return [(*map(sys.intern, r[:5]), float(r[5])) for r in lector if len(r) >= 6]


def punto(fecha, valor, signo=""):
    """Un dato de serie. Null nunca es 0: sin signo se muestra '...'; solo el signo '-' (cero absoluto del INDEC) vale 0."""
    v = num(valor) if valor not in ("", None) else None
    if v is not None and not math.isfinite(v):
        v = None
    signo = signo or None
    if v is None:
        return {"fecha": fecha, "valor": 0.0, "signo": "-"} if signo == "-" else {"fecha": fecha, "valor": None, "signo": signo or "..."}
    return {"fecha": fecha, "valor": v, "signo": signo}


def var_ia(serie):
    """Variación interanual (%) del último punto contra el mismo mes/día del año anterior. Solo si existen los dos extremos."""
    if not serie or serie[-1]["valor"] is None:
        return None
    f = serie[-1]["fecha"]
    ant = {p["fecha"]: p["valor"] for p in serie}.get(f"{int(f[:4]) - 1:04d}{f[4:]}")
    return round((serie[-1]["valor"] / ant - 1) * 100, 2) if ant else None


def mes_mas(m, k):
    a, b = divmod(int(m[:4]) * 12 + int(m[5:7]) - 1 + k, 12)
    return f"{a:04d}-{b + 1:02d}"


def series_macro(d):
    """→ (meta por id, serie por id): las de datos.gob.ar (data/macro/series.csv) más las derivadas de energia.csv."""
    meta = {s["id"]: {k: s[k] for k in ("nombre", "grupo", "frec", "unidad", "fuente")} for s in d["macro_seed"]}
    crudas = defaultdict(list)
    for r in d["macro"]:
        crudas[r["id"]].append(punto(r["fecha"], r["valor"], r["signo"]))
    ser = {i: sorted(crudas.get(i, []), key=lambda p: p["fecha"]) for i in meta}
    for sid, nombre, grupo, prefijo, canal in DERIVADAS:
        por_mes = defaultdict(float)
        for mes, _e, prod, can, _p, q in d["energia"]:
            if prod.startswith(prefijo) and (canal is None or can == canal):
                por_mes[mes] += q
        meta[sid] = {"nombre": nombre, "grupo": grupo, "frec": "M", "unidad": "m3", "fuente": FUENTE_SE}
        ser[sid] = []
        if por_mes:  # un mes sin fila dentro del rango es hueco ('...'), no 0
            desde, hasta = min(por_mes), max(por_mes)
            ser[sid] = [punto(f"{m}-01", por_mes.get(m)) for m in (mes_mas(desde, k) for k in range(
                (int(hasta[:4]) - int(desde[:4])) * 12 + int(hasta[5:7]) - int(desde[5:7]) + 1))]
    return meta, ser


def _cs(canal):
    """canal(es) → set o None (sin filtro): acepta un nombre, una lista o None."""
    return None if not canal else {canal} if isinstance(canal, str) else set(canal)


def lista(v):
    """'a,b' → ['a','b'] sin vacíos ni repetidos, en orden."""
    return list(dict.fromkeys(x.strip() for x in (v or "").split(",") if x.strip()))


def producto_multi(prods):
    """Claves de PRODUCTOS_SHARE → (nombre del conjunto, unidad). ValueError con el mensaje del 400 si hay una clave inválida o si se mezclan unidades:
    los lubricantes (m3) se suman entre sí; Grasas (Ton) nunca con m3."""
    mal = [p for p in prods if p not in PRODUCTOS_SHARE]
    if mal:
        raise ValueError(f"producto inválido: {', '.join(mal)}")
    us = {unidad_se(PRODUCTOS_SHARE[p]) for p in prods}
    if len(us) > 1:
        raise ValueError("no se pueden sumar productos en m3 con Grasas (toneladas): elegí los lubricantes juntos o Grasas sola")
    return (PRODUCTOS_SHARE[prods[0]] if len(prods) == 1 else f"Lubricantes {' + '.join(prods)}({us.pop()})"), unidad_se(PRODUCTOS_SHARE[prods[0]])


def filas_productos(d, prods):
    return [f for p in prods for f in d["energia_por_producto"].get(PRODUCTOS_SHARE[p], [])]


def agregado(filas, canal=None):
    canal = _cs(canal)
    vol, tot = defaultdict(float), defaultdict(float)
    for mes, emp, _prod, can, _prov, q in filas:
        if not canal or can in canal:
            vol[(mes, emp)] += q
            tot[mes] += q
    return vol, tot


def share_completo(filas, canal=None):
    """Serie desde el primer mes del archivo, con las mismas empresas (top 7 + Otras) que la ventana de 36 meses de `share`."""
    vol, tot = agregado(filas, canal)
    if not tot:
        return share(filas, canal)
    a, b = min(tot), max(tot)
    n = (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7]) + 1
    return share(filas, canal, n, top=[e["empresa"] for e in share(filas, canal)["empresas"] if e["empresa"] != "Otras"])


def share(filas, canal=None, n=MESES_SHARE, top=None):
    """Share mensual por empresa de un producto (`filas` = tuplas de energia.csv de ese producto), últimos n meses, top 7 + Otras (o `top` fijo)."""
    canal = _cs(canal)
    vol, tot = agregado(filas, canal)
    out = {"meses": [], "total": [], "empresas": [], "canales": [], "provincias": [], "nota": NOTA_SHARE}
    if not tot:
        return out
    meses = [mes_mas(max(tot), k - n + 1) for k in range(n)]
    ventana = set(meses)
    por_canal, por_emp = defaultdict(float), defaultdict(float)
    for mes, emp, _p, can, _pr, q in filas:
        if mes in ventana:
            por_canal[can] += q
    for (mes, emp), q in vol.items():
        if mes in ventana:
            por_emp[emp] += q
    ranking = sorted(por_emp, key=lambda e: (-por_emp[e], e))
    top = top or ranking[:TOP_EMPRESAS]

    def fila(nombre, vols):
        serie = [v / tot[m] if v is not None and tot.get(m) else None for m, v in zip(meses, vols)]
        u, h = serie[-1], serie[-13] if len(serie) >= 13 else None
        return {"empresa": nombre, "serie": [None if x is None else round(x, 6) for x in serie],
                "ultimo": None if u is None else round(u, 6), "hace12": None if h is None else round(h, 6),
                "var_pp": round((u - h) * 100, 2) if u is not None and h is not None else None,
                "volumen_ultimo": None if vols[-1] is None else round(vols[-1], 3),
                "volumen": [None if v is None else round(v, 3) for v in vols]}  # paralela a serie: null = no declaró
    empresas = [fila(e, [vol.get((m, e)) for m in meses]) for e in top]
    if len(ranking) > len(top):
        empresas.append(fila("Otras", [max(0.0, tot[m] - sum(vol.get((m, e), 0.0) for e in top)) if m in tot else None for m in meses]))
    ult, ant = meses[-1], meses[-13] if len(meses) >= 13 else None
    tp, yp = defaultdict(float), {}
    mp = set(meses[-MESES_SHARE:])  # el selector de mes del visor: solo la ventana de 36, no la serie completa
    for mes, emp, _p, can, prov, q in filas:
        if mes in mp and (not canal or can in canal):
            tp[(mes, prov)] += q
            if emp == "YPF":
                yp[(mes, prov)] = yp.get((mes, prov), 0.0) + q
    sh = lambda m, p: yp[(m, p)] / tp[(m, p)] if (m, p) in yp and tp.get((m, p)) else None
    provincias = []
    for p in sorted({p for m, p in tp if m == ult}, key=lambda p: -tp[(ult, p)]):
        a, b = sh(ult, p), sh(ant, p)
        provincias.append({"provincia": p, "share_ypf": None if a is None else round(a, 6), "share_ypf_hace12": None if b is None else round(b, 6),
                           "var_pp": round((a - b) * 100, 2) if a is not None and b is not None else None, "volumen": round(tp[(ult, p)], 3)})
    # share de YPF por provincia de cada mes de la ventana: el visor elige mes y mes de comparación sin pedir de nuevo
    prov_meses = {m: {p: {"share_ypf": None if sh(m, p) is None else round(sh(m, p), 6), "volumen": round(tp[(m, p)], 3)}
                      for mm, p in tp if mm == m} for m in meses[-MESES_SHARE:]}
    out.update(meses=meses, total=[round(tot[m], 3) if m in tot else None for m in meses], empresas=empresas,
               canales=sorted(por_canal, key=lambda c: -por_canal[c]), provincias=provincias,
               provincias_meses={m: v for m, v in prov_meses.items() if v})
    return out


def share_filas(filas, canal=None):
    """Serie mensual completa (todos los meses, todas las empresas) para /api/mercado/share?formato=csv."""
    vol, tot = agregado(filas, canal)
    return [{"mes": m, "empresa": e, "volumen": round(q, 3), "total": round(tot[m], 3), "share": round(q / tot[m], 6) if tot[m] else None}
            for (m, e), q in sorted(vol.items(), key=lambda x: (x[0][0], -x[1], x[0][1]))]


# ---------- dónde pierde share YPF: /api/mercado/perdidas y /api/mercado/filas ----------
VENTANAS = ("12m", "mes", "anterior")
MES_RX = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def piso(n):
    """Piso de volumen por defecto (m3 o Ton, igual para todos los productos) según el largo del período: lineal de 5 (1 mes) a 50 (12 meses), sigue creciendo igual
    más allá. Se cambia con ?min=."""
    return round(5 + 45 * (n - 1) / 11, 1)


def periodo_explicito(desde, hasta, vs, lo, hi):
    """?desde&hasta&vs → (t, t0), listas de meses del mismo largo. ValueError con el mensaje del 400 si algo no cierra. `lo`/`hi` = primer y último mes con datos."""
    for nom, m in (("desde", desde), ("hasta", hasta)):
        if not MES_RX.fullmatch(m or ""):
            raise ValueError(f"{nom} inválido: {m!r} (formato AAAA-MM)")
    if desde > hasta:
        raise ValueError(f"desde ({desde}) es posterior a hasta ({hasta})")
    n = (int(hasta[:4]) - int(desde[:4])) * 12 + int(hasta[5:]) - int(desde[5:]) + 1
    t = [mes_mas(desde, k) for k in range(n)]
    vs = vs or "anterior"
    if vs in ("anterior", "12m"):
        if vs == "12m" and n > 12:
            raise ValueError("vs=12m solo sirve para períodos de hasta 12 meses (el bloque de un año antes se pisaría); usá vs=anterior o un rango AAAA-MM:AAAA-MM")
        t0 = [mes_mas(m, -n if vs == "anterior" else -12) for m in t]
    else:
        a, _, b = vs.partition(":")
        if not (MES_RX.fullmatch(a) and MES_RX.fullmatch(b) and a <= b):
            raise ValueError(f"vs inválido: {vs!r} (anterior, 12m o un rango AAAA-MM:AAAA-MM con el primero <= el segundo)")
        n0 = (int(b[:4]) - int(a[:4])) * 12 + int(b[5:]) - int(a[5:]) + 1
        if n0 != n:
            raise ValueError(f"el período de comparación tiene {n0} meses y el analizado {n}: tienen que ser del mismo largo")
        t0 = [mes_mas(a, k) for k in range(n)]
    for m in (t[0], t[-1], t0[0], t0[-1]):
        if not lo <= m <= hi:
            raise ValueError(f"{m} está fuera de los datos de este producto ({lo} a {hi})")
    return t, t0
TOP_GANADORES = 5
FUENTE_PERDIDAS = {
    "dataset": "https://datos.energia.gob.ar/dataset/5bdc436c-60d4-4c86-98ab-59834d047700",
    "recurso": "https://datos.energia.gob.ar/dataset/5bdc436c-60d4-4c86-98ab-59834d047700/resource/f0e4e10a-e4b8-44e6-bd16-763a43742107",
    "csv": "https://datos.energia.gob.ar/dataset/5bdc436c-60d4-4c86-98ab-59834d047700/resource/f0e4e10a-e4b8-44e6-bd16-763a43742107/download/ventas-excluye-ventas-a-empresas-del-sector-.csv",
    "dataset_nombre": "Refinación y Comercialización de petróleo, gas y derivados (Tablas Dinámicas)",
    "recurso_nombre": "Ventas, excluye ventas a empresas del sector", "licencia": "CC-BY 4.0", "tablas": "SESCO Downstream",
    "actualizacion": "se baja desde el servidor FLN Data Analysis (tools/recolector_casa.py) cuando la SE publica algo nuevo (last_modified del recurso en CKAN)"}
NOTA_PERDIDAS = {
    "declarantes": "Share solo entre las empresas que declaran a la Secretaría de Energía (SESCO): Mobil, Castrol, Motul, Liqui Moly y los importadores chicos no figuran, "
                   "así que una pérdida contra importadores aparece como un mercado que se achica o como ganancia de nadie.",
    "sell_in": "Es el volumen que vende la empresa (sell-in), no lo que compra el consumidor, y viene por empresa, no por marca.",
    "segmento": "La Secretaría no abre por viscosidad ni por línea (Elaion premium contra mineral): segmento = producto × canal × provincia.",
    "atraso": "El dato llega con atraso: lo publica la Secretaría y se baja una vez por mes desde la PC.",
    "descomposicion": "efecto_share = (s_t − s_t0) × total_t; efecto_mercado = s_t0 × (total_t − total_t0); la suma es exactamente la variación de volumen de YPF. "
                      "Los efectos por celda suman distinto del efecto del agregado (cambio de mezcla entre celdas).",
    "nulos": "Una empresa sin fila en un período no declaró (no es 0). Si empieza o deja de declarar entre períodos va aparte (entró / salió de la declaración) y no cuenta como ganancia ni pérdida de share. "
             "Sin fila de YPF en alguno de los dos períodos: sin dato YPF."}


def unidad_se(producto):
    """'Grasas(Ton)' → 'Ton'; 'Lubricantes automotrices(m3)' → 'm3'."""
    return producto[producto.rfind("(") + 1:-1] if producto.endswith(")") else ""


def acumular(filas, per):
    """→ ({empresa: [volumen, meses con fila]}, meses con fila de alguien) de las filas dentro de los meses `per`."""
    s, emp, meses = set(per), {}, set()
    for mes, e, _p, _c, _pr, q in filas:
        if mes in s:
            x = emp.setdefault(e, [0.0, set()])
            x[0] += q
            x[1].add(mes)
            meses.add(mes)
    return emp, meses


def segmento(filas, t, t0, minimo):
    """Un segmento (las `filas` ya son de un producto × canal × provincia) en el período t contra t0."""
    a, ma = acumular(filas, t)
    b, mb = acumular(filas, t0)
    tt, t00 = sum(v[0] for v in a.values()), sum(v[0] for v in b.values())
    r = {"total_t": round(tt, 6), "total_t0": round(t00, 6), "meses_con_dato": {"t": len(ma), "t0": len(mb)},
         "huecos": len(ma) < len(t) or len(mb) < len(t0), "ypf_t": None, "ypf_t0": None, "s_t": None, "s_t0": None, "delta_ypf": None, "diagnostico": None,
         "efecto_share": None, "efecto_mercado": None, "competidores": [], "entraron_salieron": []}
    if not tt or not t00:
        r["estado"] = "sin dato"
    elif "YPF" not in a or "YPF" not in b:
        r["estado"] = "sin dato YPF"
        r["ypf_flag"] = "entró a declarar" if "YPF" in a else "salió de la declaración"
    else:
        yt, y0 = a["YPF"][0], b["YPF"][0]
        st, s0 = yt / tt, y0 / t00
        r.update(ypf_t=round(yt, 6), ypf_t0=round(y0, 6), s_t=round(st, 6), s_t0=round(s0, 6), delta_ypf=round(yt - y0, 6),
                 efecto_share=round((st - s0) * tt, 6), efecto_mercado=round(s0 * (tt - t00), 6),
                 estado="volumen chico" if min(tt, t00) < minimo else "ok")
        for e in a.keys() & b.keys() - {"YPF"}:
            ds = a[e][0] / tt - b[e][0] / t00
            r["competidores"].append({"empresa": e, "s_t": round(a[e][0] / tt, 6), "s_t0": round(b[e][0] / t00, 6), "delta_pp": round(ds * 100, 4),
                                      "m3_eq": round(ds * tt, 6), "meses_t": len(a[e][1]), "meses_t0": len(b[e][1])})
        if st < s0:   # solo se diagnostica donde YPF pierde share; sale de los volúmenes, no se infiere nada más
            r["diagnostico"] = ("Cayó el mercado y YPF cayó más" if tt < t00 else "YPF vendió menos" if yt < y0 else "El mercado creció y YPF no acompañó")
        r["competidores"].sort(key=lambda c: (-c["m3_eq"], c["empresa"]))
    for e in sorted((a.keys() ^ b.keys()) - {"YPF"}):
        enl = e in a
        x, tot = (a[e], tt) if enl else (b[e], t00)
        r["entraron_salieron"].append({"empresa": e, "flag": "entró a declarar" if enl else "salió de la declaración", "volumen": round(x[0], 6),
                                       "share": round(x[0] / tot, 6) if tot else None})
    r["ganadores"] = [c for c in r["competidores"] if c["m3_eq"] > 0][:TOP_GANADORES]
    return r


def serie_segmento(filas, ultimo, empresas, n=MESES_SHARE):
    """Share mensual de `empresas` dentro del segmento; mes o empresa sin fila = null."""
    meses = [mes_mas(ultimo, k - n + 1) for k in range(n)]
    vol, tot = {}, {}
    for mes, e, _p, _c, _pr, q in filas:
        vol[(mes, e)] = vol.get((mes, e), 0.0) + q
        tot[mes] = tot.get(mes, 0.0) + q
    return {"meses": meses, "empresas": [{"empresa": e, "serie": [round(vol[(m, e)] / tot[m], 6) if (m, e) in vol and tot.get(m) else None for m in meses]}
                                         for e in empresas]}


def perdidas(d, producto="automotrices", canal=None, provincia=None, ventana="12m", minimo=None, desde=None, hasta=None, vs=None):
    """Dónde pierde share YPF (y con quién) en un producto: celdas canal × provincia, agregados y el foco = el filtro entero.
    Cada producto va con su unidad (Grasas en Ton, el resto en m3): nunca se suman entre productos.
    Período: `ventana` (atajo, termina en el último mes con dato de cada producto) o explícito `desde`/`hasta`/`vs` (ValueError si no cierra)."""
    prods = [producto] if isinstance(producto, str) else list(producto)
    producto_multi(prods)   # ValueError si hay una clave inválida o se mezclan m3 con Ton
    prods = [k for k in PRODUCTOS_SHARE if k in prods]
    nom, unidad = producto_multi(prods)
    cs, ps = _cs(canal), _cs(provincia)
    sal = lambda x: None if not x else next(iter(x)) if len(x) == 1 else sorted(x)   # como en /api/mercado: None, string o lista
    todas = filas_productos(d, prods)
    ult = max((f[0] for f in todas), default=None)
    explicito = desde is not None or hasta is not None or vs is not None
    cache = d.setdefault("_cache_perdidas", {})
    if not ult:
        return {"producto": nom, "clave": ",".join(prods), "productos": prods, "unidad": unidad, "ventana": ventana, "min": piso(1) if minimo is None else minimo, "segmentos": [], "foco": None,
                "fuente": FUENTE_PERDIDAS, "nota": NOTA_PERDIDAS}

    def periodos(prod_filas):
        u = max((f[0] for f in prod_filas), default=None)
        if explicito:
            return u, fijo[0], fijo[1]
        n = 12 if ventana == "12m" else 1
        t = [mes_mas(u, k - n + 1) for k in range(n)] if u else []
        return u, t, [mes_mas(m, -1 if ventana == "anterior" else -12) for m in t]
    if explicito:
        fijo = periodo_explicito(desde, hasta, vs, min(f[0] for f in todas), ult)
    ult_, t, t0 = periodos(todas)
    minimo = piso(len(t)) if minimo is None else minimo
    clave = (tuple(prods), tuple(sorted(cs or ())), tuple(sorted(ps or ())), minimo, (desde, hasta, vs or "anterior") if explicito else ventana)
    if clave in cache:
        return cache[clave]
    filtrar = lambda fs, c, p: [f for f in fs if (not c or f[3] in c) and (not p or f[4] in p)]
    ventana = "personalizado" if explicito else ventana
    filas = filtrar(todas, cs, ps)
    cab = lambda fs: {k: v for k, v in fs.items() if k != "competidores"}
    grupos = defaultdict(list)
    for f in filas:
        grupos[(f[3], f[4])].append(f)
    orden = {"ok": 0, "volumen chico": 1, "sin dato YPF": 2, "sin dato": 3}
    clave_orden = lambda s: (orden[s["estado"]], s["efecto_share"] if s["efecto_share"] is not None else 0)
    segs = sorted(({"canal": c, "provincia": p, **segmento(fs, t, t0, minimo)} for (c, p), fs in grupos.items()),
                  key=lambda s: (*clave_orden(s), s["canal"], s["provincia"]))

    def agrupar(idx):
        g = defaultdict(list)
        for f in filas:
            g[f[idx]].append(f)
        return sorted(({("canal" if idx == 3 else "provincia"): k, **cab(segmento(fs, t, t0, minimo))} for k, fs in g.items()), key=clave_orden)
    por_prod = []
    for k, nm in PRODUCTOS_SHARE.items():
        fs = filtrar(d["energia_por_producto"].get(nm, []), cs, ps)
        u, tp, t0p = periodos(fs)
        por_prod.append({"producto": nm, "clave": k, "unidad": unidad_se(nm), "ultimo_mes": u, **(cab(segmento(fs, tp, t0p, minimo)) if u else {})})
    comp = {}
    for s in segs:
        if s["estado"] != "ok":
            continue
        for c in s["competidores"]:
            x = comp.setdefault(c["empresa"], {"empresa": c["empresa"], "neto_m3": 0.0, "ganado_m3": 0.0, "ganado_donde_ypf_pierde_m3": 0.0, "celdas": 0, "segmentos": []})
            x["neto_m3"] += c["m3_eq"]
            x["celdas"] += 1
            if c["m3_eq"] > 0:
                x["ganado_m3"] += c["m3_eq"]
                if s["efecto_share"] < 0:
                    x["ganado_donde_ypf_pierde_m3"] += c["m3_eq"]
                    x["segmentos"].append({"canal": s["canal"], "provincia": s["provincia"], "m3_eq": c["m3_eq"], "delta_pp": c["delta_pp"],
                                           "s_t0": c["s_t0"], "s_t": c["s_t"]})
    for x in comp.values():
        x["segmentos"].sort(key=lambda g: (-g["m3_eq"], g["canal"], g["provincia"]))
    por_comp = sorted(({k: round(v, 6) if isinstance(v, float) else v for k, v in x.items()} for x in comp.values()),
                      key=lambda x: (-x["ganado_donde_ypf_pierde_m3"], x["empresa"]))
    foco = {**segmento(filas, t, t0, minimo), "canal": sal(cs), "provincia": sal(ps)}
    foco["serie"] = serie_segmento(filas, t[-1], ["YPF"] + [c["empresa"] for c in foco["ganadores"]])
    out = cache[clave] = {
        "producto": nom, "clave": ",".join(prods), "productos": prods, "unidad": unidad, "ventana": ventana, "min": minimo, "ultimo_mes": ult, "primer_mes": min(f[0] for f in todas), "n_meses": len(t),
        "opciones": {"canales": sorted({f[3] for f in todas}), "provincias": sorted({f[4] for f in todas})}, "periodo_t": [t[0], t[-1]], "periodo_t0": [t0[0], t0[-1]], "foco": foco, "segmentos": [cab(s) | {"ganadores": s["ganadores"]} for s in segs],
        "por_producto": por_prod, "por_canal": agrupar(3), "por_provincia": agrupar(4), "por_competidor": por_comp,
        "perdido_por_share_m3": round(sum(s["efecto_share"] for s in segs if s["estado"] == "ok" and s["efecto_share"] < 0), 6),
        "fuente": FUENTE_PERDIDAS, "nota": NOTA_PERDIDAS}
    nombres = {"YPF"} | {c["empresa"] for c in foco["competidores"]} | {x["empresa"] for x in foco["entraron_salieron"]}         | {x["empresa"] for x in por_comp} | {g["empresa"] for sg in segs for g in sg["ganadores"]}
    out["origenes"] = {e: origen(d, e) for e in sorted(nombres)}
    return out


def filas_se(d, producto=None, canal=None, provincia=None, empresa=None, desde=None, hasta=None):
    """Las filas exactas de energia.csv detrás de un número (AAAA-MM en desde/hasta, inclusive). producto/canal/provincia: un valor o varios (set/lista)."""
    producto, canal, provincia = _cs(producto), _cs(canal), _cs(provincia)
    return [{"mes": m, "empresa": e, "producto": p, "canal": c, "provincia": pr, "cantidad": q} for m, e, p, c, pr, q in d["energia"]
            if (not producto or p in producto) and (not canal or c in canal) and (not provincia or pr in provincia) and (not empresa or e == empresa)
            and (not desde or m >= desde) and (not hasta or m <= hasta)]


def _span(d):
    """{empresa: (primer mes, último mes)} con filas en energia.csv (sin la fila 'Todas' del gasoil)."""
    if "_span" not in d:
        sp = {}
        for m, e, *_ in d["energia"]:
            if e != "Todas":
                a, b = sp.get(e, (m, m))
                sp[e] = (min(a, m), max(b, m))
        d["_span"] = sp
    return d["_span"]


def marcas_empresas(d):
    """Tabla marca → empresa declarante (seed/marcas_empresas.csv). Las que declaran y no traen desde/hasta lo toman de energia.csv."""
    sp = _span(d)
    out = []
    for r in d["marcas_seed"]:
        x = dict(r)
        if x["estado"].startswith("declara") and x["empresa_se"] in sp:
            x["desde"], x["hasta"] = x["desde"] or sp[x["empresa_se"]][0], x["hasta"] or sp[x["empresa_se"]][1]
        out.append(x)
    return out


# Rótulo de marca de cada empresa de la SE (la SE publica por empresa: es una re-etiqueta, los números no cambian). `exacto` = una sola marca relevante;
# `agrupado` = varias marcas que esta fuente no puede separar. Una empresa fuera de la tabla (y `Otras`) conserva su nombre, sin precisión.
ROTULOS = {"YPF": ("YPF (Elaion, Extravida, ROD)", "exacto"), "Shell/Raízen": ("Shell (Raízen)", "exacto"), "TotalEnergies": ("TotalEnergies + Elf", "agrupado"),
           "Petronas": ("Petronas", "exacto"), "Fercol": ("Fercol", "exacto"), "DAPSA": ("DAPSA", "exacto"), "Gulf": ("Gulf", "exacto")}
PAE_ANTES = ("Axion/Esso (incluía Mobil hasta 2018, inferida)", "agrupado")
PAE_DESDE = ("Castrol + Axion (no separable)", "agrupado")


def rotulos(d, emp):
    """[{desde, marca, precision}] ordenado: el rótulo de `emp` según el mes (desde '' = desde siempre). Solo PAE/Axion cambia; el corte sale del `desde` de Castrol en el seed."""
    if emp == "PAE/Axion":
        corte = next((m["desde"] for m in d.get("marcas_seed", []) if m["marca"] == "Castrol" and m["desde"]), "2019")
        corte = corte if len(corte) > 4 else corte + "-01"
        return [{"desde": "", "marca": PAE_ANTES[0], "precision": PAE_ANTES[1]}, {"desde": corte, "marca": PAE_DESDE[0], "precision": PAE_DESDE[1]}]
    marca, prec = ROTULOS.get(emp, (emp, None))
    return [{"desde": "", "marca": marca, "precision": prec}]


def rotulo_en(rs, mes):
    return [r for r in rs if not r["desde"] or r["desde"] <= mes][-1]


def etiquetar(d, S, completo=False):
    """?por=marca: suma `marca` y `precision` (los del último mes) a cada empresa de un share; con `completo` y si cambia, `marca_mes` (rótulo por mes). No toca ningún número."""
    for e in S["empresas"]:
        rs = rotulos(d, e["empresa"]) if e["empresa"] != "Otras" else [{"desde": "", "marca": "Otras", "precision": None}]
        r = rotulo_en(rs, S["meses"][-1]) if S["meses"] else rs[-1]
        e["marca"], e["precision"] = r["marca"], r["precision"]
        if completo and len(rs) > 1:
            e["marca_mes"] = [rotulo_en(rs, m)["marca"] for m in S["meses"]]
    return S


def origen(d, emp, agrupa=None):
    """De dónde sale una línea del share: empresa declarante de la SE, razones sociales que agrupa su etiqueta, marcas, meses y filas exactas.
    `agrupa` (solo 'Otras') = las etiquetas que junta."""
    dataset = FUENTE_PERDIDAS["dataset"]
    if agrupa is not None:
        return {"fuente": "SE (SESCO) — suma de las demás empresas declarantes", "razones_sociales": agrupa, "marcas": [], "desde": None, "hasta": None,
                "filas_url": None, "dataset": dataset, "rotulos": [{"desde": "", "marca": "Otras", "precision": None}]}
    sp = _span(d).get(emp, (None, None))
    marcas = []
    for m in d["marcas_seed"]:  # fechas tal cual el seed: las calculadas de energia.csv ya están en desde/hasta de la empresa
        if m["empresa_se"] == emp or f"(hoy {emp})" in m["empresa_se"]:
            q = ", ".join(x for x in (f"desde {m['desde']}" if m["desde"] else "", f"hasta {m['hasta']}" if m["hasta"] else "",
                                       "inferida" if m["evidencia"] == "inferida" else "") if x)
            # una marca que declara sin fechas en el seed va sin calificar; con fechas del seed (Castrol desde 2019) las lleva
            marcas.append(m["marca"] + (f" ({q})" if q else ""))
    return {"fuente": f"SE (SESCO) — empresa declarante {emp}", "razones_sociales": [p for p, c in macro.ETIQUETAS if c == emp] or [emp],
            "marcas": marcas, "desde": sp[0], "hasta": sp[1], "filas_url": "/api/mercado/filas?empresa=" + urllib.parse.quote(emp), "dataset": dataset,
            "rotulos": rotulos(d, emp)}


def share_origen(d, filas, canal=None):
    """share() con `origen` en cada empresa; 'Otras' dice qué etiquetas agrupa."""
    canal = _cs(canal)
    S = share(filas, canal)
    nombres = {e["empresa"] for e in S["empresas"]}
    ventana = set(S["meses"])
    otras = sorted({f[1] for f in filas if f[0] in ventana and (not canal or f[3] in canal)} - nombres)
    for e in S["empresas"]:
        e["origen"] = origen(d, e["empresa"], otras if e["empresa"] == "Otras" else None)
    return S


def precios_pares(d):
    """$/L de los pares YPF ↔ equivalente del seed (sin no_equivalente, mayoristas ni Grok sin verificar) → (por mes, por día)."""
    lado = {}
    for e in d["equivalencias"]:
        if e["tipo"] != "no_equivalente":
            lado[e["ypf_id"]] = "ypf"
            lado.setdefault(e["comp_id"], "comp")
    por_pid = defaultdict(list)
    for r in d["obs"]:
        if r["producto_id"] in lado and r["fuente"] not in MAYORISTAS and r.get("verificado") != "0" and (pl := precio_litro(r)) is not None:
            por_pid[r["producto_id"]].append((r["fecha"], pl))
    mes, dia = defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(list))
    for pid, xs in por_pid.items():
        m = median(pl for _, pl in xs)
        for f, pl in xs:
            if m / SANIDAD <= pl <= m * SANIDAD:  # mismo filtro de envases mal leídos que la vitrina
                mes[f[:7]][lado[pid]].append(pl)
                dia[f][lado[pid]].append(pl)
    return mes, dia


def idx_2023(serie):
    """{AAAA-MM: valor / promedio 2023 × 100}. Sin los 12 meses de 2023 no hay base: vacío (no se aproxima)."""
    v = {p["fecha"][:7]: p["valor"] for p in serie if p["valor"] is not None}
    base = [v.get(f"2023-{m:02d}") for m in range(1, 13)]
    if None in base or not sum(base):
        return {}
    prom = sum(base) / 12
    return {m: x / prom * 100 for m, x in v.items()}


def compuestos(d, ser):
    mes, dia = precios_pares(d)
    ipc, sal, tc = ({p["fecha"][:n]: p["valor"] for p in ser.get(i, []) if p["valor"]} for i, n in ((ID_IPC, 7), (ID_SALARIO, 7), (ID_TC, 10)))
    med = lambda xs: round(median(xs), 2) if xs else None
    meses = sorted(mes)
    base = meses[0] if meses else None
    y = {m: med(mes[m]["ypf"]) for m in meses}
    real = lambda x, m: round(x / ipc[m] * ipc[base], 2) if x is not None and ipc.get(m) and ipc.get(base) else None
    precio_real = [{"mes": m, "ypf_litro": y[m], "ypf_real": real(y[m], m), "comp_litro": (c := med(mes[m]["comp"])), "comp_real": real(c, m)} for m in meses]
    by = next((m for m in meses if y[m] is not None), None)  # asequibilidad: base = primer mes con precio YPF
    aseq = [{"mes": m, "indice": round(y[m] / sal[m] / (y[by] / sal[by]) * 100, 1)
             if y[m] is not None and by and sal.get(m) and sal.get(by) else None} for m in meses]
    usd = lambda xs, f: round(median(xs) / tc[f], 3) if xs and tc.get(f) else None
    precio_usd = [{"fecha": f, "ypf_usd": usd(dia[f]["ypf"], f), "comp_usd": usd(dia[f]["comp"], f)} for f in sorted(dia)]
    comps = {i: idx_2023(ser.get(i, [])) for i in PESOS_IDP}
    todos = sorted(set().union(*comps.values()))[-PUNTOS_ACTIVIDAD:]
    idp = [{"mes": m, "valor": round(sum(PESOS_IDP[i] * comps[i][m] for i in PESOS_IDP), 2) if all(m in c for c in comps.values()) else None}
           for m in todos]
    return {"precio_real": precio_real, "precio_usd": precio_usd, "asequibilidad": aseq, "demanda_potencial": idp, "notas": {
        "precio_real": f"Deflactado por el IPC nacional nivel general; base = primer mes con precio ({base}). Un mes sin IPC publicado queda en null "
                       "(el IPC sale con ~1 mes de atraso). Precio = mediana del $/L de los pares YPF y equivalente del seed.",
        "precio_usd": "Mediana diaria del $/L sobre el tipo de cambio de valuación del BCRA del mismo día; un día sin cotización (fin de semana, o la serie va atrasada) queda en null, no se arrastra.",
        "asequibilidad": "Precio YPF por litro sobre el índice de salarios privados registrados (es un índice, no un monto), base 100 = primer mes con precio YPF. Sube = el aceite pesa más contra el salario.",
        "demanda_potencial": "pesos supuestos, sin calibrar: 0,5 peajes + 0,3 gasoil vendido a Transporte de Carga (SE) + 0,2 EMAE Agro, cada uno en base 2023 = 100. "
                             "Nulo en los meses donde falta algún componente o si 2023 no tiene los 12 meses."}}


def actividad(meta, ser):
    return [{"id": i, **m, "serie": ser[i][-PUNTOS_ACTIVIDAD:], "ultimo": ser[i][-1] if ser[i] else None, "var_ia": var_ia(ser[i])}
            for i, m in meta.items()]


def mercado(d, producto="automotrices", canal=None, por="empresa"):
    prods = [producto] if isinstance(producto, str) else list(producto)
    nom, _u = producto_multi(prods)
    ok = [r["fecha"] for r in d["fuentes"] if r["fuente"] == "macro_series" and not r["error"]]
    meses_e = [f[0] for f in d["energia"]]
    return {"actualizado": {"energia": max(meses_e) if meses_e else None, "series": max(ok) if ok else None},
            "share": {"producto": nom, "productos": prods, "canal": canal, "por": por,
                      **(etiquetar if por == "marca" else lambda d, S: S)(d, share_origen(d, filas_productos(d, prods), canal))},
            "marcas": marcas_empresas(d),
            "actividad": actividad(d["macro_meta"], d["macro_series"]),
            "compuestos": compuestos(d, d["macro_series"])}


def calc_pais(d, pais):
    """Lo que se calcula por país (nunca mezclado): último precio, índice y vitrina, con y sin mayoristas."""
    return {"ultimo": ultimo(d["obs"], pais), "indice": indice(d, False, pais), "indice_con_mayoristas": indice(d, True, pais),
            "vitrina": vitrina(d, False, pais), "vitrina_con_mayoristas": vitrina(d, True, pais), "indice/pares": indice_pares(de_pais(d, pais), pais)}


def calcular(d, hoy=None):
    """Lo que no depende de parámetros se calcula una vez al arrancar. Argentina va en el nivel de arriba (lo de siempre);
    `_paises` trae lo mismo por país. Mercado y mapa son solo Argentina (energia.csv y series.csv son de la SE y el INDEC)."""
    da = de_pais(d, "AR")
    bi_indice_competencia(d)  # precalienta la caché: el primer GET de Power BI no paga el barrido
    por_pais = {p: calc_pais(d, p) for p in PAISES}
    return {
        "mercado": mercado(da),
        "productos": d["productos"],
        "equivalencias": equivalencias(d),
        **por_pais["AR"],
        "_paises": por_pais,
        "fuentes": fuentes(d, hoy or date.today()),
        "sin_match": sin_match(da["obs"]),
        "oferta_ml": d["oferta_ml"],
        "servicios": servicios(d["grok"]),
        "grok_sitios": d["grok_sitios"],
    }


def autorizado(headers, clave):
    if not clave:
        return True
    k = clave.encode()
    key = headers.get("X-API-Key")
    if key and hmac.compare_digest(key.encode(), k):
        return True
    auth = headers.get("Authorization", "")
    if auth[:6].lower() == "basic ":
        try:
            usuario_clave = base64.b64decode(auth[6:].strip(), validate=True).decode()
        except ValueError:
            return False
        return hmac.compare_digest(usuario_clave.partition(":")[2].encode(), k)
    return False


def a_csv(nombre, filas):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CAMPOS[nombre], extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(filas)
    return buf.getvalue().encode()


# ---------- carga de relevamientos de Grok (POST /api/cargar) ----------
def autorizado_carga(headers, clave, clave_carga):
    """Única escritura: la lectura es abierta, esto no. La clave de carga solo sirve para cargar; la principal también.
    Sin ninguna clave configurada no se carga (no hay modo abierto para escribir)."""
    k = headers.get("X-Carga-Clave")
    if clave_carga and k and hmac.compare_digest(k.encode(), clave_carga.encode()):
        return True
    return bool(clave) and autorizado(headers, clave)


def pos(s):
    x = num(s)
    return x if x is not None and math.isfinite(x) and x > 0 else None


def error_fila(r, hoy, sitios):
    e = []
    host = urlsplit(r["url"]).hostname or ""
    # el error nombra la fuente correcta: sin eso Grok prueba nombres a ciegas (helix_combos, grok_helixturno)
    esperada = next((f for f, h in sitios.items() if h == host), None)
    usar = f": usar {esperada}" if esperada else ""
    if not RX_FUENTE.fullmatch(r["fuente"]):
        e.append(f"fuente inválida (grok_<sitio>){usar}")
    if not RX_FECHA.fullmatch(r["fecha"]):
        e.append("fecha inválida (AAAA-MM-DD)")
    else:
        try:
            if abs((date.fromisoformat(r["fecha"]) - hoy).days) > 3:
                e.append("fecha a más de 3 días de hoy")
        except ValueError:
            e.append("fecha inexistente")
    if not r["url"].startswith("https://") or not host:
        e.append("url tiene que ser https")
    elif host not in sitios.values():
        e.append(f"host {host} fuera de la lista blanca (seed/grok_sitios.csv)")
    elif sitios.get(r["fuente"]) != host:
        e.append(f"la fuente {r['fuente']} no corresponde al host {host}{usar}")
    if pos(r["precio"]) is None:
        e.append("precio tiene que ser un número > 0")
    for c in ("precio_lista", "litros", "unidades"):
        if r[c] and pos(r[c]) is None:
            e.append(f"{c} tiene que ser un número > 0 o vacío")
    if r["tipo"] not in ("producto", "servicio"):
        e.append("tipo tiene que ser producto o servicio")
    pais = (r.get("pais") or "AR").upper()
    if pais not in MONEDA_DEFECTO:
        e.append(f"pais {r['pais']!r} no es un país del relevamiento (ISO 3166-1: {', '.join(MONEDA_DEFECTO)}; vacío = AR)")
    if r.get("moneda") and r["moneda"].upper() not in MONEDAS:
        e.append(f"moneda {r['moneda']!r} no es ISO 4217 de las del relevamiento ({', '.join(sorted(MONEDAS))}; vacío = la del país)")
    if r.get("provincia") and pais in MONEDA_DEFECTO and not normalizar.provincia_iso(r["provincia"], pais):
        e.append(f"provincia {r['provincia']!r} no es una provincia de {pais} (ISO {pais}-X"
                 f"{', nombre' if pais == 'AR' else ''}, online o vacío)")
    if not r["titulo"]:
        e.append("falta titulo")
    return "; ".join(e)


def validar_csv(texto, hoy, sitios):
    """→ (filas válidas, errores por fila, error fatal). El fatal rechaza la carga entera."""
    try:
        crudas = [f for f in csv.reader(io.StringIO(texto.lstrip("﻿"))) if any(c.strip() for c in f)]
    except csv.Error as e:
        return [], [], f"CSV ilegible: {e}"
    cab = [c.strip() for c in crudas[0]] if crudas else []
    if cab not in (GROK_F, GROK_PROV_F, GROK_PAIS_F):
        return [], [], ("encabezado inválido: tiene que ser exactamente " + ",".join(GROK_F) + " o, con provincia al final, " + ",".join(GROK_PROV_F)
                        + " o, con pais y moneda al final, " + ",".join(GROK_PAIS_F))
    if len(crudas) - 1 > MAX_FILAS:
        return [], [], f"más de {MAX_FILAS} filas por carga"
    filas, errores = [], []
    for i, f in enumerate(crudas[1:], 1):
        if len(f) != len(cab):
            errores.append({"fila": i, "error": f"tiene {len(f)} columnas, esperaba {len(cab)} (¿comas sin comillas en un campo?)"})
            continue
        r = {"provincia": "", "pais": "", "moneda": "", **dict(zip(cab, (c.strip() for c in f)))}
        e = error_fila(r, hoy, sitios)
        if e:
            errores.append({"fila": i, "titulo": r["titulo"], "error": e})
        else:
            r["pais"] = (r["pais"] or "AR").upper()  # sin columnas (o vacías) = AR/ARS; moneda vacía = la del país
            r["moneda"] = (r["moneda"] or MONEDA_DEFECTO[r["pais"]]).upper()
            r["provincia"] = normalizar.provincia_iso(r["provincia"], r["pais"])  # ISO del país u "online"; vacío sigue vacío
            r["_fila"] = i
            filas.append(r)
    return filas, errores, ""


def variantes_precio(p):
    n = int(p)
    cent = round((p - n) * 100)
    ents = [str(n), f"{n:,}".replace(",", "."), f"{n:,}"]
    if cent == 0:
        return ents + [e + sep + "00" for e in ents for sep in ",."]
    return [e + sep + f"{cent:02d}" for e in ents for sep in ",."]


def precio_en_texto(precio, texto):
    """84999, 84.999, 84,999, y con ,00 / .00 (el "$ " previo no molesta). Sin dígitos pegados."""
    return any(re.search(r"(?<![\d.,])" + re.escape(v) + r"(?!\d)", texto) for v in variantes_precio(precio))


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # la lista blanca vale para el host pedido, no para adónde redirija
        return None


_ultimo_req = [0.0]


def bajar(url):
    """Texto de la página o None. 1 req/s, timeout 15 s, UA honesto."""
    time.sleep(max(0, _ultimo_req[0] + 1 - time.time()))
    _ultimo_req[0] = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.build_opener(_SinRedireccion).open(req, timeout=15) as r:
            return r.read(MAX_BYTES).decode("utf-8", "replace")
    except (OSError, ValueError):
        return None


def gh_api(metodo, ruta, token, cuerpo=None):
    req = urllib.request.Request(
        "https://api.github.com" + ruta, method=metodo, data=json.dumps(cuerpo).encode() if cuerpo else None,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "User-Agent": UA,
                 "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


BAJAR, GH = bajar, gh_api  # los tests los reemplazan: ni red ni GitHub


def commitear(ruta, contenido, mensaje, token, repo):
    api = f"/repos/{repo}/contents/{ruta}"
    st, j = GH("GET", api, token)
    if st not in (200, 404):
        raise RuntimeError(f"GitHub GET {st}")
    cuerpo = {"message": mensaje, "content": base64.b64encode(contenido).decode()}
    if st == 200:
        cuerpo["sha"] = j["sha"]
    st, j = GH("PUT", api, token, cuerpo)
    if st not in (200, 201):
        raise RuntimeError(f"GitHub PUT {st}")
    return j["commit"]["sha"]


def fusionar(existentes, nuevas):
    """Idempotente: una fila nueva reemplaza a la de igual clave_grok."""
    k = clave_grok
    pisadas = {k(r) for r in nuevas}
    return sorted([r for r in existentes if k(r) not in pisadas] + nuevas, key=k)


def a_texto_grok(filas):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=GROK_ALM_F, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(filas)
    return buf.getvalue()


def procesar_carga(d, raiz, texto, hoy=None, ahora=None):
    """Valida, verifica, normaliza, guarda (archivo + commit) y actualiza `d` en memoria. → (http, respuesta)."""
    hoy, ahora = hoy or date.today(), ahora or datetime.now(timezone.utc)
    sello = ahora.strftime("%Y-%m-%dT%H:%M:%SZ")
    # ponytail: una carga totalmente pisada por otra deja de contar; el tope es contra abuso, no contabilidad
    if len({r["cargado"] for r in d["grok"] if r["cargado"][:10] == sello[:10]}) >= MAX_CARGAS_DIA:
        return 429, {"error": f"tope de {MAX_CARGAS_DIA} cargas por día"}
    sitios = {s["fuente"]: s["host"] for s in d["grok_sitios"]}
    filas, errores, fatal = validar_csv(texto, hoy, sitios)
    if fatal or not filas:
        return 400, {"error": fatal or "ninguna fila válida", "errores": errores}
    por_clave, duplicadas = {}, []
    for r in filas:  # duplicado exacto dentro de la carga: gana la última, pero se informa (nunca se descarta en silencio)
        if clave_grok(r) in por_clave:
            duplicadas.append({"fila": por_clave[clave_grok(r)]["_fila"], "reemplazada_por": r["_fila"], "titulo": r["titulo"]})
        por_clave[clave_grok(r)] = r
    paginas, resultado, rel = {}, [], relacionados(raiz)
    for k, r in list(por_clave.items()):
        n = normalizar.normalizar(r["titulo"], r["marca"], "", url=r["url"], pais=r["pais"])
        # los servicios (combos Shell/competencia sin producto_id) van a /api/servicios y nunca al $/L: pasan igual
        if r["tipo"] == "producto" and n["producto_id"] not in rel:
            errores.append({"fila": r["_fila"], "titulo": r["titulo"], "error": "no relacionado con YPF"})
            del por_clave[k]
            continue
        if r["url"] not in paginas:
            paginas[r["url"]] = BAJAR(r["url"])
        pag = paginas[r["url"]]
        r["verificado"] = "1" if pag and precio_en_texto(float(r["precio"]), pag) else "0"
        r["producto_id"], r["match"], r["cargado"] = n["producto_id"], n["match"], sello
        r["marca"] = r["marca"] or n["marca"] or ""
        if not r["litros"] and n["litros"]:
            r["litros"] = f"{n['litros']:g}"
        if not r["unidades"] and n["unidades"]:
            r["unidades"] = str(n["unidades"])
        resultado.append({"fila": r.pop("_fila"), "titulo": r["titulo"], "tipo": r["tipo"], "verificado": r["verificado"] == "1",
                          "producto_id": r["producto_id"], "provincia": r["provincia"], "pais": r["pais"], "moneda": r["moneda"]})
    if not por_clave:
        return 400, {"error": "ninguna fila relacionada con YPF", "errores": errores}
    token, repo = os.environ.get("GH_CARGA_TOKEN", ""), os.environ.get("GH_REPO") or "noguerafran-alt/LUBRICANTES"
    commits, fallo = [], ""
    for mes in sorted({r["fecha"][:7] for r in por_clave.values()}):
        nuevas = [r for r in por_clave.values() if r["fecha"][:7] == mes]
        d["grok_meses"][mes] = fusionar(d["grok_meses"].get(mes, []), nuevas)
        contenido = a_texto_grok(d["grok_meses"][mes])
        archivo = Path(raiz) / "data" / "grok" / f"{mes}.csv"
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_text(contenido, encoding="utf-8", newline="")
        if token and not fallo:
            msg = f"grok: carga {','.join(sorted({r['fuente'] for r in nuevas}))} {max(r['fecha'] for r in nuevas)} ({len(nuevas)} filas)"
            try:
                commits.append(commitear(f"data/grok/{mes}.csv", contenido.encode(), msg, token, repo))
            except Exception as e:  # el archivo local y la memoria ya quedaron; reintentar es idempotente
                fallo = f"no se pudo comitear ({e}): quedó en memoria y se pierde si el server reinicia; reenviá la carga"
    integrar_grok(d)
    ver = sum(x["verificado"] for x in resultado)
    resp = {"ok": len(resultado), "verificadas": ver, "no_verificadas": len(resultado) - ver, "errores": errores, "duplicadas": duplicadas,
            "filas": sorted(resultado, key=lambda x: x["fila"]), "commit": commits if token else "solo local"}
    if fallo:
        resp["error"] = fallo
    return (502 if fallo else 200), resp


MEDIA = {".mp4": "video/mp4", ".jpg": "image/jpeg"}


def pagina(index, site):
    """index.html con `__V__` = hash corto de los .js propios de site/ (no vendor/): Cloudflare cachea los .js 4 h
    aunque el server diga 60 s, así que la URL tiene que cambiar con el contenido. Se calcula por pedido (son ~100 KB)."""
    h = hashlib.sha1()
    for f in sorted([*site.glob("*.js"), *site.glob("*.mjs")]):
        h.update(f.name.encode() + f.read_bytes())
    return index.read_bytes().replace(b"__V__", h.hexdigest()[:10].encode())


def rango_bytes(n, h):
    """Header Range de un solo tramo -> (inicio, fin) inclusivos; None si no hay Range (o no se entiende: 200 completo); False si no cabe en el archivo (416)."""
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", h.strip())
    if not m or not (m[1] or m[2]):
        return None
    a, b = (n - int(m[2]), n - 1) if not m[1] else (int(m[1]), min(int(m[2]), n - 1) if m[2] else n - 1)
    return (max(a, 0), b) if 0 <= a <= b and a < n else False


class Handler(BaseHTTPRequestHandler):
    server_version = "lubricantes"
    sys_version = ""
    datos = None  # cargar()
    calc = None   # calcular()
    clave = None
    clave_carga = ""
    firma = ""    # firma_datos() de lo cargado
    raiz = RAIZ
    candado = threading.Lock()
    pais, usd, fx_fecha = "AR", False, ""  # por pedido (do_GET los fija; los handlers son por conexión)

    def enviar(self, codigo, cuerpo, tipo, extra=()):
        if "gzip" in self.headers.get("Accept-Encoding", "") and len(cuerpo) > 1024 and not tipo.startswith(("video/", "image/jpeg", "application/zip")):  # mp4 y jpg ya vienen comprimidos (y gzip rompería el Range)
            cuerpo = gzip.compress(cuerpo)
            extra = [*extra, ("Content-Encoding", "gzip")]
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        if not any(k == "Cache-Control" for k, _ in extra):
            self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Accept-Encoding, Authorization, X-API-Key")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(cuerpo)

    def json(self, codigo, obj):
        self.enviar(codigo, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        u = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/salud":
            return self.json(200, salud())
        if u.path == "/robots.txt":  # lectura abierta (decisión 2026-11-19): que al menos no la indexen
            return self.enviar(200, b"User-agent: *\nDisallow: /\n", "text/plain; charset=utf-8")
        if u.path in ("/", "/index.html"):  # solo se sirve este archivo: no hay path traversal posible
            return self.enviar(200, pagina(INDEX, SITE), "text/html; charset=utf-8")
        if u.path == "/ml-callback":  # Redirect URI de la app de ML: solo muestra la dirección para pegarla en `ml.py autorizar`
            return self.enviar(200, (SITE / "ml-callback.html").read_bytes(), "text/html; charset=utf-8", [("Cache-Control", "no-store")])
        if u.path in ("/favicon.svg", "/favicon.ico"):  # el navegador pide .ico por defecto: se le da el mismo SVG
            return self.enviar(200, (SITE / "favicon.svg").read_bytes(), "image/svg+xml", [("Cache-Control", "public, max-age=86400")])
        if u.path.endswith((".js", ".mjs", ".glb", ".mp4", ".jpg")):  # resolve + is_relative_to contra traversal
            f = (SITE / u.path.lstrip("/")).resolve()
            if f.is_file() and f.is_relative_to(SITE.resolve()):
                if f.suffix == ".glb":  # con ?v=<hash> la URL cambia si el archivo cambia: immutable; sin ella, poco cache
                    cc = "public, max-age=31536000, immutable" if q.get("v") else "public, max-age=3600"
                    return self.enviar(200, f.read_bytes(), "model/gltf-binary", [("Cache-Control", cc)])
                if f.suffix in MEDIA:  # video/foto del hero: sin ?v= no puede ser immutable; Safari exige Range para reproducir mp4
                    datos, tipo, rg = f.read_bytes(), MEDIA[f.suffix], rango_bytes(f.stat().st_size, self.headers.get("Range", ""))
                    cc = [("Cache-Control", "public, max-age=3600"), ("Accept-Ranges", "bytes")]
                    if rg is False:
                        return self.enviar(416, b"", tipo, [*cc, ("Content-Range", f"bytes */{len(datos)}")])
                    if rg:
                        return self.enviar(206, datos[rg[0]:rg[1] + 1], tipo, [*cc, ("Content-Range", f"bytes {rg[0]}-{rg[1]}/{len(datos)}")])
                    return self.enviar(200, datos, tipo, cc)
                # immutable en vendor/ (versión fijada) y con ?v=<hash> (la URL cambia si el módulo cambia); sin ?v= revalida pronto
                cc = "public, max-age=31536000, immutable" if q.get("v") or f.is_relative_to((SITE / "vendor").resolve()) else "public, max-age=60, must-revalidate"
                return self.enviar(200, f.read_bytes(), "text/javascript; charset=utf-8", [("Cache-Control", cc)])
        if not u.path.startswith("/api/"):
            return self.json(404, {"error": "no existe"})
        nombre = u.path[5:]
        if nombre == "fx":  # cotizaciones disponibles de una moneda (alimenta el selector de fecha del visor)
            mon = (q.get("moneda") or "").upper()
            if mon not in ("ARS", "BRL"):
                return self.json(400, {"error": "moneda tiene que ser ARS o BRL"})
            return self.json(200, {"moneda": mon, "cotizaciones": fx_lista(self.datos.get("fx_tabla", {}), mon)})
        pais = (q.get("pais") or "AR").upper()
        if pais not in PAISES:
            return self.json(400, {"error": f"pais inválido: {q.get('pais')!r}", "paises": list(PAISES)})
        self.pais, self.usd, self.fx_fecha = pais, q.get("usd") == "1", q.get("fx_fecha", "")
        if self.fx_fecha:
            err = fx_fecha_error(self.datos.get("fx_tabla", {}), PAISES[pais][1], self.fx_fecha)
            if err:
                return self.json(400, err)
        if nombre in ("mercado", "mercado/share", "mercado/perdidas", "mercado/filas", "macro") and pais != "AR":
            return self.json(400, {"error": "mercado y macro son solo Argentina (datos de la Secretaría de Energía y el INDEC)"})
        if nombre in ("mercado", "mercado/share", "mercado/perdidas", "mercado/filas", "macro"):
            return self.mercado(nombre, q)
        if nombre in ("provincias", "reventa", "cobertura"):
            return self.analisis(nombre, q)
        if nombre == "producto":
            return self.producto(q)
        if nombre == "indice/celdas":
            return self.celdas(q)
        if nombre == "puesto":
            return self.puesto(q)
        if nombre.startswith("bi/"):  # modelo estrella para Power BI: CSV con BOM (para que lea los acentos), sin filtro de país
            desde = q.get("desde", "")
            if desde and not RX_FECHA.fullmatch(desde):
                return self.json(400, {"error": "desde tiene que ser AAAA-MM-DD"})
            if nombre[3:] == "paquete.zip":
                return self.enviar(200, bi_paquete(self.datos, self.calc), "application/zip", [("Content-Disposition", 'attachment; filename="paquete.zip"')])
            if nombre[3:] == "indice":
                filas = bi_indice(self.calc, desde, q.get("mayoristas") == "1", pais if "pais" in q else "")
            elif nombre[3:] == "indice_competencia":
                filas = [r for r in bi_indice_competencia(self.datos, desde) if "pais" not in q or r["pais"] == pais]
            else:
                filas = bi_tabla(self.datos, nombre[3:], q)
            if filas is None:
                return self.json(404, {"error": "no existe", "tablas": TABLAS_BI + ["diccionario", "paquete.zip"]})
            return self.enviar(200, chr(0xFEFF).encode() + a_csv("bi_" + nombre[3:], filas), "text/csv; charset=utf-8")
        cp = self.calc["_paises"][pais]  # lo calculado por país; el resto (productos, fuentes, …) no depende del país
        if nombre == "vitrina":
            v = cp["vitrina_con_mayoristas" if q.get("mayoristas") == "1" else "vitrina"]
            if q.get("formato") == "csv":
                return self.enviar(200, a_csv("vitrina", aplanar_vitrina(v)), "text/csv; charset=utf-8")
            return self.salida(v)
        if nombre == "indice/pares":
            v = cp["indice/pares"]
            if q.get("formato") == "csv":
                return self.enviar(200, a_csv("indice/pares", [{**x, "pais": v["pais"], "moneda": v["moneda"], "desde": v["desde"], "hasta": v["hasta"]} for x in v["productos"]]), "text/csv; charset=utf-8")
            return self.salida(v)
        if nombre == "indice" and q.get("mayoristas") == "1":
            filas = cp["indice_con_mayoristas"]
        elif nombre in cp:
            filas = cp[nombre]
        elif nombre in self.calc and not nombre.startswith("_"):
            filas = self.calc[nombre]
        elif nombre in ("obs", "grok"):  # grok: cargas de Grok con verificado/tipo, aparte de obs
            por_mes = self.datos["meses" if nombre == "obs" else "grok_meses"]
            meses = sorted(por_mes)
            mes = q.get("mes", "")
            if not re.fullmatch(r"\d{4}-\d{2}", mes):
                return self.json(400, {"error": "falta mes=AAAA-MM", "meses": meses})
            if mes not in por_mes:
                return self.json(404, {"error": f"sin observaciones de {mes}", "meses": meses})
            filas = por_mes[mes]
        elif nombre == "serie":
            pid = q.get("p", "")
            if not any(p["producto_id"] == pid for p in self.datos["productos"]):
                return self.json(404, {"error": f"producto_id desconocido: {pid!r}"})
            filas = serie(self.datos["obs"], pid, pais)
        else:
            return self.json(404, {"error": "no existe"})
        if q.get("formato") == "csv":
            return self.enviar(200, a_csv(nombre, filas), "text/csv; charset=utf-8")
        self.salida(filas)

    def salida(self, obj):
        """JSON de la respuesta; con ?usd=1 suma los campos *_usd (conversión solo para visualizar, ver con_usd)."""
        if self.usd:
            obj = con_usd(obj, PAISES[self.pais][1], self.datos.get("fx_tabla", {}), fx_fecha=self.fx_fecha)
        self.json(200, obj)

    def analisis(self, nombre, q):
        """/api/provincias, /api/reventa y /api/cobertura: se calculan por pedido sobre `obs` (ventana de días y filtros varían)."""
        d = self.datos
        try:
            dias = int(q.get("dias") or 30)
        except ValueError:
            dias = 0
        if not 1 <= dias <= 366:
            return self.json(400, {"error": "dias tiene que ser un entero entre 1 y 366"})
        desde, hasta, err = rango_pedido(de_pais(d, self.pais), dias, q)
        if err:
            return self.json(400, {"error": err})
        pid = q.get("producto_id", "")
        marca = {p["producto_id"]: p["marca"] for p in d["productos"]}
        if pid and pid not in marca:
            return self.json(404, {"error": f"producto_id desconocido: {pid!r}"})
        csv_ = q.get("formato") == "csv"
        pais = self.pais
        if nombre == "cobertura":
            v = cobertura(d, pais)
            return self.enviar(200, a_csv("cobertura", [{**p, "pais": pais, "moneda": v["moneda"]} for p in v["productos"]]), "text/csv; charset=utf-8") if csv_ else self.salida(v)
        if nombre == "reventa":
            if not pid:
                return self.json(400, {"error": "falta producto_id (un producto de marca YPF)"})
            if marca[pid] != "YPF":
                return self.json(400, {"error": f"{pid} no es un producto YPF: /api/reventa parte de un YPF y trae sus equivalentes"})
            v = reventa(d, pid, dias, pais, desde, hasta)
            return self.enviar(200, a_csv("reventa", aplanar_reventa(v)), "text/csv; charset=utf-8") if csv_ else self.salida(v)
        fuente, may = q.get("fuente", ""), q.get("mayoristas") == "1"
        if pid:
            v = provincias(d, pid, dias, fuente, may, pais, desde, hasta)
            filas = [{**c, "producto_id": pid, "vendedores": ";".join(c["vendedores"])} for c in v["celdas"]]
        else:
            v = provincias_resumen(d, dias, fuente, may, pais, desde, hasta)
            filas = [{**c, "producto_id": p["producto_id"], "nombre": p["nombre"], "vendedores": ";".join(c["vendedores"])}
                     for p in v["productos"] for c in p["fuentes"]]
        filas = [{**f, "pais": pais, "moneda": v["moneda"]} for f in filas]
        self.enviar(200, a_csv("provincias", filas), "text/csv; charset=utf-8") if csv_ else self.salida(v)

    def celdas(self, q):
        """/api/indice/celdas (la vista 3D de Índice): 400 si `dias`/`hasta` son inválidos. Cacheado por estado de datos (`d` se reemplaza al recargar)."""
        d = self.datos
        try:
            dias = int(q.get("dias") or 30)
        except ValueError:
            dias = 0
        if not 1 <= dias <= 366:
            return self.json(400, {"error": "dias tiene que ser un entero entre 1 y 366"})
        hasta = q.get("hasta") or None
        try:
            if hasta and not RX_FECHA.fullmatch(hasta):
                raise ValueError
            hasta and date.fromisoformat(hasta)
        except ValueError:
            return self.json(400, {"error": "hasta tiene que ser una fecha AAAA-MM-DD válida"})
        k = (dias, hasta, q.get("mayoristas") == "1", self.pais)
        cache = d.setdefault("_cache_celdas", {})
        if k not in cache:
            if len(cache) >= 32:  # `hasta` lo elige quien pide: sin tope la caché crecería sin límite
                cache.clear()
            cache[k] = indice_celdas(d, *k[:2], k[2], k[3])
        v = cache[k]
        if q.get("formato") == "csv":
            filas = [{**c, "productos": ";".join(c["productos"]), "pais": v["pais"], "moneda": v["moneda"], "desde": v["desde"], "hasta": v["hasta"], "dias": v["dias"]} for c in v["celdas"]]
            return self.enviar(200, a_csv("indice_celdas", filas), "text/csv; charset=utf-8")
        self.json(200, celdas_usd(v, d.get("fx_tabla", {}), self.fx_fecha) if self.usd else v)
    def puesto(self, q):
        """/api/puesto: precio puesto por provincia (precio + envío cotizado a la capital). Solo AR; `dias` 7–366 (default 7); `metodo` opcional (domicilio|retiro|agencia)."""
        pid = q.get("producto_id", "")
        if self.pais != "AR":
            return self.json(400, {"error": "puesto es solo Argentina"})
        if not any(p["producto_id"] == pid for p in self.datos["productos"]):
            return self.json(400, {"error": f"producto_id desconocido o ausente: {pid!r}"})
        try:
            dias = int(q.get("dias") or 7)
        except ValueError:
            dias = 0
        if not 7 <= dias <= 366:
            return self.json(400, {"error": "dias tiene que ser un entero entre 7 y 366"})
        metodo = q.get("metodo") or None
        if metodo and metodo not in METODOS_PUESTO:
            return self.json(400, {"error": "metodo tiene que ser domicilio, retiro o agencia"})
        v = puesto(self.datos, pid, dias, metodo)
        if q.get("formato") == "csv":
            return self.enviar(200, a_csv("puesto", aplanar_puesto(v)), "text/csv; charset=utf-8")
        self.json(200, v)

    def producto(self, q):
        """/api/producto: la página de producto del visor y la fuente del agente de sobreprecios (400 si el producto no existe o `dias`/`umbral` son inválidos)."""
        d, pid = self.datos, q.get("producto_id", "")
        if not any(p["producto_id"] == pid for p in d["productos"]):
            return self.json(400, {"error": f"producto_id desconocido o ausente: {pid!r}"})
        try:
            dias = int(q.get("dias") or VENTANA_DIAS)
        except ValueError:
            dias = 0
        if not 1 <= dias <= 366:
            return self.json(400, {"error": "dias tiene que ser un entero entre 1 y 366"})
        umbral = None
        if q.get("umbral"):
            try:
                umbral = float(q["umbral"])
            except ValueError:
                umbral = math.nan
            if not math.isfinite(umbral):
                return self.json(400, {"error": "umbral tiene que ser un número (porcentaje de desvío contra la mediana)"})
        desde, hasta, err = rango_pedido(de_pais(d, self.pais), dias, q)
        if err:
            return self.json(400, {"error": err})
        v = producto(d, pid, dias, q.get("mayoristas") == "1", umbral, self.pais, desde, hasta)
        if q.get("formato") == "csv":
            return self.enviar(200, a_csv("producto", aplanar_producto(v)), "text/csv; charset=utf-8")
        self.salida(v)

    def mercado(self, nombre, q):
        d = self.datos
        if nombre == "macro":
            meta, ser = d["macro_meta"], d["macro_series"]
            ids = [i for i in q.get("ids", "").split(",") if i]
            if not ids:
                return self.json(200, [{"id": i, **m, "n": len(ser[i])} for i, m in meta.items()])
            falta = [i for i in ids if i not in meta]
            if falta:
                return self.json(404, {"error": f"id desconocido: {falta}", "ids": list(meta)})
            if q.get("formato") == "csv":
                return self.enviar(200, a_csv("macro", [{"id": i, **p} for i in ids for p in ser[i]]), "text/csv; charset=utf-8")
            return self.json(200, [{"id": i, **meta[i], "serie": ser[i]} for i in ids])
        if nombre == "mercado/filas":
            return self.mercado_filas(q)
        if nombre == "mercado/perdidas":
            return self.mercado_perdidas(q)
        prods = lista(q.get("producto")) or ["automotrices"]
        try:
            nom, _u = producto_multi(prods)
        except ValueError as e:
            return self.json(400, {"error": str(e), "productos": list(PRODUCTOS_SHARE)})
        lc = lista(q.get("canal"))
        canal = None if not lc else lc[0] if len(lc) == 1 else lc
        filas = filas_productos(d, prods)
        por = q.get("por", "empresa")
        if por not in ("empresa", "marca"):
            return self.json(400, {"error": f"por inválido: {por!r}", "por": ["empresa", "marca"]})
        canales = share(filas)["canales"]
        mal = [c for c in lc if c not in canales]
        if mal:
            return self.json(404, {"error": f"canal sin datos: {', '.join(mal)}", "canales": canales})
        if nombre == "mercado/share" and q.get("formato") == "csv":
            return self.enviar(200, a_csv("mercado_share", share_filas(filas, canal)), "text/csv; charset=utf-8")
        if nombre == "mercado/share" and q.get("completo") == "1":
            c = share_completo(filas, canal)
            if por == "marca":
                etiquetar(d, c, True)
            return self.json(200, {"producto": nom, "productos": prods, "canal": canal, "por": por, "meses": c["meses"], "total": c["total"], "empresas": c["empresas"]})
        if nombre == "mercado/share":
            S = share_origen(d, filas, canal)
            return self.json(200, {"producto": nom, "productos": prods, "canal": canal, "por": por, **(etiquetar(d, S) if por == "marca" else S)})
        self.json(200, self.calc["mercado"] if prods == ["automotrices"] and not canal and por == "empresa" else mercado(d, prods, canal, por))

    def mercado_perdidas(self, q):
        d = self.datos
        prods = [p for p in lista(q.get("producto")) if p != "todos"] or ["automotrices"]
        canal, prov = ([v for v in lista(q.get(k)) if v != "todos"] or None for k in ("canal", "provincia"))   # vacío o 'todos' = sin filtro
        desde, hasta, vs = (q.get(k) or None for k in ("desde", "hasta", "vs"))
        if q.get("ventana") and (desde or hasta or vs):
            return self.json(400, {"error": "ventana no se mezcla con desde/hasta/vs: usá una cosa o la otra"})
        if bool(desde) != bool(hasta) or (vs and not desde):
            return self.json(400, {"error": "el período explícito pide desde y hasta juntos (AAAA-MM); vs solo va con ellos"})
        vent = q.get("ventana") or "12m"
        try:
            minimo = float(q["min"]) if q.get("min") not in (None, "") else None
            if minimo is not None and not (minimo >= 0 and math.isfinite(minimo)):
                raise ValueError
        except ValueError:
            return self.json(400, {"error": f"min inválido: {q.get('min')!r} (número >= 0, en m3 o Ton del producto)"})
        try:
            producto_multi(prods)
        except ValueError as e:
            return self.json(400, {"error": str(e), "productos": list(PRODUCTOS_SHARE)})
        if vent not in VENTANAS:
            return self.json(400, {"error": f"ventana inválida: {vent!r}", "ventanas": list(VENTANAS)})
        filas = filas_productos(d, prods)
        for nombre, v, i in (("canal", canal, 3), ("provincia", prov, 4)):
            posibles = sorted({f[i] for f in filas})
            mal = [x for x in v or [] if x not in posibles]
            if mal:
                return self.json(404, {"error": f"{nombre} sin datos: {', '.join(mal)}", ("canales" if nombre == "canal" else "provincias"): posibles})
        try:
            r = perdidas(d, prods, canal, prov, vent, minimo, desde, hasta, vs)
        except ValueError as e:
            return self.json(400, {"error": str(e)})
        self.json(200, r)

    def mercado_filas(self, q):
        d = self.datos
        canal, prov, prod = ([v for v in lista(q.get(k)) if v != "todos"] or None for k in ("canal", "provincia", "producto"))   # listas con coma
        emp = None if q.get("empresa") in (None, "", "todos") else q["empresa"]
        if prod:
            prod = [PRODUCTOS_SHARE.get(p, p) for p in prod]
            if any(p not in {f[2] for f in d["energia"]} for p in prod):
                return self.json(400, {"error": f"producto inválido: {q.get('producto')!r}", "productos": list(PRODUCTOS_SHARE)})
        desde, hasta = q.get("desde", ""), q.get("hasta", "")
        for k, v in (("desde", desde), ("hasta", hasta)):
            if v and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v):
                return self.json(400, {"error": f"{k} tiene que ser AAAA-MM"})
        self.enviar(200, b"\xef\xbb\xbf" + a_csv("mercado_filas", filas_se(d, prod, canal, prov, emp, desde, hasta)), "text/csv; charset=utf-8")

    def do_POST(self):
        if urlsplit(self.path).path != "/api/cargar":
            return self.json(404, {"error": "no existe"})
        if not autorizado_carga(self.headers, self.clave, self.clave_carga):
            return self.json(401, {"error": "falta clave: header X-Carga-Clave (o la principal en X-API-Key)"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BYTES:
            return self.json(413, {"error": "carga demasiado grande"})
        cuerpo = self.rfile.read(n).decode("utf-8", "replace")
        tipo = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if tipo == "application/x-www-form-urlencoded":
            cuerpo = parse_qs(cuerpo).get("csv", [""])[0]
        elif tipo not in ("text/csv", "text/plain"):
            return self.json(415, {"error": "Content-Type: text/csv, text/plain o formulario con el campo csv"})
        with self.candado:
            codigo, resp = procesar_carga(self.datos, self.raiz, cuerpo)
            if resp.get("ok"):
                Handler.calc = calcular(self.datos)
        self.json(codigo, resp)


def demo():
    import shutil
    import tempfile
    import urllib.parse

    assert precio_litro({"precio": "20000", "litros": "4", "unidades": "1"}) == 5000
    assert precio_litro({"precio": "24000", "litros": "1", "unidades": "6"}) == 4000
    assert precio_litro({"precio": "20000", "litros": "4", "unidades": ""}) == 5000
    assert precio_litro({"precio": "0", "litros": "4", "unidades": "1"}) is None
    assert precio_litro({"precio": "100", "litros": "", "unidades": "1"}) is None

    raiz = Path(tempfile.mkdtemp())
    (raiz / "seed").mkdir()
    (raiz / "data" / "obs").mkdir(parents=True)
    (raiz / "seed" / "productos.csv").write_text(
        ",".join(PRODUCTOS_F) + "\n"
        "ypf-a-10w40,YPF,Elaion,TS 1040,pcmo,10W-40,,,,,,,,confirmado\n"
        "shell-b-10w40,Shell,Helix,HX7,pcmo,10W-40,,,,,,,,confirmado\n"
        "gulf-c-15w40,Gulf,Max,X,pcmo,15W-40,,,,,,,,inferido\n", encoding="utf-8")
    (raiz / "seed" / "equivalencias.csv").write_text(
        ",".join(EQUIV_F) + "\n1,ypf-a-10w40,shell-b-10w40,match_total,api,confirmada,x\n", encoding="utf-8")
    (raiz / "seed" / "grok_sitios.csv").write_text(
        ",".join(SITIOS_F) + "\ngrok_helix,www.helixturno.com.ar,Combos\ngrok_otro,otro.com.ar,Otro\n", encoding="utf-8")
    obs = [  # fecha,fuente,precio,litros,unidades,producto_id
        ("2026-11-01", "sepa", "4000", "1", "1", "ypf-a-10w40"),
        ("2026-11-01", "sepa", "4400", "1", "1", "ypf-a-10w40"),  # otra sucursal: mediana 4200
        ("2026-11-01", "sepa", "5000", "1", "1", "shell-b-10w40"),
        ("2026-11-02", "sepa", "4400", "1", "1", "ypf-a-10w40"),
        ("2026-11-02", "sepa", "16000", "4", "1", "ypf-a-10w40"),  # mismo día, bidón: 4000/L
        ("2026-11-02", "vtex_carrefour", "6000", "1", "1", "shell-b-10w40"),
        ("2026-11-02", "sepa", "3000", "1", "1", "gulf-c-15w40"),  # sin YPF en 15W-40
        ("2026-11-02", "vtex_easy", "9999", "1", "1", ""),
        ("2026-11-03", "vtex_easy", "9999", "1", "1", ""),
        ("2026-11-02", "shopify_datri", "2000", "1", "12", "ypf-a-10w40"),  # mayorista: caja 12x1 L = 166,67 $/L
    ]
    with open(raiz / "data" / "obs" / "2026-11.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, OBS_F, restval="")
        w.writeheader()
        for k_, (fe, fu, pr, li, un, pid) in enumerate(obs):
            w.writerow({"fecha": fe, "fuente": fu, "precio": pr, "litros": li, "unidades": un, "producto_id": pid, "vendedor": f"c{k_}",  # un aviso por fila
                        "titulo": "aceite raro", "match": "ean" if pid else "none"})
    (raiz / "data" / "fuentes.csv").write_text(
        ",".join(FUENTES_F) + "\n"
        "2026-11-01,vtex_carrefour,200,10,8,2,0,\n"
        "2026-11-02,vtex_carrefour,200,10,8,2,0,\n"
        "2026-11-03,vtex_carrefour,403,0,0,0,0,HTTP 403\n"
        "2026-11-03,ml,,0,0,0,0,sin token\n", encoding="utf-8")

    # precio puesto: envíos de prueba (en el tmp, nunca en data/ del repo)
    (raiz / "data" / "envios").mkdir()
    shutil.copy(RAIZ / "seed" / "cp_capitales.csv", raiz / "seed" / "cp_capitales.csv")
    ENV_F = "fecha,capturado,fuente,url,producto_id,litros,unidades,precio,cp_destino,provincia_destino,costo_envio,metodo,plazo_h,estado,deposito".split(",")
    A_, B_ = "https://articulo.mercadolibre.com.ar/MLA-1", "https://articulo.mercadolibre.com.ar/MLA-2"
    e_ = lambda fe, u, pv, co, me, es="ok", pr="16000": dict(fecha=fe, fuente="ml", url=u, producto_id="ypf-a-10w40", litros="4", unidades="1", precio=pr,
                                                            cp_destino="x", provincia_destino=pv, costo_envio=co, metodo=me, plazo_h="", estado=es, deposito="")
    ENV = [e_("2026-11-20", A_, "AR-X", "0", "domicilio"), e_("2026-11-20", B_, "AR-X", "6000", "agencia", pr="20000"), e_("2026-11-20", B_, "AR-X", "4000", "domicilio", pr="20000"),
           e_("2026-11-16", A_, "AR-X", "100", "domicilio", pr="1"),     # la misma cotización más vieja: gana la del 20
           e_("2026-11-20", A_, "AR-V", "", "", "sin_cotizacion"), e_("2026-11-19", B_, "AR-R", "", "", "no_envia"),
           e_("2026-11-10", A_, "AR-S", "50", "domicilio"),                # fuera de la ventana de 7 días: no se arrastra
           e_("2026-11-18", B_, "AR-N", "1000", "domicilio", pr="20000"), e_("2026-11-20", B_, "AR-N", "", "", "sin_cotizacion")]  # ok del 18 + hueco del 20: cuenta el ok
    with open(raiz / "data" / "envios" / "2026-11.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ENV_F)
        w.writeheader()
        w.writerows(ENV)

    # datos sintéticos de mercado: 13 meses de automotrices (YPF, Shell, A..F, Z1, Z2) con Shell ausente en 2026-03
    (raiz / "data" / "macro").mkdir()
    ms = [mes_mas("2025-09", k) for k in range(13)]
    AP, LA, E_ = "Al Público", "Lubricantes automotrices(m3)", []
    for m in ms:
        E_ += [(m, "YPF", LA, AP, "Córdoba", 60), (m, "YPF", LA, AP, "Salta", 60 if m == "2025-09" else 40)]
        E_ += [(m, "Shell/Raízen", LA, AP, "Córdoba", 50)] * (m != "2026-03")
        E_ += [(m, e, LA, AP, "Córdoba", v) for e, v in zip("ABCDEF", (10, 9, 8, 7, 6, 5))]
        E_ += [(m, "Z1", LA, AP, "Córdoba", 1), (m, "Z2", LA, AP, "Córdoba", 1)]
        E_ += [(m, "Todas", "Gasoil Grado 2(m3)", "Transporte de Carga", "Todas", 1000)] * (m != "2026-03")  # 2026-03: mes sin fila
    E_ += [("2026-09", "YPF", LA, "Agro", "Córdoba", 10), ("2026-09", "Shell/Raízen", LA, AP, "Jujuy", 5), ("2026-09", "YPF", "Grasas(Ton)", AP, "Córdoba", 7),
           ("2026-09", "YPF", "Lubricantes industriales(m3)", "Agro", "Córdoba", 30), ("2026-09", "Shell/Raízen", "Lubricantes industriales(m3)", "Agro", "Córdoba", 10)]
    with open(raiz / "data" / "macro" / "energia.csv", "w", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\n").writerows([("mes", "empresa", "producto", "canal", "provincia", "cantidad"), *E_])
    (raiz / "data" / "macro" / "series.csv").write_text(
        "fecha,id,valor,signo\n2026-06-01,A,1.5,*\n2026-07-01,A,,...\n2026-08-01,A,,-\n2026-08-01,B,7,\n", encoding="utf-8")
    (raiz / "seed" / "marcas_empresas.csv").write_text(
        "marca,empresa_se,desde,hasta,estado,evidencia,fuente_url,nota\nYPF,YPF,,,declara,confirmada,,\nShell,Shell/Raízen,,,declara,confirmada,,\nCastrol,PAE/Axion,2019,,declara (dentro de PAE/Axion),confirmada,,\nMobil,Esso (hoy PAE/Axion),,2018,sin dato desde 2018,inferida,,\nPuma,(no declara),,,sin dato,confirmada,,\nGulf,Gulf,2012-02,2023-01,dejó de declarar,confirmada,,\n", encoding="utf-8")
    (raiz / "seed" / "macro_series.csv").write_text(
        "id,nombre,grupo,frec,unidad,fuente\nA,Serie A,liviano,M,u,INDEC\nB,Serie B,precios,M,u,BCRA\nC,Serie C,agro,M,u,INDEC\n", encoding="utf-8")
    with open(raiz / "data" / "fuentes.csv", "a", encoding="utf-8") as f:
        f.write("2026-11-02,macro_series,200,3,3,0,0,,0\n2026-11-03,macro_series,200,3,0,0,0,sin datos,0\n2026-10-29,casa,,5,5,0,0,,0\n2026-10-30,casa,,5,4,0,0,fallaron: sepa,0\n")

    # avisos de fuentes: alerta/motivo por cadencia (casos del 2026-11-19)
    def _av(extra, hoy=date(2026, 11, 19), grok=()):
        base = {"fuentes": [], "grok": list(grok), "grok_sitios": []}
        for x in extra:
            base["fuentes"].append({**dict.fromkeys(FUENTES_F, ""), "http": "200", "n_items": "5", "n_con_precio": "0", "n_sin_stock": "5",
                                    "n_sin_match": "0", "n_descartados": "0", **dict(zip(("fecha", "fuente", "error"), x))})
        return {r["fuente"]: r for r in fuentes(base, hoy)}
    assert not _av([("2026-11-19", "vtex_x", "")])["vtex_x"]["alerta"]   # todo sin stock pero responde bien: no es falla
    assert "vtex_jumbo" not in _av([("2026-11-03", "vtex_jumbo", ""), ("2026-11-19", "vtex_easy", "")])   # dada de baja: ni fila ni alerta
    g_ = {"fecha": "2026-10-01", "fuente": "grok_helix", "cargado": "2026-10-01T10:00", "producto_id": "", "provincia": "", "pais": "AR", "moneda": "ARS"}
    assert not _av([("2026-11-19", "helix_api", "")], grok=[dict(g_, fecha="2026-11-04")])["grok_helix"]["alerta"]
    h_ = _av([("2026-11-19", "helix_api", "")], grok=[g_])["grok_helix"]   # 49 días: alertaría, pero helix_api lo cubre
    assert not h_["alerta"] and h_["aviso"] == "cubierto por helix_api", h_
    assert _av([("2026-11-17", "helix_api", "")], grok=[g_])["grok_helix"]["alerta"]   # helix_api atrasada no cubre
    assert CUBIERTA["grok_motoracing"] == "presta_motoracing" and "presta_motoracing" in NOMBRE_FUENTE and nombre_fuente({}, "tn_comprarmarket").endswith("(mayorista)")
    assert CUBIERTA["grok_tiendaneumaticos"] == CUBIERTA["grok_daytona"] == "vtex_daytona" and CUBIERTA["grok_allende"] == "woo_allende"
    assert not {f["fuente"] for f in fuentes_grok({"grok": [dict(g_, fuente="woo_allende"), dict(g_, fuente="vtex_daytona")], "grok_sitios": []}, date.today())}  # escriben en data/grok pero su estado es el de fuentes.csv
    s_ = _av([("2026-11-05", "macro_x", ""), ("2026-11-19", "macro_series", "")])
    assert not s_["macro_x"]["alerta"] and s_["macro_x"]["dias_sin_datos"] == 0, s_["macro_x"]   # sin fila propia hace 14 días, macro_series al día
    assert _av([("2026-11-05", "macro_x", ""), ("2026-11-17", "macro_series", "")])["macro_x"]["alerta"]
    assert _av([("2026-11-18", "macro_x", "HTTP 500"), ("2026-11-19", "macro_series", "")])["macro_x"]["alerta"]   # falla propia vigente
    m92 = "macro_92_2_tipo_cambiion_0_0_21_24"
    assert not _av([("2026-11-05", m92, "HTTP 500"), ("2026-11-19", "macro_series", ""), ("2026-11-19", "fx_bcra", "")])[m92]["alerta"]   # cubierta por fx_bcra
    e_ = [("2026-11-05", "macro_energia", ""), ("2026-11-18", "macro_energia", "URLError: timed out")]   # error de la Action, ruta que ya no corre
    assert not _av(e_)["macro_energia"]["alerta"] and not _av([("2026-11-05", "macro_energia", "")])["macro_energia"]["alerta"]
    assert _av([("2026-09-20", "macro_energia", "")])["macro_energia"]["alerta"]   # bajada de hace 60 días
    assert _av([("2026-11-05", "macro_energia", ""), ("2026-11-19", "casa", "fallaron: sepa, energia")])["macro_energia"]["alerta"]
    assert not _av([("2026-11-05", "macro_energia", ""), ("2026-11-19", "casa", "fallaron: sepa")])["macro_energia"]["alerta"]
    assert not _av([("2026-11-05", "macro_energia", ""), ("2026-11-04", "casa", "fallaron: energia")])["macro_energia"]["alerta"]
    assert _av([("2026-11-19", "vtex_easy", "HTTP 403")])["vtex_easy"]["alerta"] and _av([("2026-11-16", "vtex_easy", "")])["vtex_easy"]["alerta"]
    assert not _av([("2026-11-19", "vtex_easy", "")])["vtex_easy"]["alerta"]

    d = cargar(raiz)
    c = calcular(d, hoy=date(2026, 11, 3))

    u = {(r["producto_id"], r["fuente"], r["litros"]): r for r in c["ultimo"]}
    assert u[("ypf-a-10w40", "sepa", 1.0)]["fecha"] == "2026-11-02"
    assert u[("ypf-a-10w40", "sepa", 1.0)]["precio_litro"] == 4400
    assert u[("ypf-a-10w40", "sepa", 4.0)]["precio_litro"] == 4000
    assert u[("shell-b-10w40", "sepa", 1.0)]["fecha"] == "2026-11-01"  # no se arrastra al día siguiente
    assert len(c["ultimo"]) == 6 and u[("ypf-a-10w40", "shopify_datri", 1.0)]["precio_litro"] == round(2000 / 12, 2)

    i = {(r["fecha"], r["sae"], r["marca"]): r for r in c["indice"]}
    assert i[("2026-11-01", "10W-40", "YPF")]["indice"] == 100
    assert i[("2026-11-01", "10W-40", "Shell")]["indice"] == round(5000 / 4200 * 100, 1)
    assert i[("2026-11-02", "10W-40", "YPF")]["mediana_litro"] == 4200  # mediana de 4400 y 4000; el mayorista no entra
    im = {(r["fecha"], r["sae"], r["marca"]): r for r in c["indice_con_mayoristas"]}
    assert (im[("2026-11-02", "10W-40", "YPF")]["mediana_litro"], im[("2026-11-02", "10W-40", "YPF")]["n"]) == (4200, 4)  # el 166,67 del mayorista entra al flag pero la sanidad (cuerdos) lo saca
    assert i[("2026-11-02", "10W-40", "YPF")]["n"] == 4 and i[("2026-11-01", "10W-40", "YPF")]["n"] == 2  # n = avisos (ventana de 3 días: el 02 trae también los del 01)
    assert i[("2026-11-02", "10W-40", "Shell")]["indice"] == round(5500 / 4200 * 100, 1)  # Shell: 5000 del 01 (dentro de la ventana) y 6000 del 02
    assert ("2026-11-04", "10W-40", "YPF") not in i and ("2026-11-03", "10W-40", "YPF") not in i  # sin filas ese día no se inventa; la ventana solo arrastra desde días con datos
    assert i[("2026-11-02", "15W-40", "Gulf")]["indice"] is None  # sin YPF → vacío

    # el índice de una fecha == /api/indice/celdas?dias=3&hasta=<fecha>: misma definición de aviso, ventana y sanidad
    for may_, filas_ in ((False, c["indice"]), (True, c["indice_con_mayoristas"])):
        cel_ = {(x["segmento"], x["sae"], x["marca"]): (x["mediana_litro"], x["n"], x["indice"]) for x in indice_celdas(d, VENTANA_DIAS, "2026-11-02", may_)["celdas"]}
        assert cel_ and cel_ == {(x["segmento"], x["sae"], x["marca"]): (x["mediana_litro"], x["n"], x["indice"]) for x in filas_ if x["fecha"] == "2026-11-02"}
    s = serie(d["obs"], "ypf-a-10w40")
    assert [(r["fecha"], r["precio_litro"]) for r in s if r["fuente"] == "sepa"] == [("2026-11-01", 4200), ("2026-11-02", 4200)]

    f = {r["fuente"]: r for r in c["fuentes"]}
    assert f["vtex_carrefour"]["error"] == "HTTP 403" and f["vtex_carrefour"]["ultimo_ok"] == "2026-11-02"
    assert f["vtex_carrefour"]["dias_sin_datos"] == 1
    assert f["ml"]["ultimo_ok"] is None and f["ml"]["dias_sin_datos"] is None
    assert f["casa"]["dias_sin_correr"] == 4 and f["casa"]["dias_sin_datos"] == 5 and f["vtex_carrefour"]["dias_sin_correr"] == 0  # casa: contra la última fila, con o sin error

    assert len(c["sin_match"]) == 1 and c["sin_match"][0]["veces"] == 2 and c["sin_match"][0]["ultima"] == "2026-11-03"
    assert c["equivalencias"][0]["comp_nombre"] == "HX7"
    assert a_csv("indice", c["indice"]).decode().startswith("fecha,segmento,sae,marca,mediana_litro,n,indice,pais,moneda\n")
    assert a_csv("ultimo", []).decode() == "producto_id,fuente,litros,fecha,precio,precio_litro,n,url,verificado,pais,moneda\n"

    # ---------- vitrina: YPF vs competencia (sin red ni archivos) ----------
    P = lambda i, m, **k: {**dict.fromkeys(PRODUCTOS_F, ""), "producto_id": i, "marca": m, "linea": "L", "nombre": i, **k}
    E = lambda c, t, y="ypf-a": {"ypf_id": y, "comp_id": c, "tipo": t, "evidencia": "inferida"}
    O = lambda f, fu, pid, precio, litros="1", un="1", url="", **k: {**dict.fromkeys(OBS_F, ""), "fecha": f, "fuente": fu, "producto_id": pid,
                                                                      "precio": precio, "litros": litros, "unidades": un, "url": url or f"u-{fu}-{pid}-{precio}", **k}
    dv = {"productos": [P("ypf-a", "YPF"), P("ypf-b", "YPF"), P("ypf-c", "YPF"), P("shell-s", "Shell"), P("gulf-g", "Gulf"), P("motul-m", "Motul")],
          "equivalencias": [E("shell-s", "match_total"), E("gulf-g", "no_equivalente"), E("motul-m", "match_parcial"), E("shell-s", "match_parcial", "ypf-c")],
          "imagenes": [{"producto_id": "ypf-a", "url": "https://i/a.jpg", "fuente": "ypf_oficial", "fecha": "x"},
                       {"producto_id": "shell-s", "url": "https://i/s.jpg", "fuente": "ml", "fecha": "x"}],
          "obs": [O("2026-11-05", "sepa", "ypf-a", "4000", url="a1"), O("2026-11-05", "vtex_easy", "ypf-a", "20000", "4", url="a2", vendedor="Easy"),
                  O("2026-11-04", "vtex_easy", "ypf-a", "99999", "4", url="a2", vendedor="Easy"),   # mismo aviso, más viejo: lo pisa el de hoy
                  O("2026-11-05", "shopify_datri", "ypf-a", "36000", "1", "12", url="a3"),         # mayorista: caja 12x1 L = 3000 $/L
                  O("2026-11-05", "ml", "ypf-a", "4000", "1", "12", url="a8"),                     # caja leída como 12 L: 333 $/L, fuera de sanidad
                  O("2026-11-05", "grok_helix", "ypf-a", "1000", url="a4", verificado="0"),         # Grok sin verificar
                  O("2026-11-01", "sepa", "ypf-a", "1", url="a5"),                                 # fuera de la ventana de 3 días
                  O("2026-11-05", "sepa", "ypf-a", "", url="a6"),                                  # sin precio
                  O("2026-11-05", "sepa", "ypf-a", "5000", litros="", url="a7"),                   # sin litros: no hay $/L
                  O("2026-11-03", "tn_spch", "ypf-c", "8000", url="c1"),                           # Tiendanube rota: de hace 2 días entra
                  O("2026-11-05", "ml", "shell-s", "6000", url="s1"), O("2026-11-05", "vtex_jumbo", "shell-s", "7000", url="s2"),
                  O("2026-11-05", "ml", "gulf-g", "1000", url="g1"),
                  O("2026-11-05", "ml", "motul-m", "80000", url="m1"),                             # 80000 $/L vs YPF 4500: fuera de rango
                  O("2026-11-05", "ml", "", "10", url="x1")]}
    vi = vitrina(dv)
    pv = {p["producto_id"]: p for p in vi["productos"]}
    assert vi["fecha"] == "2026-11-05" and [p["producto_id"] for p in vi["productos"]] == ["ypf-a", "ypf-c", "ypf-b"]  # con precio primero, por n
    ya = pv["ypf-a"]["ypf"]
    sp = specs({"api": "SP", "oem": "A 1; B 2;", "acea": " ", "verificado": "inferido"})
    assert sp["oem"] == ["A 1", "B 2"] and sp["acea"] is None and sp["jaso"] is None and sp["api"] == "SP" and specs({})["oem"] == []
    assert pv["ypf-a"]["specs"]["sae"] is None and pv["ypf-a"]["competencia"]["equivalentes"][0]["specs"]["oem"] == []
    assert (ya["n"], ya["promedio_litro"], ya["min_litro"], ya["max_litro"], ya["mediana_litro"]) == (2, 4500, 4000, 5000, 4500), ya
    assert ya["mas_barato"] == {"fuente": "sepa", "vendedor": None, "precio": 4000.0, "litros": 1.0, "precio_litro": 4000, "url": "a1"}, ya["mas_barato"]
    assert (ya["presentacion_comun_l"], ya["promedio_presentacion"]) == (1.0, 4000)                 # empate 1 L / 4 L: gana la chica
    assert ya["por_fuente"] == [{"fuente": "sepa", "n": 1, "promedio_litro": 4000}, {"fuente": "vtex_easy", "n": 1, "promedio_litro": 5000}]

    # respaldo de ML: Grok sin verificar cuenta solo el día en que `ml` no tiene obs; otras grok_* nunca
    G = lambda fu, f, pr, u: {**dict.fromkeys(GROK_ALM_F, ""), "fecha": f, "fuente": fu, "url": u, "titulo": u, "precio": pr, "litros": "1", "unidades": "1",
                              "tipo": "producto", "verificado": "0", "producto_id": "ypf-b", "cargado": "T"}
    dr = {**dv, "obs_base": [O("2026-11-05", "ml", "ypf-b", "5000", url="m5")],
          "grok_meses": {"2026-11": [G("grok_mercadolibre", "2026-11-05", "9000", "r1"), G("grok_mercadolibre", "2026-11-06", "7000", "r2"),
                                     G("grok_mercadolibre_www", "2026-11-06", "7200", "r3"), G("grok_helix", "2026-11-06", "6000", "r4")]}}
    integrar_grok(dr)
    gv = {r["url"]: r["verificado"] for r in dr["obs"] if r["url"] in ("r1", "r2", "r3", "r4")}
    assert gv == {"r1": "0", "r2": "respaldo", "r3": "respaldo", "r4": "0"}, gv  # r1: ese día ml sí tuvo obs; r4: otra fuente
    assert sorted(r["fuente"] for r in dr["obs"] if r.get("verificado") == "respaldo") == ["grok_mercadolibre", "grok_mercadolibre_www"]
    rr = {r["url"]: r for r in dr["obs"]}
    assert [r["url"] for _, r in _validos([{**rr[u], "pl": precio_litro(rr[u])} for u in ("r1", "r2", "r3", "r4")], False)] == ["r2", "r3"]
    assert ultimo([rr["r2"]])[0]["verificado"] == "respaldo" and _celda([{**rr["r2"], "pl": 7000.0}])["verificado"] == "respaldo"
    fg = {f["fuente"]: f for f in fuentes_grok({**dr, "grok": dr["obs"], "grok_sitios": []}, date(2026, 11, 24))}
    assert "respaldo" in fg["grok_mercadolibre"]["nota"] and "respaldo" in fg["grok_mercadolibre_www"]["nota"]
    assert "respaldo" in fuentes_grok({"grok": [], "grok_sitios": [{"fuente": "grok_mercadolibre"}]}, date(2026, 11, 24))[0]["nota"]
    ca = pv["ypf-a"]["competencia"]
    assert (ca["n"], ca["promedio_litro"], ca["min_litro"], ca["max_litro"]) == (2, 6500, 6000, 7000)  # el no_equivalente (1000) no promedia
    assert pv["ypf-a"]["dif_pct"] == round((6500 / 4500 - 1) * 100, 1) == 44.4
    eqa = {e["producto_id"]: e for e in ca["equivalentes"]}
    assert [e["producto_id"] for e in ca["equivalentes"]] == ["shell-s", "gulf-g", "motul-m"]     # los que no promedian, al final
    assert eqa["gulf-g"]["en_promedio"] is False and eqa["gulf-g"]["n"] == 1 and eqa["gulf-g"]["promedio_litro"] == 1000
    assert eqa["shell-s"]["imagen"] == "https://i/s.jpg" and eqa["shell-s"]["mas_barato"]["fuente"] == "ml" and eqa["gulf-g"]["imagen"] is None
    assert eqa["motul-m"]["n"] == 1 and eqa["motul-m"]["en_promedio"] is False and eqa["motul-m"]["excluido"] == "fuera_de_rango"
    assert eqa["gulf-g"]["excluido"] == "no_equivalente" and eqa["shell-s"]["excluido"] is None
    assert vitrina({**dv, "obs": [o for o in dv["obs"] if o["url"] != "m1"]})["productos"][0]["competencia"]["equivalentes"][1]["mas_barato"] is None  # sin datos: null, no 0
    assert (pv["ypf-a"]["imagen"], pv["ypf-a"]["imagen_fuente"], pv["ypf-b"]["imagen"], pv["ypf-b"]["imagen_fuente"]) == ("https://i/a.jpg", "ypf_oficial", None, None)
    yb = pv["ypf-b"]
    assert yb["ypf"]["n"] == 0 and yb["ypf"]["promedio_litro"] is None and yb["ypf"]["mas_barato"] is None and yb["ypf"]["por_fuente"] == []
    assert yb["ypf"]["presentacion_comun_l"] is None and yb["competencia"]["n"] == 0 and yb["dif_pct"] is None and yb["competencia"]["equivalentes"] == []
    assert pv["ypf-c"]["ypf"]["promedio_litro"] == 8000 and pv["ypf-c"]["competencia"]["promedio_litro"] == 6500  # el mismo Shell sirve a dos YPF
    assert pv["ypf-c"]["dif_pct"] == round((6500 / 8000 - 1) * 100, 1) == -18.8
    assert "shell-s" not in pv   # solo se listan productos YPF
    vm = {p["producto_id"]: p for p in vitrina(dv, mayoristas=True)["productos"]}
    assert vm["ypf-a"]["ypf"]["n"] == 3 and vm["ypf-a"]["ypf"]["min_litro"] == 3000 and vm["ypf-a"]["ypf"]["mas_barato"]["fuente"] == "shopify_datri"
    assert vm["ypf-a"]["ypf"]["mas_barato"]["litros"] == 12.0 and vm["ypf-a"]["ypf"]["mas_barato"]["precio"] == 36000.0
    vv = vitrina({**dv, "obs": []})
    assert vv["fecha"] is None and len(vv["productos"]) == 3 and all(p["ypf"]["promedio_litro"] is None and p["dif_pct"] is None for p in vv["productos"])
    # /api/indice/celdas: mismos avisos y sanidad que la vitrina (3 días); cada celda lleva los $/L de sus avisos
    ic = indice_celdas(dv, 3)
    cd_ = {c["marca"]: c for c in ic["celdas"]}
    assert (ic["desde"], ic["hasta"], ic["moneda"]) == ("2026-11-03", "2026-11-05", "ARS") and list(cd_) == ["Gulf", "Motul", "Shell", "YPF"]
    assert cd_["YPF"]["n"] == vi["productos"][0]["ypf"]["n"] + pv["ypf-c"]["ypf"]["n"] and cd_["YPF"]["precios_litro"] == [4000, 5000, 8000]   # = los avisos de la vitrina (ypf-a: 2, ypf-c: 1)
    assert cd_["YPF"]["indice"] == 100 and cd_["Shell"]["indice"] == 130 and cd_["Shell"]["productos"] == ["shell-s"] and cd_["YPF"]["fecha_min"] == "2026-11-03"
    assert all(len(c["precios_litro"]) == c["n"] for c in ic["celdas"]) and all(c["mediana_litro"] == median(c["precios_litro"]) for c in ic["celdas"])
    assert indice_celdas(dv, 3, mayoristas=True)["celdas"][-1]["n"] == 4 and indice_celdas(dv, 1, "2026-11-03")["celdas"][0]["marca"] == "YPF"   # mayorista con flag; ventana de un día pedida
    assert [c["indice"] for c in indice_celdas({**dv, "obs": [o for o in dv["obs"] if o["fuente"] != "sepa"]}, 3)["celdas"] if c["marca"] != "YPF"][0] is not None   # YPF sigue por easy
    assert indice_celdas({**dv, "obs": [O("2026-11-05", "sepa", "ypf-a", "5000", litros="", url="z")]}, 3)["celdas"] == []   # solo avisos sin litros: sin celda, sin error
    sin_ypf = indice_celdas({**dv, "obs": [o for o in dv["obs"] if o["producto_id"] in ("shell-s", "gulf-g")]}, 3)
    assert sin_ypf["celdas"] and all(c["indice"] is None for c in sin_ypf["celdas"])   # sin YPF no se calcula índice
    assert indice_celdas({**dv, "obs": []})["celdas"] == [] and indice_celdas(dv, 3, pais="BR")["celdas"] == []   # sin datos: ni barras ni ceros; país aparte
    # envases de menos de 0,5 L: fuera de los tres índices, con su motivo; siguen en obs y en la vitrina
    sachet = O("2026-11-05", "sepa", "ypf-a", "100", litros="0.1", url="sx")
    dsx = {**dv, "obs": dv["obs"] + [sachet]}
    assert indice_celdas(dsx, 3)["celdas"] == ic["celdas"] and indice_celdas(dsx, 3)["sin_dato"] == [] and indice(dsx) == indice(dv)   # un sachet más no mueve ninguna celda
    solo = indice_celdas({**dv, "obs": [O("2026-11-05", "sepa", "shell-s", "500", litros="0.1", url="sy")]}, 3)
    assert solo["celdas"] == [] and solo["sin_dato"] == [{"segmento": "", "sae": "", "marca": "Shell", "n_chicos": 1, "motivo": MOTIVO_CHICOS}], solo["sin_dato"]
    assert indice({**dv, "obs": [O("2026-11-05", "sepa", "shell-s", "500", litros="0.1", url="sy")]}) == []
    ip = indice_pares(dv)
    assert {x["producto_id"]: x["indice"] for x in ip["productos"]} == {k: v["indice"] for k, v in indices_30d(dv).items()} and ip["dias"] == 30
    assert all((x["motivo"] is None) == (x["indice"] is not None) for x in ip["productos"]) and indice_pares(dsx) == ip   # sin índice = con motivo; el sachet no lo cambia
    ips = {x["producto_id"]: x for x in indice_pares({**dv, "obs": [sachet]})["productos"]}
    assert ips["ypf-a"]["indice"] is None and ips["ypf-a"]["motivo"] == "YPF: " + MOTIVO_CHICOS and ips["ypf-b"]["motivo"] == "sin avisos de YPF en la ventana"
    ipc = {x["producto_id"]: x for x in indice_pares({**dv, "obs": [o for o in dv["obs"] if o["producto_id"] == "ypf-a"] + [O("2026-11-05", "sepa", "shell-s", "500", litros="0.1", url="sy")]})["productos"]}
    assert ipc["ypf-a"]["indice"] is None and ipc["ypf-a"]["motivo"] == "competencia: " + MOTIVO_CHICOS, ipc["ypf-a"]
    assert any(r["litros"] == "0.1" for r in dsx["obs"]) and vitrina(dsx)["productos"][0]["ypf"]["n"] == vitrina(dv)["productos"][0]["ypf"]["n"] + 1   # la vitrina sí lo cuenta
    ux_ = celdas_usd(ic, {("ARS", "2026-11-05"): (1000.0, "x")})
    assert ux_["celdas"][-1]["mediana_litro_usd"] == 5 and ux_["celdas"][-1]["precios_litro_usd"] == [4, 5, 8] and ux_["celdas"][-1]["fx_fecha"] == "2026-11-05"
    assert celdas_usd(ic, {})["celdas"][0]["precios_litro_usd"] is None and celdas_usd(ic, {})["celdas"][0]["mediana_litro_usd"] is None   # sin cotización ese día: null, no se arrastra
    assert a_csv("indice_celdas", [{**cd_["YPF"], "productos": "ypf-a;ypf-c"}]).decode().startswith("segmento,sae,marca,mediana_litro,indice,n,fecha_min,fecha_max,productos,pais,moneda,desde,hasta,dias\n,,YPF,5000.0,100.0,3,")
    fl = aplanar_vitrina(vi)
    assert len(fl) == 3 and fl[0]["ypf_promedio_litro"] == 4500 and fl[0]["n_equivalentes"] == 3 and fl[2]["ypf_mas_barato_fuente"] is None
    assert a_csv("vitrina", fl).decode().startswith("fecha,producto_id,nombre,linea,segmento,sae,base,imagen,imagen_fuente,ypf_n,")

    # ---------- mercado: signos, share, interanual, deflactor, demanda potencial (sin red) ----------
    assert punto("f", "", "") == {"fecha": "f", "valor": None, "signo": "..."}          # null sin signo → '...', nunca 0
    assert punto("f", "", "-") == {"fecha": "f", "valor": 0.0, "signo": "-"}            # '-' es el único cero
    assert punto("f", "", "s")["valor"] is None and punto("f", "5", "*") == {"fecha": "f", "valor": 5.0, "signo": "*"}
    assert punto("f", float("nan"), "")["valor"] is None
    assert var_ia([punto("2025-07-01", 100), punto("2026-07-01", 110)]) == 10.0
    assert var_ia([punto("2025-07-01", ""), punto("2026-07-01", 110)]) is None and var_ia([punto("2025-07-01", 100), punto("2026-07-01", "")]) is None
    assert var_ia([punto("2025-06-01", 100), punto("2026-07-01", 110)]) is None and var_ia([punto("2025-07-01", 0), punto("2026-07-01", 1)]) is None
    assert var_ia([]) is None
    assert mes_mas("2025-11", 3) == "2026-02" and mes_mas("2026-01", -1) == "2025-12"
    sh = d["energia_por_producto"]["Lubricantes automotrices(m3)"]
    S = share(sh)
    assert len(S["meses"]) == 36 and S["meses"][-1] == "2026-09" and S["total"][0] is None and S["total"][-1] == 212 and S["total"][-2] == 197
    for i, tot_i in enumerate(S["total"]):                                               # share suma 1 en cada mes con dato
        assert tot_i is None or abs(sum(e["serie"][i] or 0 for e in S["empresas"]) - 1) < 1e-4, i
    assert [e["empresa"] for e in S["empresas"]] == ["YPF", "Shell/Raízen", "A", "B", "C", "D", "E", "Otras"]
    ey = S["empresas"][0]
    assert ey["ultimo"] == round(110 / 212, 6) and ey["hace12"] == round(120 / 217, 6) and ey["volumen_ultimo"] == 110
    assert ey["var_pp"] == round((110 / 212 - 120 / 217) * 100, 2) and ey["serie"][0] is None
    es = S["empresas"][1]
    assert es["serie"][-7] is None and es["serie"][-8] is not None and es["volumen_ultimo"] == 55  # 2026-03 sin fila de Shell: null, no 0
    assert ey["volumen"][-1] == 110 and ey["volumen"][0] is None and len(ey["volumen"]) == 36 and es["volumen"][-7] is None and es["volumen"][-1] == 55
    assert all((e["volumen"][i] is None) == (e["serie"][i] is None) for e in S["empresas"] for i in range(36))
    assert S["empresas"][-1]["volumen_ultimo"] == 7 and S["canales"] == ["Al Público", "Agro"] and S["empresas"][2]["hace12"] == round(10 / 217, 6)
    pv = {p["provincia"]: p for p in S["provincias"]}
    assert [p["provincia"] for p in S["provincias"]] == ["Córdoba", "Salta", "Jujuy"] and pv["Córdoba"]["volumen"] == 167
    assert pv["Córdoba"]["share_ypf"] == round(70 / 167, 6) and pv["Córdoba"]["share_ypf_hace12"] == round(60 / 157, 6) and pv["Salta"]["var_pp"] == 0
    assert pv["Jujuy"]["share_ypf"] is None and pv["Jujuy"]["var_pp"] is None            # sin YPF: null
    pm_ = S["provincias_meses"]                                                          # mismo dato por mes, para el selector del visor
    assert list(pm_)[-1] == "2026-09" and pm_["2026-09"]["Córdoba"] == {"share_ypf": pv["Córdoba"]["share_ypf"], "volumen": 167}
    assert pm_[S["meses"][-13]]["Córdoba"]["share_ypf"] == pv["Córdoba"]["share_ypf_hace12"] and pm_["2026-09"]["Jujuy"]["share_ypf"] is None
    Sa = share(sh, "Agro")
    assert Sa["empresas"][0]["ultimo"] == 1.0 and Sa["empresas"][0]["hace12"] is None and Sa["empresas"][0]["var_pp"] is None  # hace 12 no hay Agro
    assert share(sh, "Al Público")["empresas"][0]["ultimo"] == round(100 / 202, 6)
    assert share([])["meses"] == [] and share(sh, "Inexistente")["empresas"] == []
    sf = share_filas(sh, "Al Público")
    assert sf[0]["mes"] == "2025-09" and sf[0]["empresa"] == "YPF" and sf[0]["share"] == round(120 / 217, 6) and sf[0]["volumen"] == 120
    sc = share_completo(sh)
    assert sc["meses"][0] == "2025-09" and sc["meses"][-1] == S["meses"][-1] and [e["empresa"] for e in sc["empresas"]] == [e["empresa"] for e in S["empresas"]]
    assert sc["empresas"][0]["serie"][0] == round(120 / 217, 6) and sc["empresas"][1]["serie"][-7] is None  # sin fila = null, no 0
    # ---------- dónde pierde share: descomposición exacta, nulos, unidades ----------
    pm = perdidas(d, "automotrices", ventana="mes")
    f_ = pm["foco"]
    assert pm["periodo_t"] == ["2026-09", "2026-09"] and pm["periodo_t0"] == ["2025-09", "2025-09"] and pm["unidad"] == "m3"
    assert (f_["total_t"], f_["total_t0"], f_["ypf_t"], f_["ypf_t0"], f_["delta_ypf"]) == (212, 217, 110, 120, -10)
    assert abs(f_["efecto_share"] - (110 / 212 - 120 / 217) * 212) < 1e-5 and abs(f_["efecto_mercado"] - 120 / 217 * -5) < 1e-5
    for sg in pm["segmentos"] + pm["por_canal"] + pm["por_provincia"] + [f_]:           # identidad exacta en todo segmento con datos de YPF
        if sg["delta_ypf"] is not None:
            assert abs(sg["efecto_share"] + sg["efecto_mercado"] - sg["delta_ypf"]) < 1e-5, sg
    cel = {(s["canal"], s["provincia"]): s for s in pm["segmentos"]}
    assert cel[("Al Público", "Salta")]["efecto_share"] == 0 and cel[("Al Público", "Salta")]["efecto_mercado"] == -20 and cel[("Al Público", "Salta")]["estado"] == "ok"
    assert cel[("Agro", "Córdoba")]["estado"] == "sin dato" and cel[("Al Público", "Jujuy")]["estado"] == "sin dato"   # sin fila en t0: ni pérdida ni 100 %
    assert pm["segmentos"][0]["estado"] == "ok" and pm["foco"]["serie"]["empresas"][0]["empresa"] == "YPF" and len(pm["foco"]["serie"]["meses"]) == 36
    assert perdidas(d, "automotrices", ventana="mes", minimo=1000)["segmentos"][0]["estado"] == "volumen chico"   # el piso manda
    pa = perdidas(d, "automotrices", ventana="anterior")
    assert pa["periodo_t"] == ["2026-09", "2026-09"] and pa["periodo_t0"] == ["2026-08", "2026-08"] and pa["min"] == piso(1) == 5.0 and piso(12) == 50.0 and 5 < piso(6) < 50
    pe = perdidas(d, "automotrices", desde="2026-09", hasta="2026-09", vs="12m")                  # período explícito = el atajo `mes`
    assert pe["ventana"] == "personalizado" and pe["periodo_t0"] == pm["periodo_t0"] and pe["foco"]["delta_ypf"] == -10 and pe["n_meses"] == 1 and pe["min"] == 5.0
    assert perdidas(d, "automotrices", desde="2026-09", hasta="2026-09")["periodo_t0"] == ["2026-08", "2026-08"]                  # vs por defecto = anterior
    assert perdidas(d, "automotrices", desde="2026-09", hasta="2026-09", vs="2025-09:2025-09")["foco"]["total_t0"] == 217      # otro período explícito
    assert perdidas(d, "automotrices", desde="2026-09", hasta="2026-09", vs="12m") is pe                                           # cache por la clave completa
    p2 = perdidas(d, "automotrices", desde="2026-08", hasta="2026-09", vs="anterior")
    assert p2["periodo_t"] == ["2026-08", "2026-09"] and p2["periodo_t0"] == ["2026-06", "2026-07"] and p2["min"] == round(5 + 45 / 11, 1)
    for mal in (dict(desde="2026-9", hasta="2026-09"), dict(desde="2026-10", hasta="2026-09"), dict(desde="2026-08", hasta="2026-09", vs="2025-09:2025-09"),
                dict(desde="2020-01", hasta="2020-01"), dict(desde="2026-09", hasta="2026-09", vs="x"), dict(desde="2025-09", hasta="2026-09", vs="12m"),
                dict(desde="2026-09", hasta="2026-09", vs="2030-01:2030-01")):
        try:
            perdidas(d, "automotrices", **mal)
            assert False, mal
        except ValueError:
            pass
    assert [c for c in pm["por_competidor"] if c["segmentos"]] == [c for c in pm["por_competidor"] if c["ganado_donde_ypf_pierde_m3"] > 0]
    mm = lambda m, e, v: (m, e, "P", "c", "p", v)
    dg = lambda y0, a0, y1, a1: segmento([mm("2025-09", "YPF", y0), mm("2025-09", "A", a0), mm("2026-09", "YPF", y1), mm("2026-09", "A", a1)], ["2026-09"], ["2025-09"], 1)["diagnostico"]
    assert (dg(50, 50, 40, 60), dg(50, 50, 50, 70), dg(50, 50, 25, 30), dg(50, 50, 60, 50)) == ("YPF vendió menos", "El mercado creció y YPF no acompañó", "Cayó el mercado y YPF cayó más", None)
    p12 = perdidas(d)
    assert p12["foco"]["meses_con_dato"] == {"t": 12, "t0": 1} and p12["foco"]["huecos"] is True    # hueco informado, no rellenado
    # empresa que entra o sale de la declaración: va aparte, no es ganancia ni pérdida; YPF sin fila = sin dato YPF, no 100 % perdido
    mm = lambda m, e, v: (m, e, "P", "c", "p", v)
    sg = segmento([mm("2025-09", "YPF", 50), mm("2025-09", "A", 30), mm("2025-09", "Z", 20), mm("2026-09", "YPF", 50), mm("2026-09", "A", 30), mm("2026-09", "N", 20)],
                  ["2026-09"], ["2025-09"], 1)
    assert [c["empresa"] for c in sg["competidores"]] == ["A"] and sg["competidores"][0]["m3_eq"] == 0
    assert {(x["empresa"], x["flag"]) for x in sg["entraron_salieron"]} == {("Z", "salió de la declaración"), ("N", "entró a declarar")}
    sy = segmento([mm("2025-09", "YPF", 50), mm("2025-09", "A", 50), mm("2026-09", "A", 100)], ["2026-09"], ["2025-09"], 1)
    assert sy["estado"] == "sin dato YPF" and sy["efecto_share"] is None and sy["s_t"] is None and sy["ypf_flag"] == "salió de la declaración"
    pg = perdidas(d, "grasas", ventana="mes")                                             # Grasas: Ton, nunca mezclada con m3; el gasoil no entra
    assert pg["unidad"] == "Ton" and pg["foco"]["total_t"] == 7 and {x["producto"]: x["unidad"] for x in pg["por_producto"]}["Grasas(Ton)"] == "Ton"
    assert all(x["unidad"] == "m3" for x in pg["por_producto"] if x["clave"] != "grasas") and len(pg["por_producto"]) == 4
    assert [f["mes"] for f in filas_se(d, "Grasas(Ton)")] == ["2026-09"] and len(filas_se(d, "Lubricantes automotrices(m3)", "Agro")) == 1
    # selección múltiple: producto/canal/provincia como conjuntos; el foco es la suma y los números salen de las filas
    sel_p, sel_c, sel_v = ["automotrices", "industriales"], ["Al Público", "Agro"], ["Córdoba", "Salta"]
    pmu = perdidas(d, sel_p, sel_c, sel_v, ventana="mes", minimo=0)
    man = lambda ms_, e=None: sum(f[5] for f in d["energia"] if f[0] in ms_ and f[2] in (PRODUCTOS_SHARE[k] for k in sel_p) and f[3] in sel_c and f[4] in sel_v and (e is None or f[1] == e))
    fm = pmu["foco"]
    assert pmu["unidad"] == "m3" and pmu["productos"] == sel_p and fm["canal"] == sorted(sel_c) and fm["provincia"] == sorted(sel_v) and pmu["clave"] == "automotrices,industriales"
    assert abs(fm["total_t"] - man({"2026-09"})) < 1e-6 and abs(fm["total_t0"] - man({"2025-09"})) < 1e-6 and abs(fm["ypf_t"] - man({"2026-09"}, "YPF")) < 1e-6 and fm["total_t"] == 247 and fm["ypf_t"] == 140
    assert {(x["canal"], x["provincia"]) for x in pmu["segmentos"]} <= {(c, v) for c in sel_c for v in sel_v} and {x["producto"] for x in pmu["por_producto"]} >= {"Grasas(Ton)"}
    for sg in pmu["segmentos"] + pmu["por_canal"] + pmu["por_provincia"] + [fm]:      # la identidad se mantiene con la suma
        if sg["delta_ypf"] is not None:
            assert abs(sg["efecto_share"] + sg["efecto_mercado"] - sg["delta_ypf"]) < 1e-5, sg
    assert perdidas(d, ["automotrices"], ventana="mes") is pm and perdidas(d, ["industriales", "automotrices"], list(reversed(sel_c)), sel_v, ventana="mes", minimo=0) is pmu
    assert perdidas(d, "automotrices", "Agro", ventana="mes")["foco"]["canal"] == "Agro"          # un valor sigue siendo string
    try:
        perdidas(d, ["grasas", "automotrices"])
        assert False
    except ValueError:
        pass
    assert len(filas_se(d, {"Lubricantes automotrices(m3)", "Grasas(Ton)"}, {"Agro", "Al Público"}, ["Córdoba"], desde="2026-09", hasta="2026-09")) == 12
    ms_, ser_ = d["macro_meta"], d["macro_series"]
    assert [(p["valor"], p["signo"]) for p in ser_["A"]] == [(1.5, "*"), (None, "..."), (0.0, "-")] and ser_["C"] == [] and ser_["B"][0]["signo"] is None
    assert ser_["se_gasoil_carga"][0]["fecha"] == "2025-09-01" and ser_["se_gasoil_carga"][6] == {"fecha": "2026-03-01", "valor": None, "signo": "..."}
    assert ser_["se_lub_automotrices"][-1]["valor"] == 212 and ms_["se_lub_automotrices"]["grupo"] == "demanda"
    act = {a["id"]: a for a in actividad(ms_, ser_)}
    assert act["C"]["ultimo"] is None and act["C"]["var_ia"] is None and act["A"]["ultimo"]["valor"] == 0.0 and act["A"]["var_ia"] is None
    assert len(act["A"]["serie"]) == 3 and list(act)[-4:] == [x[0] for x in DERIVADAS]
    assert c["mercado"]["actualizado"] == {"energia": "2026-09", "series": "2026-11-02"}   # la corrida con error no cuenta
    # compuestos: deflactor, USD, asequibilidad y demanda potencial
    Ob = lambda f, pid, precio, fu="sepa": {**dict.fromkeys(OBS_F, ""), "fecha": f, "fuente": fu, "producto_id": pid, "precio": precio, "litros": "1", "unidades": "1"}
    dc = {"equivalencias": [{"ypf_id": "y", "comp_id": "c", "tipo": "match_total"}, {"ypf_id": "y", "comp_id": "g", "tipo": "no_equivalente"}],
          "obs": [Ob("2026-10-05", "y", "1000"), Ob("2026-10-06", "y", "3000"), Ob("2026-10-05", "c", "3000"), Ob("2026-11-05", "y", "2000"),
                  Ob("2026-11-05", "c", "2500"), Ob("2026-11-05", "g", "1"), Ob("2026-11-05", "y", "9", "shopify_datri")]}
    sr = {ID_IPC: [punto("2026-10-01", 100), punto("2026-11-01", 200)], ID_SALARIO: [punto("2026-10-01", 100), punto("2026-11-01", 125)],
          ID_TC: [punto("2026-10-05", 1000), punto("2026-11-05", "")]}
    cp = compuestos(dc, sr)
    assert cp["precio_real"] == [{"mes": "2026-10", "ypf_litro": 2000, "ypf_real": 2000, "comp_litro": 3000, "comp_real": 3000},
                                 {"mes": "2026-11", "ypf_litro": 2000, "ypf_real": 1000, "comp_litro": 2500, "comp_real": 1250}], cp["precio_real"]
    assert cp["asequibilidad"] == [{"mes": "2026-10", "indice": 100.0}, {"mes": "2026-11", "indice": 80.0}], cp["asequibilidad"]
    assert cp["precio_usd"] == [{"fecha": "2026-10-05", "ypf_usd": 1.0, "comp_usd": 3.0}, {"fecha": "2026-10-06", "ypf_usd": None, "comp_usd": None},
                                {"fecha": "2026-11-05", "ypf_usd": None, "comp_usd": None}]    # TC null o ausente → null, no se arrastra
    assert "sin calibrar" in cp["notas"]["demanda_potencial"]
    sin_ipc = compuestos(dc, {ID_SALARIO: sr[ID_SALARIO]})
    assert all(r["ypf_real"] is None and r["comp_real"] is None for r in sin_ipc["precio_real"]) and sin_ipc["precio_real"][0]["ypf_litro"] == 2000
    assert compuestos({**dc, "obs": []}, sr)["precio_real"] == []
    cte = lambda v, extra: [punto(f"2023-{m:02d}-01", v) for m in range(1, 13)] + extra
    sd = {ID_PEAJES: cte(100, [punto("2026-01-01", 120), punto("2026-02-01", 100)]), ID_GASOIL_CARGA: cte(50, [punto("2026-01-01", 100)]),
          ID_AGRO: cte(10, [punto("2026-01-01", 5)])}
    idp = {r["mes"]: r["valor"] for r in compuestos(dc, sd)["demanda_potencial"]}
    assert idp["2026-01"] == 130.0 and idp["2023-06"] == 100.0 and idp["2026-02"] is None     # 0,5·120 + 0,3·200 + 0,2·50; falta un componente → null
    sd[ID_AGRO] = sd[ID_AGRO][1:]                                                           # 2023 incompleto: sin base, todo null
    assert all(r["valor"] is None for r in compuestos(dc, sd)["demanda_potencial"])

    def b(s):
        return {"Authorization": "Basic " + base64.b64encode(s.encode()).decode()}
    assert autorizado({}, None) and autorizado({}, "")
    assert autorizado({"X-API-Key": "s3cr3t"}, "s3cr3t")
    assert not autorizado({"X-API-Key": "s3cr3"}, "s3cr3t")
    assert not autorizado({}, "s3cr3t")
    assert autorizado(b("cualquiera:s3cr3t"), "s3cr3t")
    assert not autorizado(b("s3cr3t:otra"), "s3cr3t")
    assert not autorizado({"Authorization": "Basic %%%"}, "s3cr3t")
    assert not autorizado({"X-API-Key": "ñ"}, "s3cr3t")

    # ---------- provincias, reventa y cobertura (sin red ni archivos) ----------
    dp = {"productos": [P("ypf-a", "YPF"), P("ypf-b", "YPF"), P("shell-s", "Shell"), P("gulf-g", "Gulf")],
          "equivalencias": [E("shell-s", "match_total"), E("gulf-g", "no_equivalente")],
          "obs": [O("2026-11-05", "sepa", "ypf-a", "4000", url="a1", vendedor="Carrefour", provincia="AR-X"),
                  O("2026-11-05", "sepa", "ypf-a", "5000", url="a2", vendedor="Jumbo", provincia="AR-X"),
                  O("2026-11-04", "sepa", "ypf-a", "1", url="a1", vendedor="Carrefour", provincia="AR-X"),   # mismo aviso, más viejo: lo pisa el de hoy
                  O("2026-11-05", "sepa", "ypf-a", "6000", url="a3", provincia="AR-B"), O("2026-11-05", "sepa", "ypf-a", "8000", url="a4", provincia="AR-C"),
                  O("2026-11-05", "sepa", "ypf-a", "7000", url="a5", provincia="AR-Y"),
                  O("2026-10-01", "sepa", "ypf-a", "1", url="a6", provincia="AR-X"),                          # fuera de los 30 días
                  O("2026-11-05", "vtex_easy", "ypf-a", "20000", "4", url="e1", provincia="online"),
                  O("2026-11-05", "vtex_easy", "ypf-a", "100", url="e2"),                                     # sin provincia: no cae en ninguna celda
                  O("2026-11-05", "shopify_datri", "ypf-a", "36000", "1", "12", url="m1", provincia="online"),
                  O("2026-11-05", "grok_helix", "ypf-a", "5200", url="g1", provincia="AR-X", verificado="1", cargado="T1"),
                  O("2026-11-05", "grok_helix", "ypf-a", "5300", url="g2", provincia="AR-B", verificado="0", cargado="T2"),
                  O("2026-11-05", "sepa", "shell-s", "6000", url="s1", provincia="AR-X")]}
    pv_ = provincias(dp, "ypf-a")
    cel = {(c["provincia"], c["fuente"]): c for c in pv_["celdas"]}
    assert pv_["hasta"] == "2026-11-05" and "tiempo real" in pv_["nota"] and pv_["n_sin_provincia"] == 1
    assert cel[("AR-X", "sepa")]["precio_litro"] == 4500 and cel[("AR-X", "sepa")]["n"] == 2 and cel[("AR-X", "sepa")]["canal"] == "publico"
    assert cel[("AR-X", "sepa")]["region"] == "Pampeana" and cel[("AR-X", "sepa")]["fecha"] == "2026-11-05" and cel[("AR-X", "sepa")]["url"] == ""
    assert cel[("AR-X", "grok_helix")]["precio_litro"] == 5200 and cel[("AR-X", "grok_helix")]["canal"] == "grok"                      # Grok no se mezcla con SEPA
    assert (cel[("AR-X", "grok_helix")]["url"], cel[("AR-X", "grok_helix")]["verificado"], cel[("AR-X", "grok_helix")]["cargado"]) == ("g1", "1", "T1")
    assert cel[("AR-B", "grok_helix")]["verificado"] == "0"
    assert cel[("online", "vtex_easy")]["precio_litro"] == 5000 and cel[("online", "vtex_easy")]["region"] == "" and ("online", "shopify_datri") not in cel
    assert all(len({c["fuente"]}) == 1 for c in pv_["celdas"]) and len(pv_["celdas"]) == 7
    rg = {(c["region"], c["fuente"]): c for c in pv_["regiones"]}
    assert rg[("Pampeana", "sepa")]["precio_litro"] == 5500 and rg[("Pampeana", "sepa")]["n"] == 4 and rg[("Pampeana", "sepa")]["provincias"] == ["AR-B", "AR-C", "AR-X"]
    assert rg[("NOA", "sepa")]["precio_litro"] == 7000 and not any(c["region"] == "" for c in pv_["regiones"])
    assert ("online", "shopify_datri") in {(c["provincia"], c["fuente"]) for c in provincias(dp, "ypf-a", mayoristas=True)["celdas"]}
    assert {c["fuente"] for c in provincias(dp, "ypf-a", fuente="grok_helix")["celdas"]} == {"grok_helix"}
    assert provincias(dp, "ypf-a", fuente="shopify_datri")["celdas"][0]["canal"] == "mayorista"  # pedida a propósito: sí sale
    assert provincias(dp, "ypf-a", dias=1)["celdas"] and provincias(dp, "ypf-b")["celdas"] == [] and provincias(dp, "ypf-b")["hasta"] == "2026-11-05"
    rs_ = {p["producto_id"]: p for p in provincias_resumen(dp)["productos"]}
    assert rs_["ypf-b"]["fuentes"] == [] and {f["fuente"]: f["provincias"] for f in rs_["ypf-a"]["fuentes"]}["sepa"] == 4 and "shell-s" not in rs_
    co = cobertura(dp)
    assert co["total"] == {"productos_ypf": 2, "con_equivalencia": 1, "con_precio_7d": 1}, co["total"]
    ca_ = {x["producto_id"]: x for x in co["productos"]}
    assert (ca_["ypf-a"]["equivalencias"], ca_["ypf-a"]["tiene_equivalencia"], ca_["ypf-a"]["fuentes_7d"], ca_["ypf-a"]["provincias_7d"]) == (1, True, 4, 4), ca_["ypf-a"]
    assert (ca_["ypf-b"]["tiene_equivalencia"], ca_["ypf-b"]["fuentes_7d"], ca_["ypf-b"]["ultima_fecha"]) == (False, 0, None)
    rv = reventa(dp, "ypf-a")
    assert [e["producto_id"] for e in rv["equivalentes"]] == ["shell-s"] and len(rv["ypf"]["observaciones"]) == 11   # todas las del período, no solo la última por aviso
    og = [o for o in rv["ypf"]["observaciones"] if o["url"] == "g1"][0]
    assert og["canal"] == "grok" and og["verificado"] == "1" and og["cargado"] == "T1" and og["region"] == "Pampeana" and og["precio_litro"] == 5200
    assert rv["ypf"]["observaciones"][0]["fecha"] == "2026-11-05" and len(aplanar_reventa(rv)) == 12 and aplanar_reventa(rv)[-1]["rol"] == "equivalente"
    assert a_csv("reventa", aplanar_reventa(rv)).decode().startswith("rol,producto_id,marca,nombre,tipo,fecha,fuente,canal,vendedor,provincia,region,url,precio,")
    assert [canal(f) for f in ("sepa", "shopify_datri", "grok_x")] == ["publico", "mayorista", "grok"]
    # desde/hasta en provincias y reventa: el mismo contrato que /api/producto (rango inclusive; solo desde = hasta el último día con datos)
    rr = reventa(dp, "ypf-a", desde="2026-11-01", hasta="2026-11-03")
    assert (rr["dias"], rr["desde"], rr["hasta"]) == (3, "2026-11-01", "2026-11-03") and all("2026-11-01" <= o["fecha"] <= "2026-11-03" for o in rr["ypf"]["observaciones"])
    assert len(rr["ypf"]["observaciones"]) < len(rv["ypf"]["observaciones"]) and reventa(dp, "ypf-a", desde="2026-11-04")["hasta"] == "2026-11-05"
    assert provincias(dp, "ypf-a", desde="2026-11-05", hasta="2026-11-05")["dias"] == 1 and provincias_resumen(dp, hasta="2026-11-04", dias=2)["desde"] == "2026-11-03"
    assert rango_pedido(dp, 30, {"desde": "2026-11-05", "hasta": "2026-11-01"})[2] and rango_pedido(dp, 30, {"desde": "2026-1-5"})[2] and rango_pedido(dp, 30, {})[2] is None
    # ---------- /api/producto: una fila por aviso, con motivo de exclusión y desvío contra la mediana; sin umbral por defecto ----------
    pr = producto(dp, "ypf-a")
    mot = {x["url"]: x["motivo_exclusion"] for x in pr["publicaciones"]}
    assert len(pr["publicaciones"]) == 10 and pr["resumen"]["n"] == 7 and pr["resumen"]["mediana_litro"] == 5200 and pr["resumen"]["p25_litro"] == 5000 and pr["producto"]["es_ypf"]
    assert (mot["e2"], mot["m1"], mot["g2"], mot["a1"], mot["g1"]) == ("fuera_de_sanidad", "mayorista", "grok_sin_verificar", None, None)
    assert {x["url"]: x["desvio_pct_vs_mediana"] for x in pr["publicaciones"]}["a4"] == 53.8 and all("sobre_umbral" not in x for x in pr["publicaciones"])
    assert pr["ventana"] == {"dias": 3, "desde": "2026-11-03", "hasta": "2026-11-05"} and producto(dp, "ypf-a", 30)["ventana"]["desde"] == "2026-10-07" and "tiempo real" in pr["nota"] and "umbral de sobreprecio" in pr["metodo"]
    assert [x["en_calculo"] for x in pr["publicaciones"]].index(False) == 7 and pr["publicaciones"][0]["url"] == "a4"  # en cálculo primero, de más caro a más barato
    g1 = next(x for x in pr["publicaciones"] if x["url"] == "g1")
    assert g1["verificado"] is True and g1["fuente_nombre"] == "Grok · grok_helix" and nombre_fuente({"grok_sitios": [{"fuente": "grok_helix", "host": "www.helixturno.com.ar"}]}, "grok_helix") == "Grok · www.helixturno.com.ar" and nombre_fuente(dp, "shopify_datri") == "Tienda D'Atri (mayorista)" and next(x for x in pr["publicaciones"] if x["url"] == "g2")["verificado"] is False
    assert {x["url"]: x["sobre_umbral"] for x in producto(dp, "ypf-a", umbral=50)["publicaciones"]}["a4"] is True
    assert producto(dp, "ypf-a", umbral=50)["publicaciones"][-1]["sobre_umbral"] is False and producto(dp, "ypf-a", umbral=50)["umbral_pct"] == 50
    assert producto(dp, "ypf-a", mayoristas=True)["resumen"]["n"] == 8 and producto(dp, "ypf-a", dias=1)["ventana"]["desde"] == "2026-11-05"
    assert [(e["producto_id"], e["en_comparacion"], e["motivo_exclusion"]) for e in pr["equivalentes"]] == [("shell-s", True, None), ("gulf-g", False, "no_equivalente")]
    assert pr["comparacion"] == {"mediana_ypf_litro": 5200, "mediana_comp_litro": 6000, "n_comp": 1, "dif_pct_mediana_comp_vs_ypf": 15.4,
                                "promedio_ypf_litro": 5742.86, "promedio_comp_litro": 6000, "dif_pct_promedio_comp_vs_ypf": 4.5}, pr["comparacion"]
    vacio = producto(dp, "ypf-b")
    assert vacio["resumen"]["n"] == 0 and vacio["resumen"]["mediana_litro"] is None and vacio["publicaciones"] == [] and vacio["comparacion"]["dif_pct_mediana_comp_vs_ypf"] is None
    assert len(aplanar_producto(pr)) == 11 and aplanar_producto(pr)[-1]["rol"] == "equivalente" and a_csv("producto", aplanar_producto(pr)).decode().startswith("rol,producto_id,marca,nombre,tipo,evidencia,fuente,")
    assert [x[0] for x in cuerdos([(1, 0), (5, 0), (5.2, 0)])] == [5, 5.2]
    # rango explícito: manda sobre `dias`; solo desde = hasta el último día con datos; solo hasta = `dias` hacia atrás; sin rango, igual que antes
    pe_ = producto(dp, "ypf-a", 30, desde="2026-11-01", hasta="2026-11-03")
    assert pe_["ventana"] == {"dias": 3, "desde": "2026-11-01", "hasta": "2026-11-03"} and pe_["datos"]["hasta"] == "2026-11-05" and pe_["datos"]["desde"] <= "2026-11-01"
    assert all("2026-11-01" <= x["fecha"] <= "2026-11-03" for x in pe_["publicaciones"])
    assert producto(dp, "ypf-a", 30, desde="2026-11-03")["ventana"] == {"dias": 3, "desde": "2026-11-03", "hasta": "2026-11-05"}
    assert producto(dp, "ypf-a", 5, hasta="2026-11-03")["ventana"] == {"dias": 5, "desde": "2026-10-30", "hasta": "2026-11-03"}
    assert producto(dp, "ypf-a")["publicaciones"] == pr["publicaciones"] and producto(dp, "ypf-a", 30)["resumen"]["n"] == pr["resumen"]["n"]
    # misma publicación de ML que cambió provincia ('' → 'online'): una sola en /api/producto (la más nueva), dos en provincias
    ml_ = {"producto_id": "p", "fuente": "ml", "url": "u", "ean": "", "titulo": "t", "vendedor": "v", "litros": "1", "unidades": "1", "precio": "9"}
    dm = {"obs": [{**ml_, "fecha": "2026-11-17", "provincia": ""}, {**ml_, "fecha": "2026-11-18", "provincia": "online"}]}
    assert [r["fecha"] for r in _avisos(dm, 30, {"p"}, prov_en_url=False)[1]["p"]] == ["2026-11-18"] and len(_avisos(dm, 30, {"p"})[1]["p"]) == 2 and len(_avisos(dm, 30, {"p"}, None)[1]["p"]) == 1
    # /api/producto con los parámetros por defecto == vitrina (n, promedio, mediana; competencia): una sola definición de aviso, ventana y sanidad
    dv = {**dp, "obs": dp["obs"] + [O("2026-11-05", "sepa", "ypf-a", "4100", url="", vendedor="Carrefour", provincia="AR-B"),   # mismo comercio en otra provincia: un solo aviso
                                    O("2026-11-05", "sepa", "ypf-a", "4000", url="", vendedor="Changomas", provincia="AR-X"),
                                    O("2026-11-05", "sepa", "ypf-a", "4000", url="", vendedor="Changomas", provincia="AR-B"),
                                    O("2026-11-05", "sepa", "shell-s", "6600", url="s2", provincia="AR-B"), O("2026-11-05", "sepa", "shell-s", "7000", url="s3", provincia="AR-C")]}
    vt_ = {x["producto_id"]: x for x in vitrina(dv)["productos"]}
    # índice según la competencia (30 días): el mismo número que /api/producto?dias=30 y que el último corte del barrido de /api/bi/indice_competencia
    sw_ = {f["producto_id"]: f for f in bi_indice_competencia(dv) if f["fecha"] == "2026-11-05"}
    for pid_, x_ in vt_.items():
        i_, c30_ = x_["indice_30d"], producto(dv, pid_, 30)["comparacion"]
        assert (i_["mediana_ypf_litro"], i_["mediana_comp_litro"], i_["n_comp"]) == (c30_["mediana_ypf_litro"], c30_["mediana_comp_litro"], c30_["n_comp"]), pid_
        assert i_["indice"] == (round(i_["mediana_ypf_litro"] / i_["mediana_comp_litro"] * 100, 1) if i_["mediana_ypf_litro"] and i_["mediana_comp_litro"] else None)
        assert (i_["desde"], i_["hasta"]) == ("2026-10-07", "2026-11-05")
        assert (pid_ in sw_) == bool(i_["n_ypf"] or i_["n_comp"]) and (pid_ not in sw_ or {k: sw_[pid_][k] for k in i_ if k not in ("desde", "hasta")} == {k: v for k, v in i_.items() if k not in ("desde", "hasta")}), pid_
    assert vt_["ypf-a"]["indice_30d"]["indice"] is not None and vt_["ypf-b"]["indice_30d"] == {"indice": None, "mediana_ypf_litro": None, "mediana_comp_litro": None, "n_ypf": 0, "n_comp": producto(dv, "ypf-b", 30)["comparacion"]["n_comp"], "desde": "2026-10-07", "hasta": "2026-11-05"}
    assert {k: v["indice_30d"] for k, v in {x["producto_id"]: x for x in vitrina(dv, True)["productos"]}.items()} == {k: v["indice_30d"] for k, v in vt_.items()}  # mayoristas no cambian el índice
    assert aplanar_vitrina(vitrina(dv))[0]["indice30_indice"] == vt_["ypf-a"]["indice_30d"]["indice"] and vitrina({**dv, "obs": []})["productos"][0]["indice_30d"]["n_ypf"] == 0
    # ventana móvil: un corte anterior solo ve lo que hasta entonces había (el 2026-11-04 no ve los avisos del 05)
    assert {f["fecha"] for f in bi_indice_competencia(dv)} >= {"2026-11-04", "2026-11-05"} and bi_indice_competencia(dv, "2026-11-05") == [f for f in bi_indice_competencia(dv) if f["fecha"] >= "2026-11-05"]
    for pid_ in vt_:
        pp_ = producto(dv, pid_)
        assert (pp_["resumen"]["n"], pp_["resumen"]["promedio_litro"], pp_["resumen"]["mediana_litro"]) == (vt_[pid_]["ypf"]["n"], vt_[pid_]["ypf"]["promedio_litro"], vt_[pid_]["ypf"]["mediana_litro"]), pid_
        assert (pp_["comparacion"]["n_comp"], pp_["comparacion"]["promedio_comp_litro"], pp_["comparacion"]["dif_pct_promedio_comp_vs_ypf"]) == (
            vt_[pid_]["competencia"]["n"], vt_[pid_]["competencia"]["promedio_litro"], vt_[pid_]["dif_pct"]), pid_
        for e_ in pp_["equivalentes"]:
            ve_ = next(x for x in vt_[pid_]["competencia"]["equivalentes"] if x["producto_id"] == e_["producto_id"])
            assert (e_["resumen"]["n"], e_["resumen"]["promedio_litro"], e_["en_comparacion"]) == (ve_["n"], ve_["promedio_litro"], ve_["en_promedio"])
    assert vt_["ypf-a"]["ypf"]["n"] == 9 and vt_["ypf-a"]["competencia"]["n"] == 3   # Carrefour y Changomas una vez cada uno, no una por provincia

    # ---------- países: nada se mezcla (ni países ni monedas); USD solo con la cotización de ese día ----------
    Pb = lambda i, m, **k: {**dict.fromkeys(PRODUCTOS_F, ""), "producto_id": i, "marca": m, "linea": "L", "nombre": i, "segmento": "pcmo", "sae": "5W-30", **k}
    Ob = lambda f, fu, pid, precio, pais="", prov="online", **k: {**dict.fromkeys(OBS_F, ""), "fecha": f, "fuente": fu, "producto_id": pid, "precio": str(precio),
                                                                   "litros": "1", "unidades": "1", "url": f"u-{fu}-{pid}-{precio}", "pais": pais,
                                                                   "moneda": {"BR": "BRL", "": ""}[pais], "provincia": prov, **k}
    db = {"productos": [Pb("ypf-x", "YPF"), Pb("shell-x", "Shell"), Pb("ypf-x-br", "YPF"), Pb("lubrax-x-br", "Lubrax")],
          "equivalencias": [E("shell-x", "sustituto_comercial", "ypf-x"), E("lubrax-x-br", "sustituto_comercial", "ypf-x-br")], "imagenes": [], "fx": [
              {"fecha": "2026-11-17", "moneda": "BRL", "por_usd": "5", "fuente": "bcb_ptax"}],
          "macro_series": {ID_TC: [{"fecha": "2026-11-17", "valor": 1000.0, "signo": None}, {"fecha": "2026-11-18", "valor": 900.0, "signo": None}]},
          "obs": [Ob("2026-11-17", "vtex_a", "ypf-x", 1000), Ob("2026-11-17", "vtex_a", "shell-x", 1200),          # AR: fila sin pais/moneda = AR/ARS
                  Ob("2026-11-17", "vtex_br_p", "ypf-x-br", 50, "BR"), Ob("2026-11-17", "vtex_br_p", "lubrax-x-br", 60, "BR"),
                  Ob("2026-11-16", "oficial_br_np", "ypf-x-br", 40, "BR", "BR-PR"), Ob("2026-11-16", "oficial_br_np", "lubrax-x-br", 44, "BR", "BR-PR")]}
    db["fx_tabla"] = tabla_fx(db)
    assert db["fx_tabla"] == {("BRL", "2026-11-17"): (5.0, "bcb_ptax"), ("ARS", "2026-11-17"): (1000.0, "BCRA (datos.gob.ar)"), ("ARS", "2026-11-18"): (900.0, "BCRA (datos.gob.ar)")}
    # ARS: el BCRA (fx.csv) gana sobre la valuación en la misma fecha; cada una con su fuente y rótulo; día sin dato = sin clave
    dx = dict(db, fx=db["fx"] + [{"fecha": "2026-11-18", "moneda": "ARS", "por_usd": "1559.5", "fuente": "bcra_cambiarias"}])
    tx = tabla_fx(dx)
    assert tx[("ARS", "2026-11-18")] == (1559.5, "bcra_cambiarias") and tx[("ARS", "2026-11-17")] == (1000.0, "BCRA (datos.gob.ar)") and ("ARS", "2026-11-19") not in tx
    fl = {x["fecha"]: x for x in fx_lista(tx, "ARS")}
    assert fl["2026-11-18"]["fuente_nombre"].startswith("BCRA, cotización") and "bcra.gob.ar" in fl["2026-11-18"]["fuente_url"] and "datos.gob.ar" in fl["2026-11-17"]["fuente_url"]
    ia, ib = indice(db), indice(db, pais="BR")
    assert {(r["pais"], r["moneda"]) for r in ia} == {("AR", "ARS")} and {(r["pais"], r["moneda"]) for r in ib} == {("BR", "BRL")}
    assert [(r["marca"], r["indice"]) for r in ia if r["fecha"] == "2026-11-17"] == [("Shell", 120.0), ("YPF", 100.0)]      # el índice AR no ve los R$
    assert [(r["fecha"], r["marca"], r["mediana_litro"], r["indice"]) for r in ib] == [("2026-11-16", "Lubrax", 44.0, 110.0), ("2026-11-16", "YPF", 40.0, 100.0),
                                                                                       ("2026-11-17", "Lubrax", 52.0, 115.6), ("2026-11-17", "YPF", 45.0, 100.0)]  # el 17 suma los avisos del 16 (ventana de 3 días)
    assert indice({**db, "obs": [o for o in db["obs"] if o["producto_id"] != "ypf-x-br"]}, pais="BR")[-1]["indice"] is None  # sin YPF del país ese día: sin índice (no usa el de otro país)
    ub = ultimo(db["obs"], "BR")
    assert {(u["pais"], u["moneda"]) for u in ub} == {("BR", "BRL")} and {u["producto_id"] for u in ub} == {"ypf-x-br", "lubrax-x-br"} and ultimo(db["obs"])[0]["moneda"] == "ARS"
    assert serie(db["obs"], "ypf-x-br") == [] and [(r["fecha"], r["precio_litro"], r["moneda"]) for r in serie(db["obs"], "ypf-x-br", "BR")] == [
        ("2026-11-16", 40, "BRL"), ("2026-11-17", 50, "BRL")]
    va, vb = vitrina(db), vitrina(db, pais="BR")
    assert (va["pais"], va["moneda"], vb["pais"], vb["moneda"]) == ("AR", "ARS", "BR", "BRL")
    assert [p["producto_id"] for p in va["productos"]] == ["ypf-x"] and [p["producto_id"] for p in vb["productos"]] == ["ypf-x-br"]   # los -br no aparecen en Argentina
    assert vb["productos"][0]["competencia"]["promedio_litro"] == 52 and vb["productos"][0]["dif_pct"] == 15.6 and va["productos"][0]["competencia"]["promedio_litro"] == 1200
    assert cobertura(db)["total"]["productos_ypf"] == 1 and cobertura(db, "BR")["total"] == {"productos_ypf": 1, "con_equivalencia": 1, "con_precio_7d": 1}
    pb_ = provincias(db, "ypf-x-br", 30, pais="BR")
    assert {(c["provincia"], c["fuente"]) for c in pb_["celdas"]} == {("online", "vtex_br_p"), ("BR-PR", "oficial_br_np")} and pb_["regiones"] == [] and pb_["moneda"] == "BRL"
    assert provincias(db, "ypf-x-br")["celdas"] == [] and reventa(db, "ypf-x-br", 30, "BR")["moneda"] == "BRL" and len(reventa(db, "ypf-x-br", 30, "BR")["ypf"]["observaciones"]) == 2
    assert reventa(db, "ypf-x-br")["ypf"]["observaciones"] == []
    # USD: el día exacto o null; ARS y BRL por su fuente; nunca el día anterior
    ux = con_usd(ub, "BRL", db["fx_tabla"])
    hoy_u = [u for u in ux if u["fecha"] == "2026-11-17"][0]
    ayer_u = [u for u in ux if u["fecha"] == "2026-11-16"][0]
    assert hoy_u["precio_litro_usd"] == round(hoy_u["precio_litro"] / 5, 3) and hoy_u["fx_fecha"] == "2026-11-17" and hoy_u["fx_fuente"] == "bcb_ptax"
    assert ayer_u["precio_litro_usd"] is None and ayer_u["precio_usd"] is None and ayer_u["fx_fecha"] is None and ayer_u["fx_fuente"] is None
    assert [u["precio_litro_usd"] for u in con_usd(ultimo(db["obs"]), "ARS", db["fx_tabla"]) if u["producto_id"] == "ypf-x"] == [1.0] and "precio_usd" not in ultimo(db["obs"])[0]
    vu = con_usd(vb, "BRL", db["fx_tabla"])["productos"][0]["ypf"]["mas_barato"]
    assert vu["precio_litro_usd"] == 8.0 and vu["fx_fecha"] == "2026-11-17" and "precio_usd" in vu
    assert pais_de_fuente("vtex_br_pitstop") == "BR" and pais_de_fuente("fx_bcb_ptax") == "BR" and pais_de_fuente("vtex_easy") == "AR"

    Handler.datos, Handler.calc, Handler.clave = d, c, "s3cr3t"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Handler.log_message = lambda *a: None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"

    def get(ruta, headers=None):
        try:
            with urllib.request.urlopen(urllib.request.Request(base + ruta, headers=headers or {})) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
    assert get("/salud")[0] == 200 and json.loads(get("/salud")[1])["ok"] is True
    sj = json.loads(get("/salud", {"CF-Connecting-IP": "203.0.113.77"})[1])
    assert set(sj) == {"ok", "commit", "ultimo_dato"} and "203.0.113.77" not in json.dumps(sj)   # el equipo vive en CELU-SERVIDOR
    assert get("/api/ultimo")[0] == 200 and get("/robots.txt")[1] == b"User-agent: *\nDisallow: /\n"
    assert urllib.request.urlopen(base + "/api/ultimo").headers["X-Robots-Tag"] == "noindex, nofollow" and get("/api/ultimo", {"X-API-Key": "mala"})[0] == 200   # la clave vieja o errónea se ignora
    assert get("/")[0] == 200
    assert rango_bytes(100, "") is None and rango_bytes(100, "bytes=0-9") == (0, 9) and rango_bytes(100, "bytes=90-") == (90, 99) and rango_bytes(100, "bytes=-10") == (90, 99)
    assert rango_bytes(100, "bytes=0-999") == (0, 99) and rango_bytes(100, "bytes=100-") is False and rango_bytes(100, "bytes=9-3") is False and rango_bytes(100, "bytes=0-1,5-6") is None and rango_bytes(100, "bytes=-") is None
    for ruta, tipo in (("/media/lubricantes.mp4", "video/mp4"), ("/media/lubricantes-poster.jpg", "image/jpeg")):
        if (SITE / ruta.lstrip("/")).is_file():
            mr = urllib.request.urlopen(base + ruta)
            cuerpo = mr.read()
            assert mr.status == 200 and mr.headers["Content-Type"] == tipo and "immutable" not in mr.headers["Cache-Control"] and mr.headers["Accept-Ranges"] == "bytes" and mr.headers.get("Content-Encoding") is None and len(cuerpo) > 1000
            pr6 = urllib.request.urlopen(urllib.request.Request(base + ruta, headers={"Range": "bytes=0-99", "Accept-Encoding": "gzip"}))
            assert pr6.status == 206 and pr6.headers["Content-Range"] == f"bytes 0-99/{len(cuerpo)}" and pr6.read() == cuerpo[:100]
    assert get("/media/no-existe.mp4")[0] == 404 and get("/media/../../server.py.jpg")[0] == 404
    for ruta in ("/favicon.svg", "/favicon.ico"):
        fv = urllib.request.urlopen(base + ruta)
        assert fv.status == 200 and fv.headers["Content-Type"] == "image/svg+xml" and b"<svg" in fv.read()
    st =urllib.request.urlopen(urllib.request.Request(base + "/vendor/three.module.min.js", headers={"X-API-Key": "s3cr3t"}))
    assert st.status == 200 and st.headers["Content-Type"].startswith("text/javascript") and "max-age=31536000" in st.headers["Cache-Control"]
    pr = urllib.request.urlopen(urllib.request.Request(base + "/presentacion.js", headers={"X-API-Key": "s3cr3t"}))
    assert "immutable" not in pr.headers["Cache-Control"] and "max-age=60" in pr.headers["Cache-Control"]
    pv = urllib.request.urlopen(base + "/presentacion.js?v=abc")
    assert "immutable" in pv.headers["Cache-Control"]
    ix = get("/")[1].decode()
    assert "__V__" not in ix and re.search(r"indice3d\.js\?v=[0-9a-f]{10}\b", ix)
    with tempfile.TemporaryDirectory() as td:  # la versión cambia con cualquier módulo propio
        tp = Path(td)
        (tp / "i.html").write_bytes(b"__V__")
        (tp / "a.js").write_bytes(b"1")
        v1 = pagina(tp / "i.html", tp)
        (tp / "a.js").write_bytes(b"2")
        assert v1 != pagina(tp / "i.html", tp) and b"__V__" not in v1
    with tempfile.TemporaryDirectory() as td:  # GLB: tipo, cache de un día sin immutable, auth, y "modelo" en la vitrina
        global MODELOS
        previo, MODELOS = MODELOS, Path(td)
        try:
            assert modelo("ypf-a") is None
            (MODELOS / "ypf-a.glb").write_bytes(b"glTF")
            m1 = modelo("ypf-a")
            assert re.fullmatch(r"modelos/ypf-a\.glb\?v=[0-9a-f]{10}", m1) and modelo("otro") is None
            (MODELOS / "ypf-a.glb").write_bytes(b"glTF-otro")
            assert modelo("ypf-a") != m1, "cambian los bytes → cambia ?v="
            (MODELOS / "ypf-a.glb").write_bytes(b"glTF")
            vm = vitrina(dv)["productos"][0]
            assert vm["producto_id"] == "ypf-a" and vm["modelo"] == m1
            assert all("modelo" in e and e["modelo"] is None for e in vm["competencia"]["equivalentes"])
            (MODELOS / "shell-s.glb").write_bytes(b"glTF")
            assert any(e["modelo"] for e in vitrina(dv)["productos"][0]["competencia"]["equivalentes"] if e["producto_id"] == "shell-s")
        finally:
            MODELOS = previo
    assert modelo("ypf-a") is None
    assert get("/vendor/three.module.min.js")[0] == 200 and get("/modelos/x.glb")[0] == 404 and get("/modelos/x.glb", {"X-API-Key": "s3cr3t"})[0] == 404 and get("/../server.py", {"X-API-Key": "s3cr3t"})[0] == 404 and get("/vendor/../../x.js", {"X-API-Key": "s3cr3t"})[0] == 404
    assert get("/api/ultimo", {"X-API-Key": "s3cr3t"})[0] == 200
    assert get("/api/ultimo", b("x:s3cr3t"))[0] == 200
    assert get("/api/obs?mes=2026-11&formato=csv", {"X-API-Key": "s3cr3t"})[1].startswith(b"fecha,fuente,url")
    k = {"X-API-Key": "s3cr3t"}
    assert json.loads(get("/api/indice", k)[1]) == c["indice"] and json.loads(get("/api/indice?mayoristas=1", k)[1]) == c["indice_con_mayoristas"]
    ipa = json.loads(get("/api/indice/pares")[1])
    assert ipa["productos"] == c["indice/pares"]["productos"] and ipa["dias"] == 30 and get("/api/indice/pares?formato=csv")[1].startswith(b"producto_id,nombre,") and get("/api/indice/pares?pais=CL")[0] == 400
    ce = json.loads(get("/api/indice/celdas?dias=30", k)[1])
    assert ce["hasta"] == "2026-11-03" and {x["marca"] for x in ce["celdas"]} == {"YPF", "Shell", "Gulf"}
    assert get("/api/indice/celdas?formato=csv")[1].startswith(b"segmento,sae,marca,") and get("/api/indice/celdas?pais=BR")[0] == 200 and get("/api/indice/celdas?pais=CL")[0] == 400
    assert all(get("/api/indice/celdas" + mal)[0] == 400 for mal in ("?dias=0", "?dias=367", "?dias=x", "?hasta=2026-13-01", "?hasta=ayer", "?hasta=2026-1-1"))
    assert "_cache_celdas" in Handler.datos and "precios_litro_usd" not in ce["celdas"][0]
    assert json.loads(get("/api/vitrina", k)[1]) == json.loads(json.dumps(c["vitrina"])) and c["vitrina"]["productos"][0]["producto_id"] == "ypf-a-10w40"
    assert json.loads(get("/api/vitrina?mayoristas=1", k)[1]) == json.loads(json.dumps(c["vitrina_con_mayoristas"]))
    assert get("/api/vitrina?formato=csv", k)[1].startswith(b"fecha,producto_id,nombre,") and get("/api/vitrina")[0] == 200
    assert get("/api/mercado")[0] == 200
    # ---------- /api/bi/*: modelo estrella para Power BI ----------
    def bi(t):
        cod, cuerpo = get("/api/bi/" + t, k)
        assert cod == 200 and cuerpo.startswith(chr(0xFEFF).encode()), t  # BOM: Power BI/Excel leen bien los acentos
        return list(csv.DictReader(io.StringIO(cuerpo.decode("utf-8-sig"))))
    for t in ("precios", "productos", "equivalencias", "fuentes", "provincias"):
        assert get("/api/bi/" + t)[0] == 200, t
    assert get("/api/bi/nada", k)[0] == 404 and get("/api/bi/precios?desde=ayer", k)[0] == 400
    ii = bi("indice")
    assert ii and list(ii[0]) == CAMPOS["bi_indice"] and {r["pais"] for r in ii} == {"AR"} and len(ii) == len(c["indice"])
    assert all(r["mediana_ypf_litro"] and round(float(r["mediana_litro"]) / float(r["mediana_ypf_litro"]) * 100, 1) == float(r["indice"]) for r in ii if r["indice"])
    assert len(bi("indice?mayoristas=1")) == len(c["indice_con_mayoristas"]) and bi("indice?desde=2026-12-01") == [] and bi("indice?pais=BR") == []
    ic = bi("indice_competencia")
    assert ic and list(ic[0]) == CAMPOS["bi_indice_competencia"] and len(ic) == len(bi_indice_competencia(Handler.datos)) and bi("indice_competencia?desde=2026-12-01") == []
    assert get("/api/bi/indice_competencia?desde=ayer", k)[0] == 400 and get("/api/bi/indice?desde=ayer", k)[0] == 400 and get("/api/bi/indice?pais=XX", k)[0] == 400
    bp = bi("precios")
    assert len(bp) == 8 and all(r["producto_id"] and r["capturado"] == "" for r in bp)  # filas sin hora: vacío, nunca inventada
    assert [r["fecha"] for r in bi("precios") if r["canal"] == "mayorista"] == ["2026-11-02"] and {r["pais"] for r in bp} == {"AR"}
    assert len(bi("precios?desde=2026-11-02")) == 5 and bi("precios?desde=2026-12-01") == []
    assert float(next(r for r in bp if r["producto_id"] == "ypf-a-10w40" and r["litros"] == "4")["precio_litro"]) == 4000 and bp[0]["precio_usd_litro"] == ""  # sin fx: vacío
    assert [(r["producto_id"], r["es_ypf"]) for r in bi("productos")] == [("ypf-a-10w40", "1"), ("shell-b-10w40", "0"), ("gulf-c-15w40", "0")]
    assert [(r["ypf_id"], r["comp_id"], r["tipo"]) for r in bi("equivalencias")] == [("ypf-a-10w40", "shell-b-10w40", "match_total")]
    assert {r["fuente"]: (r["tipo"], r["ultima_fecha"]) for r in bi("fuentes")}["shopify_datri"] == ("mayorista", "2026-11-02")
    bpv = {r["codigo"]: r for r in bi("provincias")}
    assert bpv["AR-X"]["nombre"] == "Córdoba" and bpv["AR-X"]["region"] == "Pampeana" and bpv["online"]["online"] == "1" and bpv["BR-PR"]["pais"] == "BR"
    # diccionario: toda columna de cada tabla del paquete tiene su fila y viceversa; el paquete trae un CSV por tabla con BOM y nombres fijos
    dic = bi("diccionario")
    assert list(dic[0]) == CAMPOS["bi_diccionario"] and all(r["descripcion"] and r["tipo"] in ("texto", "entero", "decimal", "fecha", "fecha_hora", "booleano") for r in dic)
    assert {(r["tabla"], r["columna"]) for r in dic} == {(t, c_) for t in TABLAS_BI for c_ in CAMPOS["bi_" + t]} and len(dic) == len({(r["tabla"], r["columna"]) for r in dic})
    assert canal("grok_enausa") == "mayorista" and canal("grok_helix") == "grok" and bi("fx") == [] or list(bi("fx")[0]) == CAMPOS["bi_fx"]
    import zipfile
    zc, zb = get("/api/bi/paquete.zip", k)
    zf = zipfile.ZipFile(io.BytesIO(zb))
    assert zc == 200 and sorted(zf.namelist()) == sorted([t + ".csv" for t in TABLAS_BI] + ["diccionario.csv", "LEEME.txt"])
    for nm in zf.namelist():
        assert zf.read(nm).startswith(chr(0xFEFF).encode()), nm
    zr = list(csv.DictReader(io.StringIO(zf.read("indice.csv").decode("utf-8-sig"))))
    assert len(zr) == len(c["indice"]) and len(list(csv.DictReader(io.StringIO(zf.read("precios.csv").decode("utf-8-sig"))))) == len(bp)
    assert "Ultimo dato" in zf.read("LEEME.txt").decode("utf-8-sig") and b"\\" not in zf.read("LEEME.txt") and get("/api/bi/paquete.zip")[0] == 200
    dg = {"obs_base": [], "grok_meses": {"m": [{**dict.fromkeys(GROK_ALM_F, ""), "tipo": "producto", "cargado": "2026-11-18T14:05:00Z"}]}}
    integrar_grok(dg)
    assert dg["obs"][0]["capturado"] == "2026-11-18T14:05:00Z"
    mj = json.loads(get("/api/mercado", k)[1])
    mq = {m["marca"]: m for m in mj["marcas"]}
    assert (mq["YPF"]["desde"], mq["YPF"]["hasta"]) == ("2025-09", "2026-09") and mq["Gulf"]["hasta"] == "2023-01" and mq["Puma"]["empresa_se"] == "(no declara)"
    og = {e["empresa"]: e["origen"] for e in mj["share"]["empresas"]}
    assert og["YPF"]["fuente"] == "SE (SESCO) — empresa declarante YPF" and og["YPF"]["razones_sociales"] == ["YPF"] and og["YPF"]["marcas"] == ["YPF"]
    assert og["Shell/Raízen"]["razones_sociales"] == ["SHELL", "RAIZEN"] and og["Shell/Raízen"]["marcas"] == ["Shell"]
    assert (og["YPF"]["desde"], og["YPF"]["hasta"]) == ("2025-09", "2026-09") and og["YPF"]["dataset"].endswith("5bdc436c-60d4-4c86-98ab-59834d047700")
    assert og["Otras"]["razones_sociales"] == ["F", "Z1", "Z2"] and og["Otras"]["filas_url"] is None
    assert origen(d, "PAE/Axion")["razones_sociales"] == ["PAN AMERICAN ENERGY", "AXION", "ESSO"] and "Castrol (desde 2019)" in origen(d, "PAE/Axion")["marcas"]
    assert mj["share"]["producto"] == "Lubricantes automotrices(m3)" and mj["share"]["empresas"][0]["empresa"] == "YPF" and len(mj["actividad"]) == 7
    assert mj["compuestos"]["notas"]["demanda_potencial"].startswith("pesos supuestos")
    mg = json.loads(get("/api/mercado?producto=grasas", k)[1])["share"]
    assert mg["producto"] == "Grasas(Ton)" and mg["empresas"][0]["ultimo"] == 1.0 and get("/api/mercado?producto=nada", k)[0] == 400
    assert json.loads(get("/api/mercado/share?canal=" + urllib.parse.quote("Al Público"), k)[1])["empresas"][0]["ultimo"] == round(100 / 202, 6)
    assert get("/api/mercado/share?canal=Nada", k)[0] == 404
    # multi-selección: lubricantes (m3) se suman, Grasas (Ton) nunca con m3; compatibilidad con un solo valor
    ms2 = json.loads(get("/api/mercado/share?producto=automotrices,industriales&canal=Agro", k)[1])
    assert ms2["productos"] == ["automotrices", "industriales"] and ms2["producto"] == "Lubricantes automotrices + industriales(m3)" and ms2["canal"] == "Agro"
    y2 = ms2["empresas"][0]
    assert y2["empresa"] == "YPF" and y2["volumen_ultimo"] == 40 and y2["ultimo"] == 0.8 and ms2["total"][-1] == 50 and ms2["total"][-2] is None   # (10 + 30) / (10 + 30 + 10)
    mc2 = json.loads(get("/api/mercado/share?producto=automotrices,industriales&canal=Agro,Al%20P%C3%BAblico&completo=1", k)[1])
    assert mc2["canal"] == ["Agro", "Al Público"] and mc2["total"][-1] == 50 + 202
    assert get("/api/mercado/share?producto=automotrices,grasas", k)[0] == 400 and get("/api/mercado?producto=industriales,grasas", k)[0] == 400
    assert get("/api/mercado/share?producto=automotrices,nada", k)[0] == 400 and get("/api/mercado/share?canal=Agro,Nada", k)[0] == 404
    assert b"2026-09,YPF,40.0,50.0,0.8" in get("/api/mercado/share?producto=automotrices,industriales&canal=Agro&formato=csv", k)[1]
    assert json.loads(get("/api/mercado?producto=automotrices,industriales&canal=Agro", k)[1])["share"]["empresas"][0]["volumen_ultimo"] == 40
    assert json.loads(get("/api/mercado/share?producto=industriales", k)[1])["empresas"][0]["volumen_ultimo"] == 30 and get("/api/mercado/perdidas?producto=grasas,automotrices", k)[0] == 400
    assert json.loads(get("/api/mercado/share", k)[1])["empresas"][0]["origen"]["marcas"] == ["YPF"]
    assert json.loads(get("/api/mercado/share?completo=1", k)[1])["meses"][0] == "2025-09"
    cv = json.loads(get("/api/mercado/share?completo=1", k)[1])
    assert all(len(e["volumen"]) == len(cv["meses"]) == len(e["serie"]) for e in cv["empresas"]) and mj["share"]["empresas"][0]["volumen"][-1] == mj["share"]["empresas"][0]["volumen_ultimo"]
    # por marca: solo rótulo y precisión; los números son los mismos que por empresa
    se_, sm_ = (json.loads(get("/api/mercado/share" + x, k)[1]) for x in ("", "?por=marca"))
    quitar = lambda es: [{a: b for a, b in e.items() if a not in ("marca", "precision")} for e in es]
    assert quitar(sm_["empresas"]) == se_["empresas"] and sm_["meses"] == se_["meses"] and sm_["total"] == se_["total"] and sm_["provincias"] == se_["provincias"]
    assert sm_["empresas"][0]["marca"] == "YPF (Elaion, Extravida, ROD)" and sm_["empresas"][0]["precision"] == "exacto" and "marca" not in se_["empresas"][0]
    assert quitar(json.loads(get("/api/mercado?por=marca", k)[1])["share"]["empresas"]) == quitar(mj["share"]["empresas"]) and get("/api/mercado/share?por=x", k)[0] == 400
    cm_ = json.loads(get("/api/mercado/share?completo=1&por=marca", k)[1])
    assert quitar(cm_["empresas"]) == json.loads(get("/api/mercado/share?completo=1", k)[1])["empresas"]
    rp_ = rotulos(d, "PAE/Axion")
    assert rotulo_en(rp_, "2018-12")["marca"].startswith("Axion/Esso") and rotulo_en(rp_, "2019-01")["marca"] == "Castrol + Axion (no separable)" and rotulo_en(rp_, "2019-01")["precision"] == "agrupado"
    fake = {"meses": ["2018-12", "2019-01"], "empresas": [{"empresa": "PAE/Axion"}, {"empresa": "Otras"}]}
    etiquetar(d, fake, True)
    assert fake["empresas"][0]["marca_mes"] == [rp_[0]["marca"], rp_[1]["marca"]] and fake["empresas"][0]["marca"] == rp_[1]["marca"] and fake["empresas"][1]["marca"] == "Otras" and "marca_mes" not in fake["empresas"][1]
    assert origen(d, "PAE/Axion")["rotulos"] == rp_ and origen(d, "TotalEnergies")["rotulos"][0]["precision"] == "agrupado"
    assert get("/api/mercado/share?formato=csv", k)[1].startswith(b"mes,empresa,volumen,total,share\n2025-09,YPF,120")
    pj = json.loads(get("/api/mercado/perdidas?ventana=mes&min=0", k)[1])
    assert pj["origenes"]["YPF"]["filas_url"] == "/api/mercado/filas?empresa=YPF" and pj["origenes"]["A"]["razones_sociales"] == ["A"]
    assert pj["foco"]["delta_ypf"] == -10 and pj["fuente"]["dataset"].startswith("https://datos.energia.gob.ar/dataset/5bdc436c") and get("/api/mercado/perdidas")[0] == 200
    assert get("/api/mercado/perdidas?ventana=anterior", k)[0] == 200 and get("/api/mercado/perdidas?ventana=x", k)[0] == 400 and get("/api/mercado/perdidas?min=-1", k)[0] == 400 and get("/api/mercado/perdidas?producto=nada", k)[0] == 400
    assert json.loads(get("/api/mercado/perdidas?desde=2026-09&hasta=2026-09&vs=12m&min=0", k)[1])["foco"]["delta_ypf"] == -10
    for mal in ("desde=2026-09", "desde=2026-09&hasta=2026-09&ventana=mes", "vs=12m", "desde=2026-10&hasta=2026-09", "desde=2026-08&hasta=2026-09&vs=2025-09:2025-09", "desde=2020-01&hasta=2020-01"):
        assert get("/api/mercado/perdidas?" + mal, k)[0] == 400, mal
    assert get("/api/mercado/perdidas?canal=Nada", k)[0] == 404 and get("/api/mercado/perdidas?pais=BR", k)[0] == 400
    assert json.loads(get("/api/mercado/perdidas?ventana=mes&canal=Agro&provincia=C%C3%B3rdoba", k)[1])["foco"]["total_t"] == 10
    pq = "/api/mercado/perdidas?ventana=mes&min=0&producto=automotrices,industriales&canal=Agro,Al%20P%C3%BAblico&provincia=C%C3%B3rdoba,Salta"
    pr_ = json.loads(get(pq, k)[1])
    assert pr_["productos"] == ["automotrices", "industriales"] and pr_["foco"]["total_t"] == 247 and pr_["foco"]["ypf_t"] == 140 and get(pq + ",Nada", k)[0] == 404
    assert get("/api/mercado/perdidas?producto=grasas,industriales", k)[0] == 400 and get("/api/mercado/perdidas?producto=todos&canal=todos&provincia=", k)[0] == 200
    assert get("/api/mercado/filas?producto=automotrices,industriales&canal=Agro,Al%20P%C3%BAblico&provincia=C%C3%B3rdoba,Salta&desde=2026-09&hasta=2026-09", k)[1].count(b"\n") == 1 + sum(
        1 for f in d["energia"] if f[0] == "2026-09" and f[2] in ("Lubricantes automotrices(m3)", "Lubricantes industriales(m3)") and f[3] in ("Agro", "Al Público") and f[4] in ("Córdoba", "Salta"))
    fc = get("/api/mercado/filas?producto=grasas", k)[1]
    assert fc.startswith(b"\xef\xbb\xbfmes,empresa,producto,canal,provincia,cantidad\n2026-09,YPF,Grasas(Ton),") and get("/api/mercado/filas?desde=2026-13", k)[0] == 400
    assert get("/api/mercado/filas?empresa=YPF&canal=Agro&desde=2026-09&hasta=2026-09", k)[1].count(b"\n") == 3 and get("/api/mercado/filas")[0] == 200
    assert [x["id"] for x in json.loads(get("/api/macro", k)[1])][:3] == ["A", "B", "C"] and get("/api/macro?ids=A,zzz", k)[0] == 404
    ma = json.loads(get("/api/macro?ids=A,B", k)[1])
    assert [m["id"] for m in ma] == ["A", "B"] and ma[0]["serie"][1] == {"fecha": "2026-07-01", "valor": None, "signo": "..."}
    assert get("/api/macro?ids=A&formato=csv", k)[1].decode().splitlines()[:3] == ["fecha,id,valor,signo", "2026-06-01,A,1.5,*", "2026-07-01,A,,..."]
    assert get("/api/obs", {"X-API-Key": "s3cr3t"})[0] == 400
    assert get("/api/serie?p=nada", {"X-API-Key": "s3cr3t"})[0] == 404
    assert get("/../server.py", {"X-API-Key": "s3cr3t"})[0] == 404
    assert get("/site/index.html", {"X-API-Key": "s3cr3t"})[0] == 404
    assert get("/ml-callback?code=TG-x")[0] == 200 and get("/ml-callback.html")[0] == 404   # la Redirect URI de ML, solo por su ruta
    # ---------- /api/provincias, /api/reventa, /api/cobertura por HTTP: con y sin clave ----------
    for ruta in ("/api/provincias?producto_id=ypf-a-10w40", "/api/provincias", "/api/reventa?producto_id=ypf-a-10w40", "/api/cobertura"):
        assert get(ruta)[0] in (200, 400), ruta
    cod, cuerpo = get("/api/provincias?producto_id=ypf-a-10w40", k)
    assert cod == 200 and json.loads(cuerpo)["celdas"] == [] and json.loads(cuerpo)["n_sin_provincia"] > 0   # el CSV de prueba es de antes de la columna: sin provincia, sin celda
    assert get("/api/provincias?producto_id=nada", k)[0] == 404 and get("/api/provincias?dias=0", k)[0] == 400 and get("/api/provincias?dias=x", k)[0] == 400
    assert json.loads(get("/api/provincias", k)[1])["productos"][0]["producto_id"] == "ypf-a-10w40"
    cod, cuerpo = get("/api/reventa?producto_id=ypf-a-10w40", k)
    assert cod == 200 and [e["producto_id"] for e in json.loads(cuerpo)["equivalentes"]] == ["shell-b-10w40"] and len(json.loads(cuerpo)["ypf"]["observaciones"]) > 0
    assert get("/api/reventa", k)[0] == 400 and get("/api/reventa?producto_id=shell-b-10w40", k)[0] == 400 and get("/api/reventa?producto_id=nada", k)[0] == 404
    assert get("/api/reventa?producto_id=ypf-a-10w40&formato=csv", k)[1].startswith(b"rol,producto_id,marca")
    cod, cuerpo = get("/api/cobertura", k)
    assert cod == 200 and json.loads(cuerpo)["total"]["productos_ypf"] == 1 and get("/api/cobertura?formato=csv", k)[1].startswith(b"producto_id,nombre")
    assert get("/api/provincias?producto_id=ypf-a-10w40&formato=csv", k)[1].startswith(b"producto_id,provincia,region,")
    assert json.loads(get("/api/reventa?producto_id=ypf-a-10w40&desde=2026-11-01&hasta=2026-11-05", k)[1])["dias"] == 5
    assert json.loads(get("/api/provincias?desde=2026-11-01&hasta=2026-11-05", k)[1])["dias"] == 5
    for mal in ("&desde=2026-11-05&hasta=2026-11-01", "&desde=x", "&desde=2024-01-01&hasta=2026-01-01"):
        assert get("/api/provincias?producto_id=ypf-a-10w40" + mal, k)[0] == 400 and get("/api/reventa?producto_id=ypf-a-10w40" + mal, k)[0] == 400, mal
    # ---------- /api/puesto: precio + envío del mismo día, ventana 7 días, sin arrastre ----------
    cod, cuerpo = get("/api/puesto?producto_id=ypf-a-10w40")  # lectura abierta
    pu_ = json.loads(cuerpo)
    cel_ = {(c["provincia"], c["fuente"]): c for c in pu_["celdas"]}
    assert cod == 200 and (pu_["desde"], pu_["hasta"], pu_["dias"]) == ("2026-11-14", "2026-11-20", 7) and ("AR-S", "ml") not in cel_
    x_ = cel_[("AR-X", "ml")]
    assert (x_["n"], x_["minimo"]["precio_puesto"], x_["minimo"]["envio"], x_["minimo"]["url"], x_["cp"]) == (2, 16000, 0, A_, "5000")   # A gratis (4000/L) y B con la opción más barata (24000/4 = 6000/L)
    assert (x_["minimo_litro_puesto"], x_["mediana_litro_puesto"], x_["fecha"]) == (4000, 5000, "2026-11-20") and x_["avisos"][1]["precio_puesto"] == 24000
    v_, r_, n_ = cel_[("AR-V", "ml")], cel_[("AR-R", "ml")], cel_[("AR-N", "ml")]
    assert (v_["minimo"], v_["n"], v_["n_sin_cotizacion"], v_["n_no_envia"], v_["mediana_litro_puesto"]) == (None, 0, 1, 0, None)   # sin cotización: sin precio, con su motivo
    assert (r_["minimo"], r_["n_no_envia"], r_["n_sin_cotizacion"]) == (None, 1, 0) and (n_["n"], n_["n_sin_cotizacion"], n_["minimo"]["precio_puesto"], n_["fecha"]) == (1, 0, 21000, "2026-11-18")
    assert "AR-C" not in {p for p, _ in cel_} and len(pu_["celdas"]) == 4   # provincia sin filas: no hay celda (el visor dice «sin datos en la ventana»)
    assert json.loads(get("/api/puesto?producto_id=ypf-a-10w40&dias=366")[1])["celdas"][0]["provincia"] == "AR-N" and ("AR-S", "ml") in {(c["provincia"], c["fuente"]) for c in json.loads(get("/api/puesto?producto_id=ypf-a-10w40&dias=366")[1])["celdas"]}
    assert get("/api/puesto?producto_id=ypf-a-10w40&formato=csv")[1].startswith(b"producto_id,provincia,cp,fuente,precio_puesto,")
    for mal in ("", "?producto_id=nada", "?producto_id=ypf-a-10w40&dias=6", "?producto_id=ypf-a-10w40&dias=367", "?producto_id=ypf-a-10w40&dias=x", "?producto_id=ypf-a-10w40&pais=BR"):
        assert get("/api/puesto" + mal)[0] == 400, mal
    assert json.loads(get("/api/puesto?producto_id=shell-b-10w40")[1])["celdas"] == []   # producto sin cotizaciones: vacío, no inventado
    assert puesto({"envios": [], "obs": [], "cp": []}, "x")["celdas"] == [] and "token" not in json.dumps(pu_).lower()
    vd_ = puesto({"envios": [dict(ENV[0])], "obs": [dict(fuente="ml", url=A_, fecha="2026-11-20", vendedor="55 tienda:7")], "cp": []}, "ypf-a-10w40")["celdas"][0]
    assert vd_["minimo"]["vendedor"] == "55 tienda:7"   # el vendedor sale de obs por url + fecha
    # Norauto: otra fuente de envíos, celda aparte de ML; su vendedor sale de SUS obs; no_envia es un dato (n_no_envia), no un precio
    NA_ = "https://www.norauto.com.ar/helix-1/p"
    nv_ = lambda pv, co, me, es="ok": dict(ENV[0], fuente="vtex_norauto", url=NA_, provincia_destino=pv, costo_envio=co, metodo=me, estado=es, precio="16000")
    dn_ = {"envios": [dict(ENV[0]), nv_("AR-X", "30631", "domicilio"), nv_("AR-A", "", "", "no_envia")],
           "obs": [dict(fuente="ml", url=A_, fecha="2026-11-20", vendedor="ML-V"), dict(fuente="vtex_norauto", url=NA_, fecha="2026-11-20", vendedor="Norauto")], "cp": []}
    cn_ = {(c["provincia"], c["fuente"]): c for c in puesto(dn_, "ypf-a-10w40")["celdas"]}
    assert set(cn_) == {("AR-X", "ml"), ("AR-X", "vtex_norauto"), ("AR-A", "vtex_norauto")} and cn_[("AR-X", "ml")]["minimo"]["vendedor"] == "ML-V"
    assert cn_[("AR-X", "vtex_norauto")]["minimo"]["vendedor"] == "Norauto" and cn_[("AR-X", "vtex_norauto")]["minimo"]["precio_puesto"] == 46631
    assert (cn_[("AR-A", "vtex_norauto")]["minimo"], cn_[("AR-A", "vtex_norauto")]["n_no_envia"]) == (None, 1) and NOMBRE_FUENTE["vtex_norauto_envios"].startswith("Norauto")
    # filtro por método: Norauto AMBA con retiro a $0 y domicilio 13452; sin filtro gana el retiro, con metodo=domicilio el domicilio
    nm_ = lambda co, me, de: dict(nv_("AR-C", co, me), deposito=de)
    dm_ = {"envios": [nm_("0", "retiro", "Norauto Lomas"), nm_("13452", "domicilio", "AMBA")],
           "obs": [dict(fuente="vtex_norauto", url=NA_, fecha="2026-11-20", vendedor="Norauto")], "cp": []}
    sf_, cd_ = puesto(dm_, "ypf-a-10w40")["celdas"][0]["minimo"], puesto(dm_, "ypf-a-10w40", metodo="domicilio")
    assert (sf_["metodo"], sf_["envio"], sf_["deposito"]) == ("retiro", 0, "Norauto Lomas") and cd_["metodo"] == "domicilio"
    assert (cd_["celdas"][0]["minimo"]["envio"], cd_["celdas"][0]["minimo"]["metodo"], cd_["celdas"][0]["n"]) == (13452, "domicilio", 1)
    assert puesto(dm_, "ypf-a-10w40", metodo="agencia")["celdas"] == [] and puesto(dm_, "ypf-a-10w40")["metodo"] is None
    assert json.loads(get("/api/puesto?producto_id=ypf-a-10w40&metodo=domicilio")[1])["metodo"] == "domicilio" and get("/api/puesto?producto_id=ypf-a-10w40&metodo=volando")[0] == 400
    # Correo Argentino: aviso con origen (SEPA AR-X, o tienda online con origen declarado) + tarifa capital → capital
    ob_ = lambda fu, pv, li, pr, ur="": dict(fuente=fu, url=ur, ean="", titulo="t" + fu + pv + li, vendedor="v" + fu, litros=li, unidades="1", provincia=pv, fecha="2026-11-20",
                                              precio=pr, producto_id="ypf-a-10w40", pais="AR", sucursal="")
    tf_ = lambda co, cd, me, pr, fe="2026-11-18": dict(fecha=fe, cp_origen=co, cp_destino=cd, litros="4", metodo=me, producto="Correo Argentino Clasico", precio=pr, plazo_min="2", plazo_max="4", estado="ok")
    dc_ = {"envios": [], "cp": [{"provincia": "AR-X", "cp": "5000"}, {"provincia": "AR-C", "cp": "1001"}, {"provincia": "AR-V", "cp": "9410"}],
           "obs": [ob_("sepa", "AR-X", "4", "40000"), ob_("tn_lspalermo", "online", "4", "44000", "https://ls/p"), ob_("ml", "online", "4", "30000", "https://ml/p"), ob_("sepa", "AR-X", "2", "20000")],
           "envases_correo": [{"litros": "4"}], "origen_fuentes": [{"fuente": "tn_lspalermo", "provincia": "AR-C"}],
           "correo": [tf_("5000", "1001", "domicilio", "6000"), tf_("5000", "1001", "sucursal", "4000"), tf_("1001", "1001", "domicilio", "3000"), tf_("5000", "9410", "domicilio", "1", "2026-11-01")]}
    pc_ = puesto(dc_, "ypf-a-10w40")
    cc_ = {c["provincia"]: c for c in pc_["celdas"] if c["fuente"] == "correo_ar"}
    m_ = cc_["AR-C"]["minimo"]
    assert (m_["precio_puesto"], m_["metodo"], m_["origen_provincia"], m_["origen_fuente"], m_["deposito"], m_["plazo"]) == (44000, "retiro", "AR-X", "sepa", "Correo Argentino Clasico", "2 a 4 días")
    assert (cc_["AR-C"]["minimo_litro_puesto"], cc_["AR-C"]["n"], cc_["AR-C"]["mediana_litro_puesto"]) == (11000, 2, 11375)  # online sin origen (ML) y 2 L (fuera de la tabla) no participan
    assert pc_["correo"] == {"avisos": 2, "sin_origen": 1, "sin_envase": 1} and pc_["hasta"] == "2026-11-20"
    assert (cc_["AR-V"]["minimo"], cc_["AR-V"]["n_sin_cotizacion"]) == (None, 2) and cc_["AR-X"]["minimo"] is None  # tarifa de 20 días: no se usa; sin tarifa, celda sin precio y con su motivo
    ad_ = {a["origen_provincia"]: a for a in cc_["AR-C"]["avisos"]}
    assert ad_["AR-C"]["origen_declarado"] is True and ad_["AR-X"]["origen_declarado"] is False and ad_["AR-C"]["precio_puesto"] == 47000
    pd_ = {c["provincia"]: c for c in puesto(dc_, "ypf-a-10w40", metodo="domicilio")["celdas"] if c["fuente"] == "correo_ar"}["AR-C"]
    assert (pd_["minimo"]["metodo"], pd_["minimo"]["precio_puesto"], pd_["n"]) == ("domicilio", 46000, 2)  # ?metodo=domicilio: solo D
    pr_ = {c["provincia"]: c for c in puesto(dc_, "ypf-a-10w40", metodo="retiro")["celdas"] if c["fuente"] == "correo_ar"}["AR-C"]
    assert (pr_["minimo"]["metodo"], pr_["n"], pr_["n_sin_cotizacion"]) == ("retiro", 1, 1) and puesto(dc_, "ypf-a-10w40", metodo="agencia")["celdas"] == []
    assert puesto({k: v for k, v in dc_.items() if k not in ("correo", "_cache_correo")}, "ypf-a-10w40")["celdas"] == [] and NOMBRE_FUENTE["correo_ar"].startswith("Correo Argentino")
    cod, cuerpo = get("/api/producto?producto_id=ypf-a-10w40")  # lectura abierta
    pj_ = json.loads(cuerpo)
    assert cod == 200 and pj_["producto"]["es_ypf"] and [e["producto_id"] for e in pj_["equivalentes"]] == ["shell-b-10w40"] and pj_["publicaciones"] and "metodo" in pj_
    assert get("/api/producto?producto_id=ypf-a-10w40&formato=csv")[1].startswith(b"rol,producto_id,marca")
    for mal in ("", "?producto_id=nada", "?producto_id=ypf-a-10w40&dias=0", "?producto_id=ypf-a-10w40&dias=367", "?producto_id=ypf-a-10w40&dias=x",
                "?producto_id=ypf-a-10w40&umbral=x", "?producto_id=ypf-a-10w40&umbral=nan"):
        assert get("/api/producto" + mal)[0] == 400, mal
    assert json.loads(get("/api/producto?producto_id=ypf-a-10w40&umbral=10")[1])["umbral_pct"] == 10
    base_ = "/api/producto?producto_id=ypf-a-10w40"
    ult_ = pj_["datos"]["hasta"]
    rg_ = json.loads(get(f"{base_}&desde={ult_}&hasta={ult_}&dias=7")[1])["ventana"]
    assert rg_ == {"dias": 1, "desde": ult_, "hasta": ult_} and json.loads(get(f"{base_}&desde={ult_}")[1])["ventana"]["hasta"] == ult_
    assert get(f"{base_}&desde={ult_}&hasta={ult_}&formato=csv")[0] == 200
    for mal in ("&desde=2026-11-05&hasta=2026-11-01", "&desde=2025-01-01&hasta=2026-11-05", "&desde=2026-13-01", "&hasta=ayer", "&desde=2026-1-1"):
        assert get(base_ + mal)[0] == 400, mal
    assert json.loads(get(base_ + "&dias=3")[1])["ventana"] == pj_["ventana"]
    # ---------- carga de Grok (sin red: BAJAR y GH son fakes) ----------
    global BAJAR, GH
    hoy_s = date.today().isoformat()
    sit = {"grok_helix": "www.helixturno.com.ar", "grok_otro": "otro.com.ar"}
    U = "https://www.helixturno.com.ar/combos"

    def fila(**kw):
        r = dict(fecha=hoy_s, fuente="grok_helix", url=U, titulo="Combo Helix HX7 10W-40 4L", marca="Shell", precio="84999",
                 precio_lista="", litros="4", unidades="1", tipo="producto", detalle="filtro; mano de obra")
        r.update(kw)
        return r

    def csv_de(*filas, cab=GROK_F):
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(cab)
        for r in filas:
            w.writerow([r.get(c, "") for c in cab])
        return buf.getvalue()

    hoy_d = date.today()
    f_, e_, fatal = validar_csv(csv_de(fila(), cab=["fecha", "fuente"]), hoy_d, sit)
    assert "encabezado" in fatal and not f_                                  # encabezado malo: nada se guarda
    assert "encabezado" in validar_csv("", hoy_d, sit)[2]
    f_, e_, fatal = validar_csv(csv_de(*[fila(titulo=f"c{i}") for i in range(501)]), hoy_d, sit)
    assert "500" in fatal and not f_                                         # más de 500 filas
    malas = [fila(url="https://malo.com/x"), fila(fuente="grok_otro"), fila(precio="0"), fila(precio="-5"), fila(precio="abc"),
             fila(fecha=(hoy_d - timedelta(days=4)).isoformat()), fila(fecha="2026-13-40"), fila(url="http://www.helixturno.com.ar/combos"),
             fila(tipo="otra"), fila(fuente="helix"), fila(precio_lista="x")]
    f_, e_, fatal = validar_csv(csv_de(*malas, fila()), hoy_d, sit)
    assert not fatal and len(f_) == 1 and [x["fila"] for x in e_] == list(range(1, 12)), e_
    assert "lista blanca" in e_[0]["error"] and "no corresponde" in e_[1]["error"] and "precio" in e_[2]["error"]
    assert "usar grok_helix" in e_[1]["error"] and "usar grok_helix" in e_[9]["error"], e_   # el error dice qué fuente va
    assert "3 días" in e_[5]["error"]
    assert validar_csv(csv_de(fila(fecha=(hoy_d - timedelta(days=3)).isoformat())), hoy_d, sit)[0]
    assert validar_csv(csv_de(fila()).replace("84999", "84999,5"), hoy_d, sit)[1][0]["fila"] == 1  # coma sin comillas: columnas de más

    f_, e_, fatal = validar_csv(csv_de(fila(provincia="Córdoba"), fila(titulo="o", provincia="online"), fila(titulo="v"), cab=GROK_PROV_F), hoy_d, sit)
    assert not fatal and not e_ and [x["provincia"] for x in f_] == ["AR-X", "online", ""]            # encabezado de 12: nombre → ISO, online, vacío
    f_, e_, fatal = validar_csv(csv_de(fila()), hoy_d, sit)
    assert not fatal and not e_ and f_[0]["provincia"] == ""                                         # encabezado de 11 (la Task diaria): sigue valiendo
    f_, e_, fatal = validar_csv(csv_de(fila(provincia="Narnia"), fila(titulo="b", provincia="GBA"), fila(titulo="c", provincia="AR-S"), cab=GROK_PROV_F), hoy_d, sit)
    assert [x["fila"] for x in e_] == [1, 2] and "provincia" in e_[0]["error"] and [x["provincia"] for x in f_] == ["AR-S"]   # inválida: se rechaza con motivo
    assert len(clave_grok(fila(provincia="AR-S"))) == 8 and clave_grok(fila(provincia="AR-S")) != clave_grok(fila(provincia="AR-X"))
    assert clave_grok(fila(pais="BR", moneda="BRL")) != clave_grok(fila()) and clave_grok(fila(pais="AR", moneda="ARS")) == clave_grok(fila())  # AR/ARS = lo de siempre
    # encabezado de 14 (pais, moneda): ISO validado; sin las columnas o vacías = AR/ARS; la provincia es del país de la fila
    f_, e_, fatal = validar_csv(csv_de(fila(provincia="BR-PR", pais="BR", moneda="BRL"), fila(titulo="b", provincia="BR-PR"), fila(titulo="c", pais="XX"),
                                       fila(titulo="d", moneda="EUR"), fila(titulo="e", pais="BR", provincia="AR-X"), fila(titulo="f", pais="br"),
                                       fila(titulo="g", provincia="AR-S"), cab=GROK_PAIS_F), hoy_d, sit)
    assert not fatal and [x["fila"] for x in e_] == [2, 3, 4, 5], e_
    assert [(x["pais"], x["moneda"], x["provincia"]) for x in f_] == [("BR", "BRL", "BR-PR"), ("BR", "BRL", ""), ("AR", "ARS", "AR-S")], f_
    assert "pais" in e_[1]["error"] and "moneda" in e_[2]["error"] and "provincia" in e_[3]["error"] and "BR" in e_[3]["error"]
    f_, e_, fatal = validar_csv(csv_de(fila(provincia="Córdoba"), cab=GROK_PROV_F), hoy_d, sit)
    assert not e_ and (f_[0]["pais"], f_[0]["moneda"]) == ("AR", "ARS")                                # encabezado de 12: AR/ARS
    f_, e_, fatal = validar_csv(csv_de(fila()), hoy_d, sit)
    assert not e_ and (f_[0]["pais"], f_[0]["moneda"]) == ("AR", "ARS")                                # encabezado de 11: AR/ARS
    for t, p in [("$ 84.999", 84999), ("  84999  ", 84999), ("84999,00", 84999), ("84.999,00", 84999), ("84,999", 84999),
                 ("precio 84999.00", 84999), ("$84.999,50", 84999.5)]:
        assert precio_en_texto(p, t), (t, p)
    assert not precio_en_texto(84999, "184.999 y 849990 y 84.9995") and not precio_en_texto(84999, "sin precio") and not precio_en_texto(1000, "21000")

    # persistencia con Contents API falsa
    llamadas = []

    def gh_fake(metodo, ruta, token, cuerpo=None):
        llamadas.append((metodo, ruta, token, cuerpo))
        if metodo == "GET":
            return (200, {"sha": "viejo"})
        return 201, {"commit": {"sha": "abc123"}}
    BAJAR, GH = (lambda url: "<html>Combo HX7 $ 84.999 con filtro</html>"), gh_fake
    norm_real = normalizar.normalizar
    norm_fake = lambda t, m="", e="", reglas=None, url="", pais="AR": dict(
        marca="Shell", sae="10W-40", litros=4.0, unidades=1, producto_id="shell-b-10w40" if "HX7" in t else "", match="texto" if "HX7" in t else "none")
    normalizar.normalizar = norm_fake
    token_ant = os.environ.pop("GH_CARGA_TOKEN", None)
    try:
        d2 = cargar(raiz)
        cuerpo = csv_de(fila(), fila(titulo="Combo cambio de aceite", tipo="servicio", precio="50000", litros="", unidades=""),
                        fila(titulo="Combo HX7 5L", precio="99999", litros="5"))  # 99999 no está en la página
        cod, rsp = procesar_carga(d2, raiz, cuerpo)
        assert cod == 200 and rsp["ok"] == 3 and rsp["verificadas"] == 1 and rsp["commit"] == "solo local" and not llamadas, rsp
        assert [x["verificado"] for x in rsp["filas"]] == [True, False, False]
        archivo = raiz / "data" / "grok" / (hoy_s[:7] + ".csv")
        filas_a = leer_csv(archivo)
        assert len(filas_a) == 3 and list(filas_a[0]) == GROK_ALM_F and filas_a[0]["cargado"].endswith("Z")
        cod, rsp = procesar_carga(d2, raiz, cuerpo)                           # idempotente: mismas 3 filas
        assert cod == 200 and len(leer_csv(archivo)) == 3 and len(d2["grok"]) == 3
        # servicio ≠ producto; verificado=0 fuera del índice pero visible en ultimo
        c2 = calcular(d2)
        assert [r["titulo"] for r in c2["servicios"]] == ["Combo cambio de aceite"] and c2["servicios"][0]["verificado"] == "0"
        assert not any(r["titulo"] == "Combo cambio de aceite" for r in d2["obs"])
        u2 = {(r["fuente"], r["litros"]): r for r in c2["ultimo"] if r["fuente"] == "grok_helix"}
        assert u2[("grok_helix", 4.0)]["verificado"] == "1" and u2[("grok_helix", 5.0)]["verificado"] == "0"
        assert u2[("grok_helix", 4.0)]["precio_litro"] == round(84999 / 4, 2) and u2[("grok_helix", 4.0)]["url"] == U
        ix = [r for r in c2["indice"] if r["fecha"] == hoy_s and r["marca"] == "Shell"]
        assert len(ix) == 1 and ix[0]["n"] == 1 and ix[0]["mediana_litro"] == round(84999 / 4, 2)  # solo la verificada
        fg = {r["fuente"]: r for r in c2["fuentes"]}
        assert fg["grok_helix"]["ultimo_ok"] == hoy_s and fg["grok_helix"]["dias_sin_datos"] == 0 and fg["grok_otro"]["ultimo_ok"] is None
        # una carga posterior de la misma fila la pisa, no la duplica
        cod, rsp = procesar_carga(d2, raiz, csv_de(fila(precio="90000")), hoy=hoy_d)
        assert len(d2["grok"]) == 3 and [r["precio"] for r in d2["grok"] if r["titulo"] == "Combo Helix HX7 10W-40 4L"] == ["90000"]
        assert rsp["no_verificadas"] == 1 and rsp["duplicadas"] == []
        # combos de una URL que difieren solo en detalle (filtro/vehículo) son filas distintas; un duplicado exacto se informa
        sv = dict(tipo="servicio", titulo="Combo HX7 X 4L")
        cod, rsp = procesar_carga(d2, raiz, csv_de(fila(detalle="filtro aire", **sv), fila(detalle="filtro aire;filtro aceite", precio="99000", **sv),
                                                   fila(detalle="filtro aire", precio="85000", **sv)), hoy=hoy_d)
        assert cod == 200 and rsp["ok"] == 2 and rsp["duplicadas"] == [{"fila": 1, "reemplazada_por": 3, "titulo": "Combo HX7 X 4L"}], rsp
        combos = sorted((r["detalle"], r["precio"]) for r in d2["grok"] if r["titulo"] == "Combo HX7 X 4L")
        assert combos == [("filtro aire", "85000"), ("filtro aire;filtro aceite", "99000")], combos
        assert sum(r["titulo"] == "Combo HX7 X 4L" for r in calcular(d2)["servicios"]) == 2  # /api/servicios tampoco los colapsa
        # $/L de servicio: solo aceite + colocación se divide; con filtros, no
        sv0 = dict(fila(tipo="servicio"), verificado="0", cargado="x", producto_id="", match="none")
        assert litro_servicio(dict(sv0, precio="96990", litros="4", detalle="COLOCACIÓN Y CONTROLES;zona: sin selector")) == ("1", 24247.5)
        assert litro_servicio(dict(sv0, precio="194790", litros="8", unidades="", detalle="HELIX HX7 10W-40 X 8L;Mano de obra: Incluida")) == ("1", 24348.75)
        assert litro_servicio(dict(sv0, precio="239990", litros="4", detalle="FILTRO AIRE;FILTRO ACEITE;COLOCACIÓN")) == ("0", "")
        assert litro_servicio(dict(sv0, precio="303690", litros="5", detalle="Filtro de aire JFA-0285;Mano de obra")) == ("0", "")
        assert litro_servicio(dict(sv0, precio="76990", litros="", detalle="COLOCACIÓN")) == ("0", "")
        assert litro_servicio(dict(sv0, precio="70000", litros="4", detalle="sin colocación")) == ("0", "")  # helix_api: sin colocación no es aceite + colocación
        import recolectar
        assert recolectar.GROK_ALM == GROK_ALM_F and "helix_api" not in {f["fuente"] for f in fuentes_grok({"grok": [dict(sv0, fuente="helix_api")], "grok_sitios": []}, date.today())}
        assert {(r["detalle"], r["solo_aceite"]) for r in calcular(d2)["servicios"] if r["titulo"] == "Combo HX7 X 4L"} ==             {("filtro aire", "0"), ("filtro aire;filtro aceite", "0")}
        # tope de 30 cargas por día
        for i in range(32):
            cod, _ = procesar_carga(d2, raiz, csv_de(fila(titulo=f"Combo HX7 n{i}", fecha="2030-01-01")), hoy=date(2030, 1, 1),
                                    ahora=datetime(2030, 1, 1, 0, 0, i, tzinfo=timezone.utc))
            if cod == 429:
                break
        assert cod == 429 and i == 30, (cod, i)
        # con token: GET sha + PUT, mensaje y base64
        os.environ["GH_CARGA_TOKEN"], os.environ["GH_REPO"] = "tok", "yo/repo"
        d3 = cargar(raiz)
        cod, rsp = procesar_carga(d3, raiz, csv_de(fila(titulo="Combo HX7 otro")))
        assert cod == 200 and rsp["commit"] == ["abc123"], rsp
        (m1, r1, t1, _), (m2, r2, t2, b2) = llamadas[-2], llamadas[-1]
        assert (m1, m2) == ("GET", "PUT") and r2 == f"/repos/yo/repo/contents/data/grok/{hoy_s[:7]}.csv" and t2 == "tok"
        assert b2["message"] == f"grok: carga grok_helix {hoy_s} (1 filas)" and b2["sha"] == "viejo"
        assert base64.b64decode(b2["content"]).decode().startswith(",".join(GROK_ALM_F))
        GH = lambda *a, **k: (500, None)
        cod, rsp = procesar_carga(d3, raiz, csv_de(fila(titulo="Combo HX7 falla")))
        assert cod == 502 and rsp["ok"] == 1 and "no se pudo comitear" in rsp["error"]
    finally:
        normalizar.normalizar = norm_real
        os.environ.pop("GH_CARGA_TOKEN", None)
        os.environ.pop("GH_REPO", None)
        if token_ant:
            os.environ["GH_CARGA_TOKEN"] = token_ant
    shutil.rmtree(raiz / "data" / "grok")

    # recarga sin reiniciar: un clon git temporal; cambia HEAD -> recarga; igual -> no; datos rotos -> sigue con lo anterior
    with tempfile.TemporaryDirectory() as td:
        clon = Path(td) / "clon"
        shutil.copytree(raiz, clon)
        gg = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=clon, capture_output=True, text=True, check=True)
        gg("init", "-q"), gg("add", "."), gg("commit", "-qm", "uno")
        previo = (Handler.datos, Handler.calc, Handler.firma)
        try:
            Handler.firma = ""
            assert recargar(clon) and not recargar(clon)   # primera vez carga; sin cambios no recarga
            s = salud()
            assert s["ok"] is True and s["ultimo_dato"] == "2026-11-03" and s["commit"] == Handler.firma[:12] and len(s["commit"]) == 12, s
            assert "token" not in json.dumps(s).lower()
            arch = clon / "data" / "obs" / "2026-11.csv"
            filas = arch.read_text(encoding="utf-8").splitlines()
            nueva = filas[-1].split(",")
            nueva[0] = "2026-11-09"
            arch.write_text("\n".join(filas + [",".join(nueva)]) + "\n", encoding="utf-8")
            assert not recargar(clon)   # sin commit nuevo no se mira el archivo (el recolector puede estar escribiendo)
            gg("add", "."), gg("commit", "-qm", "dos")
            assert recargar(clon) and salud()["ultimo_dato"] == "2026-11-09"
            ok = Handler.datos
            (clon / "seed" / "productos.csv").write_bytes(b"\xff\xfe\xff")
            gg("add", "."), gg("commit", "-qm", "roto")
            assert not recargar(clon) and Handler.datos is ok   # falla: sigue sirviendo lo anterior
        finally:
            Handler.datos, Handler.calc, Handler.firma = previo
    assert firma_datos(raiz).startswith("mtime:") or firma_datos(raiz) == ""   # sin repo: cae al mtime, nunca revienta

    # auth y POST por HTTP: la clave de carga carga pero no lee
    assert autorizado_carga({"X-Carga-Clave": "c4rga"}, "s3cr3t", "c4rga") and autorizado_carga({"X-API-Key": "s3cr3t"}, "s3cr3t", "c4rga")
    assert not autorizado_carga({"X-Carga-Clave": "c4rga"}, "s3cr3t", "") and not autorizado_carga({"X-Carga-Clave": "mala"}, "s3cr3t", "c4rga")
    Handler.datos, Handler.calc, Handler.raiz, Handler.clave_carga = cargar(raiz), c, raiz, "c4rga"
    normalizar.normalizar = norm_fake
    GH = gh_fake

    def post(cuerpo, headers, tipo="text/csv"):
        req = urllib.request.Request(base + "/api/cargar", data=cuerpo.encode(), method="POST", headers={"Content-Type": tipo, **headers})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    kc = {"X-Carga-Clave": "c4rga"}
    assert get("/api/productos", kc)[0] == 200   # la lectura es abierta con o sin clave
    assert not autorizado_carga({"X-Carga-Clave": "x"}, None, "") and not autorizado_carga({}, None, "") and autorizado_carga({"X-Carga-Clave": "c4rga"}, None, "c4rga")   # sin clave principal, solo la de carga
    assert post(csv_de(fila()), {})[0] == 401 and post(csv_de(fila()), {"X-Carga-Clave": "mala"})[0] == 401
    assert post(csv_de(fila()), kc, "application/json")[0] == 415
    cod, rsp = post(csv_de(fila(), fila(precio="0")), kc, "text/plain")
    assert cod == 200 and rsp["ok"] == 1 and len(rsp["errores"]) == 1 and rsp["commit"] == "solo local"
    cod, rsp = post("csv=" + urllib.parse.quote(csv_de(fila(titulo="Combo HX7 otra"))), k, "application/x-www-form-urlencoded")  # la principal también carga
    assert cod == 200 and rsp["ok"] == 1
    assert post("basura", kc)[0] == 400
    cod, rsp = post(csv_de(fila(titulo="Aceite Castrol GTX"), fila(titulo="Combo Castrol", tipo="servicio", precio="50000")), kc)
    assert cod == 200 and rsp["ok"] == 1 and rsp["filas"][0]["tipo"] == "servicio" and rsp["errores"] == [
        {"fila": 1, "titulo": "Aceite Castrol GTX", "error": "no relacionado con YPF"}], rsp   # producto ajeno rechazado; servicio pasa
    assert post(csv_de(fila(titulo="Aceite Castrol GTX")), kc)[0] == 400
    mes = hoy_s[:7]
    assert len(json.loads(get("/api/grok?mes=" + mes, k)[1])) == 3 and get("/api/grok?mes=1999-01", k)[0] == 404
    assert [x["titulo"] for x in json.loads(get("/api/servicios", k)[1])] == ["Combo Castrol"] and get("/api/servicios?formato=csv", k)[1].startswith(b"fecha,fuente,url")
    assert json.loads(get("/api/grok_sitios", k)[1])[0]["fuente"] == "grok_helix"
    cod, rsp = post(csv_de(fila(titulo="Combo HX7 zona", provincia="Mendoza"), cab=GROK_PROV_F), kc)
    assert cod == 200 and rsp["ok"] == 1 and rsp["filas"][0]["provincia"] == "AR-M", rsp                # header nuevo
    cod, rsp = post(csv_de(fila(titulo="Combo HX7 zona2", provincia="Narnia"), fila(titulo="Combo HX7 zona3", provincia="online"), cab=GROK_PROV_F), kc)
    assert cod == 200 and rsp["ok"] == 1 and "provincia" in rsp["errores"][0]["error"] and rsp["errores"][0]["fila"] == 1   # inválida rechazada con motivo
    assert post(csv_de(fila(titulo="Combo HX7 zona4")), kc)[0] == 200                                    # header viejo, sin provincia
    cg = json.loads(get("/api/provincias?producto_id=shell-b-10w40&fuente=grok_helix", k)[1])["celdas"]
    assert {c["provincia"] for c in cg} == {"AR-M", "online"} and all(c["url"] == U and c["verificado"] == "1" and c["cargado"].endswith("Z") for c in cg), cg
    assert "Narnia" not in json.dumps(json.loads(get("/api/provincias?producto_id=shell-b-10w40", k)[1]))
    cod, rsp = post(csv_de(fila(titulo="Combo HX7 br", provincia="BR-PR", pais="BR", moneda="BRL"), cab=GROK_PAIS_F), kc)   # header de 14 columnas
    assert cod == 200 and rsp["ok"] == 1 and (rsp["filas"][0]["pais"], rsp["filas"][0]["moneda"], rsp["filas"][0]["provincia"]) == ("BR", "BRL", "BR-PR"), rsp
    assert "Combo HX7 br" not in json.dumps(json.loads(get("/api/provincias?producto_id=shell-b-10w40", k)[1]))   # el mapa argentino no ve la fila brasileña
    assert list(leer_csv(Path(raiz) / "data" / "grok" / (hoy_s[:7] + ".csv"))[0]) == GROK_ALM_F and GROK_ALM_F[-3:] == ["provincia", "pais", "moneda"]
    assert any(r["fuente"] == "grok_helix" for r in json.loads(get("/api/fuentes", k)[1]))
    # países en la API: AR por defecto, BR en su moneda, inválido = 400, mercado solo AR, ?usd=1 solo suma campos
    assert json.loads(get("/api/vitrina", k)[1])["pais"] == "AR" and json.loads(get("/api/vitrina?pais=BR", k)[1])["moneda"] == "BRL"
    assert get("/api/vitrina?pais=CL", k)[0] == 400 and get("/api/mercado?pais=BR", k)[0] == 400 and get("/api/indice?pais=ar", k)[0] == 200
    assert all(r["pais"] == "AR" and r["moneda"] == "ARS" for r in json.loads(get("/api/ultimo", k)[1]))
    assert all(r["pais"] == "BR" and r["moneda"] == "BRL" for r in json.loads(get("/api/indice?pais=BR", k)[1])) and json.loads(get("/api/provincias?pais=BR", k)[1])["pais"] == "BR"
    assert "precio_litro_usd" in json.loads(get("/api/ultimo?usd=1", k)[1])[0] and "precio_litro_usd" not in json.loads(get("/api/ultimo", k)[1])[0]
    assert all("pais" in f and "nota" in f and "dias_sin_correr" in f for f in json.loads(get("/api/fuentes", k)[1]))
    # fx_fecha: esa cotización para todo; sin cotización o mal formada = 400; /api/fx lista las reales
    for r_ in Handler.datos["obs"]:
        Handler.datos["fx_tabla"].setdefault(("ARS", r_["fecha"]), (1000.0, "BCRA (datos.gob.ar)"))
    ars = [x["fecha"] for x in fx_lista(Handler.datos["fx_tabla"], "ARS")]
    assert ars, "el test necesita al menos una cotización ARS"
    ju = json.loads(get(f"/api/ultimo?usd=1&fx_fecha={ars[0]}", k)[1])
    assert all(r["fx_fecha"] == ars[0] for r in ju if r.get("fx_fecha")) and any(r.get("precio_litro_usd") for r in ju)
    r400 = get("/api/ultimo?usd=1&fx_fecha=1999-01-01", k)
    assert r400[0] == 400 and "fechas_cercanas" in json.loads(r400[1]) and get("/api/ultimo?usd=1&fx_fecha=ayer", k)[0] == 400
    assert get("/api/ultimo?usd=1&fx_fecha=2026-02-30", k)[0] == 400 and get("/api/ultimo?pais=BR&usd=1&fx_fecha=" + ars[0], k)[0] in (200, 400)
    jf = json.loads(get("/api/fx?moneda=ARS", k)[1])
    assert jf["moneda"] == "ARS" and [x["fecha"] for x in jf["cotizaciones"]] == ars and jf["cotizaciones"][0]["fuente_url"].startswith("https://") and get("/api/fx?moneda=CLP", k)[0] == 400
    shutil.rmtree(raiz / "data" / "grok")
    BAJAR, GH, normalizar.normalizar = bajar, gh_api, norm_real
    # Carga ML 2026-11-24: estas filas caían en "no relacionado con YPF" por alias o equivalencia faltante.
    rel_ml = relacionados(Path(__file__).resolve().parent)
    for tit, marca, pid in (
        ("Aceite Extra Vida Xv 300 15w40 Ypf Para Motor De 4 L Mineral", "YPF", "ypf-extravida-xv300-15w40"),
        ("Aceite Motor Ypf Extravida 300 15w-40 20l Alta Protección", "YPF", "ypf-extravida-xv300-15w40"),
        ("Aceite Ypf Hidro Atf 4lts", "YPF", "ypf-hidro-atf"),
        ("Aceite Ypf Atfd Iii Lubricante Direccion Hidraulica X1 Litro", "YPF", "ypf-atf-d-iii"),
        ("Aceite Liquido Direccion Hidraulica Atf Dexron 3 Ypf 1 Lts", "YPF", "ypf-atf-d-iii"),
        ("Ypf Aceite Hidro Atf Balde 20 Litros Hidraulico", "YPF", "ypf-hidro-atf"),
        ("Hidro Atf Ypf X 20 Litros Hidráulico", "YPF", "ypf-hidro-atf"),
        ("Bidon X 4 Litros Dexron Vi Atf Ypf 88863898bdx4lt", "YPF", "ypf-atf-d-vi"),
        ("Aceite Castrol Edge 5w30 100% Sintetico X 4 L Nafta/diesel", "Castrol", "castrol-edge-5w30"),
        ("Shell Helix Ultra 5w-40 Full Sintético", "Shell", "shell-helix-ultra-5w40"),
        ("Aceite Shell Helix Ultra 5w40 X 4 Litros", "Shell", "shell-helix-ultra-5w40"),
        ("Aceite De Motor Shell Helix Hx8 Sintético 5w-40 X 4 Litros", "Shell", "shell-helix-hx8-5w40"),
        ("Aceite 10w40 Mobil Super 2000 Semisintetico Api Sn Plus X 4l", "Mobil", "mobil-super-2000-10w40"),
        ("Aceite Mobil Super 10w40 Plus X4l Parat", "Mobil", "mobil-super-2000-10w40"),
        ("Aceite mobil super 10w40 semi sintetico x 4L", "Mobil", "mobil-super-2000-10w40"),
        ("Lubricante Am 5w-40 Syntium 3000 Sintético 4 Litros Petronas", "Petronas", "petronas-syntium-3000-am-5w40"),
        ("Aceite De Motor Petronas Syntium 3000 Am 5w-40 4l", "Petronas", "petronas-syntium-3000-am-5w40"),
        ("Aceite Sintético Petronas Syntium 3000 Am 5w40 X 4 Litros", "Petronas", "petronas-syntium-3000-am-5w40"),
        ("Valvoline Aceite Premium Protection 15w40 3,78l Bidón", "Valvoline", "valvoline-premium-protection-15w40"),
    ):
        n = normalizar.normalizar(tit, marca, "")
        assert n["producto_id"] == pid and pid in rel_ml, (tit, n, pid in rel_ml)
    # Rimula R4 sin X/L es ambiguo (ya documentado); ACDelco y Valvoline HD 15W-40 no tienen equivalente claro en el seed.
    for tit, marca in (
        ("Shell Rimula R4 15w40 X4lts", "Shell"),
        ("Aceite Mineral Acdelco 15w40 Bidon X 4 Litros Nafta Diesel", "ACDelco"),
        ("Aceite De Motor Acdelco Mineral 15w 40 - 4 L", "ACDelco"),
        ("Aceite Mineral Premium Blue 15w-40 19l Valvoline", "Valvoline"),
        ("Aceite Valvoline 15w40 All Fleet Max X 20lts", "Valvoline"),
        ("Aceite Valvoline 15w40 Premium Blue 7800 X Gl-3.78lt", "Valvoline"),
    ):
        n = normalizar.normalizar(tit, marca, "")
        assert n["producto_id"] not in rel_ml, (tit, n)
    srv.shutdown()
    print("OK")


def main():
    if sys.argv[1:] == ["test"]:
        return demo()
    clave = os.environ.get("LUB_CLAVE", "")
    if not clave and not os.environ.get("LUB_CARGA_CLAVE"):
        print("AVISO: sin LUB_CLAVE ni LUB_CARGA_CLAVE, la lectura es abierta y la carga (POST) queda cerrada.", flush=True)
    raiz = os.environ.get("LUB_DATOS") or RAIZ
    Handler.firma = firma_datos(raiz)
    Handler.datos = cargar(raiz)
    Handler.calc = calcular(Handler.datos)
    Handler.clave, Handler.raiz = clave, Path(raiz)
    minutos = float(os.environ.get("LUB_RECARGA_MIN", "5"))  # en Render los datos cambian con el redeploy: sin hilo
    if minutos > 0 and not os.environ.get("RENDER"):
        threading.Thread(target=vigilar, args=(raiz, minutos), daemon=True).start()
    Handler.clave_carga = os.environ.get("LUB_CARGA_CLAVE", "")
    port = int(os.environ.get("PORT", "8000"))
    # En la PC solo loopback: 0.0.0.0 expone el server a la red y dispara el firewall de Windows.
    host = "0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1"
    print(f"datos de {raiz}: {len(Handler.datos['productos'])} productos, {len(Handler.datos['obs'])} observaciones, "
          f"{len(Handler.datos['meses'])} meses. http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
