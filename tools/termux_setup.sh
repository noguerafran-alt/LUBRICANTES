#!/data/data/com.termux/files/usr/bin/bash
# Prepara el recolector de casa en Termux (Android): paquetes, clon dedicado, marcador, crontab y arranque tras reinicio.
# NO pide ni guarda el token de GitHub: eso lo hacés vos (ver docs/celular.md, paso del token).
# Se puede correr varias veces: no duplica nada.
set -e

REPO="${LUB_REPO:-https://github.com/noguerafran-alt/LUBRICANTES.git}"
CLON="$HOME/lub-casa"
ZONA="America/Argentina/Buenos_Aires"

pkg update -y
pkg install -y python git cronie termux-services tzdata

if [ ! -d "$CLON/.git" ]; then
  git clone "$REPO" "$CLON"
fi
touch "$CLON/.recolector_casa"   # marcador: el script hace reset --hard y solo corre en este clon

# crontab: 06:00 hora argentina todos los días (se saca la línea vieja si ya estaba)
LINEA="0 6 * * * python $CLON/tools/recolector_casa.py >> $CLON/cron.log 2>&1"
( crontab -l 2>/dev/null | grep -v -e recolector_casa -e '^CRON_TZ=' || true; echo "CRON_TZ=$ZONA"; echo "$LINEA" ) | crontab -

# arranque tras reinicio (necesita la app Termux:Boot instalada y abierta una vez)
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/recolector-casa.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
crond
EOF
chmod +x "$HOME/.termux/boot/recolector-casa.sh"

# ahora mismo
termux-wake-lock || true
pgrep crond >/dev/null || crond

echo
echo "Listo. Falta el token de GitHub (docs/celular.md, paso 5) y una prueba a mano:"
echo "  cd $CLON && python tools/recolector_casa.py --sin-push"
echo "Hora de Termux ahora: $(date)  (si no es la de Argentina no pasa nada: el cron usa CRON_TZ y el script fecha en hora argentina)"
