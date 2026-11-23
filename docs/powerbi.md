# Power BI: precios observados en modelo estrella

El server publica siete tablas en CSV (UTF-8 con BOM, así Power BI y Excel leen los acentos) para cruzar los precios observados con datos internos de YPF. Son de lectura abierta, sin clave, como todo `GET` de la API.

| tabla | URL | qué es |
|---|---|---|
| `precios` | `/api/bi/precios[?desde=AAAA-MM-DD]` | hechos: una fila por observación con `producto_id` |
| `productos` | `/api/bi/productos` | dimensión: `seed/productos.csv` + `es_ypf` (1/0) |
| `equivalencias` | `/api/bi/equivalencias` | puente YPF ↔ competencia (`ypf_id`, `comp_id`, `tipo`, `criterio`, `evidencia`, `fuente`) |
| `fuentes` | `/api/bi/fuentes` | dimensión: `fuente`, `canal`, `pais`, `tipo` (tienda, mayorista, grok, sepa, ml), `ultima_fecha` |
| `indice` | `/api/bi/indice[?desde=][&pais=][&mayoristas=1]` | hechos: lo mismo que la pestaña Índice (YPF = 100), una fila por `fecha × pais × moneda × segmento × sae × marca` |
| `indice_competencia` | `/api/bi/indice_competencia[?desde=][&pais=]` | hechos: índice YPF vs competencia, serie diaria por `producto_id` |
| `provincias` | `/api/bi/provincias` | dimensión: `codigo` ISO, `nombre`, `region`, `pais`, `online` (la fila `online` es el e-commerce nacional) |

Notas sobre `precios`:
- `capturado` es la hora de captura (ISO 8601 UTC). Las filas anteriores a esa columna la tienen **vacía**: no se infiere una hora.
- Una fila por captura, no hay fotos horarias.
- `verificado` solo se llena en las filas de Grok (`1` el precio apareció en la página, `0` no). Esas filas **se incluyen** (como en `/api/reventa`); filtrá `verificado <> "0"` si querés lo mismo que el índice.
- `precio_litro` = `precio / (litros × unidades)`; vacío si falta el envase. `precio_usd_litro` usa la cotización oficial de **ese mismo día**; vacío si no hay. No mezcles `moneda` ni `pais` al promediar.

## Índices

- **`indice`** (`fecha,pais,moneda,segmento,sae,marca,mediana_litro,mediana_ypf_litro,indice,n`): la tabla de la pestaña Índice. `indice` = mediana $/L de la marca / mediana $/L de YPF del mismo grupo y día × 100, o sea **YPF = 100**. Excluye mayoristas (con `?mayoristas=1` los suma) y Grok sin verificar. Todos los países y monedas en la misma tabla: filtrá por `pais`/`moneda`, nunca los mezcles. `indice` vacío = ese día no hay YPF en el grupo.
- **`indice_competencia`** (`fecha,producto_id,pais,moneda,indice,mediana_ypf_litro,mediana_comp_litro,n_ypf,n_comp`): para cada fecha con datos, el índice del producto YPF `producto_id` con una **ventana móvil de 30 días que termina en `fecha`**: mediana $/L YPF / mediana $/L de la competencia equivalente × 100, con la **competencia = 100** (menos de 100 = YPF más barato). Es el mismo número que muestra el Visualizador y que `/api/producto?dias=30` (`comparacion.mediana_ypf_litro / mediana_comp_litro`); sin mayoristas, sin `no_equivalente`, sin Grok sin verificar, con la sanidad de siempre. Se escribe una fila si ese día hay avisos de algún lado; `indice` queda vacío si falta YPF o competencia (nunca 0).
- Cuidado con las dos bases: en `indice` YPF = 100; en `indice_competencia` la competencia = 100.
- Relaciones: `indice_competencia[producto_id]` → `productos[producto_id]` (muchos a uno). `indice` no trae `producto_id` (es por segmento × SAE × marca).
- Incremental: `?desde=AAAA-MM-DD` filtra `fecha >= desde`, igual que `precios` (mal formado = 400). Cada fecha ya tiene su ventana propia, así que un rango parcial no cambia el valor de las filas.
- Tipos para Power Query (con `"en-US"` como en `precios`): `fecha` date; `indice` y `mediana_*` number; `n`, `n_ypf`, `n_comp` Int64; el resto text.
- Medida DAX de ejemplo (promedio simple del índice de los productos YPF filtrados, en la última fecha del filtro):

```dax
Indice vs competencia =
VAR f = MAX ( indice_competencia[fecha] )
RETURN
    CALCULATE (
        AVERAGE ( indice_competencia[indice] ),
        indice_competencia[fecha] = f,
        indice_competencia[pais] = "AR"
    )
```

## Conectarse

1. Power BI Desktop: **Obtener datos → Web → Básica**, pegá la URL (por ejemplo `https://<tu-servicio>.onrender.com/api/bi/productos`).
2. Credenciales **Anónimo**: desde 2026-11-19 la lectura es abierta y ya no hace falta clave. Si tenés configurada la credencial **Básica** con la clave, no molesta: el server la ignora y sigue andando.
3. Mejor crear cada tabla con **Consulta en blanco → Editor avanzado** y pegar la consulta M de abajo. Ponés la URL base en un parámetro:
   **Inicio → Administrar parámetros → Nuevo**: nombre `Base`, tipo Texto, valor `https://<tu-servicio>.onrender.com`.

Nunca pongas una clave en la URL (la lectura no la necesita).

## Consultas M

Render free duerme: la primera llamada puede tardar un minuto. `Csv.Document(..., Encoding=65001)` es UTF-8; el BOM lo descarta.

### productos
```m
let
    Origen = Csv.Document(Web.Contents(Base & "/api/bi/productos"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars=true]),
    Tipos = Table.TransformColumnTypes(Encabezados, {
        {"producto_id", type text}, {"marca", type text}, {"linea", type text}, {"nombre", type text}, {"segmento", type text},
        {"sae", type text}, {"base", type text}, {"api", type text}, {"acea", type text}, {"ilsac", type text}, {"jaso", type text},
        {"oem", type text}, {"fuente_specs", type text}, {"verificado", type text}, {"es_ypf", Int64.Type}}, "en-US")
in
    Tipos
```

### equivalencias
```m
let
    Origen = Csv.Document(Web.Contents(Base & "/api/bi/equivalencias"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars=true]),
    Tipos = Table.TransformColumnTypes(Encabezados, {
        {"ypf_id", type text}, {"comp_id", type text}, {"tipo", type text}, {"criterio", type text},
        {"evidencia", type text}, {"fuente", type text}}, "en-US")
in
    Tipos
```

### fuentes
```m
let
    Origen = Csv.Document(Web.Contents(Base & "/api/bi/fuentes"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars=true]),
    Tipos = Table.TransformColumnTypes(Encabezados, {
        {"fuente", type text}, {"canal", type text}, {"pais", type text}, {"tipo", type text}, {"ultima_fecha", type date}}, "en-US")
in
    Tipos
```

### provincias
```m
let
    Origen = Csv.Document(Web.Contents(Base & "/api/bi/provincias"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars=true]),
    Tipos = Table.TransformColumnTypes(Encabezados, {
        {"codigo", type text}, {"nombre", type text}, {"region", type text}, {"pais", type text}, {"online", Int64.Type}}, "en-US")
in
    Tipos
```

### precios
El `"en-US"` final hace que `4000.5` se lea como número aunque Windows esté en español.
```m
let
    Origen = Csv.Document(Web.Contents(Base & "/api/bi/precios"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars=true]),
    Tipos = Table.TransformColumnTypes(Encabezados, {
        {"fecha", type date}, {"capturado", type datetimezone}, {"producto_id", type text}, {"fuente", type text}, {"canal", type text},
        {"vendedor", type text}, {"sucursal", type text}, {"provincia", type text}, {"pais", type text}, {"moneda", type text},
        {"precio", type number}, {"litros", type number}, {"unidades", type number}, {"precio_litro", type number},
        {"precio_usd_litro", type number}, {"url", type text}, {"match", type text}, {"verificado", type text}}, "en-US")
in
    Tipos
```

## Relaciones del modelo

Vista **Modelo**, todas muchos a uno con dirección de filtro simple (del lado "uno" al "muchos"):

| desde (muchos) | hacia (uno) |
|---|---|
| `precios[producto_id]` | `productos[producto_id]` |
| `equivalencias[ypf_id]` | `productos[producto_id]` |
| `equivalencias[comp_id]` | `productos[producto_id]` (una de las dos queda inactiva: Power BI solo deja una activa; activá la otra con `USERELATIONSHIP` en la medida que la necesite) |
| `precios[fuente]` | `fuentes[fuente]` |
| `precios[provincia]` | `provincias[codigo]` |

Para comparar YPF contra su competencia, filtrá `precios` por producto vía `equivalencias`: el par (`ypf_id`, `comp_id`) liga cada producto YPF con sus equivalentes; `tipo` dice qué tan comparables son (`no_equivalente` no se promedia).

## Actualización incremental

`/api/bi/precios?desde=AAAA-MM-DD` trae solo `fecha >= desde`.

1. En Power Query creá dos parámetros de tipo Fecha/Hora: `RangeStart` y `RangeEnd` (nombres exactos).
2. En la consulta `precios`, usá `desde` en la URL y filtrá por rango sobre `fecha`:
```m
    Origen = Csv.Document(Web.Contents(Base & "/api/bi/precios", [Query=[desde=Date.ToText(DateTime.Date(RangeStart), "yyyy-MM-dd")]]), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
```
   y después de `Tipos`: `Filtrado = Table.SelectRows(Tipos, each [fecha] >= DateTime.Date(RangeStart) and [fecha] < DateTime.Date(RangeEnd))`.
3. Clic derecho en la tabla `precios` → **Actualización incremental**: guardar los últimos N años, actualizar los últimos 7 días (la recolección es diaria; Tiendanube rota cada 2 días y Nota Paraná trae notas de hasta 2 semanas).
4. Publicar al servicio de Power BI (la actualización incremental corre allá, no en Desktop).

Sin esto, importar todo cada vez también funciona (`precios` sin `desde`).

Límites: no se probó contra un Power BI real. Las filas se reescriben si una fuente se vuelve a correr el mismo día: la actualización incremental tiene que **reemplazar** el rango, no solo agregar (lo hace por partición).
