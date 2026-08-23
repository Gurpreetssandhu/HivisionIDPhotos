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

# run_name="__main__" so app.py's `if __name__ == "__main__"` block executes,
# and run_path sets __file__ to _APP so app.py's root_dir resolves to /app.
runpy.run_path(_APP, run_name="__main__")
