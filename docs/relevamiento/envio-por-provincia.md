# Precio puesto en provincia: diseño

Relevamiento del 2026-11-23, solo lectura. No se tocó el repo ni `data/` y no se usó el token de Mercado Libre. Los crudos y los scripts están en `scratchpad\envio\` (subcarpetas `mercadolibre\`, `vtex\`, `tiendanube_woo\` y `tarifas_correo\`).

## La idea en una línea

No hace falta adivinar dónde está el vendedor. En los canales donde se puede, **la tienda misma cotiza el envío a un código postal**, y esa cotización ya tiene en cuenta desde dónde despacha. Un vendedor cordobés que manda a Córdoba sale barato y uno fueguino que manda a Córdoba sale caro, y eso lo cotiza la tienda sin que nosotros sepamos dónde queda ninguno de los dos. Así, «el vendedor más cercano» pasa a ser **el aviso con menor precio + envío cotizado a esa provincia**. Esto cumple la regla del repo («la provincia nunca se deduce de la casa central»): no se deduce nada, se lee lo que cotiza la tienda.

## 1. Qué se puede cotizar de verdad y qué no

| canal | ¿cotiza envío a un CP? | cómo | evidencia (2026-11-23) |
|---|---|---|---|
| **Mercado Libre** | **Sí**, sin token | `GET https://api.mercadolibre.com/items/{MLA}/shipping_options?zip_code={CP}` → 200 | Shell Helix HX5 15W40 4 L ($63.355): envío gratis a CABA, Córdoba y Rosario; $6.208 a Mendoza, Neuquén y Posadas; $10.058 a Ushuaia (216 h); $11.068 a Salta. Castrol GO 2T: $10.990 a CABA y $14.490 a Salta; Ushuaia da 404 y Posadas 424 (`route options repository error`) |
| **VTEX: Norauto** | **Sí**, y por distancia | `POST https://www.norauto.com.ar/api/checkout/pub/orderForms/simulation?sc=1` con `{items:[{id,quantity:1,seller}], postalCode, country:"ARG"}` → 200 | Helix HX7 10W40 4 L: CABA $13.452 (3 días hábiles) y retiro gratis en el AMBA; Rosario $30.289; Córdoba $30.631; Mendoza $32.420; Salta $33.510; Neuquén $34.829; Ushuaia $41.725 (9 días hábiles). Sale de un solo depósito por Andreani. Es tu ejemplo tal cual |
| **VTEX: Easy** | Sí, pero **cotizado con un ítem que no es aceite** (WD-40 155 g, el primero con stock de la categoría). Falta cotizar un 4 L | igual | Con el WD-40: domicilio $12.499 en todos lados, larga distancia $12.199, «Domicilio Pesado» $31.499, retiro en tienda $0 en las capitales con local, Ushuaia `cannotBeDelivered`. Un bidón de 4 L podría caer en «Domicilio Pesado»: no se sabe si para el aceite la tarifa es plana |
| **VTEX: Carrefour y Masonline** | Sí, pero lo que cambia es **si el local de la zona lo tiene**, no el flete | igual; el costo está en `availableDeliveryWindows[].price`, no en `slas.price` | Franja a $3.990 o $3.999. Despacha el local de la zona («0268 - Hiper Rosario Pueyrredón», «Córdoba Oeste»). El Elaion MI 1540 1 L en Carrefour figura «no disponible» en Córdoba y Ushuaia. Rosario 2000 falla si no se mandan `geoCoordinates` |
| **VTEX: Daytona** | No aplica | — | Son combos con colocación: solo retiro en el AMBA |
| **Tiendanube** (10 tiendas) | **No** | El calculador es `POST /envio/`, y el robots.txt de las 10 tiendas dice `Disallow: /envio/`. No se pidió nunca | La API oficial pide el token de una app instalada en cada tienda |
| **WooCommerce** (La Ruta OK, Allende, Ceridono) | Técnicamente sí (carrito efímero de la Store API), pero **no hay ningún costo que leer** | `GET /cart` → `add-item` → `update-customer` con el CP → `remove-item` | La Ruta OK: «Envío gratuito» en los 8 CP, también con 1 L. Allende: «A convenir con el vendedor», salvo Neuquén (gratis). Ceridono: «Coordinar envío con asesor» (el método es `free_shipping` con precio 0: leerlo como gratis sería inventar) |
| **Transportistas** (OCA, Correo Argentino, Andreani) | **No sin contrato** | Las APIs de cotización piden CUIT/operativa, credenciales o contrato y cliente; Correo Argentino está detrás de Incapsula | La única tabla pública es el PDF de OCA (tarifario 09/2026, 2 a 5 kg a domicilio: $18.444 Local a $27.645 Nacional 2), pero no dice qué par de CP cae en qué zona, y sus términos prohíben republicarla. OCA no hace envíos a domicilio ni a sucursal hacia Tierra del Fuego | **Actualización 2026-11-24: Correo Argentino tiene API oficial MiCorreo (`/token`, `/users/validate`, `/rates`) y el usuario tiene credenciales; ver `correo.py` y CLAUDE.md. Sin tabla de tarifas todavía.**
| **SEPA** | No hace falta | — | Ya es el precio de la góndola en cada provincia (878 filas por día en las 24). Es «precio en sucursal física», no «puesto» |

**Cobertura de la prueba:** se probaron solo 8 de los 24 CP de capital (CABA 1001, Córdoba 5000, Rosario 2000, Mendoza 5500, Neuquén 8300, Salta 4400, Ushuaia 9410 y Posadas 3300). Las otras 16 capitales no se probaron. Un CP que dé 404/424 o error se guarda como `sin_cotizacion`.

**Ubicación del vendedor** (para qué sirve y para qué no):
- ML: `seller_address` y `/users/{id}` dan 403 sin token. Con token se podrían leer, pero **no hacen falta**, porque la cotización ya incluye el origen. Y por la regla del repo no se usarían para poner un precio en una provincia.
- VTEX: la simulación nombra el depósito o local que despacha (`deliveryIds[].warehouseId`, `courierName`, `pickupStoreInfo.address`). Es texto libre: sirve para mostrar, no como campo.
- Tiendanube y Woo: dirección declarada en `/contacto/` o en el footer. LS Palermo AR-C, Casa González AR-Q, Exporepuestos, Lubrimaster, Net Renault, Olafil y La Ruta OK AR-B, Gramaglia AR-S, Allende AR-R, Ceridono AR-T. Rano, Lubricentro DG y Toro Oils no la publican. Es un dato declarado, no verificado.

## 2. Diseño propuesto (mínimo y honesto)

### Dato nuevo: `data/envios/AAAA-MM.csv`

Va aparte de `data/obs/`: la columna `provincia` de `obs` no se toca, y los avisos online siguen siendo `online`.

```
fecha,capturado,fuente,url,producto_id,litros,unidades,precio,cp_destino,provincia_destino,costo_envio,metodo,plazo_h,estado,deposito
```

- `fuente`, `url`, `producto_id`, `litros`, `unidades` y `precio`: los del aviso de `obs` que se cotizó, copiados para que la fila se entienda sola y se pueda unir.
- `cp_destino`: el CP de la capital de la provincia (tabla fija de 24 filas, a mano). `provincia_destino` sale **de esa tabla**, nunca de la respuesta: ML manda `destination.state` null para 2000 y 3300.
- `costo_envio`: lo que paga el **comprador**, en ARS. ML: `options[].cost`. VTEX: `slas.price` + `availableDeliveryWindows[].price`, pasados de centavos a pesos. `0` solo si la tienda dice gratis.
- `metodo`: `domicilio|agencia|retiro`. Se guarda la opción más barata de cada método, no solo la mínima total, así el visor puede elegir «solo domicilio».
- `estado`: `ok|no_envia|sin_cotizacion`.
  - `no_envia`: la tienda dice que no entrega (VTEX `cannotBeDelivered`, «no disponible»). Es un dato.
  - `sin_cotizacion`: error HTTP o 404/424 de ML. Es un hueco.
  - En los dos casos `costo_envio` queda **vacío**, nunca 0.
- `deposito`: el texto de VTEX si viene; vacío en ML.
- Una corrida no duplica: reemplaza las filas de esa `fuente` y `fecha`, igual que `obs`.

### Cálculo

- **Precio puesto** de un aviso en una provincia = `precio + costo_envio`, los dos del **día de la cotización** (la fila de `data/envios/` guarda el `precio` del aviso de ese día), y el precio puesto lleva esa fecha. Nunca se suma un envío de un día al precio de otro.
- Como ML rota (k = 7), cada día solo hay cotización para más o menos 1/7 de las combinaciones. Por eso `/api/puesto` y el Mapa usan una **ventana de al menos 7 días** (default 7), que termina en el último día con cotizaciones. Cada aviso cuenta una vez, con su cotización más reciente de la ventana y su fecha. El mínimo y la mediana por provincia se toman sobre esos avisos fechados. Fuera de la ventana no se arrastra nada.
- $/L puesto = precio puesto / (litros × unidades), con la misma sanidad que la vitrina.
- Por provincia y producto se informan los dos números, porque cuentan cosas distintas:
  - **mínimo**: «lo más barato que se consigue puesto acá». Es la lógica del vendedor más cercano, y se muestra con fuente y vendedor.
  - **mediana**: lo típico. Una mediana nunca mezcla fuentes, como en el resto del repo.
- Nunca entra al índice, a la vitrina ni al comparador de $/L de góndola. Es una capa aparte.
- La API nueva es `GET /api/puesto?producto_id=<id>[&dias=N]` (`dias` de 7 a 366, default 7), con la misma nota que `/api/provincias`. Responde `{provincia, cp, fuente, minimo{precio_puesto, precio, envio, vendedor, url}, mediana_litro_puesto, n, n_no_envia, n_sin_cotizacion, fecha}`.

### Dónde corre y cuántas requests

| fuente | dónde | qué se cotiza | requests por día |
|---|---|---|---|
| ML | **en la Action, con el token**, dentro del paso `ml`: el mismo endpoint con `Authorization`, sin tocar el refresh fuera de la Action. Sin token también anda, pero choca con robots (ver decisiones) | solo productos YPF, una combinación vendedor×producto×envase (227 el 2026-11-22), rotando las 24 provincias en **k = 7 grupos** como Tiendanube: cada combinación se cotiza a todas las provincias una vez por semana | unas 800 (unos 13 min más; ML ya usa unos 14 de los 30 del job, así que quedan unos 28: muy justo). Alternativa: 8 capitales todos los días, unas 1.800 (unos 30 min, no entra en el job) |
| Norauto y Easy | en casa (`recolector_casa`), como paso aparte | si se confirma que la tarifa depende del bulto y del CP y no del producto (ver abajo): **un SKU por envase** (1, 4 y 5 L) × 24 CP | unas 150 (unos 75 por host, 1 req/s) |
| Carrefour y Masonline | en casa, **semanal**, si se quiere | disponibilidad por provincia de cada aviso YPF (con `geoCoordinates` de cada capital, tabla fija) | unas 1.150 por semana |
| Tiendanube, Woo, transportistas | no corren | — | 0 |

**Resuelto el 2026-11-24 (fase 2): el envío depende del producto, no del envase.** Shell Helix HX7 10W40 4 L (item 1292): CABA 1001 domicilio AMBA 13.452 y Andreani 27.921 más retiros en sucursal (0 y 13.450), Córdoba 5000 Andreani 30.631, Salta 4400 Andreani 33.510. Total Quartz 7000 10W40 4 L (item 538): CABA solo retiros a 0; Córdoba y Salta sin slas y `messages[].code == "cannotBeDelivered"`. Por eso se cotiza **cada aviso** (`recolectar.envios_vtex`, k=7) y solo Norauto; Easy queda afuera por términos (§4.3). Lo que sigue es el plan original, ya superado en ese punto: En Norauto y Easy el plan supone que el envío depende del envase y la provincia, no del aviso, y que el precio puesto sale de `precio del aviso + envío del envase en esa provincia`, del mismo día y la misma tienda. **Eso no está verificado**: se vio un solo SKU por tienda. Antes de implementar hay que cotizar dos SKU distintos del mismo envase en dos CP. Si la tarifa da igual, vale un SKU por envase. Si no, hay que cotizar cada aviso, unos 61 × 24 ≈ 1.460 requests por día entre las dos, o hacerlo semanal.

### Cómo se vería en el Mapa

- Un selector de capa nuevo: **«Sucursal física (SEPA)»**, que es lo de hoy, y **«Puesto en provincia (online + envío)»**. No se mezclan en el mismo color.
- En «puesto», cada provincia se pinta con el **mínimo** $/L puesto. El tooltip muestra el mínimo con fuente, vendedor y envío, la mediana y `n`. Con un clic se ve la lista de avisos.
- Una provincia sin cotización va **gris rayado**, con su motivo: «sin cotización (ML 424)» o «ninguna tienda envía»; Ushuaia en Carrefour es «no envía», que es un dato. **Nunca** se pinta con el color de la vecina.
- Nota fija al pie: «Envío cotizado a la capital de cada provincia (CP de la capital), como comprador anónimo, el día indicado. El interior puede costar distinto. Mercado Libre con usuario logueado o con Mercado Puntos puede ser más barato. No es tiempo real.»
- Para las tiendas Tiendanube y Woo, en la ficha (no en el mapa): «despacha desde <provincia> según la propia tienda (fuente, fecha); envío: gratis | a convenir». «A convenir» no suma a ningún precio puesto.

## 3. Qué NO hacer

- **No usar tarifas supuestas.** Nada de «Córdoba→Córdoba = zona Local de OCA» ni de un costo por kilómetro: OCA no publica el mapa de zonas y asignarlo sería inventar.
- **No interpolar** provincias sin cotización desde la vecina o desde la mediana nacional. Sin cotización, la provincia queda vacía con su motivo.
- **No deducir el origen** del vendedor: ni del `seller_address` de ML, ni de la característica telefónica, ni del CUIT, ni del `base_cost` más bajo. Y no escribir nada nuevo en `obs.provincia`: los avisos online siguen `online`.
- **No leer «free_shipping» ni precio 0 como gratis** sin mirar el nombre: Ceridono es «coordinar con asesor». En VTEX, no leer un solo campo: el costo puede estar en `slas.price` o en las franjas.
- **No pedir `/envio/` de Tiendanube** (robots lo prohíbe) ni armar un loop diario de carritos Woo sin permiso de la tienda.
- **No mezclar** el precio puesto con el $/L de góndola, el índice ni la vitrina, ni sumar SEPA y online en una mediana.
- **No cotizar los 1.855 avisos ML × 24 provincias** (44.520 requests por día). Solo productos YPF, con rotación.
- **No usar el token de ML fuera de la Action**: el refresh rota en cada canje.

## 4. Decisiones que tenés que tomar

1. **Mercado Libre y robots.txt.** El `robots.txt` de api.mercadolibre.com dice `Disallow: /` para todos. El repo ya usa la API (`ml_cat` sin token, `ml` con token) bajo los Términos del Programa de Desarrolladores. Opción recomendada: correr `shipping_options` **con el token en la Action**, como el resto de `ml`. ¿Va así o se deja afuera ML?
2. **Volumen de ML.** Hay dos opciones:
   - Rotación semanal de las 24 provincias: unas 800 requests por día, unos 13 min más. Sumado a los unos 14 que ya usa `ml`, quedan unos 28 de los 30 min del job: entra muy justo.
   - 8 capitales todos los días: unas 1.800 requests, unos 30 min más. No entra en el job actual: necesita un job propio o subir el timeout.
3. **Términos de uso de las tiendas VTEX.** Solo se miró robots.txt: bloquea `/checkout/*` pero no `/api/checkout/`. ¿Leemos los términos de Norauto y Easy antes de sumarlas? Recomendado: sí.

### 4.3 Veredicto de términos de las tiendas VTEX (leídos el 2026-11-24)
- **Norauto: permitido.** Términos y condiciones (https://www.norauto.com.ar/ayuda/Terminos-y-condiciones): sin cláusula contra bots ni extracción; la 1.11 protege el contenido pero no prohíbe leerlo; `robots.txt` no bloquea `/api/`. Se implementó (`vtex_norauto_envios`).
- **Easy: dudoso, no se implementa.** Sección «Utilización del PORTAL. Propiedad intelectual»: «cualquier retransmisión, reproducción, alteración, publicación o utilización de cualquier material… se encuentra estrictamente prohibido».
- **Carrefour: dudoso, no se implementa.** Punto 12) Propiedad Intelectual: «uso indebido y/o su copia, imitación, utilización o reproducción total o parcial de dichos contenidos quedan prohibidos, salvo previa autorización expresa y por escrito de INC S.A.» (el patrón de Coto).
- **Más Online: no evaluable**: los términos publicados están vacíos. No se implementa.
- Las cláusulas de Easy y Carrefour también alcanzan a la lectura de catálogo que `vtex_easy` y `vtex_carrefour` ya hacen hoy. **Decisión pendiente del usuario**; no se tocaron esas fuentes.
4. **Carrefour y Masonline.** ¿Interesa «se consigue o no en esta provincia» (semanal), o se dejan afuera porque su flete es plano?
5. **Mínimo, mediana o los dos** como color del mapa. Recomendado: mínimo para el color y mediana en el tooltip.
6. **`origen_despacho` declarado** de Tiendanube y Woo (provincia + texto + URL + fecha, en el seed): ¿se carga solo para mostrarlo en la ficha?
7. **Contrato con OCA o Andreani.** Si YPF tiene uno, con sus credenciales se podrían cotizar los 24×24 pares por mes para las tiendas sin cotizador. Sin contrato, ese camino no existe.
