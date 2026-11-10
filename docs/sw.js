// Minimal service worker for the installable wrapper.
// It caches nothing: the app needs a live connection to Streamlit Cloud anyway.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {
  // Let the browser handle every request normally.
});
