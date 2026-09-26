# Grading on the aarch64 agent host — unblocked 2026-08-17

The grader had been a single point of failure: SWE-bench evaluation images are `x86_64`
only, the agent host is `aarch64`, and the documented alternative (a separate x86 desktop) is not reliably
reachable. Every graded run on the arm64 host failed with:

```
docker.errors.ImageNotFound: 404 ... /images/swebench/sweb.eval.x86_64.<instance>:latest/json
swebench.harness.docker_build.BuildImageError: Error building image <instance>
```

Two things were missing. Both are one-time setup:

**1. x86 emulation was never registered.** `ls /proc/sys/fs/binfmt_misc/` showed no qemu
entry, and `docker run --platform linux/amd64 alpine uname -m` returned `exec format error`.

```sh
docker run --privileged --rm tonistiigi/binfmt --install amd64
# verify — must print x86_64, not an exec format error
docker run --rm --platform linux/amd64 alpine:latest uname -m
```

**2. swebench does not pull the eval image; it expects it to exist and errors if it does
not.** So the images must be pulled explicitly, with the platform pinned:

```sh
docker pull --platform linux/amd64 swebench/sweb.eval.x86_64.<instance_image_name>:latest
```

The image name replaces the `__` in the instance id with `_1776_`:
`pallets__flask-5014` → `swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest`.

## Cost

Emulated test execution is slow — budget minutes per instance, not seconds — and images are
1-2GB each. Keep `max_workers` at 1-2: parallel emulated docker builds are what OOM'd the
previous grader host.

## Why this mattered

A run can fail in two completely different ways that the summary reports identically as a
low score. The distinction is in the artifacts: `traces.jsonl` records `has_patch`, and
`grade.py` defines `error` as "genuine harness failure (env didn't build / never ran), NOT a
model failure". The 2026-08-17 run showed `errors: 3, graded: 0` with `has_patch: true` on
every instance and real 446-900 char patches — the agent had done its work and the grader
never ran. Read `graded` before reading `pass_at_1`; a `pass_at_1` of 0.0 with `graded: 0`
is not a score at all.
