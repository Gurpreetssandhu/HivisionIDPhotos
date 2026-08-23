# HivisionIDPhotos on atlas

Private ID-photo service. Reachable **only over Tailscale** — there is no
authentication layer, no public ingress, and no firewall rule holding it
closed. The single control is the host-side port bind.

| | |
|---|---|
| Host | `atlas` (Ubuntu 24.04, Docker 29.1.3, Compose v2.40.3) |
| Deploy path | `/home/gurusandhu/hivision` |
| Repo | `/home/gurusandhu/hivision/HivisionIDPhotos`, branch `atlas-deploy` |
| Data (weights + presets) | `/home/gurusandhu/hivision/data` — **outside the git tree** |
| Direct URL | `http://100.67.158.108:7860` |
| HTTPS URL | `https://atlas.tail270acc.ts.net:9447` |
| Compose project | `hivision` |
| systemd unit | `hivision.service` |
| Secrets | **none** — see [Adding secrets later](#adding-secrets-later-infisical) |

## Layout

```
/home/gurusandhu/hivision/
├── HivisionIDPhotos/              git clone of the fork, branch atlas-deploy
│   └── deploy/atlas/
│       ├── docker-compose.yml
│       ├── .env                   real values, gitignored, NOT in the repo
│       ├── .env.example           placeholders only
│       ├── fetch-weights.sh
│       ├── size_list_EN.csv       source of truth for size presets
│       ├── systemd/hivision.service
│       └── README.md              this file
└── data/                          bind-mount source, never committed
    ├── weights/
    │   ├── modnet_photographic_portrait_matting.onnx
    │   ├── hivision_modnet.onnx
    │   ├── rmbg-1.4.onnx
    │   ├── birefnet-v1-lite.onnx
    │   └── retinaface/
    │       └── retinaface-resnet50.onnx
    └── config/
        └── size_list_EN.csv       copied from the repo, bind-mounted read-only
```

All commands below assume:

```bash
cd /home/gurusandhu/hivision/HivisionIDPhotos/deploy/atlas
```

---

## Bring-up

Normal start (systemd is the supported path — it waits for Tailscale first):

```bash
sudo systemctl start hivision.service
```

Direct Compose, for debugging:

```bash
docker compose up -d
```

Check it came up healthy:

```bash
docker compose ps
```

Wait for `STATUS` to read `Up ... (healthy)`. The healthcheck has a 90-second
`start_period`; before that it reports `starting`, which is not a fault.

### Verify the exposure is Tailscale-only

Do this after any change to `.env`, the compose file, or a Docker upgrade.
Never infer exposure from reading config — measure it:

```bash
ss -tlnp | grep 7860
```

The only acceptable output binds `100.67.158.108`:

```
LISTEN 0 4096 100.67.158.108:7860 0.0.0.0:*
```

If you see `0.0.0.0:7860` or `*:7860`, **the service is on the LAN** — stop it
immediately (`docker compose down`) and fix `TAILSCALE_IP` in `.env`.

Negative check — these must all fail (connection refused):

```bash
curl -sS --max-time 5 http://10.0.0.188:7860/    # atlas's LAN address
curl -sS --max-time 5 http://127.0.0.1:7860/     # loopback
```

Positive check:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://100.67.158.108:7860/
```

---

## Tear-down

Stop, keep everything:

```bash
sudo systemctl stop hivision.service
```

Stop and remove containers (weights and presets are bind-mounts on the host, so
they survive):

```bash
docker compose down
```

Stop it coming back at boot:

```bash
sudo systemctl disable hivision.service
```

Remove the HTTPS front end:

```bash
sudo tailscale serve --https=9447 off
```

> **Never run `docker compose down -v` casually**, and never run
> `docker system prune -a` on atlas — six other stacks (`bigcapital`,
> `invoiceshelf`, `farmos`, `frappe_docker`, `ranchos-qa`, `infisical`) share
> this Docker daemon. Always scope commands to this project directory.

---

## Logs

```bash
docker compose logs -f hivision          # follow
docker compose logs --tail=200 hivision  # recent
journalctl -u hivision.service -n 50     # systemd unit (boot-time problems)
```

Container logs are capped at 3 × 10 MB (`json-file` driver) because atlas's `/`
runs around 82 % full.

**Boot-time failures** almost always show up in `journalctl`, not in the
container logs — the usual cause is the Tailscale address not being assigned
yet, which `ExecStartPre` waits up to 120 s for.

---

## Configuration

### Environment variables

Everything lives in `.env` (gitignored). `.env.example` documents each one.
The complete set the application actually reads:

| Variable | Effect |
|---|---|
| `TAILSCALE_IP` | Host-side bind address. **The only thing keeping this private.** |
| `HOST_PORT` | Host port, default `7860` |
| `DATA_DIR` | Absolute path to weights + presets |
| `DEFAULT_LANG` | UI language: `en`, `zh`, `ja`, `ko`. Anything else silently falls back to `zh`. Read at `demo/ui.py:31`. |
| `RUN_MODE` | Only `beast` is recognised — keeps models resident in RAM. Blank = normal. If you enable it, raise `mem_limit` to ~8g. |

After editing `.env`:

```bash
docker compose up -d
```

### If the Tailscale IP changes

It only changes if atlas is removed from the tailnet and re-added. When it does:

```bash
tailscale ip -4                                  # get the new address
sed -i "s/^TAILSCALE_IP=.*/TAILSCALE_IP=<new>/" .env
docker compose up -d
sudo tailscale serve --bg --https=9447 "http://<new>:7860"
ss -tlnp | grep 7860                             # confirm the new bind
```

`TAILSCALE_IP` is deliberately a variable rather than a literal in
`docker-compose.yml` so this is a one-line change. Compose **refuses to start**
if it is unset *or* empty, rather than defaulting to `0.0.0.0`.

### Size presets

The repo copy at `deploy/atlas/size_list_EN.csv` is the source of truth. It is
upstream's list plus two entries, moved to the top:

| Preset | Pixels (H×W) | Notes |
|---|---|---|
| `US passport 2x2in (600x600 @300DPI)` | 600 × 600 | 2 × 2 in at 300 DPI |
| `UK / Schengen 35x45mm (@300DPI)` | 531 × 413 | 45 × 35 mm at 300 DPI |

Three things to know:

- **Column order is `Name,Height,Width`** — height first.
- **No commas in names.** `demo/utils.py:15` does a strict three-column unpack
  (`size_name, h, w = row`); a comma in a name crashes the app at startup.
- **The first data row is the dropdown default** (`demo/ui.py:93` uses
  `choices[0]`), which is why the two presets above sit at the top.

The CSV is parsed at *import* time, so an edit needs a restart:

```bash
cp size_list_EN.csv /home/gurusandhu/hivision/data/config/size_list_EN.csv
docker compose restart hivision
```

Commit the repo copy so the change survives a reinstall.

> The mount target is `/app/demo/assets/size_list_EN.csv`, **not**
> `/app/assets/...`. `demo/config.py` looks like it reads the latter, but
> `demo/locales.py:19` passes `base_dir = <repo>/demo`. Re-check this path
> after any upstream merge.

### Model weights

Weights are **not** baked into the image and **never** committed — `.gitignore`
covers `*.onnx`, `*.mnn`, `*.pth`, `*.pt`, plus `data/`. They are bind-mounted
read-only from `$DATA_DIR`.

To (re-)download, with checksum verification:

```bash
./fetch-weights.sh
```

Idempotent — files whose SHA-256 already matches are left alone. A mismatch
never silently overwrites; it reports and exits non-zero.

> `app.py:11-27` raises at startup if `hivision/creator/weights` contains no
> `.onnx`/`.mnn` file, so a broken mount fails loudly rather than serving a
> half-working UI.

---

## Using it

Open **`https://atlas.tail270acc.ts.net:9447`** (or `http://100.67.158.108:7860`)
from any device on the tailnet.

**Print sheet / layout photo.** Upload a photo, then on the right-hand side set
**Paper size** (`6 inch`, `5 inch`, `A4`, `3R`, `4R`) before clicking the
generate button. The tiled sheet appears as the **"Layout photo"** output below
the standard and HD images, alongside two **template photo** variants. To get a
correctly-scaled print, set **"Set DPI"** to `300` (or use the custom slider) —
DPI is written into the file metadata at export, not derived from the preset.

---

## Updating from upstream

`master` tracks `Zeyi-Lin/HivisionIDPhotos` and stays clean; all deployment
work lives on `atlas-deploy`. `.github/workflows/upstream-sync.yml` runs weekly
(Mondays 04:17 UTC) and on manual dispatch, and opens a PR into `master` when
upstream moves. It never auto-merges.

1. Review and merge the `upstream-sync` PR on GitHub.
2. On your workstation:
   ```bash
   git checkout master && git pull
   git checkout atlas-deploy && git merge master
   git push origin atlas-deploy
   ```
3. On atlas:
   ```bash
   cd /home/gurusandhu/hivision/HivisionIDPhotos
   git pull
   cd deploy/atlas
   docker compose up -d --build
   docker compose ps
   ss -tlnp | grep 7860
   ```

After any upstream merge, re-check the three things upstream has moved before:
the size-CSV path, the two weights directories, and the `DEFAULT_LANG` lookup —
and re-test the workarounds in **Known upstream breakages** below.

To force a sync check now:

```bash
gh workflow run upstream-sync.yml --repo Gurpreetssandhu/HivisionIDPhotos
```

### Rolling back

The image is tagged `hivision-idphotos:atlas` and rebuilt in place, so roll back
via git and rebuild:

```bash
git log --oneline -10
git checkout <good-sha> -- .          # or: git reset --hard <good-sha>
docker compose up -d --build
```

---

## Restoring from backup

Nothing in this stack holds state worth backing up — no database, no volumes,
and generated photos are written to a per-request `tempfile.mkdtemp()` inside
the container and vanish with it. A full rebuild from the repo is the recovery
path.

```bash
# 1. Repo
mkdir -p /home/gurusandhu/hivision
cd /home/gurusandhu/hivision
git clone https://github.com/Gurpreetssandhu/HivisionIDPhotos.git
cd HivisionIDPhotos
git remote add upstream https://github.com/Zeyi-Lin/HivisionIDPhotos.git
git checkout atlas-deploy

# 2. Config
cd deploy/atlas
cp .env.example .env
# then edit .env: TAILSCALE_IP=$(tailscale ip -4), DATA_DIR=/home/gurusandhu/hivision/data

# 3. Data (weights ~450MB, re-downloaded from upstream releases)
mkdir -p /home/gurusandhu/hivision/data/config
./fetch-weights.sh
cp size_list_EN.csv /home/gurusandhu/hivision/data/config/size_list_EN.csv

# 4. Host units
sudo cp systemd/hivision.service /etc/systemd/system/hivision.service
sudo systemctl daemon-reload
sudo systemctl enable --now hivision.service

# 5. HTTPS front end
sudo tailscale serve --bg --https=9447 http://100.67.158.108:7860

# 6. Verify
docker compose ps
ss -tlnp | grep 7860
```

The only things worth keeping off-box are this repo (already on GitHub) and
`.env`, which contains no secrets — just an IP, a port, and two paths.

---

## Tailscale HTTPS front end

```bash
sudo tailscale serve --bg --https=9447 http://100.67.158.108:7860
```

This matches the pattern already used on atlas for `:9444` (frappe), `:9445`
(bigcapital) and `:9446` (farmOS), with `:443` taken by InvoiceShelf.

**It persists across reboots on its own** — `tailscale serve` config is stored
in `tailscaled`'s state directory and re-applied when the daemon starts. No
systemd unit is needed for it.

Inspect or remove:

```bash
tailscale serve status
sudo tailscale serve --https=9447 off
```

`--bg` keeps it tailnet-only. Do **not** use `tailscale funnel`, which would
publish it to the public internet.

---

## Adding secrets later (Infisical)

**This stack currently needs no secrets.** The only ones upstream supports are
the Face++ online face-detection credentials, deliberately not configured:
Face++ uploads every photo to Megvii's API, and the offline `retinaface-resnet50`
model is used instead. Nothing sensitive exists on disk for this service.

If you ever want Face++, the wiring (using the Infisical already running on
atlas at `http://100.67.158.108:8080`) is:

1. **Project + secrets.** In the Infisical UI, create project
   `hivision-idphotos`, and in the `prod` environment add `FACE_PLUS_API_KEY`
   and `FACE_PLUS_API_SECRET` from the Face++ console.

2. **Machine Identity.** Organization → Access Control → Identities → create
   `atlas-hivision` with **Universal Auth**. Grant it read-only access to
   `hivision-idphotos` / `prod`. Copy the Client ID and Client Secret.

3. **Credentials on atlas** — the only secret material on disk, never in git:
   ```bash
   sudo install -d -m 0700 -o root -g root /etc/infisical
   sudo install -m 0600 -o root -g root /dev/null /etc/infisical/hivision.env
   sudo tee /etc/infisical/hivision.env >/dev/null <<'EOF'
   INFISICAL_UNIVERSAL_AUTH_CLIENT_ID=...
   INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET=...
   EOF
   ```

4. **Infisical Agent, not `infisical run`.** The agent renders a templated
   `.env` and refreshes it unattended, so the stack survives a reboot with no
   human in the loop. Give it its own unit (`infisical-agent-hivision.service`)
   writing to `deploy/atlas/.env.secrets`, add `Requires=` and `After=` that
   unit to `hivision.service`, and add `env_file: .env.secrets` to the compose
   service. `.env.secrets` matches the existing `deploy/atlas/*.env` gitignore
   rule.

5. In the UI, switch **Face detection model** to `face++ (联网Online API)`.

---

## Known upstream breakages (and why deploy/atlas/ patches them)

Upstream **cannot be built or run from source** as of commit `5c191e2`. Both
fixes are confined to `deploy/atlas/` so `master` stays byte-identical to
upstream and merges never conflict. Re-test both after every upstream merge —
if upstream fixes one, delete the corresponding workaround.

### 1. `libgl1-mesa-glx` no longer exists (build fails)

```
E: Package 'libgl1-mesa-glx' has no installation candidate
... exit code: 100
```

`python:3.10-slim` now rebases on Debian trixie, which dropped that
transitional package. `libgl1` provides the opencv runtime instead.

**Workaround:** `deploy/atlas/Dockerfile` (used instead of the repo-root one).
This is also why Docker Hub's `linzeyi/hivision_idphotos:v1.3.1` (Jan 2025) is
still the newest published tag — nothing has built since.

### 2. gradio 6 removed `Blocks.launch(show_api=)` (container crash-loops)

```
TypeError: Blocks.launch() got an unexpected keyword argument 'show_api'
```

`requirements-app.txt` pins `gradio>=4.43.0` with no upper bound, so pip
resolves gradio 6.x while `app.py:73` still passes `show_api`.

**Workaround:** `deploy/atlas/constraints.txt` caps `gradio<6`, applied with
`pip install -c`. The running image resolves gradio 5.x, which logs a
deprecation warning about `show_api` — that warning is expected, not a fault.

To check whether upstream has fixed it:

```bash
docker compose exec hivision python3 -c "import gradio; print(gradio.__version__)"
```

### 3. `inference.py -t generate_layout_photos` crashes (CLI only — UI is fine)

```
ValueError: could not broadcast input array from shape (600,600,4) into shape (600,600,3)
```

`save_image_dpi_to_bytes` writes **PNG data into a `.jpg` filename**, so
feeding an `idphoto` output back into the CLI's layout mode reads 4 channels
that cannot broadcast into the 3-channel sheet canvas.

**Not patched, because it does not affect this deployment.** The UI never takes
this path — `demo/processor.py:372` passes an in-memory 3-channel array
straight to `generate_layout_image`. Verified: the UI produces a 1795x1205
sheet at 300 DPI. Only the standalone `inference.py` layout subcommand is
affected.

---

## Verified state at deployment

Recorded 2026-08-23, so a future reader can tell what changed.

| Check | Result |
|---|---|
| `ss -tlnp` for 7860 | `LISTEN 0 4096 100.67.158.108:7860 0.0.0.0:*` |
| From atlas, `http://10.0.0.188:7860` (LAN) | connection refused |
| From atlas, `http://127.0.0.1:7860` | connection refused |
| From atlas, `http://100.67.158.108:7860` | HTTP 200 |
| From another tailnet host, LAN IP | connection refused (port 22 open from the same host, so the path itself works) |
| From another tailnet host, Tailscale IP | HTTP 200 |
| Container | `Up (healthy)` |
| Six pre-existing stacks | untouched, uptimes unchanged |
| gitleaks over full history | 17 findings, **all** in upstream commit `47225c57e` (2023) in files upstream has since deleted; **0** in this branch's commits |

End-to-end test, US passport preset, modnet + retinaface, ~2.0 s total on CPU:

```
/tmp/tmpXXXXXXXX/<ts>_standard_300dpi.png   600x600    dpi=300
/tmp/tmpXXXXXXXX/<ts>_hd_300dpi.png         600x601    dpi=300
/tmp/tmpXXXXXXXX/<ts>_layout_300dpi.png     1795x1205  dpi=300   <- print sheet
```

Those paths are inside the container, under a per-request `tempfile.mkdtemp()`,
and vanish with it. Copies of the test run were left on the host at
`/home/gurusandhu/hivision/data/test-output/` — delete them whenever you like,
they are outside the git tree.

---

## Security posture

Re-run the scan after any upstream merge or base-image refresh:

```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  -v ~/.cache/trivy:/root/.cache/trivy \
  aquasec/trivy:latest image --scanners vuln \
  --severity CRITICAL,HIGH hivision-idphotos:atlas
```

### Where the CVE count went

| Stage | Total | HIGH | CRITICAL |
|---|---|---|---|
| Upstream Dockerfile as-is | 647 | 200 | 7 |
| after dropping unused `ffmpeg` | 272 | 76 | 5 |
| after build-time `apt-get upgrade` | 206 | 42 | 5 |
| after gradio 6 / pillow 12 / starlette 1.6 | **174** | **22** | **5** |

Of the 174 remaining, **171 have no fix available** in Debian trixie. The other
three are copies vendored inside pip (`pip/_vendor/`, listed in pip's
`vendor.txt`, which trivy parses) — not importable, used only by pip during
installation, unreachable from the application. **No runtime-reachable Python
dependency CVE remains.**

The five CRITICALs — `libglib2.0-0t64` (D-Bus XML introspection), `libxml2`
(XML parsing), `perl-base` x3 — are all unfixed upstream and none sit on a code
path this application uses. Nothing here parses XML, D-Bus, or runs perl.

### Why ffmpeg is not installed

Upstream installs it; this deployment does not. The code has **zero** video
references, and `opencv-python` links its own statically-bundled ffmpeg from the
wheel rather than the Debian package. Installing it added nine `libav*` packages
carrying 117 HIGH CVEs with no fixes, for no functionality.

If a future upstream version genuinely needs it, add it back — but re-measure.

### Why gradio is floored at 6.15 rather than capped below 6

Capping `gradio<6` is the obvious way to dodge the `show_api` crash, but gradio
5.x hard-pins `pillow<12.0` and `starlette<1.0`, which holds back 15 HIGH fixes.
The important one is **CVE-2026-42311 — arbitrary code execution via a malicious
PSD file**. Gradio hands every upload straight to PIL, and this service accepts
uploads from anyone on the tailnet, so that is a live path, not a theoretical
one.

`deploy/atlas/launch.py` adapts the one incompatible call instead. See its
header. If you ever need to roll back to gradio 5, you are knowingly
reintroducing those 15 CVEs.

### Application code

Audited at commit `5c191e2`:

- No `eval`, `exec`, `os.system`, `subprocess`, `pickle`, or `yaml.load` anywhere.
- Exactly one outbound network call — the Face++ POST at
  `hivision/creator/face_detector.py:105`. It is **inert**: no API key is
  configured, so the running service makes no outbound requests at all.
- Gradio launches with `share=False` and no `auth`, as intended for a
  Tailscale-only service. `launch.py` preserves upstream's `show_api=False` by
  translating it to `footer_links=["gradio","settings"]`, so the API docs page
  stays hidden.
- The container runs as **uid 10001**, not root, with `no-new-privileges:true`.
- Weights and the size-preset CSV are mounted **read-only**.

### Accepted risks

- **No authentication.** By design — Tailscale is the access control. Anyone on
  the tailnet can use the service and upload arbitrary images. If the tailnet
  ever includes devices you do not fully trust, revisit this.
- **Base image pinned by digest.** Reproducible, but it does not pick up new
  Debian security updates on its own. The build-time `apt-get upgrade`
  compensates on each rebuild; refresh the digest deliberately (command in
  `deploy/atlas/Dockerfile`).
- **Upstream history contains leaked credentials.** gitleaks finds 17, all in
  upstream commit `47225c57e` (2023) in files upstream later deleted. They came
  with the fork. Not rewritten, because history surgery on `master` would break
  the trivial-merge property.

---

## Constraints this deployment respects

- No firewall changes, no public ingress, no Cloudflare Tunnel — Tailscale only.
- No `tailscale funnel`.
- Nothing bound to `0.0.0.0`; Compose fails closed if `TAILSCALE_IP` is unset or empty.
- No secrets, weights, generated photos or rendered env files in git.
- The six unrelated Compose stacks on atlas are never touched.
