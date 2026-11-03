
# DISEÑO LUBRICANTES v1 (2026-11-03)

Criterio general: lo más simple que funcione. No hay base de datos ni servidor. GitHub Actions recolecta y comitea archivos al repo, y Render publica esos mismos archivos como sitio estático (visor y API). No hice pruebas HTTP nuevas en este paso. Todos los códigos HTTP de abajo vienen de los relevamientos de hoy.

## 1. Fuentes

### v1: entran (todas probadas funcionando)
| id | fuente | endpoint | aporta | frecuencia |
|---|---|---|---|---|
| ypf_gql | YPF magui (GraphQL, sin auth) | `POST https://magui.ypf.com/shp/yforms-lists/Metadata/` con `getMetadataGlobal(type:PRODUCTION){title structure data props}` | Catálogo YPF y URLs de fichas. Solo se guarda el diff | diaria |
| elaion_web | elaion.com.ar | `sitemap.xml` → `/productos/*.html` | Nombres con acentos, SAE, API/ACEA y base. Corrige los U+FFFD de la respuesta GraphQL | semanal |
| vtex_carrefour | Carrefour | `/api/catalog_system/pub/products/search?fq=C:/635/640/642/&_from&_to` | Precio, stock, EAN. Elaion, Gulf y Total (185) | diaria |
| vtex_masonline | ChangoMás | `fq=C:/1000039/2000174/3000496/` | Precio, stock, EAN. Elaion, Total, Puma, Elf, Petronas (61) | diaria |
| vtex_easy | Easy | `fq=C:/9/68/321/` | Precio, stock, EAN. YPF, Bardahl, Elf, Total, Goodyear (48) | diaria |
| vtex_jumbo | Jumbo (vale por Disco y Vea) | `fq=C:/16/126/412/` | Solo EAN y nombres de Shell, Castrol y Pennzoil. El precio se toma únicamente con `AvailableQuantity>0` | diaria |
| sepa | Precios Claros (CKAN) | `package_show?id=sepa-precios` → zip del día | Precio por sucursal y EAN (Carrefour y ChangoMás). Es la única fuente oficial | diaria |
| ml_cat | ML sin token | `/categories/{id}` (MLA375007 y sus hermanas) | Solo `total_items_in_this_category`, como métrica del tamaño de la oferta | diaria |

### Diferidas
| fuente | por qué |
|---|---|
| ML precios (`/products/search`, `/products/{id}/items`, `/items/bulk`, `/highlights`) | Todo lo que tiene precio pide OAuth y hay que crear la app en DevCenter. No se probó con token, y puede haber bloqueo por IP de datacenter (dato no oficial). El refresh_token es rotativo y habría que guardarlo como secret actualizado por la API de GitHub. ToS 7.5, 7.6 y la cláusula de divulgación a terceros: tiene que revisarlo Legales de YPF. **Es la única fuente con Shell, Castrol y Mobil en stock**, así que sin ella la competencia queda en Total, Gulf, Petronas, Puma, Elf y Bardahl |
| Scraping de listado.mercadolibre.com.ar y de mejorescompras.com.ar | Lo prohíbe la cláusula 7.6 o es un scraper de un scraper. Descartado, no diferido |
| Coto (Endeca) | Responde 200, pero tiene casi ningún lubricante de motor |
| Shell `.model.json`, Castrol HTML, Motul SSR | Solo traen nombres, no precios. Las normas se cargan a mano en el seed. Se automatiza recién cuando el seed no alcance |
| Mobil (403), Petronas (202 challenge), Total (catálogo en imágenes) | No se pueden scrapear |
| PDFs de fichas YPF con parser | `pds_extract.json` tiene columnas corridas. Se guardan las URLs y la revisión es manual. `extravida_xv_300_ft.pdf` necesita OCR |
| Frávega, Día, Cetrogar, Toledo, Blaisten, Sodimac, Disco, Vea | Responden vacío, no son VTEX o duplican a Jumbo |

## 2. Dónde corre y dónde persiste

**Recomendación: GitHub Actions cron + repo git como almacenamiento + Render Static Site.**
- `.github/workflows/recolectar.yml`: `cron: "0 9 * * *"` (06:00 ART) más `workflow_dispatch`. Ejecuta `python recolectar.py` (una sola corrida para todas las fuentes, 1 req/s por host). Comitea `data/`, y el push dispara el deploy de Render.
- SEPA corre en un job aparte del mismo workflow, porque baja 320 MB en unos 64 s. Abre el zip y cada zip interno por separado, en streaming. Filtra con la regex de aceite de motor y con los EAN conocidos (prefijo YPF `779096891` y los EAN de competidores que se vayan aprendiendo de VTEX). Al repo solo llegan las filas filtradas: unas 1.400 por día, entre Carrefour y ChangoMás.
- Por qué no Render: el disco es efímero, el servicio se duerme y no tiene cron, tiene 512 MB (SEPA no entra) y su Postgres free vence a los 30 días.
- Por qué no una DB externa: el volumen es bajo (unas 520 obs/día de VTEX y unas 1.400 de SEPA, menos de 30 MB/año en CSV) y git ya da historial, diff y backup.
- Render Static: no se duerme, así que la API responde siempre. **Gotcha conocido**: borrar un archivo del build no lo despublica, hay que pisar la ruta. Tampoco lee `render.yaml`, y el build command se carga en el panel.
- **Gotcha por validar el primer día**: si Carrefour (detrás de Cloudflare) da 403 desde Actions, queda en `fuentes.json` como caída, y su precio sigue llegando por SEPA. Plan B: correr `recolectar.py` desde esta PC con el Programador de tareas y pushear.
- Privacidad: el sitio estático es público. Los precios son públicos, pero las equivalencias y el índice son análisis de YPF. Si eso no puede quedar abierto, el plan es un Render Web Service con un FastAPI mínimo que sirva `data/` con Basic Auth (se duerme). Por defecto queda el estático. **Hay que decidirlo antes de publicar.**

## 3. Estructura del repo (lo mínimo)
```
LUBRICANTES/
  recolectar.py        # todas las fuentes → data/obs/AAAA-MM.csv + data/fuentes.json
  sepa.py              # job aparte (streaming zip)
  normalizar.py        # aviso → producto_id (regex + alias); test en __main__
  build.py             # data/ → site/api/*.json|csv (índice, último precio)
  seed/productos.csv   # catálogo normalizado YPF + competencia (manual + ypf_gql)
  seed/alias.csv       # nombre viejo/retailer → producto_id
  seed/equivalencias.csv
  data/obs/2026-11.csv # append-only, particionado por mes
  data/sin_match.csv   # avisos que no matchearon (cola de revisión manual)
  data/fuentes.json
  site/index.html, evolucion.html, indice.html, fuentes.html (+ app.js vanilla)
  ESTADO.md
```

## 4. Esquema

**productos.csv** (PK `producto_id` = slug `marca-linea-nombre-sae`, por ejemplo `ypf-elaion-ts1040-10w40`)
`producto_id, marca, linea, nombre, segmento{pcmo|hddo|moto4t|moto2t|transmision|grasa|industrial|marino|gas|otro}, sae, base{mineral|semisintetico|sintetico|null}, api, acea, ilsac, jaso, oem (separadas por ";"), fuente_specs (url), verificado{confirmado|inferido}`
No lleva litros, porque la presentación es atributo de la observación (el mismo producto se vende en 1 L y en 4 L).

**obs/AAAA-MM.csv** (append-only)
`fecha, fuente, url, ean, titulo_crudo, marca_cruda, precio, precio_lista, stock{int|null}, vendedor, sucursal (solo SEPA), litros, unidades, producto_id (vacío si no matcheó), match{ean|regex|alias|none}`
- `precio_litro = precio / (litros × unidades)` se calcula en build y no se guarda.
- Regla de ingesta: si `stock == 0` o `precio <= 0`, no se escribe fila de precio. Se cuenta igual en `fuentes.json.sin_stock`.
- En Cencosud se descarta `ListPrice`, que viene inflado unas 82 veces.

**equivalencias.csv**
`eq_id, ypf_id, comp_id, tipo{match_total|match_total_probable|match_parcial|sustituto_comercial|no_equivalente}, criterio (texto), evidencia{confirmada|inferida}, fuente`
Son tipo y evidencia, no un número de confianza inventado.

**fuentes.json** (una entrada por fuente y por corrida)
`{fuente, fecha, http, n_items, n_con_precio, n_sin_stock, n_sin_match, ultimo_ok, error}`

## 5. Normalización aviso → producto
Orden: la primera regla que matchea gana. Todas en `normalizar.py`, con `assert`s en `__main__` usando títulos reales.
1. **EAN** conocido en `alias.csv` (columna ean) → `producto_id`, `match=ean`.
2. Texto: minúsculas, sin acentos, `U+FFFD` → `""`.
3. **SAE**: `\b(0|5|10|15|20|25)\s*w\s*[-/ ]?\s*(20|30|40|50|60)\b` → `5W-30`. Monogrado `\bsae\s*(30|40|50|90|140)\b`. Gear `\b(75|80|85)w\s*-?\s*(90|140)\b`. Si no hay SAE, se deduce del código YPF en el paso 5.
4. **Litros**: `(\d+(?:[.,]\d+)?)\s*(l|lt|lts|litro|litros)\b`, o bien `(\d+)\s*ml` /1000, o bien `\bx\s*(\d+)\b` al final, que se toma como litros solo en lubricantes de motor (la regla dudosa va con un assert). **Unidades**: `x\s*(\d+)\s*unidades`. Si falla, `UNITS_PER_PACK`=1.
5. **Marca**: diccionario en minúscula. `elaion|ypf|extravida|rod|röd`→YPF, `helix|rimula|shell`→Shell, `edge|magnatec|gtx|vecton|castrol`→Castrol, `mobil|delvac`→Mobil, `quartz|rubia|total`→TotalEnergies, `elf`, `gulf`, `petronas|syntium|urania`, `motul`, `bardahl`, `puma`, `valvoline`, `pennzoil`, `liqui moly`. Si el campo VTEX `brand` existe, se usa primero.
6. **Línea/código**: cada marca tiene una lista de patrones que vive en `alias.csv`. YPF: `(auro\s+)?(hybrid\s+)?(d1|d2|fe|dpf|plus|fr)\s*0?(20|30|40)`, `\b(fs|ts|mi)\s*(530|540|1040|1540|2050)\b`, más alias viejos `f50|f30|f10` combinados con SAE. Ejemplo: Easy "Elaion F10 15W40 MI 1540" da MI por el código y lo confirma el SAE. Shell `hx\d|ultra professional (ag|af|am-l)|r4 ?[xl]`. Castrol `edge|magnatec|gtx` + SAE + sufijo (`ll`, `turbo diesel`, `c5`, `508 88`).
7. Clave = `(marca, linea_canonica, sae)` contra `productos.csv`. Exactamente un candidato → `match=regex|alias`. Cero o más de uno → `producto_id` vacío, y la fila va a `sin_match.csv` con el título. **No se adivina.**
8. Si un EAN matcheó por regex en 2 fuentes distintas con el mismo `producto_id`, se propone agregarlo a `alias.csv`. Es una propuesta en un PR manual, no automática.

**Equivalencia**: el `equivalencias.csv` es manual, sembrado con la lista de abajo. Hay un `sugerir_eq.py` que es opcional y diferido. Solo propone pares con SAE y segmento iguales, y les pone tipo según el criterio: SAE, familia ACEA y número C iguales, más OEM igual → `match_total`; OEM distinto o faltante → `match_parcial`; mismo SAE y segmento con nivel menor → `sustituto_comercial`. Sin SAE igual no hay equivalencia. Las sugerencias nunca se escriben solas en el seed.

## 6. API (estática, la genera `build.py`)
| ruta | contenido |
|---|---|
| `/api/productos.json` | catálogo normalizado |
| `/api/equivalencias.json` / `.csv` | seed con el join de nombres |
| `/api/ultimo.json` / `.csv` | último precio por (producto_id, fuente, litros) con `precio_litro` y fecha |
| `/api/obs/AAAA-MM.csv` | observaciones crudas del mes. Es el insumo para el análisis interno |
| `/api/serie/{producto_id}.json` | serie diaria: mediana de $/L por fuente |
| `/api/indice.json` / `.csv` | índice $/L por fecha, segmento, SAE y marca |
| `/api/oferta_ml.csv` | `total_items` diario por categoría de ML |
| `/api/fuentes.json` | estado de cada fuente |
| `/api/sin_match.csv` | cola de revisión |

Para el análisis interno alcanza con `pandas.read_csv("https://…/api/obs/2026-11.csv")`. No hacen falta filtros del lado del servidor, porque el volumen es chico.

**Índice $/L**: es la mediana de `precio_litro` de las observaciones con stock del día, agrupadas por (segmento, SAE, marca). La fórmula es `indice = mediana_marca / mediana_YPF × 100`, con el mismo segmento, SAE y día. Al ser relativo a YPF en pesos del mismo día, la inflación se cancela. Si YPF no tiene observación ese día y en ese grupo, la celda va vacía y no se calcula.

## 7. Páginas del visor (HTML con JS vanilla que lee `/api/*`)
- `index.html`, **Comparador**: cada fila es un producto YPF con sus equivalentes (tipo y evidencia como badge), el último $/L por fuente y la diferencia porcentual contra YPF. Filtros por segmento y SAE.
- `evolucion.html?p=`, **Evolución**: líneas de $/L por fuente para el producto y sus equivalentes. Los huecos se muestran como huecos.
- `indice.html`, **Índice**: matriz marca × (segmento, SAE) con el índice del último día y una sparkline de 90 días.
- `fuentes.html`, **Estado**: tabla de `fuentes.json` con la última corrida OK, el HTTP, los ítems, y `sin_match`.
- No es solo una página de estado: estos mismos textos de estado aparecen dentro de las otras páginas.

## 8. Riesgos y cómo se ve una caída
| riesgo | efecto | cómo se muestra |
|---|---|---|
| Fuente caída o 403 (Carrefour/Cloudflare desde Actions) | ese día no se escriben filas. No se arrastra el precio del día anterior | banner: "Carrefour: sin datos desde 2026-11-05 (HTTP 403)". El gráfico corta la línea |
| VTEX cambia el id de categoría | n_items=0 con HTTP 200 | `fuentes.json` marca `n_items=0` como error, con el texto "categoría vacía, revisar fq" |
| Competencia sin stock en retail (Shell, Castrol, Mobil) | el comparador queda sin precio para esos competidores | celda: "sin oferta con stock en fuentes v1 (falta ML)", nunca 0 ni "—" sin explicación |
| Fichas muertas de Cencosud | precios basura | se filtran por stock. Si no queda nada, se aplica la misma regla de vacío explicado |
| Error de matcheo | precio atribuido al producto equivocado | solo cuentan los matches únicos. El resto se ve en `sin_match.csv` y en el contador de `fuentes.html` |
| Acentos rotos en GraphQL de YPF | nombres feos | se usa el nombre canónico de `productos.csv`, y el diff de GraphQL solo avisa de altas y bajas |
| SEPA cambia de formato o pesa más | el job falla | queda en el estado como `sepa` caída. El resto de las fuentes no se ve afectado porque es otro job |
| Repo crece | +30 MB/año | se acepta. Recién si pasa 500 MB se mueve `obs/` a Releases |
| ML ToS y divulgación | legal | queda diferida hasta que Legales lo revise |

## 9. Conflictos entre relevamientos (resolver en el seed, marcado `inferido` hasta verificar)
- **D1 020 / D1 530**:
  - Relevamiento YPF (elaion.com.ar): API SQ-RC con ILSAC GF-7A.
  - Brochure de noviembre 2024: SP-RC con GF-6A.
  - Gana el más nuevo, elaion.com.ar. Hay que confirmarlo con la ficha.
- **DPF 530**: el OEM VW 504/507, Porsche C30, MB 229.51/52 aparece solo en el brochure. Ese dato sostiene la equivalencia #7 con Castrol EDGE LL.
- **FS 530 / FS 540**:
  - FS 530: SN en elaion.com.ar, SN Plus en el brochure.
  - FS 540: SN en elaion.com.ar, SP en el brochure.
- **Alias F50 5W-40**:
  - El relevamiento YPF lo verificó en retailers (Easy y Carrefour publican los dos nombres juntos): F50 5W-40 = FS 540.
  - El relevamiento de competencia lo infirió: Auro FR 540 / Plus 540.
  - **Gana FS 540, que es evidencia de góndola.** Pasa lo mismo con F50 5W-30, que es FS 530 y no Auro FE/D2/DPF. Los alias F50E, F50d2 y F70E quedan inferidos.
- **COMPETICIÓN 5W-50**: figura en elaion.com.ar pero no en la API YPF. Se carga con `verificado=inferido`.

---

## SEED: catálogo YPF (tal como vino del relevamiento YPF, sección 2)

**ELAION (auto, nafta/diésel/GNC).** Datos verificados en elaion.com.ar:
- AURO HYBRID D1 020, 0W-20, API SQ-RC, ILSAC GF-7A, sintético. OEM: dexos1 Gen3, Ford WSS-M2C962-A1
- AURO HYBRID D1 530, 5W-30, API SQ-RC, ILSAC GF-7A, sintético. OEM: dexos1 Gen3, Ford WSS-M2C961-A1
- AURO D2 530, 5W-30, API SN, ACEA C3, sintético. OEM: dexos2
- AURO FE 530, 5W-30, API SN, ACEA A5/B5, sintético. OEM: Ford WSS-M2C913-D
- AURO HYBRID DPF 530, 5W-30, API SP-RC, ACEA C3, sintético (para DPF/GPF/TWC)
- AURO PLUS 540, 5W-40, API SN, ACEA A3/B4, sintético. OEM: VW 508.88/509.99
- AURO FR 530, 5W-30, ACEA C2, sintético. OEM: PSA B71 2290
- AURO FR 540, 5W-40, API SP, ACEA A3/B4, sintético. OEM: PSA B71 2296, Porsche A40, VW 502.00/505.00
- COMPETICIÓN, 5W-50, API SN, ACEA A3/B4, sintético. Figura en elaion.com.ar pero no en la API de lubricantes.ypf.com
- FS 530, 5W-30, API SN, ACEA C3, sintético
- FS 540, 5W-40, API SN, ACEA C3, sintético
- TS 1040, 10W-40, API SN/CF, ACEA A3/B4, semisintético
- MI 1540, 15W-40, API SN/CF, ACEA A3/B4, mineral
- MI 2050, 20W-50, API SN/CF, ACEA A3/B4, mineral
- Ficha 285 (marzo 2024): para la familia FS/TS/MI aparecen MB 229.1, MB 229.31, PSA B71 2300 y VW 501.01. Falta confirmar a qué grado corresponde cada una.
- Renombre verificado. elaion.com.ar sigue usando los nombres viejos y la ficha 285 los nuevos. Easy y Carrefour publican ambos juntos ("Elaion F10 15W40 MI 1540", "F30 10W40 TS 1040"):
  - F50 5W-30 = FS 530
  - F50 5W-40 = FS 540
  - F30 10W-40 = TS 1040
  - F10 15W-40 = MI 1540
  - F10 20W-50 = MI 2050

**EXTRAVIDA (diésel pesado).** Ficha 282 (agosto 2026) para la serie XVT. La tabla en layout se desfasa, así que validar a mano. Entre paréntesis, el segmento.
- XVT 300 (transporte), 15W-40, mineral API Grupo II. API CK-4/SN, ACEA E7/E11, VDS-4.5, CES 20086, DH-2, Allison TES 439
- XVT 450 (transporte), 10W-40, semisintético. CI-4, E4/E7, VDS-3
- XVT 550 5W-30 (transporte): OEM Ford WSS-M2C212-A1
- XVT 550 10W-40 (transporte): OEM Scania (LDF-3), M3277, CF
- XVT 600 (transporte), 10W-40. CK-4, E6/E7/E11, VDS-4, M3477, CES 20081
- XVT 650 (transporte), 5W-30. CK-4/SN Plus, E6/E7/E11, VDS-4.5, M3775, LDF-4
- XV 100 (mainstream): CI-4/SL, E7, VDS-2, CES 20071, M3275, ECF-1a. SAE "----" en la ficha
- XV 300 (mainstream): CI-4 Plus/SL, E7, DTFR 15B110, VDS-3, CES 20078, ECF-2, DHD-1
- XVA 300 (agro): CK-4/SN, E7/E11, DTFR 15C100, VDS-4.5, CES 20086, ECF-3, M3775/M3575, DH-2, TES 439
- XVI 200 (ferroviario/MTU), 15W-40. CI-4/SL, MTU Tipo 2
- XVI 500 (minería/O&G), 5W-40. CK-4/CJ-4/CI-4 Plus, E7/E11, CES 20086/20081, ECF-3/ECF-2, VDS-4.5, DTFR 15C100, TES 439

**RÖD (moto).** Ficha 290, mayo 2024:
- 4T 20W-50: mineral, API SL, JASO MA2
- 4T 10W-30: semisintético, API SL, JASO MA2
- 4T 10W-40: semisintético, API SL, JASO MA2
- 4T 10W-50: sintético, API SN, JASO MA2
- 2T: semisintético, JASO FC, API TC
- Cadenas: aerosol

**Otros lubricantes (~100 SKUs-ficha)**
- Motores de alto kilometraje: Super 20W-50 (API SF/CF), Normal, HD Suplemento, Multiturbo, Multiturbo 25W-60, Multiturbo 20W-50, HD Diesel, Diesel BC, AT Turbo
- Transmisión:
  - ATF: Hidro ATF, ATF Sintético All, ATF D-VI, ATF D-III
  - Agrícola: Hidro 19
  - Engranajes: Helicoidal STL 75W-90, Helicoidal M 80W, Helicoidal 75W-90, Transmisión, Hipoidal Super S75W-90, Hipoidal Super (85W-140, MIL-PRF-2105E), Hipoidal
  - Maquinaria pesada: FT Super, FT Super D 50
- Grasas:
  - Litio: Limit, 60/62/63 EP, Grasalgon, Nerea CLS 15, Nerea CL EP2, Nerea CL AW2, Limit WSO, 63 FC
  - Calcio: 3/8/30 C y 102, Nerea CS MO1
  - Compuestos para roscas: Crassus TC Premium, TC API, Perfo
  - Otras: PEX G 10716, Asfáltica fluida 650, 107 EP
- Industriales:
  - Hidráulicos: Hidro 19, HSVI, D, BP (ISO VG 22–320, Denison HF-0/HF-1, Eaton Vickers)
  - Refrigeración: Polar, Frigorífico
  - Engranajes: Transmisión EP, Molino TP, Gluma
  - Turbinas: EP, R
  - Compresores: Merak, Merak S
  - Guías y bancadas: Lissos
  - Herramientas neumáticas: Lissos N
  - Otros: Cilindro, Forestal 3040, Librador HTA, Sirus, Glico PRF
  - Aislación eléctrica: Transformador, Transformador HFP
- Procesos: Butia DW 50, Solubles, Corte neto, Temple, Transferencia térmica
- Marinos: Atlanta Marine D 3005, Aurelia TI, Disola M, Talusia Universal, Talusia Universal 100, Talusia LS, Talusia HR 70. Náutica: Elaion Náutico 4T (10W-30), 2T, 2T Semisintético
- Gas: Vectis G2540 (15W-40), G2940, G540, G640, G740, G130, G140
- Ferroviario: Ferrodiesel 397, 597 II
- No son lubricantes: refrigerantes (Kriox Orgánico, Inorgánico, MTL 50, M EC 1, ATI), líquidos de frenos DOT 3/4, Línea cuidado (8) y Azul 32 (AdBlue)

**No encontré en la fuente oficial:** Elaion Moto (en moto, la línea vigente es RÖD), "Elaion Auto", "Multigrado", Tractorol, "Hidráulico AW" (existen Hidráulico BP/D/HSVI).


## SEED: catálogo YPF según brochure (relevamiento de competencia, tal como vino)
```json
[
  {"nombre":"Elaion Auro D1 020","sae":"0W-20","base":"sintetico","api":"SP-RC","ilsac":"GF-6A","oem":["GM dexos1 Gen3","Ford WSS-M2C962-A1"]},
  {"nombre":"Elaion Auro D1 530","sae":"5W-30","base":"sintetico","api":"SP-RC","ilsac":"GF-6A","oem":["GM dexos1 Gen3","Ford WSS-M2C961-A1"]},
  {"nombre":"Elaion Auro D2 530","sae":"5W-30","base":"sintetico","api":"SN","acea":"C3","oem":["GM dexos2"]},
  {"nombre":"Elaion Auro FE 530","sae":"5W-30","base":"sintetico","api":"SN","acea":"A5/B5","oem":["Ford WSS-M2C913-D"]},
  {"nombre":"Elaion Auro DPF 530","sae":"5W-30","base":"sintetico","api":"SP-RC","acea":"C3","oem":["VW 504.00/507.00","Porsche C30","MB 229.51/229.52"]},
  {"nombre":"Elaion Auro Plus 540","sae":"5W-40","base":"sintetico","api":"SN","acea":"A3/B4","oem":["VW 508.88/509.99"]},
  {"nombre":"Elaion Auro FR 530","sae":"5W-30","base":"sintetico","acea":"C2","oem":["PSA B71 2290"]},
  {"nombre":"Elaion Auro FR 540","sae":"5W-40","base":"sintetico","api":"SP","acea":"A3/B4","oem":["PSA B71 2296","Porsche A40","VW 502.00/505.00"]},
  {"nombre":"Elaion FS 530","sae":"5W-30","base":"sintetico","api":"SN Plus","acea":"C3"},
  {"nombre":"Elaion FS 540","sae":"5W-40","base":"sintetico","api":"SP","acea":"C3"},
  {"nombre":"Elaion TS 1040","sae":"10W-40","base":"semisintetico","api":"SN/CF","acea":"A3/B4"},
  {"nombre":"Elaion MI 1540","sae":"15W-40","base":"mineral","api":"SN/CF","acea":"A3/B4"},
  {"nombre":"Elaion MI 2050","sae":"20W-50","base":"mineral","api":"SN/CF","acea":"A3/B4"},
  {"nombre":"Extravida XV300","sae":"15W-40","base":"mineral","api":"CI-4 Plus","acea":"E7","oem_segun_prensa_BR":["MB 228.3","Volvo VDS-3","MAN M3275","Renault RLD-2","CAT ECF-2","Deutz DQC II","DDC 93K214"]},
  {"nombre":"Extravida XVT300","sae":"15W-40","base":"mineral","api":"CK-4/SN","acea":"E7/E11"}
]
```
alias_viejo_a_nuevo_inferido (relevamiento de competencia; ver el conflicto en §9):
```json
{"F50 5W-40 (VW 502/505)":"Auro FR 540 (si en la ficha vieja figura VW 508.88, es Auro Plus 540)","F50E 5W-30":"Auro FE 530","F50d2 5W-30":"Auro D2 530","F70E 5W-30":"Auro DPF 530","F30 10W-40":"TS 1040","F10 mineral":"MI 1540 / MI 2050","nota":"Inferido por coincidencia de SAE y normas. YPF no publicó una tabla de correspondencia que se haya podido encontrar."}
```

## SEED: equivalencias (tal como vinieron)
```json
[
  {"id":1,"ypf":"Elaion Auro FR 540 5W-40","comp":"Castrol EDGE 5W-40","tipo":"match_total","just":"A3/B4, VW 502.00/505.00 y Porsche A40 en ambos","evidencia":"confirmada (brochure YPF + castrol.com/es_ar)"},
  {"id":2,"ypf":"Elaion Auro FR 540 5W-40","comp":"Mobil Super 3000 X1 5W-40","tipo":"match_total","just":"A3/B4, VW 502/505, A40 y PSA B71 2296 en ambos","evidencia":"confirmada del lado Mobil solo por resumen de búsqueda de mobil.com/en-ar (curl 403) y del PDF de moovelub"},
  {"id":3,"ypf":"Elaion Auro FR 540 5W-40","comp":"TotalEnergies Quartz 9000 5W-40","tipo":"match_total","just":"A3/B4, VW 502/505, PSA B71 2296","evidencia":"inferida (normas sacadas de retailer europeo; venta en AR de la 9000 5W-40 sin verificar)"},
  {"id":4,"ypf":"Elaion Auro FR 540 5W-40","comp":"Motul 8100 X-cess gen2 5W-40","tipo":"match_parcial","just":"mismo SAE y segmento; normas no verificadas","evidencia":"inferida (solo nombre en motul.com/es-AR)"},
  {"id":5,"ypf":"Elaion Auro Plus 540 5W-40","comp":"Castrol MAGNATEC 5W-40 '508 88'","tipo":"match_total probable","just":"el nombre comercial AR indica VW 508.88, igual que Plus 540","evidencia":"inferida (la norma surge del nombre, no de la ficha)"},
  {"id":6,"ypf":"Elaion Auro Plus 540 5W-40","comp":"Shell Helix HX8 Professional AV 5W-40","tipo":"match_parcial","just":"una fuente minorista le atribuye VW 508.88/509.99; otra, VW 502/505","evidencia":"inferida (fuentes en conflicto)"},
  {"id":7,"ypf":"Elaion Auro DPF 530 5W-30","comp":"Castrol EDGE 5W-30 LL","tipo":"match_total","just":"C3, VW 504.00/507.00, Porsche C30, MB 229.51","evidencia":"confirmada (brochure YPF + castrol.com/es_ar)"},
  {"id":8,"ypf":"Elaion Auro DPF 530 5W-30","comp":"Shell Helix Ultra Professional AM-L 5W-30","tipo":"match_parcial","just":"en la nomenclatura Shell, AM-L = Mercedes low-SAPS (C3/229.51)","evidencia":"inferida (ninguna ficha encontrada lo confirma)"},
  {"id":9,"ypf":"Elaion Auro D2 530 5W-30","comp":"Shell Helix Ultra Professional AG 5W-30","tipo":"match_total probable","just":"en la nomenclatura Shell, AG = GM dexos2 / C3","evidencia":"inferida"},
  {"id":10,"ypf":"Elaion Auro D2 530 5W-30","comp":"Castrol EDGE 5W-40 Turbo Diesel","tipo":"no_equivalente (SAE distinto)","just":"comparte C3 y dexos2, pero es 5W-40. Útil solo para comparar precio dentro del segmento diésel","evidencia":"confirmada (castrol.com/es_ar)"},
  {"id":11,"ypf":"Elaion Auro FE 530 5W-30","comp":"Shell Helix Ultra Professional AF 5W-30","tipo":"match_total","just":"A5/B5 y Ford WSS-M2C913-D en ambos","evidencia":"confirmada (brochure YPF + ficha Shell AU/DE; venta en AR confirmada por shell.com.ar)"},
  {"id":12,"ypf":"Elaion Auro FE 530 5W-30","comp":"Motul 8100 Eco-nergy 5W-30","tipo":"match_parcial","just":"mismo SAE, posicionamiento Ford/fuel economy","evidencia":"inferida"},
  {"id":13,"ypf":"Elaion Auro D1 020 0W-20","comp":"Castrol EDGE 0W-20 C5","tipo":"match_total","just":"API SP, GF-6, dexos1 Gen3, Ford WSS-M2C962-A1","evidencia":"confirmada (brochure YPF + castrol.com/es_ar)"},
  {"id":14,"ypf":"Elaion Auro D1 530 5W-30","comp":"Castrol EDGE 5W-30","tipo":"match_parcial","just":"ambos dexos1, pero Gen3 (YPF) contra Gen2 (Castrol) y Ford 961-A1 contra 946","evidencia":"confirmada (las fichas muestran la diferencia)"},
  {"id":15,"ypf":"Elaion Auro FR 530 5W-30","comp":"TotalEnergies Quartz Ineo ECS 5W-30","tipo":"match_total","just":"PSA B71 2290 y low SAPS (C2)","evidencia":"confirmada para la norma (catálogo TotalEnergies) / inferida para la venta en AR (Masonline lista 'Quartz Ineo 5W-30' sin decir ECS)"},
  {"id":16,"ypf":"Elaion FS 530 5W-30","comp":"Mobil 1 ESP 5W-30","tipo":"match_parcial","just":"ambos C3; Mobil SP contra YPF SN Plus","evidencia":"confirmada (resumen de búsqueda de mobil.com/es-ar)"},
  {"id":17,"ypf":"Elaion FS 540 5W-40","comp":"Castrol EDGE 5W-40 Turbo Diesel","tipo":"match_parcial","just":"5W-40 C3 en ambos; Castrol suma VW 505.01, MB 229.51 y dexos2","evidencia":"confirmada"},
  {"id":18,"ypf":"Elaion TS 1040 10W-40","comp":"Shell Helix HX7 10W-40","tipo":"match_total","just":"SN/CF A3/B4","evidencia":"inferida (la norma sale del título de góndola en VTEX Vea: 'Hx7 (sn/cf/a3/b4)')"},
  {"id":19,"ypf":"Elaion TS 1040 10W-40","comp":"Castrol MAGNATEC 10W-40 A3","tipo":"match_parcial","just":"API SN/CF igual; ACEA no declarada en la página AR","evidencia":"confirmada solo para API"},
  {"id":20,"ypf":"Elaion TS 1040 10W-40","comp":"TotalEnergies Quartz 7000 10W-40","tipo":"match_parcial","just":"mismo SAE y segmento semisintético","evidencia":"inferida (en stock en Carrefour; normas sin relevar)"},
  {"id":21,"ypf":"Elaion MI 1540 15W-40","comp":"Shell Helix HX5 15W-40","tipo":"sustituto_comercial","just":"Shell es SL/CF A2/B2, nivel menor que SN/CF A3/B4","evidencia":"inferida (título de góndola en Vea)"},
  {"id":22,"ypf":"Elaion MI 1540 15W-40","comp":"Gulf Max 15W-40","tipo":"match_parcial","just":"mismo SAE, mineral","evidencia":"inferida (en stock en Carrefour; normas sin relevar)"},
  {"id":23,"ypf":"Elaion MI 2050 20W-50","comp":"Castrol GTX 20W-50 / Gulf Max 20W-50 / Shell Helix HX3 20W-50","tipo":"match_parcial / sustituto_comercial","just":"mismo SAE. HX3 figura SG/CD, muy por debajo de SN/CF","evidencia":"inferida"},
  {"id":24,"ypf":"Extravida XVT300 15W-40","comp":"Shell Rimula R4 L 15W-40 / Castrol Vecton 15W-40 CK-4","tipo":"match_total","just":"API CK-4 con ACEA E7/E11 (Rimula R4 L: CK-4, E7/E9/E11; Vecton: CK-4, ECF-3, VDS-4.5)","evidencia":"confirmada (fichas Shell y Castrol de otros países); venta de cada una en AR sin verificar"},
  {"id":25,"ypf":"Extravida XV300 15W-40","comp":"Shell Rimula R4 X 15W-40","tipo":"match_total","just":"CI-4 / E7 / mineral; ambos con CAT ECF-2","evidencia":"confirmada (ficha Shell en español + resumen del brochure YPF)"}
]
```
Notas para cargar el seed en `equivalencias.csv`:
- #23 y #24 van partidas en una fila por competidor.
- #10 queda como `no_equivalente` y solo se usa para comparar precio.
- #3, #24 y #25 tienen la venta en AR sin verificar. No muestran precio hasta que aparezca una observación.

## Pendiente de decisión antes de codear
1. ¿El sitio puede ser público (estático), o necesita Basic Auth (web service que se duerme)?
2. Para ML con token hacen falta tres cosas: crear la app en DevCenter (lo hace el usuario), que Legales de YPF revise los ToS, y repetir la tabla de pruebas con un Bearer token. Sin eso, Shell, Castrol y Mobil quedan sin precio en la v1.
3. El primer día, una corrida de prueba en Actions para validar Carrefour detrás de Cloudflare.