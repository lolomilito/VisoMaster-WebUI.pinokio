// Sin GitHub: vuelve a copiar el código incluido en src/webui y reinstala dependencias.
module.exports = {
  run: [
    { method: "shell.run", params: { path: ".", conda: { path: "webui/env" }, message: ["python copy_src.py webui"] } },
    { method: "shell.run", params: { path: "webui", conda: { path: "env" }, message: ["pip install -r requirements_cu124.txt"] } }
  ]
}
