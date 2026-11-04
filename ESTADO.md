# ESTADO

Actualizado 2026-11-04 (carga de Grok). Remoto privado `noguerafran-alt/LUBRICANTES`; la Action corre a diario.

## Qué hay
- Recolección: `recolectar.py` (YPF GraphQL, VTEX Carrefour/Mas/Easy/Jumbo/Norauto, ML categorías), `tiendas.py` (Shopify D'Atri, Tiendanube LS Palermo y Casa González), `sepa.py` (Precios Claros), `ml.py` (ML con token activo: products/search + products/{id}/items).
- `normalizar.py` + `seed/` (productos, alias, equivalencias). `python recolectar.py --renormalizar` recalcula el matcheo de `data/obs/` sin tocar precios (usarlo cada vez que cambie el seed).
- `server.py` + `site/index.html`: visor (Comparador, Evolución, Índice, Fuentes) y API con clave.
- `.github/workflows/recolectar.yml`: corrida diaria (recolectar, luego sepa).

## Verificado
- `python normalizar.py test`, `recolectar.py test`, `server.py test` dan OK.
- Corrida real del 2026-11-03 de todas las fuentes. Match (con producto_id / filas): sepa 98/111, carrefour 19/70, easy 25/48, masonline 36/54; jumbo 0 filas (224 ítems sin stock).
- Antes de esta tanda: sepa 0/111, carrefour 13/70, easy 29/48 (4 eran Bardahl mal atribuidos), masonline 36/54.
- Avisos cuyo slug de URL contradice SAE/litros del título quedan sin match (Easy/Bardahl).

- ML con token (corrida real 2026-11-04, desde la PC con `.ml_local`): 24 búsquedas, 816 productos de aceite (22 búsquedas cortadas en el tope de 50), 2393 avisos con precio, 14 min 14 s (el job de Actions admite hasta ~15: si se acerca, bajar `TOPE_PRODUCTOS` en `ml.py`). Match: 1067/2393 con producto_id (52 por EAN, 1015 por texto); el resto es catálogo que no está en `seed/` (Petronas 546, Castrol 201, Valvoline 112, Liqui Moly 89, Motul 69...), no se tocó `alias.csv`. `stock` va vacío (la API no lo da). `/items/bulk`, `/items` y `/sites/MLA/search` no sirven con este token.
- Highlights (top 20 por categoría) no se guardan: devuelven ids de producto ML y `obs` no los conserva, no hay forma de unirlos.

## Tiendas con precio (relevamiento 2026-11-04, `docs/relevamiento/tiendas-con-precio.md`)
- Corrida real 2026-11-04 desde la PC (ítems / con precio / con producto_id / duración): `vtex_norauto` 100 / 100 / 49 (49 %) / 6 s; `shopify_datri` 298 / 295 / 23 (8 %, el resto es industrial y Castrol sin alias) / 7 s; `tn_spch` 63 / 61 / 22 (36 %) / 65 s; `tn_lspalermo` 115 de 229 URLs / 113 / 22 (19 %: 30 son Valvoline, Puma, Mannol, etc. sin seed) / 119 s. Las cuatro juntas: ~3,3 min; ML ya usa ~14 de los 30 min del job.
- Norauto: `ListPrice` = `Price` en los 100 (no inflado), se guarda. `AvailableQuantity=99999` → `stock` vacío.
- D'Atri es **mayorista**: `/api/indice` lo excluye (`?mayoristas=1` lo suma) y el visor lo rotula. IVA sin verificar. Los títulos casi no dicen "Castrol": la marca sale de EDGE/GTX/MAGNATEC/VECTON (`normalizar.MARCAS`); el resto queda sin marca ni match, a propósito. Cajas con variante en quarts (1QT) → `litros` vacío. `agents.md` de la tienda pide identificarse con Web Bot Auth al tráfico "de agentes" server-to-server; `robots.txt` permite `/products.json` y mandamos el User-Agent honesto de siempre. Revisar si D'Atri se queja.
- Tiendanube: `robots.txt` de LS Palermo y Casa González no bloquea `/productos/` ni los sitemaps (se chequea en código en cada corrida). Rotación: tope 150 páginas por tienda/día; LS Palermo (229 URLs de aceite) se lee en dos mitades alternadas por `sha1(url)`, cada URL cada 2 días (`ultimo` en la API ya muestra la fecha de cada precio). Si el sitemap crece, k crece solo. Se loguea "cortadas N" y el tiempo en el log de la Action. Si sobra tiempo, subir `TOPE_PAGINAS` (250 cubre todo y suma ~2 min).
- Seed: 5 productos nuevos (Magnatec Stop-Start 5W-40 A3/B4, 5W-30 C3, 5W-30 A5; Shell Helix Ultra 5W-30 y 0W-20) con EAN de Norauto o título explícito de D'Atri; `inferido`. Magnatec Stop-Start 5W-30 en Norauto no dice C3/A5 y queda sin match. Falta correr `python recolectar.py --renormalizar` para que el histórico use los alias nuevos.
- **Coto: diferido.** Sus términos de uso no se leyeron; no se implementó (receta en el relevamiento).
- Dudas de matcheo previas, no tocadas: "Edge Professional 0W-20" y "Edge Titan 5W-30" caen en `castrol-edge-c5-0w20` / `castrol-edge-5w30` por el alias genérico `edge`.

## Carga de Grok (2026-11-04)
- `POST /api/cargar` (server.py), `seed/grok_sitios.csv`, `data/grok/AAAA-MM.csv`, `/api/servicios`, `/api/grok?mes=`, pestaña **Cargar** y sección "Servicios (combos)" en el visor, `docs/grok-task.md`. Contrato en `CLAUDE.md`.
- Verificado: `python server.py test` da OK (validación, variantes del precio, idempotencia, servicio vs producto, verificado=0 fuera del índice, auth, commit con fake de la Contents API; todo sin red). Punta a punta local en 127.0.0.1:8791: POST de un CSV de ejemplo → respuesta, `data/grok/2026-11.csv`, `/api/servicios` y `/api/fuentes`; datos de prueba borrados. Con la página real de helixturno (SPA) el precio no está en el HTML: sale `verificado=0`, como se esperaba.
- Corrección de lub-test: en 375 px la pestaña Cargar tenía scroll horizontal por el `<code>` del encabezado; ahora `.nota` y `.nota code` parten líneas (`overflow-wrap:anywhere`) y textarea/input llevan `max-width:100%`. No revisado en navegador.
- No verificado: la pestaña Cargar y las etiquetas "Grok · host" se revisaron solo por sintaxis JS y por el HTML servido, no en un navegador; la Contents API real (GitHub) nunca se llamó; el prompt de la Task es una reconstrucción, no el texto exacto que ya tiene el usuario.
- Pendiente del usuario: cargar `LUB_CARGA_CLAVE` y `GH_CARGA_TOKEN` en Render (`GH_CARGA_TOKEN` = fine-grained PAT solo de LUBRICANTES, Contents: read and write). Sin token las cargas quedan en el disco efímero.
- 2026-11-04: la primera carga real de Grok rebotó con 400 en las 33 filas: mandó `fuente` `helix_combos` y después `grok_helixturno`; la única válida para www.helixturno.com.ar es `grok_helix`. Ahora el error de fuente dice cuál usar (`...: usar grok_helix`), assert en `server.py test`.
- Cada commit de carga redeploya Render. Las cargas de un día no cuentan si otra carga las pisa por completo (tope de 10 por día contra abuso, no contabilidad).

## ypf_gql: causa del "HTTP 200 sin data" (2026-11-04)
- La corrida 2026-11-03 de Actions dio "HTTP 200 sin data"; desde la PC `--solo ypf_gql` trae 69 productos. La causa no se pudo probar fuera de Actions. Cambio en `recolectar.py`: cuando ypf_gql falla, el error de `data/fuentes.csv` lleva un extracto saneado del cuerpo (mensaje de `errors` de GraphQL o primeros 120 caracteres), para que la próxima corrida diaria diga la causa. Assert en `demo()`; `python recolectar.py test` da OK.
- Efecto lateral: el pedido de ypf_gql pasa por `ml.pedir(..., texto=True)`, que manda `Accept: */*` en vez de `application/json`. Hoy sigue trayendo 69 productos; si la Action empezara a fallar distinto, mirar esto primero.
- No verificado: la causa real, ni la Action.

## Falta
- Deploy en Render: formulario armado en el workspace YPF (`lubricantes-ypf`, free, /salud); falta que el usuario cargue LUB_CLAVE y despliegue.
- ML con token: app "Lubricantes AR precios" armada en DevCenter el 2026-11-03 (lectura de publicaciones, redirect provisorio `https://biblioteca-b8mb.onrender.com/ml-callback`); la crea el usuario (T&C + captcha). Autorizada y probada en la PC. Para la Action faltan cargar los secrets ML_CLIENT_ID/ML_CLIENT_SECRET/ML_REFRESH_TOKEN/GH_PAT (la Action necesita ML_REFRESH_TOKEN además de los dos ya cargados).
- Action en GitHub: primera corrida manual OK el 2026-11-04 (recolectar + sepa). `ypf_gql` da HTTP 200 sin data desde Actions (desde la PC trae 69): sin investigar.
- Token ML rotativo: lo usa UN solo lado. Si se sube ML_REFRESH_TOKEN a la Action, la PC deja de correr `--solo ml` (o al revés), porque cada canje invalida el anterior.
- Cola `sin_match` (~100 avisos): revisar y ampliar `seed/alias.csv`. "Quartz Ineo 5W-30" sin variante queda sin match a propósito.
- El snippet de pandas del README no se ejecutó contra el server (la API con X-API-Key y CSV sí se probó).

## Cómo retomar
`python <modulo> test` en cada módulo; `LUB_CLAVE=x python server.py` y abrir http://127.0.0.1:8000; `python recolectar.py --solo <fuente>` para una fuente.
