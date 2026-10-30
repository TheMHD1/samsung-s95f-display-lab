/*
 *  Copyright (C) 2026 Team Kodi
 *  This file is part of Kodi - https://kodi.tv
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 *  See LICENSES/README.md for more information.
 */

#version 100

precision highp float;   // LINEFIX v2: highp needed for exact row/column addressing

// LINEFIX v2 configuration (written by install_box.py from config.json):
#define LF_PANEL_W 3840.0   // GUI width in pixels (native 4K GUI)
#define LF_PANEL_H 2160.0   // GUI height in pixels
#define LF_COL_MIN 1200.0   // first panel column searched for a parameter block (C0 - Pixel Shift range - margin)
#define LF_COL_MAX 1320.0   // last panel column searched
varying vec2 v_tex;
uniform sampler2D u_samp;       // GUI FBO texture (sRGB, rendered by GUI shaders)
uniform sampler2D u_lutDegamma; // sRGB -> linear LUT (IEC 61966-2-1)
uniform sampler2D u_lutTF;      // linear -> PQ LUT (LUT_SIZE entries, sdrPeak baked in)
uniform float u_ootfGamma;      // HLG: OOTF gamma (1.2 for BT.2100 1000-nit ref)
                                // PQ: 0.0 (use LUT path instead)
uniform float u_hlgWhite;       // HLG: GUI white / 1000-nit nominal peak

// BT.709 -> BT.2020 color space conversion matrix (applied in linear light)
const mat3 bt709_to_bt2020 = mat3(
  0.6274,  0.0691,  0.0164,
  0.3293,  0.9195,  0.0880,
  0.0433,  0.0114,  0.8956
);

void main()
{
  vec4 gui = texture2D(u_samp, v_tex);

  // Skip pixels the GUI never wrote to. Blend unit would still preserve video
  // bit-exactly via DST*(1-0)+garbage*0=DST, but discard makes it structural
  // and avoids the tone-map math, BO read and BO write for those pixels.
  // LINEFIX v2: read this column's parameter block (top 4 rows of the line-fix strip, see linefix_skin.py).
  float lfCol = floor(v_tex.x * LF_PANEL_W);
  bool lfOn = false;
  float lfA = 0.0;
  vec3 lfL = vec3(0.0);
  bool lfParamPix = false;
  if (lfCol >= LF_COL_MIN && lfCol <= LF_COL_MAX)
  {
    for (int o = 0; o < 2; o++)                          // FBO row order may be flipped: try top-down and bottom-up
    {
      float s0 = (o == 0) ? 1.0 : -1.0;
      float y0 = (o == 0) ? 0.5 / LF_PANEL_H : 1.0 - 0.5 / LF_PANEL_H;
      vec4 p0 = texture2D(u_samp, vec2(v_tex.x, y0));
      vec4 p1 = texture2D(u_samp, vec2(v_tex.x, y0 + s0 * 1.0 / LF_PANEL_H));
      vec4 p2 = texture2D(u_samp, vec2(v_tex.x, y0 + s0 * 2.0 / LF_PANEL_H));
      vec4 p3 = texture2D(u_samp, vec2(v_tex.x, y0 + s0 * 3.0 / LF_PANEL_H));
      bool ok = abs(p0.r * 255.0 - 165.0) < 0.6 && abs(p1.r * 255.0 - 90.0) < 0.6 &&
                abs(p2.r * 255.0 - 60.0) < 0.6 && abs(p3.r * 255.0 - 195.0) < 0.6 &&
                p0.a > 0.998 && p1.a > 0.998 && p2.a > 0.998 && p3.a > 0.998;
      if (ok && !lfOn)
      {
        lfOn = true;
        lfA = (floor(p0.g * 255.0 + 0.5) * 256.0 + floor(p0.b * 255.0 + 0.5)) / 65535.0;
        lfL = vec3(floor(p1.g * 255.0 + 0.5) * 256.0 + floor(p1.b * 255.0 + 0.5),
                   floor(p2.g * 255.0 + 0.5) * 256.0 + floor(p2.b * 255.0 + 0.5),
                   floor(p3.g * 255.0 + 0.5) * 256.0 + floor(p3.b * 255.0 + 0.5)) / 65535.0;
        float dyRow = abs(v_tex.y - y0) * LF_PANEL_H;
        lfParamPix = dyRow < 3.5;                       // this fragment is one of the 4 parameter pixels
      }
    }
    if (u_ootfGamma > 0.0) lfOn = false;                // HLG output: no correction (calibrated for PQ only)
  }
  if (lfParamPix) gui = vec4(0.0);                      // parameter pixels are never shown
  if (gui.a == 0.0 && !lfOn)
    discard;

  // sRGB -> linear via LUT (IEC 61966-2-1 EOTF, replaces inline pow)
  vec3 linear = vec3(
    texture2D(u_lutDegamma, vec2(gui.r, 0.5)).r,
    texture2D(u_lutDegamma, vec2(gui.g, 0.5)).r,
    texture2D(u_lutDegamma, vec2(gui.b, 0.5)).r
  );

  // BT.709 -> BT.2020 gamut mapping
  linear = bt709_to_bt2020 * linear;

  vec3 result;

  if (u_ootfGamma > 0.0)
  {
    // HLG path: direct computation following libplacebo pl_color_delinearize.
    // BT.2100 reference display: 1000 nits. GUI white (linear 1.0) = u_hlgWhite
    // of that peak; 0.203 (BT.2408 reference white) maps to 75% HLG signal.
    //
    // Step 1: normalize to display-peak-relative units
    // Step 2: inverse OOTF with 12x prescale for OETF input domain
    // Step 3: HLG OETF (ARIB STD-B67) piecewise: sqrt for <=1, log for >1
    const float HLG_A = 0.17883277;
    const float HLG_B = 0.28466892;
    const float HLG_C = 0.55991073;

    vec3 scene = linear * u_hlgWhite;
    float Y = dot(scene, vec3(0.2627, 0.6780, 0.0593));
    scene *= 12.0 * pow(max(1e-6, Y), (1.0 - u_ootfGamma) / u_ootfGamma);

    // HLG OETF piecewise (threshold at scene-light 1.0)
    vec3 lo = vec3(0.5) * sqrt(max(scene, vec3(0.0)));
    vec3 hi = vec3(HLG_A) * log(max(scene - vec3(HLG_B), vec3(1e-6))) + vec3(HLG_C);
    result = mix(lo, hi, step(vec3(1.0), scene));
  }
  else
  {
    // PQ path: LUT lookup (sdrPeak baked into LUT range)
    result = vec3(
      texture2D(u_lutTF, vec2(linear.r, 0.5)).r,
      texture2D(u_lutTF, vec2(linear.g, 0.5)).r,
      texture2D(u_lutTF, vec2(linear.b, 0.5)).r
    );
  }

  // LINEFIX v2: the damage is physical, so EVERYTHING on these columns (video and GUI) is corrected:
  //   final = L + (1-a) * (g*ga + (1-ga)*video)   -> written with alpha outA = 1-(1-a)(1-ga)
  float outA = gui.a;
  if (lfOn)
  {
    outA = 1.0 - (1.0 - lfA) * (1.0 - gui.a);
    vec3 g = (gui.a > 0.0) ? result : vec3(0.0);
    result = outA > 0.0 ? clamp((lfL + (1.0 - lfA) * g * gui.a) / outA, 0.0, 1.0) : vec3(0.0);
  }

  // Limited-range encoding at the BO write boundary. Canonical normalized
  // ratios (bit-depth-agnostic in float space; BO write quantizes to the
  // active surface bit depth).
#ifdef KODI_LIMITED_RANGE
  result = result * ((235.0 - 16.0) / 255.0) + (16.0 / 255.0);
#endif

  gl_FragColor = vec4(result, outA);
}
