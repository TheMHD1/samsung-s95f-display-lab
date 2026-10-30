#!/bin/sh
# OLED line fix: mount a copy of Kodi's shader tree in which the GUI composite shader also applies the per-column
# HDR correction (see docs/HDR-SHADER.md). Runs once at boot, before Kodi (linefix-shaders.service).
#
# Safety:
# - Nothing in the read-only system image is changed: a copy of the stock tree is bind-mounted over the original.
#   Undo = `umount /usr/share/kodi/system/shaders` (or disable the unit + restart Kodi). A reboot without the unit
#   gives you the stock shaders back.
# - md5 guard: the patched file was made from ONE exact stock gles_gui_composite.frag (its md5 is stored in
#   shader-orig.md5 by install_box.py). If a CoreELEC/Kodi update changes the stock shader, nothing is mounted
#   -> HDR correction inactive, GUI completely stock. Re-run install_box.py to re-patch against the new version.
STOCK=/usr/share/kodi/system/shaders
D=/storage/linefix
OV=$D/shaders
ST=$D/shader-mount.status
ORIG_MD5=$(cat $D/shader-orig.md5 2>/dev/null)

mountpoint -q $STOCK && { echo "already mounted $(date)" > $ST; exit 0; }
[ -f $D/gles_gui_composite.linefix.frag ] || { echo "NOT mounted: patched shader missing $(date)" > $ST; exit 0; }
cur=$(md5sum $STOCK/GLES/2.0/gles_gui_composite.frag | cut -d' ' -f1)
if [ -z "$ORIG_MD5" ] || [ "$cur" != "$ORIG_MD5" ]; then
  echo "NOT mounted: stock shader changed ($cur, patched against ${ORIG_MD5:-unknown}) $(date)" > $ST; exit 0
fi
rm -rf $OV.new && cp -a $STOCK $OV.new \
  && cp $D/gles_gui_composite.linefix.frag $OV.new/GLES/2.0/gles_gui_composite.frag \
  && rm -rf $OV && mv $OV.new $OV && mount --bind $OV $STOCK \
  && echo "mounted $(date)" > $ST || echo "FAILED $(date)" > $ST
