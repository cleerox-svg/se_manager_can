const listeners = new Set();
let nextId = 1;

export function subscribeToasts(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function toast(message, type = 'info') {
  const entry = { id: nextId++, message, type };
  listeners.forEach((fn) => fn(entry));
  return entry.id;
}
