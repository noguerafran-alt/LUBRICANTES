{
  "fecha": "2026-11-03",
  "hallazgos_clave": [
    "YPF renombró la línea Elaion. El brochure oficial 'VERSIÓN 4 - NOVIEMBRE 2024' trae la nomenclatura nueva: Auro D1 020, D1 530, D2 530, FE 530, DPF 530, Plus 540, FR 530, FR 540; FS 530, FS 540, TS 1040, MI 1540, MI 2050. Las góndolas activas ya usan esos nombres (Masonline 'Elaion Mi 2050', Carrefour 'Elaion ts 1040'). F10, F30, F50 y F50E siguen apareciendo, pero solo en catálogos viejos. Hace falta una tabla alias para pasar de nombre viejo a nuevo.",
    "El VTEX de Cencosud (vea.com.ar y jumbo.com.ar) devuelve 200 con lubricantes Shell, Castrol e YPF, pero todos tienen AvailableQuantity=0 y precios absurdos (Price 135.69 contra ListPrice 11214). Son fichas muertas: sirven para EAN y nombres, no para precios. Hay que filtrar por AvailableQuantity>0.",
    "Las fuentes de precio vivas probadas son tres VTEX. masonline.com.ar tiene 15 Elaion en stock y 4 Total Quartz. carrefour.com.ar tiene 1 Elaion, 6 Gulf y Total Quartz 9000/7000. easy.com.ar tiene solo 3 Elaion. Shell, Castrol, Mobil, Valvoline, Motul y Petronas no tienen ningún SKU en stock en esos sitios: para la competencia hace falta Mercado Libre u otros canales.",
    "No se encontró una cifra confiable de participación de mercado por marca en lubricantes. El único dato es Shell, que dice estar segunda con 'ronda el 20%', en una nota sin fecha de infonegocios.info."
  ],
  "ypf_fuente": {
    "sitio": "https://lubricantes.ypf.com",
    "http": 200,
    "scrapeable": "parcial",
    "detalle": "El buscador.html se carga en el cliente (Vue + SharePoint). appsettings.json es público (200) y declara METADATA_API_URL=https://magui.ypf.com/shp/yforms-lists/Metadata/ (POST), pero el HTML trae 'No se encontraron productos'. La fuente estructurada confiable es el PDF https://elaion.com.ar/assets/BrochureELAION.pdf (200, 8.1 MB, pdftotext OK). Extravida: https://lubricantes.ypf.com/docs/extravida/extravida-brochure.pdf (200, 6.7 MB, PDF dañado: pdftotext y pypdf fallan, y WebFetch excede el tamaño). Sus datos se tomaron de un resumen de búsqueda.",
    "productos_confirmados_brochure": [
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
      {"nombre":"Elaion MI 2050","sae":"20W-50","base":"mineral","api":"SN/CF","acea":"A3/B4"}
    ],
    "pesados_extravida_segun_resumen_de_busqueda": [
      {"nombre":"Extravida XV300","sae":"15W-40","base":"mineral","api":"CI-4 Plus","acea":"E7","oem_segun_prensa_BR":["MB 228.3","Volvo VDS-3","MAN M3275","Renault RLD-2","CAT ECF-2","Deutz DQC II","DDC 93K214"]},
      {"nombre":"Extravida XVT300","sae":"15W-40","base":"mineral","api":"CK-4/SN","acea":"E7/E11"}
    ],
    "alias_viejo_a_nuevo_inferido": {
      "F50 5W-40 (VW 502/505)":"Auro FR 540 (si en la ficha vieja figura VW 508.88, es Auro Plus 540)",
      "F50E 5W-30":"Auro FE 530",
      "F50d2 5W-30":"Auro D2 530",
      "F70E 5W-30":"Auro DPF 530",
      "F30 10W-40":"TS 1040",
      "F10 mineral":"MI 1540 / MI 2050",
      "nota":"Inferido por coincidencia de SAE y normas. YPF no publicó una tabla de correspondencia que se haya podido encontrar."
    }
  },
  "competidores": [
    {"marca":"Shell","operador_AR":"Raízen (según prensa, Mercuria acordó comprar Raízen Argentina, incluida la planta de lubricantes)","lineas":["Helix Ultra Professional AG/AF/AM-L 5W-30","Helix HX8 Professional AG 5W-30 / AV 5W-40","Helix HX7","Helix HX5","Helix HX3","Rimula (R4 X, R4 L)","Advance (motos)"],
     "fuente":"https://www.shell.com.ar/conductores/aceites-para-motor.html","http":200,
     "scrapeable":"si, solo nombres","detalle":"AEM: agregando .model.json a cualquier página se obtiene JSON (200). Probado en .../motores-de-autos/sinteticos.model.json y en .../lubricantes-motores-trabajos-pesados.model.json. Trae nombres pero no normas. Para normas, la ficha global de Shell (epc.shell.com no respondió: 000). Lubematch: .../lubematch.html (200, carga JS)."},
    {"marca":"Castrol","operador_AR":"Axion Energy (axionenergy.com/castrol)","lineas":["EDGE (0W-20 C5, 0W-30, 5W-30, 5W-30 LL, 5W-40, 5W-40 Turbo Diesel)","MAGNATEC (10W-30, 10W-40 A3, 5W-40 508 88, Stop-Start 5W-30)","GTX (10W-40, 20W-50)","Vecton (pesados)","Actevo (motos)"],
     "fuente":"https://www.castrol.com/es_ar/argentina/home/products/our-brands/automotive/castrol-edge-oils/castrol-edge.html","http":200,
     "scrapeable":"si","detalle":"HTML server-side. Las páginas por viscosidad .../viscosity-grades/{5w-30,5w-40,...}.html listan productos. Las normas aparecen por pestaña (WebFetch las extrajo, el grep del HTML no: posible carga dinámica). Fichas PDF en msdspds.castrol.com/bpglis/FusionPDS.nsf (buscador: 202). Selector: https://www.selectorcastrol.com.ar (200)."},
    {"marca":"Mobil","operador_AR":"Moove (Cosan), no Axion","lineas":["Mobil 1 (ESP 5W-30, 0W-40)","Super 3000 X1 5W-40","Super 2000/1000","Delvac"],
     "fuente":"https://www.mobil.com/es-ar/passenger-vehicle-lube/pds/...","http":403,
     "scrapeable":"no por curl (anti-bot 403). Sí por buscador web.","detalle":"Alternativa: PDFs del distribuidor ar.moovelub.com/storage/uploads/*.pdf (200, application/pdf), p. ej. 00000000897.pdf = Super 3000 X1 5W-40."},
    {"marca":"TotalEnergies (+ELF)","lineas":["Quartz 9000, 7000, Ineo (ECS)","Rubia (TIR, Fuel Economy, Clean Shield)"],
     "fuente":"https://totalenergies.com.ar/es/aceite-de-motor/aceite-de-auto/aceites-quartz","http":200,
     "scrapeable":"parcial","detalle":"Hay HTML, pero el catálogo está en imágenes. El catálogo global con normas es lubricants.catalog.totalenergies.com (200; catalog-ar y catalogue-ar dan 404). Retail vivo: Carrefour y Masonline."},
    {"marca":"Petronas","lineas":["Syntium","Urania"],"fuente":"https://www.pli-petronas.com/es-ar","http":202,"scrapeable":"no (202 sin cuerpo, challenge)","detalle":"Para Syntium 3000 5W-40 no se encontró ficha AR. Lo más cercano es Syntium Prime E 5W-40 (A3/B4, VW 502/505), con fuente europea."},
    {"marca":"Gulf","fuente":"https://www.gulfoil.com.ar -> https://latam.gulfoilltd.com/","http":200,"scrapeable":"si (HTML regional)","lineas":["Max 15W-40","Max 20W-50 (en stock en Carrefour)"]},
    {"marca":"Valvoline","fuente":"https://www.valvoline.com.ar -> https://www.valvolineglobal.com/es-ar/","http":200,"scrapeable":"sin verificar (no se encontraron links de producto en el HTML)"},
    {"marca":"Motul","fuente":"https://www.motul.com/es-AR/products","http":200,"scrapeable":"si (Next.js SSR, nombres en HTML)","lineas":["8100 Eco-nergy 5W-30","8100 Eco-lite 5W-30","8100 X-clean EFE 5W-30","8100 X-cess gen2 5W-40"]},
    {"marca":"Puma Energy","fuente":"https://pumaenergy.com/es/country/argentina/","http":200,"scrapeable":"no hay catálogo: la página remite a un 'buscador de aceites'","lineas":"no se encontraron"},
    {"marca":"Liqui Moly","fuente":"https://www.liqui-moly.com/es/ar/","http":404,"scrapeable":"la ruta AR no existe; /es/ da 200","lineas":["Formula Super 5W-40 (ficha /es/)"]},
    {"marca":"Pennzoil","fuente":"pennzoil.com.ar (000) y pennzoil.com/es-ar (404)","scrapeable":"no","detalle":"No se encontró presencia oficial en AR."},
    {"marca":"Bardahl","fuente":"https://www.bardahl.com.ar","http":200,"scrapeable":"sin verificar","detalle":"Marca con sitio AR propio. Líneas no relevadas."},
    {"marca":"Repsol / Lubrax / Wanderlub / Iael","http":"000 en todos los dominios .com.ar probados","scrapeable":"no","detalle":"Presencia en AR no confirmada."}
  ],
  "criterio_equivalencia": {
    "claves_duras_deben_coincidir": ["segmento (PCMO liviano / HDDO pesado / moto 4T)","grado SAE exacto","nivel ACEA de la familia (A/B, C, E) y, dentro de C, el número (C2, C3, C5)","aprobación OEM que pide el vehículo (VW 50x, MB 229.x, dexos, Ford WSS, PSA B71, RN07x0)"],
    "claves_blandas_pueden_diferir": ["nivel API (SN vs SP; el mayor cubre al menor en nafta)","base (sintético vs semi) cuando las normas coinciden","presentación (1 L / 4 L / 5 L / balde 20 L); el precio se normaliza a $/L"],
    "score_sugerido": "match_total = SAE y ACEA y OEM iguales. match_parcial = SAE y ACEA iguales con OEM distinto o faltante. sustituto_comercial = mismo SAE y segmento con nivel inferior (sirve para comparar precio, nunca para recomendar uso). Sin SAE igual no hay equivalencia.",
    "evidencia": "confirmada = ficha oficial o página del fabricante de ambos lados. inferida = nomenclatura, retailer o ficha de otro país."
  },
  "equivalencias": [
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
  ],
  "huecos": [
    "Falta una ficha AR de Mobil Delvac, Petronas Urania y Total Rubia TIR para armar el resto de las equivalencias de pesados. Las búsquedas no devolvieron nada.",
    "Las normas de Shell AR no están en shell.com.ar; hay que ir a la ficha global (epc.shell.com no respondió).",
    "La lista completa de productos YPF del buscador (dice 'más de 500 lubricantes') no se pudo bajar: depende de un endpoint POST de SharePoint (magui.ypf.com) que no se probó."
  ],
  "archivos": {
  },
  "fuentes": ["https://elaion.com.ar/assets/BrochureELAION.pdf","https://lubricantes.ypf.com/js/appsettings.json","https://www.castrol.com/es_ar/argentina/home/products/our-brands/automotive/castrol-edge-oils/castrol-edge.html","https://www.castrol.com/es_ar/argentina/home/products/our-brands/automotive/castrol-magnatec-oils/castrol-magnatec.html","https://www.shell.com.ar/conductores/aceites-para-motor/motores-de-autos/sinteticos.model.json","https://www.mobil.com/en-ar/Passenger-Vehicle-Lube/pds/la-xx-Mobil-Super-3000-x1-5W-40","https://ar.moovelub.com/storage/uploads/00000000897.pdf","https://www.mobil.com/es-ar/passenger-vehicle-lube/pds/as-xx-mobil-1-esp-5w-30","https://www.shell.com.au/motorists/oils-lubricants/helix-for-cars/helix-fully-synthetic/shell-helix-ultra-professional-af-5w-30.html","https://elsalvador.pochteca.net/wp-content/uploads/2023/05/ft-rimula-r4x-15w-40.pdf","https://elsalvador.pochteca.net/wp-content/uploads/2023/05/ft-rimula-r4l-15w-40-ck-4.pdf","https://shop.sclubricants.com/pub/media/pds/castrol/pds-vecton-15w-40-ck-4.pdf","https://lubricants.catalog.totalenergies.com/CATALOGUETotalEnergies/en_UK/lkx_quartz-ineo-ecs-5w-30","https://omecanico.com.br/ypf-lanca-oleos-de-motor-elaion-tas-com-aprovacoes-de-montadoras/","https://infonegocios.info/plus/shell-apuesta-al-negocio-de-los-lubricantes-presento-helix-multicombustible","https://www.motul.com/es-AR/products","https://totalenergies.com.ar/es/aceite-de-motor/aceite-de-auto/aceites-quartz"]
}