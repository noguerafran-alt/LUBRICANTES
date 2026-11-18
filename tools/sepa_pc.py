"""Fuentes desde la PC: SEPA y (cada 28 días) las ventas de la SE; pushea data/ a main.

El portal de SEPA da 403 a las IP de datacenter (GitHub, Oracle) desde 2026-11-16; datos.energia.gob.ar da timeout
desde GitHub (2026-11-18). Nota Paraná está pausada (datos señuelo, ver CLAUDE.md). Desde una IP residencial responden. Corre en un CLON DEDICADO (reset --hard seguro) con el marcador `.sepa_pc` en la raíz.
Ciclo: fetch/reset -> pasos -> add data/ -> un commit -> push (3 intentos). Un paso que falla no frena a los demás; su fila de error igual se pushea.

python tools/sepa_pc.py        # una corrida; log en sepa_pc.log; salida != 0 si falla algún paso
python tools/sepa_pc.py test   # asserts sin red
"""
import csv
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REINTENTOS = 3
DIAS_ENERGIA = 28  # el CSV de la SE pesa ~770 MB y es mensual: no se baja a diario


def hay_marcador(raiz):
    return (Path(raiz) / ".sepa_pc").is_file()


def energia_vencida(raiz, hoy=None):
    """True si no hay en data/fuentes.csv una fila macro_energia sin error de los últimos DIAS_ENERGIA días."""
    hoy = hoy or date.today()
    ruta = Path(raiz) / "data" / "fuentes.csv"
    if not ruta.is_file():
        return True
    desde = (hoy - timedelta(days=DIAS_ENERGIA)).isoformat()
    with open(ruta, encoding="utf-8", newline="") as f:
        return not any(r["fuente"] == "macro_energia" and not r["error"] and r["fecha"] >= desde for r in csv.DictReader(f))


def mensaje_commit(fecha, nombres):
    return f"datos {fecha}: pc ({', '.join(nombres)})"


def push_rechazado(rc, salida):
    """Solo un rechazo por adelanto del remoto se reintenta; otro error de push (red, permisos) no."""
    s = salida.lower()
    return rc != 0 and ("rejected" in s or "non-fast-forward" in s or "fetch first" in s)


def git(raiz, *args):
    p = subprocess.run(["git", *args], cwd=raiz, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr).strip()


def actualizar(raiz):
    for args in (("fetch", "origin"), ("reset", "--hard", "origin/main")):
        rc, s = git(raiz, *args)
        if rc:
            return rc, s
    return 0, ""


def paso(raiz, *cmd):
    p = subprocess.run([sys.executable, *cmd], cwd=raiz, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    return p.returncode, (p.stdout + p.stderr).strip()


def pasos(raiz):
    """[(nombre, función(raiz) -> (rc, texto))] de esta corrida; la SE solo si toca (se decide con data/ ya actualizado)."""
    ps = [("sepa", lambda r: paso(r, "sepa.py"))]  # Nota Paraná pausada desde 2026-11-18 (datos señuelo)
    if energia_vencida(raiz):
        ps.append(("energia", lambda r: paso(r, "macro.py", "energia")))
    return ps


def correr(raiz, armar=pasos):
    """Devuelve (código de salida, texto de log)."""
    raiz = Path(raiz)
    if not hay_marcador(raiz):
        return 2, f"aborta: falta {raiz / '.sepa_pc'} (no es el clon dedicado); no se tocó nada"
    log = []
    # ponytail: techo: 3 intentos y cada reintento re-corre todos los pasos tras el reset (re-baja el zip de SEPA y, si tocaba, los 770 MB de
    # la SE); si la Action pushea 3 veces seguidas, se pierde el día.
    for intento in range(1, REINTENTOS + 1):
        rc, s = actualizar(raiz)
        log.append(f"[{intento}] fetch/reset rc={rc} {s}")
        if rc:
            return 1, "\n".join(log)
        rc_pasos, nombres = 0, []
        for nombre, fn in armar(raiz):
            try:
                rc, s = fn(raiz)
            except Exception as e:  # un paso roto no frena a los demás
                rc, s = 1, f"excepción: {e!r}"
            log.append(f"[{intento}] {nombre} rc={rc}\n{s}")
            nombres.append(nombre)
            rc_pasos = rc_pasos or rc
        git(raiz, "add", "data/")
        if git(raiz, "diff", "--cached", "--quiet")[0] == 0:
            log.append("sin cambios en data/")
            return rc_pasos, "\n".join(log)
        rc, s = git(raiz, "-c", "user.name=sepa-pc", "-c", "user.email=sepa-pc@users.noreply.github.com",
                    "commit", "-m", mensaje_commit(datetime.now().strftime("%Y-%m-%d"), nombres))
        if rc:
            log.append(f"commit rc={rc} {s}")
            return 1, "\n".join(log)
        rc, s = git(raiz, "push", "origin", "HEAD:main")
        log.append(f"[{intento}] push rc={rc} {s}")
        if rc == 0:
            return rc_pasos, "\n".join(log)
        if not push_rechazado(rc, s):
            return 1, "\n".join(log)
    return 1, "\n".join(log)


def demo():
    assert mensaje_commit("2026-11-18", ["sepa", "energia"]) == "datos 2026-11-18: pc (sepa, energia)"
    with tempfile.TemporaryDirectory() as d:
        assert [n for n, _ in pasos(d)] == ["sepa", "energia"]  # sin fuentes.csv la SE está vencida; Nota Paraná ya no va
    rc, s = paso(RAIZ, "-c", "print('¿á�')")  # el subproceso escribe utf-8, no cp1252
    assert rc == 0 and s == "¿á�", (rc, s)
    hoy = date(2026, 11, 18)
    cab = "fecha,fuente,http,n_items,n_con_precio,n_sin_stock,n_sin_match,error,n_descartados\n"
    with tempfile.TemporaryDirectory() as d:
        assert energia_vencida(d, hoy)  # sin fuentes.csv
        (Path(d) / "data").mkdir()
        fu = Path(d) / "data" / "fuentes.csv"
        fu.write_text(cab)
        assert energia_vencida(d, hoy)  # sin filas
        fu.write_text(cab + "2026-11-17,macro_energia,,0,0,0,0,timeout,0\n2026-11-10,sepa,200,1,1,0,0,,0\n")
        assert energia_vencida(d, hoy)  # solo error (y otra fuente)
        fu.write_text(cab + "2026-10-20,macro_energia,200,5,5,0,0,,0\n")
        assert energia_vencida(d, hoy)  # OK de hace 28 días: vencida
        fu.write_text(cab + "2026-10-21,macro_energia,200,5,5,0,0,,0\n")
        assert not energia_vencida(d, hoy)  # OK de hace 27 días
    # un paso que falla (rc o excepción) no corta a los demás y se pushea igual, contra un remoto local
    with tempfile.TemporaryDirectory() as d:
        o, c = Path(d) / "origin.git", Path(d) / "clon"
        g = lambda *a, cwd=d: subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True)
        g("init", "-q", "--bare", "-b", "main", str(o))
        g("clone", "-q", str(o), str(c))
        (c / "data").mkdir()
        (c / "data" / "x.txt").write_text("0")
        g("add", ".", cwd=c), g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i", cwd=c), g("push", "-q", "origin", "HEAD:main", cwd=c)
        corridos = []
        def roto(r):
            corridos.append("a")
            raise RuntimeError("x")
        def malo(r):
            corridos.append("b")
            (Path(r) / "data" / "x.txt").write_text("fila de error")
            return 1, "fallo"
        def bueno(r):
            corridos.append("c")
            return 0, "ok"
        (c / ".sepa_pc").write_text("")
        rc, s = correr(c, lambda r: [("a", roto), ("b", malo), ("c", bueno)])
        assert rc == 1 and corridos == ["a", "b", "c"], (rc, corridos, s)
        assert g("log", "-1", "--format=%s", "origin/main", cwd=c).stdout.strip().endswith("pc (a, b, c)"), s
        assert g("show", "main:data/x.txt", cwd=o).stdout == "fila de error"
    assert push_rechazado(1, "! [rejected] main -> main (fetch first)")
    assert push_rechazado(1, "Updates were rejected because the tip is behind (non-fast-forward)")
    assert not push_rechazado(1, "fatal: unable to access: Could not resolve host")
    assert not push_rechazado(0, "rejected")
    with tempfile.TemporaryDirectory() as d:
        assert not hay_marcador(d)
        rc, s = correr(d)  # sin marcador: aborta antes de cualquier git
        assert rc == 2 and "falta" in s, (rc, s)
        (Path(d) / ".sepa_pc").write_text("")
        assert hay_marcador(d)
    print("OK")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # redirigido (Tarea programada) cae en cp1252 y print rompe con '¿'
    if sys.argv[1:] == ["test"]:
        demo()
        print("¿á�")  # no debe romper con stdout redirigido
        sys.exit(0)
    rc, texto = correr(RAIZ)
    if hay_marcador(RAIZ):
        with open(RAIZ / "sepa_pc.log", "a", encoding="utf-8") as f:
            f.write(f"=== {datetime.now():%Y-%m-%d %H:%M:%S} rc={rc}\n{texto}\n")
    print(texto)
    sys.exit(rc)
