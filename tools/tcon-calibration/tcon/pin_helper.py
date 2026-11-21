#!/usr/bin/env python3
"""Pin a built TCON helper in a plan file (offline): writes the sha256 of helpers/NAME/bin/TconDump.{dll,runtimeconfig.json,
deps.json} into PLAN's "helper_sha256". The services refuse to stage a helper whose files do not match these pins, so
re-run this (after review) whenever you rebuild a helper.
usage: pin_helper.py scan-arm <work>/s0svc/plan.json      (s0-nightly)
       pin_helper.py runtime  <work>/rtsvc/rt_plan.json   (rt_tool / s95f-rt; also rt_plan-bake11.json style copies)"""
import hashlib, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); import config as C
FILES = ('TconDump.dll', 'TconDump.runtimeconfig.json', 'TconDump.deps.json')
if len(sys.argv) != 3 or sys.argv[1] not in ('scan-arm', 'runtime', 'read-poke'): sys.exit(__doc__)
b, plan = C.HELPERS / sys.argv[1] / 'bin', pathlib.Path(sys.argv[2])
d = json.loads(plan.read_text())
d['helper_sha256'] = {f: hashlib.sha256((b / f).read_bytes()).hexdigest() for f in FILES}
plan.write_text(json.dumps(d, indent=1)); print(json.dumps(d['helper_sha256'], indent=1))
