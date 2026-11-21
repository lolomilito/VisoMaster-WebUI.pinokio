module.exports = {
  run: [
    { method: "fs.rm", params: { path: "desktop/env" } },
    { method: "fs.rm", params: { path: "desktop/.install_ok" } }
  ]
}
