# syntax=docker/dockerfile:1
#
# HivisionIDPhotos - atlas deployment image.
#
# WHY THIS EXISTS INSTEAD OF THE REPO-ROOT Dockerfile
# ---------------------------------------------------
# Upstream's Dockerfile installs `libgl1-mesa-glx`. Debian dropped that
# transitional package in trixie, and python:3.10-slim now rebases on trixie,
# so the upstream Dockerfile fails to build:
#
#     E: Package 'libgl1-mesa-glx' has no installation candidate
#
# The runtime it used to pull in is provided by `libgl1`. (This is also why
# Docker Hub's linzeyi/hivision_idphotos:v1.3.1 is still the newest tag - it
# was built in Jan 2025, back when the base was bookworm.)
#
# Keeping the fix in deploy/atlas/ rather than patching the repo-root
# Dockerfile means `master` stays byte-identical to upstream and merges from
# upstream never conflict. If upstream fixes this themselves, delete this file
# and point docker-compose.yml back at the root Dockerfile.

# Pinned by digest so rebuilds are reproducible - without this, a base-image
# refresh can change the runtime under a stack nobody is watching.
# To refresh deliberately:
#     docker pull python:3.10-slim && docker inspect --format='{{index .RepoDigests 0}}' python:3.10-slim
FROM python:3.10-slim@sha256:a78e4529630cfe8c5199cafd6e0c28ee1579a13f86274396d8b6b2d80367aa3a

# libgl1 + libglib2.0-0: opencv-python's runtime deps.
#
# ffmpeg is DELIBERATELY NOT INSTALLED, unlike upstream's Dockerfile. The code
# has zero video/ffmpeg references (no VideoCapture, no imageio, no moviepy),
# and opencv-python's wheel links its own statically-bundled ffmpeg rather than
# the Debian package. Installing it pulled in nine libav*/ffmpeg packages
# carrying 117 HIGH CVEs with no fix available upstream, for no functionality.
# Verified after removal: cv2 imports, imread/imwrite work, and the full
# matting -> face-detect -> layout pipeline produces identical output.
# `apt-get upgrade` is normally an anti-pattern in a Dockerfile, but the base
# is pinned by digest above, so without it the image is frozen at whatever
# Debian shipped on that build date. It picks up published security updates -
# at the time of writing, the util-linux family (bsdutils, libblkid1, libmount1,
# libuuid1, login, mount, ...) carrying 36 HIGH CVEs fixed in 2.41.5-0+deb13u1.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The base image ships pip 23.0.1 / setuptools 70.3.0 / wheel 0.45.1, all of
# which carry advisories of their own (incl. the vendored jaraco.context).
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt requirements-app.txt ./
COPY deploy/atlas/constraints.txt ./constraints.txt
COPY deploy/atlas/requirements-deploy.txt ./requirements-deploy.txt
# -c applies upper bounds upstream omitted, without editing their requirements
# files. See constraints.txt for why each pin is there, and
# requirements-deploy.txt for what this deployment adds (HEIC support).
RUN pip install --no-cache-dir -c constraints.txt \
        -r requirements.txt \
        -r requirements-app.txt \
        -r requirements-deploy.txt

COPY . .

# Run unprivileged. This service has no authentication layer - Tailscale is the
# only access control - so it should not also be root inside its namespace.
# Gradio needs a writable HOME and temp dir; both are set explicitly rather
# than left to default to a path this user cannot write.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin hivision \
    && chown -R hivision:hivision /app

# Both temp dirs sit under /tmp, which docker-compose.yml backs with tmpfs, so
# generated photos and cached uploads live in RAM and never reach atlas's disk.
# launch.py creates them at startup, since tmpfs mounts over anything baked here.
ENV HOME=/home/hivision \
    GRADIO_TEMP_DIR=/tmp/gradio \
    MPLCONFIGDIR=/tmp/mpl \
    PYTHONUNBUFFERED=1

USER hivision

EXPOSE 7860

# deploy/atlas/launch.py, not app.py: gradio 6 removed the show_api kwarg that
# upstream still passes. See that file's header.
CMD ["python3", "-u", "deploy/atlas/launch.py", "--host", "0.0.0.0", "--port", "7860"]
