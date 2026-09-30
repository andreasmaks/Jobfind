import { readSnapshot } from "/assets/offline.js?v=2";

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options });
  } catch (error) {
    error.networkFailure = true;
    throw error;
  }
  if (response.status === 401) {
    window.location.href = "/login?next=/";
    const error = new Error("Anmeldung erforderlich");
    error.authRequired = true;
    throw error;
  }
  const body = await response.json();
  if (!response.ok || !body.ok) {
    const error = new Error(body.error || "Anfrage fehlgeschlagen");
    error.httpStatus = response.status;
    throw error;
  }
  return body;
}

export async function loadPortal() {
  const results = await Promise.allSettled([
    request("/api/jobs"), request("/api/meta"), request("/api/csrf"),
  ]);
  const authError = results.find((result) => result.status === "rejected" && result.reason.authRequired);
  if (authError) throw authError.reason;
  if (results.every((result) => result.status === "fulfilled")) {
    const [jobs, meta, csrf] = results.map((result) => result.value);
    return { jobs: jobs.jobs, meta, csrf: csrf.token, offline: false };
  }
  const snapshot = await readSnapshot().catch(() => null);
  if (!snapshot) throw results.find((result) => result.status === "rejected").reason;
  return { jobs: snapshot.jobs, meta: snapshot.meta, csrf: "", offline: true, savedAt: snapshot.savedAt };
}

export async function updateStatus(id, status, csrf) {
  return request(`/api/jobs/${encodeURIComponent(id)}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: JSON.stringify({ status }),
  });
}

export async function changeDeletion(id, deleted, csrf, feedback = {}) {
  return request(`/api/jobs/${encodeURIComponent(id)}/${deleted ? "delete" : "restore"}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: JSON.stringify(feedback),
  });
}

export async function updateLike(id, liked, csrf) {
  return request(`/api/jobs/${encodeURIComponent(id)}/${liked ? "like" : "unlike"}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: JSON.stringify({}),
  });
}
