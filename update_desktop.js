// Sin GitHub: vuelve a copiar el código incluido en src/desktop y reinstala dependencias.
module.exports = {
  run: [
    { method: "shell.run", params: { path: ".", conda: { path: "desktop/env" }, message: ["python copy_src.py desktop"] } },
    { method: "shell.run", params: { path: "desktop", conda: { path: "env" }, message: ["pip install -r requirements_cu124.txt"] } }
  ]
}
