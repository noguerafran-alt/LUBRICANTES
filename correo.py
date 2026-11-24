"""Correo Argentino, API MiCorreo (PDF oficial 08/2022): token, validación de cuenta y cotización de envío.
Credenciales solo en `.correo_local` (ignorado por git) o en CORREO_*; nunca en el repo ni en un GET.
Uso: python correo.py alta | probar <cp_origen> <cp_destino> [peso_g] | tarifas [--fecha AAAA-MM-DD] [--tope N] | test"""
import base64
import getpass
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import ml

BASES = {"prod": "https://api.correoargentino.com.ar/micorreo/v1",
         "test": "https://apitest.correoargentino.com.ar/micorreo/v1"}
ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".correo_local")
METODOS = {"D": "domicilio", "S": "sucursal"}
ULTIMO_ERROR = ""  # cuerpo recortado del último error de la API (no trae credenciales)
_tokens = {}  # (ambiente, usuario) → (token, vence epoch)


def base(ambiente):
    if ambiente not in BASES:
        raise ValueError(f"ambiente {ambiente!r}: test o prod")
    return BASES[ambiente]


def basic(usuario, clave):
    return {"Authorization": "Basic " + base64.b64encode(f"{usuario}:{clave}".encode()).decode()}


def cargar():
    """Credenciales: el archivo y, encima, las variables de entorno. None si falta algo."""
    c = {}
    if os.path.exists(ARCHIVO):
        c = json.load(open(ARCHIVO, encoding="utf-8"))
    for k, e in (("usuario", "CORREO_USUARIO"), ("clave", "CORREO_CLAVE"),
                 ("customer_id", "CORREO_CUSTOMER_ID"), ("ambiente", "CORREO_AMBIENTE")):
        if os.environ.get(e):
            c[k] = os.environ[e]
    c.setdefault("ambiente", "test")
    return c if all(c.get(k) for k in ("usuario", "clave", "customer_id")) else None


def guardar(cred):
    """Nunca la contraseña de MiCorreo: solo los cuatro campos."""
    d = {k: str(cred[k]) for k in ("ambiente", "usuario", "clave", "customer_id")}
    fd = os.open(ARCHIVO, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def _pedir(ruta, cred, data=None, headers=None):
    global ULTIMO_ERROR
    ml.ULTIMO_ERROR.clear()
    http, d = ml.pedir(base(cred["ambiente"]) + ruta, data=data, metodo="POST", headers=headers)
    ULTIMO_ERROR = ml.ULTIMO_ERROR.get(http, "")
    return http, d


def token(cred):
    """→ token Bearer (cacheado hasta `expires`) o None."""
    k = (cred["ambiente"], cred["usuario"])
    t = _tokens.get(k)
    if t and t[1] > time.time() + 30:
        return t[0]
    http, d = _pedir("/token", cred, headers=basic(cred["usuario"], cred["clave"]))
    if http != 200 or not isinstance(d, dict) or not d.get("token"):
        return None
    try:
        vence = time.mktime(time.strptime(d["expires"], "%Y-%m-%d %H:%M:%S"))
    except (KeyError, ValueError, TypeError):
        vence = time.time() + 300  # sin fecha legible: no se confía en cachear mucho
    _tokens[k] = (d["token"], vence)
    return d["token"]


def validar(cred, email, password):
    """→ customerId (str, con ceros) o None. La contraseña no se guarda ni se loguea."""
    tk = token(cred)
    if not tk:
        return None
    http, d = _pedir("/users/validate", cred, data=json.dumps(dict(email=email, password=password)).encode(),
                     headers={"Authorization": "Bearer " + tk})
    return d.get("customerId") if http == 200 and isinstance(d, dict) and d.get("customerId") else None


def _entero(nombre, v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValueError(f"{nombre} {v!r}: entero {lo}..{hi}")
    return v


def _dias(v):
    """deliveryTimeMin/Max vienen como string («2»); la API no documenta la unidad (se lee como días); otra cosa = None, no se adivina."""
    return int(v) if isinstance(v, str) and v.isdigit() else None


def cotizar(cred, cp_origen, cp_destino, peso_g, alto, ancho, largo):
    """→ (http, [{metodo, producto, precio}]). Sin token o respuesta ilegible: (http, [])."""
    dim = dict(weight=_entero("peso_g", peso_g, 1, 25000), height=_entero("alto", alto, 1, 150),
               width=_entero("ancho", ancho, 1, 150), length=_entero("largo", largo, 1, 150))
    tk = token(cred)
    if not tk:
        return 0, []
    cuerpo = dict(customerId=cred["customer_id"], postalCodeOrigin=str(cp_origen),
                  postalCodeDestination=str(cp_destino), dimensions=dim)
    http, d = _pedir("/rates", cred, data=json.dumps(cuerpo).encode(), headers={"Authorization": "Bearer " + tk})
    filas = []
    for r in (d.get("rates") if http in (200, 202) and isinstance(d, dict) else None) or []:  # prod responde 202 (visto 2026-11-24)
        try:
            m, p = METODOS.get(r.get("deliveredType")), float(r["price"])
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if m and p > 0:  # tipo desconocido o precio no numérico: se descarta, nunca 0
            filas.append(dict(metodo=m, producto=r.get("productName") or r.get("productType") or "", precio=p,
                              plazo_dias=(_dias(r.get("deliveryTimeMin")), _dias(r.get("deliveryTimeMax")))))
    return http, filas


AQUI = os.path.dirname(os.path.abspath(__file__))
CORREO = "fecha,capturado,cp_origen,provincia_origen,cp_destino,provincia_destino,litros,peso_g,metodo,producto,precio,plazo_min,plazo_max,estado".split(",")
CORREO_SEGUNDOS = 720  # presupuesto propio: ~330 requests a 1 req/s


def _litros(v):
    return f"{float(v):g}"


def tarifas(raiz=AQUI, fecha=None, tope=None, cotizar=cotizar, reloj=time.monotonic, cred=None):
    """Capital → capital (24 × 24) por envase de seed/envases_correo.csv, en rotación k=7 (como los envíos de ML).
    → (fila de fuentes.csv, filas de data/correo). La tarifa no depende del producto: sin filtro de relacionados. Sin credenciales o sin
    token no se pide nada. Un par sin tarifa legible = una fila `sin_cotizacion` (nunca un precio inventado)."""
    import recolectar as rc
    fecha = fecha or datetime.now(timezone(timedelta(hours=-3))).date().isoformat()
    fila = dict(fecha=fecha, fuente="correo_tarifas", http="", n_items=0, n_con_precio=0, n_sin_stock=0, n_sin_match=0, error="", n_descartados=0)
    caps = rc.leer(os.path.join(raiz, "seed", "cp_capitales.csv"))
    envases = rc.leer(os.path.join(raiz, "seed", "envases_correo.csv"))
    toca = [(o, d, e) for o in caps for d in caps for e in envases if rc.grupo_envios((o["cp"], d["cp"], _litros(e["litros"])), fecha)]
    if tope:
        toca = toca[:tope]
    if cred is None or not (cred.get("ambiente") == "prod" and token(cred)):
        fila["error"] = "sin credenciales de prod o sin token"  # ponytail: la tarifa de `test` no es real: no se guarda
        return fila, None
    t0, filas, hechos = reloj(), [], set()
    for o, d, e in toca:
        if reloj() - t0 > CORREO_SEGUNDOS:
            fila["error"] = "cortado por tiempo"
            break
        http, fs = cotizar(cred, o["cp"], d["cp"], int(e["peso_g"]), int(e["alto_cm"]), int(e["ancho_cm"]), int(e["largo_cm"]))
        fila["n_items"] += 1
        fila["n_con_precio"] += bool(fs)
        base = dict(fecha=fecha, capturado=rc.ahora_utc(), cp_origen=o["cp"], provincia_origen=o["provincia"], cp_destino=d["cp"],
                    provincia_destino=d["provincia"], litros=_litros(e["litros"]), peso_g=e["peso_g"])
        hechos.add((fecha, o["cp"], d["cp"], base["litros"]))
        filas += [dict(base, metodo=f["metodo"], producto=f["producto"], precio=f"{f['precio']:g}", plazo_min=f["plazo_dias"][0] if f["plazo_dias"][0] is not None else "",
                       plazo_max=f["plazo_dias"][1] if f["plazo_dias"][1] is not None else "", estado="ok") for f in fs] or [dict(base, estado="sin_cotizacion")]
    if not fila["error"] and fila["n_items"] and not fila["n_con_precio"]:
        fila["error"] = "ninguna cotizacion respondio"
    if hechos:  # los pares de hoy reemplazan a los de hoy; lo cortado por tiempo no se toca
        rc.reemplazar(os.path.join(raiz, "data", "correo", fecha[:7] + ".csv"), CORREO, filas, lambda f: (f["fecha"], f["cp_origen"], f["cp_destino"], _litros(f["litros"])), hechos)
    return fila, filas


def correr_tarifas(args):
    import recolectar as rc
    fecha = args[args.index("--fecha") + 1] if "--fecha" in args else None
    tope = int(args[args.index("--tope") + 1]) if "--tope" in args else None
    cred = cargar()
    if not cred:
        sys.exit("Sin credenciales de Correo (.correo_local): no se pidió nada.")
    fila, filas = tarifas(fecha=fecha, tope=tope, cred=cred)
    if filas is None:
        sys.exit(fila["error"])
    rc.escribir_fuentes(os.path.join(AQUI, "data", "fuentes.csv"), [fila])
    print(f"correo_tarifas {fila['fecha']}: {fila['n_con_precio']}/{fila['n_items']} cotizaciones" + (f" ({fila['error']})" if fila["error"] else ""))
    sys.exit(1 if fila["error"] else 0)


def alta():
    amb = input("Ambiente [test]: ").strip() or "test"
    cred = dict(ambiente=amb, usuario=input("Usuario API: ").strip(), clave=getpass.getpass("Clave API: "))
    if not token(cred):
        sys.exit(f"Sin token (¿usuario/clave de {amb}?). {ULTIMO_ERROR}")
    cid = validar(cred, input("Email MiCorreo: ").strip(), getpass.getpass("Contraseña MiCorreo: "))
    if not cid:
        sys.exit(f"Cuenta MiCorreo no validada. {ULTIMO_ERROR}")
    cred["customer_id"] = cid
    guardar(cred)
    print("Guardado .correo_local (sin la contraseña ni el email de MiCorreo).")
    probar("1001", "5000", 4000)


def probar(origen, destino, peso=4000):
    cred = cargar() or sys.exit("Faltan credenciales: python correo.py alta")
    http, filas = cotizar(cred, origen, destino, int(peso), 15, 30, 20)
    print("HTTP", http, "" if filas else ULTIMO_ERROR)
    for f in filas:
        print(f"{f['metodo']:9} {f['producto']:30} ${f['precio']:,.2f}  plazo {f['plazo_dias'][0]}-{f['plazo_dias'][1]}")


def demo():
    global ARCHIVO
    import tempfile
    cred = dict(ambiente="test", usuario="u", clave="k", customer_id="0090000025")
    assert basic("u", "k")["Authorization"] == "Basic dTpr"  # base64("u:k")
    assert base("prod").startswith("https://api.") and "apitest" in base("test")
    visto = []

    def falso(resp):
        def f(url, **k):
            visto.append((url, k))
            return resp[url.rsplit("/", 1)[1]]
        return f
    real = ml.pedir
    try:
        exp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + 3600))
        ml.pedir = falso(dict(token=(200, dict(token="TK", expires=exp)),
                              validate=(200, dict(customerId="0090000025", createdAt="x")),
                              rates=(200, dict(rates=[dict(deliveredType="D", productType="CP", productName="Clásico", price=5000.5),
                                                      dict(deliveredType="S", productType="CP", productName="Sucursal", price=4000),
                                                      dict(deliveredType="D", productType="X", price="n/a")]))))
        assert token(cred) == "TK" and token(cred) == "TK"
        assert len([v for v in visto if v[0].endswith("/token")]) == 1  # cacheado
        assert visto[0][1]["headers"] == basic("u", "k") and visto[0][0].startswith(BASES["test"])
        assert validar(cred, "a@b", "x") == "0090000025"
        http, f = cotizar(cred, "1001", "5000", 4000, 15, 30, 20)
        assert http == 200 and [x["metodo"] for x in f] == ["domicilio", "sucursal"] and f[0]["precio"] == 5000.5  # el no numérico se descartó
        ml.pedir = falso(dict(rates=(202, dict(rates=[dict(deliveredType="S", productType="CP", productName="Clasico", price=14050.0, deliveryTimeMin="2", deliveryTimeMax="5")]))))
        http, f = cotizar(cred, "1001", "5000", 4000, 15, 20, 30)
        assert http == 202 and f == [dict(metodo="sucursal", producto="Clasico", precio=14050.0, plazo_dias=(2, 5))], f  # respuesta real de prod
        assert visto[-1][1]["headers"]["Authorization"] == "Bearer TK"
        ml.pedir = falso(dict(rates=(200, dict()), validate=(404, None)))
        assert cotizar(cred, "1001", "5000", 1, 1, 1, 1) == (200, [])
        assert validar(cred, "a@b", "x") is None
        _tokens.clear()
        ml.pedir = falso(dict(token=(401, None)))
        assert token(cred) is None and cotizar(cred, "1001", "5000", 1, 1, 1, 1) == (0, [])
    finally:
        ml.pedir = real
    for a in ((0, 15, 15, 15), (25001, 15, 15, 15), (100, 151, 15, 15), (100, 15, 15, 0)):
        try:
            cotizar(cred, "1001", "5000", *a)
            assert False
        except ValueError:
            pass
    # tarifas: sin red, con cotizar falso y la rotación real
    import recolectar as rc
    cr = dict(cred, ambiente="prod")
    visto2 = []

    def falso2(c, o, d, peso, a, an, la):
        visto2.append((o, d, peso))
        return (202, [dict(metodo="domicilio", producto="Clasico", precio=5000.0, plazo_dias=(2, 4)), dict(metodo="sucursal", producto="Clasico", precio=3000.0, plazo_dias=(None, None))]) if d != "5000" else (500, [])
    with tempfile.TemporaryDirectory() as t:
        os.makedirs(t + "/seed"); os.makedirs(t + "/data")
        import shutil
        for a in ("cp_capitales.csv", "envases_correo.csv"):
            shutil.copy(os.path.join(AQUI, "seed", a), t + "/seed/" + a)
        _tokens[("prod", "u")] = ("TK", time.time() + 3600)
        f, filas = tarifas(t, "2026-11-24", cotizar=falso2, cred=cr)
        assert 250 < f["n_items"] < 450 and f["error"] == "" and len(visto2) == f["n_items"]  # ~576*4/7
        assert f["n_con_precio"] < f["n_items"] and {x["estado"] for x in filas} == {"ok", "sin_cotizacion"}
        assert {x["metodo"] for x in filas if x["estado"] == "ok"} == {"domicilio", "sucursal"}
        guardado = rc.leer(t + "/data/correo/2026-11.csv")
        assert len(guardado) == len(filas) and next(x for x in guardado if x["metodo"] == "domicilio")["plazo_min"] == "2"
        n0 = len(visto2)
        tarifas(t, "2026-11-24", cotizar=falso2, cred=cr)  # idempotente: no duplica
        assert len(rc.leer(t + "/data/correo/2026-11.csv")) == len(guardado) and len(visto2) == 2 * n0
        assert tarifas(t, "2026-11-25", tope=3, cotizar=falso2, cred=cr)[0]["n_items"] == 3
        reloj = iter(range(0, 10**6, 400))  # el tiempo corre 400 s por pedido: corta al segundo
        fc, _ = tarifas(t, "2026-11-26", cotizar=falso2, reloj=lambda: next(reloj), cred=cr)
        assert fc["error"] == "cortado por tiempo" and fc["n_items"] == 1
        n1 = len(visto2)
        assert tarifas(t, "2026-11-24", cotizar=falso2, cred=dict(cred, ambiente="test"))[1] is None and len(visto2) == n1  # `test` no cotiza
        _tokens.clear()
    ARCHIVO = os.path.join(tempfile.mkdtemp(), ".correo_local")
    try:
        guardar(dict(cred, password="CLAVE-MICORREO", email="yo@mail"))
        txt = open(ARCHIVO, encoding="utf-8").read()
        assert "CLAVE-MICORREO" not in txt and "yo@mail" not in txt and cargar() == cred
    finally:
        os.remove(ARCHIVO)
    print("OK")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a == ["test"]:
        demo()
    elif a == ["alta"]:
        alta()
    elif a[:1] == ["tarifas"]:
        correr_tarifas(a[1:])
    elif a[:1] == ["probar"] and len(a) in (3, 4):
        probar(*a[1:])
    else:
        sys.exit(__doc__)
