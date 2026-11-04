"""Visor y API de LUBRICANTES: sirve site/index.html y calcula /api/* desde seed/ y data/.

Los datos se leen al arrancar: cambian con un push (redeploy) o con POST /api/cargar (relevamientos de Grok).
Uso: python server.py         (PORT, LUB_CLAVE, LUB_DATOS opcionales)
     python server.py test    (asserts, tiene que dar OK)
"""
import base64
import csv
import gzip
import hmac
import io
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import median
from urllib.parse import parse_qs, urlsplit

import normalizar
from ml import UA
from tiendas import MAYORISTAS  # fuentes de precio mayorista: fuera del índice salvo ?mayoristas=1

RAIZ = Path(__file__).resolve().parent
INDEX = RAIZ / "site" / "index.html"

PRODUCTOS_F = "producto_id,marca,linea,nombre,segmento,sae,base,api,acea,ilsac,jaso,oem,fuente_specs,verificado".split(",")
EQUIV_F = "eq_id,ypf_id,comp_id,tipo,criterio,evidencia,fuente".split(",")
OBS_F = "fecha,fuente,url,ean,titulo,marca,precio,precio_lista,stock,vendedor,sucursal,litros,unidades,producto_id,match".split(",")
FUENTES_F = "fecha,fuente,http,n_items,n_con_precio,n_sin_stock,n_sin_match,error".split(",")
OFERTA_F = "fecha,categoria_id,categoria,total_items".split(",")
GROK_F = "fecha,fuente,url,titulo,marca,precio,precio_lista,litros,unidades,tipo,detalle".split(",")  # lo que devuelve la Task de Grok
GROK_ALM_F = GROK_F + ["verificado", "producto_id", "match", "cargado"]  # lo que se guarda en data/grok/
SITIOS_F = ["fuente", "host", "descripcion"]
SERVICIOS_F = [c for c in GROK_ALM_F if c not in ("tipo", "producto_id", "match")]
MAX_FILAS, MAX_CARGAS_DIA, MAX_BYTES = 500, 10, 2_000_000
RX_FUENTE = re.compile(r"grok_[a-z0-9_]{2,30}")
RX_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")

CAMPOS = {
    "productos": PRODUCTOS_F,
    "equivalencias": EQUIV_F + ["ypf_marca", "ypf_nombre", "comp_marca", "comp_nombre"],
    "ultimo": ["producto_id", "fuente", "litros", "fecha", "precio", "precio_litro", "n", "url", "verificado"],
    "grok": GROK_ALM_F,
    "servicios": SERVICIOS_F,
    "grok_sitios": SITIOS_F,
    "obs": OBS_F,
    "serie": ["fecha", "fuente", "precio_litro", "n"],
    "indice": ["fecha", "segmento", "sae", "marca", "mediana_litro", "n", "indice"],
    "fuentes": FUENTES_F + ["ultimo_ok", "dias_sin_datos"],
    "sin_match": ["fuente", "titulo", "ean", "marca", "precio", "litros", "unidades", "url", "primera", "ultima", "veces"],
    "oferta_ml": OFERTA_F,
}
CAMPOS["indice_con_mayoristas"] = CAMPOS["indice"]


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
    }
    integrar_grok(d)
    return d


def integrar_grok(d):
    """Las filas Grok de tipo producto entran a `obs` como cualquier fuente; los servicios nunca (no son $/L)."""
    d["grok"] = [r for filas in d["grok_meses"].values() for r in filas]
    d["obs"] = d["obs_base"] + [
        {**dict.fromkeys(OBS_F, ""), **{k: r.get(k) or "" for k in GROK_ALM_F if k in OBS_F or k == "verificado"}}
        for r in d["grok"] if r["tipo"] == "producto"]


def servicios(grok):
    ult = {}
    for r in sorted(grok, key=lambda r: r["fecha"]):
        if r["tipo"] == "servicio":
            ult[(r["fuente"], r["url"], r["titulo"])] = r
    return sorted(ult.values(), key=lambda r: (r["fuente"], r["titulo"]))


def equivalencias(d):
    prod = {p["producto_id"]: p for p in d["productos"]}
    out = []
    for e in d["equivalencias"]:
        y, c = prod.get(e["ypf_id"], {}), prod.get(e["comp_id"], {})
        out.append({**e, "ypf_marca": y.get("marca", ""), "ypf_nombre": y.get("nombre", ""),
                    "comp_marca": c.get("marca", ""), "comp_nombre": c.get("nombre", "")})
    return out


def ultimo(obs):
    grupos = defaultdict(list)
    for r in obs:
        pl = precio_litro(r)
        if r["producto_id"] and pl is not None:
            grupos[(r["producto_id"], r["fuente"], num(r["litros"]))].append((r["fecha"], pl, num(r["precio"]), r["url"], r.get("verificado") or ""))
    out = []
    for (pid, fuente, litros), xs in sorted(grupos.items()):
        fecha = max(x[0] for x in xs)
        dia = [x for x in xs if x[0] == fecha]  # varias sucursales/vendedores el mismo día → mediana
        out.append({"producto_id": pid, "fuente": fuente, "litros": litros, "fecha": fecha,
                    "precio": round(median(x[2] for x in dia), 2),
                    "precio_litro": round(median(x[1] for x in dia), 2), "n": len(dia), "url": dia[0][3],
                    "verificado": "" if not dia[0][4] else "1" if all(x[4] == "1" for x in dia) else "0"})
    return out


def serie(obs, pid):
    grupos = defaultdict(list)
    for r in obs:
        pl = precio_litro(r)
        if r["producto_id"] == pid and pl is not None:
            grupos[(r["fecha"], r["fuente"])].append(pl)
    return [{"fecha": f, "fuente": fu, "precio_litro": round(median(v), 2), "n": len(v)}
            for (f, fu), v in sorted(grupos.items())]


def indice(d, mayoristas=False):
    prod = {p["producto_id"]: p for p in d["productos"]}
    grupos = defaultdict(list)
    for r in d["obs"]:
        if r["fuente"] in MAYORISTAS and not mayoristas:
            continue
        if r.get("verificado") == "0":  # Grok sin verificar: se muestra, no pesa en el índice
            continue
        p, pl = prod.get(r["producto_id"]), precio_litro(r)
        if p and pl is not None:
            grupos[(r["fecha"], p["segmento"], p["sae"], p["marca"])].append(pl)
    med = {k: median(v) for k, v in grupos.items()}
    out = []
    for (fecha, seg, sae, marca), m in sorted(med.items()):
        ypf = med.get((fecha, seg, sae, "YPF"))
        out.append({"fecha": fecha, "segmento": seg, "sae": sae, "marca": marca,
                    "mediana_litro": round(m, 2), "n": len(grupos[(fecha, seg, sae, marca)]),
                    "indice": round(m / ypf * 100, 1) if ypf else None})
    return out


def fuentes(d, hoy):
    por_fuente = defaultdict(list)
    for r in d["fuentes"]:
        por_fuente[r["fuente"]].append(r)
    out = []
    for fuente, filas in sorted(por_fuente.items()):
        filas.sort(key=lambda r: r["fecha"])  # estable: la última corrida del día queda al final
        # error vacío = corrida OK (recolectar.py ya marca n_items == 0 con HTTP 200 como error)
        oks = [r["fecha"] for r in filas if not r["error"]]
        ultimo_ok = oks[-1] if oks else None
        dias = (hoy - date.fromisoformat(ultimo_ok)).days if ultimo_ok else None
        out.append({**{k: filas[-1].get(k, "") for k in FUENTES_F}, "ultimo_ok": ultimo_ok, "dias_sin_datos": dias})
    return sorted(out + fuentes_grok(d, hoy), key=lambda r: r["fuente"])


def fuentes_grok(d, hoy):
    """Una fila por grok_*: la 'corrida' es la última carga; días sin datos = hoy - fecha del último dato."""
    por = defaultdict(list)
    for r in d["grok"]:
        por[r["fuente"]].append(r)
    out = []
    for f in sorted({s["fuente"] for s in d["grok_sitios"]} | set(por)):
        filas = por.get(f, [])
        base = {"fecha": "", "fuente": f, "http": "", "n_items": 0, "n_con_precio": 0, "n_sin_stock": 0, "n_sin_match": 0,
                "error": "sin cargas todavía", "ultimo_ok": None, "dias_sin_datos": None}
        if filas:
            ult = max(r["fecha"] for r in filas)
            n = [r for r in filas if r["fecha"] == ult]
            base.update(fecha=max(r["cargado"] for r in filas)[:10], n_items=len(n), n_con_precio=len(n), error="",
                        n_sin_match=sum(not r["producto_id"] for r in n), ultimo_ok=ult,
                        dias_sin_datos=(hoy - date.fromisoformat(ult)).days)
        out.append(base)
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


def calcular(d, hoy=None):
    """Lo que no depende de parámetros se calcula una vez al arrancar."""
    return {
        "productos": d["productos"],
        "equivalencias": equivalencias(d),
        "ultimo": ultimo(d["obs"]),
        "indice": indice(d),
        "indice_con_mayoristas": indice(d, mayoristas=True),
        "fuentes": fuentes(d, hoy or date.today()),
        "sin_match": sin_match(d["obs"]),
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
    """La clave de carga solo sirve para cargar; la principal también."""
    k = headers.get("X-Carga-Clave")
    if clave_carga and k and hmac.compare_digest(k.encode(), clave_carga.encode()):
        return True
    return autorizado(headers, clave)


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
    if not r["titulo"]:
        e.append("falta titulo")
    return "; ".join(e)


def validar_csv(texto, hoy, sitios):
    """→ (filas válidas, errores por fila, error fatal). El fatal rechaza la carga entera."""
    try:
        crudas = [f for f in csv.reader(io.StringIO(texto.lstrip("﻿"))) if any(c.strip() for c in f)]
    except csv.Error as e:
        return [], [], f"CSV ilegible: {e}"
    if not crudas or [c.strip() for c in crudas[0]] != GROK_F:
        return [], [], "encabezado inválido: tiene que ser exactamente " + ",".join(GROK_F)
    if len(crudas) - 1 > MAX_FILAS:
        return [], [], f"más de {MAX_FILAS} filas por carga"
    filas, errores = [], []
    for i, f in enumerate(crudas[1:], 1):
        if len(f) != len(GROK_F):
            errores.append({"fila": i, "error": f"tiene {len(f)} columnas, esperaba {len(GROK_F)} (¿comas sin comillas en un campo?)"})
            continue
        r = dict(zip(GROK_F, (c.strip() for c in f)))
        e = error_fila(r, hoy, sitios)
        if e:
            errores.append({"fila": i, "titulo": r["titulo"], "error": e})
        else:
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
    """Idempotente: una fila nueva reemplaza a la de misma fuente+fecha+url+titulo."""
    k = lambda r: (r["fuente"], r["fecha"], r["url"], r["titulo"])
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
    por_clave = {(r["fuente"], r["fecha"], r["url"], r["titulo"]): r for r in filas}  # duplicados dentro de la carga: gana la última
    paginas, resultado = {}, []
    for r in por_clave.values():
        if r["url"] not in paginas:
            paginas[r["url"]] = BAJAR(r["url"])
        pag = paginas[r["url"]]
        r["verificado"] = "1" if pag and precio_en_texto(float(r["precio"]), pag) else "0"
        n = normalizar.normalizar(r["titulo"], r["marca"], "", url=r["url"])
        r["producto_id"], r["match"], r["cargado"] = n["producto_id"], n["match"], sello
        r["marca"] = r["marca"] or n["marca"] or ""
        if not r["litros"] and n["litros"]:
            r["litros"] = f"{n['litros']:g}"
        if not r["unidades"] and n["unidades"]:
            r["unidades"] = str(n["unidades"])
        resultado.append({"fila": r.pop("_fila"), "titulo": r["titulo"], "tipo": r["tipo"], "verificado": r["verificado"] == "1",
                          "producto_id": r["producto_id"]})
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
    resp = {"ok": len(resultado), "verificadas": ver, "no_verificadas": len(resultado) - ver, "errores": errores,
            "filas": sorted(resultado, key=lambda x: x["fila"]), "commit": commits if token else "solo local"}
    if fallo:
        resp["error"] = fallo
    return (502 if fallo else 200), resp


class Handler(BaseHTTPRequestHandler):
    server_version = "lubricantes"
    sys_version = ""
    datos = None  # cargar()
    calc = None   # calcular()
    clave = None
    clave_carga = ""
    raiz = RAIZ
    candado = threading.Lock()

    def enviar(self, codigo, cuerpo, tipo, extra=()):
        if "gzip" in self.headers.get("Accept-Encoding", "") and len(cuerpo) > 1024:
            cuerpo = gzip.compress(cuerpo)
            extra = [*extra, ("Content-Encoding", "gzip")]
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Accept-Encoding, Authorization, X-API-Key")
        self.send_header("X-Content-Type-Options", "nosniff")
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
            return self.json(200, {"ok": True})
        if not autorizado(self.headers, self.clave):
            return self.enviar(401, b'{"error":"falta clave: header X-API-Key o Basic Auth"}',
                               "application/json; charset=utf-8",
                               [("WWW-Authenticate", 'Basic realm="LUBRICANTES", charset="UTF-8"')])
        if u.path in ("/", "/index.html"):  # solo se sirve este archivo: no hay path traversal posible
            return self.enviar(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        if not u.path.startswith("/api/"):
            return self.json(404, {"error": "no existe"})
        nombre = u.path[5:]
        if nombre == "indice" and q.get("mayoristas") == "1":
            filas = self.calc["indice_con_mayoristas"]
        elif nombre in self.calc:
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
            filas = serie(self.datos["obs"], pid)
        else:
            return self.json(404, {"error": "no existe"})
        if q.get("formato") == "csv":
            return self.enviar(200, a_csv(nombre, filas), "text/csv; charset=utf-8")
        self.json(200, filas)

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
        for fe, fu, pr, li, un, pid in obs:
            w.writerow({"fecha": fe, "fuente": fu, "precio": pr, "litros": li, "unidades": un, "producto_id": pid,
                        "titulo": "aceite raro", "match": "ean" if pid else "none"})
    (raiz / "data" / "fuentes.csv").write_text(
        ",".join(FUENTES_F) + "\n"
        "2026-11-01,vtex_carrefour,200,10,8,2,0,\n"
        "2026-11-02,vtex_carrefour,200,10,8,2,0,\n"
        "2026-11-03,vtex_carrefour,403,0,0,0,0,HTTP 403\n"
        "2026-11-03,ml,,0,0,0,0,sin token\n", encoding="utf-8")

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
    assert im[("2026-11-02", "10W-40", "YPF")]["mediana_litro"] == 4000  # con mayorista: mediana de 4400, 4000 y 166,67
    assert i[("2026-11-02", "10W-40", "Shell")]["indice"] == round(6000 / 4200 * 100, 1)
    assert i[("2026-11-02", "15W-40", "Gulf")]["indice"] is None  # sin YPF → vacío

    s = serie(d["obs"], "ypf-a-10w40")
    assert [(r["fecha"], r["precio_litro"]) for r in s if r["fuente"] == "sepa"] == [("2026-11-01", 4200), ("2026-11-02", 4200)]

    f = {r["fuente"]: r for r in c["fuentes"]}
    assert f["vtex_carrefour"]["error"] == "HTTP 403" and f["vtex_carrefour"]["ultimo_ok"] == "2026-11-02"
    assert f["vtex_carrefour"]["dias_sin_datos"] == 1
    assert f["ml"]["ultimo_ok"] is None and f["ml"]["dias_sin_datos"] is None

    assert len(c["sin_match"]) == 1 and c["sin_match"][0]["veces"] == 2 and c["sin_match"][0]["ultima"] == "2026-11-03"
    assert c["equivalencias"][0]["comp_nombre"] == "HX7"
    assert a_csv("indice", c["indice"]).decode().startswith("fecha,segmento,sae,marca,mediana_litro,n,indice\n")
    assert a_csv("ultimo", []).decode() == "producto_id,fuente,litros,fecha,precio,precio_litro,n,url,verificado\n"

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
    assert get("/salud") == (200, b'{"ok": true}')
    assert get("/api/ultimo")[0] == 401
    assert get("/api/ultimo", {"X-API-Key": "s3cr3t"})[0] == 200
    assert get("/api/ultimo", b("x:s3cr3t"))[0] == 200
    assert get("/api/obs?mes=2026-11&formato=csv", {"X-API-Key": "s3cr3t"})[1].startswith(b"fecha,fuente,url")
    k = {"X-API-Key": "s3cr3t"}
    assert json.loads(get("/api/indice", k)[1]) == c["indice"] and json.loads(get("/api/indice?mayoristas=1", k)[1]) == c["indice_con_mayoristas"]
    assert get("/api/obs", {"X-API-Key": "s3cr3t"})[0] == 400
    assert get("/api/serie?p=nada", {"X-API-Key": "s3cr3t"})[0] == 404
    assert get("/../server.py", {"X-API-Key": "s3cr3t"})[0] == 404
    assert get("/site/index.html", {"X-API-Key": "s3cr3t"})[0] == 404
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
            w.writerow([r.get(c, "") for c in GROK_F])
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
    normalizar.normalizar = lambda t, m="", e="", reglas=None, url="": dict(
        marca="Shell", sae="10W-40", litros=4.0, unidades=1, producto_id="shell-b-10w40" if "HX7" in t else "", match="texto" if "HX7" in t else "none")
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
        assert rsp["no_verificadas"] == 1
        # tope de 10 cargas por día
        for i in range(12):
            cod, _ = procesar_carga(d2, raiz, csv_de(fila(titulo=f"Combo HX7 n{i}", fecha="2030-01-01")), hoy=date(2030, 1, 1),
                                    ahora=datetime(2030, 1, 1, 0, 0, i, tzinfo=timezone.utc))
            if cod == 429:
                break
        assert cod == 429 and i == 10, (cod, i)
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

    # auth y POST por HTTP: la clave de carga carga pero no lee
    assert autorizado_carga({"X-Carga-Clave": "c4rga"}, "s3cr3t", "c4rga") and autorizado_carga({"X-API-Key": "s3cr3t"}, "s3cr3t", "c4rga")
    assert not autorizado_carga({"X-Carga-Clave": "c4rga"}, "s3cr3t", "") and not autorizado_carga({"X-Carga-Clave": "mala"}, "s3cr3t", "c4rga")
    Handler.datos, Handler.calc, Handler.raiz, Handler.clave_carga = cargar(raiz), c, raiz, "c4rga"
    GH = gh_fake

    def post(cuerpo, headers, tipo="text/csv"):
        req = urllib.request.Request(base + "/api/cargar", data=cuerpo.encode(), method="POST", headers={"Content-Type": tipo, **headers})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    kc = {"X-Carga-Clave": "c4rga"}
    assert get("/api/productos", kc)[0] == 401 and get("/api/ultimo", kc)[0] == 401   # la de carga no lee nada
    assert post(csv_de(fila()), {})[0] == 401 and post(csv_de(fila()), {"X-Carga-Clave": "mala"})[0] == 401
    assert post(csv_de(fila()), kc, "application/json")[0] == 415
    cod, rsp = post(csv_de(fila(), fila(precio="0")), kc, "text/plain")
    assert cod == 200 and rsp["ok"] == 1 and len(rsp["errores"]) == 1 and rsp["commit"] == "solo local"
    cod, rsp = post("csv=" + urllib.parse.quote(csv_de(fila(titulo="otra"))), k, "application/x-www-form-urlencoded")  # la principal también carga
    assert cod == 200 and rsp["ok"] == 1
    assert post("basura", kc)[0] == 400
    mes = hoy_s[:7]
    assert len(json.loads(get("/api/grok?mes=" + mes, k)[1])) == 2 and get("/api/grok?mes=1999-01", k)[0] == 404
    assert json.loads(get("/api/servicios", k)[1]) == [] and get("/api/servicios?formato=csv", k)[1].startswith(b"fecha,fuente,url")
    assert json.loads(get("/api/grok_sitios", k)[1])[0]["fuente"] == "grok_helix"
    assert any(r["fuente"] == "grok_helix" for r in json.loads(get("/api/fuentes", k)[1]))
    shutil.rmtree(raiz / "data" / "grok")
    BAJAR, GH = bajar, gh_api
    srv.shutdown()
    print("OK")


def main():
    if sys.argv[1:] == ["test"]:
        return demo()
    clave = os.environ.get("LUB_CLAVE", "")
    if os.environ.get("RENDER") and not clave:
        sys.exit("ERROR: falta LUB_CLAVE en Render; el server no arranca sin clave.")
    if not clave:
        print("AVISO: sin LUB_CLAVE, la API queda abierta (solo para uso local).", flush=True)
    raiz = os.environ.get("LUB_DATOS") or RAIZ
    Handler.datos = cargar(raiz)
    Handler.calc = calcular(Handler.datos)
    Handler.clave, Handler.raiz = clave, Path(raiz)
    Handler.clave_carga = os.environ.get("LUB_CARGA_CLAVE", "")
    port = int(os.environ.get("PORT", "8000"))
    # En la PC solo loopback: 0.0.0.0 expone el server a la red y dispara el firewall de Windows.
    host = "0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1"
    print(f"datos de {raiz}: {len(Handler.datos['productos'])} productos, {len(Handler.datos['obs'])} observaciones, "
          f"{len(Handler.datos['meses'])} meses. http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
