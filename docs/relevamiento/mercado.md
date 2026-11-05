# Indicadores de mercado (relevamiento 2026-11-05)

Propuesta para sumar la pestaña "Mercado" a LUBRICANTES. Las series se probaron con curl el 2026-11-05, salvo donde se marca.

## 0. Lo primero: market share oficial de la Secretaría de Energía (verificado)

La Secretaría de Energía (Res. SE 1104) publica las **ventas de lubricantes por empresa, canal y provincia, por mes, desde 2010-01 hasta 2026-09**. Es el dato más valioso de todo el relevamiento: muestra cuánto vende YPF de verdad, y no solo cuánto cobra.
- **Fuente:** `http://datos.energia.gob.ar/dataset/5bdc436c-60d4-4c86-98ab-59834d047700/resource/f0e4e10a-e4b8-44e6-bd16-763a43742107/download/ventas-excluye-ventas-a-empresas-del-sector-.csv`. Respondió HTTP 200, pesa 769 MB, la última modificación es del 2026-10-26 y el servidor no acepta `Range` (no se puede bajar solo una parte).
- **Productos que trae:** `Lubricantes automotrices(m3)`, `Lubricantes industriales(m3)`, `Lubricantes marinos(m3)`, `Bases Lubricantes(m3)` y `Grasas(Ton)`.
- **Muestra real:** en 2026-09 se vendieron 13.430 m³ de automotrices. YPF tuvo 37,7%, Shell 23,6%, Total 13,4%, PAE (Axion) 11,5%, Petronas 9,0%, Fercol 4,0% y DAPSA 0,8%.
- **Tendencia contra 2019-09:** YPF bajó de 42,8% a 37,7% y PAE subió de 4,3% a 11,5%. En 2025, YPF tuvo 35,2% en automotrices y 47,8% en industriales.

**Cómo se arma el share:**
- `share(e,m) = cantidad(e,m) / Σ cantidad(m)`, para cada producto.
- Se puede abrir por canal (Al Público, Agro, Otras Empresas, Transporte de Carga) y por provincia.
- Conviene mostrarlo en tres vistas:
  - Barras apiladas de 100%, con el share mensual de los últimos 36 meses.
  - Una línea con YPF y los móviles de 12 meses.
  - Un mapa o tabla por provincia con la variación interanual del share de YPF.

**Límites (hay que escribirlos en el visor):**
- Es el share **entre las empresas que declaran**. Mobil, Castrol, Motul, Liqui Moly y los importadores chicos no figuran.
- Es volumen que vende la petrolera (sell-in), no lo que compra el consumidor final.
- No viene abierto por marca comercial (Elaion, Helix), solo por empresa.

**El mismo CSV sirve para dos cosas más:**
- **Gasoil por canal (verificado):** permite medir la actividad diésel. Agro pasó de 238.413 m³ en 2025-09 a 233.068 en 2026-09, y transporte de carga de 134.484 a 142.827.
- **Cruce con nuestros precios:** el volumen de YPF contra la brecha de precio YPF vs competencia, para ver si cuando se abre la brecha se pierde share.

Hay otros dos CSV de Energía que **están verificados pero conviene dejar para una segunda etapa**: importación y exportación de lubricantes (`.../ea145b70-.../importaciones-exportaciones-a-partir-del-2016-.csv`, 188 MB, llega a 2026-10) y producción por refinería (`.../78c4648c-.../subproductos-obtenidos.csv`, 33 MB, llega a 2026-09).

## 1. Los 10 indicadores, en orden de prioridad

Todos salen de la API de Series de Tiempo de datos.gob.ar, que no pide token: `https://apis.datos.gob.ar/series/api/series/?ids=ID&format=csv`.

| # | Indicador | Serie probada (id) | Frec. | Último dato | Por qué mueve la demanda de lubricantes | En el visor | Cruce con nuestros precios |
|---|---|---|---|---|---|---|---|
| 1 | Ventas de lubricantes por empresa | Energía (CSV de arriba) | M | 2026-09: 13.430 m³ (automotrices) | Es la demanda misma | Share apilado + línea | Share de YPF contra la brecha de precio |
| 2 | Peajes (tránsito vehicular) | `302.3_S_ORIGINALJES_0_S_17` | M | 2026-07: 135,60 | Más km recorridos, más cambios de aceite de flota liviana | Línea con variación interanual | Variación interanual de peajes contra precio real |
| 3 | Nafta y gasoil vendidos por YPF | `365.3_VENTAS_DE_YPF_I__20` (naftas), `365.3_VENTAS_DE_YPF__20` (gasoil) | M | 2026-08: 448.740 y 668.021 m³ | El combustible es proxy directo de km y horas-motor; un litro de lubricante acompaña a cierta cantidad de litros de combustible | Línea de variación interanual | Ratio lubricante/combustible de YPF (con la SE) |
| 4 | Transporte de carga | `302.3_S_TENDENCIRGA_0_S_30` + EMAE Transporte `11.3_EMC_2004_M_25` | M | 2026-07: 90,71 y 185,64 | Aceite diésel pesado (camiones): los km de flota marcan los cambios | Línea | Precio del aceite diésel contra la actividad |
| 5 | EMAE Agro | `11.3_ISOM_2004_M_39` | M | 2026-07: 119,65 (en junio 208,35 por la cosecha) | Horas-motor de tractores y cosechadoras: aceites diésel, hidráulicos y de transmisión, con pico entre abril y junio | Barras mensuales con estacionalidad | Canal Agro de la SE contra el EMAE Agro |
| 6 | EMAE Minas y canteras | `11.3_ISD_2004_M_26` | M | 2026-07: 139,39 | Equipos pesados en Vaca Muerta y en minería | Línea | — |
| 7 | IPI manufacturero + ISAC | `453.1_SERIE_DESEADA_0_0_24_58` (IPI desestacionalizado), `33.2_ISAC_SIN_EDAD_0_M_23_56` (ISAC desestacionalizado) | M | 2026-08: 114,29 y 140,74 | Aceites industriales e hidráulicos; maquinaria vial | Dos líneas | Lubricantes industriales de la SE contra el IPI |
| 8 | Ventas de 0 km | `38.3_ANIT_1994_M_21` (total), `38.3_ANIU_1994_M_27` (utilitarios) | M | 2026-08: 39.068 y 10.677 unidades | Parque nuevo: primer servicio, y aceites sintéticos premium en autos nuevos | Barras de unidades + acumulado 12 meses | Mix premium (sintéticos) de la página |
| 9 | Salario privado registrado | `149.1_SOR_PRIADO_OCTU_0_25` | M | 2026-07: 9.879,87 | El poder de compra decide si el cambio de aceite se posterga o se baja a un mineral | Indicador compuesto (sección 2) | Asequibilidad |
| 10 | IPC general, Transporte y tipo de cambio | `148.3_INIVELNAL_DICI_M_26`, `146.3_ITRANSPNAL_DICI_M_23`, `92.2_TIPO_CAMBIION_0_0_21_24` (diario) | M / D | 2026-08: 12.276,77 y 12.965,12; tipo de cambio 2026-08-31: 1.509,47 | Sirven como deflactores | No es un gráfico propio: alimenta los compuestos | Precio real y precio en USD |

Hay una serie que puede ser útil pero no está verificada. El IPC de la subclase "combustibles y lubricantes" no está en datos.gob.ar. Probablemente esté en `api.indec.gob.ar/v1/ipc_nacional`, pero esa API devolvió HTTP 401 porque pide token, así que no lo vi.

## 2. Indicadores compuestos propios (no los publica nadie)

1. **Precio real YPF:** `P_real(m) = P_YPF(m) / IPC_general(m) × IPC_general(base)`.
   - `P_YPF(m)` es la mediana del $/L de las equivalencias YPF en `data/obs/` durante el mes.
   - Variante: dividir por `IPC_Transporte` para ver si el lubricante se encarece contra el resto del costo de usar el auto.
2. **Asequibilidad del cambio de aceite:** `horas = (precio de 4 L de 10W40 YPF) / (salario diario)`.
   - Problema: el índice de salarios es un índice (base oct-2016) y no un monto en pesos. Para pasarlo a pesos hace falta un salario nominal de anclaje.
   - El RIPTE (`158.1_REPTE_0_0_5`) existe pero vino **vacío**. Mientras no haya anclaje, mostrarlo como índice: `(P_YPF / Salario_idx)`, base 100 en el primer mes con datos.
3. **Precio en dólares:** `P_USD(d) = P_YPF(d) / TC_valuación(d)`. Es diario y cruza directo con nuestras observaciones diarias.
4. **Índice de demanda potencial (liviano + pesado):** `IDP = 0,5·idx(peajes) + 0,3·idx(gasoil de transporte de carga, SE) + 0,2·idx(EMAE Agro)`, con base 100 en 2023.
   - **Los pesos son un supuesto.** Hay que calibrarlos con una regresión contra el volumen de lubricantes de la SE (indicador 1) antes de mostrarlo como algo más que exploratorio.
5. **Elasticidad de la brecha:** comparar `Δshare_YPF(m)` contra `brecha(m)`, donde la brecha es el precio de YPF dividido por la mediana de la competencia en los mismos pares de `seed/equivalencias.csv`.
   - Se muestra como un scatter mensual.
   - El histórico de precios propio es corto, así que **por ahora es una idea, no un resultado**.

## 3. Signos convencionales del INDEC y cómo respetarlos

Esta tabla está transcripta de la spec OpenAPI de api.indec.gob.ar:

| Signo | Significado |
|---|---|
| `*` | Dato provisorio |
| `**` | Dato preliminar |
| `e` | Estimado por extrapolación o proyección |
| `i` | Estimado por imputación |
| `u` | Calidad inferior al estándar |
| `-` | Cero absoluto |
| `.` | Dato no registrado |
| `...` | No disponible a la fecha de presentación |
| `///` | Dato que no corresponde presentar |
| `s` | Confidencial por secreto estadístico |

**Reglas en el visor (coinciden con la regla del repo de no inventar datos):**
- Un valor null o vacío **nunca se muestra como 0**. Se deja el hueco en la línea, sin interpolar, y en la tabla y el tooltip va el signo que corresponda (`...`, `///`, `s` o `.`). Solo `-` vale 0.
- Si el valor viene con `*`, `**`, `e`, `i` o `u`, se pone el sufijo junto al número y el punto va con trazo punteado.
- datos.gob.ar devuelve null sin ningún signo. Ese caso se muestra como `...` con la leyenda "sin dato publicado a AAAA-MM-DD". Ejemplo real: el EMAE de 2026-08 viene vacío cuando se lo combina con otras series.
- Las variaciones (interanuales, compuestos) se calculan solo si los dos extremos existen. Si falta alguno, el resultado es `...`.
- Al pie de cada gráfico va "Fuente: INDEC, vía datos.gob.ar (CC-BY 4.0)" o "Fuente: Secretaría de Energía, Res. 1104".
- **No verificado:** que en la API de INDEC el signo viaje en el campo `observaciones` lo deduje del esquema, porque sin token no vi un dato real.

## 4. Diseño técnico mínimo (stdlib, igual que el resto del repo)

- **`macro.py`:** lo llamo así y no `indec.py` porque hoy no usa la API de INDEC.
  - `series()` baja de datos.gob.ar las ids de una lista fija en `seed/macro_series.csv` (`id,nombre,grupo,frec,unidad`), todas juntas en `ids=a,b,c&format=csv`, y escribe `data/macro/series.csv` en formato largo (`fecha,id,valor,signo`).
  - `energia()` lee el CSV de 769 MB por streaming (`urllib` + `csv` + `io.TextIOWrapper`, sin guardarlo en disco). Se queda con lo que tenga `'ubric'` o `Grasas` en `producto`, o que empiece con `Gasoil`, y escribe `data/macro/energia_lub.csv` (`mes,empresa,producto,canal,provincia,cantidad`). Agregado queda en unos pocos MB.
  - `demo()` con `assert` para: null pasa a `...` (nunca a 0), share que suma 1, interanual con un extremo faltante que da `...`, y deflactor.
- **Action:** `macro.py series` va en la misma corrida diaria, porque es barato y el tipo de cambio es diario. `macro.py energia` va en un job aparte (`schedule` mensual el día 28, más `workflow_dispatch`), porque son unos 2 a 3 minutos de descarga. Si la fuente falla, se registra en `data/fuentes.csv` y no se escribe nada.
- **`server.py`:** `GET /api/macro?ids=...` y `GET /api/macro/share?producto=...&canal=...`, calculados en memoria desde `data/macro/` con la misma clave que el resto de la API.
- **`site/index.html`:** pestaña **Mercado** con tres bloques (Share oficial, Actividad, Precio real y asequibilidad), usando el SVG propio que ya existe y sin librerías nuevas.

**Riesgos:**
- datos.gob.ar tiene ids que existen pero vienen vacíos o cortados: el IPI gasoil, el EMAE construcción mensual, el RIPTE, y las importaciones `74.3_IICL`, que terminan en 2003. Hay que validar con `count>0` y una fecha mínima en cada corrida, y avisar en Fuentes.
- El CSV de Energía puede cambiar de URL o de columnas, porque es CKAN: conviene resolver la URL con `package_show` y validar el encabezado. Además, 769 MB y 133 s pueden crecer y acercarse al timeout del job.
- Cambios de base del INDEC (EMAE base 2004, IPC dic-2016): los índices se guardan tal cual y los compuestos se rebasan en código.
- La API de INDEC pide token JWT que vence a los 12 meses y se ve una sola vez. Solo hace falta si querés la subclase de lubricantes del IPC o el IPI minero. Para eso tenés que registrarte vos y guardar el token como secret `INDEC_TOKEN` en la Action. Render no lo necesita, porque solo lee `data/`.

## Lo que no está verificado

- La serie `41.3_L_0_A_11` ("lubricantes, miles de m³", de MECON) da valores que no son creíbles. Está descartada: la usable es la de la SE.
- `74.2_IICL_0_T_42` (importaciones trimestrales de combustibles y lubricantes): no la probé.
- El dataset `participacion-en-el-mercado-por-bandera-de-estaciones-de-servicio` y el de precios mayoristas de la Res. 1104: no los probé.
- Patentamientos y parque automotor no están en ninguna de las APIs probadas (son de DNRPA o ACARA). El único proxy es el de ventas de 0 km.
- Los pesos del índice de demanda potencial y cualquier elasticidad son supuestos hasta calibrarlos.


---

## Relevamiento: indec-api

Francisco —

# API INDEC (api.indec.gob.ar) para indicadores de mercado de lubricantes, probada el 2026-11-05

## 1. Documentación

**Spec:** está en `GET https://api.indec.gob.ar/api/openapi?v=2` (devolvió HTTP 200, 170 KB, OpenAPI 3). La página /docs se arma en el navegador y lee ese archivo.

**URL base:** `https://api.indec.gob.ar/v1/`. Es una API estilo PostgREST y solo devuelve JSON.

**Autenticación: sí, hace falta token.** Cada pedido lleva el header `Authorization: Bearer <JWT>`.
- Para conseguirlo hay que registrarse con correo, nombre y organización, verificar el correo con un código OTP y generar el token desde el perfil.
- El token se muestra una sola vez y vence a los 12 meses. Si se regenera, el anterior deja de valer.
- **Probado sin token:** `GET /v1/ipc_nacional?limit=1` y `GET /v1/estimador-mensual-de-actividad-economica-nivel-general?limit=1` devolvieron los dos HTTP 401 con `{"code":"42501","message":"permission denied for schema api"}`.
- No creé la cuenta: registrarse lo tenés que hacer vos. Por eso **no pude ver ni un dato real de esta API**.

**Cómo se consulta:**
- Parámetros: `select`, `limit`, `offset`, `order`.
- Filtros por columna: `?col=eq.valor`. Operadores: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `like`, `ilike`, `in`, `is`.

**Paginación:**
- Cada respuesta trae como máximo 1000 filas.
- Hay que ordenar siempre por la clave primaria completa, que la spec indica en cada endpoint.
- Con el header `Prefer: count=exact`, el total llega en `Content-Range` (por ejemplo `0-999/103545`) y el status pasa a 206 si la respuesta es parcial.

**Errores:** vienen como JSON con `code`, `message`, `details` y `hint`.
- 400: filtro mal formado.
- 401: falta el token o es inválido.
- 403: sin permiso sobre el recurso.

**Límites:** el FAQ dice que hay límites según el tipo de cuenta y remite a los términos. Los términos (/ayuda/terminos) **no dicen ningún número**.

**Licencia y cita:**
- Los términos hablan de "política de datos abiertos", de secreto estadístico (Ley 17.622 y Decreto 726/2020) y de jurisdicción argentina.
- El FAQ pide citar "Fuente: INDEC" junto con el servicio de datos consultado.
- No nombran una licencia formal.

**Aviso de la propia documentación:** los totales sumados pueden no coincidir por redondeo, y las variaciones calculadas pueden diferir de las de los informes técnicos.

**Tabla de signos convencionales / razón de nulo (transcripta de la spec):**

| Signo | Significado |
|---|---|
| `*` | Dato provisorio |
| `**` | Dato preliminar |
| `e` | Dato estimado por extrapolación, proyección |
| `i` | Dato estimado por imputación |
| `u` | Dato de calidad inferior al estándar |
| `-` | Cero absoluto |
| `.` | Dato no registrado |
| `...` | Dato no disponible a la fecha de presentación de los resultados |
| `///` | Dato que no corresponde presentar |
| `s` | Dato confidencial por aplicación de las reglas del secreto estadístico |

**Cómo se aplica la tabla:** los endpoints de series tienen `valor` (número o null) y `observaciones` ("Notas necesarias para el valor informado").
- Cuando `valor` viene null, el signo explica el motivo y es lo que hay que mostrar en lugar de un 0 o un hueco.
- Cuando el valor existe, el signo es un sufijo de calidad: `*`, `**`, `e`, `i`, `u`.
- Lo de que el signo viaja en `observaciones` es mi deducción a partir del esquema: no lo pude ver en un dato real.

**Endpoints (19 tablas):**

| Tema | Endpoints |
|---|---|
| Producción industrial | `/ipi_manufacturero` (desde 2016, base 2004; columnas `codigo_CLaNAE_2004`, `serie` original/desestacionalizada/tendencia-ciclo), `/ipi_minero` |
| Actividad económica | `/estimador-mensual-de-actividad-economica-nivel-general`, `/estimador-mensual-de-actividad-economica-sectores` (desde 2004, `codigo` = letra ClaNAE04) |
| Precios y salarios | `/ipc_nacional` (desde dic 2016, aperturas por región, división, grupo, clase y subclase), `/indice_salarios`, `/sipm_precios_mayoristas`, `/icc_precios_construccion`, `/redeterminacion_precios_contratos_obras_publicas`, `/valorizacion_canastas_cba_cbt`, `/canasta-crianza` |
| Empleo y pobreza (EPH) | `/mercado_trabajo_eph` (trimestral), `/pobreza_eph` (semestral) |
| Comercio exterior | `/comercio_exterior_exportacion_bienes`, `/comercio_exterior_importacion_bienes`, `/comercio_exterior_nomenclaturas` |
| Población | `/proyecciones_poblacion_nacional_2022_2040`, `/proyecciones_poblacion_jurisdiccion_2022_2040`, `/estimaciones_poblacion_departamento_2022_2035` |

**Lo que este catálogo no tiene:** ISAC, supermercados, patentamientos, automotores ni servicios públicos (peajes).

## 2. Alternativa sin token: la API de Series de Tiempo de datos.gob.ar

`apis.datos.gob.ar/series` publica las mismas series de INDEC sin pedir clave, bajo licencia CC-BY 4.0. Se consulta con `GET https://apis.datos.gob.ar/series/api/series/?ids=ID&last=N&format=json|csv`, y los ids se buscan en `/series/api/search/?q=`.

**Series que devolvieron datos (HTTP 200).** Los ids son los reales y las fechas son las del último dato:

| id | Serie | Frec. | Último dato |
|---|---|---|---|
| 143.3_NO_PR_2004_A_21 | EMAE original, base 2004 | M | 2026-07: 151.55 |
| 143.3_NO_PR_2004_A_31 | EMAE desestacionalizado | M | 2026-07: 149.65 |
| 11.3_EMC_2004_M_25 | EMAE Transporte, almacenamiento y comunicaciones | M | 2026-07: 185.64 |
| 11.3_VMASD_2004_M_23 | EMAE Industria manufacturera | M | 2026-07: 119.13 |
| 11.3_ISOM_2004_M_39 | EMAE Agricultura, ganadería, caza y silvicultura | M | 2026-07: 119.65 (junio: 208.35, por la cosecha) |
| 11.3_ISD_2004_M_26 | EMAE Explotación de minas y canteras | M | 2026-07: 139.39 |
| 11.3_AGCS_2004_M_41 | EMAE Comercio mayorista, minorista y reparaciones | M | 2026-07: 146.58 |
| 11.2_VMATC_2004_T_12 | EMAE Construcción | T | 2026-04: 127.46 |
| 453.1_SERIE_ORIGNAL_0_0_14_46 | IPI manufacturero, nivel general original | M | 2026-08: 119.29 |
| 453.1_SERIE_DESEADA_0_0_24_58 | IPI nivel general desestacionalizado | M | 2026-08: 114.29 |
| 453.2_REFINACIONEAR_0_0_45_82 | IPI Refinación del petróleo, coque y combustible nuclear | M | 2026-08: 134.71 |
| 453.2_OTROS_PRODION_0_0_26_12 | IPI Otros productos de la refinación del petróleo (donde caen los lubricantes) | M | 2026-08: 123.93 |
| 453.2_NAFTASTAS_0_0_6_13 | IPI Naftas | M | 2026-08: 178.83 |
| 453.2_VEHICULOS_RES_0_0_21_54 | IPI Vehículos automotores | M | 2026-08: 257.70 |
| 33.2_ISAC_NIVELRAL_0_M_18_63 | ISAC nivel general | M | 2026-08: 146.86 |
| 33.2_ISAC_SIN_EDAD_0_M_23_56 | ISAC desestacionalizado | M | 2026-08: 140.74 |
| 33.4_ISAC_CEMENAND_0_0_21_24 | ISAC insumo cemento portland | M | 2026-08: 156.78 |
| 148.3_INIVELNAL_DICI_M_26 | IPC nacional nivel general, base dic 2016 | M | 2026-08: 12276.77 |
| 148.3_INUCLEONAL_DICI_M_19 | IPC núcleo nacional | M | 2026-08: 12445.80 |
| 146.3_ITRANSPNAL_DICI_M_23 | IPC Transporte, nacional | M | 2026-08: 12965.12 |
| 149.1_TL_INDIIOS_OCTU_0_21 | Índice de salarios total, base oct 2016 | M | 2026-07: 9708.64 |
| 149.1_SOR_PRIADO_OCTU_0_25 | Salarios, sector privado registrado | M | 2026-07: 9879.87 |
| 302.3_S_ORIGINALJES_0_S_17 | Servicios públicos: peajes, serie original (proxy del tránsito vehicular) | M | 2026-07: 135.60 |
| 455.1_VENTAS_PRETES_0_M_25_98 | Ventas en supermercados a precios constantes | M | 2026-04: 21789.04 (último que vi) |
| 455.1_TARJETAS_CITO_0_M_16_85 | Supermercados, ventas con tarjeta de crédito | M | 2026-07: 1086065583 (miles de $) |
| 41.3_AA_0_A_23 | Automotores: automóviles en unidades (fuente MECON) | M | 2026-07: 81.8 |

**Series dudosas o rotas (no usar sin revisar):**
- **Lubricantes y kerosene en miles de m³** (`41.3_L_0_A_11` y `41.3_K_0_A_8`, fuente MECON sobre base INDEC): dan 1282.8 y 580.4 para 2026-08. La distribución 41.3 se llama "Valores anuales" y los números no son creíbles como miles de m³ mensuales. Es la única serie de volumen de lubricantes que encontré, así que conviene validarla contra la Secretaría de Energía.
- **Importaciones de combustibles y lubricantes** (`74.3_IICL_0_M_42`): la búsqueda dice que llega a 2026-08, pero los datos terminan en 2003-06. La versión trimestral `74.2_IICL_0_T_42` no la probé.
- **Metadata sin datos** (la API devuelve 200 con el array vacío): `11.3_VMATC_2004_M_12` (EMAE construcción mensual), `453.2_GASOILOIL_0_0_6_78` (IPI gasoil), `41.3_CP_0_A_16` (cemento), `41.3_GO_0_A_7` (gasoil m³), `455.1_SALON_VENTTAS_0_M_12_82`.

**Lo que no encontré o no probé:**
- La subclase del IPC "combustibles y lubricantes para vehículos" no tiene serie en datos.gob.ar. Seguramente esté en `/ipc_nacional` filtrando `descripcion=ilike.*lubric*`, pero eso no lo probé porque pide token.
- **Patentamientos:** INDEC no los publica (son de DNRPA y ACARA).
- **IPI minero:** no le encontré id en datos.gob.ar. Sí está en la API de INDEC (`/ipi_minero`).
- EPH no la probé.

## 3. Indicadores posibles para la página (ideas, ninguna implementada)

1. **Demanda de cambio de aceite (flota liviana):** peajes + IPC Transporte deflactado por IPC general, o sea el precio relativo de usar el auto.
2. **Lubricantes pesados y flota:** EMAE Transporte + ISAC + EMAE Minas y canteras + EMAE Agro (con pico de cosecha entre abril y junio). Sirve para anticipar la estacionalidad de los aceites de motor diésel, hidráulicos y de transmisión.
3. **Industria e insumos:** IPI nivel general como proxy de aceites industriales e hidráulicos; IPI "otros productos de la refinación" como proxy de oferta y producción.
4. **Poder de compra:** índice de salarios del sector privado registrado dividido por IPC = salario real. Cruzado con los precios que ya recolecta la página da un **índice de accesibilidad del lubricante**: cuántos litros compra un salario, YPF contra la competencia.
5. **Precio relativo:** precio de lubricante de la página (convertido en índice) dividido por IPC Transporte o IPC núcleo, para ver si el lubricante se encarece o se abarata en términos reales.
6. **Nuevo parque:** IPI Vehículos automotores + automóviles en unidades (MECON), como proxy del primer servicio de los autos nuevos. Para patentamientos de verdad hace falta DNRPA.
7. **Canal de consumo:** ventas en supermercados a precios constantes, como termómetro del consumo minorista.

**Recomendación:** arrancar con datos.gob.ar, que no pide token y ya está probada. Pasar a la API de INDEC solo para lo que no está ahí (la subclase de lubricantes del IPC, IPI minero, EPH), y para eso tenés que registrarte y guardar el token como secret en Render y en la GitHub Action. En la página hay que mostrar los signos convencionales tal cual (`...`, `///`, `*`) y no rellenar nunca con cero. En el repo LUBRICANTES todavía no hay nada que use INDEC ni datos.gob.ar.


---

## Relevamiento: datos-gob

Relevamiento de la API de Series de Tiempo (apis.datos.gob.ar/series/api), probado con curl el 2026-11-05. No pide token. Base: `https://apis.datos.gob.ar/series/api/series/?ids=<ID>&last=N` (también `&format=csv`, `&start_date=`, y varios ids separados por coma). La búsqueda es `/series/api/search/?q=...` y respondió HTTP 200 en todas las consultas.

Aviso importante: el campo `time_index_end` del buscador describe el dataset, no la serie. Varias series que el buscador lista hasta 2026 están vacías (count=0) o se cortan en años viejos. Los "últimos datos" de abajo salen de consultar cada serie.

**SERIES PROBADAS CON DATO RECIENTE (HTTP 200)**

| id | título | frec | fuente | último dato |
|---|---|---|---|---|
| 143.3_NO_PR_2004_A_21 | EMAE base 2004, original | M | INDEC | 2026-07-01 = 151.55 |
| 143.3_NO_PR_2004_A_31 | EMAE desestacionalizado | M | INDEC | 2026-07-01 = 149.65 |
| 11.3_VMASD_2004_M_23 | EMAE Industria manufacturera | M | INDEC | 2026-07-01 = 119.13 |
| 11.3_ISD_2004_M_26 | EMAE Minas y canteras | M | INDEC | 2026-07-01 = 139.39 |
| 11.3_EMC_2004_M_25 | EMAE Transporte, almac. y comunic. | M | INDEC | 2026-07-01 = 185.64 |
| 11.3_ISOM_2004_M_39 | EMAE Agro, ganadería, caza y silvic. | M | INDEC | 2026-07-01 = 119.65 |
| 11.3_AGCS_2004_M_41 | EMAE Comercio y reparaciones | M | INDEC | 2026-07-01 = 146.58 |
| 11.2_VMATC_2004_T_12 | EMAE Construcción (trimestral) | T | INDEC | 2026-04-01 = 127.46 |
| 453.1_SERIE_ORIGNAL_0_0_14_46 | IPI manufacturero, nivel general, original | M | INDEC | 2026-08-01 = 119.29 |
| 453.1_SERIE_DESEADA_0_0_24_58 | IPI nivel general desestacionalizado | M | INDEC | 2026-08-01 = 114.29 |
| 453.2_AUTOPARTESTES_0_0_10_100 | IPI Autopartes | M | INDEC | 2026-08-01 = 82.64 |
| 453.2_CEMENTONTO_0_0_7_59 | IPI Cemento | M | INDEC | 2026-08-01 = 156.68 |
| 33.2_ISAC_NIVELRAL_0_M_18_63 | ISAC nivel general (id deducido, no salió en el buscador; responde 200 con datos) | M | INDEC | 2026-08-01 = 146.86 |
| 33.4_ISAC_CEMENAND_0_0_21_24 | ISAC insumo Cemento portland | M | INDEC | 2026-08-01 = 156.78 |
| 41.2_CP_0_T_16 | Cemento portland, miles de toneladas | T | Min. Economía | 2026-04-01 = 46460.58 |
| 41.3_AA_0_A_23 | Producción de automóviles (unidades según el título; el valor parece estar en miles, sin verificar) | M | Min. Economía | 2026-07-01 = 81.8 |
| 38.3_ANIT_1994_M_21 | Ventas al mercado interno de automotores nacionales + importados, total (unidades) | M | Min. Economía | 2026-08-01 = 39068 |
| 38.3_ANIU_1994_M_27 | Ventas de utilitarios nacionales + importados (unidades) | M | Min. Economía | 2026-08-01 = 10677 |
| 145.3_INGNACNAL_DICI_M_15 | IPC nivel general nacional, base dic-2016 | M | INDEC | 2026-08-01 = 12276.77 |
| 148.3_INIVELNAL_DICI_M_26 | IPC nivel general nacional (mismo valor que la anterior) | M | INDEC | 2026-08-01 = 12276.77 |
| 146.3_ITRANSPNAL_DICI_M_23 | IPC Transporte nacional | M | INDEC | 2026-08-01 = 12965.12 |
| 148.3_IREGULANAL_DICI_M_22 | IPC Regulados nacional | M | INDEC | 2026-08-01 = 12935.97 |
| 148.3_INUCLEONAL_DICI_M_19 | IPC Núcleo nacional | M | INDEC | 2026-08-01 = 12445.80 |
| 92.2_TIPO_CAMBIION_0_0_21_24 | Tipo de cambio de valuación BCRA ($/USD) | D | BCRA | 2026-08-31 = 1509.47 |
| 92.1_TCV_0_0_21 | Tipo de cambio de valuación, promedio | M | BCRA | 2026-08-01 = 1498.71 |
| 149.1_TL_INDIIOS_OCTU_0_21 | Índice de salarios, total | M | INDEC | 2026-07-01 = 9708.64 |
| 149.1_SOR_PRIADO_OCTU_0_25 | Índice de salarios, privado registrado | M | INDEC | 2026-07-01 = 9879.87 |
| 365.3_VENTAS_DE_YPF__20 | Ventas de gasoil YPF (m3) | M | Sec. Energía | 2026-08-01 = 668021 |
| 365.3_VENTAS_DE_ELL__22 | Ventas de gasoil Shell (m3) | M | Sec. Energía | 2026-08-01 = 186759 |
| 365.3_VENTAS_DE_RAS__26 | Ventas de gasoil Petrobras (el buscador la lista hasta 2026-08; no le pedí el valor) | M | Sec. Energía | sin consultar |
| 365.3_VENTAS_DE_YPF_I__20 | Ventas de naftas YPF (m3) | M | Sec. Energía | 2026-08-01 = 448740 |
| 363.3_VENTAS_DE_OIL__16 | Ventas de gasoil, total (miles de m3) | M | Sec. Energía | 2025-11-01 = 1185.63 (atrasada) |
| 302.3_S_ORIGINALRAL_0_S_21 | Indicador de servicios públicos, nivel general | M | INDEC | 2026-07-01 = 195.90 |
| 302.3_S_ORIGINALJES_0_S_17 | Servicios públicos: Peajes, original | M | INDEC | 2026-07-01 = 135.60 |
| 302.3_S_TENDENCIRGA_0_S_30 | Servicios públicos: Transporte de carga, tendencia-ciclo | M | INDEC | 2026-07-01 = 90.71 |
| AGRO_A_Trigo_0001 | Hectáreas sembradas de trigo | A | MAGyP | 2025-01-01 = 6958766 |
| AGRO_A_Soja_0004 | Rendimiento de soja (kg/ha) | A | MAGyP | 2024-01-01 = 2927.96 |

**URL de ejemplo probada (HTTP 200, CSV):**
`https://apis.datos.gob.ar/series/api/series/?ids=143.3_NO_PR_2004_A_21,453.1_SERIE_ORIGNAL_0_0_14_46&last=3&format=csv`
Devolvió 2026-06/07/08. El EMAE de 2026-08 viene vacío, así que al combinar series hay que tolerar los nulos.

**SERIES QUE EXISTEN PERO NO SIRVEN (HTTP 200 sin datos o cortadas)**
- Vacías (count=0): 11.3_VMATC_2004_M_12 (EMAE construcción mensual), 453.2_GASOILOIL_0_0_6_78 (IPI gasoil), 41.3_CP_0_A_16 (cemento mensual), 158.1_REPTE_0_0_5 (RIPTE), 302.3_TRANSP_PASSAJ_0_S_38 (pasajeros subte).
- Cortadas: 74.3_IICL_0_M_42 (importaciones de combustibles y lubricantes en USD, mensual) termina en 2003-06. Su versión trimestral, 74.2_IICL_0_T_42, figura hasta 2026-04 pero no la probé.
- 168.1_T_CAMBI500_D_0_0_17 (A3500) termina el 2025-04-24.
- 41.3_T_0_A_9 (tractores) termina en 2011-01.
- 355.x (salario real 1986=100) termina en 1990.

**SERIES QUE NO EXISTEN O NO ENCONTRÉ**
- 148.3_ITRANSPNAL_DICI_M_25 da HTTP 400 "Serie inexistente". La correcta es 146.3_ITRANSPNAL_DICI_M_23.
- Patentamientos ACARA, parque automotor DNRPA y maquinaria agrícola INDEC (cosechadoras): el buscador no devolvió nada. La API no los tiene; hay que sacarlos de otras fuentes, como DNRPA o el informe de maquinaria agrícola de INDEC.
- Producción de gasoil total (363.2_PRODUCCIONOIL__20) es trimestral y llega hasta 2025-07. No la probé.

**INDICADORES QUE SE PUEDEN ARMAR PARA LUBRICANTES (derivados, nada se publica así)**
- **Precio relativo:** precio de lubricante YPF (del propio visor) dividido por IPC transporte (146.3_ITRANSPNAL_DICI_M_23) o por IPC general.
- **Precio en dólares:** precio del lubricante dividido por el tipo de cambio de valuación (92.2_TIPO_CAMBIION_0_0_21_24, diario).
- **Poder de compra:** índice de salarios (149.1_TL_INDIIOS_OCTU_0_21) dividido por el precio del lubricante, o por IPC.
- **Uso de vehículos:** peajes (302.3_S_ORIGINALJES_0_S_17), ventas de nafta y gasoil por empresa (365.3_*) y la variación interanual de ambas.
- **Pesados y carga:** transporte de carga (302.3_S_TENDENCIRGA_0_S_30), gasoil por empresa, EMAE transporte (11.3_EMC_2004_M_25).
- **Flota nueva:** ventas al mercado interno de 0 km (38.3_ANIT_1994_M_21), acumuladas como proxy de parque. Sin DNRPA es solo una aproximación.
- **Sectores con lubricante industrial:** IPI (453.1_*), EMAE minas (11.3_ISD_2004_M_26), EMAE agro (11.3_ISOM_2004_M_39), ISAC y cemento (33.2_ISAC_NIVELRAL_0_M_18_63, 453.2_CEMENTONTO_0_0_7_59).


---

## Relevamiento: energia

La Secretaría de Energía publica **ventas oficiales de lubricantes por empresa, provincia y canal, por mes**, de 2010-01 a **2026-09**. Con eso se puede armar un market share oficial. Todo lo que sigue lo probé con curl el 2026-11-05.

## 1. El que sirve: "Ventas (excluye ventas a empresas del sector)", Res. SE 1104

- Portal CKAN: `http://datos.energia.gob.ar/api/3/action/package_show?id=refinacion-y-comercializacion-de-petroleo-gas-y-derivados-tablas-dinamicas` → HTTP 200.
- CSV directo: `http://datos.energia.gob.ar/dataset/5bdc436c-60d4-4c86-98ab-59834d047700/resource/f0e4e10a-e4b8-44e6-bd16-763a43742107/download/ventas-excluye-ventas-a-empresas-del-sector-.csv`
  - HTTP 200, Last-Modified 2026-10-26.
  - Pesa **769 MB** y tardó 133 s en bajar.
  - El servidor ignora `Range`: no se puede pedir solo un pedazo.
- Columnas: `anio, mes, empresa, tipodecomercializacion, subtipodecomercializacion, producto, unidad, provincia, cantidad, pais, indice_tiempo`
- Productos de lubricantes:
  - `Lubricantes automotrices(m3)`
  - `Lubricantes industriales(m3)`
  - `Lubricantes marinos(m3)`
  - `Bases Lubricantes(m3)`
  - `Grasas(Ton)`
- Canal (`subtipodecomercializacion`): Al Público, Agro, Otras Empresas, Transporte de Carga, transporte Público de Pasajeros, Transporte Ferroviario, Industrias Petroquímicas, Usinas Eléctricas, Bunker, Estado.
- El mismo archivo trae gasoil y naftas por empresa, provincia y canal (`Gasoil Grado 1 (Agrogasoil)`, `Grado 2`, `Grado 3`, etc.).

**Muestra real: lubricantes automotrices, total país (m3)**

| Mes | Volumen |
|---|---|
| 2026-04 | 12.724 |
| 2026-05 | 12.248 |
| 2026-06 | 12.708 |
| 2026-07 | 12.329 |
| 2026-08 | 12.806 |
| 2026-09 | 13.430 |

Lubricantes industriales en 2026-09: 5.909 m3.

**Market share automotriz, 2026-09 (13.430 m3)**

| Empresa | Volumen (m3) | Share |
|---|---|---|
| YPF S.A. | 5.064 | 37,7% |
| SHELL C.A.P.S.A. (Raízen) | 3.176 | 23,6% |
| TOTAL ESPECIALIDADES Arg. | 1.798 | 13,4% |
| PAN AMERICAN ENERGY SL (Axion) | 1.544 | 11,5% |
| PETRONAS LUBRICANTS ARGENTINA | 1.205 | 9,0% |
| FERCOL Lubricantes | 541 | 4,0% |
| Destilería Argentina de Petróleo | 102 | 0,8% |

Comparado con 2019-09, YPF bajó de 42,8% a 37,7%, Shell subió de 20,2% a 23,6% y PAE/Axion subió de 4,3% a 11,5%. Gulf (3,3% en 2019) e Interlub ya no aparecen en 2024. Esso y Petrobras figuran hasta 2016.

**Año 2025**

| Producto | Total | Reparto por empresa |
|---|---|---|
| Automotrices | 151.332 m3 | YPF 35,2%, Shell 26,3%, Total 14,0%, PAE 10,4%, Petronas 8,2%, Fercol 4,9%, DAPSA 1,1% |
| Industriales | 68.292 m3 | YPF 47,8%, Shell 29,2%, Total 8,4%, PAE 6,3%, Fuchs 4,8% |
| Grasas | 5.029 t | YPF 34,0%, Shell 27,4%, Total 19,4%, Fercol 13,3% |

- Canal, automotrices 2025: Otras Empresas 50,1%, Al Público 29,5%, Agro 17,3%, transporte de pasajeros 1,3%, transporte de carga 0,9%.
- Provincia, automotrices 2025: Buenos Aires 36,3%, Córdoba 9,3%, Santa Fe 9,2%, CABA 6,1%, S/D 4,9%, Tucumán 4,3%, Entre Ríos 3,8%, Neuquén 3,7%, Mendoza 3,7%.

Hay dos límites para interpretar el share:
- Solo declaran las empresas inscriptas en la Res. 1104. No figuran Mobil, Castrol, Motul, Liqui Moly ni los importadores chicos, así que es el **share entre las que declaran**, no el de todo el mercado. Estas marcas aparecen en otras tablas: Mobil Argentina en exportación y Fuchs en importación.
- Es volumen vendido por la petrolera (sell-in), no lo que compra el consumidor final.

## 2. Importación y exportación de lubricantes y bases (desde 2016)

- CSV: `http://datos.energia.gob.ar/dataset/5bdc436c-60d4-4c86-98ab-59834d047700/resource/ea145b70-c78f-4c94-8df0-27e3acfda3fc/download/importaciones-exportaciones-a-partir-del-2016-.csv`
  - HTTP 200, 188 MB, último mes **2026-10**.
  - Columnas: las mismas del archivo de ventas más `monto` y `fecha_data`.
- Importación 2025 (m3):
  - Bases lubricantes: Shell 35.407, YPF 20.639, PAE 7.263, Petronas 1.800.
  - Lubricantes automotrices: Shell 7.567, Total 1.979, PAE 859.
  - Lubricantes industriales: Fuchs 1.419, Shell 1.095.
- Exportación 2025 (m3): YPF exportó 60.274 de bases, 3.337 de automotrices y 4.610 de industriales.

## 3. Producción de lubricantes por refinería

- CSV: `http://datos.energia.gob.ar/dataset/5bdc436c-60d4-4c86-98ab-59834d047700/resource/78c4648c-0c26-4db8-94ca-d271ab687f9b/download/subproductos-obtenidos.csv`
  - HTTP 200, 33 MB, último mes **2026-09**.
  - Columnas: `anio, mes, empresa, refineria, concepto, cantidadm3, cantidadtns, indice_tiempo, fecha`
- Producción 2025 (m3):

| Refinería / planta | Bases | Automotrices | Industriales |
|---|---|---|---|
| La Plata (YPF) | 122.576 | 56.565 | 37.231 |
| Dock Sud | – | 33.929 | 21.313 |
| Campana | – | 32.338 | 8.743 |
| Tablada Blending | – | 20.796 | – |
| Dock Sud-DAPSA | – | 19.010 | – |
| PETRONAS | – | 14.200 | – |

## 4. Gasoil como indicador de actividad y de costo

- **Volumen de gasoil por canal:** sale del mismo CSV de ventas. Grados 1+2+3, 2026-09 contra 2025-09 (m3):

| Canal | 2025-09 | 2026-09 |
|---|---|---|
| Al Público | 589.063 | 626.122 |
| Agro | 238.413 | 233.068 |
| Transporte de Carga | 134.484 | 142.827 |
| Pasajeros | 52.137 | 50.338 |

  Sirve como indicador de uso de flota para el lubricante de motor diésel.
- **Precios en surtidor, Res. 314/2016 (histórico):** `http://datos.energia.gob.ar/dataset/1c181390-5045-475e-94dc-410429be4b17/resource/f8dda0d5-2a9f-4d34-b79b-4e63de3995df/download/precios-historicos.csv`
  - HTTP 200, Last-Modified 2026-11-02.
  - Columnas: `idempresa, empresa, direccion, localidad, provincia, idproducto, producto, idtipohorario, tipohorario, precio, fecha_vigencia, idempresabandera, empresabandera, latitud, longitud, geojson, anio, mes`
  - Muestra: PUMA en Lomas del Mirador, Gas Oil Grado 2, $985, vigente desde 01/04/2024.
- **Precios y volúmenes de estaciones de servicio, Res. 1104/04 (desde dic-2024):** `http://datos.energia.gob.ar/dataset/708f9ab4-829b-4f02-b507-f303c5bc4800/resource/3cbdd364-a12c-46b7-b791-dd8e8bcfb32d/download/precios-eess-2025-.csv`
  - HTTP 200, Last-Modified 2026-10-30. Pesa más de 64 MB (no medí el total; lo bajé sin querer entero).
  - Columnas principales: `periodo, operador, bandera, localidad, provincia, producto, canal_de_comercializacion, precio_sin_impuestos, precio_con_impuestos, volumen, precio_surtidor`, más el desglose de impuestos.
  - Muestra 2024/12: PUMA en Lomas del Mirador, Gas Oil Grado 2, precio en surtidor $1.173, volumen 33,36.
- También aparecieron por nombre, pero **no los probé**: `participacion-en-el-mercado-por-bandera-de-estaciones-de-servicio` (modificado por última vez el 2024-06-11) y `precios-mayoristas-resolucion-1104-04`.

## Qué no hay

- Una búsqueda de "lubricantes" en el portal devuelve 0 datasets. Los lubricantes están dentro de los CSV de la Res. 1104 de arriba.
- No hay apertura por marca comercial (Elaion, Helix): solo por empresa.

## Para sumarlo a la página

El CSV de ventas (769 MB) no entra en Render free (512 MB). Habría que leerlo línea por línea en la GitHub Action una vez por mes, filtrando por `'ubric' in producto` o por producto que empiece con `Gasoil`, y guardar un JSON chico con totales por mes × empresa × canal × provincia. Así lo hicieron mis scripts y anduvo.

Los scripts y los CSV que bajé están en la carpeta temporal de esta sesión: