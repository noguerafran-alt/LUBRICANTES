"""Envoltorio: la tarea LUBRICANTES-SEPA de Windows sigue llamando acá; el código vive en recolector_casa.py."""
import runpy, os; runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "recolector_casa.py"), run_name="__main__")  # noqa: E401,E702
