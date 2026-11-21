# VisoMaster + WebUI for Pinokio

One-click [Pinokio](https://pinokio.computer) launcher that installs **two independent apps** and shares the model files between them:

| App | What it is |
| --- | --- |
| **VisoMaster** | The original desktop (Qt) application, unmodified. |
| **VisoMaster WebUI** | The same face-swap engine with a new browser interface. Run it on the GPU machine and use it from any PC on your network. |

Requires an NVIDIA GPU (CUDA 12.4). Windows is the main target; Linux should work too.

## Install

1. In Pinokio, open **Download** and paste this repository's URL (or clone it into `pinokio/api/`).
2. Open **VisoMaster + WebUI** and press **Install VisoMaster** and/or **Install VisoMaster WebUI**. They are separate; install the one(s) you want.
3. Press **Start …**. Nothing starts automatically.

Everything needed from this repo is bundled (`src/`); internet is only used for Conda/pip packages and the model download.
`model_assets` is stored once in `shared/model_assets` and linked into both apps.

## WebUI

- Pinokio shows an **Open VisoMaster WebUI** entry once it is running. It listens on `0.0.0.0`, so from another PC open `http://<server-ip>:<port>`.
- Load media and faces from the server's disk (📁 / 📄) or from the PC running the browser (💻: files or folder).
- Saved frames and recordings are created on the server; enable **Download to this PC** (on by default for remote browsers) or use **Outputs…** to download them.
- Same keyboard shortcuts as the desktop app (Space, R, A/D, Z/C, S, V/B, markers F / Alt+F / W / Q).
- Workspaces and parameter files are compatible with the desktop version.
- Warning: the WebUI has no login by default. Use it on a trusted network, or start it with `--token SECRET` (see `src/webui/README.md`).

## Without Pinokio (Windows, after installing)

`Start_Desktop.bat` – desktop app · `Start_WebUI.bat` – WebUI on port 7860.

## Update / reset

- **Update** re-copies the bundled sources and reinstalls the requirements (user data and models are kept).
- **Reset** deletes only the app's Conda env.

## License

GPL-3.0, same as VisoMaster. See `LICENSE` and `NOTICE.md`.
