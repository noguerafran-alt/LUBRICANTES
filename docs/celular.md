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
8. **Reiniciar el celular una vez** para confirmar que Termux:Boot levanta `crond` solo (`pgrep crond` tiene que devolver un número).

## Cómo sé que anda

En el visor, pestaña **Fuentes**, hay una fila «Recolector de casa» con la fecha de hoy. Si la última corrida tiene más de 2 días, el visor avisa arriba:
«El recolector de casa (celular o PC) no corre desde <fecha>: SEPA y la SE no se actualizan; el resto lo cubre GitHub». Si pasa: ¿celular apagado, sin WiFi, sin batería, token vencido (`recolector_casa.log` dice `push rc=128`)?

## Avisos

- El tráfico a las tiendas sale de la IP de tu casa. El volumen es bajo (el mismo de la Action: 1 pedido por segundo por sitio, `User-Agent` honesto, `robots.txt` respetado).
- **No usar el celular para saltear bloqueos anti-bot.** Nota Paraná sigue pausada (la API devuelve datos señuelo) y Coto sigue diferido por sus términos de uso. Si una fuente nueva da 403 también desde casa, queda sin datos: no se esquiva.
- **Mercado Libre no corre en el celular, y el celular nunca guarda sus credenciales**: el token vive solo en GitHub (secrets). El script saca del entorno todo `ML_*` y excluye `ml` de la corrida.
- El clon `~/lub-casa` es solo del recolector: el script hace `git reset --hard origin/main` en cada corrida. No edites archivos ahí.
