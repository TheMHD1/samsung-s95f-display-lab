# Root access used during the TV research

## Actual route: SDK archive launcher, not GPU-memory injection

The S95F research used the **archive-root** implementation in [Samsung TV Root](https://github.com/chris-ritsen/samsung-tv-root). The inspected source worktree was based on commit `4ad2c4d3b0d0e0da4b5b7ebe4a787e94596f416b`, with a local runtime-discovery compatibility patch described below. Source locations are `src/samsung_tv_root/archive_root.py`, `payloads/common/SamsungTvArchiveRoot.cs`, and `payloads/common/SamsungTvRootAgent.cs` in that project. The base commit alone is not the complete deployed S95F provenance.

The chain is:

```text
Developer Mode and an authorized SDB connection
  → SDB package-name command foothold
  → capability-bearing Samsung .NET runtime
  → private mount namespace
  → per-session public-key and passwd views
  → Samsung signed archive launcher
  → authenticated root agent calls back to the host
```

The upstream project's separate QN90F route uses Mali-G510/CVE-2025-0072 and GPU page-table work. **That was not the current S95F access route.** A kernel GPU exploit granting privilege is also unrelated to injecting corrected picture pixels into a compositor. For the underlying separate vulnerability, see the original [GitHub Security Lab advisory](https://securitylab.github.com/advisories/GHSL-2024-356_Arm_Mali/) and [Arm bulletin](https://developer.arm.com/documentation/110465/latest/).

## Prerequisites found by the archive-root preflight

The inspected implementation requires:

- A ready SDB connection and a successful package-name shell-injection foothold check. An ordinary interactive `sdb shell` being closed is not proof that the separate installer path failed.
- `/usr/bin/dotnet` with effective `CAP_SETGID` and `CAP_SYS_ADMIN`.
- `/usr/sbin/sdbd-tarlauncher` with effective `CAP_SETUID` and `CAP_SETGID`.
- A supported installed .NET runtime: 3.1 or at least 6 in the inspected source.
- A tar implementation supporting `--to-command`, matching compiled payloads and a reachable authenticated callback to the host.

There is no model whitelist in that archive-root code. That does not imply all models are compatible. Upstream documents its QN90B/QN90F tests; this project used an additional exact-model/build/Developer-Mode/callback-route gate on one S95F. Check the actual capabilities, ABI and source revision of any future target rather than relying on the product name.

## S95F runtime-discovery compatibility patch

The local S95F signed dotnet host rejected `--list-runtimes` with `Unknown option --list-runtimes`. The source worktree had a small fallback: only for that specific error, enumerate `/usr/share/dotnet/shared/Microsoft.NETCore.App/*`, admit directories containing both `libcoreclr.so` and `System.Private.CoreLib.dll`, then pass the discovered versions through the existing runtime-major gate. Other errors still fail. This is a runtime-discovery adjustment, not a capability, authentication or firmware-compatibility bypass.

The exact sanitized [source patch and application instructions](../../research/root-access/README.md) are included. It was checked against the pinned base and reproduces the local archive_root.py delta. A pristine upstream checkout without that change is not a complete recipe for the tested S95F environment. Re-review it if upstream has since added equivalent support.

## How the privilege transition works

The host makes a random session package, ephemeral RSA signing material, an authenticated-agent secret and a session passwd view mapping the selected owner identity to UID 0. The staged **SamsungTvArchiveRoot.dll** payload creates a **private mount namespace**. Within that namespace it substitutes the session verification-key and passwd views, then invokes the capability-bearing signed archive launcher with a package-scoped archive and tar `--to-command` script. That script starts the callback agent under the staged identity.

This is not a global replacement of the TV's passwd or verification key. The implementation checks the original system-file hashes through the original SDK namespace before and after acquisition and removes its random staging artifacts. Interrupted execution can leave user-storage staging files; cleanup is an observation to verify, not a guarantee inferred from an exit code.

The root-agent protocol uses nonce/HMAC-SHA256 authentication, ordered command frames, output limits and timeouts. The host checks both UID and EUID. The agent deletes its token file after reading it. UID 0 does not remove all mandatory-access-control boundaries: the observed SMACK label remained `User`.

Root acquisition and UEP/unsigned-execution policy are separate mechanisms. Do not add an unrelated UEP-disable operation merely because a command needs root.

## Reproduction entry points

Obtain Tizen Studio/SDB and build or install the upstream public tool according to its own [README](https://github.com/chris-ritsen/samsung-tv-root#readme). Keep its source/payload revision together. The public CLI provides:

```sh
samsung-tv-root doctor
samsung-tv-root -o json archive-root probe "$TV_HOST"
samsung-tv-root -o json archive-root root "$TV_HOST" --command 'id'
```

`TV_HOST` is the owner's selected device, set locally. **Probe is an active access test**, not a passive status getter; it can stage and acquire an authenticated session, then shut it down. The root command executes the requested command and is not an interactive PTY. Check that revision's help for callback/bind host, timeout and payload options. Do not run these against an unselected device or while another controller owns the session.

This repository links the maintained access implementation instead of copying an old exploit/payload bundle or publishing private deployment files. The upstream source has its own Unlicense; Samsung firmware, binaries and extracted signing/decryption keys are not part of this repository.

## Host-assisted persistence and the deployed guard pattern

The deployed S95F controller watched for device presence, checked exact model/build and Developer Mode configuration, acquired an authenticated session, then served local requests through an owner-only **0600 Unix socket** with peer-UID verification. It checked callback routing/firewall scope and unchanged global system-file hashes. Lost sessions were cleaned up and reacquired by the host.

“Persistent root” here means **host-assisted reacquisition**, not a TV boot service, firmware change or permanently rooted TV. A persistent-only execution mode refused to bootstrap when the existing authenticated controller was unavailable. That is useful for calibration: a routine getter should not silently trigger a new access exploit.

For a future portable adapter, put expected model/build and socket location in private configuration, serialize access with the keeper/controller tools, distinguish timeout from definite failure, and never retry an ambiguous mutation. Keep secrets, certificates, package identifiers and per-boot identities outside Git. Test identity validation and cleanup independently before attaching controller or display experiments.
