"""Visor y API de LUBRICANTES: sirve site/index.html y calcula /api/* desde seed/ y data/.

Los datos se leen una sola vez al arrancar: cambian solo con un push (redeploy).
Uso: python server.py         (PORT, LUB_CLAVE, LUB_DATOS opcionales)
     python server.py test    (asserts, tiene que dar OK)
"""
import base64
import csv
import gzip
import hmac
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import median
from urllib.parse import parse_qs, urlsplit

from tiendas import MAYORISTAS  # fuentes de precio mayorista: fuera del índice salvo ?mayoristas=1

RAIZ = Path(__file__).resolve().parent
INDEX = RAIZ / "site" / "index.html"

PRODUCTOS_F = "producto_id,marca,linea,nombre,segmento,sae,base,api,acea,ilsac,jaso,oem,fuente_specs,verificado".split(",")
EQUIV_F = "eq_id,ypf_id,comp_id,tipo,criterio,evidencia,fuente".split(",")
OBS_F = "fecha,fuente,url,ean,titulo,marca,precio,precio_lista,stock,vendedor,sucursal,litros,unidades,producto_id,match".split(",")
FUENTES_F = "fecha,fuente,http,n_items,n_con_precio,n_sin_stock,n_sin_match,error".split(",")
OFERTA_F = "fecha,categoria_id,categoria,total_items".split(",")

CAMPOS = {
    "productos": PRODUCTOS_F,
    "equivalencias": EQUIV_F + ["ypf_marca", "ypf_nombre", "comp_marca", "comp_nombre"],
    "ultimo": ["producto_id", "fuente", "litros", "fecha", "precio", "precio_litro", "n"],
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
    return {
        "productos": leer_csv(raiz / "seed" / "productos.csv"),
        "equivalencias": leer_csv(raiz / "seed" / "equivalencias.csv"),
        "meses": meses,
        "obs": [r for filas in meses.values() for r in filas],
        "fuentes": leer_csv(raiz / "data" / "fuentes.csv"),
        "oferta_ml": leer_csv(raiz / "data" / "ml_oferta.csv"),
    }


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
            grupos[(r["producto_id"], r["fuente"], num(r["litros"]))].append((r["fecha"], pl, num(r["precio"])))
    out = []
    for (pid, fuente, litros), xs in sorted(grupos.items()):
        fecha = max(x[0] for x in xs)
        dia = [x for x in xs if x[0] == fecha]  # varias sucursales/vendedores el mismo día → mediana
        out.append({"producto_id": pid, "fuente": fuente, "litros": litros, "fecha": fecha,
                    "precio": round(median(x[2] for x in dia), 2),
                    "precio_litro": round(median(x[1] for x in dia), 2), "n": len(dia)})
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


class Handler(BaseHTTPRequestHandler):
    server_version = "lubricantes"
    sys_version = ""
    datos = None  # cargar()
    calc = None   # calcular()
    clave = None

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
        elif nombre == "obs":
            meses = sorted(self.datos["meses"])
            mes = q.get("mes", "")
            if not re.fullmatch(r"\d{4}-\d{2}", mes):
                return self.json(400, {"error": "falta mes=AAAA-MM", "meses": meses})
            if mes not in self.datos["meses"]:
                return self.json(404, {"error": f"sin observaciones de {mes}", "meses": meses})
            filas = self.datos["meses"][mes]
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


def demo():
    import tempfile
    import threading
    import urllib.error
    import urllib.request

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
    assert a_csv("ultimo", []).decode() == "producto_id,fuente,litros,fecha,precio,precio_litro,n\n"

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
    Handler.clave = clave
    port = int(os.environ.get("PORT", "8000"))
    # En la PC solo loopback: 0.0.0.0 expone el server a la red y dispara el firewall de Windows.
    host = "0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1"
    print(f"datos de {raiz}: {len(Handler.datos['productos'])} productos, {len(Handler.datos['obs'])} observaciones, "
          f"{len(Handler.datos['meses'])} meses. http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
