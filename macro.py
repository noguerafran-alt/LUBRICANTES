"""Indicadores de mercado: series de datos.gob.ar y ventas de lubricantes de la Secretaría de Energía (Res. SE 1104).

python macro.py series    # baja las ids de seed/macro_series.csv -> data/macro/series.csv (largo: fecha,id,valor,signo)
python macro.py energia   # CSV de ~770 MB en streaming -> data/macro/energia.csv (mes,empresa,producto,canal,provincia,cantidad)
python macro.py fx        # dólar PTAX del Banco Central do Brasil -> data/fx.csv (fecha,moneda,por_usd,fuente); ARS sale de series.csv
python macro.py test
Una fuente que falla no escribe datos: queda registrada en data/fuentes.csv (macro_series, macro_<id>, macro_energia).
"""
import csv
import io
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import recolectar
from ml import UA

AQUI = os.path.dirname(os.path.abspath(__file__))
MACRO = os.path.join(AQUI, "data", "macro")
SEED = os.path.join(AQUI, "seed", "macro_series.csv")
FUENTES_CSV = os.path.join(AQUI, "data", "fuentes.csv")
FX_CSV = os.path.join(AQUI, "data", "fx.csv")
FX_F = ["fecha", "moneda", "por_usd", "fuente"]
# Fechas en MM-DD-AAAA. La Action corre a las 06:00 ART y la PTAX del día sale después de las 13 h: se pide una ventana para
# recuperar los días que una corrida se salteó (reemplazar es idempotente por fecha+moneda).
PTAX_URL = ("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoDolarPeriodo(dataInicial=@dataInicial,"
            "dataFinalCotacao=@dataFinalCotacao)?@dataInicial='{d}'&@dataFinalCotacao='{h}'&$format=json")
FX_VENTANA_DIAS = 10

SERIES_URL = "https://apis.datos.gob.ar/series/api/series/"
LIMITE = 5000  # la API corta ahí; el tipo de cambio diario lo supera y se pagina con start=
SERIES_F = ["fecha", "id", "valor", "signo"]
ENERGIA_F = ["mes", "empresa", "producto", "canal", "provincia", "cantidad"]
# Una serie cuyo último dato publicado es más viejo que esto está cortada (hay ids que existen pero se frenaron años atrás).
MAX_ATRASO_DIAS = {"D": 120, "M": 150, "T": 300}

CKAN = "http://datos.energia.gob.ar/api/3/action/package_show?id=5bdc436c-60d4-4c86-98ab-59834d047700"
RECURSO_ID = "f0e4e10a-e4b8-44e6-bd16-763a43742107"
ENERGIA_URL = ("http://datos.energia.gob.ar/dataset/5bdc436c-60d4-4c86-98ab-59834d047700/resource/" + RECURSO_ID +
               "/download/ventas-excluye-ventas-a-empresas-del-sector-.csv")
ENERGIA_COLS = ["anio", "mes", "empresa", "subtipodecomercializacion", "producto", "provincia", "cantidad"]
TODAS = "Todas"
DEADLINE_S = 25 * 60  # el job admite 30 min

# Etiqueta corta por empresa (clave = nombre en mayúsculas sin puntos; se busca por prefijo). Lo no mapeado queda con su nombre.
ETIQUETAS = [
    ("YPF", "YPF"),
    ("SHELL", "Shell/Raízen"),
    ("RAIZEN", "Shell/Raízen"),
    ("TOTAL ESPECIALIDADES", "TotalEnergies"),
    ("PAN AMERICAN ENERGY", "PAE/Axion"),
    ("AXION", "PAE/Axion"),
    ("PETRONAS LUBRICANTS", "Petronas"),
    ("FERCOL", "Fercol"),
    ("DESTILERIA ARGENTINA", "DAPSA"),
    ("FUCHS", "Fuchs"),
    ("NYNAS", "Nynas"),
    ("ESSO", "Esso"),
    ("PETROBRAS", "Petrobras"),
    ("GULF", "Gulf"),
    ("INTERLUB", "Interlub"),
    ("TEXACO", "Texaco"),
    ("AGIP", "Agip"),
    ("MOBIL", "Mobil"),
]


def etiqueta(empresa):
    k = re.sub(r"[.,]", "", empresa.upper()).replace("Í", "I").replace("É", "E").strip()
    for pref, corta in ETIQUETAS:
        if k.startswith(pref):
            return corta
    return empresa.strip()


def corto(sid):
    return "macro_" + re.sub(r"\W+", "_", sid).lower()


def pedir(url, timeout=60):
    """Un reintento ante error de red. Devuelve (status, bytes)."""
    for intento in (1, 2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except OSError as e:
            if intento == 2:
                raise
            print("reintento:", url[:90], e, flush=True)
            time.sleep(3)


def filas_serie(texto):
    """CSV de una sola serie (indice_tiempo,<nombre>) → [(fecha, valor_texto o '')]."""
    lector = csv.reader(io.StringIO(texto))
    next(lector, None)
    return [(f[0], f[1].strip()) for f in lector if len(f) >= 2 and f[0]]


def bajar_serie(sid):
    out, start = [], 0
    while True:
        st, cuerpo = pedir(f"{SERIES_URL}?ids={sid}&format=csv&limit={LIMITE}&start={start}")
        filas = filas_serie(cuerpo.decode("utf-8-sig"))
        out += filas
        if len(filas) < LIMITE:
            return out
        start += LIMITE


def validar_serie(frec, filas, hoy):
    """→ mensaje de error o ''. Vacía, sin ningún valor o con el último dato demasiado viejo = no sirve."""
    con_valor = [f for f, v in filas if v != ""]
    if not con_valor:
        return "sin datos (count=0 o todo nulo)"
    atraso = (hoy - date.fromisoformat(con_valor[-1])).days
    if atraso > MAX_ATRASO_DIAS.get(frec, 150):
        return f"cortada: último dato {con_valor[-1]} ({atraso} días)"
    return ""


def a_largo(sid, filas):
    """datos.gob.ar devuelve null sin ningún signo: se guarda con '...' (nunca 0). El valor sigue como texto, sin reformatear."""
    return [{"fecha": f, "id": sid, "valor": v, "signo": "" if v != "" else "..."} for f, v in filas]


def series(hoy=None):
    hoy = hoy or datetime.now(timezone(timedelta(hours=-3))).date()
    fecha = hoy.isoformat()
    seed = recolectar.leer(SEED)
    ruta = os.path.join(MACRO, "series.csv")
    previas = defaultdict(list)
    for r in recolectar.leer(ruta):
        previas[r["id"]].append(r)
    previo_fallo = {r["fuente"] for r in recolectar.leer(FUENTES_CSV) if r["fuente"].startswith("macro_") and r["error"]}
    nuevas, fuentes, ok, vacias = {}, [], 0, []
    for s in seed:
        sid, error, filas = s["id"], "", []
        try:
            filas = bajar_serie(sid)
            error = validar_serie(s["frec"], filas, hoy)
        except Exception as e:  # una serie caída no tumba a las demás
            error = f"{type(e).__name__}: {e}"[:200]
        if error:
            vacias.append(sid)
            print(f"{sid}: {error}", flush=True)
            fuentes.append(dict(fecha=fecha, fuente=corto(sid), http="", n_items=len(filas), n_con_precio=0, n_sin_stock=0,
                                n_sin_match=0, n_descartados=0, error=error))
            continue
        ok += 1
        nuevas[sid] = a_largo(sid, filas)
        print(f"{sid}: {len(filas)} filas, última {filas[-1][0]}", flush=True)
        if corto(sid) in previo_fallo:  # se recuperó: la fila buena limpia el error anterior
            fuentes.append(dict(fecha=fecha, fuente=corto(sid), http=200, n_items=len(filas), n_con_precio=len(filas), n_sin_stock=0,
                                n_sin_match=0, n_descartados=0, error=""))
    # la que falló conserva lo que ya tenía: no se borra historia por una caída
    todo = [r for s in seed for r in (nuevas.get(s["id"]) or previas.get(s["id"], []))]
    os.makedirs(MACRO, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, SERIES_F, lineterminator="\n")
        w.writeheader()
        w.writerows(todo)
    fuentes.append(dict(fecha=fecha, fuente="macro_series", http=200 if ok else "", n_items=len(seed), n_con_precio=ok, n_sin_stock=0,
                        n_sin_match=0, n_descartados=0, error="" if ok else "ninguna serie con datos"))
    recolectar.escribir_fuentes(FUENTES_CSV, fuentes)
    print(f"macro series: {ok} de {len(seed)} con datos; vacías/cortadas: {vacias or 'ninguna'}", flush=True)
    return ok, vacias


def url_energia():
    """URL del CSV según CKAN (puede cambiar); si CKAN no contesta, la directa del relevamiento."""
    try:
        st, cuerpo = pedir(CKAN, timeout=30)
        for r in json.loads(cuerpo)["result"]["resources"]:
            if r.get("id") == RECURSO_ID and r.get("url"):
                return r["url"]
    except (OSError, ValueError, KeyError) as e:
        print("CKAN no respondió, uso la URL directa:", e, flush=True)
    return ENERGIA_URL


def es_de_interes(producto):
    # Bases Lubricantes queda afuera: es insumo entre empresas, no una venta al mercado (ni entra en ningún share).
    return ("ubric" in producto and not producto.startswith("Bases")) or "Grasas" in producto or producto.startswith("Gasoil")


def agregar(lector, deadline=None):
    """Filas crudas de ventas → ({(mes, empresa, producto, canal, provincia): cantidad}, filas leídas). Valida el encabezado."""
    cab = next(lector)
    falta = [c for c in ENERGIA_COLS if c not in cab]
    if falta:
        raise ValueError(f"encabezado cambió, faltan columnas {falta}: {cab}")
    ia, im, ie, ic, ip, ipr, iq = (cab.index(c) for c in ENERGIA_COLS)
    emp, acum, n = {}, defaultdict(float), 0
    for f in lector:
        n += 1
        if not es_de_interes(f[ip]):
            continue
        mes = f"{int(f[ia]):04d}-{int(f[im]):02d}"
        if f[ip].startswith("Gasoil"):  # solo se usa por canal (actividad diésel): sin empresa ni provincia son ~1 M de filas menos
            acum[(mes, TODAS, f[ip], f[ic], TODAS)] += float(f[iq] or 0)
            continue
        e = emp.get(f[ie])
        if e is None:
            e = emp[f[ie]] = etiqueta(f[ie])
        acum[(mes, e, f[ip], f[ic], f[ipr])] += float(f[iq] or 0)
        if deadline and n % 500000 == 0 and time.time() > deadline:
            raise TimeoutError(f"se pasó de {DEADLINE_S // 60} min a las {n} filas")
    # El archivo rellena con 0.0000 toda la grilla empresa x canal x provincia x mes: esos ceros no informan y
    # son la mayoría de las filas. Una empresa sin fila ese mes queda "sin dato" (null), nunca 0.
    return {k: v for k, v in acum.items() if v}, n


def energia(hoy=None):
    hoy = hoy or datetime.now(timezone(timedelta(hours=-3))).date()
    t0, fila = time.time(), dict(fecha=hoy.isoformat(), fuente="macro_energia", http="", n_items=0, n_con_precio=0, n_sin_stock=0,
                                 n_sin_match=0, n_descartados=0, error="")
    ruta = os.path.join(MACRO, "energia.csv")
    try:
        url = url_energia()
        print("bajando", url, flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            fila["http"] = r.status
            acum, n = agregar(csv.reader(io.TextIOWrapper(r, encoding="utf-8-sig", newline="")), deadline=t0 + DEADLINE_S)
        fila["n_items"] = n
        if not acum:
            raise ValueError("ninguna fila de lubricantes ni gasoil: ¿cambió el nombre de producto?")
        ultimo_nuevo = max(k[0] for k in acum)
        previo = [r["mes"] for r in recolectar.leer(ruta)]
        if previo and ultimo_nuevo < max(previo):
            raise ValueError(f"el CSV retrocedió: último mes {ultimo_nuevo} < {max(previo)} ya guardado")
        filas = [dict(zip(ENERGIA_F, (*k, f"{v:.4f}".rstrip("0").rstrip(".") or "0"))) for k, v in sorted(acum.items())]
        os.makedirs(MACRO, exist_ok=True)
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, ENERGIA_F, lineterminator="\n")
            w.writeheader()
            w.writerows(filas)
        fila["n_con_precio"] = len(filas)
        print(f"macro energia: {n} filas leídas, {len(filas)} escritas ({os.path.getsize(ruta) / 1e6:.1f} MB), "
              f"último mes {ultimo_nuevo}, {time.time() - t0:.0f} s", flush=True)
    except Exception as e:  # sin escribir nada: los datos viejos siguen
        fila["error"] = f"{type(e).__name__}: {e}"[:200]
        print("macro energia FALLÓ:", fila["error"], flush=True)
    recolectar.escribir_fuentes(FUENTES_CSV, [fila])
    return fila


def filas_ptax(cuerpo):
    """JSON de CotacaoDolarPeriodo → filas de fx.csv: una por fecha de dataHoraCotacao (si hay más de un boletín, el último), BRL por USD
    = cotacaoVenda. Un día sin cotización no aparece (nunca se arrastra el anterior)."""
    por_fecha = {}
    for v in json.loads(cuerpo).get("value", []):
        dh, venta = v.get("dataHoraCotacao") or "", v.get("cotacaoVenda")
        if len(dh) >= 10 and isinstance(venta, (int, float)) and venta > 0 and dh >= por_fecha.get(dh[:10], ("",))[0]:
            por_fecha[dh[:10]] = (dh, venta)
    return [dict(fecha=f, moneda="BRL", por_usd=f"{v:.5f}".rstrip("0").rstrip("."), fuente="bcb_ptax") for f, (_, v) in sorted(por_fecha.items())]


def fx(hoy=None):
    """Baja la PTAX de los últimos FX_VENTANA_DIAS días a data/fx.csv. Si la fuente falla no escribe nada y lo deja en fuentes.csv (fx_bcb_ptax)."""
    hoy = hoy or datetime.now(timezone(timedelta(hours=-3))).date()
    fila = dict(fecha=hoy.isoformat(), fuente="fx_bcb_ptax", http="", n_items=0, n_con_precio=0, n_sin_stock=0, n_sin_match=0,
                n_descartados=0, error="")
    try:
        mdy = lambda d: d.strftime("%m-%d-%Y")
        fila["http"], cuerpo = pedir(PTAX_URL.format(d=mdy(hoy - timedelta(days=FX_VENTANA_DIAS)), h=mdy(hoy)))
        filas = filas_ptax(cuerpo)
        fila["n_items"] = len(filas)
        if not filas:
            raise ValueError(f"sin cotizaciones en los últimos {FX_VENTANA_DIAS} días")
        recolectar.reemplazar(FX_CSV, FX_F, filas, lambda f: (f["fecha"], f["moneda"]))
        fila["n_con_precio"] = len(filas)
        print(f"fx bcb_ptax: {len(filas)} cotizaciones, última {filas[-1]['fecha']} = {filas[-1]['por_usd']} BRL/USD", flush=True)
    except Exception as e:  # sin escribir nada: lo que ya había queda
        fila["error"] = f"{type(e).__name__}: {e}"[:200]
        print("fx bcb_ptax FALLÓ:", fila["error"], flush=True)
    recolectar.escribir_fuentes(FUENTES_CSV, [fila])
    return fila


def demo():
    import tempfile
    # PTAX: una fila por fecha (el último boletín del día), cotacaoVenda, fecha de dataHoraCotacao; sin día sin cotización
    ej = json.dumps({"value": [
        {"cotacaoCompra": 5.78450, "cotacaoVenda": 5.78510, "dataHoraCotacao": "2026-11-17 13:07:26.01516"},
        {"cotacaoCompra": 5.5, "cotacaoVenda": 5.5, "dataHoraCotacao": "2026-11-16 10:00:00.0"},
        {"cotacaoCompra": 5.7, "cotacaoVenda": 5.73240, "dataHoraCotacao": "2026-11-16 13:06:32.509132"},
        {"cotacaoCompra": 0, "cotacaoVenda": None, "dataHoraCotacao": "2026-11-15 13:00:00.0"}]})
    assert filas_ptax(ej) == [dict(fecha="2026-11-16", moneda="BRL", por_usd="5.7324", fuente="bcb_ptax"),
                              dict(fecha="2026-11-17", moneda="BRL", por_usd="5.7851", fuente="bcb_ptax")], filas_ptax(ej)
    assert filas_ptax('{"value": []}') == [] and "11-10-2026" in PTAX_URL.format(d="11-10-2026", h="11-18-2026")
    global FX_CSV, FUENTES_CSV, pedir, MACRO, SEED, bajar_serie
    raiz0 = tempfile.mkdtemp()
    FX_CSV, FUENTES_CSV, pedir0 = os.path.join(raiz0, "fx.csv"), os.path.join(raiz0, "fuentes.csv"), pedir
    try:
        pedir = lambda url, timeout=60: (200, ej.encode())
        assert fx(date(2026, 11, 18))["error"] == ""
        pedir = lambda url, timeout=60: (200, ej.replace("5.7851", "5.8").encode())
        fx(date(2026, 11, 18))  # idempotente: la misma fecha+moneda se reemplaza, no se duplica
        assert [(r["fecha"], r["por_usd"]) for r in recolectar.leer(FX_CSV)] == [("2026-11-16", "5.7324"), ("2026-11-17", "5.8")]
        pedir = lambda url, timeout=60: (_ for _ in ()).throw(OSError("caído"))
        assert "caído" in fx(date(2026, 11, 19))["error"] and len(recolectar.leer(FX_CSV)) == 2  # caída = no escribe, no arrastra
        assert "fx_bcb_ptax" in {r["fuente"] for r in recolectar.leer(FUENTES_CSV)}
    finally:
        pedir = pedir0
    # null de datos.gob.ar → '...' y nunca 0; los valores no se reformatean
    assert a_largo("x", [("2026-01-01", "1.5"), ("2026-02-01", "")]) == [
        {"fecha": "2026-01-01", "id": "x", "valor": "1.5", "signo": ""}, {"fecha": "2026-02-01", "id": "x", "valor": "", "signo": "..."}]
    assert filas_serie("indice_tiempo,a\n2026-01-01,1.5\n2026-02-01,\n") == [("2026-01-01", "1.5"), ("2026-02-01", "")]
    hoy = date(2026, 11, 5)
    assert "sin datos" in validar_serie("M", [], hoy) and "sin datos" in validar_serie("M", [("2026-07-01", "")], hoy)
    assert "cortada" in validar_serie("M", [("2003-06-01", "1")], hoy)
    assert validar_serie("M", [("2026-07-01", "1"), ("2026-08-01", "")], hoy) == ""
    assert validar_serie("D", [("2025-08-31", "1")], hoy).startswith("cortada")
    assert corto("302.3_S_ORIGINALJES_0_S_17") == "macro_302_3_s_originaljes_0_s_17"
    # etiquetas: prefijo, tildes y puntos
    assert etiqueta("YPF S.A.") == "YPF" and etiqueta("SHELL C.A.P.S.A.") == "Shell/Raízen" and etiqueta("TOTAL ESPECIALIDADES ARGENTINA S.A.") == "TotalEnergies"
    assert etiqueta("PAN AMERICAN ENERGY SL") == "PAE/Axion" and etiqueta("Destilería Argentina de Petróleo S.A.") == "DAPSA"
    assert etiqueta(" Empresa Rara SA ") == "Empresa Rara SA"
    # agregado: filtra productos, junta empresas y meses, cantidad 0 declarada se conserva
    cab = "anio,mes,empresa,tipodecomercializacion,subtipodecomercializacion,producto,unidad,provincia,cantidad,pais,indice_tiempo"
    crudo = [cab,
             "2026,9,YPF S.A.,Ventas,Al Público,Lubricantes automotrices(m3),(m3),Córdoba,100.5,no aplica,2026-09",
             "2026,9,YPF S.A.,Ventas,Al Público,Lubricantes automotrices(m3),(m3),Córdoba,10,no aplica,2026-09",
             "2026,9,YPF S.A.,Ventas,Agro,Gasoil Grado 2(m3),(m3),Córdoba,7,no aplica,2026-09",
             "2026,9,YPF S.A.,Ventas,Agro,Bases Lubricantes(m3),(m3),Córdoba,5,no aplica,2026-09",
             "2026,9,YPF S.A.,Ventas,Agro,Naftas(m3),(m3),Córdoba,99,no aplica,2026-09",
             "2026,9,SHELL C.A.P.S.A.,Ventas,Agro,Grasas(Ton),(Ton),Salta,0.0000,no aplica,2026-09"]
    acum, n = agregar(csv.reader(io.StringIO("\n".join(crudo))))
    assert n == 6 and len(acum) == 2 and acum[("2026-09", "YPF", "Lubricantes automotrices(m3)", "Al Público", "Córdoba")] == 110.5
    assert acum[("2026-09", "Todas", "Gasoil Grado 2(m3)", "Agro", "Todas")] == 7  # gasoil sin empresa ni provincia; naftas afuera; el 0 de grasas no se escribe
    try:
        agregar(csv.reader(io.StringIO("anio,mes\n2026,9")))
        raise AssertionError("tenía que fallar por encabezado")
    except ValueError as e:
        assert "encabezado" in str(e)
    # series(): sin red, una serie vacía no rompe a las otras, conserva su historia y deja su fila en fuentes
    raiz = tempfile.mkdtemp()
    MACRO, SEED, FUENTES_CSV = os.path.join(raiz, "macro"), os.path.join(raiz, "seed.csv"), os.path.join(raiz, "fuentes.csv")
    with open(SEED, "w", encoding="utf-8") as f:
        f.write("id,nombre,grupo,frec,unidad,fuente\nA,a,liviano,M,u,x\nB,b,liviano,M,u,x\n")
    real, hoy_r = bajar_serie, date(2026, 9, 1)
    try:
        bajar_serie = lambda sid: {"A": [("2026-06-01", "1"), ("2026-07-01", "")], "B": [("2026-07-01", "2")]}[sid]
        assert series(hoy_r) == (2, [])
        bajar_serie = lambda sid: {"A": [], "B": [("2026-07-01", "3")]}[sid]
        assert series(hoy_r) == (1, ["A"])
        largo = recolectar.leer(os.path.join(MACRO, "series.csv"))
        assert [(r["id"], r["valor"], r["signo"]) for r in largo] == [("A", "1", ""), ("A", "", "..."), ("B", "3", "")]
        fu = {r["fuente"]: r for r in recolectar.leer(FUENTES_CSV)}
        assert "sin datos" in fu["macro_a"]["error"] and fu["macro_series"]["n_con_precio"] == "1" and not fu["macro_series"]["error"]
        bajar_serie = lambda sid: {"A": [("2026-07-01", "4")], "B": [("2026-07-01", "3")]}[sid]
        series(hoy_r)  # A se recuperó: la fila buena limpia el error
        assert {r["fuente"]: r for r in recolectar.leer(FUENTES_CSV)}["macro_a"]["error"] == ""
    finally:
        bajar_serie = real
    print("OK")


if __name__ == "__main__":
    {"series": series, "energia": energia, "fx": fx, "test": demo}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
