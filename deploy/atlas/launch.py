"""Deployment entrypoint for atlas: gradio 6 compatibility shim, then upstream app.py.

WHY THIS EXISTS
---------------
Upstream's app.py:73 calls `demo.launch(..., show_api=False)`. gradio removed
the `show_api` argument in 6.0, so running upstream unmodified against gradio 6
crash-loops with:

    TypeError: Blocks.launch() got an unexpected keyword argument 'show_api'

Pinning `gradio<6` avoids the crash but is expensive: gradio 5.x hard-pins
`pillow<12.0` and `starlette<1.0`, which blocks 15 HIGH CVE fixes - including
CVE-2026-42311, arbitrary code execution via a malicious PSD file. That matters
here because this app's whole purpose is processing uploaded images.

So instead of capping gradio, this wrapper adapts the one incompatible call and
runs upstream's app.py untouched via runpy. Keeping the change here rather than
editing app.py means `master` stays byte-identical to upstream and merges from
upstream never conflict.

Everything else in the codebase was verified compatible with gradio 6.25:
create_ui() constructs, and the matting -> face-detect -> layout pipeline
produces identical output.

WHEN TO DELETE THIS
-------------------
Once upstream adapts app.py to the gradio 6 API, drop this file and point
docker-compose.yml's `command:` back at `app.py` directly.
"""

import inspect
import os
import runpy
import sys

_APP_DIR = "/app"
_APP = os.path.join(_APP_DIR, "app.py")

# Running this file directly puts /app/deploy/atlas on sys.path[0], not /app,
# so upstream's `from demo.processor import ...` would fail with
# ModuleNotFoundError. Put the app root first before importing anything of
# upstream's, and chdir so relative asset paths resolve the way app.py expects.
if sys.path[0] != _APP_DIR:
    sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)

import gradio as gr  # noqa: E402  (must follow the sys.path fix above)

_original_launch = gr.Blocks.launch
_launch_params = inspect.signature(_original_launch).parameters


def _launch(self, *args, **kwargs):
    if "show_api" in kwargs and "show_api" not in _launch_params:
        show_api = kwargs.pop("show_api")
        # gradio's own deprecation notice: to replicate show_api=False in 6.x,
        # use footer_links=["gradio", "settings"] - i.e. every footer link
        # except the API one. Translate rather than silently drop, so the API
        # docs page stays hidden the way upstream intended.
        if not show_api and "footer_links" in _launch_params:
            kwargs.setdefault("footer_links", ["gradio", "settings"])
    return _original_launch(self, *args, **kwargs)


gr.Blocks.launch = _launch

# /tmp is a tmpfs mounted by docker-compose.yml, so it starts empty on every
# container start and anything baked into the image at these paths is masked.
# Create the temp dirs here rather than in the Dockerfile, where they would be
# hidden by the mount. Keeping them on the tmpfs is what guarantees generated
# photos are never written to atlas's disk and are gone after a restart.
for _d in (os.environ.get("GRADIO_TEMP_DIR"), os.environ.get("MPLCONFIGDIR")):
    if _d:
        os.makedirs(_d, mode=0o700, exist_ok=True)

# Teach Pillow to decode HEIC/HEIF before any upload is handled. iPhones shoot
# HEIC by default and often present it with a .jpeg extension, which Pillow
# cannot open - gradio then fails at preprocess and the UI shows a generic
# error when Start is clicked. Registering the opener here rather than patching
# upstream keeps app.py untouched.
#
# Guarded: if the package is ever missing, the service still starts and handles
# JPEG/PNG normally, with a loud line in the logs rather than a crash-loop.
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    print("[launch] pillow-heif %s registered: HEIC/HEIF uploads supported"
          % pillow_heif.__version__, flush=True)
except Exception as exc:  # noqa: BLE001 - never block startup over this
    print("[launch] WARNING: pillow-heif unavailable (%s). HEIC uploads - "
          "including iPhone photos named .jpeg - will fail to decode." % exc,
          flush=True)

# Upstream bug: demo/processor.py's _create_error_response() returns 7 values
# while demo/ui.py wires 8 outputs, and it puts the message in the GALLERY slot
# rather than the notification textbox. So any custom-size validation failure
# makes gradio raise
#
#   ValueError: A function (process) didn't return enough output values
#               (needed: 8, returned: 7)
#
# and the UI shows a bare red "Error" badge instead of the actual reason - e.g.
# "The width should not be greater than the length...". Users are left guessing.
#
# _create_response() returns, in order: 5 images, gallery, accordion,
# notification. Mirror that exactly so the message lands where it belongs.
try:
    import gradio as _gr
    from demo.locales import LOCALES as _LOCALES
    from demo.processor import IDPhotoProcessor as _Processor

    def _create_error_response(self, language, message=None):
        msg = message or _LOCALES["size_mode"][language]["custom_size_eror"]
        return [_gr.update(value=None) for _ in range(5)] + [
            None,                                    # template gallery
            _gr.update(visible=False),               # matting accordion
            # label set explicitly: the success path relabels this same box
            _gr.update(value=msg, visible=True, label="notification"),
        ]

    _Processor._create_error_response = _create_error_response
    print("[launch] patched _create_error_response: validation messages now "
          "reach the notification box instead of raising", flush=True)
except Exception as exc:  # noqa: BLE001 - never block startup over this
    print("[launch] WARNING: could not patch _create_error_response (%s). "
          "Custom-size validation errors will show as a bare 'Error'." % exc,
          flush=True)

# Show the size of each generated photo once processing finishes.
#
# demo/ui.py:376 defines a `notification` gr.Text that is wired as the 8th
# output but only ever used for errors - on success upstream sends
# gr.update(visible=False) and the box stays hidden. Reuse it to report the
# pixel dimensions, format and file size of what was produced, which is what
# you need before uploading to a portal with a hard KB limit (Passport Seva
# caps photographs at 250 KB).
#
# Patching _create_response here rather than editing demo/processor.py keeps
# upstream files untouched so merges stay trivial.
try:
    import gradio as _gr2
    from demo.processor import IDPhotoProcessor as _Proc2
    from PIL import Image as _PILImage

    def _describe(label, obj):
        """Return 'Label: 630 x 810 px | JPEG | 240.0 KB (245,760 bytes)' or None."""
        path = obj.get("value") if isinstance(obj, dict) else obj
        if not isinstance(path, str) or not os.path.isfile(path):
            return None
        try:
            nbytes = os.path.getsize(path)
        except OSError:
            return None
        dims = fmt = "?"
        try:
            with _PILImage.open(path) as im:
                dims = "%d x %d px" % (im.size[0], im.size[1])
                fmt = im.format or "?"
        except Exception:  # noqa: BLE001 - a description must never break output
            pass
        return "%s: %s | %s | %.1f KB (%s bytes)" % (
            label, dims, fmt, nbytes / 1024.0, format(nbytes, ",d"))

    def _create_response(self, result_image_standard, result_image_hd,
                         result_image_standard_png, result_image_hd_png,
                         result_layout_image_gr, result_image_template_gr,
                         result_image_template_accordion_gr):
        lines = [d for d in (
            _describe("Standard", result_image_standard),
            _describe("HD", result_image_hd),
            _describe("Layout", result_layout_image_gr),
        ) if d]

        if lines:
            # demo/ui.py:376 declares this as a 1-line gr.Text, so grow it to
            # fit however many lines we produced - otherwise the size report is
            # clipped to the first entry.
            note = _gr2.update(value="\n".join(lines), visible=True,
                               label="Output size",
                               lines=len(lines), max_lines=len(lines))
        else:
            note = _gr2.update(visible=False)

        return [
            result_image_standard,
            result_image_hd,
            result_image_standard_png,
            result_image_hd_png,
            result_layout_image_gr,
            result_image_template_gr,
            result_image_template_accordion_gr,
            note,
        ]

    _Proc2._create_response = _create_response
    print("[launch] patched _create_response: output size shown after processing",
          flush=True)
except Exception as exc:  # noqa: BLE001 - never block startup over this
    print("[launch] WARNING: could not patch _create_response (%s). "
          "Output sizes will not be displayed." % exc, flush=True)

# run_name="__main__" so app.py's `if __name__ == "__main__"` block executes,
# and run_path sets __file__ to _APP so app.py's root_dir resolves to /app.
runpy.run_path(_APP, run_name="__main__")
