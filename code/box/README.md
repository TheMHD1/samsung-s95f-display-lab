# Player runtime

Installed by [`install_box.py`](../install_box.py), following the [Kodi guide](../../docs/kodi/README.md). These files run on the CoreELEC player, not the TV.

| Component | Role |
| --- | --- |
| `relay.py`, `linefix-relay.service` | Select SDR/chroma/HDR profiles and reconcile the layer after output-mode changes |
| `shader-mount.sh`, `linefix-shaders.service` | Mount the HDR shader override only when the original shader matches the expected digest |
| `shaders/` | Kodi-derived shader source and patch, GPL-2.0-or-later |

The relay has an explicit idle player-reboot policy after certain HDMI replug failures. See [reliability](../../docs/kodi/RELIABILITY.md) for that behavior and controls; an active service alone does not prove correct HDR output. [Shader internals](../../docs/kodi/HDR-SHADER.md) explain the PQ-domain correction and version guard.
