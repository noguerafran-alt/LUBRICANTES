# LUBRICANTES

Precios de lubricantes en Argentina (YPF y competencia) en el tiempo, con equivalencias YPF ↔ competidor. Una Action recolecta a diario y comitea CSV en `data/`; un server liviano (solo stdlib) sirve un visor y una API con clave. Uso interno de YPF.

## Levantar local
```
LUB_CLAVE=miclave python server.py
```
Escucha solo en 127.0.0.1:8000 (con `RENDER` definida, en 0.0.0.0). Visor en `/`; la clave se pide ahí.

## Consumir la API
```python
import pandas as pd, requests
H = {"X-API-Key": "miclave"}
base = "http://127.0.0.1:8000"
obs = pd.DataFrame(requests.get(f"{base}/api/obs?mes=2026-11", headers=H).json())
ultimo = pd.read_csv(f"{base}/api/ultimo?formato=csv", storage_options=H)
```
La clave va siempre en el header, nunca en la URL. Rutas en `CLAUDE.md`. `/api/indice` excluye las fuentes mayoristas (D'Atri); `?mayoristas=1` las incluye.

## Render (Web Service free)
- Start command: `python server.py` (Build: nada que instalar).
- Health check path: `/salud`.
- Env: `LUB_CLAVE` (obligatoria: sin ella el server no arranca) y `PYTHON_VERSION=3.12.10`.
- Cada push de `data/` redeploya.

## Activar Mercado Libre
0. Ya activo desde la PC (`python recolectar.py --solo ml`, ~14 min); la Action necesita ML_REFRESH_TOKEN además de ML_CLIENT_ID y ML_CLIENT_SECRET.
1. Crear una app en developers.mercadolibre.com.ar y obtener un refresh token.
2. Secrets del repo: `ML_CLIENT_ID`, `ML_CLIENT_SECRET`, `ML_REFRESH_TOKEN` y `GH_PAT` (PAT que puede escribir secrets: el refresh token rota en cada corrida y la Action guarda el nuevo).

## Fuentes
`python recolectar.py --solo <fuente>` corre una (`vtex_norauto`, `shopify_datri`, `tn_lspalermo`, `tn_spch`, …); `python tiendas.py test` prueba los lectores Shopify/Tiendanube sin red.

## Reglas de matcheo
Si cambia `seed/`, correr `python recolectar.py --renormalizar`.
