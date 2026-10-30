"""Camera controller: runs measure.py (locally or on the camera computer over SSH) and turns a frame into
per-panel-column ratios against the healthy neighbours.

Mapping camera samples to panel columns: a reference shot of the UNCORRECTED line (calib/reference.py) stores the
camera x of the darkest column, which you identified as panel column `ref_col` (config). Every later frame uses the
column whose centre is nearest to that x - NOT the darkest column of the new frame (once the fix works there is no
darkest column). The camera column mapping drifts by ~1 TV column per 60-100 columns away from the line (lens
distortion, angle), so always compare against LOCAL neighbours (bg_left / bg_right in config, ~10-40 columns away).
"""
import json, os, shlex, subprocess, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lfconfig as C

REF = os.path.join(C.HERE, 'camera-ref.json')
LOG = os.path.join(C.HERE, 'camera-log.jsonl')


def measure(label, count=1, shutter=None, keep=0):
    cam = C.CFG['camera']
    script = cam['measure_script']
    if cam.get('mode', 'local') == 'local' and not os.path.isabs(script):
        script = os.path.join(C.HERE, script)
    cmd = [cam.get('python', 'python3'), script, '--label', label, '--count', str(count), '--keep', str(keep),
           '--phase-r', str(cam.get('phase_r', 1.96)), '--phase-b', str(cam.get('phase_b', -1.49))]
    if shutter:
        cmd += ['--shutter', shutter]
    if cam.get('mode', 'local') == 'ssh':
        p = subprocess.run(['ssh', '-o', f"User={cam['ssh_user']}", cam['ssh_host'], ' '.join(shlex.quote(c) for c in cmd)],
                           capture_output=True, text=True, timeout=900)
    else:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    try:
        d = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        raise RuntimeError(f'measure.py gave no JSON: {p.stderr[-500:]}')
    if 'error' in d:
        raise RuntimeError(d['error'])
    with open(LOG, 'a') as f:
        f.write(json.dumps({'t': time.strftime('%F %T'), 'label': label, 'shutter': d.get('shutter'),
                            'peak': d['frames'][0]['peak'], 'period': d['frames'][0]['period']}) + '\n')
    return d['frames']


def save_reference(frame):
    cen = np.array(frame['centres'])
    ref = {'x': float(cen[frame['line_col_idx']]), 'col': C.CFG['line']['ref_col'], 'period': frame['period']}
    json.dump(ref, open(REF, 'w'))
    return ref


def ratios(frame, ref=None):
    """-> {'R': {col: ratio}, 'G': ..., 'B': ..., 'R_bg': median background, ...}
    ratio = column light / local linear fit of the healthy columns on both sides (1.00 = invisible)."""
    ref = ref or json.load(open(REF))
    ln = C.CFG['line']; rc = ref['col']
    cen = np.array(frame['centres']); i0 = int(np.argmin(np.abs(cen - ref['x'])))
    out = {}
    for c in 'RGB':
        v = np.array(frame['cols'][c]); idx = np.arange(len(v)) - i0 + rc     # panel column of every camera column
        side = ((idx >= ln['bg_left'][0]) & (idx <= ln['bg_left'][1])) | ((idx >= ln['bg_right'][0]) & (idx <= ln['bg_right'][1]))
        bgl = np.polyval(np.polyfit(idx[side] - rc, v[side], 1), idx - rc)
        cols = range(ln['report_cols'][0], ln['report_cols'][1] + 1)
        out[c] = {j: float(v[i0 + j - rc] / bgl[i0 + j - rc]) for j in cols}
        out[c + '_abs'] = {j: float(v[i0 + j - rc] - bgl[i0 + j - rc]) for j in cols}
        out[c + '_bg'] = float(np.median(v[side]))
    return out


def fmt(r, chans='RGB'):
    return '  '.join(f'{c}:' + ','.join(f'{r[c][j]:.2f}' for j in sorted(r[c])) for c in chans)
