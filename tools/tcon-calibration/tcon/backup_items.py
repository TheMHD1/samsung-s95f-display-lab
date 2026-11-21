#!/usr/bin/env python3
"""Read-only backup of every panel-controller storage item through the stock storage-read opcode."""
import hashlib, json, pathlib, shutil, struct, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); import config as C
H = pathlib.Path(__file__).parent; C.ensure_dirs(); B = C.BACKUP; CAPS = C.CAPTURES
if len(sys.argv) != 2: sys.exit('usage: backup_items.py TCON_PACKAGE.bin   (the F_RSM1_*_COMMON.bin TCON package from YOUR TV\'s firmware;\n'
                                 '       only its storage map at 0x3d7f8 is used; this S95F firmware layout - verify yours)')
pkg = pathlib.Path(sys.argv[1]).read_bytes(); im = pkg[0x200:0x40200]
N = 'C1 C2 C6 D1 D2 D3 D4 CA VEP2x2 RTSCAN DOT FabTemp OffTemp PANELID OriT NewT MFree QFS_OFST PDN_QC'.split(); ex = []
for i, n in enumerate(N):
    w = struct.unpack_from('<8I', im, 0x3d7f8+32*i); seen = set()
    for s in (0, 1):
        if w[3+s] not in seen: seen.add(w[3+s]); ex.append((f'{i:02d}_{n}/hdr{s}.bin', w[3+s], 512))
    if w[7]:
        b0, b1, ram, size, stride, cnt = struct.unpack_from('<6I', im, w[7])
        for k, b in enumerate((b0, b1)):
            for j in range(cnt): ex.append((f'{i:02d}_{n}/bank{k}_seg{j:02d}.bin', b+j*stride, size))
batches, cur, sz = [], [], 0
for e in ex:
    if cur and (sz+e[2] > 24*1024*1024 or len(cur) >= 60): batches.append(cur); cur, sz = [], 0
    cur.append(e); sz += e[2]
batches.append(cur); man = json.loads((B/'MANIFEST.json').read_text()) if (B/'MANIFEST.json').exists() else []; have = {m['file'] for m in man}; print(len(ex), 'extents', sum(e[2] for e in ex), 'bytes', len(batches), 'batches', flush=True)
for k, b in enumerate(batches):
    if all(f in have for f, _, _ in b): continue
    b = [e for e in b if e[0] not in have]
    name = f'bk-{k:03d}'; shutil.rmtree(CAPS/name, ignore_errors=True)
    r = ','.join(f'st:{a:x}:{n:x}' for _, a, n in b)
    p = subprocess.run([sys.executable, '-B', str(H/'tvdump.py'), '--name', name, '--chunk', '4096', '--budget-ms', '70000', '--ranges', r], capture_output=True, text=True, timeout=400)
    m = json.loads((CAPS/name/'meta.json').read_text())['result']
    if m.get('rc') != 0 or m.get('error') or 'hash ok' not in p.stdout: print('STOP', name, m.get('error'), m.get('stopped'), p.stdout[-300:], p.stderr[-300:]); sys.exit(1)
    d = (CAPS/name/'dump.bin').read_bytes(); o = 0
    for f, a, n in b:
        (B/f).parent.mkdir(exist_ok=True); c = d[o:o+n]; assert len(c) == n; (B/f).write_bytes(c); man.append(dict(file=f, storage=hex(a), bytes=n, sha256=hashlib.sha256(c).hexdigest())); o += n
    shutil.rmtree(CAPS/name); (B/'MANIFEST.json').write_text(json.dumps(man, indent=0)); print(name, 'ok', m['ms'], 'ms', o, flush=True)
print('DONE', len(man))
