/* Admin dashboard: user account and role management.
 * Backed by GET/POST/PATCH /api/users (admin-only, enforced server-side).
 * Exposes window.AdminDashboard = { init }.
 */
(function () {
    "use strict";

    let apiRef;
    let currentUserId = null;

    function escapeHtml(s) {
        return String(s ?? "").replace(/[&<>"']/g, (ch) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        })[ch]);
    }

    function pill(value) {
        return `<span class="pill pill-${escapeHtml(value)}">${escapeHtml(String(value).replace("_", " "))}</span>`;
    }

    async function loadUsers() {
        const users = await apiRef("/api/users");
        const me = window.Auth.user();
        currentUserId = me ? me.id : null;

        const el = document.getElementById("admin-users");
        el.innerHTML = users
            .map((u) => {
                const isSelf = u.id === currentUserId;
                const roleOptions = ["client", "operator", "admin"]
                    .map(
                        (r) =>
                            `<option value="${r}" ${u.role === r ? "selected" : ""}>${r}</option>`
                    )
                    .join("");
                return `
                <tr class="border-t border-slate-100 hover:bg-slate-50">
                    <td class="px-3 py-2 font-mono text-xs text-slate-500">#${u.id}</td>
                    <td class="px-3 py-2">${escapeHtml(u.email)}</td>
                    <td class="px-3 py-2 font-medium">${escapeHtml(u.name)}</td>
                    <td class="px-3 py-2">${escapeHtml(u.organisation || "—")}</td>
                    <td class="px-3 py-2">
                        <select data-role-for="${u.id}" ${isSelf ? "disabled" : ""}
                            class="rounded-lg border border-slate-300 px-2 py-1 text-xs focus:border-indigo-500 focus:outline-none disabled:opacity-40">
                            ${roleOptions}
                        </select>
                    </td>
                    <td class="px-3 py-2">${u.is_active ? pill("accepted") : pill("rejected")}</td>
                    <td class="px-3 py-2">${new Date(u.created_at).toLocaleDateString()}</td>
                    <td class="px-3 py-2 text-right">
                        ${isSelf
                            ? `<span class="text-xs text-slate-400" title="You cannot deactivate yourself">you</span>`
                            : `<button data-toggle="${u.id}" data-active="${u.is_active}"
                                class="rounded px-2.5 py-1 text-xs font-semibold ${u.is_active
                                    ? "border border-red-200 text-red-600 hover:bg-red-50"
                                    : "bg-green-600 text-white hover:bg-green-700"}">
                                ${u.is_active ? "Deactivate" : "Activate"}</button>`}
                    </td>
                </tr>`;
            })
            .join("");

        el.querySelectorAll("[data-role-for]").forEach((sel) =>
            sel.addEventListener("change", () =>
                patchUser(Number(sel.dataset.roleFor), { role: sel.value })
            )
        );
        el.querySelectorAll("[data-toggle]").forEach((btn) =>
            btn.addEventListener("click", () =>
                patchUser(Number(btn.dataset.toggle), { is_active: btn.dataset.active !== "true" })
            )
        );
    }

    async function patchUser(id, body) {
        const errEl = document.getElementById("admin-error");
        errEl.classList.add("hidden");
        try {
            await apiRef(`/api/users/${id}`, { method: "PATCH", body: JSON.stringify(body) });
            await loadUsers();
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove("hidden");
            await loadUsers(); // re-render to discard any stale control state
        }
    }

    async function createUser(e) {
        e.preventDefault();
        const errEl = document.getElementById("admin-error");
        const okEl = document.getElementById("admin-success");
        errEl.classList.add("hidden");
        okEl.classList.add("hidden");
        const payload = {
            email: document.getElementById("au-email").value.trim(),
            password: document.getElementById("au-password").value,
            role: document.getElementById("au-role").value,
            name: document.getElementById("au-name").value.trim(),
            organisation: document.getElementById("au-org").value.trim() || null,
        };
        try {
            const created = await apiRef("/api/users", {
                method: "POST",
                body: JSON.stringify(payload),
            });
            e.target.reset();
            okEl.textContent = `Created ${created.email} (${created.role})`;
            okEl.classList.remove("hidden");
            await loadUsers();
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove("hidden");
        }
    }

    window.AdminDashboard = {
        init() {
            apiRef = window.Auth.api;
            const form = document.getElementById("admin-user-form");
            if (form && !form.dataset.wired) {
                form.addEventListener("submit", createUser);
                form.dataset.wired = "1";
            }
            loadUsers().catch((err) => {
                const errEl = document.getElementById("admin-error");
                if (errEl) {
                    errEl.textContent = err.message;
                    errEl.classList.remove("hidden");
                }
            });
        },
    };
})();
