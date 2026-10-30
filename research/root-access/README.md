# S95F archive-root compatibility delta

The actual local S95F worktree was based on Samsung TV Root commit `4ad2c4d3b0d0e0da4b5b7ebe4a787e94596f416b`, with the included [runtime-discovery patch](s95f-runtime-discovery.patch). The upstream project is [chris-ritsen/samsung-tv-root](https://github.com/chris-ritsen/samsung-tv-root), whose source is Unlicense. No private controller, payload binary, access secret, firmware or key is bundled here.

The patch handles a Samsung dotnet host that rejects `--list-runtimes`. It discovers only complete installed runtime directories and retains the original supported-major gate. It rethrows other failures. It does not add a new exploit, bypass target checks, establish universal S95F compatibility or change the TV by itself.

To inspect/apply later, in a separate host-side checkout:

```sh
git clone https://github.com/chris-ritsen/samsung-tv-root.git
cd samsung-tv-root
git checkout 4ad2c4d3b0d0e0da4b5b7ebe4a787e94596f416b
git apply --check /path/to/oled-dead-column-line-fix/research/root-access/s95f-runtime-discovery.patch
git apply /path/to/oled-dead-column-line-fix/research/root-access/s95f-runtime-discovery.patch
```

Follow upstream's build/dependency instructions after reviewing the [root architecture](../../docs/advanced/ROOT-ACCESS.md). Applying this patch is an offline source edit; running upstream probe/root commands is an active operation and should be treated separately. The publication check applied the patch to a temporary pristine source file and compared the result byte-for-byte with the retained local delta; it did not contact the TV.
