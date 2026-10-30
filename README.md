# Samsung S95F Display Lab

**Inside a damaged QD-OLED: controller-memory blackout mitigation, TV graphics correction, calibrated SDR/HDR shaders, and the firmware research behind future panel calibration.**

This project began with a physically damaged **77-inch Samsung S95F**: a dim vertical line and recurring panel blackouts. It grew into an investigation across the TV's root-access chain, display compositor, controller RAM, sensing logic and calibration storage—and a working correction system on a **Ugoos AM9 Pro running CoreELEC/Kodi with Arctic Fuse 3**.

We traced how faults reach the panel-stop path, deployed a bounded RAM mask that resolved the owner's recurring blackouts, made a TV-side overlay affect HDMI, measured a paired graphics/gain correction, and built a sharper native-4K player correction for SDR and HDR. We also traced real compensation-storage writes and found why several apparent success and rollback signals cannot be trusted.

**[Start here →](docs/START-HERE.md)** · [TV research handbook](docs/advanced/README.md) · [Kodi installation](docs/kodi/README.md) · [Mobile Demura / panel dossier](docs/advanced/panel/README.md)

## What we achieved

| Result | What actually happened | Evidence / guide |
| --- | --- | --- |
| **Recurring blackout mitigation** | Set skip flags for controller lanes 540–661 through guarded RAM writes; a source-aware watcher re-verifies and reapplies the mask after controller resets | Owner-confirmed outcome; [fault, bypass and recovery](docs/advanced/BLACKOUT-MITIGATION.md) |
| **TV-side graphics correction** | Root-run EFL overlay, HWC/compositor changes and paired MGA RGB gain affected the tested HDMI image; measured background preservation at grey 51 was 1.000 ± 0.2% | Camera-measured; [graphics and gain research](docs/advanced/GRAPHICS-AND-GPU.md) |
| **Native-4K Kodi correction** | Per-column/per-colour strips, Arctic skin integration, separate chroma profiles and a raw-PQ HDR GUI-composite shader | Working code and camera results; [installation and results](docs/kodi/README.md) |
| **Root-access compatibility work** | The SDK archive-root path worked on the retained S95F setup; the actual runtime-discovery delta is published | Target-observed; [root chain and patch](docs/advanced/ROOT-ACCESS.md) |
| **Controller and firmware reconstruction** | USB protocol, RAM aliases, sensing-table writers, fault producers, compensation save/load descriptors and hardware-LUT transfer paths | Static traces and host models; [controller](docs/advanced/CONTROLLER-COMMUNICATIONS.md) / [firmware](docs/advanced/panel/FIRMWARE-AND-COMPENSATION.md) |
| **Mobile Demura / panel-flashing research** | Identified the TV service app and TCON flash chain; later source models exposed false-success and both-slot-overwrite cases in stock storage routines | Research only; [consolidated dossier](docs/advanced/panel/README.md) |

The distinction matters: the blackout fix writes **controller RAM**; the TV line correction uses **graphics composition plus display gain**; the Kodi HDR correction modifies a **player shader**. A direct TV GPU-memory/video-injection loop has not been demonstrated. This is substantial reverse engineering of selected display paths, rather than a claim to have decoded the entire television.

## See the correction results

These are measured damaged-column / neighbouring-column luminance ratios on the original set. **1.00 means equal measured luminance**, not a guarantee that every artifact is invisible.

| Test | Before | After |
| --- | --- | --- |
| SDR grey 51/255, core columns | About 0.12–0.45 across RGB | 0.98–1.09 |
| HDR10 2-nit target, core columns | About 0.02 | 0.92–1.18 |
| HDR10 0.5-nit target | Severe near-black loss | 0.53–0.86; correction remains limited |

The SDR result used a coupled dimming/TV-gain configuration. The default Kodi installer uses a different B=0 variant that was not separately camera-verified in SDR. HDR figures refer to the tested player path; TV-overlay performance is limited by a 1080p canvas scaled to 4K. See [all measurements and limits](docs/kodi/RESULTS-AND-LIMITS.md) before reusing the numbers.

## Choose a path

- **Reproduce the player correction:** follow the [Kodi guide](docs/kodi/README.md). It covers finding columns, installing the layer/relay/shader, RAW-camera calibration, profiles and removal. Ordinary installation needs no TV root.
- **Understand or continue the TV work:** read [the research handbook](docs/advanced/README.md), starting with the blackout and graphics chapters. The TV tools are model- and firmware-specific research, with an experimental EFL client and the root compatibility patch published separately.
- **Prepare for native panel calibration:** read [Mobile Demura and panel flashing](docs/advanced/panel/README.md), then the [future research plan](docs/advanced/panel/FUTURE-PANEL-CALIBRATION.md). Exact known formats, failed assumptions and missing evidence are preserved. No qualified calibration writer or restore procedure exists yet.

## Project map

| Area | Contents |
| --- | --- |
| [docs/START-HERE.md](docs/START-HERE.md) | Guided reading and workflow choices |
| [TV research](docs/advanced/README.md) | Root, blackout mitigation, controller communications, graphics, evidence and chronology |
| [Panel research](docs/advanced/panel/README.md) | Mobile service app, flash chains, compensation storage, backup failures and future work |
| [Kodi guide](docs/kodi/README.md) | Installation, calibration, SDR/HDR method and operational lessons |
| [code/](code/) | Configurable installer, skin/strip generator, relay, shader patch, keeper and camera tools |
| [research/](research/README.md) | Offline format inspectors/tests, experimental TV overlay and archive-root patch |

## Scope and reproducibility

The physical panel remains damaged. The mask reduces diagnostic coverage in one sensing-consistency path; it does not certify electrical safety. Shared compensation RAM can reach persistent storage through stock firmware, and neither a reboot nor an app `ok` is a verified undo/success mechanism. Read [SAFETY.md](SAFETY.md) before device work.

The handbook separates camera measurements, target observations, source facts, host models and hypotheses. Source hashes preserve provenance. Credentials, private device identities, OEM binaries/keys and unique calibration dumps stay outside the repository. The public package provides code where generalized, tested components exist and documents the remaining owner-specific deployment dependencies.

Offline tools can be checked without a TV:

```sh
python3 -m unittest discover -s research/tests -v
python3 research/inspect_formats.py layout comp2 0
```

## License

MIT ([LICENSE](LICENSE)), except `code/box/shaders/*`, derived from Kodi and licensed GPL-2.0-or-later. Independent owner-device research; not affiliated with Samsung, Kodi or CoreELEC.
