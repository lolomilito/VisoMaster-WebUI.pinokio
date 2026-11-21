module.exports = {
  version: "3.0",
  title: "VisoMaster + WebUI",
  description: "VisoMaster (escritorio) y VisoMaster WebUI (navegador), instalados por separado y compartiendo la carpeta de modelos. Requiere GPU NVIDIA.",
  icon: "icon.png",
  menu: async (kernel, info) => {
    const apps = [
      { key: "desktop", name: "VisoMaster", icon: "fa-solid fa-desktop" },
      { key: "webui", name: "VisoMaster WebUI", icon: "fa-solid fa-globe" }
    ]
    const items = []
    for (const a of apps) {
      const install = `install_${a.key}.js`, start = `start_${a.key}.js`, update = `update_${a.key}.js`, reset = `reset_${a.key}.js`
      const complete = info.exists(`${a.key}/.install_ok`)
      const partial = !complete && info.exists(`${a.key}/env`) && info.exists(`${a.key}/main.py`)
      if (info.running(install)) {
        items.push({ icon: "fa-solid fa-plug", text: `${a.name}: instalando`, href: install })
      } else if (!complete && !partial) {
        items.push({ icon: "fa-solid fa-plug", text: `Instalar ${a.name}`, href: install })
      } else if (info.running(start)) {
        const local = info.local(start)
        if (a.key === "webui" && local && local.url) {
          items.push({ icon: a.icon, text: `Abrir ${a.name}`, href: local.url, target: "_blank" })
        }
        items.push({ icon: "fa-solid fa-terminal", text: `${a.name}: en ejecución (terminal / detener)`, href: start })
      } else if (info.running(update)) {
        items.push({ icon: "fa-solid fa-terminal", text: `${a.name}: actualizando`, href: update })
      } else if (info.running(reset)) {
        items.push({ icon: "fa-solid fa-terminal", text: `${a.name}: reseteando`, href: reset })
      } else {
        items.push({ icon: "fa-solid fa-power-off", text: `Iniciar ${a.name}`, href: start })
        items.push({ icon: "fa-solid fa-rotate", text: `Actualizar ${a.name}`, href: update })
        items.push({ icon: "fa-solid fa-wrench", text: partial ? `Terminar instalación de ${a.name}` : `Reinstalar ${a.name}`, href: install })
        items.push({ icon: "fa-regular fa-circle-xmark", text: `Reset entorno ${a.name}`, href: reset })
      }
    }
    if (items.length > 0) items[0].default = false
    return items
  }
}
