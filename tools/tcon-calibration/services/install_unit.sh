#!/bin/bash
# Install one of the kit's systemd --user units with the placeholders filled from config.py (no TV contact).
# usage: services/install_unit.sh s0-nightly|s95f-rt|s95f-bake11-guard   (does NOT enable or start it)
set -euo pipefail
K=$(cd "$(dirname "$0")/.." && pwd)
case "${1:-}" in
  s0-nightly) SRC=$K/services/s0-nightly/s0-nightly.service ;;
  s95f-rt) SRC=$K/services/s95f-rt/s95f-rt.service ;;
  s95f-bake11-guard) SRC=$K/services/bake11-guard/s95f-bake11-guard.service ;;
  *) echo "usage: $0 s0-nightly|s95f-rt|s95f-bake11-guard"; exit 2 ;;
esac
CFG=$(python3 -B "$K/config.py" get config_file)
python3 -B "$K/config.py" show > /dev/null
S0=$(python3 -B "$K/config.py" get s0svc); RT=$(python3 -B "$K/config.py" get rtsvc)
B11=$(python3 -B "$K/config.py" get bake11); WD=$(python3 -B "$K/config.py" get watcher_dir)
mkdir -p ~/.config/systemd/user
sed -e "s|@KIT@|$K|g" -e "s|@CONFIG@|$CFG|g" -e "s|@S0SVC@|$S0|g" -e "s|@RTSVC@|$RT|g" -e "s|@BAKE11@|$B11|g" -e "s|@WATCHER@|$WD|g" \
  "$SRC" > ~/.config/systemd/user/"$1".service
systemctl --user daemon-reload
echo "installed ~/.config/systemd/user/$1.service (not enabled; enable with: systemctl --user enable --now $1)"
