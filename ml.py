"""Cliente Mercado Libre: solo API oficial (ToS 7.5/7.6 prohíben scraping).

Sin token: /categories/{id}. Con token (secrets ML_CLIENT_ID, ML_CLIENT_SECRET,
ML_REFRESH_TOKEN): /products/search, /products/{id}/items, /items/bulk, /highlights.
La parte con token NO está probada: no hay app creada en DevCenter.
`python ml.py test` corre los asserts.
"""
import json
import os
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
REDIRECT = "https://biblioteca-b8mb.onrender.com/ml-callback"
BUSQUEDAS = ["elaion", "shell helix", "castrol", "mobil", "total quartz", "petronas", "motul", "gulf"]

_ultimo = {}  # host → hora del último request


def pedir(ruta, token=None, data=None):
    """→ (http, json o None). 1 req/s por host, timeout 30 s, un reintento ante red/5xx/429.
    `data` dict va como formulario; bytes, como JSON. Lo usa también recolectar.py."""
    url = ruta if ruta.startswith("http") else API + ruta
    host = urllib.parse.urlsplit(url).netloc
    h = {"User-Agent": UA, "Accept": "application/json"}
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
                try:
                    return r.status, json.loads(r.read())
                except ValueError:  # 200 con HTML (p. ej. challenge de Cloudflare)
                    return r.status, None
        except urllib.error.HTTPError as e:
            if intento == 2 or (e.code < 500 and e.code != 429):
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


def autorizar():
    """Alta inicial en la PC del usuario: pide credenciales sin mostrarlas, canjea el code
    y prueba los endpoints. Imprime solo códigos HTTP, nunca tokens."""
    import getpass
    import webbrowser
    cid = input("Client ID (App ID): ").strip()
    sec = getpass.getpass("Client Secret (no se muestra): ").strip()
    redirect = input(f"Redirect URI [{REDIRECT}]: ").strip() or REDIRECT
    url = "https://auth.mercadolibre.com.ar/authorization?" + urllib.parse.urlencode(
        dict(response_type="code", client_id=cid, redirect_uri=redirect))
    print("\nSe abre el navegador. Autorizá la app y copiá la dirección completa a la que te manda\n"
          "(la página puede dar error o 404: no importa, lo que sirve es el ?code=... de la barra).\n")
    webbrowser.open(url)
    pegado = input("Pegá la dirección completa (o solo el code): ").strip()
    code = urllib.parse.parse_qs(urllib.parse.urlsplit(pegado).query).get("code", [pegado])[0]
    http, d = pedir("/oauth/token", data=dict(grant_type="authorization_code", client_id=cid,
                                              client_secret=sec, code=code, redirect_uri=redirect))
    if not d or "refresh_token" not in d:
        sys.exit(f"No se pudo canjear el code (HTTP {http}). El code dura minutos y sirve una sola vez: repetí.")
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


def avisos():
    """→ (http, avisos, error). Cada aviso con las columnas crudas de obs."""
    tok, err = token()
    if not tok:
        return "", [], err
    ids, http = [], 0
    for q in BUSQUEDAS:
        http, d = pedir("/products/search?" + urllib.parse.urlencode(
            dict(status="active", site_id="MLA", q=q)), tok)
        if d is None:
            return http, [], f"products/search HTTP {http}"
        ids += [p["id"] for p in d.get("results", [])]
    items = []
    for pid in dict.fromkeys(ids):
        http, d = pedir(f"/products/{pid}/items", tok)
        if d:  # un producto sin publicaciones da 404: no es caída
            items += [r["item_id"] for r in d.get("results", []) if r.get("item_id")]
    out = []
    items = list(dict.fromkeys(items))
    for i in range(0, len(items), 20):
        http, d = pedir("/items/bulk?" + urllib.parse.urlencode(dict(
            ids=",".join(items[i:i + 20]),
            attributes="body.id,body.title,body.price,body.original_price,body.seller_id,"
                       "body.available_quantity,body.permalink,body.attributes")), tok)
        if d is None:
            return http, [], f"items/bulk HTTP {http}"
        for r in d:
            b = r.get("body") or {}
            if r.get("status_code", r.get("code")) != 200 or not b:
                continue
            at = {a.get("id"): a.get("value_name") or "" for a in b.get("attributes") or []}
            out.append(dict(url=b.get("permalink", ""), ean=at.get("GTIN", ""), titulo=b.get("title", ""),
                            marca_cruda=at.get("BRAND", ""), precio=b.get("price") or 0,
                            precio_lista=b.get("original_price") or "", stock=b.get("available_quantity"),
                            vendedor=str(b.get("seller_id", ""))))
    return http, out, ""


def demo():
    global ARCHIVO_LOCAL
    for k in ("ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REFRESH_TOKEN"):
        os.environ.pop(k, None)
    real, ARCHIVO_LOCAL = ARCHIVO_LOCAL, os.path.join("tmp", "ml_local_inexistente")
    try:
        assert avisos() == ("", [], "sin token")
        assert token() == (None, "sin token")
    finally:
        ARCHIVO_LOCAL = real
    print("OK")


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        demo()
    elif sys.argv[1:] == ["autorizar"]:
        autorizar()
