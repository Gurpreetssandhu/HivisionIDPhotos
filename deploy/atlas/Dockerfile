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
# ffmpeg: pulled in by upstream's Dockerfile; kept for parity.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-app.txt ./
COPY deploy/atlas/constraints.txt ./constraints.txt
# -c applies upper bounds upstream omitted, without editing their requirements
# files. See constraints.txt for why each pin is there.
RUN pip install --no-cache-dir -c constraints.txt -r requirements.txt -r requirements-app.txt

COPY . .

# Run unprivileged. This service has no authentication layer - Tailscale is the
# only access control - so it should not also be root inside its namespace.
# Gradio needs a writable HOME and temp dir; both are set explicitly rather
# than left to default to a path this user cannot write.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin hivision \
    && mkdir -p /var/tmp/gradio \
    && chown -R hivision:hivision /app /var/tmp/gradio

ENV HOME=/home/hivision \
    GRADIO_TEMP_DIR=/var/tmp/gradio \
    MPLCONFIGDIR=/var/tmp/gradio \
    PYTHONUNBUFFERED=1

USER hivision

EXPOSE 7860

CMD ["python3", "-u", "app.py", "--host", "0.0.0.0", "--port", "7860"]
