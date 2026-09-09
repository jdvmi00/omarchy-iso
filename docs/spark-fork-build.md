# Spark builds from Jim’s fork

`spark/arm-integration` carries the pending ARM work in `jdvmi00/omarchy-iso`.
It preserves Matt’s original commits through `b333b46c6f3d1ec4e1c97ab6811b94b53006da55`,
including Jim’s graphical-unlock fix, and merges upstream `quattro` at
`a23f8d464dcb0616a61bfaa8026e23d0533da209`. This is an integration branch for
our builds, not a claim that the ARM work has merged upstream.

Use a native ARM64 Spark with Docker, Git and the builder prerequisites.
The current workstation is x86_64; running the ARM build there additionally
requires configured ARM emulation. Prefer the native Spark used for our earlier build.

Check out this branch from Jim’s fork, with sibling `omarchy` and
`omarchy-pkgs` source checkouts. Known inputs from the previous successful build:

- `jdvmi00/omarchy`: `b31c78dfed296d63aac3e78558ee902585d051a4`
  (includes the ARM NVIDIA package-selection fix).
- `omacom/omarchy-pkgs`: `2b15c13e86303cfcc9a8f94974bbaaa802270029`.
- archiso submodule: `424e78130db2af6c1ceb55b442d7914b1109ff2b`.

From the ISO checkout:

```bash
git submodule update --init
./test/all
./bin/omarchy-iso-make --arch aarch64 --keep-pkg-cache --no-boot-offer \
  --local-source ../omarchy ../omarchy-pkgs
```

The wrapper uses a privileged container and shares the host package cache.
`--keep-pkg-cache` avoids clearing that cache wholesale; rebuilding local
packages still replaces their matching cache entries. Output goes to `release/`.
The build does not write installer media or reboot the machine.

The command uses the configured public package repositories. Carrying the source
removes the need to request built ISOs, but does not make package downloads
self-contained. If ARM packages are unavailable, inspect the missing packages
and supply local recipes or a reviewed mirror; see `alarm-iso.md` for the extra
package and mirror options. Do not silently redirect builds to a personal mirror.
Repository contents and the container tag can change; record their actual
versions, build log and ISO checksum for every build.

Run `test/unit/iso-structure-test.sh` against the resulting image, then compute
its SHA-256. The current structure script has a known false failure caused by
`grep -q` closing a pipe early under `pipefail`; inspect that failure before
attributing it to the image. Hardware boot/install testing remains separate.

Keep incorporating upstream fixes into this integration branch. Submit focused
contributions directly to Omacom, identifying dependencies on ARM PR #156.
After ARM lands upstream, reconcile this branch with the merged implementation
and retire carried changes that are covered. Do not force-push away authorship.
