#!/usr/bin/env python3
"""Make narrow-bar SDR clips: columns 1100..1419, full height, BT.709 limited range, 24 fps, 60 s, High profile 4:2:0.
One frame is written to disk and looped by ffmpeg (no big buffers).  usage: mkclip.py OUTDIR NAME:R:G:B [...]  (full-range 0-255 codes)"""
import os, subprocess, sys, tempfile, numpy as np
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
for spec in sys.argv[2:]:
    n, r, g, b = spec.split(':'); r, g, b = float(r)/255, float(g)/255, float(b)/255
    Y = .2126*r+.7152*g+.0722*b; y, u, v = round(16+219*Y), round(128+224*(b-Y)/1.8556), round(128+224*(r-Y)/1.5748)
    P = np.full((2160, 3840), 16, np.uint8); P[:, 1100:1420] = y
    U = np.full((1080, 1920), 128, np.uint8); V = U.copy(); U[:, 550:710] = u; V[:, 550:710] = v
    with tempfile.NamedTemporaryFile(suffix='.yuv') as t:
        t.write(P.tobytes()+U.tobytes()+V.tobytes()); t.flush()
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-stream_loop', '1439', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', '3840x2160', '-r', '24', '-i', t.name,
                        '-c:v', 'libx264', '-preset', 'medium', '-qp', '2', '-profile:v', 'high', '-level', '5.1', '-pix_fmt', 'yuv420p', '-bf', '2',
                        '-x264-params', 'keyint=48:aq-mode=0:deblock=0,0', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
                        '-color_range', 'tv', os.path.join(out, n+'.mp4')], check=True)
    d = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '3', '-i', os.path.join(out, n+'.mp4'), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-'], capture_output=True, check=True).stdout
    a = np.frombuffer(d, np.uint8); Yd = a[:3840*2160].reshape(2160, 3840); Ud = a[3840*2160:3840*2160+1920*1080].reshape(1080, 1920); Vd = a[3840*2160+1920*1080:].reshape(1080, 1920)
    print(n, 'want', (y, u, v), 'got bar', (int(np.median(Yd[:, 1110:1410])), int(np.median(Ud[:, 560:700])), int(np.median(Vd[:, 560:700]))),
          'max dev', int(np.abs(Yd[:, 1110:1410].astype(int)-y).max()), 'black', int(Yd[:, :1080].max()), flush=True)
