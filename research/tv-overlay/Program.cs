// GapOverlay — full-screen semi-transparent black layer with a per-column "gap" over the damaged line.
// Paired with an MGA gain of 1/(1-a) the rest of the picture is unchanged and the gap columns are boosted.
// Experimental S95F example (Tizen, ARM32); ordinary EFL composition, not GPU-memory injection.
// SPDX-License-Identifier: MIT
//
// Usage: dotnet GapOverlay.dll <dir> [canvasW canvasH]
//   <dir>/params : text, re-read when it changes. Lines:
//       alpha <0-255>              base layer alpha (black, premultiplied)
//       gap <x> <a0> <a1> ...      canvas x of first gap pixel, then one alpha per gap pixel (0 = fully open)
//       enabled <0|1>              0 = draw nothing (transparent)
//       marker <0|1>               1 = also draw a small grey test square in the centre
//       lifetime <seconds>         exit after this many seconds (0 = no limit)
//   <dir>/stop   : exit when it exists.   <dir>/status : written each param apply.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

namespace GapOverlay {
[StructLayout(LayoutKind.Sequential, Pack = 4)] struct Rect { public int X, Y, W, H; }
static class LibC {
  [DllImport("libc.so.6", SetLastError = true)] public static extern int open([MarshalAs(UnmanagedType.LPUTF8Str)] string path, int flags);
  [DllImport("libc.so.6", SetLastError = true)] public static extern int read(int fd, byte[] buf, int count);
  [DllImport("libc.so.6", SetLastError = true)] public static extern long lseek(int fd, long off, int whence);
  [DllImport("libc.so.6", SetLastError = true)] public static extern int close(int fd);
}
/// Follows the TV's Pixel Shift instantly: blocks on /dev/kmsg and reacts to "[S_F]BLACK PIXELSHIFT [on:N](x,y)".
static class ShiftFollower {
  public static volatile int X = 0; public static volatile int Seq = 0; public static string Notify = ""; public static volatile bool Known = false;
  static readonly System.Text.RegularExpressions.Regex Rx = new(@"BLACK PIXELSHIFT \[on:(\d)\]\((-?\d+),(-?\d+)\)");
  static readonly System.Net.Http.HttpClient Http = new() { Timeout = TimeSpan.FromMilliseconds(1500) };
  static bool Parse(string rec) {
    var m = Rx.Match(rec); if (!m.Success) return false;
    int x = m.Groups[1].Value == "1" ? int.Parse(m.Groups[2].Value) : 0;
    bool first = !Known; Known = true;
    if (x != X || first) { X = x; Seq++; Send(); }
    return true;
  }
  public static void Send() {
    var url = Notify; if (string.IsNullOrEmpty(url) || !Known) return;   // never announce x before a real record
    int x = X;
    System.Threading.Tasks.Task.Run(async () => { try { await Http.GetAsync($"{url}?v={x}"); } catch { } });
  }
  public static void Start() {
    new Thread(() => {
      var buf = new byte[8192];
      // 1) history: last known position (non-blocking drain)
      int fd = LibC.open("/dev/kmsg", 0x800);                      // O_RDONLY|O_NONBLOCK
      if (fd >= 0) { while (true) { int n = LibC.read(fd, buf, buf.Length); if (n > 0) Parse(System.Text.Encoding.UTF8.GetString(buf, 0, n));
                                    else if (n < 0 && Marshal.GetLastWin32Error() == 32) continue; else break; } LibC.close(fd); }
      Send();
      // 2) live: blocking reads from the end
      while (true) {
        fd = LibC.open("/dev/kmsg", 0);
        if (fd < 0) { Thread.Sleep(2000); continue; }
        LibC.lseek(fd, 0, 2);                                       // SEEK_END
        while (true) {
          int n = LibC.read(fd, buf, buf.Length);
          if (n > 0) { Parse(System.Text.Encoding.UTF8.GetString(buf, 0, n)); continue; }
          if (n < 0 && Marshal.GetLastWin32Error() == 32) continue;   // EPIPE: records overwritten, keep going
          break;
        }
        LibC.close(fd); Thread.Sleep(500);
      }
    }) { IsBackground = true, Name = "kmsg-shift" }.Start();
    new Thread(() => { while (true) { Thread.Sleep(20000); Send(); } }) { IsBackground = true }.Start();   // periodic re-assert
  }
}
static class N {
  const string EE = "libecore_evas.so.1", EV = "libevas.so.1", EC = "libecore.so.1";
  [DllImport(EE)] public static extern int ecore_evas_init();
  [DllImport(EE)] public static extern int ecore_evas_shutdown();
  [DllImport(EE)] public static extern IntPtr ecore_evas_new([MarshalAs(UnmanagedType.LPUTF8Str)] string engine, int x, int y, int w, int h, IntPtr extra);
  [DllImport(EE)] public static extern IntPtr ecore_evas_get(IntPtr w);
  [DllImport(EE)] public static extern void ecore_evas_alpha_set(IntPtr w, int a);
  [DllImport(EE)] public static extern void ecore_evas_focus_skip_set(IntPtr w, int s);
  [DllImport(EE)] public static extern void ecore_evas_input_rect_set(IntPtr w, ref Rect r);
  [DllImport(EE)] public static extern void ecore_evas_layer_set(IntPtr w, int l);
  [DllImport(EE)] public static extern void ecore_evas_show(IntPtr w);
  [DllImport(EE)] public static extern void ecore_evas_free(IntPtr w);
  [DllImport(EE)] public static extern void ecore_evas_geometry_get(IntPtr w, out int x, out int y, out int wd, out int ht);
  [DllImport(EV)] public static extern IntPtr evas_object_rectangle_add(IntPtr c);
  [DllImport(EV)] public static extern void evas_object_move(IntPtr o, int x, int y);
  [DllImport(EV)] public static extern void evas_object_resize(IntPtr o, int w, int h);
  [DllImport(EV)] public static extern void evas_object_color_set(IntPtr o, int r, int g, int b, int a);
  [DllImport(EV)] public static extern void evas_object_show(IntPtr o);
  [DllImport(EV)] public static extern void evas_object_hide(IntPtr o);
  [DllImport(EV)] public static extern void evas_object_del(IntPtr o);
  [DllImport(EC)] public static extern int ecore_main_loop_iterate_may_block(int b);
}
sealed class Params {
  public int Alpha = 0, GapX = 0, Blue = 0, Tile = 0; public bool Follow = false; public string Notify = ""; public List<int> Gap = new(); public SortedDictionary<int, int[]> Px = new(), PxOdd = new(); public int Split = 100; public bool Enabled = false, Marker = false; public int Lifetime = 60;
  public Params WithPx(SortedDictionary<int, int[]> px) { var q = (Params)MemberwiseClone(); q.Px = px; return q; }
  public static Params Parse(string text) {
    var p = new Params();
    foreach (var raw in text.Split('\n')) {
      var t = raw.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries);
      if (t.Length == 0 || t[0].StartsWith("#")) continue;
      int I(int i) => int.Parse(t[i], CultureInfo.InvariantCulture);
      switch (t[0]) {
        case "alpha": p.Alpha = Math.Clamp(I(1), 0, 255); break;
        case "gap": p.GapX = I(1); for (int i = 2; i < t.Length; i++) p.Gap.Add(Math.Clamp(I(i), 0, 255)); break;
        case "enabled": p.Enabled = I(1) != 0; break;
        case "marker": p.Marker = I(1) != 0; break;
        case "blue": p.Blue = Math.Clamp(I(1), 0, 255); break;
        case "tile": p.Tile = Math.Max(0, I(1)); break;
        case "follow": p.Follow = I(1) != 0; break;
        case "notify": p.Notify = t.Length > 1 ? t[1] : ""; break;
        case "px": { int a = Math.Clamp(I(5), 0, 255); p.Px[I(1)] = new[] { Math.Clamp(I(2), 0, a), Math.Clamp(I(3), 0, a), Math.Clamp(I(4), 0, a), a }; break; }
        case "pxodd": { int a = Math.Clamp(I(5), 0, 255); p.PxOdd[I(1)] = new[] { Math.Clamp(I(2), 0, a), Math.Clamp(I(3), 0, a), Math.Clamp(I(4), 0, a), a }; break; }
        case "split": p.Split = Math.Clamp(I(1), 0, 100); break;
        case "lifetime": p.Lifetime = Math.Max(0, I(1)); break;
      }
    }
    return p;
  }
}
static class Program {
  static IntPtr canvas; static readonly List<IntPtr> objs = new(); static int W, H;
  static IntPtr Rect(int x, int y, int w, int h, int r, int g, int b, int a) {
    var o = N.evas_object_rectangle_add(canvas);
    N.evas_object_move(o, x, y); N.evas_object_resize(o, w, h); N.evas_object_color_set(o, r, g, b, a); N.evas_object_show(o);
    objs.Add(o); return o;
  }
  static int TileW = 0;
  static void Fill(int x, int y, int w, int h, int a) {           // base layer, optionally as narrow tiles
    if (w <= 0 || h <= 0 || a <= 0) return;
    if (TileW <= 0) { Rect(x, y, w, h, 0, 0, 0, a); return; }
    for (int t = x; t < x + w; t += TileW) Rect(t, y, Math.Min(TileW, x + w - t), h, 0, 0, 0, a);
  }
  static void Apply(Params p) {
    TileW = p.Tile;
    foreach (var o in objs) N.evas_object_del(o);
    objs.Clear();
    if (!p.Enabled) return;
    if (p.Px.Count > 0 && p.Follow) {             // Pixel Shift follow: physical column P is shown at image column P + x
      int xs = ShiftFollower.X, d = (int)Math.Floor(xs / 2.0);
      var src = ((xs & 1) != 0 && p.PxOdd.Count > 0) ? p.PxOdd : p.Px;   // odd x: line sits half a canvas pixel over
      var moved = new SortedDictionary<int, int[]>(); foreach (var kv in src) moved[kv.Key + d] = kv.Value; p = p.WithPx(moved);
    }
    if (p.Px.Count > 0) {                         // per-pixel mode: px lines define the gap, base alpha elsewhere
      int x0 = -1;
      void Base(int a0, int a1) { if (a1 > a0 && p.Alpha > 0) Fill(a0, 0, a1 - a0, H, p.Alpha); }
      int lo = Math.Max(0, p.Px.Keys.Min()), hi = Math.Min(W - 1, p.Px.Keys.Max());
      Base(0, lo);
      for (int x = lo; x <= hi; x++) {
        if (p.Px.TryGetValue(x, out var c)) {
          int ys = H * p.Split / 100;                       // fixed part on top, original (base layer) below
          if (ys > 0 && c[3] > 0) Rect(x, 0, 1, ys, c[0], c[1], c[2], c[3]);
          if (ys < H && p.Alpha > 0) Fill(x, ys, 1, H - ys, p.Alpha);
        }
        else Base(x, x + 1);
      }
      Base(hi + 1, W);
      _ = x0;
    } else {
    int gx = Math.Clamp(p.GapX, 0, W), n = Math.Min(p.Gap.Count, W - gx);
    if (p.Alpha > 0) {
      if (gx > 0) Fill(0, 0, gx, H, p.Alpha);
      if (gx + n < W) Fill(gx + n, 0, W - gx - n, H, p.Alpha);
    }
    for (int i = 0; i < n; i++) {
      int a = p.Gap[i], b = 0;
      if (p.Blue > 0 && a < p.Alpha) { b = p.Blue; a = Math.Max(a, b); }
      if (a > 0) Rect(gx + i, 0, 1, H, 0, 0, b, a);
    }
    }
    if (p.Marker) Rect(W / 2 - 48, H / 2 - 48, 96, 96, 50, 50, 50, 255);
  }
  static int Main(string[] args) {
    if (args.Length < 1) { Console.Error.WriteLine("usage: GapOverlay <dir> [w h]"); return 2; }
    string dir = args[0], pf = Path.Combine(dir, "params"), stop = Path.Combine(dir, "stop"), status = Path.Combine(dir, "status");
    W = args.Length >= 3 ? int.Parse(args[1]) : 1920; H = args.Length >= 3 ? int.Parse(args[2]) : 1080;
    if (N.ecore_evas_init() <= 0) { Console.Error.WriteLine("init failed"); return 3; }
    // Same creation sequence as the proven marker: small window, content first, then show
    // (a full-size empty window shown immediately ends up 1x1 / not composited on this TV).
    var win = N.ecore_evas_new("wayland_shm", 96, 96, 96, 96, IntPtr.Zero);
    if (win == IntPtr.Zero) { Console.Error.WriteLine("window failed"); N.ecore_evas_shutdown(); return 3; }
    N.ecore_evas_alpha_set(win, 1); N.ecore_evas_focus_skip_set(win, 1);
    var empty = new Rect(); N.ecore_evas_input_rect_set(win, ref empty); N.ecore_evas_layer_set(win, 6);
    canvas = N.ecore_evas_get(win);
    var anchor = N.evas_object_rectangle_add(canvas);           // tiny near-invisible anchor (alpha 1/255, 1 px)
    N.evas_object_move(anchor, 0, 0); N.evas_object_resize(anchor, 1, 1); N.evas_object_color_set(anchor, 0, 0, 0, 1); N.evas_object_show(anchor);
    N.ecore_evas_show(win);
    DateTime mtime = DateTime.MinValue; Params cur = new(); long start = Environment.TickCount64, lastCheck = 0; int rc = 0;
    ShiftFollower.Start(); int seenSeq = -1;
    try {
      while (true) {
        long now = Environment.TickCount64;
        if (File.Exists(stop)) break;
        if (cur.Lifetime > 0 && now - start > cur.Lifetime * 1000L) { rc = 0; break; }
        if (ShiftFollower.Seq != seenSeq) {
          seenSeq = ShiftFollower.Seq;
          if (cur.Follow) { Apply(cur); try { File.WriteAllText(status, $"shift x={ShiftFollower.X} {DateTime.UtcNow:O}\n"); } catch { } }
        }
        if (now - lastCheck >= 50) {
          lastCheck = now;
          try {
            var m = File.GetLastWriteTimeUtc(pf);
            if (File.Exists(pf) && m != mtime) {
              mtime = m; cur = Params.Parse(File.ReadAllText(pf)); ShiftFollower.Notify = cur.Notify; Apply(cur);
              N.ecore_evas_geometry_get(win, out int gx0, out int gy0, out int gw, out int gh);
              File.WriteAllText(status, $"applied {DateTime.UtcNow:O} alpha={cur.Alpha} blue={cur.Blue} gapx={cur.GapX} gap=[{string.Join(",", cur.Gap)}] px={cur.Px.Count} split={cur.Split} tile={cur.Tile} follow={cur.Follow} shift={ShiftFollower.X} enabled={cur.Enabled} marker={cur.Marker} objs={objs.Count} geom={gx0},{gy0},{gw}x{gh}\n");
            }
          } catch (Exception e) { File.WriteAllText(status, "param error: " + e.Message + "\n"); }
        }
        N.ecore_main_loop_iterate_may_block(0);
        Thread.Sleep(15);
      }
    } finally {
      foreach (var o in objs) N.evas_object_del(o);
      objs.Clear();
      N.ecore_evas_free(win); N.ecore_evas_shutdown();
      try { File.AppendAllText(status, $"exited {DateTime.UtcNow:O}\n"); } catch { }
    }
    return rc;
  }
}
}
