# Consumir `/api/producto` desde un agente de IA (sobreprecios de revendedores)

Un agente (por ejemplo Copilot) puede usar este endpoint para detectar revendedores que publican productos YPF muy por encima de lo habitual.
**El endpoint no decide qué es un sobreprecio**: entrega las publicaciones, su precio por litro y cuánto se apartan de la mediana. El criterio lo pone quien consulta.

## De dónde salen los precios

YPF no publica precios en canales propios. Todo precio de un producto YPF viene de **terceros que lo venden**: tiendas online, supermercados (SEPA / Precios Claros),
Mercado Libre y relevamientos cargados por Grok. Las `url` apuntan a las publicaciones de esos terceros, no a YPF. SEPA declara el precio por comercio y provincia y no trae `url`.

**No es tiempo real**: la recolección es diaria y SEPA llega con ~1 día de atraso. La ventana termina en el último día con datos (`ventana.hasta`), no en hoy.

## Pedido

```
GET /api/producto?producto_id=<id>[&dias=N][&mayoristas=1][&umbral=N][&formato=csv][&pais=AR|BR]
```

- Lectura abierta, sin clave ni header. La URL del visor equivalente es `#producto/<producto_id>`.
- `producto_id`: slug del catálogo (`/api/productos`), por ejemplo `ypf-elaion-ts1040-10w40`. Los YPF y sus equivalentes están en `/api/bi/productos` (`es_ypf`).
- `dias`: 1 a 366, por defecto 30.
- `mayoristas=1`: suma los mayoristas (precio por caja o tambor, IVA sin verificar) al cálculo. Por defecto quedan listados pero fuera.
- `umbral`: opcional y **sin valor por defecto**. Un porcentaje N: cada publicación trae `sobre_umbral = desvio_pct_vs_mediana >= N`. Si no se manda, el campo no existe.
- Errores: 400 si `producto_id` falta o no existe, si `dias` no es un entero entre 1 y 366 o si `umbral` no es un número.

Ejemplo: `GET /api/producto?producto_id=ypf-elaion-ts1040-10w40&dias=30&umbral=15`

## Respuesta (JSON)

| campo | contenido |
|---|---|
| `producto` | `producto_id, marca, linea, nombre, segmento, sae, base, es_ypf, specs{api, acea, ilsac, jaso, oem[], base, sae, segmento, verificado, fuente_specs}, imagen, imagen_fuente, modelo` |
| `pais`, `moneda` | `AR`/`ARS` por defecto; nunca se mezclan países ni monedas |
| `ventana` | `{dias, desde, hasta}` |
| `nota` | aviso de que no es tiempo real |
| `metodo` | las reglas de cálculo en texto |
| `resumen` | `{n, mediana_litro, promedio_litro, min_litro, max_litro, p25_litro, p75_litro}` solo con las publicaciones **en cálculo**; con `n = 0` los demás son `null` |
| `publicaciones[]` | una por aviso (ver abajo) |
| `equivalentes[]` | los competidores de `seed/equivalencias.csv`: `{producto_id, marca, nombre, tipo, evidencia, specs, imagen, en_comparacion, motivo_exclusion, resumen, publicaciones[]}` |
| `comparacion` | `{mediana_ypf_litro, mediana_comp_litro, n_comp, dif_pct_mediana_comp_vs_ypf}` |
| `umbral_pct` | solo si se mandó `umbral` |

`publicaciones[]`: `fuente`, `fuente_nombre` (legible), `canal` (`publico`, `mayorista` o `grok`), `vendedor`, `sucursal`, `provincia` (ISO 3166-2, `online` o `null`), `fecha`, `capturado` (hora ISO UTC; `null` en filas anteriores a esa columna),
`precio`, `litros`, `unidades`, `precio_litro` (`precio / (litros × unidades)`), `desvio_pct_vs_mediana`, `url` (`null` en SEPA), `verificado` (`true`/`false` solo en Grok, `null` en el resto),
`en_calculo` y `motivo_exclusion` (`sin_litros`, `mayorista`, `grok_sin_verificar` o `fuera_de_sanidad`; `null` si cuenta). Un campo sin dato es `null`: no se rellena.
Vienen primero las que cuentan, de más cara a más barata por litro.

## Cómo se calcula

1. **Ventana**: `dias` días terminando en el último día con datos.
2. **Un aviso, una vez**: la clave es fuente + url + ean + título + vendedor + envase + provincia, con su observación más reciente de la ventana.
3. **$/L** = precio / (litros × unidades). Una caja de 12 × 1 L son 12 L.
4. **Sanidad**: un aviso con $/L fuera de [mediana ÷ 2,5; mediana × 2,5] del producto no cuenta (envase mal leído).
5. **Fuera del cálculo** (siguen listados con su motivo): sin litros, mayoristas, Grok sin verificar y los de la sanidad. Los servicios (combos con mano de obra) nunca entran.
6. **Promedio vs mediana**: el promedio es la media simple y lo mueve un aviso extremo; la mediana es el valor central. El desvío de cada publicación es contra la **mediana** del propio producto: `(precio_litro / mediana_litro - 1) × 100`.
7. **Comparación**: mediana de todos los avisos de los equivalentes incluidos (se excluyen los `no_equivalente` y los de mediana a más de 3 veces la de YPF) contra la mediana de YPF. Positivo: la competencia es más cara.

## Cómo usarlo bien

- Mirar `en_calculo`: una publicación con desvío enorme y `en_calculo = false` es casi seguro un envase mal leído, no un sobreprecio.
- Mirar `n` y `ventana`: con pocos avisos la mediana es frágil. Mirar `capturado` y `fecha`: el precio puede haber cambiado desde entonces.
- Citar siempre la `url` (publicación de un tercero) para que una persona pueda verificarla. Las de Grok con `verificado = false` no se confirmaron contra la página.
- `?formato=csv` entrega lo mismo aplanado: una fila por publicación con `rol` (`ypf` o `equivalente`), `producto_id`, `marca`, `nombre`, `tipo` y `evidencia`.
