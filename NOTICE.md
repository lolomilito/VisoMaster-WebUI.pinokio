# Notice

This repository bundles:

- `src/desktop/` – the [VisoMaster](https://github.com/visomaster/VisoMaster) source code (only change: automatic CPU fallback when CUDA/TensorRT are not available, in `app/processors/models_processor.py`).
- `src/webui/` – a modified copy of VisoMaster in which the PySide6 desktop interface was replaced by a browser-based WebUI (Flask + vanilla JS) living in `app/web/`.

VisoMaster is licensed under the GNU General Public License v3.0 (see `LICENSE`). All modifications and the Pinokio scripts in this repository are released under the same license. Credit for VisoMaster goes to its original authors.
Model files are not included; they are downloaded by VisoMaster's own `download_models.py` during installation.
