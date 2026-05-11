// Single-tenant: paste the API token once, persist to localStorage,
// gate the app on its presence. The token is sent as a Bearer header on
// every API call. We never echo it back to the UI after save.

const KEY = "ckg.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(KEY);
}

export function setToken(t: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, t.trim());
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
}
