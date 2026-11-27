#!/usr/bin/env python3
"""Importa el paquete de LUBRICANTES (/api/bi/paquete.zip) al proyecto de Cloudera CML. Solo stdlib, sin red, sin claves.

    python tools/cml_paquete.py importar [paquete.zip] [--destino DIR] [--forzar]
    python tools/cml_paquete.py resumen [--destino DIR] [--json]
    python tools/cml_paquete.py test

Flujo: el usuario baja paquete.zip (celu o Render), lo pasa a la PC del trabajo y lo sube a DIR/entrada/ del proyecto; un Job de CML corre `importar`.
DIR por defecto: env LUB_DESTINO o /home/cdsw/lubricantes. Resultado: DIR/actual/*.csv (sin BOM) + estado.json, copia en DIR/historico/<ultimo_dato>_<commit>/,
zip original en DIR/procesados/. Un zip roto, incompleto o con último dato anterior al de actual/ se rechaza (exit 1) sin tocar actual/ (salvo --forzar)."""
import csv, io, json, os, re, shutil, sys, tempfile, zipfile
from datetime import datetime, timezone

DESTINO = os.environ.get("LUB_DESTINO", "/home/cdsw/lubricantes")


class Rechazo(Exception):
    pass


def _csv(crudo):
    """Bytes del zip -> texto sin BOM."""
    try:
        return crudo.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise Rechazo(f"no es UTF-8: {e}")


def validar(ruta_zip):
    """Devuelve (meta, archivos{nombre: bytes sin BOM}, filas{tabla: n}). Levanta Rechazo con el motivo."""
    try:
        z = zipfile.ZipFile(ruta_zip)
        malo = z.testzip()
    except (zipfile.BadZipFile, OSError) as e:
        raise Rechazo(f"zip ilegible: {e}")
    if malo:
        raise Rechazo(f"zip corrupto en {malo}")
    nombres = set(z.namelist())
    for n in ("diccionario.csv", "LEEME.txt"):
        if n not in nombres:
            raise Rechazo(f"falta {n}")
    dic = list(csv.DictReader(io.StringIO(_csv(z.read("diccionario.csv")))))
    cols = {}
    for r in dic:
        cols.setdefault(r.get("tabla", ""), []).append(r.get("columna", ""))
    if not cols or "" in cols:
        raise Rechazo("diccionario.csv vacío o sin columnas tabla/columna")
    archivos, filas = {}, {}
    for t, esperadas in cols.items():
        if t + ".csv" not in nombres:
            raise Rechazo(f"falta {t}.csv (lo lista el diccionario)")
        texto = _csv(z.read(t + ".csv"))
        lector = csv.reader(io.StringIO(texto))
        enc = next(lector, None)
        if enc != esperadas:
            raise Rechazo(f"encabezado de {t}.csv distinto del diccionario: trae {enc}, esperado {esperadas}")
        filas[t] = sum(1 for _ in lector)
        archivos[t + ".csv"] = texto.encode("utf-8")
    leeme = _csv(z.read("LEEME.txt"))
    m = re.search(r"Ultimo dato[^:\n]*:\s*(\d{4}-\d{2}-\d{2})", leeme)
    if not m:
        raise Rechazo("el LEEME.txt no trae «Ultimo dato» con fecha")
    c = re.search(r"Commit[^:\n]*:\s*([0-9a-f]{7,40})", leeme)
    g = re.search(r"Generado:\s*(\S+)", leeme)
    archivos["diccionario.csv"] = _csv(z.read("diccionario.csv")).encode("utf-8")
    archivos["LEEME.txt"] = leeme.encode("utf-8")
    meta = {"ultimo_dato": m.group(1), "commit": c.group(1)[:12] if c else "", "generado": g.group(1) if g else ""}
    return meta, archivos, filas


def leer_estado(destino):
    try:
        with open(os.path.join(destino, "actual", "estado.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def importar(destino, ruta_zip=None, forzar=False):
    entrada = os.path.join(destino, "entrada")
    if ruta_zip is None:
        zips = sorted((os.path.join(entrada, n) for n in os.listdir(entrada) if n.lower().endswith(".zip")), key=os.path.getmtime) if os.path.isdir(entrada) else []
        if not zips:
            raise Rechazo(f"no hay ningún .zip en {entrada}")
        ruta_zip = zips[-1]
    meta, archivos, filas = validar(ruta_zip)
    previo = leer_estado(destino)
    if previo and meta["ultimo_dato"] < previo.get("ultimo_dato", "") and not forzar:
        raise Rechazo(f"último dato {meta['ultimo_dato']} es anterior al de actual/ ({previo['ultimo_dato']}); usar --forzar")
    estado = dict(meta, importado=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), origen_zip=os.path.basename(ruta_zip), filas=filas)
    archivos["estado.json"] = json.dumps(estado, ensure_ascii=False, indent=1).encode("utf-8")
    os.makedirs(destino, exist_ok=True)
    nuevo = tempfile.mkdtemp(prefix=".nuevo_", dir=destino)
    try:
        for n, b in archivos.items():
            with open(os.path.join(nuevo, n), "wb") as f:
                f.write(b)
        # historico: copia propia (si falla acá, actual/ ni se tocó)
        hist = os.path.join(destino, "historico", f"{meta['ultimo_dato']}_{meta['commit'] or 'sindato'}")
        os.makedirs(os.path.dirname(hist), exist_ok=True)
        tmp_h = hist + ".tmp"
        shutil.rmtree(tmp_h, ignore_errors=True)
        shutil.copytree(nuevo, tmp_h)
        shutil.rmtree(hist, ignore_errors=True)
        os.rename(tmp_h, hist)
        # actual: se aparta el viejo y se pone el nuevo; si falla el rename, vuelve el viejo
        actual, viejo = os.path.join(destino, "actual"), os.path.join(destino, ".actual_viejo")
        shutil.rmtree(viejo, ignore_errors=True)
        if os.path.isdir(actual):
            os.rename(actual, viejo)
        try:
            os.rename(nuevo, actual)
        except OSError:
            if os.path.isdir(viejo):
                os.rename(viejo, actual)
            raise
        shutil.rmtree(viejo, ignore_errors=True)
    finally:
        shutil.rmtree(nuevo, ignore_errors=True)
    if os.path.abspath(os.path.dirname(ruta_zip)) == os.path.abspath(entrada):
        os.makedirs(os.path.join(destino, "procesados"), exist_ok=True)
        os.replace(ruta_zip, os.path.join(destino, "procesados", os.path.basename(ruta_zip)))
    return estado


def _tabla(destino, nombre):
    try:
        with open(os.path.join(destino, "actual", nombre + ".csv"), encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return None


def resumen(destino):
    est = leer_estado(destino)
    if not est:
        raise Rechazo(f"no hay datos importados en {destino}/actual (correr importar)")
    out = {"estado": est, "indice": None, "indice_ypf": None}
    ind = _tabla(destino, "indice")
    if ind:
        dia = max(r["fecha"] for r in ind)
        out["indice"] = {"fecha": dia, "filas": [r for r in ind if r["fecha"] == dia and r["marca"] != "YPF" and r["indice"]]}
    ic = _tabla(destino, "indice_competencia")
    if ic:
        dia = max(r["fecha"] for r in ic)
        out["indice_ypf"] = {"fecha": dia, "filas": [r for r in ic if r["fecha"] == dia and r["indice"] and r["producto_id"].startswith("ypf-")]}
    return out


def texto_resumen(r):
    e = r["estado"]
    L = [f"Último dato: {e['ultimo_dato']}   Commit: {e['commit'] or 'sin dato'}   Generado: {e['generado']}   Importado: {e['importado']}",
         "Filas por tabla: " + ", ".join(f"{t}={n}" for t, n in e["filas"].items())]
    if r["indice"]:
        L += ["", f"Índice por marca (YPF = 100), {r['indice']['fecha']}:"]
        g = lambda x, k: x.get(k) or ""  # .get: el paquete real trae todas las columnas; el sintético del test, solo algunas
        L += [f"  {g(x, 'pais')} {g(x, 'segmento'):<8} {g(x, 'sae'):<7} {x['marca']:<14} indice {x['indice']:>6}  ({g(x, 'mediana_litro')} {g(x, 'moneda')}/L, n={g(x, 'n')})"
              for x in sorted(r["indice"]["filas"], key=lambda x: (g(x, "pais"), g(x, "segmento"), g(x, "sae"), x["marca"]))] or ["  (sin marcas con dato ese día)"]
    if r["indice_ypf"]:
        L += ["", f"Productos YPF frente a su competencia (competencia = 100), {r['indice_ypf']['fecha']}:"]
        L += [f"  {x['producto_id']:<42} indice {x['indice']:>6}  (n_ypf={x['n_ypf']}, n_comp={x['n_comp']})"
              for x in sorted(r["indice_ypf"]["filas"], key=lambda x: x["producto_id"])] or ["  (sin pares con dato ese día)"]
    return "\n".join(L)


def main(argv):
    if argv and argv[0] == "test":
        demo()
        return 0
    destino, forzar, js, pos, i = DESTINO, False, False, [], 1
    while i < len(argv):
        a = argv[i]
        if a == "--destino" and i + 1 < len(argv):
            destino, i = argv[i + 1], i + 1
        elif a == "--forzar":
            forzar = True
        elif a == "--json":
            js = True
        else:
            pos.append(a)
        i += 1
    try:
        if argv and argv[0] == "importar" and len(pos) <= 1:
            e = importar(destino, pos[0] if pos else None, forzar)
            print(f"OK: último dato {e['ultimo_dato']}, commit {e['commit']}, {sum(e['filas'].values())} filas en {len(e['filas'])} tablas -> {destino}/actual")
            return 0
        if argv and argv[0] == "resumen" and not pos:
            r = resumen(destino)
            print(json.dumps(r, ensure_ascii=False, indent=1) if js else texto_resumen(r))
            return 0
    except Rechazo as e:
        print("RECHAZADO: " + str(e), file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


def _zip(ruta, ultimo="2026-11-27", commit="abc123def456", cambiar=None, sin=None):
    """Zip sintético con el formato del paquete real (dos tablas, con BOM como el real)."""
    dic = "tabla,columna,tipo,unidad,descripcion,ejemplo\nprecios,fecha,fecha,,d,x\nprecios,precio,decimal,,d,1\nindice,fecha,fecha,,d,x\nindice,marca,texto,,d,x\nindice,indice,decimal,,d,1\n"
    cont = {"precios.csv": "fecha,precio\n2026-11-27,10\n", "indice.csv": f"fecha,marca,indice\n{ultimo},YPF,100\n{ultimo},Castrol,\"86,1\"\n",
            "diccionario.csv": dic, "LEEME.txt": f"Generado: 2026-11-27T19:00:00Z\nUltimo dato (ultima observacion de precio): {ultimo}\nCommit de datos servido: {commit}\n"}
    cont.update(cambiar or {})
    with zipfile.ZipFile(ruta, "w") as z:
        for n, t in cont.items():
            if n != sin:
                z.writestr(n, "﻿".encode("utf-8") + t.encode("utf-8"))
    return ruta


def demo():
    base = tempfile.mkdtemp(prefix="cml_test_")
    try:
        d = os.path.join(base, "dest")
        zp = lambda n, **k: _zip(os.path.join(base, n), **k)
        # bueno, con BOM de entrada: sale sin BOM, con estado y copia histórica
        e = importar(d, zp("a.zip"))
        assert e["ultimo_dato"] == "2026-11-27" and e["commit"] == "abc123def456" and e["filas"] == {"precios": 1, "indice": 2}
        for n in ("precios.csv", "indice.csv", "diccionario.csv", "LEEME.txt", "estado.json"):
            assert not open(os.path.join(d, "actual", n), "rb").read().startswith((b"\xef\xbb\xbf", b"\xff\xfe")), n
        assert os.path.isfile(os.path.join(d, "historico", "2026-11-27_abc123def456", "indice.csv"))
        leer = lambda: {n: open(os.path.join(d, "actual", n), "rb").read() for n in os.listdir(os.path.join(d, "actual"))}
        antes = leer()

        def rechaza(zip_, **k):
            try:
                importar(d, zip_, **k)
            except Rechazo:
                pass
            else:
                raise AssertionError("debió rechazar")
            assert leer() == antes  # actual/ intacto
        rechaza(zp("b.zip", cambiar={"indice.csv": "fecha,indice,marca\n2026-11-28,100,YPF\n"}, ultimo="2026-11-28"))  # encabezado malo
        rechaza(zp("c.zip", sin="indice.csv", ultimo="2026-11-28"))  # tabla faltante
        rechaza(zp("d.zip", sin="LEEME.txt", ultimo="2026-11-28"))
        rechaza(zp("e.zip", ultimo="2026-11-20"))  # último dato viejo
        open(os.path.join(base, "roto.zip"), "wb").write(b"PK\x03\x04basura")
        rechaza(os.path.join(base, "roto.zip"))
        # viejo con --forzar entra
        assert importar(d, zp("f.zip", ultimo="2026-11-20", commit="0123456789ab"), forzar=True)["ultimo_dato"] == "2026-11-20"
        assert leer_estado(d)["ultimo_dato"] == "2026-11-20"
        # idempotente: reimportar el mismo no duplica filas ni carpetas
        importar(d, zp("g.zip")), importar(d, zp("g.zip"))
        assert leer_estado(d)["filas"] == {"precios": 1, "indice": 2}
        assert sorted(os.listdir(os.path.join(d, "historico"))) == ["2026-11-20_0123456789ab", "2026-11-27_abc123def456"]
        assert sorted(os.listdir(d)) == ["actual", "historico"]  # sin temporales
        # sin zip: toma el más nuevo de entrada/ y lo pasa a procesados/
        os.makedirs(os.path.join(d, "entrada"))
        _zip(os.path.join(d, "entrada", "p.zip"), ultimo="2026-11-28", commit="ffffffffffff")
        assert importar(d)["ultimo_dato"] == "2026-11-28" and os.listdir(os.path.join(d, "entrada")) == [] and os.listdir(os.path.join(d, "procesados")) == ["p.zip"]
        # resumen: marcas contra YPF=100 del último día
        r = resumen(d)
        assert r["indice"]["fecha"] == "2026-11-28" and [x["marca"] for x in r["indice"]["filas"]] == ["Castrol"] and r["indice_ypf"] is None
        assert "Castrol" in texto_resumen(r) and "2026-11-28" in texto_resumen(r)
        assert main(["importar", "--destino", d]) == 1  # entrada/ vacía
        print("OK")
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


# ---- Ejemplos (sin probar en CML) ----
# Spark: una tabla por CSV. Si los ejecutores no ven /home/cdsw, subir antes los CSV a HDFS/S3.
# from pyspark.sql import SparkSession
# spark = SparkSession.builder.appName("lubricantes").getOrCreate()
# for t in ["precios", "indice", "indice_competencia", "productos", "equivalencias", "fuentes", "provincias", "fx"]:
#     (spark.read.option("header", True).option("inferSchema", True)
#           .csv(f"file:///home/cdsw/lubricantes/actual/{t}.csv")
#           .write.mode("overwrite").saveAsTable(f"lub_{t}"))
# pandas:
# import pandas as pd
# precios = pd.read_csv("/home/cdsw/lubricantes/actual/precios.csv")
# indice = pd.read_csv("/home/cdsw/lubricantes/actual/indice.csv")
