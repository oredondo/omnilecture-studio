# Initialization for the notes generation pipeline package.
import os
import sys
import glob

_proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_venv_sites = glob.glob(os.path.join(_proj_root, ".venv", "lib", "python3.*", "site-packages"))
for _sp in _venv_sites:
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

_venv_bin = os.path.join(_proj_root, ".venv", "bin")
if os.path.isdir(_venv_bin) and _venv_bin not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = _venv_bin + os.pathsep + os.environ.get("PATH", "")

