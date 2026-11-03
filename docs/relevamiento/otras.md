
FUENTES_PRECIOS_LUBRICANTES_AR (probadas con curl desde esta PC el 2026-11-03, con UA de Chrome y sin token)

## 1. VTEX catalog_system (API pública, JSON)
Endpoint base: `https://{host}/api/catalog_system/pub/products/search?{ft=texto | fq=C:/id/id/id/}&_from=N&_to=N+49`
- Paginación: 50 por página como máximo. El header `resources: a-b/TOTAL` trae el total. VTEX corta alrededor de `_from` 2500 (no lo probé acá).
- Campos útiles: `brand`, `productName`, `categories[0]`, `categoriesIds`, `items[0].ean`, `items[0].sellers[0].commertialOffer.{Price, ListPrice, AvailableQuantity}`, `sellers[].sellerName`.
- Regla de limpieza (vista en los datos): cuando `AvailableQuantity=0`, `Price` sale en 0 o con basura (Jumbo: 66.29 contra un ListPrice de 5479). En Cencosud el `ListPrice` viene inflado unas 82 veces en productos que sí tienen stock (WD-40: Price 15199, ListPrice 1256116). Usar solo `Price` y solo si hay stock.
- Alternativa: `/api/io/_v/api/intelligent-search/product_search/?query=X&count=N` responde 200 en Carrefour, Día y Cetrogar, pero es difusa y trae productos que no corresponden.

| Comercio | host | HTTP | Filtro de lubricantes | Total en la categoría | Muestra (marca / nombre / precio ARS / stock) | Marcas que aparecen | Notas |
|---|---|---|---|---|---|---|---|
| Carrefour | www.carrefour.com.ar | 206 | `fq=C:/635/640/642/` (Automotor/Todo para el auto/Lubricantes y aditivos) | 185 | Elaion / Aceite Elaion ts 1040 x 1 lt / 24999 / 10 | Total, Gulf, Elaion, Loctite, Carrefour | Detrás de Cloudflare (CF-RAY), con riesgo de bloqueo a IPs de nube. Con `ft=shell helix` y `ft=castrol` da 0. |
| Jumbo | www.jumbo.com.ar | 206 | `fq=C:/16/126/412/` (Hogar y textil/Automotor/Lubricantes y Refrigerantes). Hay otro árbol, 578 (Tiempo Libre/Automotor), que dio 0 con fq. | 224 | YPF / Lubricante Elaion Ultra 10w / sin stock | YPF, Castrol, Shell, Pennzoil, WD-40 | Mucho producto sin stock y con precio basura. Nginx de VTEX. |
| Disco | www.disco.com.ar | 206 | igual que Jumbo (Cencosud) | ~igual | SHELL / Aceite Lubricante Shell Helix X 4 Lts. / 0 / 0 | ídem | Catálogo y precios iguales a Jumbo/Vea: tomar uno solo de los tres. |
| Vea | www.vea.com.ar | 206 | igual que Jumbo | ~igual | ídem | ídem | ídem |
| Easy | www.easy.com.ar | 206 | `fq=C:/9/68/321/` (Automotor/Aditivos y Lubricantes/Aceites y Lubricantes) | 48 | YPF / Lubricante Semisintético 10W40 4 Lts YPF Elaion / 100350 / 10 | Goodyear, Bardahl, YPF, Elf, Total, WD-40 | Su robots.txt bloquea `?map=category` y `/p?idsku`, no `/api`. |
| ChangoMás (MásOnline, Walmart AR) | www.masonline.com.ar | 206 | `fq=C:/1000039/2000174/3000496/` | 61 | Elaion Ypf / Lubricante Ypf Elaion Mi 1540 4l / 79999 / 100 | Elaion/YPF, TotalEnergies, Puma, Elf, Spirit, Bardahl | walmart.com.ar no responde (000). changomas.com.ar redirige (301). |
| Frávega | www.fravega.com | 206/200 | `ft=aceite lubricante` da 13 resultados (Lusqtoff, Konan: aceite 2T de herramientas) | 13 | Aceite Lubricante Motores 2t 200cc / 1605 / vendedor FILHOS SRL | — | Es marketplace. `ft=elaion` da 0. La búsqueda web mostró páginas de Shell Helix "no disponible para tu ubicación". Cobertura baja. |
| Día | diaonline.supermercadosdia.com.ar | 200 `[]` | — | 0 | — | — | Es VTEX pero no vende lubricantes de motor. |
| Cetrogar | www.cetrogar.com.ar | 200 `[]` | — | 0 | — | — | Es VTEX pero sin lubricantes. |
| Toledo | www.toledodigital.com.ar | 200 `[]` | — | 0 | — | — | Es VTEX pero sin lubricantes. |
| Blaisten | www.blaisten.com.ar | 200 `[]` | — | 0 | — | — | Es VTEX pero sin lubricantes. |
| Sodimac | www.sodimac.com.ar | 308 y después 404 | — | — | — | — | No es VTEX (es Falabella). No lo seguí. |
| La Anónima (Hiper Libertad redirige acá) | www.laanonima.com.ar | 404 | — | — | — | — | No es VTEX. |
| Musimundo | www.musimundo.com | 301 a la home | — | — | — | — | No es VTEX. |
| Megatone | www.megatone.net | 404 | — | — | — | — | No es VTEX. |
| Casa Roca | www.casaroca.com.ar | 403 | — | — | — | — | Bloquea. |
| La Coope en Casa | www.lacoopeencasa.coop | 200 HTML | — | — | — | — | No es VTEX. Probé `api.lacoopeencasa.coop/api/articulos/pagina_busqueda` y dio 404. Ruta no confirmada. |

Coto (no es VTEX, usa Oracle Endeca):
- URL: `https://www.coto.com.ar/sitios/cdigi/browse?Ntt={q}&Nrpp=50&format=json`. cotodigital3 redirige con 301 a esa.
- HTTP 200, JSON.
- Campos: `product.displayName`, `product.brand`, `sku.activePrice`, `totalNumRecs`.
- Resultados: `aceite para motor` dio 21. `elaion` dio 0 relevantes. `shell helix` dio 0. `castrol` dio 0 relevantes. `lubricante` dio 108, casi todo afeitado y WD-40.
- Marcas vistas: Bardahl, Total.
- Muestra: BARDAHL / Aceite Motor 4t Para Motos 1ltr Bardahl. El emparejado de mi regex entre nombre y precio fue poco confiable, así que no doy el precio.
- Cobertura de lubricantes de motor: muy baja.

## 2. SEPA / Precios Claros (oficial)
- Metadata: `https://datos.produccion.gob.ar/api/3/action/package_show?id=sepa-precios` da HTTP 200 (CKAN). El dataset se llama "Precios Claros - Base SEPA" y se actualizó por última vez el 2026-11-02.
- Archivos: 7 zips rotativos, uno por día de la semana (se pisa el del mismo día de la semana anterior), de 311 a 325 MB cada uno. Ejemplo: `https://datos.produccion.gob.ar/dataset/6f47ec76-d1ce-4e34-a7e1-621fe9b1d0b5/resource/0a9069a9-06e8-4f98-874d-da5578693290/download/sepa_lunes.zip` (200, 324 MB, bajó en 64 s). Las URLs de los otros días están en `resources[]` del package_show.
- Formato: zip con 17 zips adentro, uno por comercio y bandera. Cada uno trae `comercio.csv`, `sucursales.csv` y `productos.csv`, separados por pipe `|`.
- Columnas de productos.csv: id_comercio, id_bandera, id_sucursal, id_producto (EAN), productos_ean, productos_descripcion, productos_cantidad_presentacion, productos_unidad_medida_presentacion, productos_marca, productos_precio_lista, productos_precio_referencia, productos_cantidad_referencia, productos_unidad_medida_referencia, promo1, promo2.
- Tamaño: 14,3 millones de filas por día (lunes 2026-11-02).
- ¿Incluye lubricantes? Sí, pero solo de 2 o 3 cadenas. Filtré con regex de aceite de motor:
  - Carrefour (INC S.A., comercio 10): 1093 filas, 104 sucursales. Productos distintos (EAN) por marca: GULF 10, ELAION 8, TOTAL 5, BARDAHL 1, ELF 1.
  - ChangoMás (DORINKA, comercio 11): 279 filas, 93 sucursales, PETRONAS 3. Mi regex subcuenta acá, porque en MásOnline el Elaion figura como "Lubricante Ypf Elaion Mi 2050" sin "W".
  - Coto, Vea (Cencosud), Día, La Anónima y Cooperativa Obrera: 0 filas de aceite de motor. La Obrera tuvo 1 coincidencia con la regex amplia.
- Muestras:
  - `10|1|233|7790968914633|1|ACEITE ELAION MI 1540 X 4|1|UNI|ELAION|82990.00|...`
  - `10|1|231|7790968914633|...|79999.00` (el mismo EAN cuesta distinto según la sucursal, así que sirve para dispersión geográfica)
  - `10|1|5|7790627701673|1|ACEITE BARDAHL 4T MOTOS 20W50 X 1 L|...|BARDAHL|12990.00`
- Valor: es el único dato oficial y legal de precio por sucursal y por EAN. Cobertura de lubricantes baja (dos cadenas).
- Frecuencia: diaria.
- Ejecución: no entra en Render free (descomprimir 320 MB con 512 MB de RAM). Hay que procesarlo leyendo el zip en streaming y filtrando por EAN 779096891xxxx (YPF) más una lista de EAN de competidores, todo dentro de GitHub Actions.
- Riesgo legal: ninguno (datos abiertos). Bloqueo a IPs de nube: improbable, porque es CKAN del Estado y no tiene WAF a la vista.

## 3. Tiendas oficiales de marca, lubricentros y distribuidores
- Tienda YPF: `tienda.ypf.com` y `www.tiendaypf.com.ar` no resuelven (000). `www.ypf.com/productosyservicios/Paginas/lubricantes.aspx` redirige a error.html. No encontré e-commerce oficial de YPF lubricantes.
- Shell (Raízen): `www.shell.com.ar/conductores/lubricantes-shell-para-autos.html` da 404. La búsqueda no muestra tienda online oficial en AR; venden por estaciones y puntos de venta adheridos.
- Axion: `www.axionenergy.com/lubricantes` da 404. Sin tienda online oficial. En agroads.com.ar aparece por distribuidores.
- Mobil AR: `www.mobil.com.ar` no resuelve (000).
- Lubricentros online: la búsqueda solo devuelve tiendas dentro de Mercado Libre (Lubricentro Extreme, Lubri Artigas, Lubricentro Goya, Multifacro, LS Palermo). No encontré e-commerce propios con API.
- Mercado Libre:
  - `api.mercadolibre.com/products/MLA27257458` da 401 (pide token).
  - `api.mercadolibre.com/products/search?...` da 403 (PolicyAgent).
  - `www.mercadolibre.com.ar/p/MLA27257458` responde 200 pero redirige a `/gz/account-verification` (muro anti-bot).
  - Solo se accede con OAuth de una app de developers ML, en otro análisis.
- Tercero que rastrea precios de ML: mejorescompras.com.ar.
  - URL: `https://mejorescompras.com.ar/precio/MLA27257458--aceite-ypf-elaion-10w40-ts-1040-semisintetico-x-4l-ex-f30`. HTTP 200, HTML con ld+json.
  - Muestra: lowPrice 62499, highPrice 70310, offerCount 10, ARS, para Elaion 10W40 TS 1040 4L.
  - Riesgo: alto. Es scraping de un scraper, sin licencia y frágil. Sirve solo como referencia, no como fuente.

## 4. Precio de lubricantes en surtidor
- Dataset Res. 314/2016: `http://datos.energia.gob.ar/api/3/action/package_show?id=precios-en-surtidor` da 200. Su descripción dice "naftas, gasoil y GNC", y en el CSV aparecen solo Gas Oil G2/G3, Nafta súper/premium y GNC. No incluye lubricantes.
- `package_search?q=lubricantes` en datos.energia.gob.ar: 0 resultados.
- Conclusión: no existe fuente pública de precios de lubricantes en estación de servicio. Solo se puede sacar de listas internas de YPF o de relevamiento manual.

## Riesgo de bloqueo desde GitHub Actions (no probado desde la nube, es estimación)
- Riesgo alto: Mercado Libre (ya bloquea desde IP residencial) y Carrefour (Cloudflare, puede desafiar a IPs de Azure).
- Riesgo medio-bajo: Jumbo, Disco, Vea, Easy, MásOnline y Frávega (nginx de VTEX, sin WAF a la vista; los robots.txt no prohíben `/api`). Ir a 1 req/s.
- Riesgo bajo: SEPA en datos.produccion.gob.ar.
- Coto (Endeca): desconocido.
- Antes de comprometerse hay que validarlo con un workflow de prueba en Actions.

## Recomendación de ingesta (fuentes que valen)
1. VTEX diario por categoría: Carrefour 642, Jumbo 412 (Disco y Vea se omiten porque duplican a Jumbo), Easy 321, MásOnline 3000496. Son unos 520 productos y alrededor de 12 requests en total. La clave para cruzar entre cadenas es el EAN (prefijo YPF 779096891).
2. SEPA diario, filtrado por EAN, para tener dispersión por sucursal de Carrefour y ChangoMás.
3. Coto: opcional, cobertura baja.
4. Frávega, Día, Cetrogar, Toledo, Blaisten y Sodimac: descartados.

Archivos locales:

Sources:
- [Easy Elaion F30 4L](https://www.easy.com.ar/lubricante-elaion-f30-10w40-ts-1040-x-4/p)
- [mejorescompras MLA27257458](https://mejorescompras.com.ar/precio/MLA27257458--aceite-ypf-elaion-10w40-ts-1040-semisintetico-x-4l-ex-f30)
- [Frávega Shell Helix Ultra](https://www.fravega.com/p/aceite-shell-helix-ultra-x-5w30-4-lts-x-3-unidades-22089830)
- [Lubricentro Extreme en ML](https://www.mercadolibre.com.ar/pagina/lubricentroextreme)
- [Raízen promo Shell](https://www.16valvulas.com.ar/?p=163131)
- [agroads Axion](https://www.agroads.com.ar/seccion.asp?subcat=45)