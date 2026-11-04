# ESTADO

Actualizado 2026-11-04 (carga de Grok). Remoto privado `noguerafran-alt/LUBRICANTES`; la Action corre a diario.

## Vitrina YPF vs competencia y recolección acotada (2026-11-04, rama feat/vitrina-ypf)
- **Solo lo relacionado con YPF**: `recolectar.a_obs` escribe una observación únicamente si su `producto_id` es YPF o un `comp_id` de `seed/equivalencias.csv`; el resto se cuenta en `n_descartados` (columna nueva al final de `data/fuentes.csv`, filas viejas vacías = 0). Ya no hay `sin_match` en `data/obs/`: `/api/sin_match` queda vacía por diseño (el visor lo tiene que explicar). `n_con_precio == 0` ya no significa "sin precios con stock": hay que mirar también `n_descartados` (el visor actual lo sigue leyendo así).
- **`python recolectar.py --podar`** (corrido): `data/obs/2026-11.csv` 6022 -> 2641 filas (184 producto_id relacionados). Es idempotente.
- Corrida real 2026-11-04 (fuente: sin stock / guardadas / descartadas): vtex_carrefour 115 / 10 / 60; masonline 5 / 36 / 20; easy 0 / 14 / 34; jumbo 224 / 0 / 0; norauto 0 / 47 / 53; shopify_datri (mayorista) 3 / 22 / 273; tn_lspalermo 2 / 26 / 87; tn_spch 4 / 27 / 32. Tiempo total sin ML ni SEPA: 3 min 45 s (Tiendanube 121 + 65 s).
- **Mercado Libre**: `BUSQUEDAS` pasó a `ml.busquedas()` = 4 líneas YPF + "marca línea" de cada competidor del seed (21 búsquedas), y `ml.avisos(filtro)` no pide las publicaciones de un producto que no matchea con uno relacionado (antes ~1 request/s por cada uno de los 816 productos de aceite). **No medido ni corrido contra ML real**: esta PC no tiene token (`sin token`; el refresh es solo de la Action). Verificado solo con un test con `pedir` falso. Mirar el tiempo y el log `ml: ... productos relacionados con YPF (N de aceite descartados)` en la primera corrida de la Action; la fila buena de ML del día en `fuentes.csv` no se pisó. El campo `pictures` de `/products/search` tampoco se vio con datos reales.
- **Fotos** (`data/imagenes.csv`: 31 oficiales YPF + 34 de tiendas = 65; 32 de 116 productos YPF y 43 de 82 equivalentes): la oficial es `props.imagen` del GraphQL (ahora también en `data/catalogo_ypf.json`), unida al seed por título y solo si hay un candidato (31 de 69 ítems del catálogo; los de nombre genérico quedan sin foto oficial). Prioridad: oficial > VTEX > Shopify > Tiendanube > ML, por orden de llegada; una foto de tienda no pisa a otra.
- **`/api/vitrina`** (contrato en `CLAUDE.md`): 116 productos YPF, 24 con precio hoy, 19 con `dif_pct`. Asserts en `server.py test` (promedio/min/max/mediana, más barato, mayoristas, Grok no verificado, no_equivalente fuera del promedio, null sin datos, orden, ventana de 3 días, CSV, HTTP).
- **Sanidad del $/L** (rechazo del inspector: Rimula R3 L a 80570 $/L, dif +295 %). Causas y arreglos:
  - `normalizar.LITROS`/`ML`: un número pegado a una letra ya no es volumen ("R3 L" daba 3 L sobre "20 Litros"); la `x` de "X4lt" sigue valiendo.
  - ML con `UNITS_PER_PACK` igual al volumen ("5 L x 5 unidades": Motul 8100, Castrol GTX): `unidades = 1`. "Caja x6 Bidones 4L" (Quartz 7000) → 6 unidades.
  - `--renormalizar` pisaba litros/unidades de D'Atri (caja/tambor salen de la variante, que no está en el título) y de Tiendanube: ahora deja los mayoristas como están y a `tn_*` les aplica `tiendas.envase(titulo)`, igual que al recolectar. Las 13 filas de D'Atri del 2026-11-04 se restauraron desde HEAD.
  - `/api/vitrina`: un aviso a más de 2,5× (o menos de 1/2,5) de la mediana de su producto no cuenta (`SANIDAD`), y un equivalente cuya mediana está a más de 3× de la del YPF queda `en_promedio: false` con `excluido: "fuera_de_rango"` (`RANGO_EQ`; campo nuevo `excluido`: `null|no_equivalente|fuera_de_rango`). Umbrales fijos a ojo.
  - Resultado: Rimula R3 L 12086 $/L (xv100 dif +15,8), Castrol GTX 19374, Motul 8100 24594 (auro-fr-540 -38,0); Valvoline Synpower 2T (60875, títulos "1 L") queda fuera de rango; rod-2t queda +111,6 contra Castrol Go 2T (1 aviso, 30000 $/L, dentro del rango).
  - Abierto: Tiendanube con "12x1L" en el título (HX8 Prof AV a 35184, Mobil Super Moto 24X1L a 2040) parece precio por botella, no por caja; hoy se toma como caja y la sanidad lo saca. No verificado en la página.
- Pendiente: `sepa.py` y Grok todavía escriben sin filtrar (el próximo `--podar` los limpia); el visor (`site/index.html`), su carrusel y el aviso de cola vacía los hace otro agente.

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

## Primera corrida de ML en la Action (2026-11-04, run 41860377079) — resuelto en run 41878301945
- Recolectar OK: `ml` 2385 avisos con precio (194 sin match), y `ypf_gql` **trajo 69 desde Actions** (el "200 sin data" del 2026-11-03 no se repitió). SEPA OK.
- **Falla:** el paso "Rotar refresh token ML" dio `HTTP 403: Resource not accessible by personal access token` en `actions/secrets/public-key`: el `GH_PAT` cargado no tiene permiso de Secrets. El canje ya había rotado el refresh, así que el nuevo se perdió y el viejo (el del secret y el de `.ml_local` en la PC) ya no vale. **ML queda sin token en los dos lados** hasta reautorizar.
- Acción correctiva en `recolectar.yml`: paso "Chequear GH_PAT" que prueba `gh api .../actions/secrets/public-key` ANTES del canje; si falla, ML no recibe `ML_REFRESH_TOKEN` (queda "sin token") y el refresh no se quema.
- Corrida de prueba del chequeo (run 41866351947): "Chequear GH_PAT" dio 403, ML quedó "sin token", "Rotar" se salteó; el chequeo funciona. Efecto colateral encontrado: esa re-corrida pisó en `fuentes.csv` la fila buena de ML del día (las 2385 obs sí se conservaron), y `sepa.py` agregaba filas sin reemplazar (había `2026-11-03,sepa` duplicada). Corregido: `recolectar.escribir_fuentes` (una fila por fecha+fuente; una fila con error no pisa una buena del mismo día), que usa también `sepa.py`; assert en `recolectar.py test`. Datos reparados a mano: fila ML 2026-11-04 restituida desde el log del run 41860377079 y sepa 2026-11-03 sin duplicar.
- **Vuelta a servicio (2026-11-04, run 41878301945):** GH_PAT nuevo con Secrets: Read and write y reautorización en la PC (`ml.py autorizar`, refresh subido a `ML_REFRESH_TOKEN`). Chequear GH_PAT, Recolectar y Rotar dieron success: `ml` 2378 avisos con precio (190 sin match) y `ML_REFRESH_TOKEN` actualizado a las 17:50:09 UTC. `fuentes.csv` sin filas duplicadas. Desde acá el token es SOLO de la Action: la PC no corre `--solo ml` (su `.ml_local` ya no vale).
- Para volver a servicio (usuario): (1) GH_PAT con permiso **Secrets: Read and write** sobre LUBRICANTES (fine-grained) y recargarlo; (2) `python ml.py autorizar` en la PC; (3) subir el refresh nuevo de `.ml_local` a `ML_REFRESH_TOKEN`; (4) desde ahí la PC no corre `--solo ml`.

## $/L de los combos de Grok (2026-11-04)
- Pedido del usuario: dividir por litros el precio de los combos que son solo aceite. Ningún combo de helixturno es aceite pelado: todos traen colocación/mano de obra. Regla: aceite + colocación → `precio_litro` (rotulado "con colocación" en el visor); con filtros u otro repuesto (lista negra `RX_EXTRA` en server.py) o sin litros → vacío. Sigue fuera del comparador y del índice: la mano de obra infla el litro frente al bidón.
- Con los datos reales: 8 combos HX5/HX7 con $/L (HX5 4 L $19.247,50; HX7 de $24.247,50 a $25.665); los 9 sintéticos (Ultra, HX8) traen filtros y quedan sin $/L. Asserts en `server.py test`.

## Comparador en el celular (2026-11-04)
- La página nunca desbordaba (scrollWidth = 375 en las 5 pestañas), pero el Comparador arma una tabla de ~650 px por producto: en el celular cada una había que deslizarla de costado. Ahora, a 640 px o menos, cada tabla se muestra como tarjeta (una línea por fuente con su nombre a la izquierda, `data-l`); en escritorio la tabla queda igual.
- Verificado en el navegador con datos reales: a 375 px, 116 tarjetas y ninguna desborda; a 1280 px, tabla con encabezado; consola sin errores.

## Relevamiento de fuentes candidatas (2026-11-04)
- 61 sitios revisados, 37 con precio visto. Lista completa en `docs/relevamiento/fuentes-candidatas.md`; resumen y reglas para seguir relevando en `CLAUDE.md` ("Fuentes: en uso y candidatas"). Ninguna implementada todavía. Falta leer los términos de uso de cada una antes de sumarla.

## Visor y README verificados (2026-11-04, sin cambios de código)
- lub-test en navegador: a 375 px las pestañas Cargar, Fuentes e Índice entran en el viewport (las tablas scrollean dentro de su contenedor); la etiqueta "Grok · www.helixturno.com.ar" aparece en Fuentes y en el aviso de fuentes con problemas, con "sin cargas" explicado. Consola sin errores propios del visor. Comparador y Evolución a 375 px no se recorrieron.
- Snippet de pandas del README ejecutado contra server.py local (pandas + requests): `/api/obs?mes=2026-11` 2789x15, `/api/ultimo?formato=csv` 190x9. Correcto, no se tocó.
- Primera carga real de Grok: queda por reenviar con `fuente=grok_helix`.

## Coto: términos leídos (2026-11-04) — sigue diferido, decisión del usuario
- Los términos (https://www.coto.com.ar/ayuda?s=2) no nombran scraping ni robots, pero la cláusula 2.3 (ix) prohíbe el uso comercial del sitio sin autorización escrita de Coto, y un monitor de precios para YPF puede leerse como tal. La 11 prohíbe reproducir imágenes/textos (no menciona precios).
- No hay API pública: el front lee el catálogo de Constructor.io (ac.cnstrc.com) con la clave de cliente de Coto embebida en el bundle, con precio por sucursal. No es un endpoint ofrecido a terceros: no se usa.
- Conclusión: ambiguo con riesgo. No se implementa sin autorización escrita de Coto (o un dictamen de Legales de YPF).

## Cierre de la Vitrina YPF (2026-11-04)
- `sepa.py` y `POST /api/cargar` ahora filtran con la misma `recolectar.relacionados()` (no se duplicó). SEPA: `agregar(fecha, grupos, rel)` descarta lo ajeno y lo cuenta en `n_descartados` de `fuentes.csv` (`n_sin_match` = 0). Grok: un `tipo=producto` cuyo `producto_id` no es YPF ni `comp_id` sale en `errores` con `"no relacionado con YPF"` (y no se baja su URL); si todas las filas son ajenas, 400. Los `tipo=servicio` se aceptan siempre (combos Shell/competencia sin `producto_id`): van a `/api/servicios`, nunca al $/L. Asserts en `sepa.py test` y `server.py test`.
- Visor: Fuentes y el banner muestran "n guardados · m descartados (no relacionados con YPF)" cuando hay descartados; "sin precios con stock" solo si `n_sin_stock == n_items`. La cola `sin_match` vacía se explica como diseño.
- Vitrina: por defecto solo YPF con precio hoy (24 de 116 con los datos de hoy); botón `Ver todos (n)` (`aria-pressed`) suma los demás con su vacío explicado; el buscador mira todos y, si elige uno sin precio, activa el botón. CSS mínimo del botón, con las variables existentes (no se invocó la skill frontend-design).
- Probado en Chrome headless (127.0.0.1:8791): 24 slides por defecto, 116 con el botón; buscar "Aceites de corte netos" lo activa y salta a ese producto; sin desborde a 375 px en claro y oscuro.

## Falta
- Deploy en Render: formulario armado en el workspace YPF (`lubricantes-ypf`, free, /salud); falta que el usuario cargue LUB_CLAVE y despliegue.
- ML con token: app "Lubricantes AR precios" armada en DevCenter el 2026-11-03 (lectura de publicaciones, redirect provisorio `https://biblioteca-b8mb.onrender.com/ml-callback`); la crea el usuario (T&C + captcha). Autorizada y probada en la PC. Para la Action faltan cargar los secrets ML_CLIENT_ID/ML_CLIENT_SECRET/ML_REFRESH_TOKEN/GH_PAT (la Action necesita ML_REFRESH_TOKEN además de los dos ya cargados).
- Action en GitHub: primera corrida manual OK el 2026-11-04 (recolectar + sepa). `ypf_gql` da HTTP 200 sin data desde Actions (desde la PC trae 69): la próxima corrida deja el extracto del cuerpo en `data/fuentes.csv`.
- Token ML rotativo: lo usa UN solo lado. Si se sube ML_REFRESH_TOKEN a la Action, la PC deja de correr `--solo ml` (o al revés), porque cada canje invalida el anterior.
- Cola `sin_match`: ampliada (ver "Seed sin match"); quedan 174 avisos ML ambiguos o de bajo volumen. "Quartz Ineo 5W-30" sin variante queda sin match a propósito.

## Cómo retomar
`python <modulo> test` en cada módulo; `LUB_CLAVE=x python server.py` y abrir http://127.0.0.1:8000; `python recolectar.py --solo <fuente>` para una fuente.

## Sitios Grok (2026-11-04)
- Lista blanca `seed/grok_sitios.csv`: helix + 15 sitios revisados (robots.txt y términos).
- No habilitados: enausa (términos), mejorescompras (republica ML), fiatturin/motoracing/performance-lube y donagro (robots bloquea bots de IA), lubritodo/autodo/maxkar (términos prohíben copia o extracción), sodimac (Cloudflare), ceridono (solo aceites de refrigeración).
- Visor 2026-11-04: el Comparador en escritorio tenía columnas de ~57 px y los textos se pisaban; ahora cada fuente tiene 118 px fijos (encabezados en dos líneas) y la tabla scrollea dentro de su recuadro. El banner junta en una línea los sitios Grok habilitados que todavía no tuvieron carga.

## Visor: mejora visual y responsive (2026-11-04, solo `site/index.html`)
- Fix tras rechazo: en <=640 px los `.filtros` (label, select, input) ocupan 100% y `min-width: 0`, así el select largo de Evolución ya no ensancha la página (antes `scrollWidth` 458 a 375 px). Medido por lub-test el 2026-11-04 en 375/768/1366/1920: OK.
- Encabezado en una fila (título + pestañas, que scrollean solas si no entran); banner de avisos en una línea con `<details>` (el texto de cada aviso sigue igual al abrirlo); título de Vitrina más chico.
- Carrusel: la tarjeta actual ocupa todo el ancho (sin vecinas cortadas); foto de 230 px de columna con imagen de 190 px (150 px en tablet); a 640 px o menos la foto es una franja de 124 px (tope 140 px; el slide no estira la fila, `align-content: start`) arriba del nombre, y el buscador mide 44 px. Nombre y precios más chicos para que precio YPF, precio competencia y diferencia % entren sin scroll a 1366x768.
- Celular: inputs a 16 px y 44 px de alto, pestañas de 44 px, `.vt-slide` con `min-width: 0` contra el desborde horizontal.
- Medidas del responsive verificadas en navegador por lub-test (2026-11-04, 375/768/1366/1920).
- Paleta clara estilo YPF (solo CSS y markup): tema claro siempre (`color-scheme: light`, sin `prefers-color-scheme`; un solo juego de tokens en `:root`); encabezado de barra azul YPF `#0047ba` a todo el ancho con título y pestañas en blanco (activa con subrayado blanco, foco blanco); fondo `#f3f6fa`, paneles blancos con borde suave y sombra leve; competencia en ámbar `#e08a00`; banner de avisos amarillo claro; bordes de controles `--borde-ctl` (3:1). Fondo de la foto blanco y alineada arriba (`align-self: start`). Los controles del carrusel pasaron arriba de la pista para verse sin scroll a 1366x768. Sin medir todavía en navegador: contraste y capturas quedan para lub-test.
- Vitrina a pantalla completa (2026-11-04, solo CSS de `site/index.html`): en escritorio (>=1025 px de ancho y >=641 px de alto) la Vitrina usa `100dvh` con flex en columna (encabezado, banner, cabecera, controles, tarjeta, franja de miniaturas); la tarjeta toma el alto que sobra, la foto principal llena su columna de 340 px (`object-fit: contain`) y lo que no entra (lista de equivalentes) scrollea dentro de `.vt-datos`, no la página. Fotos de equivalentes 60 px (antes 40) y miniaturas 72 px (antes 56). Con alto menor a 641 px o en tablet/celular vuelve el flujo normal con scroll. Medido por lub-test (2026-11-04): sin scroll de página a 1366x768, 1902x865, 1920x1080 y 1366x650 en 12 de 24 productos; foto principal 385 px de alto a 1366x768 y 482 px a 1902x865 (a 1920x1080 la limita el ancho de la columna). La rama `max-height: 640px` y `:has()` en navegadores viejos no se probaron.
