# Task diaria de Grok (SuperGrok) para LUBRICANTES

Grok lee páginas públicas sin API y devuelve un CSV; ese CSV se pega en la pestaña **Cargar** del visor (o se manda a `POST /api/cargar`). El server lo valida, comprueba cada precio contra la página y lo comitea al repo (`data/grok/AAAA-MM.csv`).

## Prompt de la Task (fuente `grok_helix`)

```
Todos los días, entrá a https://www.helixturno.com.ar/combos (combos de cambio de aceite Shell; es una SPA: esperá a que carguen las tarjetas) y relevá cada combo con el precio que se ve en pantalla.

Devolvé SOLO un CSV, sin texto antes ni después, sin bloque de código, con este encabezado exacto:
fecha,fuente,url,titulo,marca,precio,precio_lista,litros,unidades,tipo,detalle

Reglas:
- fecha: hoy, AAAA-MM-DD.
- fuente: siempre grok_helix.
- url: https://www.helixturno.com.ar/combos
- titulo: el nombre del combo tal cual figura.
- marca: la marca del aceite (Shell) si se ve; si no, vacío.
- precio: el precio final en pesos, solo dígitos (84999, sin $ ni puntos). precio_lista: el precio tachado/anterior si existe; si no, vacío.
- litros y unidades: los del aceite del combo si figuran (4 y 1); si no, vacío. No los calcules ni los inventes.
- tipo: "producto" si el combo es solo el aceite (o aceite + filtro sin servicio); "servicio" si incluye mano de obra / colocación.
- detalle: qué incluye el combo, separado por ";" (sin comas; si hace falta una coma, poné el campo entre comillas dobles).
- No inventes ni estimes nada. Si un precio no se ve, omití esa fila.
```

## Variante con provincia (opcional)
`POST /api/cargar` acepta también un encabezado de 12 columnas, con `provincia` al final: `fecha,fuente,url,titulo,marca,precio,precio_lista,litros,unidades,tipo,detalle,provincia`.
Pedirla **solo si la página muestra un selector de zona/sucursal o una ubicación explícita** (ahí: el nombre de la provincia o su código ISO, p. ej. `Córdoba` o `AR-X`); si la página no dice dónde rige el precio, dejar vacío.
No deducir la provincia del domicilio de la empresa. Una provincia que no existe rechaza esa fila. El encabezado de 11 columnas sigue valiendo (la Task actual no cambia).

## Cómo pegar el resultado

1. Abrí el visor, pestaña **Cargar**.
2. Pegá el CSV en el cuadro.
3. Escribí la **clave de carga** (`LUB_CARGA_CLAVE`). No se guarda en el navegador: hay que escribirla cada vez (o que el gestor de claves del navegador la complete).
4. **Enviar**. Muestra una fila por línea: guardada (✓ verificado o no verificado) o rechazada con el motivo.

Si Grok puede hacer el POST solo: `POST https://<server>/api/cargar` con el CSV como cuerpo, `Content-Type: text/csv` (o `text/plain`; también sirve un formulario con el campo `csv`) y el header `X-Carga-Clave: <clave>`. Nunca la clave en la URL.

## La clave de carga

`LUB_CARGA_CLAVE` solo sirve para `POST /api/cargar`: con ella no se lee nada de la API. La clave principal (`LUB_CLAVE`) también carga. Se configura en Render junto a `GH_CARGA_TOKEN` (fine-grained PAT, solo el repo LUBRICANTES, permiso Contents: read and write) y, opcional, `GH_REPO` (por defecto `noguerafran-alt/LUBRICANTES`). Sin `GH_CARGA_TOKEN` la carga queda solo en el disco del server (efímero en Render) y la respuesta dice "solo local".

## Qué valida el server

Encabezado exacto (si no, no se guarda nada); fuente `grok_<sitio>` y que corresponda al host de la URL (`seed/grok_sitios.csv`, lista blanca; para sumar un sitio se agrega una fila ahí); URL https; fecha a no más de 3 días de hoy; precio numérico > 0; tipo `producto|servicio`; máximo 500 filas por carga y 10 cargas por día. Las filas con error se rechazan y las demás se guardan.

**Verificado:** el server baja cada URL y marca `verificado=1` si el precio aparece en el texto de la página. En una SPA (helixturno) el precio no está en el HTML del server: sale `verificado=0` ("no verificado"). Esas filas se guardan y se muestran, pero no entran al índice. Los `servicio` nunca entran al $/L; se ven en "Servicios (combos)" y en `/api/servicios`.
