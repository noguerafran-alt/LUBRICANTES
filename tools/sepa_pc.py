"""SEPA desde la PC: baja Precios Claros y pushea data/ a main.

El portal de SEPA da 403 a las IP de datacenter (GitHub, Oracle) desde 2026-11-16; desde una IP residencial responde.
Corre en un CLON DEDICADO (reset --hard seguro) con el marcador `.sepa_pc` en la raíz.

python tools/sepa_pc.py        # una corrida; log en sepa_pc.log; salida != 0 si falla
python tools/sepa_pc.py test   # asserts sin red
"""
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REINTENTOS = 3


def hay_marcador(raiz):
    return (Path(raiz) / ".sepa_pc").is_file()


def mensaje_commit(fecha):
    return f"datos {fecha}: sepa (pc)"


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


def sepa(raiz):
    p = subprocess.run([sys.executable, "sepa.py"], cwd=raiz, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr).strip()


def correr(raiz):
    """Devuelve (código de salida, texto de log)."""
    raiz = Path(raiz)
    if not hay_marcador(raiz):
        return 2, f"aborta: falta {raiz / '.sepa_pc'} (no es el clon dedicado); no se tocó nada"
    log = []
    # ponytail: si sepa.py falla igual se pushea fuentes.csv (la fila de error); techo: 3 intentos de ~5 min c/u
    # (cada reintento re-baja el zip); si la Action pushea 3 veces seguidas, se pierde el día.
    rc_sepa = 0
    for intento in range(1, REINTENTOS + 1):
        rc, s = actualizar(raiz)
        log.append(f"[{intento}] fetch/reset rc={rc} {s}")
        if rc:
            return 1, "\n".join(log)
        rc_sepa, s = sepa(raiz)
        log.append(f"[{intento}] sepa.py rc={rc_sepa}\n{s}")
        git(raiz, "add", "data/")
        if git(raiz, "diff", "--cached", "--quiet")[0] == 0:
            log.append("sin cambios en data/")
            return rc_sepa, "\n".join(log)
        rc, s = git(raiz, "-c", "user.name=sepa-pc", "-c", "user.email=sepa-pc@users.noreply.github.com",
                    "commit", "-m", mensaje_commit(datetime.now().strftime("%Y-%m-%d")))
        if rc:
            log.append(f"commit rc={rc} {s}")
            return 1, "\n".join(log)
        rc, s = git(raiz, "push", "origin", "HEAD:main")
        log.append(f"[{intento}] push rc={rc} {s}")
        if rc == 0:
            return rc_sepa, "\n".join(log)
        if not push_rechazado(rc, s):
            return 1, "\n".join(log)
    return 1, "\n".join(log)


def demo():
    assert mensaje_commit("2026-11-18") == "datos 2026-11-18: sepa (pc)"
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
    if sys.argv[1:] == ["test"]:
        demo()
        sys.exit(0)
    rc, texto = correr(RAIZ)
    if hay_marcador(RAIZ):
        with open(RAIZ / "sepa_pc.log", "a", encoding="utf-8") as f:
            f.write(f"=== {datetime.now():%Y-%m-%d %H:%M:%S} rc={rc}\n{texto}\n")
    print(texto)
    sys.exit(rc)
