export function token() { return sessionStorage.getItem("token"); }

export async function api(method, path, body, headers = {}) {
  const opts = { method, headers: { ...headers } };
  if (token()) opts.headers.Authorization = "Bearer " + token();
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && token()) {
    // Session is gone (for example the API restarted). Start again from sign in.
    sessionStorage.clear();
    location.assign("/login");
  }
  if (!res.ok) {
    const err = new Error(typeof data.detail === "string" ? data.detail : "Request failed (" + res.status + ")");
    err.status = res.status;
    throw err;
  }
  return data;
}
