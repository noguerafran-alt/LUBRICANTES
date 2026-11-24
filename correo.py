"""Correo Argentino, API MiCorreo (PDF oficial 08/2022): token, validación de cuenta y cotización de envío.
Credenciales solo en `.correo_local` (ignorado por git) o en CORREO_*; nunca en el repo ni en un GET.
Uso: python correo.py alta | probar <cp_origen> <cp_destino> [peso_g] | test"""
import base64
import getpass
import json
import os
import sys
import time

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
    elif a[:1] == ["probar"] and len(a) in (3, 4):
        probar(*a[1:])
    else:
        sys.exit(__doc__)
