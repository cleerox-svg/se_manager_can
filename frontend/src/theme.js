const THEME_KEY = 'theme';

export function isStoredThemeLight() {
  return localStorage.getItem(THEME_KEY) === 'light';
}

export function applyTheme(light) {
  document.body.classList.toggle('light-mode', light);
}

export function setTheme(light) {
  applyTheme(light);
  localStorage.setItem(THEME_KEY, light ? 'light' : 'dark');
}

export function initTheme() {
  const light = isStoredThemeLight();
  applyTheme(light);
  return light;
}

export function enterPresentMode() {
  document.body.classList.add('present-mode');
}

export function exitPresentMode() {
  document.body.classList.remove('present-mode');
}
