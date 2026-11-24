# Consulta a Mercado Libre Developers: 403 PolicyAgent en products/{id}/items

Para mandar desde el correo de YPF (o por el formulario de soporte de developers.mercadolibre.com.ar) al equipo de Developers / OpenPlatform. No lleva tokens ni el Client Secret. La dirección de destino sale del canal de contacto oficial de ML: no se inventa.

---

**Asunto:** App 244077280147192 – 403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES en GET /products/{id}/items desde el 23/11/2026

Hola, equipo de Developers:

Les escribo por la aplicación «Lubricantes AR precios» (App ID **244077280147192**, sitio MLA, usuario autorizante 200791825). La usamos para leer, una vez por día, los precios públicos de aceites lubricantes del catálogo, para análisis de mercado. No publica, no vende y no modifica nada.

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
- La app tiene el permiso «Publicación y sincronización» en **Lectura** y «Usuarios» en Lectura y escritura. Los flujos activos son Authorization Code, Client Credentials y Refresh Token.
- En el DevCenter la app figura como «Aplicación no certificada», con la configuración de seguridad en 70/100. La autorización del usuario figura «INACTIVA» aunque se renovó.

Consultas:
1. ¿Qué política está rechazando `/products/{id}/items` para esta app? ¿Hubo un cambio el 23/11/2026 para apps no certificadas?
2. ¿Qué permiso, certificación o configuración necesito para volver a leer las publicaciones de un producto del catálogo, solo en lectura?
3. Si este recurso ya no está disponible para apps de este tipo, ¿cuál es el endpoint recomendado para consultar el precio público de las publicaciones de un producto de catálogo?
4. ¿Qué ítems faltan para completar la configuración de seguridad (70/100)?

Muchas gracias.
Francisco Noguera
[cargo / área] – YPF
[teléfono]

---

Si piden más datos: el request lleva `Authorization: Bearer <token>` y `User-Agent` propio, con una llamada por segundo como máximo y unas 300 llamadas a `/items` por día.
