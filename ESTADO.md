# ESTADO

Actualizado 2026-11-04 (carga de Grok). Remoto privado `noguerafran-alt/LUBRICANTES`; la Action corre a diario.

## Qué hay
- Recolección: `recolectar.py` (YPF GraphQL, VTEX Carrefour/Mas/Easy/Jumbo/Norauto, ML categorías), `tiendas.py` (Shopify D'Atri, Tiendanube LS Palermo y Casa González), `sepa.py` (Precios Claros), `ml.py` (ML con token activo: products/search + products/{id}/items).
- `normalizar.py` + `seed/` (productos, alias, equivalencias). `python recolectar.py --renormalizar` recalcula el matcheo de `data/obs/` y `data/grok/` sin tocar precios (usarlo cada vez que cambie el seed).
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
- **Coto: diferido.** Términos leídos el 2026-11-04: ver sección Coto.
- Duda de "Edge Professional 0W-20" / "Edge Titan 5W-30": resuelta en la tanda "Seed sin match" (abajo).

## Carga de Grok (2026-11-04)
- `POST /api/cargar` (server.py), `seed/grok_sitios.csv`, `data/grok/AAAA-MM.csv`, `/api/servicios`, `/api/grok?mes=`, pestaña **Cargar** y sección "Servicios (combos)" en el visor, `docs/grok-task.md`. Contrato en `CLAUDE.md`.
- Verificado: `python server.py test` da OK (validación, variantes del precio, idempotencia, servicio vs producto, verificado=0 fuera del índice, auth, commit con fake de la Contents API; todo sin red). Punta a punta local en 127.0.0.1:8791: POST de un CSV de ejemplo → respuesta, `data/grok/2026-11.csv`, `/api/servicios` y `/api/fuentes`; datos de prueba borrados. Con la página real de helixturno (SPA) el precio no está en el HTML: sale `verificado=0`, como se esperaba.
- Corrección de lub-test: en 375 px la pestaña Cargar tenía scroll horizontal por el `<code>` del encabezado; ahora `.nota` y `.nota code` parten líneas (`overflow-wrap:anywhere`) y textarea/input llevan `max-width:100%`. No revisado en navegador.
- No verificado: la pestaña Cargar y las etiquetas "Grok · host" se revisaron solo por sintaxis JS y por el HTML servido, no en un navegador; la Contents API real (GitHub) nunca se llamó; el prompt de la Task es una reconstrucción, no el texto exacto que ya tiene el usuario.
- Pendiente del usuario: cargar `LUB_CARGA_CLAVE` y `GH_CARGA_TOKEN` en Render (`GH_CARGA_TOKEN` = fine-grained PAT solo de LUBRICANTES, Contents: read and write). Sin token las cargas quedan en el disco efímero.
- 2026-11-04: la primera carga real de Grok rebotó con 400 en las 33 filas: mandó `fuente` `helix_combos` y después `grok_helixturno`; la única válida para www.helixturno.com.ar es `grok_helix`. Ahora el error de fuente dice cuál usar (`...: usar grok_helix`), assert en `server.py test`.
- Cada commit de carga redeploya Render. Las cargas de un día no cuentan si otra carga las pisa por completo (tope de 10 por día contra abuso, no contabilidad).

## Seed sin match (2026-11-04)
- Cambió el seed: +57 productos en `seed/productos.csv` (`verificado=inferido`, specs solo si las dice el título) y +59 alias en `seed/alias.csv` (+73 líneas tocadas en el diff, 7 reemplazadas; el archivo pasó de 287 a 346 líneas). Prioridad por cantidad de avisos de ML: Petronas, Valvoline, Motul, Liqui Moly, Shell, Castrol. `normalizar.py`: el alias genérico `edge` ya no atrapa Professional ni Titan, y un aviso de ML con varios EAN se matchea por EAN si uno solo identifica.
- Match antes -> después (con producto_id / filas, `data/obs/2026-11.csv` tras `recolectar.py --renormalizar`): ml 1067/2393 -> 2221/2393; sepa 196/222 -> 214/222; vtex_masonline 38/56 -> 38/56; vtex_carrefour 19/70 y vtex_easy 25/48 sin cambio. Total 1345/2789 -> 2517/2789. Precios intactos, solo cambia `producto_id`.
- Inspección independiente (lub-test) encontró una regresión: 2 avisos ML "Helix Ultra Pro Af ... 5w30 ultra" perdían `shell-helix-ultra-professional-af-5w30` porque el `.*` de los alias genéricos de Helix Ultra dejaba que el "ultra" final esquivara la exclusión de Pro/E. Corregido moviendo la exclusión a un lookahead al inicio de la regex (ver `seed/alias.csv`), assert en `normalizar.py test`. Diff fila a fila contra main después de renormalizar: 0 matches perdidos, 0 cambiados.
- Sin match a propósito: "Quartz Ineo 5W-30" sin variante (no se toca); "Edge Professional 0W-20" y "Edge Titan 5W-30" (no hay producto propio en el seed); títulos con más de un candidato; cola de ML con pocos avisos por producto (174 avisos restantes).
- Verificado: `normalizar.py test` con asserts de los casos nuevos (incluido Edge Professional/Titan) y los demás tests dan OK. No verificado: nada contra red ni ML con token; los alias son `inferida`, no salen de fichas.

## ypf_gql: causa del "HTTP 200 sin data" (2026-11-04)
- La corrida 2026-11-03 de Actions dio "HTTP 200 sin data"; desde la PC `--solo ypf_gql` trae 69 productos. La causa no se pudo probar fuera de Actions. Cambio en `recolectar.py`: cuando ypf_gql falla, el error de `data/fuentes.csv` lleva un extracto saneado del cuerpo (mensaje de `errors` de GraphQL o primeros 120 caracteres), para que la próxima corrida diaria diga la causa. Assert en `demo()`; `python recolectar.py test` da OK.
- Efecto lateral: el pedido de ypf_gql pasa por `ml.pedir(..., texto=True)`, que manda `Accept: */*` en vez de `application/json`. Hoy sigue trayendo 69 productos; si la Action empezara a fallar distinto, mirar esto primero.
- No verificado: la causa real, ni la Action.

## Primera carga real de Grok (2026-11-04)
- Con `fuente=grok_helix` entró: 200, 17 filas (todas `verificado=0`: helixturno es SPA), commit 7d9ec1a. Grok mandó 33: **16 se perdieron sin aviso** porque la clave de idempotencia era `fuente+fecha+url+titulo` y los combos de una misma URL que cambian solo por filtro comparten título (dentro de la carga ganaba la última; `/api/servicios` también los colapsaba).
- Acción correctiva: `clave_grok` = `fuente+fecha+url+titulo+detalle` en la fusión, en la carga y en `servicios()`; un duplicado exacto se informa en `duplicadas`. Asserts en `server.py test`.
- "HELIX ULTRA HX8 5W-40" entraba como `shell-helix-ultra-5w40` por el alias genérico de Helix Ultra. Un título que mezcla Ultra y HXn es ambiguo: los alias genéricos de Helix Ultra excluyen `hx\s*\d` y queda sin match (assert en `normalizar.py test`). `--renormalizar` ahora también recorre `data/grok/` (solo `producto_id`/`match`). Diff contra main: obs sin cambios; grok solo la fila HX8 pasa a sin match.
- Pendiente: Grok reenvía las 33 filas (idempotente: las 17 guardadas se pisan, las 16 faltantes entran).

## Primera corrida de ML en la Action (2026-11-04, run 41860377079) — ML INOP
- Recolectar OK: `ml` 2385 avisos con precio (194 sin match), y `ypf_gql` **trajo 69 desde Actions** (el "200 sin data" del 2026-11-03 no se repitió). SEPA OK.
- **Falla:** el paso "Rotar refresh token ML" dio `HTTP 403: Resource not accessible by personal access token` en `actions/secrets/public-key`: el `GH_PAT` cargado no tiene permiso de Secrets. El canje ya había rotado el refresh, así que el nuevo se perdió y el viejo (el del secret y el de `.ml_local` en la PC) ya no vale. **ML queda sin token en los dos lados** hasta reautorizar.
- Acción correctiva en `recolectar.yml`: paso "Chequear GH_PAT" que prueba `gh api .../actions/secrets/public-key` ANTES del canje; si falla, ML no recibe `ML_REFRESH_TOKEN` (queda "sin token") y el refresh no se quema.
- Para volver a servicio (usuario): (1) GH_PAT con permiso **Secrets: Read and write** sobre LUBRICANTES (fine-grained) y recargarlo; (2) `python ml.py autorizar` en la PC; (3) subir el refresh nuevo de `.ml_local` a `ML_REFRESH_TOKEN`; (4) desde ahí la PC no corre `--solo ml`.

## Visor y README verificados (2026-11-04, sin cambios de código)
- lub-test en navegador: a 375 px las pestañas Cargar, Fuentes e Índice entran en el viewport (las tablas scrollean dentro de su contenedor); la etiqueta "Grok · www.helixturno.com.ar" aparece en Fuentes y en el aviso de fuentes con problemas, con "sin cargas" explicado. Consola sin errores propios del visor. Comparador y Evolución a 375 px no se recorrieron.
- Snippet de pandas del README ejecutado contra server.py local (pandas + requests): `/api/obs?mes=2026-11` 2789x15, `/api/ultimo?formato=csv` 190x9. Correcto, no se tocó.
- Primera carga real de Grok: queda por reenviar con `fuente=grok_helix`.

## Coto: términos leídos (2026-11-04) — sigue diferido, decisión del usuario
- Los términos (https://www.coto.com.ar/ayuda?s=2) no nombran scraping ni robots, pero la cláusula 2.3 (ix) prohíbe el uso comercial del sitio sin autorización escrita de Coto, y un monitor de precios para YPF puede leerse como tal. La 11 prohíbe reproducir imágenes/textos (no menciona precios).
- No hay API pública: el front lee el catálogo de Constructor.io (ac.cnstrc.com) con la clave de cliente de Coto embebida en el bundle, con precio por sucursal. No es un endpoint ofrecido a terceros: no se usa.
- Conclusión: ambiguo con riesgo. No se implementa sin autorización escrita de Coto (o un dictamen de Legales de YPF).

## Falta
- Deploy en Render: formulario armado en el workspace YPF (`lubricantes-ypf`, free, /salud); falta que el usuario cargue LUB_CLAVE y despliegue.
- ML con token: app "Lubricantes AR precios" armada en DevCenter el 2026-11-03 (lectura de publicaciones, redirect provisorio `https://biblioteca-b8mb.onrender.com/ml-callback`); la crea el usuario (T&C + captcha). Autorizada y probada en la PC. Para la Action faltan cargar los secrets ML_CLIENT_ID/ML_CLIENT_SECRET/ML_REFRESH_TOKEN/GH_PAT (la Action necesita ML_REFRESH_TOKEN además de los dos ya cargados).
- Action en GitHub: primera corrida manual OK el 2026-11-04 (recolectar + sepa). `ypf_gql` da HTTP 200 sin data desde Actions (desde la PC trae 69): la próxima corrida deja el extracto del cuerpo en `data/fuentes.csv`.
- Token ML rotativo: lo usa UN solo lado. Si se sube ML_REFRESH_TOKEN a la Action, la PC deja de correr `--solo ml` (o al revés), porque cada canje invalida el anterior.
- Cola `sin_match`: ampliada (ver "Seed sin match"); quedan 174 avisos ML ambiguos o de bajo volumen. "Quartz Ineo 5W-30" sin variante queda sin match a propósito.

## Cómo retomar
`python <modulo> test` en cada módulo; `LUB_CLAVE=x python server.py` y abrir http://127.0.0.1:8000; `python recolectar.py --solo <fuente>` para una fuente.
