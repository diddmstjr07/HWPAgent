const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('adminBridge', {
  getConfig: () => ipcRenderer.invoke('admin:get-config'),
  login: (payload) => ipcRenderer.invoke('admin:login', payload),
  quit: () => ipcRenderer.invoke('admin:quit')
});
