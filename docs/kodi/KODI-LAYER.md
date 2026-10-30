# The Kodi correction layer

Code: `code/linefix_skin.py` (generator + installer), `code/box/relay.py` (switching, enforcement, self-heal).

## 1. Native 4K GUI: one GUI pixel = one panel column

By default CoreELEC renders Kodi's GUI at 1920x1080 and scales it up; a 1-pixel strip would then cover 2-3 panel
columns. Setting `coreelec.amlogic.disableguiscaling = true` (set by `install_box.py` through JSON-RPC
`Settings.SetSettingValue`; it applies live) makes the GUI 3840x2160. Camera check: a 1-pixel line drawn by Kodi
lands on exactly one panel column. (For comparison, the TV's own graphics layer is 1920x1080 upscaled with a fixed
blur and smeared a 1-pixel strip over ~2.5 columns - see TV-SIDE-CONCEPTS.md.)

Requirements that follow:
- the HDMI output must be 2160p (the relay draws nothing for any other mode);
- the TV must not overscan or scale ("fit to screen"); sharpness 0 helps (edge enhancement creates halos);
- video itself is placed 1:1 at 2160p, so the GUI layer and the video line up.
Reported risk: 4K GUI has caused dropped frames or GUI corruption on some kernels; on our box it froze twice while we
also forced 2160p30 RGB output for testing. With automatic colour settings it was stable.

## 2. The skin dialog

`Custom_<id>_LineFix.xml` in the skin's XML folder (`1080i` for Arctic Fuse 3), a dialog window that:
- is visible while the Home window property `linefix_on` is non-empty (Kodi opens/closes dialogs by their
  `<visible>` condition), `zorder` 99 so it sits above menus, OSD and subtitles;
- has **no focusable controls**, so it never takes remote input (navigation verified unaffected);
- contains one group with: optional dim rectangles left/right of the line (only if B > 0, hidden while
  `linefix_hdr` is set) and one image over columns C0..C1 whose texture is `$INFO[Window(Home).Property(linefix_strip)]`.
Skin coordinates are 1920x1080 units, so a panel column is 0.5 units (`left = C0/2`, `width = (C1-C0+1)/2`).

Pitfalls:
- `colordiffuse="00000000"` means "no tint" to Kodi, i.e. a **white** full-screen image. With B = 0 the generator
  emits no dim rectangles at all.
- A changed skin XML is **not used until `ReloadSkin()`**. A stale in-memory XML silently invalidated a series of HDR
  measurements once; the installer compares md5 and reloads only when needed.
- A skin update deletes the custom file; the keeper re-installs it.

## 3. Strip textures

Small RGBA PNGs, stretched to full height by the skin:
- **SDR**: (C1-C0+1) x 4 pixels. Per column alpha `a` and colour `rgb = lift * 255 / a` (PNG stores straight colour;
  Kodi blends it as `out = lift + (1 - a/255) * below`). Lift is premultiplied and must be <= alpha. Columns without a
  profile entry get alpha B (= same dim as the rest of the screen).
- **HDR**: (C1-C0+1) x 2160, transparent except a 4-pixel parameter block at the top of each column (HDR-SHADER.md).
  Shown by mistake without the shader it is 4 tiny dots per column at the top edge.
Strips are uploaded as `strip-<md5>.png`; the profile table `/storage/linefix/profiles.json` maps profile name -> file.

## 4. Profiles and automatic switching (relay)

| profile | when | why |
|---|---|---|
| `444` | SDR, 2160p at <= 30 Hz | the box outputs YCbCr 4:4:4 |
| `422` | SDR, 2160p at 50/60 Hz | 4:2:2 output: colour lifts slightly different (METHOD.md section 3) |
| `hdr` | HDR10 / HDR10+ output, patched shader active | PQ-domain parameters; `linefix_hdr=1` hides dim rectangles |
| none | Dolby Vision, HLG, unknown HDR, non-2160p, or shader missing | no strip (no correction, no harm) |

The relay polls `/sys/class/display/mode` and Kodi's `VideoPlayer.HdrType` every 0.2-0.5 s. The box knows its output
format immediately (TVs report HDR several seconds late), and the switch happens during the TV's HDMI re-sync blank,
so it is invisible. Order of property changes is chosen so a transition is never brighter or darker than either end
state (dim off before an HDR strip appears; strip before dim comes back).

## 5. Pixel Shift following

OLED TVs move the whole picture by a few pixels every 30-60 s (Pixel Shift / orbit) to reduce burn-in. On the S95F
we saw horizontal shifts of about -1..+16 panel columns (1-pixel steps) and vertical shifts that do not matter for
a vertical line. The damaged columns are physical, so with a shift `x` the correction must be drawn at image column
`P + x` (our TV moves the picture LEFT by x; check the sign on yours with a strip and the camera).

The layer supports this without redrawing anything: the skin group carries 60 conditional slide animations with
`time="0"`, one per x in -30..30 (`end = x/2` skin units), selected by the Home property `linefix_x`. Setting the
property moves the layer on the next frame. The relay sets it from `GET /x?v=<x>` and re-asserts it every 0.5 s.

Where `x` comes from: on our TV the current shift was readable only from inside the TV (a helper with device access,
documented in the [TV graphics chapter](../advanced/GRAPHICS-AND-GPU.md)). Measured: following ON 1.02-1.09 vs following OFF 0.43-0.59 at x = 6. **Without a source for x, turn
Pixel Shift OFF** in the TV menu (panel care settings) - with Pixel Shift on and no following, the correction lands
beside the line most of the time. Trade-off: Pixel Shift off slightly raises burn-in risk for static content.

## 6. Properties (Home window) used

| property | set by | meaning |
|---|---|---|
| `linefix_on` | keeper / you (`/storage/linefix/on` flag), enforced by relay | layer visible |
| `linefix_strip` | relay | path of the active strip texture |
| `linefix_hdr` | relay | `1` = HDR mode (dim rectangles hidden) |
| `linefix_x` | relay (`/x`) | Pixel Shift x in panel columns |

## 7. What it covers

Everything Kodi plays or shows on the box: video files, Jellyfin/Plex/YouTube add-ons, menus, subtitles (the layer is
on top, so menus over the line are corrected as well). Not covered: TV apps, other HDMI sources, Dolby Vision
(see IDEAS.md), HLG. A practical tip: play streaming services through Kodi add-ons where possible.
