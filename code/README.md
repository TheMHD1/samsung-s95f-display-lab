# Kodi correction implementation

Part of [Samsung S95F Display Lab](../README.md). Follow the [installation and calibration guide](../docs/kodi/README.md) before running the tools. Run its commands from this directory. The ordinary installer operates on the player; it does not root the TV or write panel calibration.

| Component | Responsibility |
| --- | --- |
| `config.example.json`, `lfconfig.py` | Target/profile configuration; copy the example to private `config.json` |
| `install_box.py` | Player relay and guarded HDR shader override installation/removal |
| `linefix_skin.py` | Native-4K skin dialog, strips and profile installation; Arctic Fuse 3 was tested |
| `keeper.py` | Checks/reinstalls player-side state after updates or HDMI incidents |
| `box/` | Relay, systemd units, shader mount and Kodi-derived GLSL source/patch |
| `calib/` | Ruler/marker clips, SDR/chroma/HDR fitting and final verification |
| `camera/` | Tethered camera capture and RAW CFA measurements |
| `examples/` | Original S95F measurements/profiles and a starter profile; calibrate your own target |

The B=60 SDR reference assumes a paired TV-side gain; it is not the default installer configuration. The B=0 starter avoids that deployment dependency. See [method](../docs/kodi/METHOD.md), [measured limits](../docs/kodi/RESULTS-AND-LIMITS.md) and [reliability](../docs/kodi/RELIABILITY.md).

Experimental TV access/compositor work lives under [research/](../research/README.md) and the [TV handbook](../docs/advanced/README.md), with separate dependencies and restoration requirements.
