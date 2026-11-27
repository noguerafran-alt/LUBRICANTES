# Power BI: precios observados en modelo estrella

El server publica ocho tablas en CSV (UTF-8 con BOM, así Power BI y Excel leen los acentos, coma como separador y punto decimal) para cruzar los precios observados con datos internos de YPF. **La lectura es abierta: no hay clave**, ni en la URL ni en un header (un `X-API-Key` o Basic Auth que llegue se ignora). Solo la carga de Grok (`POST /api/cargar`) pide clave.

Host principal: **`https://lubricantes.fln-data-analysis.com`** (el celular con Cloudflare Tunnel). Respaldo: `https://lubricantes-ypf.onrender.com` (Render free duerme: la primera llamada puede tardar un minuto). Mismas rutas en los dos.

Hay dos caminos para llevar los datos a Power BI:

1. **SharePoint (carga manual)**: el camino elegido por ciberseguridad. Una persona baja un `.zip`, reemplaza los archivos en una carpeta de SharePoint y Power BI lee de ahí. Ver la sección siguiente.
2. **Conexión web directa** (alternativa, más abajo): Power BI pide cada tabla a la API.

| tabla | URL | qué es |
|---|---|---|
| `precios` | `/api/bi/precios[?desde=AAAA-MM-DD]` | hechos: una fila por observación con `producto_id` |
| `indice` | `/api/bi/indice[?desde=][&pais=][&mayoristas=1]` | hechos: índice YPF = 100 por `fecha × pais × moneda × segmento × sae × marca` |
| `indice_competencia` | `/api/bi/indice_competencia[?desde=][&pais=]` | hechos: índice YPF vs competencia (competencia = 100), serie diaria por `producto_id` |
| `productos` | `/api/bi/productos` | dimensión: `seed/productos.csv` + `es_ypf` (1/0) |
| `equivalencias` | `/api/bi/equivalencias` | puente YPF ↔ competencia (`ypf_id`, `comp_id`, `tipo`, `criterio`, `evidencia`, `fuente`) |
| `fuentes` | `/api/bi/fuentes` | dimensión: `fuente`, `canal`, `pais`, `tipo` (tienda, mayorista, grok, sepa, ml), `ultima_fecha` |
| `provincias` | `/api/bi/provincias` | dimensión: `codigo` ISO, `nombre`, `region`, `pais`, `online` (la fila `online` es el e-commerce nacional) |
| `fx` | `/api/bi/fx` | cotizaciones: `fecha`, `moneda` (ARS, BRL), `por_usd`, `fuente` |
| `diccionario` | `/api/bi/diccionario` | una fila por columna de cada tabla: `tabla,columna,tipo,unidad,descripcion,ejemplo` |
| (todo junto) | `/api/bi/paquete.zip` | un CSV por tabla + `diccionario.csv` + `LEEME.txt` |

## SharePoint (carga manual)

### 1. Bajar el paquete
Abrir `https://lubricantes.fln-data-analysis.com/api/bi/paquete.zip` en el navegador (o `curl -O`). Se baja `paquete.zip` (~1 MB). Trae diez archivos con **nombres fijos, sin fecha**:

`precios.csv`, `indice.csv`, `indice_competencia.csv`, `productos.csv`, `equivalencias.csv`, `fuentes.csv`, `provincias.csv`, `fx.csv`, `diccionario.csv`, `LEEME.txt`.

`LEEME.txt` dice cuándo se generó, cuál es el último dato, qué commit de datos sirve el server y de dónde salió.

### 2. Reemplazar en SharePoint
Descomprimir y **reemplazar** los archivos en la carpeta de SharePoint (por ejemplo `Documentos compartidos/Lubricantes`) **sin cambiarles el nombre**: las consultas de Power BI buscan el archivo por nombre, y con otro nombre (o con la fecha puesta) la actualización se rompe. Subir también `LEEME.txt`.

### 3. Power BI: una consulta M por tabla
**Obtener datos → Consulta en blanco → Editor avanzado**. Primero dos parámetros (**Inicio → Administrar parámetros**): `Sitio` (texto, la URL del sitio de SharePoint, p. ej. `https://<tenant>.sharepoint.com/sites/<sitio>`) y `Carpeta` (texto, la ruta de la carpeta tal como aparece en `[Folder Path]`, con la barra final, p. ej. `https://<tenant>.sharepoint.com/sites/<sitio>/Documentos compartidos/Lubricantes/`). Credenciales: **cuenta organizacional** (la de Microsoft 365).

Función auxiliar (consulta `LeerCsv`, tipo función; la reutilizan todas las tablas):

```m
(archivo as text) =>
let
    Archivos = SharePoint.Files(Sitio, [ApiVersion = 15]),
    Carpeta_ = Table.SelectRows(Archivos, each [Folder Path] = Carpeta and [Name] = archivo),
    Contenido = Carpeta_{0}[Content],
    Csv = Csv.Document(Contenido, [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Encabezados = Table.PromoteHeaders(Csv, [PromoteAllScalars = true])
in
    Encabezados
```

Después una consulta por tabla, con sus tipos y `"en-US"` (así `4000.5` se lee como número aunque Windows esté en español; las fechas ISO también):

```m
// precios
let
    Origen = LeerCsv("precios.csv"),
    Tipos = Table.TransformColumnTypes(Origen, {
        {"fecha", type date}, {"capturado", type datetimezone}, {"producto_id", type text}, {"fuente", type text}, {"canal", type text},
        {"vendedor", type text}, {"sucursal", type text}, {"provincia", type text}, {"pais", type text}, {"moneda", type text},
        {"precio", type number}, {"litros", type number}, {"unidades", type number}, {"precio_litro", type number},
        {"precio_usd_litro", type number}, {"url", type text}, {"match", type text}, {"verificado", type text}}, "en-US")
in
    Tipos
```
```m
// indice
let
    Origen = LeerCsv("indice.csv"),
    Tipos = Table.TransformColumnTypes(Origen, {
        {"fecha", type date}, {"pais", type text}, {"moneda", type text}, {"segmento", type text}, {"sae", type text}, {"marca", type text},
        {"mediana_litro", type number}, {"mediana_ypf_litro", type number}, {"indice", type number}, {"n", Int64.Type}}, "en-US")
in
    Tipos
```
```m
// indice_competencia
let
    Origen = LeerCsv("indice_competencia.csv"),
    Tipos = Table.TransformColumnTypes(Origen, {
        {"fecha", type date}, {"producto_id", type text}, {"pais", type text}, {"moneda", type text}, {"indice", type number},
        {"mediana_ypf_litro", type number}, {"mediana_comp_litro", type number}, {"n_ypf", Int64.Type}, {"n_comp", Int64.Type}}, "en-US")
in
    Tipos
```
```m
// productos
let
    Origen = LeerCsv("productos.csv"),
    Tipos = Table.TransformColumnTypes(Origen, {
        {"producto_id", type text}, {"marca", type text}, {"linea", type text}, {"nombre", type text}, {"segmento", type text},
        {"sae", type text}, {"base", type text}, {"api", type text}, {"acea", type text}, {"ilsac", type text}, {"jaso", type text},
        {"oem", type text}, {"fuente_specs", type text}, {"verificado", type text}, {"es_ypf", Int64.Type}}, "en-US")
in
    Tipos
```
```m
// equivalencias
let
    Origen = LeerCsv("equivalencias.csv"),
    Tipos = Table.TransformColumnTypes(Origen, {
        {"ypf_id", type text}, {"comp_id", type text}, {"tipo", type text}, {"criterio", type text}, {"evidencia", type text}, {"fuente", type text}}, "en-US")
in
    Tipos
```
```m
// fuentes
let
    Origen = LeerCsv("fuentes.csv"),
    Tipos = Table.TransformColumnTypes(Origen, {
        {"fuente", type text}, {"canal", type text}, {"pais", type text}, {"tipo", type text}, {"ultima_fecha", type date}}, "en-US")
in
    Tipos
```
```m
// provincias
let
    Origen = LeerCsv("provincias.csv"),
    Tipos = Table.TransformColumnTypes(Origen, {
        {"codigo", type text}, {"nombre", type text}, {"region", type text}, {"pais", type text}, {"online", Int64.Type}}, "en-US")
in
    Tipos
```
```m
// fx
let
    Origen = LeerCsv("fx.csv"),
    Tipos = Table.TransformColumnTypes(Origen, {{"fecha", type date}, {"moneda", type text}, {"por_usd", type number}, {"fuente", type text}}, "en-US")
in
    Tipos
```
```m
// diccionario (opcional: para armar las descripciones; no hace falta cargarla al modelo)
let
    Origen = LeerCsv("diccionario.csv")
in
    Origen
```

Notas: `precios.csv` pesa ~8 MB y ~51.000 filas (crece unas 1.500 por día): importarla completa es razonable. `SharePoint.Files` con `ApiVersion = 15` lista **todos** los archivos del sitio; el filtro por `Folder Path` y `Name` es lo que lo acota, y es el mismo patrón para las diez tablas.

### 4. Relaciones del modelo estrella
Vista **Modelo**, todas muchos a uno con filtro simple (del lado «uno» al «muchos»):

| desde (muchos) | hacia (uno) |
|---|---|
| `precios[producto_id]` | `productos[producto_id]` |
| `indice_competencia[producto_id]` | `productos[producto_id]` |
| `equivalencias[ypf_id]` | `productos[producto_id]` |
| `equivalencias[comp_id]` | `productos[producto_id]` (queda inactiva: Power BI solo deja una activa; usá `USERELATIONSHIP` donde la necesites) |
| `precios[fuente]` | `fuentes[fuente]` |
| `precios[provincia]` | `provincias[codigo]` |

`indice` no tiene `producto_id` (es por segmento × SAE × marca): se usa por sí sola, con `fecha`, `segmento`, `sae` y `marca` como ejes. `fx` se relaciona con `precios` por `fecha` + `moneda` (clave compuesta: Power BI no la soporta directo; si hace falta, una columna `fecha&moneda` en las dos tablas). `precios[precio_usd_litro]` ya viene convertido: `fx` es para otras conversiones.

### 5. Medidas DAX sugeridas

```dax
-- índice YPF = 100 de la marca elegida, en el último día del filtro (la tabla ya trae la mediana por aviso)
Indice vs YPF =
VAR f = CALCULATE ( MAX ( indice[fecha] ), ALLSELECTED ( indice[fecha] ) )
RETURN CALCULATE ( MAX ( indice[indice] ), indice[fecha] = f, indice[pais] = "AR" )

-- n de avisos detrás de esa celda (mostrarlo siempre al lado del índice)
Avisos del indice =
VAR f = CALCULATE ( MAX ( indice[fecha] ), ALLSELECTED ( indice[fecha] ) )
RETURN CALCULATE ( SUM ( indice[n] ), indice[fecha] = f, indice[pais] = "AR" )

-- índice YPF vs competencia (competencia = 100), promedio de los productos YPF filtrados, en el último día
Indice vs competencia =
VAR f = CALCULATE ( MAX ( indice_competencia[fecha] ), ALLSELECTED ( indice_competencia[fecha] ) )
RETURN CALCULATE ( AVERAGE ( indice_competencia[indice] ), indice_competencia[fecha] = f, indice_competencia[pais] = "AR" )

-- diferencia % de la competencia contra YPF (positivo = la competencia es más cara)
Dif % competencia vs YPF = DIVIDE ( 100, [Indice vs competencia] ) * 100 - 100

-- precio por litro mediano de los avisos filtrados (para detalle por producto o fuente, no para el índice)
Precio por litro mediano =
MEDIANX ( FILTER ( precios, NOT ISBLANK ( precios[precio_litro] ) && precios[pais] = "AR" && precios[canal] <> "mayorista" && precios[verificado] <> "0" ), precios[precio_litro] )
```

**Advertencia:** una mediana sobre `precios` repite el sesgo que el índice ya corrigió. SEPA escribe una fila por comercio × provincia (unas 24 por comercio) y una mediana sobre filas la domina; además cuenta cada precio repetido de todos los días del período como una observación distinta. Por eso existe `indice` (y `indice_competencia`) ya calculado: **para el índice, usar esas tablas, no recalcularlo desde `precios`**. `Dif % competencia vs YPF` es la inversa del índice de competencia (`100/x·100−100`), no el `dif_pct` promedio del Visualizador (que usa promedios, no medianas). Nunca mezclar `pais` ni `moneda` en una agregación.

### 6. Descripciones para Copilot
Copilot responde mejor si el modelo semántico está descripto. `diccionario.csv` sale pensado para eso:

- **Descripción de columna**: en la vista Modelo, seleccionar cada columna → panel Propiedades → *Descripción*; pegar el campo `descripcion` de su fila en `diccionario.csv` (filtrar por `tabla` y `columna`). Incluyen unidad, qué significa vacío y cuál es la base del índice (YPF = 100 en `indice`, competencia = 100 en `indice_competencia`).
- **Descripción de tabla**: una línea por tabla, p. ej. `indice`: «Índice de precio por litro de cada marca contra YPF (YPF = 100), por segmento y SAE, con ventana de 3 días»; `indice_competencia`: «Índice de cada producto YPF contra su competencia equivalente (competencia = 100), ventana de 30 días»; `precios`: «Precios observados de lubricantes (una fila por observación); no usar para el índice».
- **Sinónimos** (Modelo → Propiedades → *Sinónimos*; los usa Copilot para entender la pregunta): `indice` → «índice de precios», «posicionamiento de precio», «precio relativo a YPF»; `mediana_litro` → «precio por litro», «$/L»; `marca` → «competidor», «competencia»; `producto_id` → «producto», «SKU»; `fuente` → «sitio», «canal de venta»; `provincia` → «zona», «jurisdicción»; `n` → «cantidad de avisos», «publicaciones».
- Marcar como **ocultas** las claves técnicas que no hay que preguntar (`producto_id`, `capturado`, `match`) y configurar el **resumen predeterminado** de `indice` en «No resumir» (sumar índices no tiene sentido).
- Instrucciones para el agente (Copilot → *Instrucciones de IA*): el índice es una mediana por aviso en ventana de 3 días; con `n` bajo es poco confiable; vacío = sin dato (no es cero); no se mezclan países ni monedas; los precios son de terceros (YPF no publica precio) y no son tiempo real.

### 7. Cada cuánto actualizar y cómo ver la frescura
- Los datos son **diarios**: la recolección corre a primera hora y SEPA se carga de día. El índice **cambia con cada día** (cada fecha usa su ventana de 3 días), así que conviene reemplazar los archivos **una vez por día hábil**, después del mediodía; con menos frecuencia el último día del modelo queda atrasado.
- **Frescura**: `LEEME.txt` (dentro del zip) trae `Generado`, `Ultimo dato` y el commit de datos. Fuera del zip, `GET /salud` devuelve `{"ok":true,"commit":"…","ultimo_dato":"AAAA-MM-DD"}`: si `ultimo_dato` es de hace más de 2 días, el celular no está recolectando (la pestaña Fuentes del visor lo explica) y conviene no publicar. Dentro del modelo, `fuentes[ultima_fecha]` dice qué fuente está atrasada.
- Un día sin fila de una fuente es «sin dato», no cero: no se arrastra el precio anterior.

## Conexión web directa (alternativa)

1. Power BI Desktop: **Obtener datos → Web → Básica**, pegá la URL (por ejemplo `https://lubricantes.fln-data-analysis.com/api/bi/productos`).
2. Credenciales **Anónimo**. Si ya tenías configurada la credencial **Básica** con la clave, no molesta: el server la ignora y sigue andando.
3. Mejor crear cada tabla con **Consulta en blanco → Editor avanzado** y pegar la consulta M de abajo, con la URL base en un parámetro (**Inicio → Administrar parámetros → Nuevo**: `Base`, texto, `https://lubricantes.fln-data-analysis.com`).

Nunca pongas una clave en la URL (la lectura no la necesita). Las consultas son las mismas de arriba cambiando la primera línea de `Origen` por:

```m
    Origen = Csv.Document(Web.Contents(Base & "/api/bi/precios"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars=true]),
    Tipos = Table.TransformColumnTypes(Encabezados, { ...los mismos tipos de arriba... }, "en-US")
```

(`Encoding=65001` es UTF-8; el BOM lo descarta.) Con la conexión directa, el servidor de Cloudflare Tunnel tiene que ser alcanzable desde donde corre Power BI; si la red de la empresa lo bloquea, usá el camino de SharePoint.

## Notas sobre cada tabla

Notas sobre `precios`:
- `capturado` es la hora de captura (ISO 8601 UTC). Las filas anteriores a esa columna la tienen **vacía**: no se infiere una hora.
- Una fila por captura, no hay fotos horarias.
- `verificado` solo se llena en las filas de Grok (`1` el precio apareció en la página, `0` no). Esas filas **se incluyen** (como en `/api/reventa`); filtrá `verificado <> "0"` si querés lo mismo que el índice (las de respaldo de Mercado Libre vienen como `respaldo` y cuentan en el índice solo los días en que `ml` no tiene filas).
- `precio_litro` = `precio / (litros × unidades)`; vacío si falta el envase. `precio_usd_litro` usa la cotización oficial de **ese mismo día**; vacío si no hay. No mezcles `moneda` ni `pais` al promediar.

### Índices
- **`indice`** (`fecha,pais,moneda,segmento,sae,marca,mediana_litro,mediana_ypf_litro,indice,n`): la tabla de la pestaña Índice. Para cada `fecha`, la **mediana por aviso** de $/L de la marca en la **ventana de 3 días que termina en esa fecha** (cada aviso cuenta una vez, con su precio más reciente de la ventana, con la sanidad de la vitrina: un aviso a más de 2,5× o menos de 1/2,5 de la mediana de su producto es un envase mal leído y no entra), dividida por la de YPF del mismo segmento y SAE × 100: **YPF = 100**. `n` = cantidad de avisos de la marca. Es la misma definición de la vitrina, de `/api/producto` y de `/api/indice/celdas?dias=3`, así que el último día coincide con ellas. Excluye mayoristas (con `?mayoristas=1` los suma) y Grok sin verificar. Todos los países y monedas en la misma tabla: filtrá por `pais`/`moneda`. `indice` vacío = en esa ventana no hay YPF en el grupo (nunca 0). Hasta 2026-11-26 el índice era por fila del día exacto (sesgado por SEPA): los números viejos no son comparables con los nuevos.
- **`indice_competencia`** (`fecha,producto_id,pais,moneda,indice,mediana_ypf_litro,mediana_comp_litro,n_ypf,n_comp`): para cada fecha con datos, el índice del producto YPF `producto_id` con una **ventana móvil de 30 días que termina en `fecha`**: mediana $/L YPF / mediana $/L de la competencia equivalente × 100, con la **competencia = 100** (menos de 100 = YPF más barato). Es el mismo número que muestra el Visualizador y que `/api/producto?dias=30`; sin mayoristas, sin `no_equivalente`, sin Grok sin verificar, con la sanidad de siempre. Se escribe una fila si ese día hay avisos de algún lado; `indice` queda vacío si falta YPF o competencia (nunca 0).
- Cuidado con las dos bases: en `indice` YPF = 100; en `indice_competencia` la competencia = 100.
- Incremental: `?desde=AAAA-MM-DD` filtra `fecha >= desde` (mal formado = 400). Cada fecha ya tiene su ventana propia, así que un rango parcial no cambia el valor de las filas.

## Actualización incremental (conexión web directa)

`/api/bi/precios?desde=AAAA-MM-DD` trae solo `fecha >= desde`.

1. En Power Query creá dos parámetros de tipo Fecha/Hora: `RangeStart` y `RangeEnd` (nombres exactos).
2. En la consulta `precios`, usá `desde` en la URL y filtrá por rango sobre `fecha`:
```m
    Origen = Csv.Document(Web.Contents(Base & "/api/bi/precios", [Query=[desde=Date.ToText(DateTime.Date(RangeStart), "yyyy-MM-dd")]]), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
```
   y después de `Tipos`: `Filtrado = Table.SelectRows(Tipos, each [fecha] >= DateTime.Date(RangeStart) and [fecha] < DateTime.Date(RangeEnd))`.
3. Clic derecho en la tabla `precios` → **Actualización incremental**: guardar los últimos N años, actualizar los últimos 7 días (la recolección es diaria; Tiendanube rota cada 2 días y Nota Paraná trae notas de hasta 2 semanas).
4. Publicar al servicio de Power BI (la actualización incremental corre allá, no en Desktop).

Sin esto, importar todo cada vez también funciona. Con el camino de SharePoint no se usa: se reemplaza el archivo entero.

Límites: no se probó contra un Power BI real ni contra SharePoint. Las filas de `precios` se reescriben si una fuente se vuelve a correr el mismo día: la actualización incremental tiene que **reemplazar** el rango, no solo agregar (lo hace por partición).
