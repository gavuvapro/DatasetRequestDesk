/* Auth: login form, token persistence, fetch wrapper, role-based view switching.
 * Exposes window.Auth = { login, logout, token, user, api, requireRole, showView }.
 */
(function () {
    "use strict";

    const { api, tokenKey, userKey } = window.DRD;

    // ---- session ---------------------------------------------------------
    function token() {
        return localStorage.getItem(tokenKey);
    }

    function user() {
        try {
            return JSON.parse(localStorage.getItem(userKey)) || null;
        } catch {
            return null;
        }
    }

    function saveSession(newToken, newUser) {
        localStorage.setItem(tokenKey, newToken);
        localStorage.setItem(userKey, JSON.stringify(newUser));
    }

    function clearSession() {
        localStorage.removeItem(tokenKey);
        localStorage.removeItem(userKey);
    }

    // ---- fetch wrapper ----------------------------------------------------
    async function apiFetch(path, options = {}) {
        const headers = Object.assign({}, options.headers || {});
        if (token()) headers["Authorization"] = "Bearer " + token();
        if (options.body && typeof options.body === "string") {
            headers["Content-Type"] = "application/json";
        }
        const res = await fetch(api(path), Object.assign({}, options, { headers }));

        if (res.status === 401) {
            clearSession();
            showView("login");
            throw new Error("Session expired, please log in again");
        }
        let data = null;
        const text = await res.text();
        if (text) {
            try {
                data = JSON.parse(text);
            } catch {
                data = text;
            }
        }
        if (!res.ok) {
            const detail =
                data && typeof data === "object" && data.detail ? data.detail : res.statusText;
            throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
        }
        return data;
    }

    // ---- login ------------------------------------------------------------
    async function login(email, password) {
        const body = new URLSearchParams({ username: email, password });
        const res = await fetch(api("/api/auth/login"), {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.detail || "Login failed");
        }
        saveSession(data.access_token, data.user);
        return data.user;
    }

    function logout() {
        clearSession();
        showView("login");
    }

    // ---- view switching ----------------------------------------------------
    function showView(name) {
        const loginView = document.getElementById("view-login");
        const appView = document.getElementById("view-app");
        const header = document.getElementById("app-header");
        if (!loginView || !appView) return;

        if (name === "login") {
            loginView.classList.remove("hidden");
            appView.classList.add("hidden");
            if (header) header.classList.add("hidden");
            const emailInput = document.getElementById("login-email");
            if (emailInput) emailInput.focus();
            return;
        }

        const u = user();
        if (!u) {
            showView("login");
            return;
        }

        // Role-based UI switching. The server remains the authority; this only
        // decides which dashboard is convenient to show.
        const isClient = u.role === "client";
        const dashboards = document.querySelectorAll("[data-dashboard]");
        dashboards.forEach((el) => {
            const wanted = el.getAttribute("data-dashboard");
            const visible =
                wanted === u.role || (wanted === "operator" && u.role === "admin");
            el.classList.toggle("hidden", !visible);
        });

        loginView.classList.add("hidden");
        appView.classList.add("hidden");
        appView.classList.remove("hidden");
        appView.classList.add("view-enter");
        if (header) {
            header.classList.remove("hidden");
            const nameEl = document.getElementById("header-user-name");
            const roleEl = document.getElementById("header-user-role");
            if (nameEl) nameEl.textContent = u.name;
            if (roleEl) roleEl.textContent = u.role;
        }
        if (isClient && window.ClientDashboard) {
            window.ClientDashboard.init();
        }
        if (!isClient && window.OperatorDashboard) {
            window.OperatorDashboard.init();
        }
    }

    // ---- wire up login form -------------------------------------------------
    document.addEventListener("DOMContentLoaded", () => {
        const form = document.getElementById("login-form");
        const errEl = document.getElementById("login-error");
        if (form) {
            form.addEventListener("submit", async (e) => {
                e.preventDefault();
                errEl.classList.add("hidden");
                const email = document.getElementById("login-email").value.trim();
                const password = document.getElementById("login-password").value;
                const btn = document.getElementById("login-submit");
                btn.disabled = true;
                btn.textContent = "Signing in...";
                try {
                    const u = await login(email, password);
                    showView("app");
                    void u;
                } catch (err) {
                    errEl.textContent = err.message;
                    errEl.classList.remove("hidden");
                } finally {
                    btn.disabled = false;
                    btn.textContent = "Sign in";
                }
            });
        }

        const logoutBtn = document.getElementById("logout-btn");
        if (logoutBtn) logoutBtn.addEventListener("click", logout);

        // Resume an existing session on page load.
        if (token() && user()) {
            showView("app");
        } else {
            showView("login");
        }
    });
})();
