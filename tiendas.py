"""Tiendas sin catálogo VTEX: Shopify (D'Atri, mayorista) y Tiendanube (LS Palermo, Casa González).

Cada lector devuelve (http, avisos, error) como `recolectar.vtex`. Respeta robots.txt de cada host
(urllib.robotparser) y usa ml.pedir: 1 req/s por host y el User-Agent honesto de ml.UA.
`python tiendas.py test` corre los asserts (sin red).
"""
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.robotparser
from datetime import date

import ml
from normalizar import sae_de, texto

SHOPIFY = {"shopify_datri": "https://tiendadatri.com.ar"}
TIENDANUBE = {"tn_lspalermo": "https://lspalermo.com.ar", "tn_spch": "https://spch.com.ar"}
MAYORISTAS = {"shopify_datri"}  # precio por caja/tambor, IVA no verificado: /api/indice los excluye

# product_type de D'Atri que son lubricantes de motor, transmisión o industriales (el resto es repuesto).
TIPOS_DATRI = {"LUBRICANTES", "LUBRICANTE", "SINTÉTICO", "SEMISINTÉTICO", "MINERAL", "MULTIGRADO", "MONOGRADO"}
# 150 páginas por tienda y día ≈ 3 min por tienda a 1 req/s: ML ya usa ~14 de los 30 min del job.
TOPE_PAGINAS = 150
OLEO = re.compile(r"aceite|lubric|elaion|helix|castrol|quartz|mobil")
NO_ACEITE = re.compile(r"filtro|kit|service|combo|bomba|pack|aerosol|limpia|aditivo|tapon|bulbo|interruptor|"
                       r"lampara|medidor|embudo|sensor|varilla|reten|anillo|calorstat|\bbidon-vacio")

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


def permitido(url):
    """True si el robots.txt del host deja pedir `url`. Sin robots.txt (404) se puede; si no se pudo leer, no."""
    p = urllib.parse.urlsplit(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        http, txt = ml.pedir(base + "/robots.txt", texto=True)
        rp = urllib.robotparser.RobotFileParser()
        if txt is not None:
            rp.parse(txt.splitlines())
            _robots[base] = rp
        else:
            rp.parse([])
            _robots[base] = rp if http == 404 else None
    rp = _robots[base]
    return rp is not None and rp.can_fetch(ml.UA, url)


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
    if not permitido(base + "/products.json"):
        return 0, [], "robots.txt no deja leer /products.json"
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
    # rotación determinística: todo el conjunto se cubre en k días, sin repetir dentro del ciclo
    urls = [f"https://t.com/productos/aceite-{i}/" for i in range(250)]
    d1, c1 = elegir(urls, "2026-11-04")
    d2, c2 = elegir(urls, "2026-11-05")
    assert len(d1) + c1 == 250 and len(d1) <= TOPE_PAGINAS and not set(d1) & set(d2) and set(d1) | set(d2) == set(urls)
    assert elegir(urls, "2026-11-04")[0] == d1 and elegir(urls[:100], "2026-11-04") == (sorted(urls[:100], key=lambda u: hashlib.sha1(u.encode()).hexdigest()), 0)
    print("OK")


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        demo()
