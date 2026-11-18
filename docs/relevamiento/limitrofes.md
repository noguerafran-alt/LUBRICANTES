# Países limítrofes: de dónde sacar precios (relevamiento 2026-11-18)

Países: Chile (CL), Uruguay (UY), Paraguay (PY), Bolivia (BO) y Brasil (BR). Todo se probó con curl el 2026-11-18, desde la PC y con
User-Agent honesto (`LUBRICANTES-relevamiento/1.0`), a ~1 req/s por host. Cada fuente la relevó un agente y la volvió a probar otro,
que repitió los curl sin mirar los del primero. Cuando no coincidieron, vale lo de la segunda pasada y se anota la corrección. No se
probó nada desde IPs de GitHub Actions. No se tocó código ni `data/`.

Resumen en una línea por país:
- **Brasil** es el único con fuentes automatizables que traen YPF (Elaion) con EAN, más un equivalente estadual de SEPA (Nota Paraná).
- **Chile** tiene competencia con precio por API (WooCommerce), pero en ninguna tienda online apareció YPF.
- **Uruguay** tiene YPF con precio (distribuidor Benco, en USD), pero solo en HTML. ML (MLU) es chico.
- **Paraguay y Bolivia**: casi no hay e-commerce de lubricantes. ML existe, pero tiene 0 avisos de lubricantes. En Bolivia lo que se vende es
  **YPFB** (la petrolera estatal boliviana), que no es YPF.

## 1. Mercado Libre por país (sin token)

| País | Sitio (`/sites`) | `/sites/{X}` | Categoría "Para Motor" (`domain_discovery`) | `total_items` | search / products sin token |
|---|---|---|---|---|---|
| Chile | MLC, CLP | 200 · `sale_fees_mode` not_free · `mercadopago_version` 3 | MLC161667 (MLC-ENGINE_OILS) | **83.279** | 403 / 403 PolicyAgent |
| Uruguay | MLU, UYU | 200 · not_free · 3 | MLU431495 | **2.426** | 403 / 403 |
| Paraguay | MPY, PYG | 200 · **free · null** | MPY452953 | **0** | 403 / 403 |
| Bolivia | MBO, BOB | 200 · **free · null** | MBO375007 | **0** | 403 / 403 |
| Brasil | MLB, BRL | 200 · not_free · 3 | MLB194027 (Óleos de Motor) | **73.115** | 403 / 403 |

- `GET https://api.mercadolibre.com/sites` dio 200 y lista los cinco sitios (más MLA y otros 13).
- El 0 de Paraguay y Bolivia no es un filtro mal puesto. Se recorrió el árbol hacia arriba:
  - `MPY456111` Lubricantes y Fluidos tiene 0 ítems y todas sus hijas también. `MPY1747` Accesorios para Vehículos tiene **91** ítems en total.
  - `MBO456111` también tiene 0. `MBO1747` tiene **20** ítems en total.
- Los dos tienen `sale_fees_mode: free` y no tienen Mercado Pago. *Inferido, no verificado:* operan como sitios de clasificados sin
  checkout, y por eso casi no hay oferta.
- `domain_discovery` y `/categories/{id}` responden 200 sin token en los cinco sitios. Igual que en MLA, sirven como métrica diaria de
  oferta, como hoy hace `data/ml_oferta.csv`.
- Lo que tiene precio (`/sites/{X}/search`, `/products/search`, `/products/{id}/items`) pide token en los cinco sitios: 403
  `PA_UNAUTHORIZED_RESULT_FROM_POLICIES`. Es el mismo comportamiento que en MLA (ver `mercadolibre.md`). `/sites/{X}/categories` también da 403.

### Cómo probar el token en otros sitios (no se hizo)

No se probó. No está verificado que la app registrada en MLA pueda leer MLC, MLU o MLB: las apps de ML se dan de alta por país y
puede hacer falta una app por sitio.

La prueba tiene que correr **en la Action**, nunca en la PC. El refresh token rota en cada canje y solo vale el último.

- **Riesgo:** un paso de prueba que haga su propio canje y no guarde el refresh nuevo deja sin ML a la recolección diaria.
- **Receta:**
  1. Reusar el access token que el paso `ml` ya obtuvo en esa corrida.
  2. Correr la prueba en un paso posterior a "Rotar refresh token ML", solo con `workflow_dispatch`.
  3. Pedir `/products/search?status=active&site_id=MLC&q=helix` (y lo mismo con MLU y MLB), y después `/products/{id}/items` de un
     resultado.
  4. Registrar el HTTP de cada uno en el log. No escribir nada en `data/`.
- **Si da 403:** hace falta una app por país. Es un alta manual del usuario en el portal de developers de cada sitio y suma secrets
  `ML_*_MLC` y `ML_*_MLB`. En ese caso, comparar el costo contra las tiendas de abajo, que no piden token.

## 2. Fuentes por país

Veredictos posibles:
- `automatizable`: API JSON sin token, robots no bloquea y no se halló cláusula que lo prohíba.
- `grok/manual`: con precio, pero solo en HTML, o sin términos legibles.
- `descartada`: con el motivo.

"Términos no encontrados" **no** es lo mismo que "permitido". Lo único que significa es que no hay una cláusula que los prohíba.

### Brasil (BRL) — YPF se vende como Elaion, con EAN 789… (distintos de los argentinos)

| Fuente | Endpoint probado | HTTP | Ejemplo real | robots / términos | Veredicto |
|---|---|---|---|---|---|
| **Pitstop** (VTEX) | `https://www.pitstop.com.br/api/catalog_system/pub/products/search?ft=elaion&_from=0&_to=49` | 200 JSON | Elaion F50J 5W30 1 L **R$ 64,70**, EAN 7898245572580. Elaion 20W50 1 L R$ 30,90, EAN 7898245572511. Mobil 1 FS 0W40 1 L R$ 123,70. Lubrax Valora 5W30 1 L R$ 68,63 | Un solo grupo de robots, para `*` y bots de IA, con `Allow: /`. No bloquea `/api`. No tiene página de Termos de Uso. La política de privacidad no menciona robôs ni extração | **automatizable**. Excluir stock 0 y precios anómalos: Elaion 0W20 a R$ 782,10 y 10W30 "1L" a R$ 638,20 parecen cajas. La categoría `fq=C:9317` da `[]`: barrer por `ft=` |
| **Altese** (VTEX) | `https://www.altese.com.br/api/catalog_system/pub/products/search?ft=oleo%20shell&_from=0&_to=49` (igual con castrol, mobil, motul, total, texaco, ipiranga, selenia, lubrax, elaion) | 200 JSON | Shell Helix HX8 5W30 1 L **R$ 44,50**, EAN 5011987272620. Lubrax Top Auto 5W30 1 L R$ 42,90. Selenia Perform 5W30 1 L R$ 47,90. Elaion F50J 5W30 R$ 26,50, **stock 0** | Solo `User-agent: *`. No bloquea `/api`. Sin Termos de Uso; la privacidad no tiene cláusula | **automatizable**, para la competencia: Castrol 28, Motul 28, Total 22, Shell 18, Texaco 18, Ipiranga 16, Mobil 12, Petronas 10, Lubrax 7. YPF: 1 SKU sin stock |
| **Autoz** (VTEX) | `https://www.autoz.com.br/api/catalog_system/pub/products/search?ft=oleo%20motor%205w30&_from=0&_to=11` | 206 JSON | BProauto 5W30 SP 1 L R$ 33,90 | No bloquea `/api`. Términos no leídos | automatizable, **baja prioridad**: sin YPF ni majors, y un mismo EAN se repite en dos SKU |
| Americanas (VTEX) | `https://www.americanas.com.br/api/catalog_system/pub/products/search?ft=elaion&_from=0&_to=19` | 206 JSON | 20 ítems Elaion con EAN (ej. FS 530 5W30, 7898920510784), todos `Price 0` y stock 0 | Bloquea GPTBot, CCBot y Google-Extended (no a `*`). Los términos (`/especial/termos-e-condicoes`, versión 2/2025) no prohíben robots ni extracción | **descartada para precios**. Sirve para cruzar EAN de Elaion BR |
| **Menor Preço / Nota Paraná** (oficial, estadual) | `https://menorpreco.notaparana.pr.gov.br/api/v1/produtos?termo=elaion&offset=0&raio=100&data=-1&ordem=0&gtin=0&local=6gkzmg1v4` | 200 JSON | "OLEO WURTH ELAION F50J 1L", GTIN 07898245572054, **R$ 49,90**, 2026-11-17, Auto Posto Pedrazzoli (Curitiba), NCM 27101932. `total` 65 para "elaion" | Sin robots (404) y sin términos publicados (`/termos` 404). Es una API interna del sitio, no documentada | **automatizable con cautela**. Ver §3 |
| Lojadomecanico, Grupo Celinho, Conexão Brasil | HTML | 200/302 | Precios de Elaion vistos solo en buscador web | Sin API | grok/manual |
| Carrefour BR, Casas Bahia, Ponto, Extra, Magalu, Leroy Merlin, Autozone, PneuStore, Mercadocar y otros | `/api/catalog_system/...` o `robots.txt` | 403 | — | Anti-bot | descartada: no se evade |
| Telhanorte, Cobasi, Obramax, Sam's Club, Super Muffato, Tumelero | VTEX | 200/206 | Sin aceite de motor automotriz | — | descartada |

Ninguna tienda de autopeças brasileña expuso Shopify, Nuvemshop o WooCommerce: se probaron unos 25 hosts. La búsqueda de dominios fue
incompleta, así que pueden existir más.

### Chile (CLP) — YPF no aparece en tiendas online

Hay presencia de YPF Chile: La Tercera, 2022-04-25, ["YPF presenta Elaion Auro en Chile"](https://www.latercera.com/mtonline/noticia/ypf-presenta-elaion-auro-en-chile-nuevo-lubricante-para-vehiculos-premium/TQV4RLVVKZCVDEV6Y37NTBKGYE/).
Sin embargo, se buscó ypf/elaion en las tiendas de abajo y en todas dio **0**. Lo que se revisó: 542 resultados de Sodimac (página 1),
424 de Insumotor, 46 de Autopartes Santiago y SP Trade. Esto cubre solo lo muestreado; no es un censo.

| Fuente | Endpoint probado | HTTP | Ejemplo real | robots / términos | Veredicto |
|---|---|---|---|---|---|
| **SP Trade** (WooCommerce) | `https://sptrade.cl/wp-json/wc/store/v1/products?search=aceite&per_page=100` | 200, 100 ítems | Castrol Edge 5W30 4 L **CLP 54.900** (sku 1036382). Castrol Magnatec 10W40 4 L CLP 39.900. Mobil Super 3000 XE 1 L CLP 11.900 | robots no bloquea `/wp-json`. Los [términos](https://sptrade.cl/terminos-y-condiciones/) no hablan de extracción: el "uso no autorizado" se refiere a software y diseño | **automatizable**. Sin EAN; litros en el nombre. El Mobil 3000 XE 4 L aparece dos veces (39.990 y 49.990): deduplicar |
| **Autopartes Santiago** (WooCommerce) | `https://www.autopartessantiago.cl/wp-json/wc/store/v1/products?search=aceite&per_page=100` | 200, 46 ítems | Shell Helix HX7 **CLP 25.900**. Petronas Syntium 5000 XS CLP 43.900. Mobil 1 ESP CLP 53.900 | robots no bloquea `/wp-json`. No hay términos publicados (404, y la home no los enlaza) | **automatizable**. Litros solo en el slug y sin sku: matcheo difícil |
| Sodimac CL | `https://www.sodimac.cl/sodimac-cl/b/aceite-5w30` (HTML SSR, JSON-LD) | 200 | Shell Helix HX8 5W30 4 L CLP 55.990. Mobil Super 3000 XE 4 L CLP 51.690 | robots bloquea `?Ntt=` y `/buscar/`, no `/b/` ni `/lista/`. Los términos cargan por JS: **no leídos** | grok/manual |
| Falabella CL | `https://www.falabella.com/falabella-cl/shop/aceite-5w30` | 200 (403 en `Ntt=elaion`) | Shell Helix HX8 5W30 4 L CLP 55.990 | robots abierto. Términos por JS: no leídos | grok/manual |
| Easy CL | ficha `https://www.easy.cl/aceite-sintetico-4-litros-5w-30-mobil-1241227/p` | 200 | Mobil 5W-30 4 L CLP 61.990, **EAN 7806358010943** | Sin API: `/api/catalog_system` da 404. Términos por JS | grok/manual (solo fichas sueltas) |
| Insumotor (Shopify) | `https://insumotor.com/collections/aceite-motor/products.json?limit=250` | 200, 424 productos | Shell Helix HX7 10W40 4 L CLP 33.490 | [Términos](https://insumotor.com/policies/terms-of-service): "Ningún producto, imagen o sonido pueden ser reproducidos, duplicados, copiados, vendidos, revendidos, visitados o explotados para ningún fin… sin el consentimiento escrito previo" | **descartada por términos**. Se podría pedir el consentimiento |
| Lider (Walmart) | `robots.txt` | 200 | — | Bloquea `/catalogo/product*` y `/search*` | descartada |
| Jumbo / Santa Isabel | `/api/catalog_system/...` | 200 HTML (no JSON) | — | Santa Isabel: `Disallow: /api/` | descartada |
| Ripley | `robots.txt` | 403 | — | Anti-bot | descartada |
| Autoplanet, Copec, Mundo Repuestos | — | 200 SPA / 000 | — | — | no probado a fondo (ver §6) |

### Uruguay (UYU, y USD en distribuidores)

| Fuente | Endpoint probado | HTTP | Ejemplo real | robots / términos | Veredicto |
|---|---|---|---|---|---|
| **Benco S.A.** (distribuidor YPF; plataforma Luna) | `https://benco.com.uy/p/elaion-f30-10w40/126/166` (listado: `/lubricantes-/lubricantes-de-carter-automotrices-/1`, 30 Elaion) | 200 | Elaion F30 10W40: 1 L **USD 16** · 4 L USD 63 · 20 L USD 298 · 205 L USD 2.931. El mapa sku→litros se verificó por `data-spec-id`. Sin EAN | robots `Disallow:` vacío. La página de términos responde 200 pero viene sin texto legal | grok/manual (HTML con JSON embebido, parseable). **Precio en USD**: va con `moneda=USD`, no se convierte a UYU |
| **Feyvi** (repuestos Chevrolet; CS-Cart) | `https://www.feyvi.com.uy/repuestos/mantenimiento-y-estetica-automotriz/aceites-lubricantes/?items_per_page=96` | 200 | Elaion mineral 15W40 4 L **UYU 2.537**, brand YPF en JSON-LD. Shell 10W40 4 L UYU 3.324 (la marca sale del slug). Syntium 5W40 4 L UYU 2.390 | robots abierto. Las [condiciones](https://www.feyvi.com.uy/condiciones-de-uso/) solo prohíben crear enlaces sin autorización y reservan los derechos; nada sobre extracción | grok/manual: es la única fuente con YPF y competencia en UYU, pero solo en HTML |
| Repuestos Avenida (Chuy) | ficha Castrol Magnatec 5W40 kit 4 L | 200 | UYU 4.202 | robots bloquea `/api/`. Los términos no prohíben | grok/manual (una sola ficha verificada) |
| Sodimac UY | `/sodimac-uy/search?Ntt=lubricante` | 200 | Ancap Súper-A 20W50 4 L UYU 1.986 | robots **prohíbe** `?Ntt=` y `/search` para `*`. El Allow a ClaudeBot no aplica a nuestro UA | descartada. Sin YPF |
| Maquinaria UY (WooCommerce) | `https://maquinaria.com.uy/wp-json/wc/store/v1/products?search=rimula&per_page=100` | 200 | Shell Rimula R4 X 15W40 USD 176 (balde, litros no declarados) | robots no bloquea `/wp-json` | descartada: solo pesado y sin YPF |
| Tata (VTEX `tatauy`) | `https://tatauy.vtexcommercestable.com.br/api/catalog_system/pub/products/search?ft=lubricante` | 200 `[]` | No vende aceite de motor | — | descartada |
| Disco / Devoto / Géant | `/api/catalog_system/...` | 404 (Blazor Server, no es VTEX) | — | — | descartada |
| Tienda Inglesa | `/supermercado` | 403 | — | Anti-bot | descartada |

### Paraguay (PYG)

YPF está presente: [CGS](https://www.cgs.com.py/portfolio.html) (200) se presenta como "Representante Oficial de YPF en Paraguay", con Elaion,
Extravida y Elaion Moto. No tiene tienda online. **Ninguna fuente publica precio de YPF.**

| Fuente | Endpoint probado | HTTP | Ejemplo real | robots / términos | Veredicto |
|---|---|---|---|---|---|
| Chacomer (Magento) | `https://www.chacomer.com.py/auto/lubricantes.html` | 200 (REST 401, GraphQL 403) | Elf Evolution 700 FTX 5W30 4 L **Gs 180.100** (lista 275.700). Gulf Multi G 20W50 4 L Gs 112.795 (por envase, no por caja) | robots bloquea `/*?`, así que no se puede paginar ni buscar. Los términos no prohíben | grok/manual: una sola página con 36 ítems, Elf, Power Line y Gulf |
| Electro Diesel (HTML) | `https://www.electrodiesel.com.py/productos?s=aceite+para+motor&page=1` | 200 | Valvoline Advanced 5W30 1 qt Gs 106.000 | robots vacío. No hay términos (solo `/privacidad`, sin cláusula) | automatizable por HTML, pero **inútil**: solo Valvoline, Ravenol y Coastal. Sin YPF ni majors |
| Investigaciones Agropecuarias (WooCommerce) | `https://investigacionesagropecuarias.com.py/wp-json/wc/store/v1/products?per_page=100` | 200, 282 productos | Los 282 con precio 0 (incluye YPF Extravida XV300 15W-40) | robots abierto | descartada: sin precios |
| Liqui Moly PY, Rogaguazú (WooCommerce) | `/wp-json/wc/store/v1/products` | 200 | Precio 0 / "Consultar precio" | — | descartada |
| Porter | `robots.txt` | 403 (Cloudflare) | — | Anti-bot | descartada |
| Superseis, Casa Rica, Tupí, Stock, Biggie, Nissei, Salemma, Shopping China | varios | 200/404 | Sin aceite de motor o sin API. Nissei bloquea `/catalogsearch/` | — | descartada |

### Bolivia (BOB)

No hay evidencia de que YPF (Argentina) se venda en Bolivia. Lo que se vende es **YPFB**, otra empresa. Si algún día se suma, YPFB va
como marca aparte y nunca se mezcla con YPF.

| Fuente | Endpoint probado | HTTP | Ejemplo real | robots / términos | Veredicto |
|---|---|---|---|---|---|
| Lubricruz (distribuidor YPFB; WooCommerce) | `https://www.lubricruz.com/wp-json/wc/store/v1/products?per_page=100&page=1` | 200, X-WP-Total 101 | YPFB GX Extra 20W50 caja 12×1 L **Bs 506**. DX Turbo 15W40 balde 20 L Bs 850 | robots no bloquea `/wp-json`. No hay términos publicados | automatizable, pero **fuera de alcance**: solo YPFB y en presentaciones mayoristas. No se sabe si incluye IVA |
| Multicenter (VTEX multipaís) | `https://www.multicenter.com/api/catalog_system/pub/products/search?ft=aceite` | 200 | Sin aceite de motor | [Términos](https://www.multicenter.com/terminos-y-condiciones): "Queda prohibido cualquier uso comercial… de cualesquiera contenidos incluidos en el Sitio… sin autorización previa" | descartada |
| Fidalga, Farmacorp (Shopify) | `/search/suggest.json?q=lubricante` | 200 | Sin aceite de motor | Farmacorp: el robots trae texto dirigido a agentes de IA, tratado como dato y no seguido | descartada |
| Imcruz (distribuidor Shell) | `/wp-json/wc/store/v1/products` | 404 | — | robots bloquea a ClaudeBot y GPTBot; `ai-train=no` | descartada |
| Hipermaxi | `/` | 302 a un challenge de Radware | — | Anti-bot | descartada |

## 3. Equivalente de SEPA

| País | Sistema | Prueba | ¿Cubre lubricantes? |
|---|---|---|---|
| Brasil | **Menor Preço / Nota Paraná** (Sefaz-PR; precios sacados de notas fiscales, por establecimiento) | API de la tabla de §2, 200 JSON sin token. Campos `desc, gtin, valor, datahora, estabelecimento, ncm`. Hace falta `local` (geohash) y `raio` (≤100 km probado) | **Sí**, por NCM 27101932: 65 filas Elaion con fechas del 2026-11-05 al 2026-11-18. **Solo Paraná.** Mezcla precios de distribuidor (cajas 12X1 sin GTIN, ej. FLEX COMERCIO) con precios de posto o taller: filtrar por GTIN no vacío. Sin términos ni robots publicados. Un Acórdão TCE-PR 706/19 menciona límites de uso (no leído) |
| Brasil (nacional) | ANP Levantamento de Preços | [Página](https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas) 200. El xlsx dio 403 al HEAD | No: es de combustibles, según la página. El archivo no se inspeccionó |
| Uruguay | **SIPC** (MEF / Defensa del Consumidor), [precios.uy](https://www.precios.uy/) y CKAN [catalogodatos.gub.uy](https://catalogodatos.gub.uy/dataset/c2edcd30-8a99-45da-b208-b76056de430e), licencia odc-uy | `productos.csv` 2026, 200, 379 filas | **No.** El único "aceite" es comestible. `lubric`/`motor`/`nafta` = 0 en 2026 y en 2025. `package_search?q=lubricantes` → count 0 |
| Chile | — | No se hicieron requests a CNE ni SERNAC | No verificado. No se conoce ninguno |
| Paraguay | datos.gov.py, SEDECO | `datos.gov.py/api/3/action/package_search?q=precios` 200, pero en "Mantenimiento". SEDECO 301 → 200, sin sección de precios | No. La canasta de SEDECO es de alimentos (dato de prensa, no verificado) |
| Bolivia | ANH, Defensoría del Pueblo | Solo búsqueda web | No verificado: la ANH regula combustibles y los sondeos de la Defensoría son de consumo general (PDF no abierto) |

## 4. Tipo de cambio diario y gratuito (moneda local → USD)

El repo ya tiene **ARS por USD**: `92.2_TIPO_CAMBIION_0_0_21_24` (BCRA vía datos.gob.ar) en `data/macro/series.csv`. La conversión
para mostrar pasa por USD: local → USD con la fuente de abajo, y USD → ARS con la serie existente.

| Moneda | Fuente oficial | Prueba (2026-11-18) | Registro | Notas |
|---|---|---|---|---|
| BRL | BCB PTAX, OData Olinda | `https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)?@dataInicial='11-10-2026'&@dataFinalCotacao='11-18-2026'&$format=json` → 200. 2026-11-17: venta **5,78510** | No | Fecha en MM-DD-AAAA. Publica los días hábiles después de las 13 h |
| UYU | BCU, web service SOAP | POST `https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/awsbcucotizaciones` (WSDL 200), moneda 2225 (dólar billete) → 200. 2026-11-17: **40,578** | No | Un día hábil de rezago. No se probó la 2224 (interbancario) |
| PYG | BCP, planilla HTML | `https://www.bcp.gov.py/webapps/web/cotizacion/monedas` → 200, "al martes 17 de noviembre del 2026": **6.272,50** Gs/USD | No | Hay que parsear HTML. La home y el `robots.txt` del BCP dan **403 con challenge de Cloudflare**: riesgo de que el job diario se caiga |
| BOB | BCB Bolivia, portada | `https://www.bcb.gob.bo/` → 200, "miércoles 18 de noviembre, 2026, Bs 11,75" | No | El valor está escrito a mano en el HTML ("tipo de cambio oficial quemado"). Ya no rige la paridad 6,96 |
| CLP | Banco Central de Chile, API BDE `si3.bcentral.cl/SieteRestWS/...` serie `F073.TCO.PRE.Z.D` | 200 con `{"Codigo":-5,"Descripcion":"Invalid username or password"}` | **Sí: usuario y clave gratuitos** (va como secret de la Action) | CMF pide apikey (421). `mindicador.cl` no respondió (000) |

**Alternativas no oficiales** (solo si la oficial falla; se rotulan "no oficial"):
- **ExchangeRate-API**: `https://open.er-api.com/v6/latest/USD` dio 200 (CLP 998,56; BOB 11,66). Sus [términos](https://www.exchangerate-api.com/terms)
  **prohíben redistribuir** los datos y usarlos en un servicio que dé acceso programático a tipos de cambio. Exponerlos por `/api/*`
  quedaría fuera.
- **fawazahmed0/currency-api**: `https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json` dio 200 (CLP 994,19;
  BOB 11,68). Licencia no leída.

## 5. Esquema propuesto (no implementado)

Regla: **nunca se mezclan monedas ni países**. Un precio se guarda en la moneda en que se publicó. La conversión existe solo en el
visor y siempre muestra la fecha del tipo de cambio.

- **`data/obs/AAAA-MM.csv`** y **`data/grok/`**: sumar dos columnas al final, `pais,moneda`.
  - `pais` va en ISO 3166-1 alfa-2 (`AR, CL, UY, PY, BO, BR`) y `moneda` en ISO 4217 (`ARS, CLP, UYU, PYG, BOB, BRL, USD`).
  - En las filas viejas quedan vacías y se leen como `AR`/`ARS`. Es el mismo patrón que `n_descartados` y `provincia`.
  - `provincia` sigue siendo ISO 3166-2:AR. En otro país va vacía, o con su subdivisión ISO si la fuente la da (ej. `BR-PR` para Nota Paraná).
- **`moneda` es la de la publicación, no la del país.** Benco publica en USD en Uruguay: va como `pais=UY, moneda=USD`.
- **`data/fx.csv`** (nuevo): `fecha,moneda,por_usd,fuente`.
  - Una fila por moneda y día hábil publicado.
  - Día sin cotización = no hay fila. No se arrastra el valor anterior, igual que `precio_usd` en `/api/mercado`.
  - ARS no se duplica: sale de `data/macro/series.csv`.
  - Una fuente no oficial lleva `fuente=` con su nombre y el visor la rotula.
- **API**:
  - `/api/indice`, `/api/vitrina`, `/api/reventa` y el comparador filtran `pais=AR` por defecto. `?pais=BR` muestra otro país, siempre
    en su moneda.
  - **El índice YPF = 100 se calcula solo dentro de un país, nunca entre países.** Los impuestos al consumidor (IVA, ICMS en Brasil,
    IMESI en Uruguay), los envases y los canales cambian por país.
  - Toda comparación entre países es en USD, con `fx_fecha`, y se rotula "conversión al tipo de cambio oficial del día X, solo
    referencia".
- **`fuentes.csv`**: sin cambios de esquema. El nombre de la fuente lleva el país, ej. `vtex_br_pitstop`, `woo_cl_sptrade`, `oficial_br_notaparana`.
- **Seed**: los EAN de Elaion en Brasil (789…) son distintos de los argentinos. Van como alias nuevos del mismo `producto_id` si el
  producto es el mismo, y eso se verifica con la ficha técnica, no se adivina. YPFB no es YPF: si alguna vez entra, es marca aparte.
- Fuera del mismo commit: la regla "Solo se recolecta lo relacionado con YPF" sigue igual. Para cargar Ipiranga, Lubrax o Texaco de Brasil,
  primero hay que darlos de alta en el seed con su equivalencia.

## 6. Qué no se probó

- El token de ML en MLC, MLU y MLB (§1).
- Términos de uso de Sodimac CL, Falabella y Easy CL: cargan por JS y no se leyeron. Autoplanet, Copec y Mundo Repuestos, lubricentros
  chilenos en Jumpseller o Tiendanube, Ancap/Ducsa, Bartl y Macromercado (UY).
- Preço da Hora (Bahía) en profundidad y el xlsx de la ANP.
- Licencias del BCU, BCP, BCB Bolivia y fawazahmed0. El robots del BCP (403).
- Si los precios de Lubricruz y Benco incluyen IVA.
- Nota Paraná fuera de Curitiba (geohash `6gkzmg1v4`).
- Si YPF Chile vende hoy en Chile: la nota de 2022 y un título de Lubes'n'Greases sobre venta de unidades en Brasil y Chile no se pudieron leer.

## 7. Tabla final: qué se puede automatizar

| País | Fuente | Trae YPF | Moneda | Automatizable | Por qué |
|---|---|---|---|---|---|
| BR | Pitstop (VTEX) | **Sí** (Elaion, EAN) | BRL | **Sí** | API pública, robots abierto, sin cláusula en contra. Filtrar stock 0 y precios de lote |
| BR | Altese (VTEX) | 1 SKU sin stock | BRL | **Sí** | Ídem. La más completa en competencia |
| BR | Menor Preço / Nota Paraná | **Sí** (65 filas) | BRL | **Con cautela** | API interna no documentada, sin términos publicados. Solo Paraná. Filtrar GTIN y NCM 27101932 |
| BR | Autoz (VTEX) | No | BRL | Sí, baja prioridad | Sin majors; EAN duplicados |
| BR | Americanas (VTEX) | Sí, sin precio | — | No (precios) | Price 0 en todo. Solo para cruzar EAN |
| CL | SP Trade (WooCommerce) | No | CLP | **Sí** | Store API pública; los términos no lo prohíben |
| CL | Autopartes Santiago (WooCommerce) | No | CLP | **Sí** | Store API pública; sin términos publicados |
| CL / UY / BR | Mercado Libre (MLC, MLU, MLB) | a verificar | local | **Con token, a verificar** | Sin token, 403. Probar la app MLA en la Action (§1). El scraping está descartado siempre (ToS 7.5/7.6) |
| CL / UY / PY / BO / BR | ML categorías (`total_items`) | — | — | **Sí, sin token** | Métrica de oferta, como `ml_oferta.csv`. PY y BO dan 0 |
| CL | Sodimac, Falabella, Easy | No | CLP | No (grok/manual) | Sin API; términos por JS, no leídos |
| UY | Benco (distribuidor YPF) | **Sí** | USD | No (grok/manual) | Solo HTML; términos sin texto |
| UY | Feyvi | **Sí** + Shell/Petronas | UYU | No (grok/manual) | Solo HTML (CS-Cart) |
| PY | Chacomer | No | PYG | No (grok/manual) | robots impide paginar |
| PY | Electro Diesel | No | PYG | Técnicamente sí, sin valor | Solo marcas de nicho |
| BO | Lubricruz | YPFB (≠ YPF) | BOB | Fuera de alcance | Solo YPFB mayorista |
| CL | Insumotor | No | CLP | **No** | Los términos prohíben copiar o explotar sin consentimiento escrito |
| UY | Sodimac UY | No | UYU | **No** | robots prohíbe la búsqueda |
| BO | Multicenter | No | — | **No** | Los términos prohíben el uso comercial; además no vende aceite |
| todos | Tiendas con 403 / challenge (Carrefour BR, Magalu, Ripley, Tienda Inglesa, Porter, Hipermaxi, etc.) | — | — | **No** | Anti-bot: no se evade |
| UY / PY / BO / CL | SEPA-equivalente | — | — | No existe o no cubre lubricantes | SIPC (UY) verificado sin lubricantes; PY, BO y CL sin sistema verificado |

**FX automatizable**: BRL (PTAX), UYU (BCU SOAP), BOB (HTML del BCB) y PYG (HTML del BCP, con riesgo de Cloudflare), todas sin registro.
CLP pide un usuario BDE gratuito, que va como secret.

**Recomendación**: si se avanza, empezar por Brasil. Pitstop + Altese + Nota Paraná + PTAX dan YPF y competencia con EAN y fuente
oficial de FX. Chile entra con las dos WooCommerce, pero sin YPF no hay índice posible. Uruguay solo vía Grok (Benco y Feyvi).
Paraguay y Bolivia no tienen hoy fuente útil.
