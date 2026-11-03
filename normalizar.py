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
                    eans[r["valor"].strip()] = r["producto_id"]
                elif r["tipo"] == "texto" and r["producto_id"] in prod:
                    p = prod[r["producto_id"]]
                    textos.append((re.compile(r["valor"]), r["producto_id"], p["marca"], p["sae"]))
    return {"ean": eans, "texto": textos}


_REGLAS = None


def normalizar(titulo, marca_vtex="", ean="", reglas=None):
    global _REGLAS
    if reglas is None:
        if _REGLAS is None:
            _REGLAS = cargar()
        reglas = _REGLAS
    t = texto(titulo)
    marca = marca_de(marca_vtex) or marca_de(titulo)
    sae, resto = sae_de(t)

    litros = None
    m = LITROS.search(resto)
    if m:
        litros = float(m[1].replace(",", "."))
    else:
        m = ML.search(resto)
        if m:
            litros = float(m[1].replace(",", ".")) / 1000
        elif sae:  # "x 4" al final solo se lee como litros si es aceite (tiene SAE)
            m = X_FINAL.search(resto)
            if m:
                litros = float(m[1])
    m = UNIDADES.search(t)
    unidades = int(m[1]) if m else 1

    pid, match = "", "none"
    ean = (ean or "").strip()
    if ean and ean in reglas["ean"]:
        pid, match = reglas["ean"][ean], "ean"
    elif marca:
        cand = {p for rx, p, pm, ps in reglas["texto"]
                if pm == marca and (not sae or ps == sae) and rx.search(t)}
        if len(cand) == 1:
            pid, match = cand.pop(), "texto"
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
                "totalenergies-quartz-7000-10w40,TotalEnergies,10W-40\n")
    with open(ra, "w", encoding="utf-8") as f:
        f.write("producto_id,tipo,valor\n"
                r"ypf-elaion-mi1540-15w40,texto,\bmi\s*1540\b|\bf\s*10\b" "\n"
                r"ypf-elaion-mi2050-20w50,texto,\bmi\s*2050\b|\bf\s*10\b" "\n"
                r"ypf-elaion-ts1040-10w40,texto,\bts\s*1040\b|\bf\s*30\b|elaion.*semi\s*-?sint|semi\s*-?sint.*elaion" "\n"
                r"ypf-elaion-fs540-5w40,texto,\bfs\s*540\b" "\n"
                r"shell-helix-hx7-10w40,texto,\bhx\s*7\b" "\n"
                "totalenergies-quartz-7000-10w40,ean,7798038700728\n")
    R = cargar(ra, rp)

    def n(titulo, marca="", ean=""):
        return normalizar(titulo, marca, ean, reglas=R)

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
    # Seed vacío (rutas inexistentes) → nunca matchea, no explota.
    assert normalizar("Aceite Elaion FS 540 4 lts", "Elaion", "", cargar(ra + "x", rp + "x"))["match"] == "none"
    print("OK")


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        demo()
