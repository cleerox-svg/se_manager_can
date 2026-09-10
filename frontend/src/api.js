const API = {
  get: (url) => fetch(url).then((r) => r.json()),
  post: (url, body) =>
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    }).then((r) => r.json()),
};

export function getDeals({ quarter, stage, search } = {}) {
  const params = new URLSearchParams({ quarter: quarter || 'current' });
  if (stage) params.set('stage', stage);
  if (search) params.set('search', search);
  return API.get(`/api/deals?${params}`);
}

export function getReps() {
  return API.get('/api/reps');
}

export function updateRep(repId, fields) {
  return API.post(`/api/reps/${repId}`, fields);
}

export function getRepDeals(repId) {
  return API.get(`/api/reps/${repId}/deals`);
}

export function getRepSlack(repId) {
  return API.get(`/api/reps/${repId}/slack`);
}

export function getReview(repId, period) {
  return API.get(`/api/reps/${repId}/reviews/${period}`);
}

export function generateReview(repId, period) {
  return API.post(`/api/reps/${repId}/reviews/${period}/generate`, {});
}

export function saveReview(repId, period, content, status) {
  return API.post(`/api/reps/${repId}/reviews/${period}`, { content, status });
}

export function getSettings() {
  return API.get('/api/settings');
}

export function syncSheets() {
  return API.post('/api/sync/sheets');
}

export function syncSlack() {
  return API.post('/api/sync/slack');
}

export function getTechForecast() {
  return API.get('/api/tech-forecast');
}

export function generatePrereadDraft() {
  return API.post('/api/tech-forecast/preread/draft', {});
}
