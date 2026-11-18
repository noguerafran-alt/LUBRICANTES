# LUBRICANTES — contrato del repo

Centraliza los lubricantes que se venden en Argentina (YPF y competencia), sus
precios en el tiempo y las equivalencias YPF ↔ competidor, y los expone en un
visor y una API con clave para que YPF los analice internamente.

**Arquitectura:** GitHub Actions recolecta una vez por día y comitea CSV en
`data/`. El push redeploya el Render Web Service free, que sirve visor y API
leyendo esos archivos. No hay base de datos: git es el almacenamiento y el
historial. Render free tiene disco efímero y su Postgres vence a los 30 días;
por eso el server no guarda nada en su disco: la única escritura (`POST /api/cargar`, Grok) se persiste comiteando al repo.

El relevamiento que fundamenta todo esto está en `docs/relevamiento/`
(`sintesis.md` es el diseño; el resto, las pruebas HTTP de cada fuente).

## Reglas que no se negocian

- **Python solo stdlib** (3.12). Ni requests ni pandas ni Flask: la Action corre
  `python` pelado y el server entra holgado en 512 MB.
- **No inventar datos.** Fuente caída = no se escribe fila ese día, no se arrastra
  el precio anterior. En el visor, vacío explicado ("Carrefour: sin datos desde
  2026-11-05, HTTP 403"), nunca 0 ni un guion sin explicación.
- **No se adivina el matcheo.** Un aviso entra con `producto_id` solo si hay
  exactamente un candidato. Si no, `producto_id` vacío y `match=none`.
- **Sin scraping de Mercado Libre** (Términos del Programa de Desarrolladores
  7.5/7.6). Solo API: categorías sin token, precios con OAuth de app propia.
- **Clave obligatoria en Render.** Si `RENDER` está definida y falta
  `LUB_CLAVE`, el server no arranca. Nunca una clave en la URL.
- **Única excepción a "solo stdlib": three.js vendorizado** (`site/vendor/three.module.min.js`, three@0.170.0, licencia MIT en
  `site/vendor/three.LICENSE`), solo para el modo presentación y cargado on-demand (import dinámico) para que el resto del visor no lo
  pague. Versión fijada, nada de CDN en runtime; `server.py` sirve cualquier `.js`/`.mjs` de `site/` como `text/javascript` con cache largo.
- **Geometría vendorizada**: `site/vendor/ar-provincias.js` (Natural Earth, dominio público; ver «Geometría del mapa»). Es datos, no código de terceros.
- Lógica nueva → su `assert` en el `demo()` de ese módulo
  (`python <modulo>.py test` tiene que dar `OK`).
- `ESTADO.md` se actualiza en el mismo commit que cualquier cambio.
- Todo en español. Comentarios solo para el porqué.

## Archivos

```
recolectar.py      # (--renormalizar: recalcula el matcheo de data/obs/ y data/grok/ sin tocar precios; --podar: deja en data/obs/ solo lo relacionado con YPF) una corrida: YPF GraphQL + VTEX + Shopify + Tiendanube + ML categorías (+ ML con token si hay secrets)
tiendas.py         # lectores Shopify (D'Atri) y Tiendanube (LS Palermo, Casa González), litros de caja/tambor, robots.txt
ml.py              # cliente ML: categorías sin token, OAuth refresh, products/items con token
sepa.py            # Precios Claros (SEPA): zip diario en streaming, filtra lubricantes
normalizar.py      # aviso → (marca, sae, litros, unidades, producto_id, match)
macro.py           # `series`: series de datos.gob.ar → data/macro/series.csv; `energia`: ventas de lubricantes de la SE (CSV de 770 MB en streaming) → data/macro/energia.csv
server.py          # http.server: visor estático site/ + /api/* calculado desde data/ y seed/
site/index.html    # visor: Mapa, Cobertura, Comparador, Evolución, Índice, Fuentes (JS vanilla, SVG propio)
seed/productos.csv     # catálogo normalizado YPF + competencia (a mano)
seed/alias.csv         # EAN / regex de título → producto_id
seed/equivalencias.csv # pares YPF ↔ competidor (a mano)
tools/geo_provincias.py # regenera site/vendor/ar-provincias.js desde Natural Earth (solo a mano; ver Geometría)
seed/grok_sitios.csv   # lista blanca de sitios que puede cargar Grok: fuente,host,descripcion
data/obs/AAAA-MM.csv   # observaciones de precio, append-only
data/fuentes.csv       # una fila por fuente y corrida
data/grok/AAAA-MM.csv  # relevamientos de Grok cargados por POST /api/cargar (los comitea el server)
data/ml_oferta.csv     # total de publicaciones por categoría ML por día
data/catalogo_ypf.json # foto del catálogo oficial YPF (el diff de git avisa altas/bajas); cada ítem trae `imagen` (URL https absoluta o "")
data/imagenes.csv      # una foto por producto_id (ver esquema)
seed/macro_series.csv  # ids de datos.gob.ar que baja `macro.py series`: id,nombre,grupo,frec,unidad,fuente (grupo: liviano|pesado|agro|industria|precios|demanda)
data/macro/series.csv  # series largas de datos.gob.ar (ver Mercado)
data/macro/energia.csv # ventas de lubricantes y gasoil de la Secretaría de Energía por mes (ver Mercado)
.github/workflows/recolectar.yml
```

## Esquemas (CSV UTF-8, coma, con encabezado)

**seed/productos.csv** — PK `producto_id` slug `marca-linea-nombre-sae`
(ej. `ypf-elaion-ts1040-10w40`, `shell-helix-hx7-10w40`).
`producto_id,marca,linea,nombre,segmento,sae,base,api,acea,ilsac,jaso,oem,fuente_specs,verificado`
- `marca`: canónica — `YPF, Shell, Castrol, Mobil, TotalEnergies, Elf, Gulf,
  Petronas, Motul, Bardahl, Puma, Valvoline, Pennzoil, Liqui Moly, Goodyear`.
- `segmento`: `pcmo|hddo|moto4t|moto2t|transmision|grasa|industrial|marino|gas|otro`.
- `sae`: `5W-30` (con guion), monogrado `SAE 40`, engranaje `75W-90`; vacío si no aplica.
- `base`: `mineral|semisintetico|sintetico` o vacío.
- `oem`: separadas por `;`. `verificado`: `confirmado|inferido`.
- Sin litros: la presentación es atributo de la observación.

**seed/alias.csv** — `producto_id,tipo,valor`
- `tipo=ean`: `valor` es el EAN exacto.
- `tipo=texto`: `valor` es una regex (Python `re`) sobre el título normalizado
  (minúsculas, sin acentos). Solo cuenta si la marca detectada del aviso coincide
  con la del producto (Elf y TotalEnergies cuentan como la misma: Elf es marca de
  TotalEnergies y Carrefour publica Elf con marca VTEX `TotalEnergies`; en
  `productos.csv` las marcas siguen separadas) y, si el aviso tiene SAE, coincide
  con la del producto. Si el slug de la URL trae otro SAE u otros litros que el
  título, el aviso queda `match=none` (cola `sin_match`).

**seed/equivalencias.csv** — `eq_id,ypf_id,comp_id,tipo,criterio,evidencia,fuente`
- `tipo`: `match_total|match_total_probable|match_parcial|sustituto_comercial|no_equivalente`.
- `evidencia`: `confirmada|inferida`. Sin puntajes de confianza inventados.

**data/obs/AAAA-MM.csv** —
`fecha,fuente,url,ean,titulo,marca,precio,precio_lista,stock,vendedor,sucursal,litros,unidades,producto_id,match,provincia`
- `provincia` (al final; única definición `recolectar.OBS`, que importan `sepa.py` y `server.py`): código ISO 3166-2:AR de la provincia donde se vende
  (`AR-X` Córdoba, `AR-C` CABA, …; las 24 en `normalizar.PROVINCIAS`), `online` (e-commerce de alcance nacional: VTEX, Shopify, Tiendanube y ML; **no es una
  provincia**) o vacío = sin dato. **Nunca se deduce de la casa central** del vendedor. SEPA la saca de `sucursales.csv` (`sucursales_provincia`, ya viene ISO;
  se cruza por `id_comercio,id_bandera,id_sucursal`); lo que no mapea queda vacío. Las filas anteriores a esta columna quedan con `provincia` vacía (no se reescriben).
  ML: no se lee `seller_address` (el vendedor no es el lugar de venta; diferido, ver ESTADO.md).
- **Región** (`normalizar.REGIONES`, criterio INDEC con La Rioja en NOA): NOA = AR-A,F,G,K,T,Y · NEA = AR-H,N,P,W · Cuyo = AR-D,J,M · Pampeana = AR-B,C,E,L,S,X · Patagonia = AR-Q,R,U,V,Z. CABA no se separa como AMBA
  (el conurbano está en AR-B y SEPA no lo parte): cae en Pampeana. Una región es la agregación de provincias **dentro de una misma fuente**.
- **Canal** (derivado, sin columna; `server.canal`): `mayorista` si la fuente está en `tiendas.MAYORISTAS`, `grok` si empieza con `grok_`, `publico` el resto.
- SEPA: una fila por comercio × bandera × **provincia** × EAN (mediana de `precio_lista` entre las sucursales de esa provincia; `sucursal` = `n=..;min=..;max=..` de esa provincia).
  Corrida real 2026-11-17: 878 filas/día (antes ~63 nacionales) en las 24 provincias; 32 filas sin provincia (44 filas de sucursal).
- `fecha` ISO `AAAA-MM-DD`. `precio` en ARS. `stock` entero o vacío.
- `match`: `ean|texto|none`.
- Si `stock == 0` o `precio <= 0`, no se escribe fila (se cuenta en `fuentes.csv`).
- Cencosud (Jumbo/Disco/Vea): `ListPrice` viene inflado, va vacío en `precio_lista`.
- **Fuentes mayoristas** (hoy `shopify_datri`, lista `MAYORISTAS` en `tiendas.py`): el precio es por caja o tambor
  y no se verificó si incluye IVA. `litros` es por unidad y `unidades` las de la caja (CAJA 12X1L → 1 y 12;
  TAMBOR 205L → 205 y 1; si el título habla en litros y la variante en quarts, `litros` vacío), así que
  `precio_litro` sigue siendo `precio / (litros × unidades)`. `/api/indice` las **excluye** por defecto y las suma con
  `?mayoristas=1`; el visor las rotula "(mayorista)" en Comparador, Evolución y Fuentes.
- Una corrida no duplica: si ya hay filas de esa `fuente` y `fecha`, se reemplazan.
- **Solo se recolecta lo relacionado con YPF.** Una observación se escribe únicamente si su `producto_id` es un producto de
  marca YPF de `seed/productos.csv` o un `comp_id` de `seed/equivalencias.csv` (cualquier `tipo`, incluido `no_equivalente`).
  Lo demás (otros productos, avisos sin match) **no se escribe, ni siquiera como `sin_match`**: se cuenta en `n_descartados` de
  `data/fuentes.csv`. Consecuencia: `match=none` y `producto_id` vacío ya no aparecen en `data/obs/` y la cola `/api/sin_match`
  queda vacía **por diseño** (el visor lo tiene que decir, no mostrar una cola "limpia" sin explicar). Para sumar un competidor
  hay que darlo de alta en el seed (producto + equivalencia) y recién ahí se recolecta. `python recolectar.py --podar` reescribe
  el histórico de `data/obs/` con esta misma regla (una vez; es idempotente). `sepa.py` y `POST /api/cargar` (Grok) aplican el mismo filtro (`recolectar.relacionados`): SEPA cuenta lo ajeno en `n_descartados`; Grok rechaza el `tipo=producto` ajeno con el motivo `no relacionado con YPF` en `errores`, y acepta siempre `tipo=servicio` (va a `/api/servicios`, no al $/L).

**data/grok/AAAA-MM.csv** —
`fecha,fuente,url,titulo,marca,precio,precio_lista,litros,unidades,tipo,detalle,verificado,producto_id,match,cargado,provincia`
- `provincia` (al final, después de `cargado`): ISO, `online` o vacío. `POST /api/cargar` acepta el encabezado de 11 columnas (la Task diaria) **y** el de 12 con `provincia` al final; el valor puede ser ISO, nombre
  de provincia (se pasa a ISO), `online` o vacío; cualquier otra cosa rechaza esa fila con motivo en `errores`. `provincia` entra a la clave de idempotencia (misma URL y título en dos zonas = dos filas). Los archivos viejos sin la columna se leen con provincia vacía.
- Las 11 primeras son lo que devuelve la Task de Grok (`docs/grok-task.md`); `fuente = grok_<sitio>`, `tipo = producto|servicio`,
  `detalle` separado por `;`. `verificado` (`1|0`): el server bajó la URL y el precio aparece en el texto (84999, 84.999, 84999,00,
  84.999,00, $ 84.999); `0` si no aparece o la página no se pudo leer / es SPA. `cargado`: timestamp UTC de la carga.
- `producto_id`/`match` salen de `normalizar.normalizar(titulo, marca, '', url)`; `litros`/`unidades` del CSV, si vienen vacíos los completa el normalizador.
- Una carga reemplaza las filas de igual `fuente+fecha+url+titulo+detalle` (`clave_grok`, idempotente): combos de una misma URL que cambian solo por filtro o vehículo son filas distintas. Un duplicado exacto dentro de la carga se guarda una vez (la última) y se informa en `duplicadas` (`fila`, `reemplazada_por`, `titulo`); nunca se descarta en silencio. `/api/servicios` usa la misma clave. Máx. 500 filas por carga y 10 cargas por día.
- Entra a `obs` (y por lo tanto a comparador, `ultimo`, `serie`, `sin_match`) solo `tipo=producto`; `verificado=0` se muestra
  (`ultimo` lleva `url` y `verificado`) pero **no entra al índice**; `tipo=servicio` nunca entra al $/L (va a `/api/servicios`).
- Un sitio nuevo = una fila en `seed/grok_sitios.csv` (`fuente,host,descripcion`); la fuente de cada fila tiene que corresponder al host de su URL (https).

**data/fuentes.csv** —
`fecha,fuente,http,n_items,n_con_precio,n_sin_stock,n_sin_match,error,n_descartados`
- `n_descartados` (al final, vacío en filas viejas = 0): avisos con stock y precio que no son de un producto relacionado con YPF y
  por eso no se escribieron. Desde que se filtra, `n_items = n_sin_stock + n_descartados + n_con_precio` y `n_sin_match` es 0;
  `n_con_precio` cuenta solo lo guardado. Ya **no** se puede deducir "sin precios con stock" de `n_con_precio == 0`: eso solo vale
  si también `n_descartados` está vacío o es 0. En `ml` los productos ajenos se descartan antes de pedir sus publicaciones y
  no figuran en ninguno de los contadores (el log de la corrida dice cuántos).
- `n_items == 0` con HTTP 200 es error: `"categoria vacia, revisar fq"`.
- `n_items > 0` y `n_con_precio == 0` sin error (Jumbo, todo sin stock): no es caída;
  el visor dice "sin precios con stock" solo si `n_sin_stock == n_items`; si hay `n_descartados` muestra "n guardados · m descartados" (no aplica a `ypf_gql` ni `ml_cat`, que no traen precio).

**data/ml_oferta.csv** — `fecha,categoria_id,categoria,total_items`

**data/imagenes.csv** — `producto_id,url,fuente,fecha`
- Una fila por `producto_id` (YPF o equivalente). Solo URLs `https`. Se escribe si el producto no tiene foto, o si llega la imagen
  oficial de YPF (`fuente=ypf_oficial`, `props.imagen` del GraphQL de lubricantes.ypf.com, resuelta contra
  `https://lubricantes.ypf.com/`) y es otra URL; una foto de tienda nunca pisa a otra. `fuente` = la de la observación que la
  trajo (`vtex_*`: `items[].images[0].imageUrl`; `ml`: `pictures[0].url` del producto; `shopify_*`: `images[0].src`;
  `tn_*`: `og:image` del producto principal). Orden de llegada = orden de corrida (YPF, VTEX, Shopify, Tiendanube, ML).
  El ítem del catálogo oficial se une al producto del seed por título (sin espacios ni signos) contra `nombre`, `nombre+sae` o
  `linea+nombre`; si hay 0 o más de un candidato, no se une (no se adivina).

## Fuentes v1 (probadas el 2026-11-03)

| fuente | endpoint |
|---|---|
| `ypf_gql` | `POST https://magui.ypf.com/shp/yforms-lists/Metadata/` GraphQL `getMetadataGlobal(type:PRODUCTION){title structure data props}` |
| `vtex_carrefour` | `https://www.carrefour.com.ar/api/catalog_system/pub/products/search?fq=C:/635/640/642/&_from=&_to=` |
| `vtex_masonline` | `https://www.masonline.com.ar/...` `fq=C:/1000039/2000174/3000496/` |
| `vtex_easy` | `https://www.easy.com.ar/...` `fq=C:/9/68/321/` |
| `vtex_jumbo` | `https://www.jumbo.com.ar/...` `fq=C:/16/126/412/` — precio solo con `AvailableQuantity>0` |
| `sepa` | CKAN `package_show?id=sepa-precios` → zip del día |
| `vtex_norauto` | `https://www.norauto.com.ar/...` `fq=C:/3/20/` (aceites sueltos; NO `C:/4/24/`: combos con colocación). `AvailableQuantity=99999` es relleno: `stock` queda vacío. `ListPrice` = `Price` (verificado 2026-11-04), se guarda |
| `shopify_datri` | `https://tiendadatri.com.ar/products.json?limit=250&page=N` hasta página vacía; `product_type` LUBRICANTES, SINTÉTICO, SEMISINTÉTICO, MINERAL, MULTIGRADO, MONOGRADO. **Mayorista.** Marca solo si el título la dice (`vendor` es D'ATRI) |
| `tn_lspalermo`, `tn_spch` | Tiendanube: `sitemap.xml` → URLs `/productos/` cuyo slug pasa `aceite\|lubric\|elaion\|helix\|castrol\|quartz\|mobil` y no es filtro/kit/aerosol/etc. → en cada HTML, `LS.variants[].price_number` del producto principal (el JSON-LD `Product` es de los relacionados: no se usa). Páginas con más de una variante no se leen. Tope 150 páginas por tienda y día (`TOPE_PAGINAS`); si el sitemap tiene más, se rota por `sha1(url)` en k = ceil(n/150) grupos, hoy toca el `ordinal del día % k`: cada URL se lee cada k días |
| `ml_cat` | `https://api.mercadolibre.com/categories/{id}` sin token (MLA375007 y hermanas) |
| `ml` | con token: `/products/search` + `/products/{id}/items` (un aviso por publicación nueva; atributos del producto: BRAND, GTIN, VISCOSITY_GRADE, NET_VOLUME, UNITS_PER_PACK). `/items/bulk` da `[{}]`, `/items?ids=` 403, `/sites/MLA/search` 403: no se usan. `/highlights` (top 20 por categoría, ids de producto) queda fuera: no hay forma de unirlos a `obs` |

VTEX pagina de a 50 (`_from`/`_to`, máximo 2500). 1 request/s por host,
`User-Agent` honesto, timeout 30 s, un reintento. Las tiendas Shopify/Tiendanube consultan antes el `robots.txt` del host
(`tiendas.permitido`, `urllib.robotparser`): si no se puede leer, la fuente no corre. Coto está **diferido**: sus términos
(cláusula 2.3 ix) prohíben el uso comercial sin autorización escrita; no se implementa sin esa autorización.

## Fuentes: en uso y candidatas

**En uso** (todas las de la tabla de arriba, más Grok): Mercado Libre (API con token) · SEPA/Precios Claros · Carrefour,
Más Online, Easy, Jumbo, Norauto (VTEX) · D'Atri (Shopify, mayorista) · LS Palermo y Casa González (Tiendanube) ·
catálogo YPF (GraphQL, sin precios) · categorías ML · helixturno.com.ar vía Grok (`grok_helix`, combos).

**Candidatas, NO en uso:** relevamiento del 2026-11-04 en `docs/relevamiento/fuentes-candidatas.md` (61 sitios, 37 con
precio visto; estado, ejemplo de precio, forma de lectura, robots/términos y notas de cada uno). Resumen:
- `automatica` (API JSON, se suman al recolector como las actuales): API JSON de helixturno (reemplaza a Grok para Shell),
  neumaticoslarutaok, repuestosrano, allenderepuestos, lubritodo, olafil, autodo, daytona, tiendaneumaticos, fiatturin, ceridono.
- `automatica_o_grok`: performance-lube (YPF, Puma, Mobil, Shell, Castrol y Total juntos), lubrimaster, lubricentrodg,
  exporepuestos, laestacionsrl, enausa (mayorista YPF con IVA), mejorescompras (historial de ML).
- `grok`: motoracing, norfren, lubricentromaximo (robots pide ir lento), netrenault, gramagliarepuestos, maxkar,
  comprarmarket, hermanrepuestos, lubricentrotorooils, donagro, sodimac.
- No usar: cambiodeaceite.com.ar (robots bloquea todo bot salvo Google), precialo (bloquea bots de IA), Coto.
- Hallazgo: **YPF no publica precio en ningún canal propio** (YPF Boxes solo en la app con login); Axion/Castrol, Bardahl,
  Motul y Liqui Moly tampoco. El precio de las marcas siempre sale de terceros.

**Para seguir relevando** (cualquier sesión o cuenta):
1. Un sitio cuenta solo si se abrió la página y se vio un precio en pesos de un lubricante concreto, con fecha. Si no, `precio visto = no`.
2. Mirar `robots.txt` y los términos de uso antes de proponerlo. Si prohíbe bots o el uso comercial, va a "no usar" con la cláusula citada.
3. Preferir API (Tiendanube, WooCommerce `/wp-json/wc/store/v1/products`, VTEX `/api/catalog_system/pub/products/search`, Shopify `/products.json`) antes que Grok.
4. Anotar cada hallazgo en `docs/relevamiento/fuentes-candidatas.md` (misma tabla); no se toca el código ni `data/` para relevar.
5. Pasar una candidata a uso = implementarla con `/lub-cambio` (lub-edit + lub-test) y moverla a "En uso" acá.

## Mercado Libre con token

Corre `python recolectar.py --solo ml` con las credenciales de `.ml_local` (PC) o con los secrets `ML_CLIENT_ID`, `ML_CLIENT_SECRET`,
`ML_REFRESH_TOKEN` (Action). El refresh token rota en cada canje (solo vale el último):
la Action guarda el nuevo con `gh secret set ML_REFRESH_TOKEN` usando el secret
`GH_PAT` (el `GITHUB_TOKEN` no puede escribir secrets). Sin secrets, `ml` queda
en `fuentes.csv` con `error="sin token"`. Búsquedas por marca/línea (`BUSQUEDAS`, tope 50 productos c/u) filtradas a dominios de aceites; `stock` queda vacío (la API no lo da); `vendedor` = `seller_id` (+ ` tienda:<official_store_id>`). Duración: ver ESTADO.md. Desde 2026-11-04 las búsquedas (`ml.busquedas()`) son las 4 líneas YPF (`BUSQUEDAS_YPF`) más "marca línea" de cada `comp_id` de `seed/equivalencias.csv`, y un producto cuyo título/GTIN no matchea con un producto relacionado no se baja (`avisos(filtro)`): no se piden sus publicaciones.

## API (server.py)

Autenticación: header `X-API-Key: <LUB_CLAVE>` o Basic Auth (usuario cualquiera,
contraseña `LUB_CLAVE`). Respuestas JSON; `?formato=csv` devuelve CSV.

| ruta | contenido |
|---|---|
| `/api/productos` | `seed/productos.csv` |
| `/api/equivalencias` | equivalencias con nombre y marca de ambos lados |
| `/api/ultimo` | último precio por (producto_id, fuente, litros) con `precio_litro` y fecha |
| `/api/obs?mes=AAAA-MM` | observaciones crudas del mes (insumo del análisis interno) |
| `/api/serie?p=<producto_id>` | serie diaria: mediana de $/L por fuente |
| `/api/indice` | índice $/L por fecha, segmento, SAE y marca (YPF = 100). Excluye fuentes mayoristas; `?mayoristas=1` las incluye |
| `/api/fuentes` | último estado de cada fuente + días sin datos |
| `/api/sin_match` | avisos sin `producto_id` (cola de revisión) |
| `/api/oferta_ml` | `data/ml_oferta.csv` |
| `/api/vitrina` | YPF vs competencia por producto (ver abajo). Excluye mayoristas; `?mayoristas=1` los incluye. `?formato=csv` aplana |
| `/api/servicios` | último precio de cada servicio/combo cargado por Grok (`tipo=servicio`), con `verificado`, `solo_aceite` y `precio_litro`: si `detalle` no nombra filtros ni otro repuesto (`RX_EXTRA`) y hay litros, `precio_litro = precio / (litros × unidades)` con la colocación adentro; si no, vacío. Nunca entra al comparador ni al índice |
| `/api/grok?mes=AAAA-MM` | filas Grok crudas del mes (con `verificado`, `tipo`, `cargado`); van aparte de `/api/obs` |
| `/api/grok_sitios` | `seed/grok_sitios.csv` |
| `POST /api/cargar` | carga de un CSV de Grok (ver abajo) |
| `/api/mercado` | share oficial de la SE + actividad + compuestos (ver "Mercado"). `?producto=automotrices\|industriales\|marinos\|grasas` (default automotrices), `?canal=` |
| `/api/mercado/share` | solo el bloque `share` (mismos parámetros); `?formato=csv` = serie mensual completa de todas las empresas (`mes,empresa,volumen,total,share`) |
| `/api/macro?ids=a,b` | series largas de `data/macro/series.csv` y las derivadas de la SE (`se_*`); `?formato=csv` = `fecha,id,valor,signo`. Sin `ids`, el catálogo |
| `/api/provincias?producto_id=<id>` | $/L y precio medianos por (provincia, fuente) y por (región, fuente), con `canal`, `n`, `fecha`; ver abajo |
| `/api/reventa?producto_id=<id YPF>` | todas las observaciones del período del producto YPF y de cada equivalente (el endpoint para cruzar con datos internos); ver abajo |
| `/api/cobertura` | por producto YPF del seed: equivalencias, fuentes y provincias con precio en 7 días, última fecha; ver abajo |
| `/salud` | sin clave, `{"ok":true}` para el health check de Render |

`/api/ultimo` suma `url` y `verificado` (vacío en las fuentes que no son Grok). `/api/fuentes` incluye una fila por cada `grok_*` de
`seed/grok_sitios.csv` o de los datos: la "corrida" es la última carga, `ultimo_ok` la fecha del último dato.

### Precio de reventa por provincia — `/api/provincias`, `/api/reventa`, `/api/cobertura`
Con clave, calculados por pedido sobre `obs` (Grok `verificado=0` se muestra marcado, no se oculta). La ventana `dias` (1 a 366, default 30) termina en el **último día con datos**, no en hoy. Todas las
respuestas llevan `hasta` y `nota` ("no es tiempo real: recolección diaria, SEPA con ~1 día de atraso"). `?formato=csv` aplana. Una mediana **nunca mezcla fuentes**. Cada aviso (fuente + url + ean + título + vendedor + envase + provincia)
cuenta una vez, con su observación más reciente de la ventana; `$/L = precio / (litros × unidades)`, igual que `/api/indice`; avisos sin litros no entran.
- `GET /api/provincias?producto_id=<id>[&fuente=][&mayoristas=1][&dias=N]` → `{producto_id, dias, hasta, nota, celdas[], regiones[], n_sin_provincia}`.
  `celdas[]` = `{provincia, region, fuente, canal, precio_litro, precio, n, fecha, vendedores[≤5], url, verificado, cargado}`: una por (provincia, fuente); `provincia:"online"` va con `region:""`.
  `regiones[]` = lo mismo por (región, fuente) con `provincias[]` en lugar de `provincia` (`online` no entra). `url`/`verificado`/`cargado` solo vienen llenos en fuentes Grok (de su observación más nueva; `verificado` es `1` solo si todas lo están).
  Los mayoristas salen solo con `mayoristas=1` o pidiendo esa `fuente` a propósito. Sin `producto_id`: `{dias, hasta, nota, productos:[{producto_id, nombre, fuentes:[celda + provincias (cuántas distintas)]}]}` para cada producto YPF, sin detalle por provincia.
- `GET /api/reventa?producto_id=<id YPF>[&dias=N]` → `{producto_id, dias, hasta, nota, ypf:{producto_id, marca, nombre, observaciones[]}, equivalentes:[{producto_id, marca, nombre, tipo, evidencia, observaciones[]}]}`
  (equivalentes de `seed/equivalencias.csv` sin `no_equivalente`). `observaciones[]` (todas las del período, la más nueva primero) = `{fecha, fuente, canal, vendedor, provincia, region, url, precio, precio_litro, litros, unidades, verificado, cargado}`
  (`verificado`/`cargado` solo en Grok, vacíos en el resto; `precio_litro` null si falta el envase). 400 si el producto no es YPF; 404 si no existe. CSV: una fila por observación con `rol` (`ypf|equivalente`), `producto_id`, `marca`, `nombre`, `tipo`.
- `GET /api/cobertura` → `{hasta, nota, total:{productos_ypf, con_equivalencia, con_precio_7d}, productos:[{producto_id, nombre, linea, segmento, sae, equivalencias, tiene_equivalencia, fuentes_7d, provincias_7d, ultima_fecha}]}`.
  Cuenta solo el precio del propio producto YPF (no el del equivalente), sin Grok `verificado=0`; `provincias_7d` cuenta provincias ISO (no `online`).

### Geometría del mapa (vendorizada)
`site/vendor/ar-provincias.js` (`window.AR_GEO`: `viewBox` y, por ISO, `n` nombre, `r` región, `d` path SVG, `c` centro) sale de **Natural Earth 1:10m Admin 1 – States, Provinces** (dominio público; texto en `site/vendor/ar-provincias.LICENSE`),
simplificada con `tools/geo_provincias.py` (Douglas-Peucker 0,03°, equirectangular × cos 40°, islas < 0,1 grados² fuera). Son los límites de Natural Earth, no una posición oficial del IGN. Sin CDN ni tiles.

### Vitrina — `/api/vitrina`
`{"fecha": último día con datos, "productos": [...]}`: un elemento por producto de marca YPF de `seed/productos.csv`, primero los
que tienen precio hoy (por `ypf.n` desc), después los que no. Cada uno:
`producto_id, nombre, linea, segmento, sae, base, imagen, imagen_fuente` (de `data/imagenes.csv`; `null` si no hay),
`ypf{n, promedio_litro, min_litro, max_litro, mediana_litro, presentacion_comun_l, promedio_presentacion, mas_barato{fuente, vendedor, precio, litros, precio_litro, url}, por_fuente[{fuente, n, promedio_litro}]}`,
`competencia{n, promedio_litro, min_litro, max_litro, equivalentes[{producto_id, marca, nombre, tipo, evidencia, en_promedio, imagen, n, promedio_litro, min_litro, mas_barato}]}`,
`specs{api, acea, ilsac, jaso, oem[], base, sae, segmento, verificado: confirmado|inferido, fuente_specs}` (de `seed/productos.csv`; campo vacío = `null`, `oem` separado por `;` → lista, `[]` si no hay), también en cada equivalente,
`dif_pct = (competencia.promedio_litro / ypf.promedio_litro - 1) × 100` (1 decimal; `null` si falta un lado).
- Qué cuenta: cada aviso (fuente + url + ean + título + vendedor + envase) una vez, con su observación más reciente dentro de los
  últimos 3 días contados desde el último día con datos (Tiendanube rota cada 2 días; SEPA no trae URL, por eso la clave es más larga que fuente+url).
  `precio_litro = precio / (litros × unidades)`. Se excluyen mayoristas (salvo `?mayoristas=1`), Grok con `verificado=0`
  y `tipo=servicio` (nunca entra a `obs`), y los avisos sin litros o sin `producto_id`.
- `promedio_litro` es media simple de los avisos; `mas_barato.litros` es el envase completo (litros × unidades, así `precio / litros = precio_litro`);
  `presentacion_comun_l` es el envase más frecuente (empate: el más chico) y `promedio_presentacion` el precio promedio de ese envase.
- Los equivalentes de `tipo = no_equivalente` se listan con `en_promedio: false` y **no** entran en `competencia.*` ni en `dif_pct`.
  Sin datos todo es `null` (n = 0), nunca 0 ni un valor arrastrado.
- Sanidad (`SANIDAD`, `RANGO_EQ` en `server.py`): un aviso con `precio_litro` fuera de [mediana/2,5; mediana×2,5] de su producto no
  cuenta (envase mal leído); un equivalente cuya mediana está a más de 3× (o menos de 1/3) de la mediana YPF va con `en_promedio: false`.
  Cada equivalente lleva `excluido`: `null`, `"no_equivalente"` o `"fuera_de_rango"`.
- CSV: una fila por producto YPF con `ypf_*` y `comp_*` aplanados y `n_equivalentes` (sin las listas).

### Carga de Grok — `POST /api/cargar`
Cuerpo = el CSV (`Content-Type: text/csv` o `text/plain`; o formulario con el campo `csv`). Auth: header `X-Carga-Clave` = env
`LUB_CARGA_CLAVE` (solo sirve para cargar: el resto de la API da 401) o la clave principal. Nunca en la URL. Sin `LUB_CARGA_CLAVE`, solo la principal.
Encabezado malo, más de 500 filas o ninguna fila válida → 400 sin guardar nada; filas con error se listan en `errores` (con `fila`) y las
demás se guardan. Respuesta: `ok`, `verificadas`, `no_verificadas`, `errores`, `duplicadas`, `filas` (una por fila guardada) y `commit` (lista de sha) o
`"solo local"`. Persistencia: escribe `data/grok/AAAA-MM.csv` y, con `GH_CARGA_TOKEN`, lo comitea por la GitHub Contents API
(`grok: carga <fuente> <fecha> (<n> filas)`); si el commit falla responde 502 y los datos quedan solo en memoria (reenviar es idempotente).
Envs: `LUB_CARGA_CLAVE`, `GH_CARGA_TOKEN` (fine-grained PAT, solo este repo, Contents: read and write), `GH_REPO` (default `noguerafran-alt/LUBRICANTES`).
Verificación: 1 req/s, timeout 15 s, sin seguir redirecciones, `User-Agent` de `ml.py`.

`precio_litro = precio / (litros × unidades)`. Índice: mediana de `precio_litro`
del día por (segmento, SAE, marca) / mediana YPF del mismo grupo y día × 100.
Sin YPF ese día en ese grupo → celda vacía, no se calcula.

## Mercado — `macro.py`, `/api/mercado`, `/api/macro`

Relevamiento y fuentes en `docs/relevamiento/mercado.md`. Dos fuentes, dos corridas:

- **`python macro.py series`** (diaria, en el job `recolectar`): baja de `https://apis.datos.gob.ar/series/api/series/?ids=ID&format=csv&limit=5000`
  (una request por id, paginada con `start=`; sin token, CC-BY 4.0) las ids de `seed/macro_series.csv` y escribe
  **`data/macro/series.csv`** `fecha,id,valor,signo`. Valida que tenga algún valor y que el último dato no sea más viejo que
  120 (diarias) / 150 (mensuales) / 300 (trimestrales) días: una serie vacía o cortada **no se escribe** (conserva lo que ya tenía) y queda en
  `data/fuentes.csv` como `macro_<id con _>` con el error; además una fila `macro_series` por corrida (`n_items` = series pedidas, `n_con_precio` = con datos).
  Cuando una serie se recupera, `macro.py` escribe una fila buena de esa fuente que limpia el error.
- **`python macro.py energia`** (mensual, job `mercado`, cron `0 12 28 * *` + `workflow_dispatch`, ~2,5 min): resuelve la URL por CKAN `package_show`
  (dataset `5bdc436c-…`, recurso `f0e4e10a-…`; si falla, la URL directa), lee el CSV de ~770 MB **en streaming** (sin guardarlo), valida el encabezado,
  se queda con `ubric`/`Grasas`/`Gasoil*` (no `Bases Lubricantes`: es insumo entre empresas) y escribe **`data/macro/energia.csv`**
  `mes,empresa,producto,canal,provincia,cantidad` (`mes` AAAA-MM; `canal` = `subtipodecomercializacion`; ~130 mil filas, 9 MB).
  El archivo rellena con `0.0000` toda la grilla empresa × canal × provincia: esas filas **no se escriben**, así que una empresa sin fila ese mes es
  "sin dato", nunca 0. **Gasoil** va sin empresa ni provincia (`empresa=Todas`, `provincia=Todas`): solo se usa por canal.
  `empresa` lleva una etiqueta corta (`macro.ETIQUETAS`: YPF, Shell/Raízen, TotalEnergies, PAE/Axion, Petronas, Fercol, DAPSA, Fuchs, Nynas, Esso, …;
  lo no mapeado queda con su nombre). Si la fuente falla o el último mes retrocede, no se escribe nada y `macro_energia` queda con el error en `fuentes.csv`.

**Signos INDEC** (tabla en el relevamiento §3). datos.gob.ar manda null sin signo: en `series.csv` es `valor` vacío + `signo` `...`. Un null **nunca es 0**;
solo `-` (cero absoluto) vale 0. Las variaciones (`var_ia`, compuestos) se calculan solo si existen los dos extremos; si no, `null`.

**`GET /api/mercado`** (todo calculado en memoria al arrancar desde `data/macro/`, `data/obs/` y `seed/`):
- `actualizado`: `energia` = último mes de `energia.csv`; `series` = última corrida de `macro_series` sin error.
- `share`: `producto` (`Lubricantes automotrices(m3)`, …), `canal` (o null), `meses` (36, terminan en el último mes con dato), `total` (m3 o null), `empresas`
  (top 7 por volumen de la ventana + `Otras`; `serie` de share 0–1 o null, `ultimo`, `hace12`, `var_pp` en puntos porcentuales, `volumen_ultimo`), `canales`
  (del producto, por volumen), `provincias` (último mes: `share_ypf`, `share_ypf_hace12`, `var_pp`, `volumen`; mes contra el mismo mes del año anterior), `nota` (límites).
  Share = volumen de la empresa / suma de las empresas que declaran ese mes. Un mes o empresa sin fila = null.
- `actividad`: una entrada por serie de `seed/macro_series.csv` más las derivadas de la SE (`se_lub_automotrices`, `se_lub_industriales`, `se_gasoil_carga`,
  `se_gasoil_agro`; `server.DERIVADAS`): `id,nombre,grupo,unidad,frec,fuente`, `serie` (últimos 60 puntos `{fecha,valor,signo}`), `ultimo` (el último punto, aunque sea null),
  `var_ia` (% contra el mismo mes del año anterior).
- `compuestos`: `precio_real` (mediana mensual del $/L de los pares YPF ↔ equivalente de `seed/equivalencias.csv` — sin `no_equivalente`, mayoristas ni Grok sin verificar, con la
  sanidad de la vitrina —, deflactada por el IPC nacional general, base = primer mes con precio; sin IPC publicado = null), `precio_usd` (diario, sobre el tipo de cambio de
  valuación; día sin cotización = null, no se arrastra), `asequibilidad` (precio YPF / índice de salarios privados registrados, base 100 = primer mes con precio YPF),
  `demanda_potencial` (0,5 peajes + 0,3 gasoil a Transporte de Carga de la SE + 0,2 EMAE Agro, cada uno base 2023 = 100; null si falta un componente o 2023 no está completo;
  **pesos supuestos, sin calibrar**) y `notas`.
- Límites del share (van en `nota` y hay que mostrarlos): solo declaran las empresas inscriptas en la Res. SE 1104 (Mobil, Castrol, Motul, Liqui Moly e importadores chicos no
  figuran); es sell-in de la petrolera, no compra del consumidor; viene por empresa, no por marca (Elaion/Helix).
- Fuente al pie: "INDEC, vía datos.gob.ar (CC-BY 4.0)" o "Secretaría de Energía, Res. 1104".
