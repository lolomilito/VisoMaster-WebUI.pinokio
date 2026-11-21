module.exports = {
  run: [
    {
      method: "shell.run",
      params: {
        path: "webui",
        conda: { path: "env", python: "python=3.10.13" },
        message: [
          "conda install -y -c nvidia/label/cuda-12.4.1 cuda-runtime",
          "conda install -y -c conda-forge cudnn",
          "conda install -y scikit-image"
        ]
      }
    },
    {
      method: "shell.run",
      params: { path: ".", conda: { path: "webui/env" }, message: ["python copy_src.py webui"] }
    },
    {
      method: "shell.run",
      params: { path: "webui", conda: { path: "env" }, message: ["pip install -r requirements_cu124.txt"] }
    },
    {
      method: "shell.run",
      params: { path: ".", conda: { path: "webui/env" }, message: ["python link_models.py webui"] }
    },
    {
      method: "shell.run",
      params: { path: "webui", conda: { path: "env" }, message: ["python download_models.py"] }
    },
    {
      when: "{{platform === 'win32'}}",
      method: "fs.download",
      params: {
        uri: "https://github.com/visomaster/visomaster-assets/releases/download/v0.1.0_dp/ffmpeg.exe",
        dir: "webui/dependencies"
      }
    },
    {
      when: "{{platform !== 'win32'}}",
      method: "shell.run",
      params: { path: "webui", conda: { path: "env" }, message: ["conda install -y -c conda-forge ffmpeg"] }
    },
    { method: "fs.write", params: { path: "webui/.install_ok", text: "ok" } },
    { method: "notify", params: { html: "Instalado. Vuelve al menú y pulsa Iniciar." } }
  ]
}
