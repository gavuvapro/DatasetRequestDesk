/* Operator dashboard: all requests + status transitions, episode browser with
 * task/quality filters, and episode assignment to requests.
 * Exposes window.OperatorDashboard = { init }.
 */
(function () {
    "use strict";

    const { api } = window.DRD;
    let apiRef;
    let selectedRequestId = null;

    function escapeHtml(s) {
        return String(s ?? "").replace(/[&<>"']/g, (ch) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        })[ch]);
    }

    function pill(value) {
        return `<span class="pill pill-${escapeHtml(value)}">${escapeHtml(String(value).replace("_", " "))}</span>`;
    }

    // ---- requests panel -----------------------------------------------------
    const NEXT_LABEL = {
        submitted: "Start (in_progress)",
        in_progress: "Deliver",
        rejected: "Rework (in_progress)",
    };

    async function loadRequests() {
        const status = document.getElementById("ops-status-filter").value;
        const qs = status ? `?status=${status}` : "";
        const rows = await apiRef(`/api/requests${qs}`);
        const listEl = document.getElementById("ops-requests");
        if (!rows.length) {
            listEl.innerHTML = `<div class="p-6 text-center text-sm text-slate-500">No requests found.</div>`;
            return;
        }
        listEl.innerHTML = rows
            .map((r) => {
                const complete = r.assigned_count >= r.episodes_requested;
                const canAdvance = ["submitted", "in_progress", "rejected"].includes(r.status);
                const action = canAdvance && NEXT_LABEL[r.status]
                    ? `<button data-advance="${r.id}" data-to="${r.status === "submitted" || r.status === "rejected" ? "in_progress" : "delivered"}"
                         class="rounded ${r.status === "in_progress" && !complete ? "bg-slate-300" : "bg-indigo-600 hover:bg-indigo-700"} px-2.5 py-1 text-xs font-semibold text-white"
                         ${r.status === "in_progress" && !complete ? 'title="Assign enough episodes first" disabled' : ""}>
                         ${r.status === "in_progress" ? "Deliver" : NEXT_LABEL[r.status]}</button>`
                    : "";
                return `
                <tr class="border-t border-slate-100 hover:bg-slate-50 ${selectedRequestId === r.id ? "bg-indigo-50" : ""}">
                    <td class="px-3 py-2 font-mono text-xs text-slate-500">#${r.id}</td>
                    <td class="px-3 py-2">${escapeHtml(r.client_name || `user ${r.client_id}`)}</td>
                    <td class="px-3 py-2 font-medium">${escapeHtml(r.task_name)}</td>
                    <td class="px-3 py-2 text-center ${complete ? "text-green-700 font-semibold" : ""}">${r.assigned_count}/${r.episodes_requested}</td>
                    <td class="px-3 py-2">${new Date(r.deadline).toLocaleDateString()}</td>
                    <td class="px-3 py-2">${pill(r.status)}</td>
                    <td class="px-3 py-2 text-right space-x-1">
                        <button data-select="${r.id}" class="rounded border border-slate-300 px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100">Assign episodes</button>
                        ${action}
                    </td>
                </tr>`;
            })
            .join("");

        listEl.querySelectorAll("[data-select]").forEach((btn) =>
            btn.addEventListener("click", () => selectRequest(Number(btn.dataset.select)))
        );
        listEl.querySelectorAll("[data-advance]").forEach((btn) =>
            btn.addEventListener("click", () =>
                transition(Number(btn.dataset.advance), btn.dataset.to)
            )
        );
    }

    async function transition(id, toStatus) {
        try {
            await apiRef(`/api/requests/${id}/transition`, {
                method: "POST",
                body: JSON.stringify({ to_status: toStatus }),
            });
            await Promise.all([loadRequests(), selectedRequestId ? loadAssignments() : null]);
        } catch (err) {
            alert(err.message);
        }
    }

    // ---- episode browser ------------------------------------------------------
    async function loadEpisodes() {
        const task = document.getElementById("ep-task-filter").value.trim();
        const quality = document.getElementById("ep-quality-filter").value;
        const params = new URLSearchParams({ limit: "25" });
        if (task) params.set("task_name", task);
        if (quality) params.set("quality", quality);
        const data = await apiRef(`/api/episodes?${params}`);
        const el = document.getElementById("episodes-list");
        if (!data.items.length) {
            el.innerHTML = `<div class="p-6 text-center text-sm text-slate-500">No episodes match.</div>`;
            return;
        }
        el.innerHTML = data.items
            .map(
                (ep) => `
            <tr class="border-t border-slate-100 hover:bg-slate-50">
                <td class="px-3 py-1.5 font-mono text-xs">${escapeHtml(ep.episode_id)}</td>
                <td class="px-3 py-1.5">${escapeHtml(ep.robot_id)}</td>
                <td class="px-3 py-1.5">${escapeHtml(ep.task_name)}</td>
                <td class="px-3 py-1.5">${pill(ep.quality)}</td>
                <td class="px-3 py-1.5 text-right">
                    <button data-assign="${ep.id}" ${selectedRequestId ? "" : "disabled"}
                        class="rounded bg-indigo-600 px-2 py-0.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-40">
                        Assign</button>
                </td>
            </tr>`
            )
            .join("");
        el.querySelectorAll("[data-assign]").forEach((btn) =>
            btn.addEventListener("click", () => assign(Number(btn.dataset.assign)))
        );
    }

    // ---- assignment panel ------------------------------------------------------
    function selectRequest(id) {
        selectedRequestId = id;
        document.getElementById("assign-target").classList.remove("hidden");
        loadAssignments().catch((e) => alert(e.message));
        document
            .getElementById("assign-target")
            .scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    async function loadAssignments() {
        const data = await apiRef(`/api/requests/${selectedRequestId}`);
        const detail = await apiRef(`/api/requests/${selectedRequestId}/assignments`);
        const head = document.getElementById("assign-head");
        head.innerHTML = `Request #${data.id} — <strong>${escapeHtml(data.task_name)}</strong>
            ${pill(data.status)} · ${data.assigned_count}/${data.episodes_requested} episodes
            · client ${escapeHtml(data.client_name || data.client_id)}`;

        const list = document.getElementById("assign-list");
        list.innerHTML = detail.length
            ? detail
                  .map(
                      (a) => `
                <tr class="border-t border-slate-100">
                    <td class="px-3 py-1.5 font-mono text-xs">${escapeHtml(a.episode_id)}</td>
                    <td class="px-3 py-1.5">${escapeHtml(a.task_name)}</td>
                    <td class="px-3 py-1.5">${pill(a.quality)}</td>
                    <td class="px-3 py-1.5 text-right">
                        <button data-unassign="${a.episode_pk}" class="rounded border border-red-200 px-2 py-0.5 text-xs font-semibold text-red-600 hover:bg-red-50">Remove</button>
                    </td>
                </tr>`
                  )
                  .join("")
            : `<tr><td colspan="4" class="px-3 py-3 text-center text-xs text-slate-400">No episodes assigned yet — pick some from the episode browser.</td></tr>`;
        list.querySelectorAll("[data-unassign]").forEach((btn) =>
            btn.addEventListener("click", () => unassign(Number(btn.dataset.unassign)))
        );
    }

    async function assign(episodePk) {
        if (!selectedRequestId) return alert("Select a request first");
        try {
            await apiRef(`/api/requests/${selectedRequestId}/assign`, {
                method: "POST",
                body: JSON.stringify({ episode_id: episodePk }),
            });
            await Promise.all([loadAssignments(), loadEpisodes(), loadRequests()]);
        } catch (err) {
            alert(err.message);
        }
    }

    async function unassign(episodePk) {
        try {
            await apiRef(`/api/requests/${selectedRequestId}/assign/${episodePk}`, {
                method: "DELETE",
            });
            await Promise.all([loadAssignments(), loadRequests()]);
        } catch (err) {
            alert(err.message);
        }
    }

    window.OperatorDashboard = {
        init() {
            apiRef = window.Auth.api;
            const wire = (id, fn) => {
                const el = document.getElementById(id);
                if (el && !el.dataset.wired) {
                    el.addEventListener(fn.event, fn.handler);
                    el.dataset.wired = "1";
                }
            };
            wire("ops-status-filter", { event: "change", handler: loadRequests });
            wire("ops-refresh", { event: "click", handler: loadRequests });
            wire("ep-task-filter", { event: "input", handler: loadEpisodes });
            wire("ep-quality-filter", { event: "change", handler: loadEpisodes });
            wire("ep-search", { event: "click", handler: loadEpisodes });
            loadRequests().catch((e) => alert(e.message));
            loadEpisodes().catch((e) => alert(e.message));
        },
    };
})();
