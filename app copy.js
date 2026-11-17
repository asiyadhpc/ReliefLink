
const K = { session: "rl_session" };

function getSession() {
    try {
        return JSON.parse(localStorage.getItem(K.session));
    } catch {
        return null;
    }
}

function saveSession(session) {
    localStorage.setItem(K.session, JSON.stringify(session));
}

function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    })[char]);
}

function statusPill(status) {
    const classes = {
        "Resolved": "resolved",
        "Approved": "resolved",
        "In Progress": "progress",
        "Rejected": "rejected",
        "Pending": "pending"
    };

    return `<span class="pill ${classes[status] || "pending"}">${escapeHTML(status)}</span>`;
}

function priorityPill(priority) {
    const classes = {
        "Low": "low",
        "Medium": "medium",
        "High": "high"
    };

    return `<span class="pill ${classes[priority] || "medium"}">${escapeHTML(priority)}</span>`;
}

function go(role) {
    const pages = {
        user: "user-dashboard.html",
        volunteer: "volunteer-dashboard.html",
        admin: "admin-dashboard.html"
    };

    if (pages[role]) {
        window.location.href = pages[role];
    } else {
        alert("Please select a valid role.");
    }
}

async function api(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        }
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
        throw new Error(data.error || `Request failed (${response.status})`);
    }

    return data;
}

function showError(error) {
    console.error(error);
    alert(error.message || "Something went wrong. Please try again.");
}

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
}

// Login: demo-only role selection, not real authentication.
function setupLogin() {
    const form = document.getElementById("loginForm");
    if (!form) return;

    form.addEventListener("submit", event => {
        event.preventDefault();

        const role = document.getElementById("role")?.value;
        const email = document.getElementById("email")?.value.trim();
        const password = document.getElementById("password")?.value;

        if (!role || !email || !password) {
            alert("Please fill in all login fields.");
            return;
        }

        saveSession({
            role,
            email: email.toLowerCase(),
            name: email.split("@")[0]
        });

        go(role);
    });
}

// Volunteer registration: save through the Flask API.
function setupVolunteerRegistration() {
    const form = document.getElementById("volunteerForm");
    if (!form) return;

    form.addEventListener("submit", async event => {
        event.preventDefault();

        const button = form.querySelector('[type="submit"]');

        try {
            if (button) button.disabled = true;

            const result = await api("/api/volunteers", {
                method: "POST",
                body: JSON.stringify({
                    name: document.getElementById("vName").value.trim(),
                    email: document.getElementById("vEmail").value.trim(),
                    phone: document.getElementById("vPhone").value.trim(),
                    skill: document.getElementById("vSkill").value
                })
            });

            alert(result.message || "Volunteer application submitted.");
            form.reset();
            window.location.href = "login.html";
        } catch (error) {
            showError(error);
        } finally {
            if (button) button.disabled = false;
        }
    });
}

function setupLogout() {
    document.querySelectorAll("[data-logout]").forEach(button => {
        button.addEventListener("click", () => {
            localStorage.removeItem(K.session);
            window.location.href = "login.html";
        });
    });
}

function requireSession(page) {
    const session = getSession();

    if (!session) {
        window.location.href = "login.html";
        return null;
    }

    if (session.role !== page) {
        alert("Please sign in using the correct demo role.");
        go(session.role);
        return null;
    }

    setText("displayName", session.name || page);
    return session;
}

// Community User Dashboard
async function setupUserDashboard(session) {
    const form = document.getElementById("requestForm");
    const table = document.getElementById("userRequestsTable");

    async function render() {
        const all = await api("/api/requests");

        const mine = all.filter(request =>
            String(request.owner || "").toLowerCase() ===
            session.email.toLowerCase()
        );

        setText("userTotal", mine.length);
        setText("userProgress", mine.filter(r => r.status === "In Progress").length);
        setText("userResolved", mine.filter(r => r.status === "Resolved").length);

        if (table) {
            table.innerHTML = mine.length
                ? mine.map(r => `
                    <tr>
                        <td>${escapeHTML(r.id)}</td>
                        <td>${escapeHTML(r.type)}</td>
                        <td>${escapeHTML(r.location)}</td>
                        <td>${priorityPill(r.priority)}</td>
                        <td>${statusPill(r.status)}</td>
                    </tr>
                `).join("")
                : `<tr><td colspan="5">No requests for this email yet.</td></tr>`;
        }
    }

    if (form) {
        form.addEventListener("submit", async event => {
            event.preventDefault();

            const button = form.querySelector('[type="submit"]');
            const message = document.getElementById("requestMessage");

            try {
                if (button) button.disabled = true;

                const result = await api("/api/requests", {
                    method: "POST",
                    body: JSON.stringify({
                        owner: session.email,
                        type: document.getElementById("requestType").value,
                        location: document.getElementById("location").value.trim(),
                        priority: document.getElementById("priority").value,
                        details: document.getElementById("details").value.trim()
                    })
                });

                if (message) {
                    message.textContent = ` Request ${result.id} submitted successfully.`;
                }

                form.reset();
                await render();
            } catch (error) {
                showError(error);
            } finally {
                if (button) button.disabled = false;
            }
        });
    }

    await render();
}

// Volunteer Dashboard
async function setupVolunteerDashboard() {
    const table = document.getElementById("volunteerRequestsTable");
    const filter = document.getElementById("statusFilter");

    async function render() {
        const requests = await api("/api/requests");
        const selectedStatus = filter?.value || "All";

        const shown = selectedStatus === "All"
            ? requests
            : requests.filter(r => r.status === selectedStatus);

        setText("volOpen", requests.filter(r => r.status === "Pending").length);
        setText("volProgress", requests.filter(r => r.status === "In Progress").length);
        setText("volCompleted", requests.filter(r => r.status === "Resolved").length);
        setText("volHelped", requests.filter(r => r.status === "Resolved").length);

        if (!table) return;

        table.innerHTML = shown.length
            ? shown.map(r => `
                <tr>
                    <td>${escapeHTML(r.id)}</td>
                    <td>${escapeHTML(r.owner)}</td>
                    <td>${escapeHTML(r.type)}</td>
                    <td>${escapeHTML(r.location)}</td>
                    <td>${priorityPill(r.priority)}</td>
                    <td>
                        ${statusPill(r.status)}
                        <select data-request-id="${r.id}" aria-label="Update request status">
                            <option value="Pending" ${r.status === "Pending" ? "selected" : ""}>Pending</option>
                            <option value="In Progress" ${r.status === "In Progress" ? "selected" : ""}>In Progress</option>
                            <option value="Resolved" ${r.status === "Resolved" ? "selected" : ""}>Resolved</option>
                        </select>
                    </td>
                </tr>
            `).join("")
            : `<tr><td colspan="6">No matching requests.</td></tr>`;

        table.querySelectorAll("[data-request-id]").forEach(select => {
            select.addEventListener("change", async () => {
                const id = select.dataset.requestId;
                const newStatus = select.value;

                try {
                    select.disabled = true;

                    await api(`/api/requests/${id}`, {
                        method: "PATCH",
                        body: JSON.stringify({ status: newStatus })
                    });

                    await render();
                } catch (error) {
                    showError(error);
                    await render();
                }
            });
        });
    }

    if (filter) {
        filter.addEventListener("change", () => {
            render().catch(showError);
        });
    }

    await render();
}

// Admin Dashboard
async function setupAdminDashboard() {
    const volunteerTable = document.getElementById("volunteerApplicationsTable");
    const requestTable = document.getElementById("adminRequestsTable");

    async function render() {
        const [requests, volunteers] = await Promise.all([
            api("/api/requests"),
            api("/api/volunteers")
        ]);

        setText("adminRequestCount", requests.length);
        setText("adminPendingVolunteers",
            volunteers.filter(v => v.status === "Pending").length);
        setText("adminOpenRequests",
            requests.filter(r => r.status !== "Resolved").length);

        if (volunteerTable) {
            volunteerTable.innerHTML = volunteers.length
                ? volunteers.map(v => `
                    <tr>
                        <td>${escapeHTML(v.name)}</td>
                        <td>${escapeHTML(v.email)}</td>
                        <td>${escapeHTML(v.phone)}</td>
                        <td>${escapeHTML(v.skill)}</td>
                        <td>${statusPill(v.status)}</td>
                        <td>
                            ${v.status === "Pending"
                                ? `<button class="primary" data-volunteer-id="${v.id}" data-action="Approved">Approve</button>
                                   <button class="light" data-volunteer-id="${v.id}" data-action="Rejected">Reject</button>`
                                : "Reviewed"}
                        </td>
                    </tr>
                `).join("")
                : `<tr><td colspan="6">No applications yet.</td></tr>`;

            volunteerTable.querySelectorAll("[data-action]").forEach(button => {
                button.addEventListener("click", async () => {
                    try {
                        button.disabled = true;

                        await api(`/api/volunteers/${button.dataset.volunteerId}`, {
                            method: "PATCH",
                            body: JSON.stringify({
                                status: button.dataset.action
                            })
                        });

                        await render();
                    } catch (error) {
                        showError(error);
                        await render();
                    }
                });
            });
        }

        if (requestTable) {
            requestTable.innerHTML = requests.length
                ? requests.map(r => `
                    <tr>
                        <td>${escapeHTML(r.id)}</td>
                        <td>${escapeHTML(r.owner)}</td>
                        <td>${escapeHTML(r.type)}</td>
                        <td>${escapeHTML(r.location)}</td>
                        <td>${priorityPill(r.priority)}</td>
                        <td>${statusPill(r.status)}</td>
                    </tr>
                `).join("")
                : `<tr><td colspan="6">No requests yet.</td></tr>`;
        }
    }

    await render();
}

async function init() {
    setupLogin();
    setupVolunteerRegistration();
    setupLogout();

    const page = document.body.dataset.page;
    if (!page) return;

    const session = requireSession(page);
    if (!session) return;

    try {
        if (page === "user") {
            await setupUserDashboard(session);
        } else if (page === "volunteer") {
            await setupVolunteerDashboard();
        } else if (page === "admin") {
            await setupAdminDashboard();
        }
    } catch (error) {
        showError(error);
    }
}

document.addEventListener("DOMContentLoaded", init);
