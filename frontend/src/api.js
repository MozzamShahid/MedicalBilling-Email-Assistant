async function req(path, opts = {}) {
  const res = await fetch(`/api${path}`, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

const json = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  leads: () => req("/leads"),
  lead: (id) => req(`/leads/${id}`),
  stats: () => req("/stats"),
  importLeads: (form) => req("/leads/import", { method: "POST", body: form }),
  run: (ids) => req("/leads/run", json("POST", { ids })),
  update: (id, fields) => req(`/leads/${id}`, json("PATCH", fields)),
  markSent: (id) => req(`/leads/${id}/sent`, { method: "POST" }),
  remove: (id) => req(`/leads/${id}`, { method: "DELETE" }),
  exportUrl: (fmt, ids, research) =>
    `/api/export?fmt=${fmt}&ids=${ids.join(",")}&research=${research}`,
};
