# Tiendas y sitios con precio (relevamiento 2026-11-04)

Ya usamos el catálogo. `recolectar.py` lee `/api/catalog_system/pub/products/search` de VTEX en Carrefour, Masonline, Easy y Jumbo. Probamos los catálogos de las marcas (YPF por GraphQL, Shell, Castrol/Axion, Mobil/Moove, TotalEnergies, Petronas, Puma, Gulf, Motul, Liqui Moly, Bardahl) y ninguno trae precio. Los catálogos con precio son los de las tiendas. La novedad es una tienda VTEX que no teníamos: Norauto, con Shell y Castrol en stock. Se suma con una línea de código.

Todo se probó con curl el 2026-11-04, desde la PC y con User-Agent honesto. No se probó desde IPs de GitHub Actions.

## Tabla única, de más a menos valor

| # | Sitio | Tipo | Marcas que cubre | Precios públicos | Método legítimo y endpoint | HTTP | Ejemplo real | Riesgo ToS / bloqueo | Veredicto |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Norauto | Cadena de service (VTEX) | Elaion 14, Total 10, Castrol 7, Elf 7, Shell 7, Eurorepar 5 | Sí | VTEX `https://www.norauto.com.ar/api/catalog_system/pub/products/search?fq=C:/3/20/&_from=&_to=` (100 productos, con EAN) | 206 `0-49/100` | Shell Helix HX7 10W40 4 L $57.999,99 (EAN 5011987067134). Castrol Magnatec 10W40 A3 4 L $66.500 | Bajo. robots no bloquea `/api` y los términos no hablan de extracción | **Incorporar v1.** Trae Shell y Castrol por EAN sin código nuevo |
| 2 | Tienda D'Atri | Mayorista Castrol/Axion (Shopify) | Castrol (EDGE, GTX, Magnatec, ACTEVO) | Sí | Shopify `https://tiendadatri.com.ar/products.json?limit=250&page=N` (1006 productos, unos 101 lubricantes) | 200 | EDGE PROF E 0W-30 caja 12x1 L $480.967,85 | Bajo. robots no bloquea `/products.json` y no encontré cláusula contra la extracción | **Incorporar v1 como fuente mayorista aparte.** Hay que pasar caja o tambor a litros. **No verificado:** si el precio incluye IVA |
| 3 | Coto | Súper (Oracle Endeca) | Total, Bardahl, Gulf (Elaion, Shell y Castrol: 0) | Sí, unos 20 aceites | Vista JSON de la búsqueda pública: `https://www.coto.com.ar/sitios/cdigi/browse?Ntt={q}&Nrpp=50&format=json` (sin token; trae `eanPrincipal`, `brand`, `sku.activePrice`) | 200 | TOTAL Quartz 7000 10W-40 4 L $64.169. Gulf Pride 4T Plus 20W-50 1 L $12.339 | Medio. No es una API documentada y **los términos no se leyeron** | **Diferir** hasta leer los términos. Si no lo prohíben, entra |
| 4 | LS Palermo | Lubricentro (Tiendanube) | Multimarca: YPF, Shell y otras | Sí | `sitemap.xml` (10.476 URLs `/productos/`), filtro de URLs con regex de aceite y `LS.variants[].price_number` en cada HTML | 200 | Elaion Auro 5W30 4 L $131.000. Shell Helix Ultra 5W30 1 L $45.800 (salió del JSON-LD de productos relacionados) | Bajo. robots estándar de Tiendanube. No encontré términos | **Incorporar v1 en la segunda tanda.** Un request por producto. Ojo: el JSON-LD `Product` es de los relacionados, no del principal |
| 5 | Casa González (spch.com.ar) | Lubricentro (Tiendanube) | YPF; Shell según la búsqueda | Sí | Igual que LS Palermo (2486 productos, 189 de aceite) | 200 | ELAION MI 15w40 4 L $51.584. EXTRA VIDA XV300 1 L $16.224 | Bajo | **Incorporar v1** con el mismo lector. **No verificado:** el precio de Shell ($129.100 el Helix Ultra 5W-40 4 L, visto solo en la búsqueda) |
| 6 | Daytona / Tienda Neumáticos | Service (VTEX) | Total y otras, en combos | Sí | VTEX `fq=C:/3/` (12 productos) | 200 | Combo Total Quartz 7000 10W-40 + filtro $87.923 | Bajo | **Diferir.** Es precio de servicio, no de producto. No entra en $/L |
| 7 | Fercol | Marca nacional (Tiendanube) | Fercol | Sí | Tiendanube, sitemap (307 productos) y `LS.variants` | 200 | Semisintético 10w-40 $34.999 | Bajo | **Diferir.** Una sola marca de segunda línea, y los litros no están claros |
| 8 | Allende Repuestos | Repuestos (WooCommerce) | Casi todo YPF | Sí | `https://www.allenderepuestos.com.ar/wp-json/wc/store/v1/products?search=aceite&per_page=50` | 200, 24 productos | Elaion Auro 5W30 4 L $137.400 | robots no verificado | **Diferir.** Aporta poco |
| 9 | Lubricentro DG | Comercio chico (Tiendanube) | Castrol, YPF, Total | Sí | Tiendanube, 25 productos | 200 | Castrol Edge 5w40 $107.000 | Bajo | **Descartar.** Precios desactualizados (Elaion TS a $39.000) y títulos sin litros |
| 10 | Wynn's | Marca (WooCommerce) | Wynn's, solo aditivos | Sí | `https://wynns.com.ar/wp-json/wc/store/v1/products?per_page=100` | 200, 59 productos | FOR OIL 325 ml $395.757,12 | Bajo | **Descartar.** No vende aceite de motor y el precio parece por caja sin decirlo |
| 11 | Frávega | Retail (VTEX marketplace) | Importados (Valvoline, Castrol ATF) | Sí | VTEX `fq=C:/1000928/1000534/1000541/` | 206, 163 productos | Valvoline Daily Protection 10W30 $243.695 (Glic) | Bajo | **Descartar.** Son precios de importación de terceros, no de góndola |
| 12 | ENAUSA | Distribuidor YPF | YPF | Sí, en el JSON-LD | sitemap y JSON-LD | 200 | Elaion Auro D1 530 caja 4x4 L $471.300 | **Alto.** Los términos prohíben reproducir el contenido y dicen "no publicamos precios" | **Descartar** salvo autorización escrita |
| — | Disco, Vea | Súper (VTEX) | — | Fichas sin stock | VTEX | 206 | — | — | Descartar. Duplican a Jumbo y todo está sin stock |
| — | Sitios oficiales de marca: YPF, Shell, Castrol/Axion, Mobil/Moove, Total/Elf, Puma, Gulf, Motul, Liqui Moly, Mannol, Valvoline, Fuchs | Marca | — | **No** | — | 200 | — | — | Descartar. Catálogos sin precio y ninguna tienda oficial |
| — | Petronas, mobil.com, Hiper Libertad, La Anónima, Ditesac | — | — | — | — | 202 challenge o 403 | — | Bloqueo anti-bot | Descartar. No se evade |
| — | Helixturno (Shell) | Turnos | Shell | Solo por API interna | — | 200 | — | Fuera de las reglas | Descartar |
| — | Bardahl, Yaguar | — | — | — | — | 200 | — | robots `Disallow: /` | Descartar |
| — | Día, Cetrogar, Toledo, Blaisten, Diarco, Makro, Vital, Megatone, Musimundo, Lubricentro Máximo | — | — | No venden aceite o no publican precio | — | 200 | — | — | Descartar |
| — | Repsol, Lubrax, Pennzoil, STP, Ravenol | — | — | Sin sitio en AR | — | 000 | — | — | Descartar. Lubrax se relanzó en julio de 2026: volver a mirarlo más adelante |

## Las 5 fuentes nuevas que más suman, con su receta

**1. `vtex_norauto` (Shell, Castrol, Elf, Total, YPF).** Es una línea en `VTEX` de `recolectar.py`. `ml.pedir` ya acepta el 206, como en Carrefour.
```python
    "vtex_norauto": ("www.norauto.com.ar", "C:/3/20/"),
```
- Queda afuera `C:/4/24/`: son combos de cambio de aceite con colocación, un precio de servicio.
- Algunos productos traen `AvailableQuantity=99999`. Es un valor de relleno: tomarlo como "hay stock", no como cantidad.
- `ListPrice` no fue revisado. No verifiqué si viene inflado como en Cencosud; mirarlo en la primera corrida antes de guardarlo.

**2. `shopify_datri` (Castrol mayorista).** Necesita un lector nuevo de unas 25 líneas, solo con stdlib.
- Pedir `/products.json?limit=250&page=N` hasta que `products` venga vacío, con `ml.pedir`.
- Quedarse con los productos cuyo `product_type` sea LUBRICANTES, SINTÉTICO o MINERAL.
- Por cada variante con `available`: `precio=float(price)`.
- Las unidades salen del título: `CAJA (\d+)X(\d+(?:[.,]\d+)?)L` da unidades × litros, y `TAMBOR (\d+)L` da 1 × litros.
- `marca_cruda` va vacía, porque el vendor es "D'ATRI". La marca sale del título solo si `normalizar.marca_de` la reconoce.
- **No verificado:** que los títulos digan "Castrol". Si no lo dicen, quedan en `sin_match`. No hay que poner Castrol por defecto, porque eso es adivinar.
- Va como fuente propia, para que el índice la pueda excluir: es precio mayorista y no se sabe si incluye IVA.

**3. `coto` (Total, Bardahl, Gulf), condicionado a leer sus términos de uso.**
- Hacer 6 búsquedas por día: "aceite motor", "total quartz", "bardahl", "gulf", "elaion", "shell".
- Endpoint: `/sitios/cdigi/browse?Ntt={q}&Nrpp=50&format=json`.
- Mapeo: `ean=eanPrincipal`, `marca_cruda=brand`, `precio=sku.activePrice`.
- Sacar los duplicados por EAN, porque las búsquedas se pisan.
- **Pendiente:** confirmar la estructura exacta del JSON. No guardé un ejemplo para armar el parser.

**4 y 5. `tn_lspalermo` y `tn_spch` (Shell y multimarca).** Llevan un lector Tiendanube común, también con stdlib.
- Bajar `sitemap.xml` y quedarse con las URLs `/productos/` que pasen la regex `aceite|lubric|elaion|helix|castrol|quartz|mobil`.
- Por cada URL, a 1 request/s: sacar el JSON de `LS.variants = [...]` con regex y leer `price_number` y `stock`.
- El título sale de `<h1>` o de `og:title`. No usar el JSON-LD: es de los productos relacionados.
- Ponerle un tope de URLs por día. **No verificado:** cuántas URLs de LS Palermo quedan después del filtro.

## Lo que sigue faltando

- **Mobil y Petronas:** ninguna fuente pública con precio verificado. Norauto, Coto y los lubricentros no los mostraron en stock. El único camino es `ml` con token (`official_store_id`), que ya está previsto. Por web, las tiendas oficiales de ML dieron 403 y no insistí, por la regla del repo.
- **Shell y Castrol** quedan cubiertas con Norauto (EAN), D'Atri (Castrol mayorista) y LS Palermo o Casa González.
- **No verificado:** los términos de Coto, el IVA de D'Atri, el `ListPrice` de Norauto, la estructura JSON de Coto y si hay bloqueos desde GitHub Actions.


---

## Relevamiento: marcas-grandes

Ninguno de los sitios oficiales de mi grupo (YPF, Shell, Castrol/Axion, Mobil, TotalEnergies/Elf, Petronas, Puma y Gulf) publica precios de lubricantes. No hay una tienda online oficial de estas marcas en Argentina.

Probé todo con curl y un User-Agent honesto (`LUBRICANTES-relevamiento/1.0`) el 2026-11-04. En cada página que bajé conté los precios del tipo `$ 12.345` y busqué rastros de plataforma (Shopify, WooCommerce, VTEX, Tiendanube) y de schema.org/Product. En todas dio cero, salvo una clase CSS de WooCommerce en Puma.

| Marca | URL real | HTTP | ¿Precios públicos? | Vía legítima | robots / términos | Productos con precio |
|---|---|---|---|---|---|---|
| YPF (Elaion/Extravida) | lubricantes.ypf.com, www.elaion.com.ar | 200 / 200 | No | Ninguna para precios | elaion.com.ar: no lo revisé | — |
| YPF tienda | tienda.ypf.com, tiendaypf.com.ar, ypfshop.com.ar, tienda.elaion.com.ar | 000 (no resuelven); www.ypf.com/tienda: 302 a error 404 | No existe | — | — | — |
| YPF ServiClub | www.serviclub.com.ar | 200 | No: es canje por puntos, no venta en pesos | — | no lo revisé | — |
| Shell | www.shell.com.ar | 200 | No: vende en estaciones, sin tienda | `.model.json` de la página (ya probado): da nombres, no precios | no lo revisé | — |
| Shell Helixturno | www.helixturno.com.ar (/combos, /lubricantes) | 200 | No en el HTML. Es una app Angular que carga los combos con su API interna. El JSON-LD tiene `priceRange: "Más información en https://helixturno.com.ar"` | No viable: solo por la API interna api-core-turnos-prod, que está excluida | robots.txt: `Allow: /`, sitemap con 9 URLs. En términos no encontré cláusula sobre extracción automatizada | — |
| Shell tienda | tienda.shell.com.ar, shop.shell.com.ar, tiendashell.com.ar | 000 | No existe | — | — | — |
| Castrol | www.castrol.com/es_ar/argentina/home.html (castrol.com.ar redirige con 301) | 200 | No. "Dónde comprar" (wtb-argentina.html, 200) es un buscador de locales, sin precios ni links a tiendas | — | no lo revisé | — |
| Axion (Castrol) | www.axionenergy.com/castrol/ | 200 | No | WooCommerce Store API: 404 | no lo revisé | — |
| Castrol/Axion tienda | tienda.castrol.com.ar, tiendacastrol.com.ar, tienda.axionenergy.com(.ar) | 000 | No existe | — | — | — |
| Mobil (Moove) | www.mobil.com/es-ar; ar.moovelub.com | 403; 200 | No viable: mobil.com bloquea (403, también en robots.txt). Moove no tiene precios ni tienda (Shopify `/products.json`: 404) | — | mobil robots: 403 | — |
| TotalEnergies / Elf | totalenergies.com.ar/es | 200 (301 desde la raíz) | No. Solo "Dónde cambiar el aceite": distribuidores, Elf Expert y listado de talleres Quartz Auto Services | `/products.json`: 404 | no lo revisé | — |
| Total/Elf tienda | tienda.totalenergies.com.ar, elf.com.ar, tiendaelf.com.ar | 000 | No existe | — | — | — |
| Petronas | www.pli-petronas.com/es-ar | 202 sin cuerpo (challenge) | No viable: hay un challenge anti-bot y no lo evado | — | robots.txt: 302 | — |
| Puma Energy | pumaenergy.com/es/country/argentina/ | 200 | No | WooCommerce Store API: 404 (el WooCommerce que se ve es una clase CSS de galería, no una tienda) | no lo revisé | — |
| Gulf | www.gulfoil.com.ar redirige con 301 a latam.gulfoilltd.com | 200 | No | WooCommerce Store API y `/products.json`: 404 | no lo revisé | — |

Lo que no está en la tabla:

- **Sobre "¿por qué no usar catálogo?":** los catálogos oficiales que existen no traen precios. El de YPF (`data/catalogo_ypf.json`, del GraphQL `magui.ypf.com`) tiene título, descripción, imagen y fichas técnicas, pero ningún campo de precio. Los de Shell, Castrol y TotalEnergies son solo nombres y normas.
- **Dónde sí hay precios por catálogo:** en dos fuentes, y ninguna es de las marcas:
  1. El `catalog_system` de VTEX en las cadenas, que ya se usa.
  2. El catálogo de productos de Mercado Libre por API con OAuth, que también está previsto. Allí el filtro "Solo tiendas oficiales" muestra Castrol y Mobil, entre otras. No probé la API ni confirmé tiendas oficiales argentinas de cada marca, porque no es mi grupo y la regla del repo no permite scraping de Mercado Libre.
- **Para que alguien lo revise:** el GraphQL `magui.ypf.com` que ya usa el repo es un backend propio de YPF que la web llama sin documentación pública. Para el catálogo de YPF ya está en uso, pero con las reglas de esta tarea, si se lo tomara como fuente de precios quedaría como "no viable". Igual no tiene precios.
- **Sin precios para mostrar:** no hay un solo producto con marca y precio en mis resultados, porque ningún sitio oficial publica precios.
- **Fuentes:** [mejorescompras Elaion](https://mejorescompras.com.ar/precio/MLA27257458--aceite-ypf-elaion-10w40-ts-1040-semisintetico-x-4l-ex-f30), [Moove representa a Mobil](https://www.16valvulas.com.ar/nuevo-comienzo-mobil-se-relanzo-en-argentina-ahora-representada-por-moove/), [Raízen licenciataria de Shell](https://www.16valvulas.com.ar/raizen-argentina-nueva-representante-de-shell-oficializo-su-alianza-con-volkswagen/), [ML más vendidos aceites](https://www.mercadolibre.com.ar/blog/mas-vendidos/aceites-motor).


---

## Relevamiento: marcas-importadas

Solo una fuente de este grupo publica precios y deja leerlos por una API pública: **wynns.com.ar**, con la WooCommerce Store API. Los precios que devuelve no parecen precios por unidad y vende aditivos, no aceite de motor. Ningún sitio oficial de los otros 12 muestra precios. Lo probé con curl y User-Agent `LUBRICANTES-relevamiento/1.0 (curl)` el 2026-11-04.

| Marca | URL real | HTTP | ¿Precios públicos? | Cómo se lee legítimamente | robots / términos | Productos de muestra (marca / nombre / precio) | Veredicto |
|---|---|---|---|---|---|---|---|
| Wynn's | https://wynns.com.ar/tienda/ | 200 | Sí | WooCommerce Store API: `/wp-json/wc/store/v1/products?per_page=100` da 200, X-WP-Total=59, 1 página, los 59 con `is_in_stock=true`. Precio en `prices.price` dividido por 10^`currency_minor_unit` (2), en ARS. El HTML de la ficha muestra lo mismo. | robots.txt solo bloquea `/wp-admin/`, `?add-to-cart=` y carpetas de logs; `/wp-json` está permitido. No encontré página de términos: las 3 rutas que probé dieron 404. | Wynn's / FOR OIL 325 ml antifricción / $395.757,12. Wynn's / Engine Stop Leak 325 ml / $433.799,52. Wynn's / Refrigerante Anticongelante 1L / $137.068,80 (la ficha HTML confirma el mismo número). | Viable técnicamente. Pero los montos son absurdos para una unidad (Stop Squeak 30 ml a $323.476,56): probablemente son por caja o están mal cargados, y la API no dice la unidad. No hay aceite de motor, solo aditivos. Antes de sumarla habría que confirmar la unidad. |
| Bardahl | https://bardahl.com.ar | 200 | No | PrestaShop en modo catálogo: el HTML trae `"is_catalog":true` y `"show_prices":false`. | robots.txt: `User-agent: *` / `Disallow: /` (solo habilita los bots de Google) | — | No viable: no muestra precios y robots prohíbe todo. |
| Motul | https://motul.com.ar/productos/ | 200 | No | Catálogo con fichas técnicas, sin precios. La compra de distribuidores pasa por un registro (`/auth/register?role=distribuidor`). Enlaza al Mercado Shops de un revendedor (motosjonte.mercadoshops.com.ar). | robots: Cloudflare `Content-Signal: search=yes,ai-train=no,use=reference`, Allow / | — | No viable (sin precios). |
| Liqui Moly | https://liqui-moly.com.ar | 200 | No | WordPress con JetEngine; no es WooCommerce (la Store API da 404 y wp-json no expone `wc`). Sitemap `producto-sitemap.xml` con fichas sin precio. Deriva a la tienda de ML del distribuidor "dazsa" (mercadolibre.com.ar/pagina/dazsa). | robots solo bloquea `/wp-admin/` | — | No viable. La vía con precios es ML, por API. |
| Mannol | https://mannol.com.ar | 200 | No | HTML estático (Bootstrap), sin catálogo con precios | robots.txt da 404 | — | No viable. |
| Valvoline | valvoline.com.ar redirige a https://www.valvolineglobal.com/es-ar/ | 200 | No | Sitio institucional global | no revisado | — | No viable (ya figuraba así en competencia.md). |
| Fuchs | https://www.fuchs.com/ar/es/ | 200 | No | Institucional (FUCHS ARGENTINA S.A.), sin tienda; fuchs.com.ar no resuelve (000) | no revisado | — | No viable. |
| Goodyear lubricantes | goodyear.com.ar (es de neumáticos); goodyearlubricantes.com.ar y lubricantesgoodyear.com.ar dan 000 | 200 / 000 | No hay sitio oficial de lubricantes | Ya está cubierta por el VTEX de Easy, que vende Elite 5W40, 10W40, 15W40 y 20W50 | — | — | Sin fuente oficial; ya entra por vtex_easy. |
| Repsol | repsol.com.ar y www.repsol.com.ar dan 000 | 000 | — | La búsqueda solo trajo la tienda de España (repsol.es, en euros) | — | — | No viable: sin presencia web en AR. |
| Lubrax | lubrax.com.ar y www.lubrax.com.ar dan 000 | 000 | — | Según la prensa, Vibra relanzó la marca en AR el 2026-07-27; no apareció un sitio AR | — | — | No viable por ahora; vale revisarlo de nuevo, es un lanzamiento reciente. |
| Pennzoil | pennzoil.com.ar da 000 | 000 | — | Sin presencia oficial (igual que en competencia.md). Hay fichas en Jumbo VTEX. | — | — | No viable. |
| STP | stp.com.ar y www.stp.com.ar dan 000 | 000 | — | Solo aparece en desertcart.com.ar (reventa importada) | — | — | No viable. |
| Ravenol | ravenol.com.ar y ravenolargentina.com.ar dan 000; ravenol.de da 200 | 000 | — | No encontré importador oficial; solo desertcart.com.ar | — | — | No viable. |
| Tiendas oficiales en ML | `mercadolibre.com.ar/tienda/{motul, valvoline, liqui-moly, pennzoil, repsol, lubrax, bardahl, goodyear, wynns, stp, ravenol, mannol, fuchs}` | 403 en todas | — | No insistí: las reglas del repo prohíben scrapear ML. Si existen tiendas oficiales, hay que verlo por la API (`official_store_id`). | — | — | Solo como dato: no verificado. La única tienda vinculada desde una web oficial es la de "dazsa" (Liqui Moly). |

Con estas marcas, los precios hay que sacarlos de la API de ML (OAuth) o de los VTEX de retail que ya tenemos (Easy para Goodyear y Bardahl, Jumbo para Pennzoil). No hay catálogos de marca con precio, salvo Wynn's con la duda de la unidad.


Fuentes:
- [Vibra: relanzamiento de Lubrax en Argentina](https://vibraenergia.com.br/sites/default/files/2026-07/Lubrax%20relan%C3%A7a%20sua%20marca%20na%20Argentina%20e%20acelera%20plano%20de%20expans%C3%A3o%20com%20produ%C3%A7%C3%A3o%20local.pdf)
- [Fuchs Argentina](https://www.fuchs.com/ar/en/company/about-fuchs/company-portrait)
- [Easy: Goodyear Elite 5W40](https://easy.com.ar/aceite-goodyear-elite-full-sint-5w40-1l/p)
- [Repsol España, tienda](https://www.repsol.es/tienda/vehiculo/aceites-de-motor/coche/)
- [Desertcart AR, Ravenol](https://www.desertcart.com.ar/products/65155565-ravenol1111122-005-01-000-engine-oil.md)
- [Desertcart AR, STP](https://www.desertcart.com.ar/products/49554709-engine-stop-leak-for-petrol-and-diesel-engines-300-ml.md)

---

## Relevamiento: lubricentros

Relevamiento del grupo "lubricentros y e-commerce especializados", probado con curl el 2026-11-04. Usé un User-Agent honesto (`LubricantesRelevamiento/0.1`), sin cookies ni tokens.

**Viable como fuente diaria**

| # | Sitio | URL | Plataforma | ¿Precios sin login? | Cómo se leen (legítimo) | robots.txt / términos | HTTP | Productos reales probados (marca / nombre / ARS) | Valor |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Norauto Argentina** (cadena de service) | https://www.norauto.com.ar | VTEX | Sí | La misma API `catalog_system/pub/products/search` que ya usa `recolectar.py`: `fq=C:/3/20/` (Lubricentro/Aceites) tiene 100 productos sueltos con EAN, `fq=C:/4/24/` (Servicios/Cambio de aceite) 35 combos con colocación y `C:/3/163/` 3 productos | Solo bloquea `/busca/`, `/checkout/`, `/account/` y similares, no `/api`. La página de términos (200) no menciona robots, scraping ni extracción | 206, `resources: 0-49/100` | Shell Helix / Aceite Shell Helix HX7 10W40 Semi Sintético 4 Lts / 57999.99 (EAN 5011987067134) · Elaion / Aceite YPF Elaion Ts 10W40 Semi Sintético 4 Lts / 63600 (EAN 7790968914671) · Castrol / Aceite Castrol Magnatec 10W40 A3 Semi Sintético 4 Lts / 66500 | **Alto.** Es el único de este grupo que tiene Shell y Castrol con stock (Elaion 14, Total 10, Castrol 7, Elf 7, Shell 7, Eurorepar 5). Cruza por EAN. En algunos productos `AvailableQuantity` = 99999, que es un valor de relleno |
| 2 | **Tienda D'Atri** (mayorista Castrol/Axion) | https://tiendadatri.com.ar | Shopify | Sí | `/products.json?limit=250&page=N`: 1006 productos, unos 101 son lubricantes (`product_type` LUBRICANTES, SINTÉTICO, MINERAL; los tags traen SAE y litros) | Solo bloquea checkout, cuenta y similares, no `/products.json`. En los términos no hay cláusula anti-extracción (lo único que encontré con "spider" era código JS, no texto legal) | 200 | EDGE PROF E 0W-30 (CAJA 12X1L) / 480967.85 · GTX 10W-40 (TAMBOR 205L) / 1555367.58 · ACTEVO 4T 10W-40 SYN BLD (CAJA 16X1L) / 261703.55 | **Medio-alto.** Precio mayorista por caja o tambor: hay que dividir por la cantidad de unidades. Todo figura con vendor "D'ATRI", así que la marca sale del título. No verifiqué si los precios incluyen IVA |
| 3 | **LS Palermo** (lubricentro) | https://lspalermo.com.ar | Tiendanube | Sí | Tiendanube no tiene API pública de productos. Camino: `sitemap.xml` (10476 URLs `/productos/`) y en cada página el JSON inline `LS.variants` (`price_number`) o `#price_display[data-product-price]`. Ojo: en Tiendanube el JSON-LD `Product` de la página es de los productos **relacionados**, no del principal (el principal figura como `WebPage`) | robots estándar de Tiendanube (bloquea admin, checkout y account, no `/productos/`). No encontré link a términos en la home | 200 | Aceite Elaion Auro 5w30 Sintetico Nafta Diesel 4 Litros / 131000 · Shell / Aceite Shell Helix Ultra 5w30 X 1l Sintetico / 45800 (sale del JSON-LD de relacionados) | **Medio.** Catálogo grande y multimarca, pero lleva un request por producto: limitarlo a las URLs que filtre una regex de aceite |
| 4 | **Casa González** (SPCH) | https://spch.com.ar | Tiendanube | Sí | Igual que LS Palermo: sitemap (2486 productos, 189 de aceites) y `LS.variants` | robots estándar de Tiendanube. Sin términos a la vista | 200 | ELAION MI 15w40 x 1L / 15600 · YPF / EXTRA VIDA XV300 C12/1 x 1L / 16224 · ELAION MI 15w40 x 4L / 51584 | **Medio.** Según la búsqueda vende Shell (Helix Ultra 5W-40 4 L a $129.100), pero ese precio no lo probé con curl |
| 5 | **Fercol Lubricantes** (marca nacional, tienda propia) | https://www.fercollubricantes.com.ar | Tiendanube | Sí | Sitemap (307 productos) y `LS.variants` / JSON-LD | robots estándar de Tiendanube | 200 (home y sitemap). Una URL que armé a mano dio 404 | Fercol / Aceite Semisintético 10w-40 / 34999 · Fercol / Aceite Larga Vida 15w40 / 35678 · Fercol / Aceite Sintético 5w-30 / 43712 | **Medio.** Es una sola marca, segunda línea. No conozco los litros de cada precio: hay que sacarlos de la variante |
| 6 | **Allende Repuestos** | https://www.allenderepuestos.com.ar | WooCommerce | Sí | Store API `/wp-json/wc/store/v1/products?search=aceite&per_page=50` (24 resultados) | No lo verifiqué (robots.txt no devolvió contenido legible) | 200, `X-WP-Total: 24` | Aceite ELAION AURO 5W30 sintético 4L / 137400 (in stock) · ACEITE ELAION 4L 10W40 SEMISINTETICO F30 / 72800 | **Bajo.** Pocos productos, casi todo YPF. Algunos tienen precio 0 sin stock y hay que descartarlos |
| 7 | **Lubricentro DG** | https://lubricentrodg.mitiendanube.com | Tiendanube | Sí | Sitemap (25 productos) y `LS.variants` | robots estándar de Tiendanube | 200 | Castrol Edge EURO CAR 5w40 / 107000 · YPF Elaion TS 10w40 - EX F30 / 39000 · Total Quartz 9000 5w40 / 72000 | **Bajo.** Comercio chico. Los precios parecen desactualizados (Elaion TS a 39000, contra 63600 en Norauto) y los títulos no dicen litros. Hay un Liqui Moly a $0 |

**Probados pero no viables, o sin valor para la serie de precios**

| # | Sitio | URL | Resultado | Motivo |
|---|---|---|---|---|
| 8 | Daytona / Tienda Neumáticos (mismo catálogo VTEX) | https://www.daytona.com.ar · https://www.tiendaneumaticos.com.ar | 200. La API VTEX funciona: `fq=C:/3/` da 12 productos | Solo vende combos "cambio de aceite + filtro" (Total Quartz 7000 10W-40 + filtro: 87923), no aceite suelto. Sirve como precio de servicio, no de producto |
| 9 | ENAUSA (distribuidor oficial YPF) | https://www.enausa.com.ar | 200. El sitemap tiene 156 URLs de lubricantes y el JSON-LD trae `offers` por presentación (YPF Elaion Auro D1 530 · Caja 4 x 4 L / 471300) | **No viable por términos.** El punto 3 dice "No publicamos precios en este sitio" (contradice el JSON-LD) y el punto 9 prohíbe reproducir contenidos con fines comerciales sin permiso escrito. Solo con autorización. Además es solo YPF |
| 10 | Lubricentro Máximo | https://www.lubricentromaximo.com.ar | 200. WooCommerce Store API, 53 productos | Solo baterías Moura y kits por modelo de auto, ningún aceite suelto |
| 11 | cambiodeaceite.com.ar (TotalEnergies) | https://www.cambiodeaceite.com.ar | 200 (PrestaShop) | Es reserva del servicio de cambio de aceite en lubricentros. La home no muestra precios y el sitemap dio 404. No seguí el flujo de reserva |
| 12 | Tuamoto Mayorista | https://tuamotomayoristas.com.ar | 200 | "La tienda fue momentáneamente suspendida" |
| 13 | Lubricentro CM | https://lubricentrocm.com.ar | 410 | Tienda dada de baja |
| 14 | Ditesac | https://ditesac.com | 403 "Just a moment..." (Cloudflare) | Desafío anti-bot: no lo evado. Parece ser de Perú (no lo confirmé) |
| 15 | compralubricantes.com | https://compralubricantes.com | 200 (PrestaShop) | Es de España (teléfono +34): fuera de alcance |
| 16 | Albano S.A.S. (distribuidor Shell, Paraná) | https://www.albanosas.com.ar | 200 | No muestra precios online (según la búsqueda; no lo probé más a fondo) |

**Notas para sumarlos al recolector**

- **Prioridad 1:** Norauto, fuente `vtex_norauto`, `fq=C:/3/20/`, 2 páginas. Entra al `recolectar.py` actual sin código nuevo, como un host más.
- **Prioridad 2:** D'Atri con Shopify `/products.json`, a 1 request por segundo. Hay que normalizar caja o tambor a litros.
- **Tiendanube** (LS Palermo, Casa González, Fercol): hace falta un lector nuevo con stdlib (sitemap, regex de aceite sobre la URL y `LS.variants` en el HTML). Es un request por producto: no repetirlo diario sobre las 6405 URLs de LS Palermo sin filtrar antes.
- **Sin probar:** el bloqueo desde IPs de GitHub Actions (todo se probó desde la PC) y si los precios de D'Atri incluyen IVA.


Sources:
- [Norauto Lubricentro](https://www.norauto.com.ar/lubricentro)
- [Daytona Lubricentro](https://www.daytona.com.ar/lubricentro)
- [Lubricentro DG](https://lubricentrodg.mitiendanube.com/)
- [Lubricentro CM](https://lubricentrocm.com.ar/)
- [Fercol Lubricantes](https://www.fercollubricantes.com.ar/)
- [Máximo Lubricentro](https://www.lubricentromaximo.com.ar/)
- [Tienda D'Atri](https://tiendadatri.com.ar/)
- [cambiodeaceite.com.ar](https://www.cambiodeaceite.com.ar/en/)
- [LS Palermo Elaion Auro](https://lspalermo.com.ar/productos/aceite-elaion-auro-5w30-sintetico-nafta-diesel-4-litros-ktsf9/)
- [Tienda Neumáticos Elaion Auro](https://www.tiendaneumaticos.com.ar/lubricentro/Elaion%20Auro?map=c%2CspecificationFilter_33)
- [ENAUSA Elaion Auro D1 530](https://www.enausa.com.ar/productos/lubricantes/elaion-auro-d1-530)
- [Allende Repuestos Elaion Auro](https://www.allenderepuestos.com.ar/producto/aceite-elaion-auro-5w30-sintetico-4l/)
- [Tuamoto Mayorista](https://tuamotomayoristas.com.ar/aceite/)
- [Ditesac](https://ditesac.com/c/lubricantes/)
- [Albano S.A.S.](https://www.albanosas.com.ar/)
- [Casa González Shell](https://spch.com.ar/catalogo/lubricantes1/marcas2/shell/)
- [compralubricantes.com](https://compralubricantes.com/72-shell)
- [16 Válvulas: tienda online de TOTAL](https://www.16valvulas.com.ar/?p=194037)

---

## Relevamiento: retail

Francisco —

**Respuesta a "¿por qué no usar catálogo?":** el catálogo (`/api/catalog_system/pub/products/search`) ya es lo que se usa. El problema no es la API sino lo que hay adentro. Lo volví a probar hoy, sitio por sitio, con `ft=` y `fq=` y un User-Agent honesto. Las únicas novedades son dos: Coto ahora sí tiene aceites con precio y EAN, y Frávega tiene una categoría de lubricantes que no sirve como referencia de precio.

| Sitio | URL real | Plataforma / endpoint | HTTP | ¿Lubricantes con precio, sin login? | Muestra real (marca / nombre / ARS) | robots.txt / términos | Veredicto |
|---|---|---|---|---|---|---|---|
| **Coto** | www.coto.com.ar | Oracle Endeca/ATG. Es la misma página de búsqueda con `format=json`: `/sitios/cdigi/browse?Ntt={q}&Nrpp=50&format=json`. No pide token. Trae `product.eanPrincipal`, `product.brand`, `sku.activePrice` | 200 | **Sí, unos 20 aceites de motor** (antes figuraban casi 0). Marcas: Total, Bardahl, Gulf. Elaion, Shell y Castrol: 0 | TOTAL / Aceite TOTAL Quartz 7000 10w-40 4 L / 64169 · GULF / Aceite para Motos Gulf Pride 4T Plus 20W-50 1 L / 12339 · TOTAL / Quartz Ineo Mc3 5w-30 4 L / 146309 | robots no prohíbe `/sitios/cdigi/browse`. Los términos no los leí | **Viable**, con dos dudas: `format=json` no es una API documentada (es la vista JSON de la página pública) y faltan los términos. Se cruza por EAN |
| Disco | www.disco.com.ar | VTEX catalog, `fq=C:/16/126/412/` | 206 | Hay 294 fichas y **0 con stock**. `ft=elaion` da 15 fichas y `castrol` 18, todas sin stock | WD-40 155 Gr / 9899 (el único lubricante con precio) | `/api` no está bloqueado | No viable: fichas muertas, igual que Jumbo. Probé `sc=1..8` y todas dan 400 "sc is inactive" |
| Vea | www.vea.com.ar | VTEX, igual que Disco | 206 | Igual: 294 fichas y 0 con stock | WD-40 155 Gr / 9890 | ídem | No viable (duplica a Jumbo) |
| Día | diaonline.supermercadosdia.com.ar | VTEX catalog | 200 | No. Con `ft=lubricante` solo aparecen afeitadoras | — | — | No vende aceites de motor |
| Cetrogar | www.cetrogar.com.ar | VTEX catalog | 200 `[]` | 0 en todas las búsquedas | — | — | No vende |
| Toledo | www.toledodigital.com.ar | VTEX catalog | 200 `[]` | 0 | — | — | No vende |
| Blaisten | www.blaisten.com.ar | VTEX catalog | 200 `[]` | 0 | — | — | No vende |
| Frávega | www.fravega.com | VTEX catalog, `fq=C:/1000928/1000534/1000541/` ("Aditivos y lubricantes") | 206, `resources 0-49/163` | Sí: 163 productos con precio, pero casi todo es de marketplace y en gran parte importado (vendedores Glic 89, Tienda Ferretera 48, nocnoc 22). Ni Elaion, ni Shell, ni Total | Generico / Aceite de Motor Valvoline Daily Protection 10W30 / 243695 (Glic) · Castrol / Transmax DEX/MERC ATF / 75105 (Glic) | `/api` no está bloqueado | Técnicamente viable, pero no sirve: precios de importación, no de góndola argentina |
| Sodimac | www.sodimac.com.ar | Falabella (Next.js, Cloudflare) | Home 200. `/sodimac-ar/buscar?Ntt=aceite+motor` redirige a 404 | No lo pude confirmar: WebSearch solo devolvió Sodimac Chile y Perú | — | robots no bloquea `/buscar` | No confirmado: no encontré catálogo de aceites en .com.ar |
| Hiper Libertad | www.hiperlibertad.com.ar | CloudFront | 403 (también el robots.txt) | — | — | — | No viable: bloqueado, no lo evadí |
| La Anónima | www.laanonima.com.ar | CloudFront | 403 (también el robots.txt) | — | — | — | No viable: bloqueado |
| Cooperativa Obrera | www.lacoopeencasa.coop | SPA en Apache, sin API pública conocida | 200 HTML | No confirmado. En SEPA tiene 0 aceites de motor | — | robots solo bloquea cuenta y carrito | No viable sin API interna |
| Yaguar | yaguar.com.ar | WooCommerce (Store API activa) | 200 | 0 resultados para "aceite motor", "lubricante" y "elaion" | — | robots: `User-agent: *` con `Disallow: /` + content-signals de Cloudflare | No viable: no vende y robots prohíbe |
| Diarco | www.diarco.com.ar | WooCommerce Store API `/wp-json/wc/store/v1/products?search=` | 200 | No: solo WD-40, con `price "0"` (mayorista, no publica precio) | Lubricante WD-40 155 Ml / 0 | robots estándar de WordPress | No viable |
| Makro | makro.com.ar | WordPress sin Store API | 404 `rest_no_route` | No encontré catálogo con precios | — | robots `Disallow:` vacío (no prohíbe nada) | No viable |
| Vital | www.vital.com.ar | WordPress sin Store API | 404 `rest_no_route` | No encontré catálogo con precios | — | robots `Disallow:` vacío (no prohíbe nada) | No viable |
| Megatone | www.megatone.net | Propia | Home 200. `/listado/?q=` y `/search/?q=` dan 404 | No encontré aceites (WebSearch tampoco) | — | robots: `allow /listado/ /producto/` y `disallow: /` | No viable / sin lubricantes |
| Musimundo | www.musimundo.com | SPA en S3 | 200; la búsqueda vuelve a la home | No | — | robots vacío | No viable |
| Walmart | www.walmart.com.ar | — | 000, no responde | — | — | — | Ya no existe. Es ChangoMás, ya cubierto |
| Mercado Libre Super | mercadolibre.com.ar/supermercado | — | 404 | — | — | Lo rige la regla del repo: sin scraping de ML | Ya cubierto por `ml` con token |

**Lo que sí se puede sumar:**
- **`coto` (Endeca JSON).** Bastan unas 6 búsquedas por día ("aceite motor", "total quartz", "bardahl", "gulf", "elaion", "shell") filtrando aceites de motor. Se cruza por `eanPrincipal`. Aporta Total, Bardahl y Gulf con precio de góndola.
- **Antes de activarlo hay que leer los términos de uso de Coto.** No los revisé.

**Lo que no se probó:** los términos de uso de cada sitio, y si Sodimac AR tiene una categoría de automotor en otra URL.


Sources:
- [sodimac.cl aceites y lubricantes](https://www.sodimac.cl/sodimac-cl/category/scat652323/aceites-y-lubricantes-para-autos)
- [sodimac.com.pe aceite para motor](https://www.sodimac.com.pe/sodimac-pe/lista/CATG14284/Aceite-para-motor)
- [Easy Elaion F30 4 L](https://www.easy.com.ar/lubricante-elaion-f30-10w40-ts-1040-x-4/p)
- [mejorescompras Elaion 10W40](https://mejorescompras.com.ar/precio/MLA27257458--aceite-ypf-elaion-10w40-ts-1040-semisintetico-x-4l-ex-f30)