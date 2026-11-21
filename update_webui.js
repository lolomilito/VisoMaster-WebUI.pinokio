// No GitHub needed: re-copies the bundled sources (src/webui) and reinstalls the requirements.
module.exports = {
  run: [
    { method: "shell.run", params: { path: ".", conda: { path: "webui/env" }, message: ["python copy_src.py webui"] } },
    { method: "shell.run", params: { path: "webui", conda: { path: "env" }, message: ["pip install -r {{gpu === 'nvidia' ? 'requirements_cu124.txt' : '../requirements_cpu.txt'}}"] } }
  ]
}
