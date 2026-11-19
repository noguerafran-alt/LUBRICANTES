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
3. En Termux, **bajar y correr el instalador** (instala python, git, cronie, termux-services y tzdata, clona el repo en `~/lub-casa`, crea el marcador `.recolector_casa`, deja el cron a las 06:00 hora argentina y el script de arranque en `~/.termux/boot/`):
   ```
   pkg install -y git
   git clone https://github.com/noguerafran-alt/LUBRICANTES.git ~/lub-casa
   bash ~/lub-casa/tools/termux_setup.sh
   ```
   Si el repo es privado, el `git clone` pide usuario y contraseña: hacé primero el paso 5 (crear el token) y usalo como contraseña.
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
8. **Reiniciar el celular una vez** para confirmar que Termux:Boot levanta `crond` y los servicios solos (`bash ~/lub-casa/tools/termux_setup.sh estado`).

## Servidor y túnel (el celu también sirve la página)

El mismo celular corre `python server.py` (servicio `lub-server`, solo en `127.0.0.1:8090`) y `cloudflared` (servicio `lub-tunel`) lo publica en **https://lubricantes.fln-data-analysis.com**. Render queda de respaldo. El instalador (`tools/termux_setup.sh`) ya instala `cloudflared`, crea los dos servicios y el cron del pull horario (minuto 20). Lo que falta lo hacés vos, una vez:

1. **Login de Cloudflare** (recomendado). En Termux:
   ```
   cloudflared tunnel login
   ```
   Imprime un link: abrilo en el navegador del celular, entrá a tu cuenta de Cloudflare y autorizá el dominio `fln-data-analysis.com`. Queda `~/.cloudflared/cert.pem`.
2. **Crear el túnel y la ruta DNS**:
   ```
   cloudflared tunnel create lubricantes
   cloudflared tunnel route dns lubricantes lubricantes.fln-data-analysis.com
   ```
3. Dentro de unos segundos `lub-tunel` arranca solo (el servicio reintenta cada 5 minutos si todavía no había credenciales; para apurarlo: `sv restart lub-tunel`).
4. **Probar**: `bash ~/lub-casa/tools/termux_setup.sh estado` y, desde cualquier lado, `https://lubricantes.fln-data-analysis.com/salud`. Devuelve `{"ok": true, "commit": "...", "ultimo_dato": "AAAA-MM-DD"}`: el commit de datos que se sirve y la fecha de la última observación. Si `ultimo_dato` queda viejo, mirá `~/lub-casa/pull.log`.
5. Si el proxy de YPF marca el dominio como «sin categoría», pedir que lo categoricen, igual que se hizo con A4D.

**Variante con token** (si preferís no hacer el login en el celular): en el panel de Cloudflare (Zero Trust > Networks > Tunnels) creá un túnel, apuntá el hostname `lubricantes.fln-data-analysis.com` a `http://127.0.0.1:8090` y guardá el token en `~/.lub-tunel-token` (`chmod 600`). El servicio lo lee de ahí; el instalador nunca lo pide ni lo guarda. **Nunca pegues el token en un chat ni en el repo.**

**Qué hace cada cosa**: el server recarga los datos solo (cada 5 minutos mira si cambió el commit del clon; no hace falta reiniciarlo). El pull horario trae lo que sube GitHub (Mercado Libre a las 10:00) y la PC. Un cambio de **código** (no de datos) requiere `sv restart lub-server`. Logs en `~/lub-casa/logs/` (`server.log`, `tunel.log`, `pull-cron.log`).

**Cloudera**: apuntarlo a `https://lubricantes.fln-data-analysis.com` como URL principal y a `https://lubricantes-ypf.onrender.com` como respaldo. Para saber si el celu está al día comparar `ultimo_dato` de `/salud` en ambas.

Sin clave configurada la lectura es abierta y la carga POST (`/api/cargar`) queda cerrada. No cargues claves en el celu salvo que quieras habilitar esa carga.

## Alternativa: instalar por ADB desde la PC

Con el celular conectado por USB y la **depuración USB** activada (Ajustes > Opciones de desarrollador), desde la PC:
```
adb devices                              # tiene que aparecer el celu (aceptá el cartel de autorización en el celular)
adb install termux.apk                   # los APK de F-Droid o de GitHub (termux-app, termux-boot)
adb install termux-boot.apk
adb shell am start -n com.termux/.app.TermuxActivity   # abrir Termux una vez
```
Los comandos de Termux se pueden correr desde la PC con `adb shell run-as com.termux ...`, **solo si el APK es debug** (los de GitHub lo son; los de F-Droid, no). Ejemplo: `adb shell run-as com.termux files/usr/bin/bash -lc "bash ~/lub-casa/tools/termux_setup.sh estado"`. El `cloudflared tunnel login` y el token de GitHub los seguís haciendo vos en el celular.

## Cómo sé que anda

En el visor, pestaña **Fuentes**, hay una fila «Recolector de casa» con la fecha de hoy. Si la última corrida tiene más de 2 días, el visor avisa arriba:
«El recolector de casa (celular o PC) no corre desde <fecha>: SEPA y la SE no se actualizan; el resto lo cubre GitHub». Si pasa: ¿celular apagado, sin WiFi, sin batería, token vencido (`recolector_casa.log` dice `push rc=128`)?

## Avisos

- El tráfico a las tiendas sale de la IP de tu casa. El volumen es bajo (el mismo de la Action: 1 pedido por segundo por sitio, `User-Agent` honesto, `robots.txt` respetado).
- **No usar el celular para saltear bloqueos anti-bot.** Nota Paraná sigue pausada (la API devuelve datos señuelo) y Coto sigue diferido por sus términos de uso. Si una fuente nueva da 403 también desde casa, queda sin datos: no se esquiva.
- **Mercado Libre no corre en el celular, y el celular nunca guarda sus credenciales**: el token vive solo en GitHub (secrets). El script saca del entorno todo `ML_*` y excluye `ml` de la corrida.
- El clon `~/lub-casa` es solo del recolector: el script hace `git reset --hard origin/main` en cada corrida. No edites archivos ahí.
