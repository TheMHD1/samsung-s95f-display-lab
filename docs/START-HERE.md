# Start here

[Samsung S95F Display Lab](../README.md) has three connected tracks. Choose the outcome you need; a working Kodi installation does not require TV root, controller-memory changes or panel flashing.

| Your goal | Start with | Then read |
| --- | --- | --- |
| Correct a damaged column line through Kodi | [Kodi installation and calibration](kodi/README.md) | [Layer](kodi/KODI-LAYER.md), [HDR shader](kodi/HDR-SHADER.md), [reliability](kodi/RELIABILITY.md) |
| Understand the blackout/crash bypass | [Blackout mitigation](advanced/BLACKOUT-MITIGATION.md) | [Controller protocol](advanced/CONTROLLER-COMMUNICATIONS.md), [root access](advanced/ROOT-ACCESS.md) |
| Understand TV-side graphics/gain correction | [Graphics and GPU](advanced/GRAPHICS-AND-GPU.md) | [Experimental EFL source](../research/tv-overlay/README.md), [results](kodi/RESULTS-AND-LIMITS.md) |
| Continue Mobile Demura or panel flashing | [Consolidated panel dossier](advanced/panel/README.md) | [Firmware/storage](advanced/panel/FIRMWARE-AND-COMPENSATION.md), [future programme](advanced/panel/FUTURE-PANEL-CALIBRATION.md) |
| Audit the evidence before building on it | [Evidence and chronology](advanced/EVIDENCE-AND-CHRONOLOGY.md) | [Source manifest](../research/panel/sources.json), [offline tools](../research/README.md) |

## Player correction workflow

Read [safety](../SAFETY.md) and the [measured limits](kodi/RESULTS-AND-LIMITS.md). Back up the player configuration, identify exact output columns, install the native-4K skin layer and relay, calibrate against RAW-camera measurements, then enable and verify the matching HDR shader. Use the final output path, chroma mode and Pixel Shift behavior during calibration. The [complete guide](kodi/README.md) contains the commands and removal steps; examples from the original S95F are starting references, not universal profiles.

## TV/controller research workflow

Read the [handbook](advanced/README.md) and identify firmware, architecture, address domain and evidence level before interpreting an address. The [root chapter](advanced/ROOT-ACCESS.md) explains access; [controller communications](advanced/CONTROLLER-COMMUNICATIONS.md) explains transaction ownership. The blackout watcher, keeper and manual tools share one access/transport coordination contract. Public documentation records the original deployment and its limitations; it is not a generic automatic TV bypass installer.

## Panel research workflow

Start offline with the [Mobile Demura dossier](advanced/panel/README.md) and source hashes. Keep the TV app transport, external-controller storage and internal-SoC demura routes separate. Recover coefficient meanings, qualified acquisition and an independently verified restore before designing a writer. The [future plan](advanced/panel/FUTURE-PANEL-CALIBRATION.md) lists the missing producer/consumer and recovery evidence. No panel-calibration flash was attempted in this project.

## Where the implementations live

- `code/`: working Kodi installer, skin generator, profiles, relay, shader, keeper and camera scripts. Start with `config.example.json`; do not commit your private config.
- `research/`: offline format/layout/checksum tools, experimental TV overlay source, root-access compatibility patch and source provenance.
- `docs/`: workflows and technical evidence. This is the reading layer; it contains no device credentials or unique calibration backups.
