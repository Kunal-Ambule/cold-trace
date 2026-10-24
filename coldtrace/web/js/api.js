// Thin fetch wrapper: attaches the JWT, throws on non-2xx with the server's error detail.
const API = (() => {
  let token = localStorage.getItem('ct_token') || null;

  function setToken(t) { token = t; if (t) localStorage.setItem('ct_token', t); else localStorage.removeItem('ct_token'); }
  function getToken() { return token; }

  async function req(method, path, body) {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
    if (res.status === 401) { setToken(null); location.reload(); throw new Error('Session expired'); }
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) throw new Error((data && data.detail) || res.statusText);
    return data;
  }
  return {
    setToken, getToken,
    get: (p) => req('GET', p),
    post: (p, b) => req('POST', p, b === undefined ? {} : b),
    patch: (p, b) => req('PATCH', p, b === undefined ? {} : b),
    del: (p) => req('DELETE', p),
    login: (username, password) => req('POST', '/api/auth/login', { username, password }),
  };
})();
