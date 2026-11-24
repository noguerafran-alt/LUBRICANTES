"""Tiendas sin catálogo VTEX: Shopify (D'Atri, mayorista), Tiendanube y WooCommerce (Store API).

Cada lector devuelve (http, avisos, error) como `recolectar.vtex`. Respeta robots.txt de cada host
(`robots`, propio: soporta `*`, `$` y Crawl-delay) y usa ml.pedir: 1 req/s por host y el User-Agent honesto de ml.UA.
`python tiendas.py test` corre los asserts (sin red).
"""
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
from datetime import date

import ml
from normalizar import sae_de, texto

SHOPIFY = {"shopify_datri": "https://tiendadatri.com.ar"}
TIENDANUBE = {"tn_lspalermo": "https://lspalermo.com.ar", "tn_spch": "https://spch.com.ar",
              "tn_rano": "https://repuestosrano.com.ar", "tn_olafil": "https://www.olafil.com.ar",
              "tn_lubrimaster": "https://lubrimaster.mitiendanube.com", "tn_lubricentrodg": "https://lubricentrodg.mitiendanube.com",
              "tn_exporepuestos": "https://www.exporepuestos.com", "tn_netrenault": "https://www.netrenault.com.ar",
              "tn_gramaglia": "https://gramagliarepuestos.com.ar", "tn_torooils": "https://lubricentrotorooils.mitiendanube.com",
              "tn_comprarmarket": "https://comprarmarket.com.ar"}
WOOCOMMERCE = {"woo_larutaok": "https://neumaticoslarutaok.com", "woo_ceridono": "https://ceridono.ar",
               "woo_allende": "https://www.allenderepuestos.com.ar", "woo_fiatturin": "https://www.fiatturin.com.ar"}
ODOO = {"odoo_performancelube": "https://www.performance-lube.com.ar"}
PRESTASHOP = {"presta_motoracing": "https://motoracing.com.ar"}
TERMINOS_ODOO = ("elaion", "extravida", "helix", "rimula", "quartz", "castrol", "mobil")
PRESTA_CATEGORIA = "/20-lubricantes"
TERMINOS_WOO = ("aceite", "lubricante")
MAYORISTAS = {"shopify_datri", "tn_olafil", "woo_ceridono", "tn_comprarmarket"}  # precio por caja/tambor, IVA no verificado: /api/indice los excluye

# product_type de D'Atri que son lubricantes de motor, transmisión o industriales (el resto es repuesto).
TIPOS_DATRI = {"LUBRICANTES", "LUBRICANTE", "SINTÉTICO", "SEMISINTÉTICO", "MINERAL", "MULTIGRADO", "MONOGRADO"}
# 150 páginas por tienda y día ≈ 3 min por tienda a 1 req/s: ML ya usa ~14 de los 30 min del job.
TOPE_PAGINAS = 150
OLEO = re.compile(r"aceite|lubric|elaion|helix|castrol|quartz|mobil")
NO_ACEITE = re.compile(r"filtro|kit|service|combo|bomba|pack|aerosol|limpia|aditivo|tapon|bulbo|interruptor|"
                       r"lampara|medidor|embudo|sensor|varilla|reten|anillo|calorstat|\bbidon-vacio")

# Fuentes cuyo catálogo mezcla aceite suelto con combos (aceite + filtro/colocación): el combo es un servicio y va a data/grok
# (recolectar.servicios_combo), nunca a obs ni al $/L. Daytona y Tienda Neumáticos (NEUMASUR) son el mismo catálogo VTEX: solo corre Daytona.
COMBOS = {"woo_allende", "vtex_daytona"}
COMBO = re.compile(r"\bkit\b|\bcombo\b|cambio de aceite|\+\s*filtro")  # sobre texto() (sin acentos)


def es_combo(titulo):
    """Combo de aceite: dice kit/combo/cambio y nombra aceite o lubricante, y sacadas esas palabras no queda otro repuesto (retenes, distribución…)."""
    t = texto(titulo)
    return bool(COMBO.search(t) and re.search(r"aceite|lubric", t) and not NO_ACEITE.search(re.sub(r"filtro|kit|combo|pack|service", "", t)))

CAJA = re.compile(r"(?<![\w.,])(\d+)\s*x\s*(\d+(?:[.,]\d+)?)\s*(?:l|lt|lts|litros?)\b")
GRANEL = re.compile(r"\b(?:tambor|balde|contenedor|bidon)\s*(?:de\s*)?(\d+(?:[.,]\d+)?)\s*(?:l|lt|lts|litros?)\b")
QUART = re.compile(r"\d\s*qt\b")


def envase(titulo, variante=""):
    """→ (litros por unidad, unidades) o None si no dice nada. Caja 12X1L → (1, 12); tambor 205L → (205, 1).
    Si la variante habla en quarts (1QT) y el título en litros se contradicen: litros None, no se adivina."""
    nums = lambda s: float(s.replace(",", "."))
    ambiguo = bool(QUART.search(texto(variante)))
    for txt in (titulo, variante):
        _, t = sae_de(texto(txt))  # el SAE (5W-40) no se lee como "40 x ..."
        m = CAJA.search(t)
        if m:
            return (None if ambiguo else nums(m[2])), int(m[1])
        m = GRANEL.search(t)
        if m:
            return (None if ambiguo else nums(m[1])), 1
    return None


# ---------- robots.txt ----------
_robots = {}
CRAWL_MAX = 1.0  # s: nuestro ritmo es 1 req/s; un Crawl-delay mayor y la fuente no corre


def reglas_robots(txt, ua):
    """robots.txt → ([(permite, patrón)], crawl_delay) del grupo que aplica a `ua` (el agente más específico que esté
    contenido en el UA; si no, `*`). urllib.robotparser no entiende `*` ni `$` dentro de los patrones: por eso esto."""
    grupos, agentes, reglas, delay, nuevo = [], [], [], None, True
    for linea in txt.splitlines():
        k, _, v = linea.split("#", 1)[0].partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            if not nuevo:
                grupos.append((agentes, reglas, delay))
                agentes, reglas, delay = [], [], None
            agentes.append(v.lower())
            nuevo = True
        elif k in ("allow", "disallow"):
            nuevo = False
            if v:
                reglas.append((k == "allow", v))
        elif k == "crawl-delay":
            nuevo = False
            try:
                delay = float(v)
            except ValueError:
                pass
    grupos.append((agentes, reglas, delay))
    mejor = max(((len(a), r, d) for ags, r, d in grupos for a in ags if a != "*" and a in ua.lower()), default=None, key=lambda x: x[0])
    if mejor:
        return mejor[1], mejor[2]
    # varios grupos `*` se juntan, como pide el RFC 9309
    ast = [(r, d) for ags, r, d in grupos if "*" in ags]
    return [x for r, _ in ast for x in r], next((d for _, d in ast if d is not None), None)


def ruta_permitida(reglas, ruta):
    """RFC 9309: gana la regla de patrón más largo que matchea `ruta` (path + query); en empate, Allow. Sin regla = permitido."""
    mejor = (-1, True)
    for permite, pat in reglas:
        rx = re.escape(pat).replace(r"\*", ".*")
        rx = rx[:-2] + r"\Z" if rx.endswith(r"\$") else rx
        if re.match(rx, ruta) and (len(pat), permite) > mejor:
            mejor = (len(pat), permite)
    return mejor[1]


def robots(url):
    """→ (permitido, motivo). Sin robots.txt (404) se puede; si no se pudo leer, no; Crawl-delay mayor a CRAWL_MAX, no."""
    p = urllib.parse.urlsplit(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        http, txt = ml.pedir(base + "/robots.txt", texto=True)
        _robots[base] = reglas_robots(txt, ml.UA) if txt is not None else ([], None) if http == 404 else None
    r = _robots[base]
    if r is None:
        return False, "no se pudo leer robots.txt"
    if r[1] is not None and r[1] > CRAWL_MAX:
        return False, f"robots.txt pide Crawl-delay {r[1]:g} s (leemos a 1 req/s)"
    if not ruta_permitida(r[0], p.path + ("?" + p.query if p.query else "")):
        return False, f"robots.txt no deja leer {p.path}"
    return True, ""


def permitido(url):
    return robots(url)[0]


# ---------- Shopify ----------
def avisos_shopify(base, productos):
    out = []
    for p in productos:
        if p.get("product_type") not in TIPOS_DATRI:
            continue
        vs = p.get("variants") or []
        for v in vs:
            titulo = p["title"] if len(vs) == 1 or v.get("title") == "Default Title" else f'{p["title"]} {v["title"]}'
            a = dict(url=f'{base}/products/{p["handle"]}', ean=v.get("barcode") or "", titulo=titulo, marca_cruda="",
                     precio=float(v.get("price") or 0), stock=None if v.get("available") else 0,
                     vendedor=p.get("vendor", ""), imagen=ml.https(((p.get("images") or [{}])[0]).get("src")))
            e = envase(p["title"], v.get("title", ""))
            if e:
                a["litros"], a["unidades"] = e
            out.append(a)
    return out


def shopify(fuente):
    base = SHOPIFY[fuente]
    ok, motivo = robots(base + "/products.json")
    if not ok:
        return 0, [], motivo
    avisos, http = [], 0
    for pag in range(1, 31):
        http, d = ml.pedir(f"{base}/products.json?limit=250&page={pag}")
        if d is None:
            return http, [], f"HTTP {http} en page={pag}"
        if not d.get("products"):
            break
        avisos += avisos_shopify(base, d["products"])
    return http, avisos, ""


# ---------- Tiendanube ----------
def urls_aceite(sitemap):
    """URLs /productos/ del sitemap cuyo slug parece aceite (y no filtro/kit/aerosol...)."""
    out = []
    for u in re.findall(r"<loc>([^<]+)</loc>", sitemap):
        slug = texto(u.split("/productos/", 1)[1]) if "/productos/" in u else ""
        if slug and OLEO.search(slug) and not NO_ACEITE.search(slug):
            out.append(html.unescape(u.strip()))
    return out


def elegir(urls, fecha, tope=TOPE_PAGINAS):
    """→ (urls de hoy, cuántas quedaron afuera). Si sobran, se parte el conjunto (ordenado por hash de URL)
    en k = ceil(n/tope) grupos y hoy toca el grupo `ordinal del día % k`: cada URL se lee cada k días."""
    urls = sorted(urls, key=lambda u: hashlib.sha1(u.encode()).hexdigest())
    k = max(1, -(-len(urls) // tope))
    hoy = [u for i, u in enumerate(urls) if i % k == date.fromisoformat(fecha).toordinal() % k]
    return hoy, len(urls) - len(hoy)


def parsear_tn(pagina, url):
    """HTML de un producto Tiendanube → aviso o None. El precio sale de LS.variants del producto principal
    (el JSON-LD Product de estas páginas es de los productos relacionados: no se usa).
    Con más de una variante (talles/presentaciones) no se adivina cuál es: None."""
    m = re.search(r"LS\.variants\s*=\s*", pagina)
    if not m:
        return None
    try:
        vs, _ = json.JSONDecoder().raw_decode(pagina, m.end())
    except ValueError:
        return None
    t = re.search(r'<h1[^>]*js-product-name[^>]*>\s*([^<]+)', pagina) or re.search(r'og:title"\s+content="([^"]+)', pagina)
    if len(vs) != 1 or not t:
        return None
    v = vs[0]
    stock = v.get("stock")
    a = dict(url=url, ean="", titulo=html.unescape(t[1]).strip(), marca_cruda="", precio=v.get("price_number") or 0,
             stock=0 if v.get("available") is False else (stock if isinstance(stock, int) else None), vendedor="",
             imagen=ml.https((re.search(r'og:image"\s+content="([^"]+)', pagina) or [0, ""])[1], url))
    e = envase(a["titulo"])
    if e:
        a["litros"], a["unidades"] = e
    return a


def tiendanube(fuente, fecha):
    base = TIENDANUBE[fuente]
    ini = time.time()
    http, sm = ml.pedir(base + "/sitemap.xml", texto=True)
    if not sm:
        return http, [], f"HTTP {http} en sitemap.xml"
    todas = urls_aceite(sm)
    urls, cortadas = elegir(todas, fecha)
    avisos, fallas, variantes = [], 0, 0
    for u in urls:
        if not permitido(u):
            fallas += 1
            continue
        h, pag = ml.pedir(u, texto=True)
        a = parsear_tn(pag, u) if pag else None
        if a:
            avisos.append(a)
        elif pag:
            variantes += 1
        else:
            fallas += 1
    print(f"{fuente}: {len(todas)} URLs de aceite en el sitemap, hoy {len(urls)} (tope {TOPE_PAGINAS}), "
          f"cortadas {cortadas}, sin precio legible o multivariante {variantes}, fallas {fallas}, "
          f"{time.time() - ini:.0f} s", flush=True)
    if urls and not avisos:
        return http, [], "ninguna página legible"
    return http, avisos, ""


# ---------- WooCommerce (Store API pública) ----------
def avisos_woo(productos, combos=False):
    """Productos de /wp-json/wc/store/v1/products → avisos. price viene en unidades menores (currency_minor_unit)."""
    out = []
    for p in productos:
        pr = p.get("prices") or {}
        div = 10 ** int(pr.get("currency_minor_unit", 2))
        try:
            precio = int(pr.get("price") or 0) / div
            lista = int(pr.get("regular_price") or 0) / div
        except ValueError:
            continue
        titulo = html.unescape(p.get("name") or "").strip()
        if not titulo or (NO_ACEITE.search(texto(titulo)) and not (combos and es_combo(titulo))):
            continue
        sku = (p.get("sku") or "").strip()
        a = dict(url=p.get("permalink") or "", ean=sku if re.fullmatch(r"\d{13}", sku) else "", titulo=titulo, marca_cruda="",
                 precio=precio, precio_lista=lista if lista > precio else "", stock=None if p.get("is_in_stock") else 0, vendedor="",
                 imagen=ml.https(((p.get("images") or [{}])[0]).get("src")))
        e = envase(titulo)
        if e:
            a["litros"], a["unidades"] = e
        out.append(a)
    return out


def woocommerce(fuente, fecha):
    base = WOOCOMMERCE[fuente]
    api = base + "/wp-json/wc/store/v1/products"
    ok, motivo = robots(api + "?per_page=100&page=1&search=aceite")  # con query: `Disallow: /*?` bloquea la Store API
    if not ok:
        return 0, [], motivo
    vistos, avisos, http = set(), [], 0
    for t in TERMINOS_WOO:
        for pag in range(1, 11):
            http, d = ml.pedir(f"{api}?per_page=100&page={pag}&search={t}")
            if not isinstance(d, list):
                return http, [], f"HTTP {http} en search={t} page={pag}"
            nuevos = [p for p in d if p.get("id") not in vistos]
            vistos.update(p.get("id") for p in d)
            avisos += avisos_woo(nuevos, fuente in COMBOS)
            if len(d) < 100:
                break
    return http, avisos, ""


# ---------- Odoo (website_sale) ----------
def avisos_odoo(pagina, base):
    """HTML de /shop → avisos. Precio = PRIMER oe_currency_value (ARS con IVA, formato inglés 96,566.23); el segundo es otro
    valor (parece USD, no confirmado) y no se usa. Un ribbon out_of_stock_ribbon es sin stock."""
    out = []
    for c in re.split(r'(?=<form[^>]*oe_product_cart)', pagina)[1:]:
        a = re.search(r'<a\b[^>]*itemprop="name"[^>]*>', c)
        href = a and re.search(r'href="([^"]+)"', a[0])
        nombre = a and re.match(r'([^<]*)', c[a.end():])[1]
        v = re.search(r'oe_currency_value">([\d.,]+)<', c)
        if not (href and nombre and v):
            continue
        try:
            precio = float(v[1].replace(",", ""))
        except ValueError:
            continue
        av = dict(url=urllib.parse.urljoin(base, html.unescape(href[1]).split("?")[0]), ean="", titulo=html.unescape(nombre).strip(),
                  marca_cruda="", precio=precio, stock=0 if "out_of_stock_ribbon" in c else None, vendedor="",
                  imagen=ml.https((re.search(r'<img[^>]*\bsrc="([^"]+)"', c) or [0, ""])[1], base + "/"))
        e = envase(av["titulo"])
        if e:
            av["litros"], av["unidades"] = e
        out.append(av)
    return out


def odoo(fuente, fecha):
    base = ODOO[fuente]
    ok, motivo = robots(base + "/shop?search=elaion")
    if not ok:
        return 0, [], motivo
    vistos, avisos, http = set(), [], 0
    for t in TERMINOS_ODOO:
        for pag in range(1, 11):
            ruta = "/shop" + (f"/page/{pag}" if pag > 1 else "")
            http, h = ml.pedir(f"{base}{ruta}?search={t}", texto=True)
            if h is None:
                return http, [], f"HTTP {http} en search={t} page={pag}"
            nuevos = [a for a in avisos_odoo(h, base) if a["url"] not in vistos]
            if not nuevos:
                break
            vistos.update(a["url"] for a in nuevos)
            avisos += nuevos
    return http, avisos, ""


# ---------- PrestaShop ----------
def avisos_presta(pagina, base):
    """HTML del listado → [(id, aviso)]. Precio argentino ($ 90.301,68); `Stock: <b>Sin Stock</b>` es sin stock."""
    out = []
    for c in re.split(r'(?=<article )', pagina)[1:]:
        i = re.search(r'data-id-product="(\d+)"', c)
        href = re.search(r'<a href="([^"]+)"', c)
        nombre = re.search(r'itemprop="name">([^<]+)', c)
        v = re.search(r'class="price"[^>]*>[^\d<]*([\d.]+,\d+)', c)
        if not (i and href and nombre and v):
            continue
        av = dict(url=html.unescape(href[1]), ean="", titulo=html.unescape(nombre[1]).strip(), marca_cruda="",
                  precio=float(v[1].replace(".", "").replace(",", ".")), vendedor="",
                  stock=0 if re.search(r"Stock: <b>Sin Stock", c) else None,
                  imagen=ml.https((re.search(r'<img src="([^"]+)"', c) or [0, ""])[1], base + "/"))
        e = envase(av["titulo"])
        if e:
            av["litros"], av["unidades"] = e
        out.append((i[1], av))
    return out


def prestashop(fuente, fecha):
    """Lee la categoría de lubricantes (24 por página, `?page=N`), no la búsqueda: el robots.txt de Motoracing
    bloquea `/*controller=search` y `/*ag/busqueda`."""
    base = PRESTASHOP[fuente]
    url = base + PRESTA_CATEGORIA
    ok, motivo = robots(url + "?page=1")
    if not ok:
        return 0, [], motivo
    vistos, avisos, http = set(), [], 0
    for pag in range(1, 11):
        http, h = ml.pedir(f"{url}?page={pag}", texto=True)
        if h is None:
            return http, [], f"HTTP {http} en page={pag}"
        nuevos = [x for x in avisos_presta(h, base) if x[0] not in vistos]
        if not nuevos:
            break
        vistos.update(x[0] for x in nuevos)
        avisos += [a for _, a in nuevos]
    return http, avisos, ""


def demo():
    # litros de caja y tambor
    assert envase("EDGE PROF E 0W-30 (CAJA 12X1L)") == (1.0, 12)
    assert envase("GTX 10W-40 (TAMBOR 205L)") == (205.0, 1)
    assert envase("ACTEVO ESSENTIAL 2T (CAJA 32X0.1L)") == (0.1, 32)
    assert envase("MAGNATEC STOP-START 5W-40 A3/B4 (CAJA 4X4L)", "CAJA 4 X 4L") == (4.0, 4)
    assert envase("POWER 1 4T 5W-40 (CAJA 16X1L)", "CAJA 16 X 1LT") == (1.0, 16)
    assert envase("HYSPIN VG-32 (BALDE 20L)") == (20.0, 1)
    assert envase("TECHNICLEAN S 5001 (TAMBOR 208.2)", "TAMBOR 208.2L / 55USG") == (208.2, 1)
    assert envase("Shell Helix Ultra ECT C2/C3 0W-30 12x1L") == (1.0, 12)
    assert envase("EDGE PROFESSIONAL V 0W-20 (CAJA 6X1L)", "CAJA 6 X 1QT") == (None, 6)  # litros vs quarts: no se adivina
    # "A3 X 4L" y un segundo SAE pegado ("15w40 x 4 litros") no son cajas
    assert envase("CASTROL MAGNATEC 10W-40 A3 X 4L") is None and envase("Elaion Mi 15w-40 F10 15w40 X 4 Litros") is None
    # el SAE no se lee como unidades: "5W-40 x 4 L" es un bidón, no una caja de 40
    assert envase("Aceite Helix 5W-40 x 4 L") is None and envase("CRB MULTI 15W-40 CI-4 (GRANEL)") is None
    # parseo Shopify (sin red)
    ps = [dict(title="EDGE PROF E 0W-30 (CAJA 12X1L)", handle="edge-prof-e", product_type="SINTÉTICO", vendor="D'ATRI",
               variants=[dict(title="CAJA 12 X 1L", price="480967.85", available=True)]),
          dict(title="GTX 10W-40 (TAMBOR 205L)", handle="gtx", product_type="MINERAL", vendor="D'ATRI",
               variants=[dict(title="TAMBOR 205L", price="1555367.58", available=False)]),
          dict(title="ARO DE LLANTA", handle="aro", product_type="REPUESTOS", vendor="D'ATRI",
               variants=[dict(title="Default Title", price="100", available=True)])]
    a = avisos_shopify("https://x.com", ps)
    assert len(a) == 2 and a[0]["precio"] == 480967.85 and a[0]["stock"] is None and a[0]["marca_cruda"] == ""
    assert (a[0]["litros"], a[0]["unidades"]) == (1.0, 12) and a[0]["url"] == "https://x.com/products/edge-prof-e"
    assert a[1]["stock"] == 0 and a[1]["litros"] == 205.0
    assert a[0]["imagen"] is None
    assert avisos_shopify("https://x.com", [dict(ps[0], images=[dict(src="https://cdn.x.com/a.jpg")])])[0]["imagen"] == "https://cdn.x.com/a.jpg"
    # a_obs calcula litros×unidades desde el aviso, no desde el título (sin filtro de relacionados)
    import recolectar
    f = recolectar.a_obs("shopify_datri", "2026-11-04", a)[0]
    assert (f[0]["litros"], f[0]["unidades"], f[0]["marca"]) == ("1", 12, "Castrol") and len(f) == 1
    # Tiendanube: sitemap → URLs de aceite; LS.variants del principal; JSON-LD de relacionados ignorado
    sm = ("<urlset><url><loc>https://t.com/productos/aceite-shell-helix-ultra-5w30-4l-ab1/</loc></url>"
          "<url><loc>https://t.com/productos/kit-filtros-aceite-gol/</loc></url>"
          "<url><loc>https://t.com/productos/lampara-h7/</loc></url>"
          "<url><loc>https://t.com/productos/castrol-magnatec-10w-40-x-1l/</loc></url></urlset>")
    assert urls_aceite(sm) == ["https://t.com/productos/aceite-shell-helix-ultra-5w30-4l-ab1/",
                               "https://t.com/productos/castrol-magnatec-10w-40-x-1l/"]
    pag = ('<meta property="og:title" content="Otro">'
           '<h1 class="h2 js-product-name mb-3" data-store="x">SHELL Helix Ultra X 5W-30 4L\n</h1>'
           '<script type="application/ld+json">{"@type":"Product","name":"Relacionado","offers":{"price":"999"}}</script>'
           '<script>LS.variants = [{"price_number":123888,"stock":2,"available":true,"sku":"a"}];LS.x=1;</script>')
    a = parsear_tn(pag, "https://t.com/productos/p/")
    assert (a["titulo"], a["precio"], a["stock"]) == ("SHELL Helix Ultra X 5W-30 4L", 123888, 2), a
    assert parsear_tn(pag.replace('"stock":2,"available":true', '"stock":null,"available":false'), "u")["stock"] == 0
    assert a["imagen"] is None
    assert parsear_tn('<meta property="og:image" content="//cdn.t.com/p.jpg">' + pag, "https://t.com/productos/p/")["imagen"] == "https://cdn.t.com/p.jpg"
    assert parsear_tn(pag.replace("}];", "},{}];"), "u") is None  # dos variantes: no se adivina
    assert parsear_tn("<html>sin variantes</html>", "u") is None
    # WooCommerce: precio en unidades menores, regular_price → precio_lista, sin stock, EAN en sku, filtros fuera
    P = lambda pr, rp: dict(price=str(pr), regular_price=str(rp), currency_minor_unit=2)
    pw = [dict(id=1, name="Aceite Valvoline 10w40 4 Litros", prices=P(4375000, 5000000), is_in_stock=True, sku="7790000012345",
               permalink="https://w.com/product/a/", images=[dict(src="https://w.com/a.jpg")]),
          dict(id=2, name="Aceite Shell &amp; Co 5w30 1 Litro", prices=P(1800000, 1800000), is_in_stock=False, sku="abc", permalink="https://w.com/product/b/"),
          dict(id=3, name="Filtro de aceite Gol", prices=P(100, 100), is_in_stock=True, sku="", permalink="u"),
          dict(id=4, name="Aceite 0 decimales", prices=dict(price="999", regular_price="999", currency_minor_unit=0), is_in_stock=True, sku="", permalink="u")]
    w = avisos_woo(pw)
    assert len(w) == 3 and w[0]["precio"] == 43750.0 and w[0]["precio_lista"] == 50000.0 and w[0]["ean"] == "7790000012345" and w[0]["stock"] is None
    assert w[0]["imagen"] == "https://w.com/a.jpg" and w[0]["url"] == "https://w.com/product/a/" and w[0]["vendedor"] == ""
    assert w[1]["stock"] == 0 and w[1]["precio_lista"] == "" and w[1]["ean"] == "" and w[1]["titulo"] == "Aceite Shell & Co 5w30 1 Litro" and w[2]["precio"] == 999.0
    # rotación determinística: todo el conjunto se cubre en k días, sin repetir dentro del ciclo
    urls = [f"https://t.com/productos/aceite-{i}/" for i in range(250)]
    d1, c1 = elegir(urls, "2026-11-04")
    d2, c2 = elegir(urls, "2026-11-05")
    assert len(d1) + c1 == 250 and len(d1) <= TOPE_PAGINAS and not set(d1) & set(d2) and set(d1) | set(d2) == set(urls)
    assert elegir(urls, "2026-11-04")[0] == d1 and elegir(urls[:100], "2026-11-04") == (sorted(urls[:100], key=lambda u: hashlib.sha1(u.encode()).hexdigest()), 0)
    # robots.txt propio: comodines, $, regla más larga, Allow gana el empate, grupo por UA, Crawl-delay
    R = lambda txt: reglas_robots(txt, ml.UA)
    rm = R("User-agent: *\nDisallow: /*?\nCrawl-delay: 60\n")
    assert not ruta_permitida(rm[0], "/wp-json/wc/store/v1/products?per_page=100") and ruta_permitida(rm[0], "/producto/x") and rm[1] == 60
    pdf = R("User-agent: *\nDisallow: /*.pdf$")[0]
    assert not ruta_permitida(pdf, "/a/b.pdf") and ruta_permitida(pdf, "/a/b.pdf?x=1")
    al = R("User-agent: *\nDisallow: /tienda\nAllow: /tienda/aceites")[0]
    assert ruta_permitida(al, "/tienda/aceites/x") and not ruta_permitida(al, "/tienda/otro")
    assert ruta_permitida(R("User-agent: *\nDisallow: /a\nAllow: /a")[0], "/a")  # empate: Allow
    assert ruta_permitida(R("User-agent: *\nDisallow:\n")[0], "/x") and ruta_permitida(R("")[0], "/x")
    g = R("User-agent: *\nDisallow: /\n\nUser-agent: Otro\nUser-agent: lubricantes\nAllow: /\nCrawl-delay: 0.5\n")
    assert ruta_permitida(g[0], "/x") and g[1] == 0.5  # el grupo del repo gana al `*`
    assert not ruta_permitida(R("User-agent: bot\nAllow: /\n\nUser-agent: *\nDisallow: /")[0], "/x")
    _robots["https://r.com"] = rm
    assert robots("https://r.com/producto/x")[0] is False and "Crawl-delay 60" in robots("https://r.com/producto/x")[1]
    _robots["https://r.com"] = R("User-agent: *\nDisallow: /*?\n")
    assert robots("https://r.com/producto/x") == (True, "") and "/wp-json" in robots("https://r.com/wp-json/a?b=1")[1]
    del _robots["https://r.com"]
    # Odoo: tarjeta con stock (precio con coma de miles, el 2º valor es USD y no se usa), agotada, sin precio
    T = lambda nom, href, precio, ribbon="": (
        f'<form action="/en/shop/cart/update" class="oe_product_cart h-100"><img src="/web/image/p/1" itemprop="image"/>'
        f'<span class="o_ribbon {ribbon}"></span><a class="t" itemprop="name" href="{href}" content="x">{nom}</a>'
        + (f'<span data-oe-type="monetary">$<span class="oe_currency_value">{precio}</span></span>'
           f'<div class="product_price_usd">USD<span class="oe_currency_value">61.12</span></div>' if precio else "") + "</form>")
    pg = (T("YPF ELAION FS 5W40 - 4L (EX F50)", "/en/shop/176095-ypf-elaion-23117?search=elaion", "115,923.23")
          + T("YPF ELAION MOTO 2T BALDE 20L", "/en/shop/9-x?search=e", "1,234,567.00", "out_of_stock_ribbon") + T("SIN PRECIO", "/en/shop/8-y", ""))
    o = avisos_odoo(pg, "https://p.com")
    assert len(o) == 2 and o[0]["precio"] == 115923.23 and o[0]["stock"] is None and o[0]["url"] == "https://p.com/en/shop/176095-ypf-elaion-23117"
    assert o[0]["titulo"] == "YPF ELAION FS 5W40 - 4L (EX F50)" and o[1]["stock"] == 0 and o[1]["precio"] == 1234567.0 and (o[1]["litros"], o[1]["unidades"]) == (20.0, 1)
    assert o[0]["imagen"] == "https://p.com/web/image/p/1"
    # PrestaShop: precio argentino, «Sin Stock», título sin litros queda sin litros
    A = lambda i, nom, precio, stock: (f'<article class="item" data-id-product="{i}"><a href="https://m.com/inicio/{i}-x.html" class="thumbnail"><img src="https://m.com/i.jpg"></a>'
                                        f'<h6 itemprop="name">{nom}</h6>title="Stock: <b>{stock}</b>"<span class="price">$\xa0{precio}</span></article>')
    pp = A(1, "ACEITE MAGNATEC 10W40 A3 SEMI-SINTETICO x 4lts (CASTROL)", "90.301,68", "Bajo") + A(2, "ACEITE EDGE 5W30 SUELTO", "1.234,50", "Sin Stock")
    pr = avisos_presta(pp, "https://m.com")
    assert [i for i, _ in pr] == ["1", "2"] and pr[0][1]["precio"] == 90301.68 and pr[0][1]["stock"] is None and pr[0][1]["url"] == "https://m.com/inicio/1-x.html"
    assert pr[1][1]["stock"] == 0 and pr[1][1]["precio"] == 1234.5 and "litros" not in pr[1][1] and pr[0][1]["titulo"].startswith("ACEITE MAGNATEC")
    assert "tn_comprarmarket" in MAYORISTAS and "woo_fiatturin" in WOOCOMMERCE
    print("OK")


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        demo()
