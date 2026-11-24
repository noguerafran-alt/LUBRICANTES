# Consulta a Mercado Libre Developers: 403 PolicyAgent en products/{id}/items

Canal: **ticket de Soporte para Integradores** (https://developers.mercadolibre.com.ar/es_ar/soporte-para-integradores), no mail. Las respuestas llegan al mail de la cuenta de ML; ahí se puede sumar el correo de YPF a la cadena. No lleva tokens ni el Client Secret.

Campos del ticket:

| Campo | Valor |
|---|---|
| Categoría | Productos → Publicaciones |
| Aplicación | 244077280147192 |
| Tipo | Problema |
| Asunto | el de abajo |
| Descripción | el cuerpo de abajo (máx. 5000 caracteres) |
| Usuarios afectados | 200791825 |
| Método | GET |
| Recurso | `https://api.mercadolibre.com/products/MLA74282835/items` |
| Request | `Authorization: Bearer <token del usuario>`, sin body |
| Respuesta | `HTTP 403 {"blocked_by":"PolicyAgent","message":"At least one policy returned UNAUTHORIZED.","status":403,"code":"PA_UNAUTHORIZED_RESULT_FROM_POLICIES"}` |

Antes de mandarlo: revisar en la cuenta de ML (Mi perfil → Datos personales) si hay validación de identidad pendiente. La página «Error 403» de ML lista «el usuario debe tener concluido el proceso de validación de datos» y «usuarios inactivos» entre las causas, y el devcenter muestra la autorización «INACTIVA».

---

**Asunto:** App 244077280147192 – 403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES en GET /products/{id}/items desde el 23/11/2026

Hola, equipo de Developers:

Les escribo por la aplicación «Lubricantes AR precios» (App ID **244077280147192**, sitio MLA, usuario autorizante 200791825). La usamos para leer, una vez por día, los precios públicos de aceites lubricantes del catálogo, para análisis de mercado. La cuenta también es vendedora y la app gestiona sus propias publicaciones (precio y stock).

Desde el **23/11/2026** todas las llamadas a `GET /products/{product_id}/items` responden:

```
HTTP 403
{"blocked_by":"PolicyAgent","message":"At least one policy returned UNAUTHORIZED.","status":403,"code":"PA_UNAUTHORIZED_RESULT_FROM_POLICIES"}
```

Hasta el 22/11/2026 la misma llamada, con la misma app y el mismo código, devolvía unas 1.850 publicaciones por día.

Lo que ya probé:
- El token es válido. `POST /oauth/token` (refresh_token y client_credentials) da 200, `GET /products/search?site_id=MLA&q=elaion` da 200 y `GET /highlights/MLA/category/MLA375007` da 200.
- Volví a autorizar la app con el usuario el 24/11/2026 (authorization code, y ahora con PKCE activado). Con el token nuevo, `/products/{id}/items` sigue en 403. Ejemplo: `GET /products/MLA74282835/items`.
- Da el mismo 403 desde distintas redes (servidor en la nube e IP residencial), así que no parece un bloqueo por IP.
- El 24/11/2026 pasé «Publicación y sincronización» a **Lectura y escritura** y volví a autorizar. El token nuevo trae `urn:ml:all:publish-sync:/read-write`, `urn:ml:mktp:publish-sync:/read-write` y `write`, y `/products/MLA74282835/items` sigue en 403 PolicyAgent. Con ese mismo token responden 200 `/users/me`, `/users/200791825/items/search`, `/items/{id}`, `/items/{id}/price_to_win` y `/products/MLA74282835` (con `buy_box_winner` en null). `/sites/MLA/search` da 403 forbidden.
- Los flujos activos son Authorization Code (con PKCE), Client Credentials y Refresh Token.
- En el DevCenter la app figura como «Aplicación no certificada», con la configuración de seguridad en 70/100. La autorización del usuario figura «INACTIVA» aunque se renovó.

Consultas:
1. ¿Qué política está rechazando `/products/{id}/items` para esta app? ¿Hubo un cambio el 23/11/2026 para apps no certificadas?
2. La doc de permisos funcionales indica que este 403 corresponde a un permiso faltante, pero con «Publicación y sincronización» en lectura y escritura sigue igual. ¿Qué permiso, certificación o configuración necesito para volver a leer las publicaciones de un producto del catálogo?
3. Si este recurso ya no está disponible para apps de este tipo, ¿cuál es el endpoint recomendado para consultar el precio público de las publicaciones de un producto de catálogo?
4. ¿Qué ítems faltan para completar la configuración de seguridad (70/100)?

Muchas gracias.
Francisco Noguera
[cargo / área] – YPF
[teléfono]

---

Si piden más datos: el request lleva `Authorization: Bearer <token>` y `User-Agent` propio, con una llamada por segundo como máximo y unas 300 llamadas a `/items` por día.

---

# Formulario de alta de una app nueva (ML, desde 2026-11-17)

`https://forms.gle/2Q39SStHLJNQLjuK9` («Application Creation Request — Mercado Libre»). Crear apps desde el DevCenter está cerrado; ML evalúa cada pedido.

**Requisito:** «This request is available only to users who have never created an application on Mercado Libre». La cuenta 200791825 (FRANLNOGUERA) ya tiene la app 244077280147192, así que **con esa cuenta no corresponde**. Habría que pedirlo con otra cuenta de ML que nunca haya creado una app, por ejemplo una corporativa de YPF, y esa cuenta la crea y la usa el usuario. Una app nueva también arranca «no certificada»: no hay garantía de que no le toque la misma política del 403.

Borrador de respuestas (en inglés, como el formulario):

| Pregunta | Respuesta |
|---|---|
| Username of that account | el de la cuenta nueva (Account data → Username) |
| Intended use (1) | **Personal use**: the application will be used only with my own account |
| Intended use (2) | **View metrics and reports** (ninguna opción es exactamente «leer precios públicos»; es la más cercana y no pide escritura) |
| Describe what the application will do | Read-only daily market analysis of engine oil and lubricant prices in Argentina. Once a day it searches the product catalog (/products/search) for lubricant brands and reads the public listings of each catalog product (/products/{id}/items) to compute median prices per liter. About 300 read requests per day, max 1 request per second. It never creates, edits or pauses listings, never buys, and does not access other users' data. Results are used internally for market analysis. |
| Redirect URL | `https://lubricantes.fln-data-analysis.com/ml-callback` |
| Demo link | `https://lubricantes.fln-data-analysis.com` (visor de lectura) |

**Actualización 2026-11-24:** el formulario aplica a la **cuenta de vendedor NUEVA** (la que el usuario va a crear y que nunca creó una app), con uso de vendedor y no de solo lectura. Respuestas para ese caso: Intended use (1) **Personal use**; Describe: «Seller tool for my own lubricant store: manages my listings (price/stock), reads my orders, checks catalog competition of my own catalog listings, plus read-only public catalog search for internal market analysis (~300 requests/day, max 1 request/second)»; Redirect URL `https://lubricantes.fln-data-analysis.com/ml-callback`; Demo `https://lubricantes.fln-data-analysis.com`. Ver «Vía vendedor» en `docs/ml-via-oficial.md`.
