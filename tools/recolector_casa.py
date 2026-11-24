"""Recolector de casa (celular con Termux o PC con Windows): las fuentes que bloquean IP de datacenter, desde una IP residencial.

Corre en un CLON DEDICADO (hace reset --hard) con el marcador `.recolector_casa` (o `.sepa_pc`, de la tarea de Windows) en la raíz.
Ciclo: fetch/reset -> pasos -> fila fuente=casa en data/fuentes.csv -> un commit -> push (3 intentos). Un paso que falla no frena a los demás.
Pasos: recolectar.py --sin ml, sepa.py, macro.py series, macro.py fx, correo.py tarifas (solo si existe .correo_local) y macro.py energia SOLO si la SE publicó algo nuevo.
NUNCA toca Mercado Libre: el token de ML vive solo en GitHub (no se lee .ml_local ni ML_*).

python tools/recolector_casa.py              # una corrida; log en recolector_casa.log; salida != 0 si falla algún paso
python tools/recolector_casa.py --sin-push   # prueba: hace todo menos publicar
python tools/recolector_casa.py --solo-pull  # liviano (cron horario): fetch + reset --hard origin/main, sin recolectar; log en pull.log
python tools/recolector_casa.py test         # asserts sin red
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import recolectar  # noqa: E402  (escribir_fuentes, FUENTES)

REINTENTOS = 3
MARCADORES = (".recolector_casa", ".sepa_pc")
ORIGEN = Path("data") / "macro" / "energia_origen.json"
ART = timezone(timedelta(hours=-3))  # no depende de la zona horaria del celular


def hoy_art():
    return datetime.now(ART).date().isoformat()


def hay_marcador(raiz):
    return any((Path(raiz) / m).is_file() for m in MARCADORES)


def energia_a_bajar(lm, previo):
    """lm = last_modified del recurso en CKAN (o None); previo = {last_modified, bajada} de la última bajada buena (o None)."""
    if not previo:
        return True
    if not lm:
        return False  # sin fecha publicada no se puede saber si hay algo nuevo
    return lm > (previo.get("last_modified") or "")


def leer_origen(raiz):
    try:
        return json.loads((Path(raiz) / ORIGEN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def consultar_lm():
    import macro
    req = urllib.request.Request(macro.CKAN, headers={"User-Agent": macro.UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        recursos = json.load(r)["result"]["resources"]
    return next(x for x in recursos if x["id"] == macro.RECURSO_ID).get("last_modified")


def fila_casa(fecha, resultados):
    """resultados: [(paso, ok)] → fila de fuentes.csv (n_items = pasos corridos, n_con_precio = pasos OK, error = pasos fallidos)."""
    malos = [n for n, ok in resultados if not ok]
    return dict(fecha=fecha, fuente="casa", http="", n_items=len(resultados), n_con_precio=len(resultados) - len(malos), n_sin_stock=0,
                n_sin_match=0, error=("fallaron: " + ", ".join(malos)) if malos else "", n_descartados=0)


def mensaje_commit(fecha, nombres):
    return f"datos {fecha}: casa ({', '.join(nombres)})"


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
    # reset --hard no mueve los submódulos (site/modelos = LUB-MODELOS3D): sin esto el celu serviría GLB viejos o ninguno.
    # Si falla (red, deploy key) no frena la recolección: sin GLB la página anda igual, sin 3D.
    rc, s = git(raiz, "submodule", "update", "--init", "--recursive")
    return 0, "" if not rc else f"aviso: submodule update rc={rc}: {s[-200:]}"


LOCK = ".casa.lock"
LOCK_VENCE = 4 * 3600  # una corrida entera no tarda tanto: un candado más viejo es de un proceso muerto


def tomar_lock(raiz):
    """Una corrida y un pull no pueden convivir en el clon (el pull hace reset --hard). True si lo tomó."""
    p = Path(raiz) / LOCK
    try:
        if p.exists() and datetime.now().timestamp() - p.stat().st_mtime > LOCK_VENCE:
            p.unlink()
        os.close(os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except OSError:
        return False


def soltar_lock(raiz):
    try:
        (Path(raiz) / LOCK).unlink()
    except OSError:
        pass


def solo_pull(raiz):
    """Modo liviano: trae lo que subió GitHub (ML) o la PC, sin recolectar. Si hay una corrida en curso, no hace nada."""
    raiz = Path(raiz)
    if not hay_marcador(raiz):
        return 2, f"aborta: falta {raiz / MARCADORES[0]} (no es el clon dedicado); no se tocó nada"
    if not tomar_lock(raiz):
        return 0, "hay una corrida en curso, no se hace pull"
    try:
        rc, s = actualizar(raiz)
        rc2, h = git(raiz, "log", "-1", "--format=%h %s")
        return rc, f"pull rc={rc} {s}\nHEAD {h}"
    finally:
        soltar_lock(raiz)


def entorno():
    """Sin credenciales de ML: el recolector de casa no las ve ni por error."""
    return {**{k: v for k, v in os.environ.items() if not k.startswith("ML_")}, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def paso(raiz, *cmd):
    p = subprocess.run([sys.executable, *cmd], cwd=raiz, capture_output=True, text=True, encoding="utf-8", errors="replace", env=entorno())
    return p.returncode, (p.stdout + p.stderr).strip()


def energia(raiz, lm):
    rc, s = paso(raiz, "macro.py", "energia")  # macro.py devuelve 0 aunque falle: el resultado está en su fila de fuentes.csv
    filas = [f for f in recolectar.leer(str(Path(raiz) / "data" / "fuentes.csv")) if f["fuente"] == "macro_energia" and f["fecha"] == hoy_art()]
    if rc or not filas or filas[-1]["error"]:
        return 1, s + "\nenergia: la bajada no quedó OK, no se registra el origen"
    (Path(raiz) / ORIGEN).write_text(json.dumps({"last_modified": lm, "bajada": hoy_art()}), encoding="utf-8")
    return 0, s


def pasos(raiz, consultar=consultar_lm):
    """[(nombre, función(raiz) -> (rc, texto))]; la SE solo si publicó algo nuevo (se decide con data/ ya actualizado)."""
    ps = [("recolectar", lambda r: paso(r, "recolectar.py", "--sin", "ml")), ("sepa", lambda r: paso(r, "sepa.py")),
          ("series", lambda r: paso(r, "macro.py", "series")), ("fx", lambda r: paso(r, "macro.py", "fx"))]
    if (Path(raiz) / ".correo_local").is_file():  # solo donde están las credenciales de MiCorreo (nunca en la Action)
        ps.append(("correo", lambda r: paso(r, "correo.py", "tarifas")))
    try:
        lm = consultar()
    except Exception as e:
        return ps + [("energia", lambda r, e=e: (1, f"no se pudo consultar CKAN: {e!r}"))]
    if energia_a_bajar(lm, leer_origen(raiz)):
        ps.append(("energia", lambda r: energia(r, lm)))
    return ps


def correr(raiz, armar=pasos, publicar=True):
    """Devuelve (código de salida, texto de log)."""
    raiz = Path(raiz)
    if not hay_marcador(raiz):
        return 2, f"aborta: falta {raiz / MARCADORES[0]} (no es el clon dedicado); no se tocó nada"
    log = []
    # ponytail: techo: 3 intentos y cada reintento re-corre todos los pasos tras el reset; si la Action pushea 3 veces seguidas, se pierde el día.
    for intento in range(1, REINTENTOS + 1):
        rc, s = actualizar(raiz)
        log.append(f"[{intento}] fetch/reset rc={rc} {s}")
        if rc:
            return 1, "\n".join(log)
        resultados = []
        for nombre, fn in armar(raiz):
            try:
                rc, s = fn(raiz)
            except Exception as e:  # un paso roto no frena a los demás
                rc, s = 1, f"excepción: {e!r}"
            log.append(f"[{intento}] {nombre} rc={rc}\n{s}")
            resultados.append((nombre, rc == 0))
        recolectar.escribir_fuentes(str(raiz / "data" / "fuentes.csv"), [fila_casa(hoy_art(), resultados)])
        rc_pasos = int(not all(ok for _, ok in resultados))
        git(raiz, "add", "data/")
        if git(raiz, "diff", "--cached", "--quiet")[0] == 0:
            log.append("sin cambios en data/")
            return rc_pasos, "\n".join(log)
        rc, s = git(raiz, "-c", "user.name=recolector-casa", "-c", "user.email=recolector-casa@users.noreply.github.com",
                    "commit", "-m", mensaje_commit(hoy_art(), [n for n, _ in resultados]))
        if rc:
            log.append(f"commit rc={rc} {s}")
            return 1, "\n".join(log)
        if not publicar:
            log.append("--sin-push: commit local, no se publicó")
            return rc_pasos, "\n".join(log)
        rc, s = git(raiz, "push", "origin", "HEAD:main")
        log.append(f"[{intento}] push rc={rc} {s}")
        if rc == 0:
            return rc_pasos, "\n".join(log)
        if not push_rechazado(rc, s):
            return 1, "\n".join(log)
    return 1, "\n".join(log)


def demo():
    assert mensaje_commit("2026-11-19", ["recolectar", "sepa"]) == "datos 2026-11-19: casa (recolectar, sepa)"
    # decisión de bajar la SE según last_modified
    assert energia_a_bajar("2026-11-01T10:00:00", None) and energia_a_bajar(None, None)  # nunca hubo bajada buena
    assert energia_a_bajar("2026-11-10T10:00:00", {"last_modified": "2026-11-01T10:00:00"})  # más nueva
    assert not energia_a_bajar("2026-11-01T10:00:00", {"last_modified": "2026-11-01T10:00:00"})  # igual
    assert not energia_a_bajar("2026-10-01T10:00:00", {"last_modified": "2026-11-01T10:00:00"})  # más vieja
    assert not energia_a_bajar(None, {"last_modified": "2026-11-01T10:00:00"})  # CKAN sin fecha: no se adivina
    # armado de la fila casa
    f = fila_casa("2026-11-19", [("recolectar", True), ("sepa", False), ("fx", False), ("series", True)])
    assert (f["fuente"], f["n_items"], f["n_con_precio"], f["error"]) == ("casa", 4, 2, "fallaron: sepa, fx")
    assert fila_casa("2026-11-19", [("a", True)])["error"] == "" and set(f) == set(recolectar.FUENTES)
    # pasos: sin red; recolectar siempre con --sin ml y entorno sin ML_*
    with tempfile.TemporaryDirectory() as d:
        assert [n for n, _ in pasos(d, lambda: "2026-11-10")] == ["recolectar", "sepa", "series", "fx", "energia"]
        (Path(d) / "data" / "macro").mkdir(parents=True)
        (Path(d) / ORIGEN).write_text(json.dumps({"last_modified": "2026-11-10", "bajada": "2026-11-11"}))
        assert [n for n, _ in pasos(d, lambda: "2026-11-10")] == ["recolectar", "sepa", "series", "fx"]  # sin novedad
        assert pasos(d, lambda: "2026-11-12")[-1][0] == "energia"
        (Path(d) / ".correo_local").write_text("{}")  # con credenciales de Correo: paso nuevo, después de fx
        assert [n for n, _ in pasos(d, lambda: "2026-11-10")] == ["recolectar", "sepa", "series", "fx", "correo"]
        (Path(d) / ".correo_local").unlink()
        def cae():
            raise OSError("sin red")
        assert pasos(d, cae)[-1][1](d)[0] == 1  # CKAN caído = paso energia fallido, no excepción
    os.environ["ML_REFRESH_TOKEN"] = "secreto"
    try:
        e = entorno()
        assert not any(k.startswith("ML_") for k in e) and e["PYTHONUTF8"] == "1"
        rc, s = paso(RAIZ, "-c", "import os;print([k for k in os.environ if k.startswith('ML_')], '¿á�')")
        assert rc == 0 and s == "[] ¿á�", (rc, s)  # el subproceso no ve ML_* y escribe utf-8
    finally:
        del os.environ["ML_REFRESH_TOKEN"]
    # un paso que falla (rc o excepción) no corta a los demás; la fila casa y el commit se pushean contra un remoto local
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
        (c / ".sepa_pc").write_text("")  # el marcador viejo también vale
        rc, s = correr(c, lambda r: [("a", roto), ("b", malo), ("c", bueno)])
        assert rc == 1 and corridos == ["a", "b", "c"], (rc, corridos, s)
        assert g("log", "-1", "--format=%s", "origin/main", cwd=c).stdout.strip().endswith("casa (a, b, c)"), s
        assert g("show", "main:data/x.txt", cwd=o).stdout == "fila de error"
        fu = g("show", "main:data/fuentes.csv", cwd=o).stdout
        assert '"fallaron: a, b"' in fu and fu.count(",casa,") == 1, fu
        # --sin-push: commitea y no publica
        n0 = g("rev-parse", "main", cwd=o).stdout
        (c / ".sepa_pc").unlink()
        (c / ".recolector_casa").write_text("")
        rc, s = correr(c, lambda r: [("c", bueno)], publicar=False)
        assert g("rev-parse", "main", cwd=o).stdout == n0 and "no se publicó" in s, s
    # --solo-pull: trae lo nuevo del remoto (y pisa lo local), respeta el marcador y el candado
    with tempfile.TemporaryDirectory() as d:
        o, c, otro = Path(d) / "origin.git", Path(d) / "clon", Path(d) / "otro"
        g = lambda *a, cwd=d: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True, text=True, check=True)
        g("init", "-q", "--bare", "-b", "main", str(o))
        g("clone", "-q", str(o), str(otro))
        (otro / "x.txt").write_text("1")
        g("add", ".", cwd=otro), g("commit", "-qm", "uno", cwd=otro), g("push", "-q", "origin", "HEAD:main", cwd=otro)
        g("clone", "-q", str(o), str(c))
        rc, s = solo_pull(c)
        assert rc == 2 and "falta" in s, s  # sin marcador no toca nada
        (c / ".recolector_casa").write_text("")
        (otro / "x.txt").write_text("2")
        g("commit", "-qam", "dos", cwd=otro), g("push", "-q", "origin", "HEAD:main", cwd=otro)
        (c / "x.txt").write_text("sucio")
        assert tomar_lock(c) and not tomar_lock(c)
        rc, s = solo_pull(c)
        assert rc == 0 and "en curso" in s and (c / "x.txt").read_text() == "sucio", s  # con candado tomado no pisa
        soltar_lock(c)
        rc, s = solo_pull(c)
        assert rc == 0 and (c / "x.txt").read_text() == "2" and "dos" in s and not (c / LOCK).exists(), s
        # submódulo: el pull lo trae al commit que fija el padre (reset --hard solo no lo hace)
        sub, subw = Path(d) / "sub.git", Path(d) / "subw"
        g("init", "-q", "--bare", "-b", "main", str(sub))
        g("clone", "-q", str(sub), str(subw))
        (subw / "m.glb").write_text("v1")
        g("add", ".", cwd=subw), g("commit", "-qm", "m1", cwd=subw), g("push", "-q", "origin", "HEAD:main", cwd=subw)
        g("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "modelos", cwd=otro)
        g("commit", "-qm", "con submodulo", cwd=otro), g("push", "-q", "origin", "HEAD:main", cwd=otro)
        os.environ.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="protocol.file.allow", GIT_CONFIG_VALUE_0="always")  # submódulo local en el test
        try:
            rc, s = solo_pull(c)
        finally:
            for k in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
                os.environ.pop(k)
        assert rc == 0 and (c / "modelos" / "m.glb").read_text() == "v1", s
    assert push_rechazado(1, "! [rejected] main -> main (fetch first)")
    assert push_rechazado(1, "Updates were rejected because the tip is behind (non-fast-forward)")
    assert not push_rechazado(1, "fatal: unable to access: Could not resolve host")
    assert not push_rechazado(0, "rejected")
    with tempfile.TemporaryDirectory() as d:
        assert not hay_marcador(d)
        rc, s = correr(d)  # sin marcador: aborta antes de cualquier git
        assert rc == 2 and "falta" in s, (rc, s)
        (Path(d) / ".recolector_casa").write_text("")
        assert hay_marcador(d)
    print("OK")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # redirigido (Tarea programada, cron) puede caer en cp1252/ascii
    if sys.argv[1:] == ["test"]:
        demo()
        print("¿á�")  # no debe romper con stdout redirigido
        sys.exit(0)
    pull = "--solo-pull" in sys.argv[1:]
    if pull:
        rc, texto = solo_pull(RAIZ)
    elif not tomar_lock(RAIZ):
        rc, texto = 0, "hay otra corrida o un pull en curso, no se corre"
    else:
        try:
            rc, texto = correr(RAIZ, publicar="--sin-push" not in sys.argv[1:])
        finally:
            soltar_lock(RAIZ)
    if hay_marcador(RAIZ):
        with open(RAIZ / ("pull.log" if pull else "recolector_casa.log"), "a", encoding="utf-8") as f:
            f.write(f"=== {datetime.now():%Y-%m-%d %H:%M:%S} rc={rc}\n{texto}\n")
    print(texto)
    sys.exit(rc)
