#!/usr/bin/env python3
"""Reference shot: layer OFF, grey 51 clip, find the camera position of the line.

  reference.py            shoot, store camera-ref.json (camera x of the darkest column = config line.ref_col)
  reference.py --check    shoot again with the layer off and print the uncorrected ratios (your 'before' numbers)

Run it again whenever the camera or tripod moved. Check the printed ratios: the darkest column must be the one you
configured as ref_col (from the ruler/marker step); healthy columns left/right should read 1.00 +- 0.02.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lfcal, camctl
import lfconfig as C

check = '--check' in sys.argv
lfcal.show_original()
C.play('grey51')
import time
time.sleep(8)
fr = camctl.measure('reference-grey51', 1, lfcal.shutter_for('grey', 51))[0]
C.stop()
if not check:
    ref = camctl.save_reference(fr)
    print(f"reference saved: camera x {ref['x']:.1f} = panel column {ref['col']}, period {ref['period']:.2f} samples/column; "
          f"phase estimate R {fr['phase_est']['R']}, B {fr['phase_est']['B']} (config: {C.CFG['camera'].get('phase_r')}, "
          f"{C.CFG['camera'].get('phase_b')})")
r = camctl.ratios(fr)
print('uncorrected grey51  ' + camctl.fmt(r))
