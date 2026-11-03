
# MERCADO LIBRE AR: CÓMO TRAER LOS DATOS (verificado 2026-11-03, desde esta PC, sin token)

## 1. Pruebas HTTP sin token (curl, host api.mercadolibre.com)
| Endpoint | HTTP | Respuesta / muestra |
|---|---|---|
| /sites/MLA/search?q=elaion | 403 | `{"error":"forbidden"}` |
| /sites/MLA/search?category=MLA375007 | 403 | forbidden |
| /products/search?status=active&site_id=MLA&q=elaion | 403 | PA_UNAUTHORIZED_RESULT_FROM_POLICIES (PolicyAgent) |
| /products/MLA14719808 | 401 | "authorization value not present" |
| /products/MLA14719808/items | 403 | PolicyAgent |
| /highlights/MLA/category/MLA1747 | 401 | "unspecified_token" |
| /trends/MLA y /trends/MLA/MLA375007 | 403 | PolicyAgent |
| /items?ids=MLA1 | 401 | nginx 401 |
| /items/bulk?ids=MLA1 | 403 | PolicyAgent |
| /reviews/item/MLA1, /sites/MLA, /sites/MLA/categories, /currencies/ARS, /users/me | 403 | PolicyAgent |
| **/categories/MLA375007** | **200** | name "Para Motor", total_items_in_this_category 30558, catalog_domain "MLA-ENGINE_OILS" |
| **/categories/MLA375007/attributes** | **200** | la lista de atributos (ver punto 4) |
| **/sites/MLA/domain_discovery/search?q=aceite motor 10w40** | **200** | domain_id MLA-ENGINE_OILS, category_id MLA375007, VISCOSITY_GRADE value_id 16917217 "10W40" |
| POST /oauth/token grant_type=client_credentials (IDs inventados) | 400 | "invalid_client". No dice "unsupported_grant_type", así que no queda claro si ese grant está permitido |
| listado.mercadolibre.com.ar/aceite-elaion | 302 | redirige a /gz/account-verification (anti-bot) |
| www.mercadolibre.com.ar/robots.txt | 200 | `Disallow: /` para ClaudeBot, GPTBot, PerplexityBot, Amazonbot, ChatGPT-User |

Sin token solo responden categorías, atributos y domain_discovery. Todo lo que tiene precio pide token.

## 2. IDs reales de categoría en MLA (probados, con su total_items)
- MLA456111 Lubricantes y Fluidos: 96670
  - MLA86011 Autos y Camionetas: 44244
    - MLA432536 Aceites
      - **MLA375007 Para Motor: 30384–30558** (domain MLA-ENGINE_OILS)
      - MLA456128 Para Cajas Automáticas: 3156
      - MLA438870 Para Transmisión Manual: 2097
      - MLA432538 Otros: 365
  - MLA429226 Motos: 18674
  - MLA432535 Líquidos: 20357
  - MLA456130 Agro e Industria: 5609
  - MLA437274 Grasas: 3547
  - MLA456115 Línea Pesada: 2323
  - MLA456116 Náutica: 1785
  - MLA456112 Otros: 62

El total por categoría se puede pedir sin token. Sirve como métrica diaria del tamaño de la oferta.

## 3. Lo que dice la documentación oficial

**Ítems y búsquedas** (developers.mercadolibre.com.ar/es_ar/items-y-busquedas, actualizada 10/09/2026):
- La documentación solo muestra la búsqueda por vendedor, `/sites/MLA/search?seller_id=` o `?nickname=`, siempre con Bearer.
- La tabla de migración marca `?nickname` como "Sin sustitución" y manda `?seller_id` a `/users/{id}/items/search`.
- La búsqueda general por `q` y por categoría ya no aparece documentada para terceros.
- `/items?ids=` está en deprecación y lo reemplaza `/items/bulk?ids=` (fecha de migración 25/10/2026, ya pasada).
  - En el bulk, `code` pasa a llamarse `status_code`.
  - Para elegir campos se usa `attributes=body.id,body.price`.
- En los recursos públicos, `available_quantity` llega en rangos: 1, 50, 100, 150, 200, 250, 500, 5000, 50000.

**Otros endpoints documentados (todos con `Authorization: Bearer $ACCESS_TOKEN`):**
- `/products/search?status=active&site_id=MLA&q=...` o `&product_identifier=GTIN`. Devuelve catálogo (id, domain_id, name, buy_box_winner, pickers). Un MCP de terceros confirma que no trae precios.
- `/highlights/MLA/category/{CAT}`: top 20 más vendidos, tipo BEST_SELLER, con ids de tipo USER_PRODUCT. También filtra por marca, producto o ítem.
- `/trends/MLA`: las keywords que más crecieron en búsquedas.

**Rate limit:** no hay una cifra publicada. La doc pide backoff exponencial con jitter ante un 429 y no hacer multiget masivo.

**Error 403 con token:**
- Causas oficiales: scopes o permisos funcionales sin activar en DevCenter, app bloqueada, IP bloqueada, o token que no es del dueño del dato.
- Un MCP de terceros (mercadolivre-mcp, sitio MLB) reporta que `/sites/*/search` está "bloqueada na borda" para IP de datacenter aun con token. Es un dato no oficial, pero aplica directo a Render.

## 4. Cómo se obtiene el token
1. Crear una app gratis en developers.mercadolibre.com.ar (DevCenter). Hace falta una cuenta ML y un redirect_uri fijo.
2. Activar los permisos funcionales de lectura. Por defecto solo viene `users`, el resto devuelve 403 PolicyAgent. Después hay que volver a autorizar la app.
3. Pedir el código de autorización:
   `https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id=$APP_ID&redirect_uri=$REDIRECT_URI`
   Si la app tiene PKCE activo, agregar `code_challenge` y `code_challenge_method`.
4. Canjear el código:
   `POST https://api.mercadolibre.com/oauth/token` con headers `accept: application/json` y `content-type: application/x-www-form-urlencoded`, y body `grant_type=authorization_code&client_id&client_secret&code&redirect_uri[&code_verifier]`.
5. La respuesta trae `access_token` (APP_USR-...), `expires_in` y `refresh_token` (TG-...), con scope "offline_access read write".
   - El texto de la doc dice que el access_token dura 6 h. El ejemplo de la misma doc muestra `expires_in` 10800 (3 h). Hay que confiar en el valor de cada respuesta.
6. Refrescar con `grant_type=refresh_token&client_id&client_secret&refresh_token`.
   - El refresh_token es de un solo uso: cada canje trae uno nuevo y solo vale el último.
   - Dura 6 meses y se invalida si se revoca la autorización.
7. `client_credentials` no aparece en la doc actual de autenticación. Mi prueba fue inconclusa, así que hay que probarlo con una app real.
8. Consecuencia para Render free (disco efímero): el refresh_token rotativo tiene que vivir en un almacenamiento persistente externo (una DB free o una variable de entorno actualizada por la API de Render). Si se guarda en disco, se pierde en cada redeploy o reinicio.

## 5. Términos de uso
- Términos del Programa de Desarrolladores, cláusula 7.6: prohíbe "robots, harvesters, spiders, scraping u otra tecnología" para acceder al Sitio u obtener información que no se entregue por la API.
- Cláusula 7.5: prohíbe eludir limitaciones técnicas.
- También se lista como uso prohibido divulgar información obtenida por la integración a terceros que no son usuarios de ML. Para un uso interno en YPF conviene que lo revise Legales.
- La Declaración de Privacidad de ML AR dice que aplican medidas contra la extracción automatizada (es el 302 a account-verification de la prueba).
- robots.txt: `Disallow: /` explícito para bots de IA.
- Conclusión: hacer scraping de listado.mercadolibre.com.ar no es legal ni sostenible (viola el contrato y además está bloqueado). Evadir el 302 o la verificación también viola la cláusula 7.5.

## 6. Campos útiles para competencia (por endpoint, sin probar con token)
- Desde un ítem (`/items/bulk`): id, title, price, original_price, currency_id, seller_id, official_store_id, catalog_product_id, listing_type_id, condition, shipping.free_shipping, available_quantity (en rangos) y attributes[].
- `sold_quantity`: según la doc de ítems no se muestra sin el token del dueño. No encontré confirmación oficial de que siga saliendo en recursos públicos de terceros. Como proxy de ventas quedan `/highlights` (posición en el top 20) y `available_quantity` en rangos.
- Atributos que existen en MLA375007 (confirmados con HTTP 200):
  - BRAND, LINE, MODEL, DETAILED_MODEL
  - VISCOSITY_GRADE, ENGINE_OIL_TYPE (sintético, semi, mineral), CLASSIFICATIONS (API/ACEA)
  - NET_VOLUME (number_unit), UNITS_PER_PACK, SALE_FORMAT, CONTAINER_TYPE
  - VEHICLE_TYPE, ENGINE_TYPES, ENGINE_TIMES
  - GTIN, MPN, OEM
  - VISCOSITY_INDEX, FLASH_POINT, POUR_POINT, ORIGIN
- Para la equivalencia YPF↔competidor, la clave es VISCOSITY_GRADE + ENGINE_OIL_TYPE + CLASSIFICATIONS + NET_VOLUME. Para precio por litro: price / (NET_VOLUME × UNITS_PER_PACK).
- La categoría también devuelve settings.item_conditions ["new"] y buying_modes.

## 7. Receta recomendada (en orden)
- **A. Catálogo, sin token, diario:**
  - `/categories/{id}` para el total de ítems por subcategoría.
  - `/categories/MLA375007/attributes` para mapear los valores.
  - `/sites/MLA/domain_discovery/search?q=` para clasificar los SKU propios de YPF.
- **B. Con token de app propia:**
  1. `/products/search?status=active&site_id=MLA&q={marca línea viscosidad}` o `&product_identifier={GTIN}`, para obtener los catalog product_id de Elaion y de cada competidor.
  2. `/products/{product_id}/items`, para todas las publicaciones de ese producto con precio y vendedor. Endpoint conocido; dio 403 sin token y no lo pude probar con token.
  3. `/items/bulk?ids=` (hasta 20) con `attributes=body.id,body.price,body.original_price,body.seller_id,body.official_store_id,body.attributes`.
  4. `/highlights/MLA/category/MLA375007` (y por marca) para el ranking diario.
  5. `/trends/MLA/MLA375007` para la demanda de búsquedas.
- **C. Riesgo de IP:** si con token `/products/search` o `/items/bulk` dan 403 desde la IP de Render (datacenter), correr el recolector desde esta PC o desde GitHub Actions y empujar los resultados a la DB.
- **D. Alternativas legales si la búsqueda autenticada no alcanza:**
  - Retailers VTEX con API pública (carrefour.com.ar, ya probado con 206; también Jumbo, Disco y Vea).
  - Precios de lista de los fabricantes.
  - Un proveedor de datos con licencia (por ejemplo, la propia ML vía Mercado Ads o un acuerdo comercial).
  - No usar Apify ni scrapers de ML: violan la cláusula 7.6.

## 8. Lo que no se pudo verificar
- Comportamiento real con token, porque no hay app creada.
- Si client_credentials está habilitado.
- Si `sold_quantity` sigue público.
- El rate limit numérico.
- Si Render queda bloqueado por IP.

**Para destrabarlo:** crear la app en DevCenter con los permisos de lectura y repetir la tabla del punto 1 con `-H "Authorization: Bearer $TOKEN"`.


Fuentes:
- [Error 403 ML AR](https://developers.mercadolibre.com.ar/error-403)
- [Error 403 ML MX](https://developers.mercadolibre.com.mx/error-403)
- [lumile/mercadolibre-mcp](https://glama.ai/mcp/servers/@lumile/mercadolibre-mcp/tree)
- [anythingmcp guía](https://anythingmcp.com/es/guides/connect-mercado-libre-to-claude)
- [romualdoag/mercadolivre-mcp](https://glama.ai/mcp/servers/romualdoag/mercadolivre-mcp)
- [Moderations (PolicyAgent)](https://global-selling.mercadolibre.com/devsite/moderations-gs)
- [Claims Messages](https://global-selling.mercadolibre.com/devsite/manage-claims-messages)
- [T&C Programa de Desarrolladores](https://developers.mercadolibre.com.ar/es-ar-terminos-y-condiciones)
- [Privacidad ML AR](https://www.mercadolibre.com.ar/privacidad/declaracion-privacidad/31256)
- [ML list-products](https://developers.mercadolibre.com.ar/en_us/list-products)
- [mercadolibreR sold_quantity](https://rdrr.io/github/njcorona/mercadolibreR/man/sold_quantity.html)
- [Autenticación y autorización](https://developers.mercadolibre.com.ar/es_ar/autenticacion-y-autorizacion)
- [Ítems y búsquedas](https://developers.mercadolibre.com.ar/es_ar/items-y-busquedas)
- [Más vendidos](https://developers.mercadolibre.com.ar/es_ar/mas-vendidos-en-mercado-libre)
- [Buscador de productos](https://developers.mercadolibre.com.ar/es_ar/buscador-de-productos)
- [Tendencias](https://developers.mercadolibre.com.ar/es_ar/tendencias)
- [Rate limit 429](https://developers.mercadolibre.com.ar/es_ar/rate-limit-error-429)