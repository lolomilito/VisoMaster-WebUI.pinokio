module.exports = {
  daemon: true,
  run: [
    {
      method: "shell.run",
      params: {
        path: "webui",
        conda: { path: "env" },
        env: { KMP_DUPLICATE_LIB_OK: "TRUE", PYTHONUNBUFFERED: "1" },
        message: ["python main.py --host 0.0.0.0 --port {{port}}"],
        on: [{ event: "/Running on (http:\\/\\/\\S+)/", done: true }]
      }
    },
    { method: "local.set", params: { url: "{{input.event[1]}}" } }
  ]
}
