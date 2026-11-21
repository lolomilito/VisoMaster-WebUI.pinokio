// desktop: installs the app. NVIDIA GPUs use CUDA 12.4 + TensorRT; any other machine
// (AMD, Intel, Apple Silicon, no GPU) runs on the CPU provider.
module.exports = {
  run: [
    {
      when: "{{gpu === 'nvidia'}}",
      method: "shell.run",
      params: {
        path: "desktop",
        conda: { path: "env", python: "python=3.10.13" },
        message: [
          "conda install -y -c nvidia/label/cuda-12.4.1 cuda-runtime",
          "conda install -y -c conda-forge cudnn",
          "conda install -y scikit-image"
        ]
      }
    },
    {
      when: "{{gpu !== 'nvidia'}}",
      method: "shell.run",
      params: {
        path: "desktop",
        conda: { path: "env", python: "python=3.10.13" },
        message: ["conda install -y scikit-image"]
      }
    },
    {
      method: "shell.run",
      params: { path: ".", conda: { path: "desktop/env" }, message: ["python copy_src.py desktop"] }
    },
    {
      when: "{{gpu === 'nvidia'}}",
      method: "shell.run",
      params: { path: "desktop", conda: { path: "env" }, message: ["pip install -r requirements_cu124.txt"] }
    },
    {
      when: "{{gpu !== 'nvidia'}}",
      method: "shell.run",
      params: { path: "desktop", conda: { path: "env" }, message: ["pip install -r ../requirements_cpu.txt", "pip install PySide6==6.8.2.1 pyqt-toast-notification==1.3.2 qdarkstyle pyqtdarktheme"] }
    },
    {
      method: "shell.run",
      params: { path: ".", conda: { path: "desktop/env" }, message: ["python link_models.py desktop"] }
    },
    {
      method: "shell.run",
      params: { path: "desktop", conda: { path: "env" }, message: ["python download_models.py"] }
    },
    {
      when: "{{platform === 'win32'}}",
      method: "fs.download",
      params: {
        uri: "https://github.com/visomaster/visomaster-assets/releases/download/v0.1.0_dp/ffmpeg.exe",
        dir: "desktop/dependencies"
      }
    },
    {
      when: "{{platform !== 'win32'}}",
      method: "shell.run",
      params: { path: "desktop", conda: { path: "env" }, message: ["conda install -y -c conda-forge ffmpeg"] }
    },
    { method: "fs.write", params: { path: "desktop/.install_ok", text: "ok" } },
    { method: "notify", params: { html: "Installed. Go back to the menu and press Start." } }
  ]
}
