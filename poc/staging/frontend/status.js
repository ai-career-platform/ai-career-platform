async function getJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error("Health request failed");
  return response.json();
}

async function updateStatus() {
  const [health, version, database] = await Promise.allSettled([
    getJson("/api/health"),
    getJson("/api/version"),
    getJson("/api/health/db")
  ]);
  const backendOk = health.status === "fulfilled" && health.value.status === "ok";
  const databaseOk = database.status === "fulfilled" && database.value.status === "ok";
  document.getElementById("backend").textContent = backendOk ? "Connected" : "Unavailable";
  document.getElementById("version").textContent =
    version.status === "fulfilled" ? version.value.version : "Unavailable";
  document.getElementById("status").textContent =
    backendOk && databaseOk ? "Operational" : "Degraded";
}
updateStatus();
