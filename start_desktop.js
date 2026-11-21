module.exports = {
  run: [
    {
      method: "shell.run",
      params: {
        path: "desktop",
        conda: { path: "env" },
        env: { KMP_DUPLICATE_LIB_OK: "TRUE" },
        message: ["python main.py"]
      }
    }
  ]
}
