/* Client dashboard: create a request, see own requests with status, and
 * accept or reject a delivered request.
 * Exposes window.ClientDashboard = { init }.
 */
(function () {
    "use strict";

    const { api } = window.DRD;
    let apiRef;

    function escapeHtml(s) {
        return String(s ?? "").replace(/[&<>"']/g, (ch) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        })[ch]);
    }

    function pill(value) {
        return `<span class="pill pill-${escapeHtml(value)}">${escapeHtml(value.replace("_", " "))}</span>`;
    }

    async function load() {
        const listEl = document.getElementById("client-requests");
        const data = await apiRef("/api/requests");
        listEl.innerHTML = renderTable(data);
        wireRowActions(data);
    }

    function renderTable(rows) {
        if (!rows.length) {
            return `<div class="p-8 text-center text-sm text-slate-500">
                No requests yet. Create your first dataset request on the left.</div>`;
        }
        const body = rows
            .map((r) => {
                const canReview = r.status === "delivered";
                return `
                <tr class="border-t border-slate-100 hover:bg-slate-50">
                    <td class="px-3 py-2 font-mono text-xs text-slate-500">#${r.id}</td>
                    <td class="px-3 py-2 font-medium">${escapeHtml(r.task_name)}</td>
                    <td class="px-3 py-2 text-center">${r.assigned_count}/${r.episodes_requested}</td>
                    <td class="px-3 py-2">${new Date(r.deadline).toLocaleDateString()}</td>
                    <td class="px-3 py-2">${pill(r.status)}</td>
                    <td class="px-3 py-2 text-right space-x-1">
                        ${canReview ? `
                            <button data-accept="${r.id}" class="rounded bg-green-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-green-700">Accept</button>
                            <button data-reject="${r.id}" class="rounded bg-red-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-red-700">Reject</button>`
                        : `<span class="text-xs text-slate-400">—</span>`}
                    </td>
                </tr>`;
            })
            .join("");
        return `
            <table class="w-full text-sm">
                <thead class="text-left text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                        <th class="px-3 py-2">ID</th>
                        <th class="px-3 py-2">Task</th>
                        <th class="px-3 py-2 text-center">Episodes</th>
                        <th class="px-3 py-2">Deadline</th>
                        <th class="px-3 py-2">Status</th>
                        <th class="px-3 py-2 text-right">Review</th>
                    </tr>
                </thead>
                <tbody>${body}</tbody>
            </table>`;
    }

    function wireRowActions(rows) {
        document.querySelectorAll("#client-requests [data-accept]").forEach((btn) => {
            btn.addEventListener("click", () => transition(Number(btn.dataset.accept), "accepted"));
        });
        document.querySelectorAll("#client-requests [data-reject]").forEach((btn) => {
            btn.addEventListener("click", () => transition(Number(btn.dataset.reject), "rejected"));
        });
        void rows;
    }

    async function transition(id, toStatus) {
        try {
            await apiRef(`/api/requests/${id}/transition`, {
                method: "POST",
                body: JSON.stringify({ to_status: toStatus }),
            });
            await load();
        } catch (err) {
            alert(err.message);
        }
    }

    async function createRequest(e) {
        e.preventDefault();
        const msgEl = document.getElementById("client-form-msg");
        msgEl.classList.add("hidden");
        const payload = {
            task_name: document.getElementById("cr-task").value.trim(),
            episodes_requested: Number(document.getElementById("cr-count").value),
            deadline: document.getElementById("cr-deadline").value
                ? new Date(document.getElementById("cr-deadline").value).toISOString()
                : "",
            notes: document.getElementById("cr-notes").value.trim() || null,
        };
        try {
            await apiRef("/api/requests", { method: "POST", body: JSON.stringify(payload) });
            e.target.reset();
            await load();
        } catch (err) {
            msgEl.textContent = err.message;
            msgEl.classList.remove("hidden");
        }
    }

    window.ClientDashboard = {
        init() {
            apiRef = window.Auth.api;
            const form = document.getElementById("client-request-form");
            if (!form.dataset.wired) {
                form.addEventListener("submit", createRequest);
                form.dataset.wired = "1";
            }
            load().catch((err) => alert(err.message));
        },
    };
})();
