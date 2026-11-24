"""Cliente Mercado Libre: solo API oficial (ToS 7.5/7.6 prohíben scraping).

Sin token: /categories/{id}. Con token (secrets ML_CLIENT_ID, ML_CLIENT_SECRET,
ML_REFRESH_TOKEN, o .ml_local en la PC): /products/search + /products/{id}/items (probado
2026-11-04). /items/bulk da [{}], /items?ids= 403 y /sites/MLA/search 403 con este token.
`python ml.py test` corre los asserts.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.mercadolibre.com"
UA = "LUBRICANTES/1.0 (relevamiento diario de precios de lubricantes, 1 req/s)"
# Aceites (MLA432536): Para Motor y sus hermanas.
CATEGORIAS = ["MLA375007", "MLA456128", "MLA438870", "MLA432538"]
# El refresh nuevo va a este archivo y nunca a stdout: la Action lo sube con gh secret set.
ARCHIVO_REFRESH = os.environ.get("ML_REFRESH_ARCHIVO", ".ml_refresh_nuevo")
# Credenciales de la PC (las deja `python ml.py autorizar`); en .gitignore.
ARCHIVO_LOCAL = os.environ.get("ML_LOCAL", ".ml_local")
# Provisorio: dominio propio en Render hasta que LUBRICANTES tenga el suyo (cambiarlo también en DevCenter).
REDIRECT = "https://lubricantes.fln-data-analysis.com/ml-callback"  # tiene que ser idéntica a la Redirect URI de la app en el devcenter
# Líneas YPF; las de la competencia salen de los equivalentes del seed (`busquedas()`).
BUSQUEDAS_YPF = ["elaion", "extravida", "rod ypf", "ypf aceite"]
TOPE_PRODUCTOS = 50  # por búsqueda; se loguea cuántas búsquedas se cortan
TOPE_ITEMS = 100     # publicaciones por producto

_ultimo = {}  # host → hora del último request
ULTIMO_ERROR = {}  # código HTTP → cuerpo recortado de la última respuesta de error (para el diagnóstico en fuentes.csv)
TOKEN_HOY = None  # access token que canjeó `avisos()` en esta corrida: lo reusa la cotización de envíos (el refresh rota en cada canje: no se canjea dos veces)
METODOS_ENVIO = {"address": "domicilio", "agency": "agencia", "pickup": "retiro", "self_service": "retiro"}  # shipping_option_type → metodo; otro tipo no se adivina


def https(u, base=""):
    """URL absoluta https o None (las fotos solo se guardan si son https)."""
    u = urllib.parse.urljoin(base, u.strip()) if u and u.strip() else ""
    return u if u.startswith("https://") else None


def busquedas(raiz=None):
    """Búsquedas de ML: líneas YPF + "marca línea" de cada competidor que figura en seed/equivalencias.csv."""
    import csv
    raiz = raiz or os.path.dirname(os.path.abspath(__file__))
    leer = lambda n: list(csv.DictReader(open(os.path.join(raiz, "seed", n), encoding="utf-8", newline="")))
    prod = {p["producto_id"]: p for p in leer("productos.csv")}
    from normalizar import pais_producto  # ML corre sobre MLA: nada de líneas brasileñas
    comp = {f"{prod[e['comp_id']]['marca']} {prod[e['comp_id']]['linea']}".lower() for e in leer("equivalencias.csv")
            if e["comp_id"] in prod and "AR" == pais_producto(e["comp_id"]) == pais_producto(e["ypf_id"])}
    return BUSQUEDAS_YPF + sorted(comp)


def pedir(ruta, token=None, data=None, texto=False):
    """→ (http, json o None). 1 req/s por host, timeout 30 s, un reintento ante red/5xx/429.
    `data` dict va como formulario; bytes, como JSON. `texto=True` devuelve el cuerpo como str
    (HTML, XML, robots.txt). Lo usan también recolectar.py y tiendas.py."""
    url = ruta if ruta.startswith("http") else API + ruta
    host = urllib.parse.urlsplit(url).netloc
    h = {"User-Agent": UA, "Accept": "*/*" if texto else "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    if isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    elif data is not None:
        h["Content-Type"] = "application/json"
    for intento in (1, 2):
        time.sleep(max(0, _ultimo.get(host, 0) + 1 - time.time()))
        _ultimo[host] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=30) as r:
                if texto:
                    return r.status, r.read().decode("utf-8", "replace")
                try:
                    return r.status, json.loads(r.read())
                except ValueError:  # 200 con HTML (p. ej. challenge de Cloudflare)
                    return r.status, None
        except urllib.error.HTTPError as e:
            if intento == 2 or (e.code < 500 and e.code != 429):
                try:   # el cuerpo del error de ML dice el motivo (política, scope); nunca trae el token
                    ULTIMO_ERROR[e.code] = " ".join(e.read(400).decode("utf-8", "replace").split())[:300]
                except OSError:
                    pass
                return e.code, None
        except (urllib.error.URLError, TimeoutError, OSError):
            if intento == 2:
                return 0, None
        time.sleep(2)


def categorias(fecha):
    """→ (http, filas ml_oferta, error). Sin token."""
    filas, http = [], 0
    for c in CATEGORIAS:
        http, d = pedir(f"/categories/{c}")
        if not d:
            return http, [], f"categories/{c} HTTP {http}"
        filas.append(dict(fecha=fecha, categoria_id=c, categoria=d.get("name", ""),
                          total_items=d.get("total_items_in_this_category", "")))
    return http, filas, ""


def _local():
    try:
        with open(ARCHIVO_LOCAL, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _guardar_local(d):
    with open(ARCHIVO_LOCAL, "w", encoding="utf-8") as f:
        json.dump(d, f)


def token():
    """Canjea el refresh token. → (access_token o None, error).
    Credenciales: secrets de la Action (env) o, en la PC, el .ml_local que deja `autorizar`."""
    cid, sec, ref = (os.environ.get(k, "") for k in ("ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REFRESH_TOKEN"))
    local = {} if (cid and sec and ref) else _local()
    if local:
        cid, sec, ref = local.get("client_id", ""), local.get("client_secret", ""), local.get("refresh_token", "")
    if not (cid and sec and ref):
        return None, "sin token"
    http, d = pedir("/oauth/token", data=dict(grant_type="refresh_token", client_id=cid,
                                              client_secret=sec, refresh_token=ref))
    if not d or "access_token" not in d:
        return None, f"oauth HTTP {http}"
    if d.get("refresh_token"):  # rota: solo vale el último
        if local:
            _guardar_local(dict(local, refresh_token=d["refresh_token"]))
        else:
            with open(ARCHIVO_REFRESH, "w", encoding="utf-8") as f:
                f.write(d["refresh_token"])
    return d["access_token"], ""


def pkce(verifier=None):
    """→ (code_verifier, code_challenge S256), RFC 7636. La app tiene «Requiere PKCE» (seguridad del devcenter):
    sin esto el canje del code falla. Solo interviene en el alta; el refresh diario no lo usa."""
    import base64
    import hashlib
    import secrets
    v = verifier or secrets.token_urlsafe(64)
    return v, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")


def autorizar():
    """Alta inicial en la PC del usuario: pide credenciales sin mostrarlas, canjea el code
    y prueba los endpoints. Imprime solo códigos HTTP, nunca tokens."""
    import getpass
    import webbrowser
    cid = input("Client ID (App ID): ").strip()
    sec = getpass.getpass("Client Secret (no se muestra): ").strip()
    redirect = input(f"Redirect URI [{REDIRECT}]: ").strip() or REDIRECT
    verifier, challenge = pkce()
    url = "https://auth.mercadolibre.com.ar/authorization?" + urllib.parse.urlencode(
        dict(response_type="code", client_id=cid, redirect_uri=redirect, code_challenge=challenge, code_challenge_method="S256"))
    print("\nSe abre el navegador. Autorizá la app y copiá la dirección completa a la que te manda\n"
          "(la página puede dar error o 404: no importa, lo que sirve es el ?code=... de la barra).\n")
    webbrowser.open(url)
    pegado = input("Pegá la dirección completa (o solo el code): ").strip()
    code = urllib.parse.parse_qs(urllib.parse.urlsplit(pegado).query).get("code", [pegado])[0]
    http, d = pedir("/oauth/token", data=dict(grant_type="authorization_code", client_id=cid,
                                              client_secret=sec, code=code, redirect_uri=redirect, code_verifier=verifier))
    if not d or "refresh_token" not in d:
        sys.exit(f"No se pudo canjear el code (HTTP {http}): {ULTIMO_ERROR.get(http, 'sin detalle')}\n"
                 f"El code dura minutos y sirve una sola vez, y la Redirect URI tiene que ser idéntica a la del devcenter: repetí.")
    _guardar_local(dict(client_id=cid, client_secret=sec, refresh_token=d["refresh_token"]))
    tok = d["access_token"]
    print(f"\nOK: credenciales guardadas en {ARCHIVO_LOCAL} (está en .gitignore).\nPruebas:")
    http_cc, _ = pedir("/oauth/token", data=dict(grant_type="client_credentials", client_id=cid, client_secret=sec))
    print(f"  client_credentials ............ HTTP {http_cc}")
    http, s = pedir("/products/search?" + urllib.parse.urlencode(dict(status="active", site_id="MLA", q="elaion")), tok)
    print(f"  products/search?q=elaion ...... HTTP {http}, {len((s or {}).get('results', []))} productos")
    pid = ((s or {}).get("results") or [{}])[0].get("id")
    if pid:
        http, it = pedir(f"/products/{pid}/items", tok)
        print(f"  products/{pid}/items ... HTTP {http}, {len((it or {}).get('results', []))} publicaciones")
    http, _ = highlights(tok)
    print(f"  highlights MLA375007 .......... HTTP {http}")
    print("\nSiguiente: `python recolectar.py --solo ml` usa estas credenciales desde la PC.")


def highlights(tok, cat="MLA375007"):
    """Top 20 más vendidos. No se guarda todavía: no hay esquema en el contrato."""
    return pedir(f"/highlights/MLA/category/{cat}", tok)


def aceite(p):
    """Descarta lo que la búsqueda por marca trae de otros rubros (zapatillas Puma, pelucas, cervezas)."""
    d = p.get("domain_id", "")
    return "ENGINE_OILS" in d or (d.startswith("MLA-VEHICLE_") and d.endswith("_OILS"))


def aviso(prod, it):
    """Producto del catálogo + una publicación de products/{id}/items → aviso crudo.
    El título suma SAE, volumen y pack del producto si el nombre no los trae: así normalizar los lee."""
    at = {a.get("id"): a.get("value_name") or "" for a in prod.get("attributes") or []}
    t = prod.get("name", "")
    extra = [at.get("VISCOSITY_GRADE", ""), at.get("NET_VOLUME", "")]
    if at.get("UNITS_PER_PACK", "1") not in ("", "1"):
        extra.append(f"x {at['UNITS_PER_PACK']} unidades")
    t = " ".join([t] + [e for e in extra if e and e.lower() not in t.lower()])
    num = it["item_id"].removeprefix("MLA")
    tienda = it.get("official_store_id")
    foto = https(((prod.get("pictures") or [{}])[0]).get("url"))
    return dict(url=f"https://articulo.mercadolibre.com.ar/MLA-{num}", ean=at.get("GTIN", ""), titulo=t,
                marca_cruda=at.get("BRAND", ""), precio=it.get("price") or 0,
                precio_lista=it.get("original_price") or "", stock=None,
                vendedor=str(it.get("seller_id", "")) + (f" tienda:{tienda}" if tienda else ""), imagen=foto)


def _paginar(ruta, tope, token):
    """→ (http, resultados, cortado). Pagina con offset/limit hasta `tope` o hasta agotar."""
    out, http, off = [], 0, 0
    while off < tope:
        lim = min(50, tope - off)
        http, d = pedir(f"{ruta}{'&' if '?' in ruta else '?'}limit={lim}&offset={off}", token)
        if not d:
            return http, out, False
        r = d.get("results", [])
        out += r
        off += lim
        if len(r) < lim or off >= (d.get("paging") or {}).get("total", off):
            return http, out, False
    return http, out, True


def avisos(filtro=None):
    """→ (http, avisos, error). Cada aviso con las columnas crudas de obs.
    `filtro(aviso)`: si da False el producto no se baja (no se piden sus publicaciones): ahorra el grueso del tiempo.
    /items/bulk e /items dan vacío/403 con este token: el aviso sale de products/{id}/items + atributos."""
    global TOKEN_HOY
    tok, err = token()
    if not tok:
        return "", [], err
    TOKEN_HOY = tok
    prods, cortadas, http, ajenos = {}, 0, 0, 0
    qs = busquedas()
    for q in qs:
        http, rs, cortado = _paginar("/products/search?" + urllib.parse.urlencode(
            dict(status="active", site_id="MLA", q=q)), TOPE_PRODUCTOS, tok)
        if not rs and http != 200:
            return http, [], f"products/search HTTP {http}"
        cortadas += cortado
        for p in rs:
            if aceite(p):
                if filtro is None or filtro(aviso(p, dict(item_id="MLA0", price=1))):
                    prods[p["id"]] = p
                else:
                    ajenos += 1
    out, codigos = [], {}
    for pid, p in prods.items():
        h, rs, _ = _paginar(f"/products/{pid}/items", TOPE_ITEMS, tok)  # 404 = sin publicaciones, no es caída
        codigos[h] = codigos.get(h, 0) + 1
        out += [aviso(p, r) for r in rs if r.get("item_id") and r.get("condition", "new") == "new"]
    # con 0 avisos, el HTTP de /items es lo único que dice si ML cambió la API o cerró el permiso (2026-11-23: 0 sin rastro)
    vistos = ", ".join(f"HTTP {c} ×{n}" + (f" ({ULTIMO_ERROR[c]})" if c in ULTIMO_ERROR else "")
                       for c, n in sorted(codigos.items(), key=lambda x: -x[1]))
    print(f"ml: {len(qs)} búsquedas, {len(prods)} productos relacionados con YPF ({ajenos} de aceite descartados), {cortadas} búsquedas cortadas "
          f"en {TOPE_PRODUCTOS}, {len(out)} avisos; products/{{id}}/items: {vistos}", flush=True)
    if not out:
        return http, [], f"token válido pero 0 publicaciones ({len(prods)} productos encontrados; items: {vistos})"
    return http, out, ""


def item_id(url):
    """URL de un aviso (`.../MLA-1873751937`) → id de item (`MLA1873751937`) o None."""
    m = re.search(r"/(MLA)-?(\d+)$", url or "")
    return m and m.group(1) + m.group(2)


def opciones(http, d):
    """Respuesta de `items/{MLA}/shipping_options?zip_code=` → (estado, [(metodo, costo, plazo_h)]).
    `ok` con la opción más barata de cada método (costo = options[].cost, lo que paga el comprador; 0 solo si la opción declara 0).
    404/424/error HTTP/200 sin opciones legibles = `sin_cotizacion` (un hueco, nunca costo 0)."""
    mejor = {}
    for o in (d.get("options") or []) if http == 200 and isinstance(d, dict) else []:
        metodo, c = METODOS_ENVIO.get(o.get("shipping_option_type")), o.get("cost")
        if not metodo or isinstance(c, bool) or not isinstance(c, (int, float)) or c < 0:
            continue
        e = o.get("estimated_delivery_time") or {}
        h = e.get("shipping") if isinstance(e.get("shipping"), (int, float)) else None
        h = h if e.get("unit") == "hour" or h is None else h * 24 if e.get("unit") in ("day", "days") else None
        if metodo not in mejor or c < mejor[metodo][0]:
            mejor[metodo] = (c, "" if h is None else int(h))
    return ("ok", [(m, c, h) for m, (c, h) in sorted(mejor.items())]) if mejor else ("sin_cotizacion", [])


def cotizar(url, cp, tok):
    """→ (http, estado, opciones). Solo con token (robots.txt de la API es Disallow: /; se usa bajo el Programa de Desarrolladores)."""
    assert tok, "shipping_options nunca se pide sin token"
    iid = item_id(url)
    if not iid:
        return 0, "sin_cotizacion", []
    http, d = pedir(f"/items/{iid}/shipping_options?zip_code={cp}", tok)
    return (http, *opciones(http, d))


def demo():
    global ARCHIVO_LOCAL, pedir, token
    for k in ("ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REFRESH_TOKEN"):
        os.environ.pop(k, None)
    real, ARCHIVO_LOCAL = ARCHIVO_LOCAL, os.path.join("tmp", "ml_local_inexistente")
    try:
        assert avisos() == ("", [], "sin token")
        p = dict(name="Elaion F 50 F", attributes=[dict(id="BRAND", value_name="Elaion"), dict(id="GTIN", value_name="7790001"),
                 dict(id="VISCOSITY_GRADE", value_name="5W-30"), dict(id="NET_VOLUME", value_name="4 L"),
                 dict(id="UNITS_PER_PACK", value_name="2")])
        a = aviso(p, dict(item_id="MLA2006591717", price=239900, original_price=None, seller_id=55, official_store_id=7))
        assert a["url"] == "https://articulo.mercadolibre.com.ar/MLA-2006591717" and a["ean"] == "7790001"
        assert a["titulo"] == "Elaion F 50 F 5W-30 4 L x 2 unidades" and a["precio_lista"] == "" and a["stock"] is None
        assert a["vendedor"] == "55 tienda:7" and a["marca_cruda"] == "Elaion"
        assert aceite(dict(domain_id="MLA-ENGINE_OILS")) and not aceite(dict(domain_id="MLA-SNEAKERS"))
        assert aviso(dict(name="Aceite 5W-30 4 L"), dict(item_id="MLA1", price=1, seller_id=2))["titulo"] == "Aceite 5W-30 4 L"
        assert token() == (None, "sin token")
        assert pkce("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")[1] == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"  # vector de RFC 7636
        v, c = pkce()
        assert 43 <= len(v) <= 128 and pkce(v)[1] == c and pkce()[0] != v
        assert item_id("https://articulo.mercadolibre.com.ar/MLA-1873751937") == "MLA1873751937" and item_id("https://x.com/a") is None
        op = lambda c, t="address", h=None: dict(cost=c, shipping_option_type=t, **({} if h is None else dict(estimated_delivery_time=h)))
        assert opciones(200, dict(options=[op(0)])) == ("ok", [("domicilio", 0, "")])  # gratis: 0 solo si la opción lo declara
        assert opciones(200, dict(options=[op(6208, "address", dict(shipping=216, unit="hour")), op(7000), op(4500, "agency"), op(0, "pickup")])) == (
            "ok", [("agencia", 4500, ""), ("domicilio", 6208, 216), ("retiro", 0, "")])  # la más barata de cada método
        assert opciones(200, dict(options=[op(5, "address", dict(shipping=3, unit="days"))]))[1][0][2] == 72
        assert opciones(404, None) == ("sin_cotizacion", []) and opciones(424, None) == ("sin_cotizacion", []) and opciones(0, None)[0] == "sin_cotizacion"
        assert opciones(200, dict(options=[])) == ("sin_cotizacion", []) and opciones(200, dict(options=[op(5, "rara"), op(None)]))[0] == "sin_cotizacion"
        try:
            cotizar("https://articulo.mercadolibre.com.ar/MLA-1", "5000", None)
            assert False
        except AssertionError as e:
            assert "sin token" in str(e)
        assert https("//x.com/a.jpg", "https://t.com/") == "https://x.com/a.jpg" and https("http://x.com/a.jpg") is None and https("") is None
        assert aviso(dict(name="A", pictures=[dict(url="https://http2.mlstatic.com/x.jpg")]), dict(item_id="MLA1", price=1))["imagen"].endswith("x.jpg")
        assert aviso(dict(name="A"), dict(item_id="MLA1", price=1))["imagen"] is None
        # el filtro corta antes de pedir publicaciones: el producto ajeno no genera request de /items
        pedir0, token0, pedidos = pedir, token, []
        def pedir(ruta, tok=None, **k):
            pedidos.append(ruta)
            if ruta.startswith("/products/search"):
                return 200, dict(paging=dict(total=2), results=[dict(id="A", domain_id="MLA-ENGINE_OILS", name="Elaion F 50"),
                                                                dict(id="B", domain_id="MLA-ENGINE_OILS", name="Aceite Zeta")])
            return 200, dict(results=[dict(item_id="MLA5", price=10)])
        token = lambda: ("t", "")
        try:
            r = avisos(filtro=lambda a: "Elaion" in a["titulo"])
            items_http = 403   # /items cerrado: el error tiene que decir el código, no solo "0 publicaciones"
            pedir_ok = pedir
            pedir = lambda ruta, tok=None, **k: (items_http, None) if "/items" in ruta else pedir_ok(ruta, tok)
            ULTIMO_ERROR[403] = '{"message":"forbidden"}'
            r403 = avisos()
            ULTIMO_ERROR.clear()
        finally:
            pedir, token = pedir0, token0
        assert len(r[1]) == 1 and r[1][0]["titulo"] == "Elaion F 50" and not any("/products/B" in x for x in pedidos), (r, pedidos)
        assert r403[1] == [] and 'items: HTTP 403 ×2 ({"message":"forbidden"})' in r403[2], r403
        q = busquedas()
        assert q[:4] == BUSQUEDAS_YPF and "castrol edge" in q and "shell helix" in q and len(q) == len(set(q)) and "bardahl" not in q
        import tempfile
        with tempfile.TemporaryDirectory() as d:  # un par AR y uno con comp_id -br (y otro con ypf_id -br)
            os.mkdir(os.path.join(d, "seed"))
            for n, t in (("productos", "producto_id,marca,linea\nc-ar,Castrol,Edge\nc-br,Lubrax,Top-br\ny-br,YPF,Elaion\n"),
                         ("equivalencias", "eq_id,ypf_id,comp_id\n1,y,c-ar\n2,y,c-br\n3,y-br,c-ar\n")):
                open(os.path.join(d, "seed", n + ".csv"), "w", encoding="utf-8").write(t)
            assert busquedas(d) == BUSQUEDAS_YPF + ["castrol edge"], busquedas(d)
    finally:
        ARCHIVO_LOCAL = real
    print("OK")


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        demo()
    elif sys.argv[1:] == ["autorizar"]:
        autorizar()
