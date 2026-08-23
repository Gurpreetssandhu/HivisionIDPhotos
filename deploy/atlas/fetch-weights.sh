#!/usr/bin/env bash
#
# Download HivisionIDPhotos model weights into $DATA_DIR, outside the git tree.
#
# Upstream ships scripts/download_model.py, but it writes into the repo working
# tree (hivision/creator/weights) and has no integrity checking. This puts the
# files where the bind-mounts expect them and verifies them.
#
# Usage:  ./fetch-weights.sh [DATA_DIR]
#         DATA_DIR defaults to the value in ./.env
#
# Idempotent: a file whose checksum already matches is left alone.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

data_dir="${1:-}"
if [[ -z "$data_dir" ]]; then
  if [[ -f "$here/.env" ]]; then
    data_dir="$(grep -E '^DATA_DIR=' "$here/.env" | tail -1 | cut -d= -f2-)"
  fi
fi
if [[ -z "$data_dir" ]]; then
  echo "error: no DATA_DIR. Pass it as \$1 or set it in $here/.env" >&2
  exit 1
fi

matting_dir="$data_dir/weights"
retina_dir="$data_dir/weights/retinaface"
mkdir -p "$matting_dir" "$retina_dir"

# name|destination dir|url|sha256   ("-" = unpinned, prints the hash instead)
#
# Note the two renames: upstream publishes rmbg-1.4 as "model.onnx" and
# birefnet-v1-lite as "BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx", but
# hivision/creator/choose_handler.py looks them up by the names below.
models=(
  "modnet_photographic_portrait_matting.onnx|$matting_dir|https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/modnet_photographic_portrait_matting.onnx|SHA_MODNET_PHOTO"
  "hivision_modnet.onnx|$matting_dir|https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/hivision_modnet.onnx|SHA_HIVISION_MODNET"
  "rmbg-1.4.onnx|$matting_dir|https://huggingface.co/briaai/RMBG-1.4/resolve/main/onnx/model.onnx?download=true|SHA_RMBG"
  "birefnet-v1-lite.onnx|$matting_dir|https://github.com/ZhengPeng7/BiRefNet/releases/download/v1/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx|SHA_BIREFNET"
  "retinaface-resnet50.onnx|$retina_dir|https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/retinaface-resnet50.onnx|SHA_RETINAFACE"
)

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

rc=0
for entry in "${models[@]}"; do
  IFS='|' read -r name dest url want <<<"$entry"
  path="$dest/$name"

  if [[ -f "$path" ]]; then
    have="$(sha_of "$path")"
    if [[ "$want" == "$have" ]]; then
      echo "ok       $name (cached, sha256 verified)"
      continue
    fi
    if [[ "$want" == SHA_* ]]; then
      echo "present  $name (unpinned in this script) sha256=$have"
      continue
    fi
    echo "MISMATCH $name" >&2
    echo "         expected $want" >&2
    echo "         got      $have" >&2
    echo "         refusing to overwrite; delete it by hand to re-download" >&2
    rc=1
    continue
  fi

  echo "fetch    $name"
  tmp="$path.partial"
  if ! curl -fSL --retry 3 --retry-delay 2 --connect-timeout 20 -o "$tmp" "$url"; then
    echo "FAILED   $name - download error from $url" >&2
    rm -f "$tmp"
    rc=1
    continue
  fi

  have="$(sha_of "$tmp")"
  if [[ "$want" != SHA_* && "$want" != "$have" ]]; then
    echo "MISMATCH $name after download" >&2
    echo "         expected $want" >&2
    echo "         got      $have" >&2
    rm -f "$tmp"
    rc=1
    continue
  fi

  # ONNX files start with a protobuf field header; a captive-portal HTML page
  # or an S3 error document does not. Cheap guard against silent corruption.
  if [[ "$(head -c 2 "$tmp" | xxd -p)" == "3c68" ]]; then
    echo "FAILED   $name - got HTML, not a model (bad URL or redirect?)" >&2
    rm -f "$tmp"
    rc=1
    continue
  fi

  mv "$tmp" "$path"
  echo "         sha256=$have  size=$(du -h "$path" | cut -f1)"
done

echo
echo "--- $matting_dir ---"
ls -la "$matting_dir"
echo "--- $retina_dir ---"
ls -la "$retina_dir"

exit "$rc"
