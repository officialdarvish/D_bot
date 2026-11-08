# Optional local Xray archive

Normal builds use the official, pinned multi-architecture Xray container image.
For an offline Xray installation, put the official release ZIP in one of:

- `build/xray/26.9.9/Xray-linux-arm64-v8a.zip` (ARM64)
- `build/xray/26.9.9/Xray-linux-64.zip` (AMD64)
- `build/xray/26.9.9/Xray-linux-arm32-v7a.zip` (ARMv7)

Build with `XRAY_SOURCE=archive docker compose build api bot`, then run
`docker compose up -d --no-build api bot`.

Only Xray is supplied offline; Docker base images, Python and Node dependencies
still need their normal network access or an existing build cache.
The binary must match the selected version and target architecture. Local files
are validated before installation. See `docs/DOCKER_XRAY_UPDATE_FIX_FA.md`.
