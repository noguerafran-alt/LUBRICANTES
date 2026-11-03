
## 1. Fuente scrapeable (lo más importante)

| Endpoint | HTTP | Qué devuelve |
|---|---|---|
| `GET https://lubricantes.ypf.com/js/appsettings.json` | 200 | config: `METADATA_API_URL=https://magui.ypf.com/shp/yforms-lists/Metadata/`, `METADATA_API_DIRECTORY=PRODUCTION`, `SHAREPOINT_SITE_PATH=lubricantes` |
| `POST https://magui.ypf.com/shp/yforms-lists/Metadata/` (GraphQL, sin auth) | 200, ~305 KB | `getMetadataGlobal(type:PRODUCTION){title structure data props}`: es la base que alimenta el buscador de lubricantes.ypf.com. POST sin body: 400 |
| Listas útiles dentro de `getMetadataGlobal` | — | `PyS - Lubricantes ELAION` (13), `PyS - Lubricantes Extravida` (11), `PyS - Lubricantes ROD` (6), `PyS - Otros lubricantes` (38 grupos, ~100 productos), `PyS - Azul 32` (1), más las listas `PyS - Categorías - *` |
| Campos de cada ítem | — | `props{categoria, titulo, descripcion, imagen, imagen-guia, target}` y `children[type=documento-producto]{titulo, url}`, que traen la ficha técnica y la de seguridad |
| `https://elaion.com.ar/sitemap.xml` | 200 | 14 URLs `/productos/*.html`. Cada página trae "NOMBRE SAE API/ACEA BASE" en texto plano |
| `https://www.ypf.com/sitemap.xml` | 200 | inútil: solo 2 URLs. robots.txt: `Disallow:` vacío |
| `www.ypf.com/productosyservicios/lubricantes`, `/lubricantes` | 302 a error 404 | — |
| `tienda.ypf.com`, `www.tiendaypf.com.ar` | 000 (no resuelve) | no hay tienda YPF propia de lubricantes |
| `serviclub.com.ar` | 200 | sin catálogo de lubricantes (no lo profundicé) |
| Fichas PDF `lubricantes.ypf.com/docs/...` y `elaion.com.ar/fichas/...` | 200 (125/126) | `merak-rs.pdf` da 302. `extravida_xv_300_ft.pdf` es una imagen escaneada: sin texto, haría falta OCR |

Estrategia para el cron: un POST GraphQL diario con el diff de `data`, y re-bajar los PDFs cuando cambie la URL o la fecha. El costo es mínimo y entra en Render free.

Advertencia: la respuesta GraphQL trae acentos rotos (U+FFFD) desde el servidor. Hay que normalizar o completar los nombres con elaion.com.ar.

## 2. Catálogo YPF (133 ítems)


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

**No encontré en la fuente oficial:**
- Elaion Moto (en moto, la línea vigente es RÖD)
- "Elaion Auto"
- "Multigrado"
- Tractorol
- "Hidráulico AW" (existen Hidráulico BP/D/HSVI)

## 3. Lo que falta

- **Presentaciones en litros:** no hay fuente oficial. Las fichas dicen textual "Por disponibilidad de envases, consultar con su referente comercial", y ningún JSON de YPF tiene envases. La fuente real son los retailers VTEX, que probé:
  - Carrefour (`/api/catalog_system/pub/products/search?ft=elaion`): 200, 13 ítems, en 1 L y 4 L. Ejemplo: "Aceite Elaion FS 540 4 lts" a $159.999. Varios con precio 0, o sea sin stock.
  - Easy, mismo endpoint VTEX: 200, 3 ítems. Ejemplo: "Lubricante Semisintético 10W40 4 Lts YPF Elaion" a $100.350.
- **Normas por producto en "Otros":** sale un extracto automático por regex en `...\scratchpad\ypf\pds_extract.json` con estos campos: `sae, iso_vg, nlgi, api, acea, jaso, oem, base, ficha_n, fecha`. Las tablas multicolumna dejan columnas corridas, así que falta un parser por tabla o revisión manual antes de cargarlo como dato.

Fuentes web: [Easy MI 1540](https://www.easy.com.ar/lubricante-elaion-f10-15w40-mi-1540-x-4/p), [Easy TS 1040](https://www.easy.com.ar/lubricante-elaion-f30-10w40-ts-1040-x-4/p), [Easy YPF](https://www.easy.com.ar/ypf).