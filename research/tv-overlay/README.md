# Experimental TV EFL overlay source

This is the adapted source of the TV-side **ordinary Wayland/EFL client** used during the S95F research. It is not GPU-memory injection. It does not obtain root, change HWC, write MGA/controller registers, flash a panel or install a service.

The tested environment was Tizen ARM32 native EFL with a compatible .NET 6 runtime. The P/Invoke declarations name platform libraries; compiling successfully on a PC does not validate another TV's ABI. The effective canvas on the measured TV was 1920×1080, even with a 4K panel.

Build locally with the .NET 6 SDK:

```sh
dotnet build research/tv-overlay/GapOverlay.csproj -c Release
```

After independently establishing a compatible authorized TV session/environment, stage the managed build to a private temporary directory. Run `dotnet GapOverlay.dll <run-directory> 1920 1080` **on that TV**, not on a normal desktop without the native libraries. `<run-directory>/params` controls the client. `params.example` is disabled and uses neutral whole-screen alpha by default. The adapted default lifetime is 60 seconds; an explicit `lifetime 0` opts into an indefinite session. A `stop` file requests exit. Check `status`, then verify that the surface really disappeared.

Supported parameter lines include `enabled`, `alpha`, `px x r g b a`, `pxodd x r g b a`, `follow`, `marker`, `split` and `lifetime`. Colour values are premultiplied and clamped to alpha. Optional `notify URL` sends only parsed shift x to a relay; leave it absent unless the private destination is deliberately configured. No destination is embedded in this source.

Pixel Shift following reads matching kernel-log records where accessible; it does not grant access to those logs. Missing records are not proof that the shift is zero. An enabled layer or a zero/invalid profile is not proof of correction. Measure canvas orientation, offset, source/HDR mode and shift behaviour on the target. This is experimental source, not the generalized Kodi installer's TV backend. Pairing an overlay with global gain requires the coupled state/calibration work described in [GRAPHICS-AND-GPU](../../docs/advanced/GRAPHICS-AND-GPU.md).
