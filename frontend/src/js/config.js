// API base URL resolution order:
// 1. ?api= query param  (e.g. index.html?api=http://localhost:8000)
// 2. window.API_BASE_URL global (set at deploy time if desired)
// 3. same origin (default; nginx proxies /api to the backend in Docker)
const API_BASE_URL =
    new URLSearchParams(window.location.search).get("api") ||
    window.API_BASE_URL ||
    "";

window.DRD = {
    api: (path) => `${API_BASE_URL}${path}`,
    tokenKey: "drd_token",
    userKey: "drd_user",
};
