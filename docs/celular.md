# Recolector de casa en el celular (Termux)

Por qué: SEPA (Precios Claros) y las ventas de la Secretaría de Energía bloquean las IP de GitHub y de Oracle. Desde una IP de casa responden. El celular
corre todos los días a las 06:00 (hora argentina), baja esos datos y los sube al repo. GitHub corre solo Mercado Libre (10:00) y, si el celular no
corrió, hace de respaldo con lo que sirva desde allá.

Si no tenés celular a mano, la PC con Windows hace lo mismo con la tarea programada `LUBRICANTES-SEPA` (ver `CLAUDE.md`, «Recolector de casa»).

## Qué necesitás

- Un celular Android que quede **enchufado y con WiFi** de casa.
- Una cuenta de GitHub con acceso de escritura al repo.

## Pasos

1. **Instalar Termux y Termux:Boot desde F-Droid** (https://f-droid.org). **No desde Play Store**: esa versión está abandonada y no funciona. Abrí las dos apps una vez.
2. **Sacar la optimización de batería** a Termux y a Termux:Boot: Ajustes > Aplicaciones > Termux > Batería > «Sin restricciones» (el nombre cambia según la marca). Sin esto Android mata el proceso. No hace falta `termux-setup-storage`.
   En Samsung, además: Ajustes > Batería > Límites de uso en segundo plano > «Aplicaciones que nunca se suspenden», y agregá Termux y Termux:Boot.
   Si el reloj está mal, en Samsung el WiFi dice «sin internet» (Android lo valida por HTTPS): cargá la fecha y la hora a mano.
3. En Termux, **bajar y correr el instalador** (instala python, git, cronie, termux-services, cloudflared y curl, clona el repo en `~/lub-casa`, crea el marcador `.recolector_casa`, deja el cron a las 06:00 hora argentina y el script de arranque en `~/.termux/boot/`):
   ```
   pkg install -y git
   git clone https://github.com/noguerafran-alt/LUBRICANTES.git ~/lub-casa
   bash ~/lub-casa/tools/termux_setup.sh
   ```
   **El repo es privado**: el token fine-grained (paso 5, sub-pasos 1 y 2) se crea **antes** del clone y es la «Password» que pide git (el usuario es el tuyo de GitHub). Antes del clone corré `git config --global credential.helper store` para que no lo vuelva a pedir.
   El instalador se puede correr de nuevo sin romper nada. No pide ni guarda ningún token.
4. **Mantener despierto el celular**: el instalador ya llama `termux-wake-lock` y el script de arranque lo repite tras cada reinicio.
5. **Token de GitHub** (lo creás y lo cargás vos; **nunca lo pegues en un chat ni en el repo**):
   1. GitHub > Settings > Developer settings > Personal access tokens > **Fine-grained tokens** > Generate new token.
   2. Repository access: **solo este repo**. Permissions > Repository permissions > **Contents: Read and write**. Nada más. Poné vencimiento y anotá la fecha para renovarlo.
   3. En Termux:
      ```
      cd ~/lub-casa
      git config credential.helper store
      git config user.name "recolector-casa"
      git push --dry-run origin HEAD:main
      ```
      Cuando pida usuario ponés el tuyo de GitHub y como contraseña el token. Queda guardado en `~/.git-credentials` del celular.
6. **Probar a mano sin publicar**:
   ```
   cd ~/lub-casa && python tools/recolector_casa.py --sin-push
   ```
   Hace todos los pasos y deja un commit local, sin subir nada. Tarda unos minutos (la SE, ~770 MB, solo se baja cuando publicó algo nuevo). Para publicar de verdad: `python tools/recolector_casa.py`.
7. **Ver el log**: `tail -50 ~/lub-casa/recolector_casa.log` (lo que hizo cada paso) y `tail ~/lub-casa/cron.log` (si el cron llegó a arrancarlo). Con el cron corriendo, `crontab -l` muestra la agenda.
8. **Reiniciar el celular una vez** para confirmar que Termux:Boot levanta `crond` y los servicios solos (`bash ~/lub-casa/tools/termux_setup.sh estado`). Termux:Boot hay que **abrirlo una vez** para que funcione. Tras un reinicio los servicios arrancan recién después del primer desbloqueo de pantalla: hasta entonces la página da error 1033 de Cloudflare.

## Servidor y túnel (el celu también sirve la página)

El mismo celular corre `python server.py` (servicio `lub-server`, solo en `127.0.0.1:8090`) y `cloudflared` (servicio `lub-tunel`) lo publica en **https://lubricantes.fln-data-analysis.com**. Render queda de respaldo. El instalador (`tools/termux_setup.sh`) ya instala `cloudflared`, crea los dos servicios y el cron del pull horario (minuto 20). Lo que falta lo hacés vos, una vez:

1. **Login de Cloudflare** (recomendado). En Termux:
   ```
   cloudflared tunnel login
   ```
   Imprime un link: abrilo en el navegador del celular, entrá a tu cuenta de Cloudflare y autorizá el dominio `fln-data-analysis.com`. Queda `~/.cloudflared/cert.pem`. El link vence a los ~10 minutos y cada `login` nuevo invalida el link anterior. Se puede autorizar desde la PC: `cloudflared` en el celu sondea cada ~55 s y toma la autorización solo.
2. **Crear el túnel y la ruta DNS**:
   ```
   cloudflared tunnel create lubricantes
   cloudflared tunnel route dns lubricantes lubricantes.fln-data-analysis.com
   ```
3. Dentro de unos segundos `lub-tunel` arranca solo (el servicio reintenta cada 5 minutos si todavía no había credenciales; para apurarlo: `sv restart lub-tunel`).
4. **Probar**: `bash ~/lub-casa/tools/termux_setup.sh estado` y, desde cualquier lado, `https://lubricantes.fln-data-analysis.com/salud`. Devuelve `{"ok": true, "commit": "...", "ultimo_dato": "AAAA-MM-DD", "equipo": {...}}`: el commit de datos que se sirve, la fecha de la última observación y el estado del equipo (`bateria` {pct, estado, temp_c} vía `termux-battery-status` o `/sys`, `disco_gb`, `server_arriba_s`, `equipo_arriba_s`, `trafico_24h` {pedidos, e4xx, e5xx, mb, ips, por_hora[24]} y `clipper` {clips, mb, ultimo}; lo desconocido es `null`; nunca IPs, rutas ni env). Si `ultimo_dato` queda viejo, mirá `~/lub-casa/pull.log`.
5. Si el proxy de YPF marca el dominio como «sin categoría», pedir que lo categoricen, igual que se hizo con A4D.

**Variante con token** (si preferís no hacer el login en el celular): en el panel de Cloudflare (Zero Trust > Networks > Tunnels) creá un túnel, apuntá el hostname `lubricantes.fln-data-analysis.com` a `http://127.0.0.1:8090` y guardá el token en `~/.lub-tunel-token` (`chmod 600`). El servicio lo lee de ahí; el instalador nunca lo pide ni lo guarda. **Nunca pegues el token en un chat ni en el repo.**

**Qué hace cada cosa**: el server recarga los datos solo (cada 5 minutos mira si cambió el commit del clon; no hace falta reiniciarlo). El pull horario trae lo que sube GitHub (Mercado Libre a las 10:00) y la PC. Un cambio de **código** de `server.py` entra solo: el mismo chequeo de 5 minutos ve que cambió el archivo (con más de 30 s de antigüedad y que compila) y el server sale para que runit lo levante con el código nuevo. **La primera vez** hace falta un `sv restart lub-server` (o reiniciar el celu) para que entre este código; después, el pull horario alcanza. Un cambio solo de `site/` ya se sirve sin reiniciar. Logs en `~/lub-casa/logs/` (`server.log`, `tunel.log`, `pull-cron.log`).

**Cloudera**: apuntarlo a `https://lubricantes.fln-data-analysis.com` como URL principal y a `https://lubricantes-ypf.onrender.com` como respaldo. Para saber si el celu está al día comparar `ultimo_dato` de `/salud` en ambas.

Sin clave configurada la lectura es abierta y la carga POST (`/api/cargar`) queda cerrada. No cargues claves en el celu salvo que quieras habilitar esa carga.

## Archivo de zips de SEPA

El cron de las 06:00 define `SEPA_ARCHIVO=$HOME/sepa-archivo` (lo deja `termux_setup.sh`, fuera del clon). `sepa.py` copia ahí el zip crudo del día como `sepa-AAAA-MM-DD.zip` (~336 MB; escribe un `.tmp` y renombra) y borra los más viejos cuando la carpeta pasa de 60 GB. Sirve para reprocesar días pasados si se suman productos al seed (SEPA publica pocos días hacia atrás). Para cambiar el tope: `SEPA_ARCHIVO_MAX_GB=<n>` en el crontab (`crontab -e`, que `termux_setup.sh` no pisa) o, para apagarlo, borrar la línea `SEPA_ARCHIVO=`. Si falla (disco lleno), se loguea y SEPA sigue igual.

## Respaldo con chip 4G

Decisión del usuario (2026-11-19), solo si cae el WiFi de casa: Ajustes > Conexiones > Wi-Fi > Avanzado > «Cambiar a datos móviles», y poner un límite de datos móviles. SEPA pesa ~336 MB por día. El túnel anda igual por 4G. No hay código para esto.

## Alternativa: instalar por ADB desde la PC

Con el celular conectado por USB y la **depuración USB** activada (Ajustes > Opciones de desarrollador), desde la PC:
```
adb devices                              # tiene que aparecer el celu (aceptá el cartel de autorización en el celular)
adb install termux.apk                   # APK +github-debug: termux-app arm64-v8a y termux-boot debug (misma firma)
adb install termux-boot.apk
adb shell am start -n com.termux/.app.TermuxActivity   # abrir Termux una vez
```
Los comandos de Termux se pueden correr desde la PC con `adb shell run-as com.termux ...`, **solo si el APK es debug** (los de GitHub lo son; los de F-Droid, no). `run-as com.termux` necesita exportar `PREFIX`, `HOME`, `PATH` y `LD_PRELOAD` de Termux. `adb shell input text` solo anda con la pantalla desbloqueada y Termux en primer plano. Los servicios (`sv`, `crond`) conviene arrancarlos desde la app Termux, no por adb. Ejemplo: `adb shell run-as com.termux files/usr/bin/bash -lc "bash ~/lub-casa/tools/termux_setup.sh estado"`. El `cloudflared tunnel login` y el token de GitHub los seguís haciendo vos en el celular.

## Cómo sé que anda

En el visor, pestaña **Fuentes**, hay una fila «Recolector de casa» con la fecha de hoy. Si la última corrida tiene más de 2 días, el visor avisa arriba:
«El recolector de casa (celular o PC) no corre desde <fecha>: SEPA y la SE no se actualizan; el resto lo cubre GitHub». Si pasa: ¿celular apagado, sin WiFi, sin batería, token vencido (`recolector_casa.log` dice `push rc=128`)?

## Avisos

- El tráfico a las tiendas sale de la IP de tu casa. El volumen es bajo (el mismo de la Action: 1 pedido por segundo por sitio, `User-Agent` honesto, `robots.txt` respetado).
- **No usar el celular para saltear bloqueos anti-bot.** Nota Paraná sigue pausada (la API devuelve datos señuelo) y Coto sigue diferido por sus términos de uso. Si una fuente nueva da 403 también desde casa, queda sin datos: no se esquiva.
- **Mercado Libre no corre en el celular, y el celular nunca guarda sus credenciales**: el token vive solo en GitHub (secrets). El script saca del entorno todo `ML_*` y excluye `ml` de la corrida.
- El clon `~/lub-casa` es solo del recolector: el script hace `git reset --hard origin/main` en cada corrida. No edites archivos ahí.

## Qué mide `/salud` en el equipo (RAM, CPU, procesos)

`equipo` suma `ram_mb` `{total, disponible}` (MemTotal/MemAvailable de `/proc/meminfo`), `cpu` `{nucleos, mhz_actual, mhz_max, total_pct, procesos_pct}` y `procesos` (hasta 8 `{nombre, cpu_pct, ram_mb}`). Todo lo que no se pueda leer es `null`, nunca un error.
- `mhz_actual`/`mhz_max`: promedio de `scaling_cur_freq`/`cpuinfo_max_freq` de los núcleos que se leen (en el Galaxy A22 se leen).
- `procesos_pct` y `cpu_pct`: CPU de los procesos propios en % de **toda** la capacidad (100 = los 8 núcleos al máximo), por delta contra la lectura anterior (entre 1 s y 10 min; si no hay, dos lecturas a 0,5 s). Un proceso nuevo cuenta 0 en su primera vuelta. Resultado cacheado 5 s.
- `procesos`: solo los de la misma uid que el server, agrupados por nombre (`server.py`, `clipper.py`, `cloudflared`, `runsv`…). Nunca rutas ni argumentos.
- **No se puede ver en Android 13** (medido en el A22 desde Termux): el CPU total del equipo (`/proc/stat` y `/proc/loadavg` dan `Permission denied`, por eso `total_pct` es `null`) y el uptime del equipo (`/proc/uptime`); Android restringe `/proc` a los procesos de la propia app desde la versión 8-10 (hidepid). En una PC Linux `total_pct` sí viene. En Windows no hay `/proc`: todo `null` y `procesos` vacío.

## Por qué red sale el equipo (`equipo.red`)

`equipo.red` = `{tipo, desde}`. `tipo`: `wifi` (la IP de salida es la de `wlan0`), `movil` (hay salida pero no por `wlan0`: el celu perdió el WiFi de casa y sigue por datos, señal de corte de luz o del router), `sin_red` (el connect UDP falla) o `null` (no se puede determinar, p. ej. Windows sin `fcntl`). `desde` = epoch del último cambio de tipo que vio el proceso (en memoria; al arrancar, el arranque). Se mide en cada `/salud` y cada `LUB_RECARGA_MIN` minutos en `vigilar`.
- Método (Android 13 le niega a Termux netlink, `ip route`, `/proc/net` y `/sys/class/net`): `ioctl SIOCGIFADDR` sobre `wlan0` y un `connect` UDP a `1.1.1.1:53` (no manda nada) para ver la IP de salida. Las IPs y los nombres de interfaz nunca salen en el JSON.
- Si los datos móviles del celu están apagados, sin WiFi da `sin_red` y el server queda offline (no hay quién lo informe).
