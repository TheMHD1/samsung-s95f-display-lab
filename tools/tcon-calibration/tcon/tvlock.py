"""TV-side lock shared by every tool that talks to the TCON helper (copied unchanged from the blackout watcher, where it
   was verified with a 4-way concurrent steal test). The scripts run on the TV through config.tv_root()."""

def lock_script(path, owner, stale):
    """POSIX sh run on the TV: prints LOCK=ACQUIRED or LOCK=BUSY <owner> <t>. Re-entrant for the same owner (refresh).
    Steal of a stale lock is serialised by a second mkdir (<path>.steal); inside it staleness is re-checked from scratch
    (owner time, or the dir mtime while the owner file is not yet written) and the new lock is taken before the guard
    is released, so a fresh lock is never removed (verified by a 4-way concurrent steal test)."""
    return (f'L={path}; O={owner}; S={int(stale)}; n=$(date +%s)\n'
            'take() { mkdir "$L" 2>/dev/null && echo "$O $n" > "$L/owner" && echo LOCK=ACQUIRED; }\n'
            'take && exit 0\n'
            'o=; t=; read o t < "$L/owner" 2>/dev/null\n'
            'if [ "$o" = "$O" ]; then echo "$O $n" > "$L/owner"; echo LOCK=ACQUIRED; exit 0; fi\n'
            'tt=${t:-$(stat -c %Y "$L" 2>/dev/null || echo 0)}\n'
            'if [ $((n - tt)) -gt $S ]; then\n'
            '  g=$(stat -c %Y "$L.steal" 2>/dev/null || echo $n); [ $((n - g)) -gt $S ] && rmdir "$L.steal" 2>/dev/null\n'
            '  if mkdir "$L.steal" 2>/dev/null; then\n'
            '    if [ -d "$L" ]; then\n'
            '      o2=; t2=; read o2 t2 < "$L/owner" 2>/dev/null\n'
            '      t2=${t2:-$(stat -c %Y "$L" 2>/dev/null || echo 0)}\n'
            '      [ "$o2" != "$O" ] && [ $((n - t2)) -gt $S ] && rm -rf "$L"\n'
            '    fi\n'
            '    take; r=$?; rmdir "$L.steal"; [ $r = 0 ] && exit 0\n'
            '  fi\n'
            'fi\n'
            'echo "LOCK=BUSY ${o:-?} ${t:-?}"\n')


def unlock_script(path, owner):
    return (f'L={path}; O={owner}; o=; read o t < "$L/owner" 2>/dev/null\n'
            '[ "$o" = "$O" ] && rm -rf "$L"; echo LOCK=RELEASED\n')


