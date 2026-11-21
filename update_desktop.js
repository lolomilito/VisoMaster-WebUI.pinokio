// No GitHub needed: re-copies the bundled sources (src/desktop) and reinstalls the requirements.
module.exports = {
  run: [
    { method: "shell.run", params: { path: ".", conda: { path: "desktop/env" }, message: ["python copy_src.py desktop"] } },
    { method: "shell.run", params: { path: "desktop", conda: { path: "env" }, message: ["pip install -r {{gpu === 'nvidia' ? 'requirements_cu124.txt' : '../requirements_cpu.txt'}}"] } }
  ]
}
