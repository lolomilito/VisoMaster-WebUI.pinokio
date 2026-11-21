module.exports = {
  run: [
    { method: "fs.rm", params: { path: "webui/env" } },
    { method: "fs.rm", params: { path: "webui/.install_ok" } }
  ]
}
