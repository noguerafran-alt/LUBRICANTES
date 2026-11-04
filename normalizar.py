"""Aviso de tienda → (marca, sae, litros, unidades, producto_id, match).

Uso: normalizar(titulo, marca_vtex, ean). `python normalizar.py test` corre los asserts.
"""
import csv
import os
import re
import sys
import unicodedata

AQUI = os.path.dirname(os.path.abspath(__file__))

MARCAS = [  # (canónica, regex sobre texto normalizado). El orden importa: gana la primera.
    ("YPF", r"\b(elaion|ypf|extravida|rod)\b"),
    ("Shell", r"\b(shell|helix|rimula)\b"),
    ("Castrol", r"\b(castrol|edge|magnatec|gtx|vecton)\b"),
    ("Mobil", r"\b(mobil|delvac)\b"),
    ("Elf", r"\belf\b"),
    ("TotalEnergies", r"\b(totalenergies|total|quartz|rubia)\b"),
    ("Gulf", r"\bgulf\b"),
    ("Petronas", r"\b(petronas|syntium|urania)\b"),
    ("Motul", r"\bmotul\b"),
    ("Bardahl", r"\bbardahl\b"),
    ("Puma", r"\bpuma\b"),
    ("Valvoline", r"\bvalvoline\b"),
    ("Pennzoil", r"\b(pennzoil|penzzoil)\b"),
    ("Liqui Moly", r"\bliqui\s*moly\b"),
    ("Goodyear", r"\bgoodyear\b"),
]

# Sin \b adelante del número de verano: "15w501l" (ChangoMás) pega SAE y litros.
SAE_MULTI = re.compile(r"\b(0|5|10|15|20|25)\s*w\s*[-/ ]?\s*(20|30|40|50|60)(?!\d\d)")
SAE_GEAR = re.compile(r"\b(75|80|85)\s*w\s*-?\s*(90|140)\b")
SAE_MONO = re.compile(r"\bsae\s*(30|40|50|90|140)\b")
LITROS = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(l|lt|lts|litro|litros)\b")
ML = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(ml|cc|c\.c\.)(?!\w)")
X_FINAL = re.compile(r"\bx\s*(\d+)\s*$")
LINEA_YPF = re.compile(r"\b(mi|ts|fs|tf)\s*\d{3,4}\b")  # códigos Elaion/Extravida: MI 1540, TS 1040, FS 540
GRUPO = {"Elf": "TotalEnergies"}  # Elf es marca de TotalEnergies: compatibles al matchear, sin fusionar en productos.csv
UNIDADES = re.compile(r"x\s*(\d+)\s*unidades")


def texto(s):
    s = (s or "").replace("�", "").replace("\xa0", " ").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def marca_de(s):
    t = texto(s)
    for canon, rx in MARCAS:
        if re.search(rx, t):
            return canon
    return ""


def sae_de(t):
    """Devuelve (sae, texto sin el SAE) para que el SAE no se lea como litros."""
    m = SAE_GEAR.search(t)
    if m:
        return f"{m[1]}W-{m[2]}", t[:m.start()] + " " + t[m.end():]
    m = SAE_MULTI.search(t)
    if m:
        return f"{m[1]}W-{m[2]}", t[:m.start()] + " " + t[m.end():]
    m = SAE_MONO.search(t)
    if m:
        return f"SAE {m[1]}", t[:m.start()] + " " + t[m.end():]
    return "", t


def cargar(ruta_alias=None, ruta_productos=None):
    """Lee alias.csv y productos.csv. Si no existen (seed vacío) no matchea nada."""
    ruta_alias = ruta_alias or os.path.join(AQUI, "seed", "alias.csv")
    ruta_productos = ruta_productos or os.path.join(AQUI, "seed", "productos.csv")
    prod = {}
    if os.path.exists(ruta_productos):
        with open(ruta_productos, encoding="utf-8", newline="") as f:
            prod = {r["producto_id"]: r for r in csv.DictReader(f)}
    eans, textos = {}, []
    if os.path.exists(ruta_alias):
        with open(ruta_alias, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r["tipo"] == "ean":
                    eans[r["valor"].strip().lstrip("0")] = r["producto_id"]
                elif r["tipo"] == "texto" and r["producto_id"] in prod:
                    p = prod[r["producto_id"]]
                    textos.append((re.compile(r["valor"]), r["producto_id"], p["marca"], p["sae"]))
    return {"ean": eans, "texto": textos, "sae": {k: v["sae"] for k, v in prod.items()}}


_REGLAS = None


def url_contradice(t, sae, litros, url):
    """True si el slug de la URL trae otro SAE u otros litros que el título (aviso mal armado: no se atribuye)."""
    slug = texto(re.sub(r"/p$", "", (url or "").rstrip("/")).rsplit("/", 1)[-1]).replace("-", " ")
    u_sae, resto = sae_de(slug)
    if u_sae and sae and u_sae != sae:
        return True
    m = LITROS.search(resto)
    return bool(m and litros is not None and float(m[1].replace(",", ".")) != litros)


def normalizar(titulo, marca_vtex="", ean="", reglas=None, url=""):
    global _REGLAS
    if reglas is None:
        if _REGLAS is None:
            _REGLAS = cargar()
        reglas = _REGLAS
    t = texto(titulo)
    marca = marca_de(marca_vtex) or marca_de(titulo)
    sae, resto = sae_de(t)

    m = UNIDADES.search(t)
    unidades = int(m[1]) if m else 1

    pid, match = "", "none"
    # ML trae varios EAN por aviso ("a, b") y a veces con ceros de más (UPC en 14 dígitos): sirve si todos los conocidos dan el mismo producto.
    por_ean = {reglas["ean"][e] for e in (x.strip().lstrip("0") for x in (ean or "").split(",")) if e in reglas["ean"]}
    g = lambda x: GRUPO.get(x, x)
    if len(por_ean) == 1:
        pid, match = por_ean.pop(), "ean"
    elif marca:
        cand = {p for rx, p, pm, ps in reglas["texto"]
                if g(pm) == g(marca) and (not sae or ps == sae) and rx.search(t)}
        if len(cand) == 1:
            pid, match = cand.pop(), "texto"

    litros = None
    m = LITROS.search(resto)
    if m:
        litros = float(m[1].replace(",", "."))
    else:
        m = ML.search(resto)
        if m:
            litros = float(m[1].replace(",", ".")) / 1000
        # "x 4" al final solo se lee como litros si es aceite: SAE, producto con SAE o código Elaion/Extravida
        elif sae or reglas["sae"].get(pid) or LINEA_YPF.search(resto):
            m = X_FINAL.search(resto)
            if m:
                litros = float(m[1])
    if match != "none" and url_contradice(t, sae, litros, url):
        pid, match = "", "none"
    return dict(marca=marca, sae=sae, litros=litros, unidades=unidades, producto_id=pid, match=match)


def demo():
    import tempfile
    d = tempfile.mkdtemp()
    ra, rp = os.path.join(d, "alias.csv"), os.path.join(d, "productos.csv")
    with open(rp, "w", encoding="utf-8") as f:
        f.write("producto_id,marca,sae\n"
                "ypf-elaion-mi1540-15w40,YPF,15W-40\n"
                "ypf-elaion-mi2050-20w50,YPF,20W-50\n"
                "ypf-elaion-ts1040-10w40,YPF,10W-40\n"
                "ypf-elaion-fs540-5w40,YPF,5W-40\n"
                "shell-helix-hx7-10w40,Shell,10W-40\n"
                "totalenergies-quartz-7000-10w40,TotalEnergies,10W-40\n"
                "elf-evolution-900-ft-5w40,Elf,5W-40\n")
    with open(ra, "w", encoding="utf-8") as f:
        f.write("producto_id,tipo,valor\n"
                r"ypf-elaion-mi1540-15w40,texto,\bmi\s*1540\b|\bf\s*10\b" "\n"
                r"ypf-elaion-mi2050-20w50,texto,\bmi\s*2050\b|\bf\s*10\b" "\n"
                r"ypf-elaion-ts1040-10w40,texto,\bts\s*1040\b|\bf\s*30\b|elaion.*semi\s*-?sint|semi\s*-?sint.*elaion" "\n"
                r"ypf-elaion-fs540-5w40,texto,\bfs\s*540\b" "\n"
                r"shell-helix-hx7-10w40,texto,\bhx\s*7\b" "\n"
                "totalenergies-quartz-7000-10w40,ean,7798038700728\n"
                r"elf-evolution-900-ft-5w40,texto,\bevolution\s*900\b" "\n")
    R = cargar(ra, rp)

    def n(titulo, marca="", ean="", url=""):
        return normalizar(titulo, marca, ean, reglas=R, url=url)

    # Easy: nombre viejo y nuevo juntos; el SAE descarta MI 2050 (también es F10).
    r = n("Elaion F10 15W40 MI 1540")
    assert r == dict(marca="YPF", sae="15W-40", litros=None, unidades=1,
                     producto_id="ypf-elaion-mi1540-15w40", match="texto"), r
    # Carrefour: sin SAE en el título, el código alcanza.
    r = n("Aceite Elaion FS 540 4 lts", "Elaion")
    assert (r["litros"], r["sae"], r["producto_id"]) == (4.0, "", "ypf-elaion-fs540-5w40"), r
    # Easy: sin código de línea, matchea por "semisintético" + YPF + SAE.
    r = n("Lubricante Semisintético 10W40 4 Lts YPF Elaion", "YPF")
    assert (r["marca"], r["sae"], r["litros"], r["producto_id"]) == ("YPF", "10W-40", 4.0, "ypf-elaion-ts1040-10w40"), r
    # Jumbo: "F10 Mineral" sin SAE puede ser MI 1540 o MI 2050 → no se adivina.
    r = n("Elaion F10 Mineral 1 L", "YPF")
    assert (r["producto_id"], r["match"], r["litros"]) == ("", "none", 1.0), r
    # Jumbo: marca VTEX "SHELL", litros pegados a la x.
    r = n("Lubricante Helix Hx7 X1l (sn/cf/a3/b4)mf-s/e-un.-1", "SHELL")
    assert (r["marca"], r["litros"], r["producto_id"]) == ("Shell", 1.0, "shell-helix-hx7-10w40"), r
    # Marca de otro producto: Gulf no matchea el regex YPF aunque diga 10W-40 semisintético.
    r = n("Aceite Gulf max ultra plus 10W-40 4 lts", "Gulf")
    assert (r["marca"], r["sae"], r["producto_id"]) == ("Gulf", "10W-40", ""), r
    # ChangoMás: EAN conocido gana sobre el texto.
    r = n("Lubricante Totalenergies 7000 10w40 4l", "TotalEnergies", "7798038700728")
    assert (r["marca"], r["match"], r["producto_id"], r["litros"]) == ("TotalEnergies", "ean", "totalenergies-quartz-7000-10w40", 4.0), r
    # ChangoMás: SAE y litros pegados.
    r = n("Aceite Elf Moto 4 Road 15w501l", "Elf")
    assert (r["marca"], r["sae"], r["litros"]) == ("Elf", "15W-50", 1.0), r
    # Formatos de SAE reales.
    assert n("Aceite Elaion F30 10w 40 x 4 l.")["sae"] == "10W-40"
    assert n("Aceite Elf Evolution 500 Ts 15W 40 x 1 Lt")["sae"] == "15W-40"
    assert n("Puma gear oil ep 80w90 gl5  x 1 l")["sae"] == "80W-90"
    assert n("Puma hd super sae 40 mineral sj x 4 l")["sae"] == "SAE 40"
    # ml y cc → litros; los 1540 del código no son litros.
    assert n("Agua desmineralizada Bulnez 950 ml")["litros"] == 0.95
    assert n("Lubrax Essencial 2t Sae 30 x 500cc")["litros"] == 0.5
    assert n("Lubricante Ypf Elaion Mi 1540 4l")["litros"] == 4.0
    assert n("Aceite Penzzoil X 3.8 Lt Ultra Turbo-10w40  Pvc 3.8 Lt.", "PENNZOIL")["litros"] == 3.8
    # "x 4" final: solo con SAE (aceite de motor); sin SAE no se lee.
    assert n("Lubricante Elaion F10 15W40 MI 1540 x 4")["litros"] == 4.0
    assert n("Grasa multiuso Salkor x 4")["litros"] is None
    assert n("Aceite Elaion 15w40 x 4 lt  f10")["litros"] == 4.0
    # Unidades.
    assert n("Aceite Quartz 9000 5w40 x 12 unidades 1 l")["unidades"] == 12
    # Acentos rotos de YPF GraphQL y marca VTEX compuesta.
    assert texto("Sint�tico Lubricación") == "sinttico lubricacion"
    assert marca_de("Elaion Ypf") == "YPF" and marca_de("QUARTZ") == "TotalEnergies" and marca_de("Quim Bat") == ""
    # Elaion sin SAE: el código de línea habilita "x 4".
    assert n("ACEITE ELAION MI 1540 X 4", "YPF")["litros"] == 4.0
    assert n("ACEITE ELAION TS 1040 X 1")["litros"] == 1.0 and n("ACEITE ELAION FS 540 X 4")["litros"] == 4.0
    # Elf y TotalEnergies compatibles al matchear (Carrefour publica Elf con marca VTEX TotalEnergies).
    r = n("Aceite Evolution 900 5W40 Sintetico Ft 1LT", "TotalEnergies")
    assert (r["marca"], r["producto_id"]) == ("TotalEnergies", "elf-evolution-900-ft-5w40"), r
    # URL que contradice al título (Easy/Bardahl: título 10W-40, URL 25W-60 x4): no se atribuye.
    u = "https://www.easy.com.ar/lubricante-25w60-x4lts-bardahl/p"
    r = n("Aceite Shell Helix HX7 10W40 1 L", "Shell", url=u)
    assert (r["producto_id"], r["match"]) == ("", "none"), r
    r = n("Aceite Shell Helix HX7 10W40 1 L", "Shell", url="https://x.com/aceite-helix-hx7-10w40-1l/p")
    assert r["producto_id"] == "shell-helix-hx7-10w40", r
    r = n("Aceite Shell Helix HX7 10W40 1 L", "Shell", url="https://x.com/aceite-helix-hx7-10w40-4l/p")
    assert r["match"] == "none", r
    # EAN con ceros de más y lista de EAN de ML; dos productos distintos en la lista = sin match por EAN.
    assert n("x", "", "07798038700728")["producto_id"] == "totalenergies-quartz-7000-10w40"
    assert n("x", "", "111, 7798038700728")["match"] == "ean"
    assert n("x", "", "7798038700728, 7798038700729")["match"] == "ean"
    # Edge: sin alias propio, Professional y Titan no caen en los Edge genéricos (Castrol Edge real vive en seed/).
    R2 = cargar()
    def m(t, marca="Castrol"): return normalizar(t, marca, "", reglas=R2)["producto_id"]
    assert m("Aceite Castrol Edge Professional 0W-20 4L") == "" and m("Castrol Edge Titan 5W-30 4L") == ""
    assert m("Aceite Sintético Castrol Edge 0w20 4 Litros") == "castrol-edge-c5-0w20"
    assert m("Aceite Castrol Edge 5w-40 A3/B4 4L") == "castrol-edge-5w40" and m("Castrol Edge 10W-60 4 L") == "castrol-edge-10w60"
    assert m("Aceite Castrol Edge Turbo Diesel 5w-40 1l") == "castrol-edge-turbo-diesel-5w40"
    # Un "ultra" suelto al final del título no puede abrir el alias genérico de Helix Ultra (regresión Pro AF, ML).
    assert m("Aceite Shell Helix Ultra Pro Af 5w30 Sintetico 4 L 5w30 ultra", "Shell") == "shell-helix-ultra-professional-af-5w30"
    assert m("Aceite Shell Helix Ultra 5w30 4l", "Shell") == "shell-helix-ultra-5w30" and m("Shell Helix Ultra 5W-40 1 L", "Shell") == "shell-helix-ultra-5w40"
    # "Helix Ultra HX8" mezcla dos líneas: sin match (no se adivina), y HX8 Professional AV sigue entrando.
    assert m("Combo Sintético HELIX ULTRA HX8 5W-40 X 4L", "Shell") == ""
    assert m("Combo Sintético Shell Helix HX8 Professional AV 5W-40 (4 Litros)", "Shell") == "shell-helix-hx8-professional-av-5w40"
    # Quineo sin variante: no se adivina.
    assert m("Aceite Total Quartz Ineo 5w-30 1l", "TotalEnergies") == ""
    # Casos nuevos del seed.
    assert m("Aceite Petronas Syntium 3000 XS 5W-30 100% Sintético x4L", "Petronas") == "petronas-syntium-3000-xs-5w30"
    assert m("Aceite Petronas Syntium 3000 FR 5W-30 x4L", "Petronas") == "petronas-syntium-3000-fr-5w30"
    assert m("Aceite Petronas Syntium 500 15w40 Mineral X 4 Litros", "Petronas") == "petronas-syntium-500-15w40"
    assert m("Aceite Petronas Syntium 3000 5w40 4L", "Petronas") == ""  # falta la variante (AM/AV/BV)
    assert m("Aceite Para Motor Elf Evolution 700st Semi Sintetico 15w50 4Lts", "Elf") == "elf-evolution-700-15w50"
    assert m("Aceite Shell Helix Hx3 Sae 40 1 Litro", "Shell") == "shell-helix-hx3-sae40"
    assert m("Aceite Shell Rimula R4 15w40 20lt", "Shell") == ""  # R4 L o R4 X: ambiguo
    assert m("Aceite Magnatec 10w-30 4l Castrol") == "castrol-magnatec-10w30"
    assert m("Aceite Castrol Magnatec Stop Start 5w30 C3 Auto Sintetico 4l") == "castrol-magnatec-stop-start-c3-5w30"
    assert m("Aceite Valvoline Advanced Sintetico 5w20 4.73 Lts", "Valvoline") == "valvoline-advanced-5w20"
    assert m("Motul 4100 10w40 X4lt Semi-sintetico", "Motul") == "motul-4100-10w40"
    assert m("Aceite Shell Helix Ultra 0w30 Vw 504.00 507.00", "Shell") == ""
    # Seed vacío (rutas inexistentes) → nunca matchea, no explota.
    assert normalizar("Aceite Elaion FS 540 4 lts", "Elaion", "", cargar(ra + "x", rp + "x"))["match"] == "none"
    print("OK")


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        demo()
