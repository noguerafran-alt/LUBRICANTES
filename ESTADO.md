# ESTADO

Actualizado 2026-11-03. Sin remoto todavía: todo es local en la rama `main`.

## Qué hay
- Recolección: `recolectar.py` (YPF GraphQL, VTEX Carrefour/Mas/Easy/Jumbo, ML categorías), `sepa.py` (Precios Claros), `ml.py` (token apagado).
- `normalizar.py` + `seed/` (productos, alias, equivalencias). `python recolectar.py --renormalizar` recalcula el matcheo de `data/obs/` sin tocar precios (usarlo cada vez que cambie el seed).
- `server.py` + `site/index.html`: visor (Comparador, Evolución, Índice, Fuentes) y API con clave.
- `.github/workflows/recolectar.yml`: corrida diaria (recolectar, luego sepa).

## Verificado
- `python normalizar.py test`, `recolectar.py test`, `server.py test` dan OK.
- Corrida real del 2026-11-03 de todas las fuentes. Match (con producto_id / filas): sepa 98/111, carrefour 19/70, easy 25/48, masonline 36/54; jumbo 0 filas (224 ítems sin stock).
- Antes de esta tanda: sepa 0/111, carrefour 13/70, easy 29/48 (4 eran Bardahl mal atribuidos), masonline 36/54.
- Avisos cuyo slug de URL contradice SAE/litros del título quedan sin match (Easy/Bardahl).

## Falta
- Deploy en Render (Web Service free, ver README). Nunca se desplegó.
- ML con token: app "Lubricantes AR precios" armada en DevCenter el 2026-11-03 (lectura de publicaciones, redirect provisorio `https://biblioteca-b8mb.onrender.com/ml-callback`); la crea el usuario (T&C + captcha). Después: `python ml.py autorizar` en la PC (pide credenciales sin mostrarlas, guarda `.ml_local`, prueba endpoints) y `python recolectar.py --solo ml`. Para la Action: secrets ML_CLIENT_ID/ML_CLIENT_SECRET/ML_REFRESH_TOKEN/GH_PAT. Con token no está probado.
- Action en GitHub: no hay remoto, el workflow nunca corrió; falta repo, secrets y primer run.
- Cola `sin_match` (~100 avisos): revisar y ampliar `seed/alias.csv`. "Quartz Ineo 5W-30" sin variante queda sin match a propósito.
- El snippet de pandas del README no se ejecutó contra el server (la API con X-API-Key y CSV sí se probó).

## Cómo retomar
`python <modulo> test` en cada módulo; `LUB_CLAVE=x python server.py` y abrir http://127.0.0.1:8000; `python recolectar.py --solo <fuente>` para una fuente.
