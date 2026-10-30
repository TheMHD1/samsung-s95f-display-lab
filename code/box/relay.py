#!/usr/bin/env python3
"""OLED line-fix relay - runs on the CoreELEC box next to Kodi (unit linefix-relay.service).

Settings: /storage/linefix/relay.json (written by install_box.py from config.json -> "relay").

1. Profiles (every 0.2 s): HDMI output mode (/sys/class/display/mode) + Kodi VideoPlayer.HdrType ->
     "444"  SDR at 24/25/30 Hz (the box sends YCbCr 4:4:4 there),
     "422"  SDR at 50/60 Hz (4:2:2 over an HDMI 2.0 link -> slightly different colour lifts),
     "hdr"  HDR10/HDR10+: the v2 parameter strip for the patched gles_gui_composite.frag (only if the patched shader
            is active, else no strip) + Home property linefix_hdr=1 (hides any SDR dim rectangles),
     none   Dolby Vision / HLG / unknown HDR / any non-2160p output: no strip (no correction, but also no harm).
   The switch happens while the TV is re-syncing to the new HDMI mode, so it is not visible.
2. Pixel Shift (optional): GET /x?v=<shift> sets Home property linefix_x; the skin slides the layer by that many panel
   columns on the next frame. You need your own source for the current shift value (see docs/kodi/KODI-LAYER.md);
   without one keep the TV's Pixel Shift OFF.
3. Optional external HDR hint: GET /h?v=0|1|auto (overrides the box's own SDR/HDR decision; normally unused because the
   box knows its own output state immediately while TVs report HDR seconds late).
4. Enforcement (every 0.5 s): reads Kodi's actual linefix_on / linefix_strip / linefix_x / linefix_hdr and re-sends any
   that differ (Kodi restart, lost UDP packet). linefix_on is wanted while /storage/linefix/on exists.
5. Self-heal: after an HDMI re-plug (hpd_state 0->1: TV/soundbar restart, eARC handshake; +4 s) and after every
   output-mode change (+2 s) everything is re-applied, with the strip shown through a FRESHLY NAMED copy
   (/storage/linefix/rt/) so Kodi must reload the texture. (After an HDMI reset the strip once stopped working while
   all properties still looked right.) 'resets' in /p counts these.
6. Re-init (optional, relay.json auto_reboot_after_replug): an HDMI re-plug once left the display chain in a state where
   the HDR correction no longer worked; a Kodi restart did NOT fix it, a reboot of the box did. So after a re-plug the
   relay reboots the box once, at a quiet moment: no video for 20 s, uptime > 5 min, at most every 30 min.
   Diagnostics go to /storage/linefix/diag/ first. Disable at runtime: touch /storage/linefix/no-auto-reboot.
/storage/linefix/profile.lock (younger than 2 h) pauses switching + enforcement (used during calibration).
GET /p returns the state as JSON. Only addresses in relay.json "allowed" may call the HTTP API.
NEVER read /sys/class/amvecm/* on Amlogic boxes: reading some of those nodes crashed/rebooted the box."""
import http.server, json, os, re, socket, threading, time
from urllib.parse import urlparse, parse_qs
from kodi.xbmcclient import XBMCClient          # ships with Kodi on CoreELEC (EventServer client)

D = "/storage/linefix"
try:
    CFG = json.load(open(f"{D}/relay.json"))
except Exception:
    CFG = {}
PORT = int(CFG.get("port", 8790))
ALLOWED = set(CFG.get("allowed", ["127.0.0.1"])) | {"127.0.0.1"}
XMAX = int(CFG.get("pixel_shift_max", 30))
HDR_OK = tuple(CFG.get("hdr_ok", ["hdr10", "hdr10plus", "hdr10+"]))   # calibrated + verified; DV / HLG: no strip
AUTO_REBOOT = bool(CFG.get("auto_reboot_after_replug", True))
PROFILES, LOCK, ONFLAG = f"{D}/profiles.json", f"{D}/profile.lock", f"{D}/on"
SHADER = "/usr/share/kodi/system/shaders/GLES/2.0/gles_gui_composite.frag"
HPD = "/sys/class/amhdmitx/amhdmitx0/hpd_state"
REINIT_LAST = f"{D}/last-auto-reboot"
RT = f"{D}/rt"
state = {"x": None, "t": 0.0, "tv_hdr": None, "profile": None, "strip": None, "hdr_prop": None, "mode": None,
         "hdr": "", "err": "", "shader": False, "shader_t": 0.0, "enforced": 0, "hpd": None, "resets": 0,
         "shown": None, "reinit_pending": None}
lock = threading.Lock()
cli = XBMCClient("linefix-relay"); cli.connect()


def action(a):
    with lock:
        cli.send_action(a)


def rpc(method, params):
    """Kodi JSON-RPC over raw TCP. Note: replies can arrive in several chunks - read until the JSON closes."""
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    with socket.create_connection(("127.0.0.1", 9090), timeout=1.0) as s:
        s.sendall(req); buf = b""
        while not buf.rstrip().endswith(b"}"):
            d = s.recv(4096)
            if not d:
                break
            buf += d
    return json.loads(buf)["result"]


def has_video():
    return bool(rpc("XBMC.GetInfoBooleans", {"booleans": ["Player.HasVideo"]}).get("Player.HasVideo"))


def kodi_hdr():
    """'' for SDR or no video, else hdr10 / dolbyvision / hlg / hdr10plus (Kodi reports the OUTPUT type)."""
    if not has_video():
        return ""
    return (rpc("XBMC.GetInfoLabels", {"labels": ["VideoPlayer.HdrType"]}).get("VideoPlayer.HdrType") or "").lower()


def shader_ok():
    try:
        return "LINEFIX v2" in open(SHADER).read()
    except Exception:
        return False


def want(mode, khdr, prof):
    """-> (profile name, strip path or '', linefix_hdr '1' or '')"""
    if not mode.startswith("2160p"):                      # GUI not 1:1 with the panel -> never draw a strip
        return "none", "", "1" if (khdr or state["tv_hdr"]) else ""
    tv_hdr = state["tv_hdr"]
    out_hdr = bool(khdr) if tv_hdr is None else bool(tv_hdr)
    if out_hdr:
        if khdr in HDR_OK and state["shader"] and prof.get("hdr"):
            return "hdr", prof["hdr"], "1"
        return "none", "", "1"                            # DV / HLG / no shader: no correction, no dim
    m = re.search(r"p(\d+(?:\.\d+)?)hz", mode)
    p = "444" if (float(m.group(1)) if m else 60.0) <= 30.5 else "422"
    return p, prof.get(p) or prof.get("444") or "", ""


def shown_copy(strip):
    """Fresh path for the same strip image -> Kodi must load a new texture."""
    os.makedirs(RT, exist_ok=True)
    state["resets"] += 1
    dst = f"{RT}/{os.path.basename(strip)[:-4]}-r{state['resets']}.png"
    with open(strip, "rb") as a, open(dst + ".tmp", "wb") as b:
        b.write(a.read())
    os.replace(dst + ".tmp", dst)
    for f in sorted(os.listdir(RT), key=lambda n: os.path.getmtime(f"{RT}/{n}"))[:-3]:
        try:
            os.remove(f"{RT}/{f}")
        except OSError:
            pass
    return dst


IDLE = {"since": None}


def maybe_reinit():
    """After an HDMI re-plug: reboot the box once at a quiet moment (no video for 20 s)."""
    if not AUTO_REBOOT or state["reinit_pending"] is None or os.path.exists(f"{D}/no-auto-reboot"):
        return
    if state["hdr"] != "" or has_video():
        IDLE["since"] = None; return
    IDLE["since"] = IDLE["since"] or time.time()
    up = float(open("/proc/uptime").read().split()[0])
    last = os.path.getmtime(REINIT_LAST) if os.path.exists(REINIT_LAST) else 0
    if time.time() - IDLE["since"] < 20 or up < 300 or time.time() - last < 1800:
        return
    d = f"{D}/diag/{time.strftime('%Y%m%d-%H%M%S')}"
    os.makedirs(d, exist_ok=True)
    os.system(f"cat /sys/class/amhdmitx/amhdmitx0/config > {d}/hdmitx.txt 2>&1; dmesg | tail -n 300 > {d}/dmesg.txt; "
              f"tail -n 400 /storage/.kodi/temp/kodi.log > {d}/kodi.txt")
    with open(f"{d}/relay.json", "w") as f:
        json.dump(state, f)
    open(REINIT_LAST, "w").write(time.strftime("%F %T") + " auto reboot after HDMI re-plug\n")
    os.system("sync; reboot")


def profiles_loop():
    prof, mtime, last_hdr_t, last_enf, refresh_at = {}, None, 0.0, 0.0, 0.0
    while True:
        try:
            try:
                hpd = open(HPD).read().strip()[:1]
            except Exception:
                hpd = None
            if hpd == "1" and state["hpd"] == "0":
                refresh_at = time.time() + 4.0              # HDMI re-plug: re-apply once the picture is back
                state["reinit_pending"] = time.time()       # ...and re-init the display chain when idle
            state["hpd"] = hpd
            mt = os.path.getmtime(PROFILES) if os.path.exists(PROFILES) else None
            if mt != mtime:
                prof = json.load(open(PROFILES)) if mt else {}; mtime = mt; state["strip"] = None
            mode = open("/sys/class/display/mode").read().strip()
            if state["mode"] is not None and mode != state["mode"]:
                refresh_at = max(refresh_at, time.time() + 2.0)
            if mode != state["mode"] or time.time() - last_hdr_t > 0.5:
                try:
                    state["hdr"] = kodi_hdr()
                except Exception:
                    pass                                    # keep the last value on a transient JSON-RPC error
                last_hdr_t = time.time()
            state["mode"] = mode
            if time.time() - state["shader_t"] > 20:
                state["shader"] = shader_ok(); state["shader_t"] = time.time()
            locked = os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 7200   # stale lock ignored
            if prof and not locked:
                p, strip, hp = want(mode, state["hdr"], prof)
                if (p, strip, hp) != (state["profile"], state["strip"], state["hdr_prop"]):
                    # ordering: dim off BEFORE an HDR strip appears, strip BEFORE dim comes back -> never too dark/bright
                    if hp:
                        action("SetProperty(linefix_hdr,1,Home)")
                    action(f"SetProperty(linefix_strip,{strip},Home)" if strip else "ClearProperty(linefix_strip,Home)")
                    if not hp:
                        action("ClearProperty(linefix_hdr,Home)")
                    state["profile"], state["strip"], state["hdr_prop"], state["shown"] = p, strip, hp, strip
                if refresh_at and time.time() >= refresh_at:   # self-heal after HDMI reset / mode change
                    refresh_at = 0.0
                    shown = shown_copy(state["strip"]) if state["strip"] and os.path.exists(state["strip"]) else ""
                    action("ClearProperty(linefix_strip,Home)")
                    action(f"SetProperty(linefix_strip,{shown},Home)" if shown else "ClearProperty(linefix_strip,Home)")
                    action("SetProperty(linefix_hdr,1,Home)" if state["hdr_prop"] else "ClearProperty(linefix_hdr,Home)")
                    if os.path.exists(ONFLAG):
                        action("ClearProperty(linefix_on,Home)"); action("SetProperty(linefix_on,1,Home)")
                    if state["x"] is not None:
                        action(f"SetProperty(linefix_x,{state['x']},Home)")
                    state["shown"] = shown or None
                if time.time() - last_enf > 0.5:            # enforce what Kodi actually has
                    last_enf = time.time()
                    lab = rpc("XBMC.GetInfoLabels", {"labels": [f"Window(Home).Property({k})" for k in
                                                                ("linefix_on", "linefix_strip", "linefix_x", "linefix_hdr")]})
                    g = lambda k: lab.get(f"Window(Home).Property({k})", "")
                    on = os.path.exists(ONFLAG)
                    fix = []
                    if (g("linefix_on") == "1") != on:
                        fix.append("SetProperty(linefix_on,1,Home)" if on else "ClearProperty(linefix_on,Home)")
                    want_strip = state["shown"] or state["strip"] or ""
                    if g("linefix_strip") != want_strip:
                        fix.append(f"SetProperty(linefix_strip,{want_strip},Home)" if want_strip else "ClearProperty(linefix_strip,Home)")
                    if g("linefix_hdr") != (state["hdr_prop"] or ""):
                        fix.append("SetProperty(linefix_hdr,1,Home)" if state["hdr_prop"] else "ClearProperty(linefix_hdr,Home)")
                    if state["x"] is not None and g("linefix_x") != str(state["x"]):
                        fix.append(f"SetProperty(linefix_x,{state['x']},Home)")
                    for a in fix:
                        action(a)
                    state["enforced"] += len(fix)
            maybe_reinit()
            state["err"] = ""
        except Exception as e:
            state["err"] = f"{type(e).__name__}: {e}"[:200]
        time.sleep(0.2)


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.client_address[0] not in ALLOWED:
            self.send_response(403); self.end_headers(); return
        u = urlparse(self.path); q = parse_qs(u.query)
        try:
            if u.path == "/x":
                x = int(q["v"][0])
                if not -XMAX <= x <= XMAX:
                    raise ValueError
                action(f"SetProperty(linefix_x,{x},Home)"); state["x"] = x; state["t"] = time.time()
                body = str(x).encode()
            elif u.path == "/h":
                v = q["v"][0]                               # 0 / 1 = force SDR / HDR, auto = box decides
                if v not in ("0", "1", "auto"):
                    raise ValueError
                state["tv_hdr"] = None if v == "auto" else int(v)
                body = str(state["tv_hdr"]).encode()
            elif u.path == "/p":
                body = json.dumps(state).encode()
            else:
                body = str(state["x"]).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        except Exception:
            self.send_response(400); self.end_headers()

    def log_message(self, *a):
        pass


def keepalive():
    """EventServer clients are dropped after a minute of silence -> ping."""
    while True:
        time.sleep(30)
        try:
            with lock:
                cli.ping()
        except Exception:
            pass


threading.Thread(target=keepalive, daemon=True).start()
threading.Thread(target=profiles_loop, daemon=True).start()
http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
