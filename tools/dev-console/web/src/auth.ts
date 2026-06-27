const _token = new URLSearchParams(window.location.search).get("token");

export function authFetch(url: string): Promise<Response> {
  const opts: RequestInit = _token
    ? { headers: { Authorization: `Bearer ${_token}` } }
    : {};
  return fetch(url, opts);
}
