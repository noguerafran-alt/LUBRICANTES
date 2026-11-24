# Mercado Libre por la vía oficial

Situación (verificada el 2026-11-24): la app **244077280147192** («Lubricantes AR precios», no certificada, propósito Negocios, PKCE activo, Redirect URI `https://lubricantes.fln-data-analysis.com/ml-callback`) recibe **403 PolicyAgent `PA_UNAUTHORIZED_RESULT_FROM_POLICIES`** en `GET /products/{id}/items` desde el 2026-11-23. Búsqueda, highlights y OAuth dan 200. Reautorizar y cambiar de IP no lo arregla: el bloqueo es de la app.

La documentación de ML sobre [bloqueo de aplicaciones](https://developers.mercadolibre.com.ar/es_ar/bloqueo-de-aplicaciones) define `INTEGRATORS_DATA_INFRACTION` como «Se bloqueará por infracción de datos cuando se utilicen únicamente datos de lectura, sin consumo de APIs que generen valor». Nuestra app solo lee, así que encaja. No se esquiva (ni apps nuevas «por la ventana», ni otra IP, ni scraping): las vías son las de abajo.

## Vía 1 — Formulario con una cuenta de ML de YPF que nunca creó una app

Desde el 2026-11-17 crear apps es por formulario (https://forms.gle/2Q39SStHLJNQLjuK9), solo para cuentas que **nunca crearon una app**. La cuenta actual ya creó esta, así que no califica.

Preparar:
- Una cuenta de ML de YPF (corporativa, con la validación de datos completa) y la autorización interna de YPF para usarla.
- Redirect URL: `https://lubricantes.fln-data-analysis.com/ml-callback`.
- Demo: lo que muestre el uso real (el visor y la lectura diaria).

Respuestas honestas para uso de solo lectura (en inglés, como pide el formulario):
- Username: el de la cuenta de YPF.
- Use: Business (si la cuenta es de la empresa; Personal si es personal).
- Type: View metrics and reports.
- Description: «Daily read of public lubricant prices (engine oils category) for internal market analysis. About 300 requests per day at 1 request per second. Read-only: no listings, orders or messages are created or modified.»

Riesgo a decir en voz alta: puede ser **rechazada** por la política de solo lectura, o aprobada y bloqueada de nuevo por la misma causa.

## Vía 2 — Integración con escritura real

Solo si existe una **operación de venta real** en ML: tienda oficial de YPF, un distribuidor o una cuenta que publica lubricantes YPF.

- Qué haría la app: gestionar **sus propias** publicaciones (precios, stock, preguntas) y usar el precio de mercado que ya recolectamos para fijar los propios.
- Qué cuenta la autoriza: la del vendedor (la que publica), no una cuenta de análisis.
- Permisos funcionales a pedir: «Publicación y sincronización» en lectura y escritura; «Comunicaciones pre y post venta» solo si responde preguntas.
- Tipos a marcar en el formulario: Manage product listings y Manage or optimize prices.

**No se agregan escrituras sin un uso real para aparentar valor: es simular uso para evadir la política de ML y arriesga la cuenta.** La vía 2 existe solo si la operación de venta existe.

## Vía 3 — Pedirle los datos a ML como marca

YPF puede pedir información de mercado de la categoría a Mercado Libre por su relación comercial (equipos de marcas o de publicidad de ML). Este documento no inventa productos ni contactos: el usuario lo dirige a quien YPF ya tenga en ML.

Qué pedir:
- Precios publicados por producto de catálogo (SKU/GTIN) y por vendedor, **por día**.
- Categoría MLA de aceites de motor (la de `ml_cat`), marcas YPF y los competidores de `seed/equivalencias.csv`.
- Formato CSV o API, frecuencia diaria, histórico si lo hay.

Borrador (completar destinatario y firma):

> Asunto: Datos de precios de lubricantes en Mercado Libre para YPF
>
> Hola, [nombre]. Desde YPF analizamos el mercado de lubricantes en Argentina. Nos gustaría recibir, por la relación comercial que ya tenemos, un reporte diario de los precios publicados en la categoría Aceites de motor (MLA): por producto de catálogo y por vendedor, para las marcas YPF y las marcas competidoras que les indicamos en el adjunto. Formato CSV o acceso por API. ¿Pueden indicarnos si existe un producto de datos para marcas o cómo gestionarlo? Gracias, [firma]

## Estado y qué sigue

- La consulta técnica por el 403 (ticket de Soporte para Integradores) está redactada en `docs/ml-soporte-403.md`; **no se envió** al 2026-11-24 (el portal de tickets no aparece para esta cuenta: parece exclusivo del Developer Partner Program). Mientras tanto `ml` no trae precios y `ml_envios` no cotiza.
- Cuando ML apruebe una app nueva: `python ml.py autorizar` con el Client ID y el Client Secret nuevos (desde la PC); cargar los secrets `ML_CLIENT_ID`, `ML_CLIENT_SECRET` y `ML_REFRESH_TOKEN` en GitHub; actualizar la Redirect URI en el devcenter. Solo la Action usa el token (nunca el celular ni la PC de casa).
