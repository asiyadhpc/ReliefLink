const K = { session: "rl_session" };

// ========================================
// SESSION AND HELPERS
// ========================================
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

function formatLocationDisplay(locationStr) {
    const raw = String(locationStr || "").trim();
    if (!raw) return "Location not specified";

    const coordMatch = raw.match(/-?\d{1,3}\.\d+,\s*-?\d{1,3}\.\d+/);

    if (coordMatch) {
        const coords = coordMatch[0];
        const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(coords)}`;
        return `<a href="${mapsUrl}" target="_blank" rel="noopener noreferrer" style="color:#087e78;font-weight:700;text-decoration:underline;">📍 Open in Maps (${escapeHTML(coords)})</a>`;
    }

    return escapeHTML(raw);
}

function getDescription(request) {
    return request.description || request.details || "No description provided";
}

function statusPill(status) {
    const classes = {
        Resolved: "resolved",
        Approved: "resolved",
        "In Progress": "progress",
        Scheduled: "progress",
        Rejected: "rejected",
        Pending: "pending",
        Available: "pending"
    };

    return `<span class="pill ${classes[status] || "pending"}">${escapeHTML(status || "Pending")}</span>`;
}

function priorityPill(priority) {
    const classes = {
        Low: "low",
        Medium: "medium",
        High: "high"
    };

    return `<span class="pill ${classes[priority] || "medium"}">${escapeHTML(priority || "Medium")}</span>`;
}

function bloodPill(bloodGroup) {
    const raw = String(bloodGroup || "").trim();
    if (!raw || raw === "N/A" || raw.toLowerCase() === "none") {
        return `<span style="color:#94a3b8;font-size:11px;">N/A</span>`;
    }
    return `<span class="pill" style="background:#fee2e2;color:#b91c1c;font-weight:700;font-size:11px;padding:3px 8px;border-radius:12px;">🩸 ${escapeHTML(raw)}</span>`;
}

function proofLinkHTML(item) {
    if (!item || !item.proof_url) return "";
    return `
        <div style="margin-top:6px;">
            <a href="${escapeHTML(item.proof_url)}" target="_blank" rel="noopener noreferrer"
               style="display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:700;color:#087e78;background:#e6f8f5;border:1px solid #99ded7;padding:3px 8px;border-radius:6px;text-decoration:none;">
                📷 View Photo Proof
            </a>
        </div>
    `;
}

function normalizeRole(value) {
    const role = String(value || "").trim().toLowerCase();

    if (["user", "community user", "community-user", "community_user"].includes(role)) return "user";
    if (["volunteer", "community volunteer"].includes(role)) return "volunteer";
    if (["admin", "administrator"].includes(role)) return "admin";

    return "";
}

function normalizeList(data, keys = []) {
    if (Array.isArray(data)) return data;

    for (const key of keys) {
        if (Array.isArray(data?.[key])) return data[key];
    }

    return [];
}

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = String(value ?? "");
}

function showError(error) {
    console.error("ReliefLink error:", error);
    alert(error?.message || "Something went wrong. Please try again.");
}

function go(role) {
    const normalizedRole = normalizeRole(role);

    const pages = {
        user: "user-dashboard.html",
        volunteer: "volunteer-dashboard.html",
        admin: "admin-dashboard.html"
    };

    if (pages[normalizedRole]) {
        window.location.assign(pages[normalizedRole]);
    } else {
        alert("Please select Community User, Volunteer, or Administrator.");
    }
}

// ========================================
// API HELPERS
// ========================================
async function api(url, options = {}) {
    const headers = { ...(options.headers || {}) };
    const isFormData = options.body instanceof FormData;

    if (!isFormData && options.body !== undefined && typeof options.body === "string") {
        headers["Content-Type"] = "application/json";
    }

    let response;

    try {
        response = await fetch(url, {
            ...options,
            headers,
            credentials: "same-origin",
            cache: "no-store"
        });
    } catch {
        throw new Error("Cannot connect to the ReliefLink server. Check that the backend is running.");
    }

    const text = await response.text();
    let data = {};

    if (text) {
        try {
            data = JSON.parse(text);
        } catch {
            data = { message: text };
        }
    }

    if (!response.ok) {
        throw new Error(
            data.error ||
            data.message ||
            `Request failed with HTTP ${response.status}`
        );
    }

    return data;
}

async function uploadApi(url, formData) {
    return api(url, {
        method: "POST",
        body: formData
    });
}

// ========================================
// LOGIN AND REGISTRATION
// ========================================
function setupLogin() {
    const loginForm = document.getElementById("loginForm");
    const registerForm = document.getElementById("registerForm");

    const loginMessage = document.getElementById("loginMessage");
    const registerMessage = document.getElementById("registerMessage");

    const showMessage = (element, message, type) => {
        if (!element) return;
        element.textContent = message;
        element.className = "login-message" + (type ? " " + type : "");
    };

    const pages = {
        user: "user-dashboard.html",
        volunteer: "volunteer-dashboard.html",
        admin: "admin-dashboard.html"
    };

    const loginView = document.getElementById("loginView");
    const registerView = document.getElementById("registerView");

    function showView(view) {
        if (!loginView || !registerView) return;

        loginView.classList.toggle("active", view !== "register");
        registerView.classList.toggle("active", view === "register");

        document.title = view === "register"
            ? "ReliefLink | Create Account"
            : "ReliefLink | Sign In";
    }

    document.getElementById("showRegister")?.addEventListener("click", event => {
        event.preventDefault();
        history.replaceState(null, "", "#register");
        showView("register");
    });

    document.getElementById("showLogin")?.addEventListener("click", event => {
        event.preventDefault();
        history.replaceState(null, "", "#login");
        showView("login");
    });

    document.getElementById("backToLogin")?.addEventListener("click", event => {
        event.preventDefault();
        history.replaceState(null, "", "#login");
        showView("login");
    });

    showView(location.hash === "#register" ? "register" : "login");

    // LOGIN
    if (loginForm && loginForm.dataset.rlLoginReady !== "true") {
        loginForm.dataset.rlLoginReady = "true";

        loginForm.addEventListener("submit", async event => {
            event.preventDefault();

            const button = document.getElementById("loginButton");
            const roleSelect = document.getElementById("role");
            const role = roleSelect ? normalizeRole(roleSelect.value) : "user";
            const email = document.getElementById("email")?.value.trim().toLowerCase();
            const password = document.getElementById("password")?.value || "";

            try {
                if (button) button.disabled = true;

                if (!email || !password) {
                    throw new Error("Please enter your email and password.");
                }

                const result = await api("/api/login", {
                    method: "POST",
                    body: JSON.stringify({ role, email, password })
                });

                const userObj = result.user || { email, role: role || "user", name: email.split("@")[0] };
                saveSession(userObj);

                showMessage(
                    loginMessage,
                    "Login successful. Opening your dashboard...",
                    "success"
                );

                const destination = pages[normalizeRole(userObj.role)] || "user-dashboard.html";
                setTimeout(() => window.location.assign(destination), 400);

            } catch (error) {
                showMessage(loginMessage, error.message, "error");
            } finally {
                if (button) button.disabled = false;
            }
        });
    }

    // REGISTRATION
    if (registerForm && registerForm.dataset.rlRegisterReady !== "true") {
        registerForm.dataset.rlRegisterReady = "true";

        registerForm.addEventListener("submit", async event => {
            event.preventDefault();

            const button = document.getElementById("registerButton");
            const name = document.getElementById("regName")?.value.trim();
            const email = document.getElementById("regEmail")?.value.trim().toLowerCase();
            const password = document.getElementById("regPassword")?.value || "";
            const confirm = document.getElementById("regConfirm")?.value || "";
            const phone = document.getElementById("regPhone")?.value.trim();
            const pincode = document.getElementById("regPincode")?.value.trim();
            const bloodGroup = document.getElementById("regBlood")?.value;

            if (!name || !email || !password) {
                showMessage(registerMessage, "Please complete all required fields.", "error");
                return;
            }

            if (password !== confirm) {
                showMessage(registerMessage, "Passwords do not match.", "error");
                return;
            }

            if (password.length < 8) {
                showMessage(registerMessage, "Password must be at least 8 characters.", "error");
                return;
            }

            try {
                if (button) button.disabled = true;

                const result = await api("/api/register", {
                    method: "POST",
                    body: JSON.stringify({
                        name,
                        email,
                        password,
                        phone: phone || null,
                        pincode: pincode || null,
                        blood_group: bloodGroup || null,
                        bloodGroup: bloodGroup || null,
                        role: "user"
                    })
                });

                const userObj = result.user || {
                    name,
                    email,
                    role: "user",
                    phone: phone || "",
                    blood_group: bloodGroup || "",
                    bloodGroup: bloodGroup || "",
                    pincode: pincode || ""
                };
                saveSession(userObj);

                showMessage(
                    registerMessage,
                    (result.message || "Account created successfully.") + " Opening your dashboard...",
                    "success"
                );

                setTimeout(() => window.location.assign(pages.user), 500);

            } catch (error) {
                showMessage(registerMessage, error.message, "error");
            } finally {
                if (button) button.disabled = false;
            }
        });
    }
}

// ========================================
// VOLUNTEER REGISTRATION
// ========================================
function setupVolunteerRegistration() {
    const form = document.getElementById("volunteerForm");

    if (!form || form.dataset.rlReady === "true") return;

    form.dataset.rlReady = "true";

    form.addEventListener("submit", async event => {
        event.preventDefault();

        const button = form.querySelector('[type="submit"]');

        try {
            if (button) button.disabled = true;

            const name = document.getElementById("vName")?.value.trim();
            const email = document.getElementById("vEmail")?.value.trim();
            const phone = document.getElementById("vPhone")?.value.trim();
            const skill = document.getElementById("vSkill")?.value;

            if (!name || !email || !phone || !skill) {
                throw new Error("Please complete all volunteer registration fields.");
            }

            const result = await api("/api/volunteers", {
                method: "POST",
                body: JSON.stringify({ name, email, phone, skill })
            });

            alert(result.message || "Volunteer application submitted successfully.");
            form.reset();
            window.location.href = "login.html";

        } catch (error) {
            showError(error);
        } finally {
            if (button) button.disabled = false;
        }
    });
}

// ========================================
// LOGOUT AND SESSION CHECK
// ========================================
function setupLogout() {
    document.querySelectorAll("[data-logout], #userLogoutBtn, #logoutBtn").forEach(button => {
        if (button.dataset.rlReady === "true") return;

        button.dataset.rlReady = "true";

        button.addEventListener("click", async () => {
            try {
                await api("/api/logout", {
                    method: "POST",
                    body: "{}"
                });
            } catch (error) {
                console.warn("Logout ping skipped:", error);
            }

            localStorage.removeItem(K.session);
            window.location.href = "login.html";
        });
    });
}

async function requireSession(page) {
    const session = getSession();

    if (!session || !session.email) {
        localStorage.removeItem(K.session);
        window.location.href = "login.html";
        return null;
    }

    const currentRole = normalizeRole(session.role);

    if (!currentRole) {
        localStorage.removeItem(K.session);
        window.location.href = "login.html";
        return null;
    }

    if (currentRole !== page) {
        alert("Access restricted. Opening your designated dashboard.");
        go(currentRole);
        return null;
    }

    setText("displayName", session.name || session.email.split("@")[0] || page);
    return session;
}

// ========================================
// COMMUNITY ALERTS
// ========================================
function getIncidentImageUrl(incident) {
    const url = incident.image_url || incident.image || incident.image_path || "";

    if (url.startsWith("/") || /^https?:\/\//i.test(url)) {
        return url;
    }

    if (incident.image_filename) {
        return `/api/incidents/uploads/${encodeURIComponent(incident.image_filename)}`;
    }

    return "";
}

function renderIncidentCard(incident) {
    const imageUrl = getIncidentImageUrl(incident);
    const category = incident.category || incident.type || "Safety Alert";
    const location = incident.location || "Location not provided";
    const description = incident.description || incident.details || "No description provided";
    const reporter = incident.posted_by || incident.reporter || incident.owner || "Community team";
    const date = incident.created_at || incident.date || "";

    return `
        <article class="incident-card" style="border:1px solid #dce5e9;border-radius:12px;padding:14px;margin:12px 0;background:#fff;">
            <h3>${escapeHTML(category)}</h3>
            <p><strong>Location:</strong> ${formatLocationDisplay(location)}</p>
            <p style="white-space:pre-wrap;">${escapeHTML(description)}</p>
            ${imageUrl ? `
                <img
                    src="${escapeHTML(imageUrl)}"
                    alt="Alert image"
                    loading="lazy"
                    style="display:block;width:100%;max-width:520px;max-height:320px;object-fit:contain;border-radius:8px;margin-top:10px;">
            ` : ""}
            <p style="color:#657783;font-size:13px;">
                Posted by ${escapeHTML(reporter)}
                ${date ? " · " + escapeHTML(date) : ""}
            </p>
        </article>
    `;
}

async function loadIncidents() {
    const feed = document.getElementById("alertFeed");
    if (!feed) return;

    feed.textContent = "Loading community alerts...";

    try {
        const data = await api("/api/incidents");
        const incidents = normalizeList(data, ["incidents", "alerts"]);

        feed.innerHTML = incidents.length
            ? incidents.map(renderIncidentCard).join("")
            : "<p>No community alerts have been published yet.</p>";

    } catch (error) {
        console.error("Could not load alerts:", error);
        feed.textContent = "Alerts could not be loaded. Check backend connection.";
    }
}

function setupIncidentForm(session) {
    const form = document.getElementById("alertForm");
    if (!form || form.dataset.rlReady === "true") return;

    form.dataset.rlReady = "true";
    const message = document.getElementById("alertMessage");

    if (!["admin", "volunteer"].includes(session.role)) {
        form.hidden = true;
        return;
    }

    form.addEventListener("submit", async event => {
        event.preventDefault();

        const button = form.querySelector('[type="submit"]');
        const category = document.getElementById("alertCategory")?.value;
        const location = document.getElementById("alertLocation")?.value.trim();
        const description = document.getElementById("alertDescription")?.value.trim();
        const image = document.getElementById("alertImage")?.files?.[0];

        if (!category || !location || !description) {
            if (message) message.textContent = "Enter the category, location, and description.";
            return;
        }

        if (image && !image.type.startsWith("image/")) {
            if (message) message.textContent = "Please select a valid image file.";
            return;
        }

        if (image && image.size > 5 * 1024 * 1024) {
            if (message) message.textContent = "The image must be 5 MB or smaller.";
            return;
        }

        const formData = new FormData();
        formData.append("category", category);
        formData.append("title", category);
        formData.append("location", location);
        formData.append("description", description);
        formData.append("posted_by", session.email);
        formData.append("role", session.role);

        if (image) {
            formData.append("image", image);
        }

        try {
            if (button) button.disabled = true;
            if (message) message.textContent = "Publishing alert...";

            const result = await uploadApi("/api/incidents", formData);

            if (message) {
                message.textContent = result.message || "Alert published successfully.";
            }

            form.reset();
            await loadIncidents();

        } catch (error) {
            if (message) {
                message.textContent = `Could not publish alert: ${error.message}`;
            }
            console.error(error);
        } finally {
            if (button) button.disabled = false;
        }
    });
}

// ========================================
// SHARED REQUEST LOADER
// ========================================
async function getAllRequests() {
    const data = await api("/api/requests");
    return normalizeList(data, ["requests", "data", "items"]);
}

// ========================================
// VOLUNTEER DONATION MANAGEMENT
// ========================================
async function loadVolunteerDonations(session) {
    const table = document.getElementById("volunteerDonationsTable");
    if (!table) return;

    try {
        const data = await api("/api/donations");
        const list = normalizeList(data, ["donations", "data", "items"]);

        if (!list.length) {
            table.innerHTML = '<tr><td colspan="7">No item donations available at this time.</td></tr>';
            return;
        }

        table.innerHTML = list.map(item => {
            const isScheduled = item.status === "Scheduled";

            return `
                <tr>
                    <td>#D-${escapeHTML(item.id)}</td>
                    <td>
                        <div style="font-weight:700;color:#092d46;">${escapeHTML(item.donor_name || "Donor")}</div>
                        <a href="mailto:${escapeHTML(item.donor_email)}" style="font-size:11px;color:#087e78;text-decoration:underline;">
                            ${escapeHTML(item.donor_email)}
                        </a>
                    </td>
                    <td><span class="pill medium">${escapeHTML(item.item_category)}</span></td>
                    <td>${formatLocationDisplay(item.location)}</td>
                    <td>${escapeHTML(item.item_details)}</td>
                    <td>${statusPill(item.status)}</td>
                    <td>
                        ${isScheduled
                            ? `
                                <div style="font-size:11px;color:#07866e;font-weight:700;">
                                    ✓ Scheduled: "${escapeHTML(item.pickup_message)}"
                                    <div style="font-size:10px;color:#657783;font-weight:normal;margin-top:2px;">
                                        Assigned: ${escapeHTML(item.assigned_volunteer || "Volunteer")}
                                    </div>
                                </div>
                            `
                            : `
                                <div style="display:flex;flex-direction:column;gap:6px;">
                                    <input
                                        type="text"
                                        id="msg-${item.id}"
                                        placeholder="e.g. We will pick up today by 4 PM"
                                        style="padding:6px;font-size:11px;border:1px solid #dce8f1;border-radius:6px;outline:none;">
                                    <button
                                        type="button"
                                        class="primary"
                                        data-pickup-id="${item.id}"
                                        style="padding:6px 10px;font-size:11px;">
                                        🚚 Send Message & Pick Up
                                    </button>
                                </div>
                            `
                        }
                    </td>
                </tr>
            `;
        }).join("");

        table.querySelectorAll("[data-pickup-id]").forEach(button => {
            button.addEventListener("click", async () => {
                const id = button.dataset.pickupId;
                const input = document.getElementById(`msg-${id}`);
                const message = (input?.value || "").trim();

                if (!message) {
                    alert("Please enter a pickup message for the donor.");
                    return;
                }

                try {
                    button.disabled = true;
                    button.textContent = "Sending...";

                    await api(`/api/donations/${id}/schedule`, {
                        method: "PATCH",
                        body: JSON.stringify({
                            volunteer_email: session.email,
                            pickup_message: message
                        })
                    });

                    await loadVolunteerDonations(session);

                } catch (error) {
                    showError(error);
                    button.disabled = false;
                    button.textContent = "🚚 Send Message & Pick Up";
                }
            });
        });

    } catch (error) {
        console.error("Could not load donations:", error);
        table.innerHTML = '<tr><td colspan="7">Unable to load item donations. Check the Flask backend.</td></tr>';
    }
}

// ========================================
// VOLUNTEER DASHBOARD (Fallback table handler)
// ========================================
async function setupVolunteerDashboard(session) {
    const table = document.getElementById("volunteerRequestsTable");
    const filter = document.getElementById("statusFilter");

    async function render() {
        const requests = await getAllRequests();
        const selectedStatus = filter?.value || "All";

        const shown = selectedStatus === "All"
            ? requests
            : requests.filter(item => item.status === selectedStatus);

        setText("volOpen", requests.filter(item => (item.status || "Pending") === "Pending").length);
        setText("volProgress", requests.filter(item => item.status === "In Progress").length);
        setText("volCompleted", requests.filter(item => item.status === "Resolved").length);
        setText("volHelped", requests.filter(item => item.status === "Resolved").length);

        if (!table) return;

        table.innerHTML = shown.length
            ? shown.map(item => {
                let volunteerAction = "";

                const rawPhone = item.phone || item.contact || item.mobile;
                const phone = (rawPhone && rawPhone !== "None" && rawPhone !== "null" && rawPhone !== "Not provided") ? rawPhone : "Not provided";
                const blood = item.blood_group || item.bloodGroup || item.blood || "N/A";
                const pin = (item.pincode && item.pincode !== "N/A" && item.pincode !== "None") ? ` (${escapeHTML(item.pincode)})` : "";

                if (item.offer_status === "Offered") {
                    volunteerAction = `
                        <div style="margin-top:8px;padding:8px;background:#e6f8f5;border:1px solid #99ded7;border-radius:8px;">
                            <strong style="color:#087e78;font-size:11px;display:block;">Helper Waiting for Approval:</strong>
                            <span style="font-size:11px;color:#29445d;">${escapeHTML(item.helper_email || "")}</span>
                            <div style="margin-top:6px;">
                                <button
                                    type="button"
                                    class="primary"
                                    data-proceed-id="${escapeHTML(item.id)}"
                                    style="padding:6px 12px;font-size:11px;border-radius:6px;cursor:pointer;">
                                    ⚡ Proceed (Approve)
                                </button>
                            </div>
                        </div>
                    `;
                } else if ((item.status || "Pending") === "Pending") {
                    volunteerAction = `
                        <div style="margin-top:8px;">
                            <button
                                type="button"
                                class="primary"
                                data-proceed-id="${escapeHTML(item.id)}"
                                style="padding:6px 12px;font-size:11px;border-radius:6px;cursor:pointer;">
                                ⚡ Proceed
                            </button>
                        </div>
                    `;
                } else if (item.status === "In Progress") {
                    volunteerAction = `
                        <div style="margin-top:6px;font-size:11px;color:#087e78;font-weight:600;">
                            ✓ Approved / In Progress
                            <div style="color:#72869b;font-weight:normal;">Waiting for helper/user confirmation...</div>
                        </div>
                    `;
                } else if (item.status === "Resolved") {
                    volunteerAction = `
                        <div style="margin-top:6px;font-size:11px;color:#07866e;font-weight:700;">
                            ✓ User Confirmed Helped
                        </div>
                    `;
                }

                return `
                    <tr>
                        <td>#RL-${escapeHTML(item.id)}</td>
                        <td>
                            <div style="font-weight:700;color:#092d46;">${escapeHTML(item.name || "Community Member")}</div>
                            <a href="mailto:${escapeHTML(item.owner || item.email)}" style="font-size:11px;color:#087e78;text-decoration:underline;">
                                ${escapeHTML(item.owner || item.email)}
                            </a>
                            <div style="font-size:11px;color:#475569;margin-top:2px;">📞 ${escapeHTML(phone)}</div>
                        </td>
                        <td>${bloodPill(blood)}</td>
                        <td>${escapeHTML(item.type || item.category)}</td>
                        <td>${formatLocationDisplay(item.location)}${pin}</td>
                        <td>${escapeHTML(getDescription(item))}</td>
                        <td>${priorityPill(item.priority)}</td>
                        <td>
                            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                                ${statusPill(item.status || "Pending")}
                                <select
                                    data-request-id="${escapeHTML(item.id)}"
                                    aria-label="Update request status"
                                    style="padding:4px 8px;border-radius:6px;border:1px solid #d5e0e6;font-size:11px;">
                                    <option value="Pending" ${(item.status || "Pending") === "Pending" ? "selected" : ""}>Pending</option>
                                    <option value="In Progress" ${item.status === "In Progress" ? "selected" : ""}>In Progress</option>
                                    <option value="Resolved" ${item.status === "Resolved" ? "selected" : ""}>Resolved</option>
                                </select>
                            </div>
                            ${volunteerAction}
                            ${proofLinkHTML(item)}
                        </td>
                    </tr>
                `;
            }).join("")
            : '<tr><td colspan="8">No matching requests.</td></tr>';

        table.querySelectorAll("[data-request-id]").forEach(select => {
            select.addEventListener("change", async () => {
                try {
                    select.disabled = true;
                    await api(`/api/requests/${select.dataset.requestId}`, {
                        method: "PATCH",
                        body: JSON.stringify({ status: select.value })
                    });
                    await render();
                } catch (error) {
                    showError(error);
                    await render();
                }
            });
        });

        table.querySelectorAll("[data-proceed-id]").forEach(button => {
            button.addEventListener("click", async () => {
                const id = button.dataset.proceedId;

                try {
                    button.disabled = true;
                    button.textContent = "Processing...";

                    await api(`/api/requests/${id}`, {
                        method: "PATCH",
                        body: JSON.stringify({
                            action: "proceed",
                            status: "In Progress",
                            offer_status: "Approved",
                            volunteer_email: session.email
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

    if (filter && filter.dataset.rlReady !== "true") {
        filter.dataset.rlReady = "true";
        filter.addEventListener("change", () => {
            render().catch(showError);
        });
    }

    setupIncidentForm(session);

    await Promise.all([
        render(),
        loadIncidents(),
        loadVolunteerDonations(session)
    ]);
}

// ========================================
// ADMIN DASHBOARD
// ========================================
async function setupAdminDashboard(session) {
    const volunteerTable = document.getElementById("volunteerApplicationsTable");
    const requestTable = document.getElementById("adminRequestsTable");
    const donationTable = document.getElementById("adminDonationsTable");

    async function render() {
        const [requestData, volunteerData, donationData] = await Promise.all([
            api("/api/requests").catch(() => []),
            api("/api/volunteers").catch(() => []),
            api("/api/donations").catch(() => [])
        ]);

        const requests = normalizeList(requestData, ["requests", "data", "items"]);
        const volunteers = normalizeList(volunteerData, ["volunteers", "data", "items"]);
        const donations = normalizeList(donationData, ["donations", "data", "items"]);

        setText("adminRequestCount", requests.length);
        setText("adminPendingVolunteers", volunteers.filter(item => (item.status || "Pending") === "Pending").length);
        setText("adminOpenRequests", requests.filter(item => item.status !== "Resolved").length);

        // VOLUNTEER APPLICATIONS
        if (volunteerTable) {
            volunteerTable.innerHTML = volunteers.length
                ? volunteers.map(item => `
                    <tr>
                        <td>${escapeHTML(item.name)}</td>
                        <td>${escapeHTML(item.email)}</td>
                        <td>${escapeHTML(item.phone)}</td>
                        <td>${escapeHTML(item.skill)}</td>
                        <td>${statusPill(item.status || "Pending")}</td>
                        <td>
                            ${(item.status || "Pending") === "Pending"
                                ? `
                                    <button
                                        type="button"
                                        data-volunteer-id="${escapeHTML(item.id)}"
                                        data-action="Approved">
                                        Approve
                                    </button>
                                    <button
                                        type="button"
                                        data-volunteer-id="${escapeHTML(item.id)}"
                                        data-action="Rejected">
                                        Reject
                                    </button>
                                `
                                : "Reviewed"
                            }
                        </td>
                    </tr>
                `).join("")
                : '<tr><td colspan="6">No applications yet.</td></tr>';

            volunteerTable.querySelectorAll("[data-action]").forEach(button => {
                button.addEventListener("click", async () => {
                    try {
                        button.disabled = true;
                        await api(`/api/volunteers/${button.dataset.volunteerId}`, {
                            method: "PATCH",
                            body: JSON.stringify({ status: button.dataset.action })
                        });
                        await render();
                    } catch (error) {
                        showError(error);
                        await render();
                    }
                });
            });
        }

        // EMERGENCY REQUESTS
        if (requestTable) {
            requestTable.innerHTML = requests.length
                ? requests.map(item => {
                    const rawPhone = item.phone || item.contact || item.mobile;
                    const phone = (rawPhone && rawPhone !== "None" && rawPhone !== "null" && rawPhone !== "Not provided") ? rawPhone : "Not provided";
                    const blood = item.blood_group || item.bloodGroup || item.blood || "N/A";
                    const pin = (item.pincode && item.pincode !== "N/A" && item.pincode !== "None") ? ` (${escapeHTML(item.pincode)})` : "";

                    return `
                        <tr>
                            <td>#RL-${escapeHTML(item.id)}</td>
                            <td>
                                <div style="font-weight:700;color:#092d46;">${escapeHTML(item.name || "User")}</div>
                                <a href="mailto:${escapeHTML(item.owner || item.email)}" style="font-size:11px;color:#087e78;text-decoration:underline;">
                                    ${escapeHTML(item.owner || item.email)}
                                </a>
                                <div style="font-size:11px;color:#475569;margin-top:2px;">📞 ${escapeHTML(phone)}</div>
                            </td>
                            <td>${bloodPill(blood)}</td>
                            <td>${escapeHTML(item.type || item.category)}</td>
                            <td>${formatLocationDisplay(item.location)}${pin}</td>
                            <td>${escapeHTML(getDescription(item))}</td>
                            <td>${priorityPill(item.priority)}</td>
                            <td>
                                ${statusPill(item.status || "Pending")}
                                ${proofLinkHTML(item)}
                            </td>
                        </tr>
                    `;
                }).join("")
                : '<tr><td colspan="8">No requests yet.</td></tr>';
        }

        // ITEM DONATIONS
        if (donationTable) {
            donationTable.innerHTML = donations.length
                ? donations.map(item => `
                    <tr>
                        <td>#D-${escapeHTML(item.id)}</td>
                        <td>
                            <div style="font-weight:700;color:#092d46;">${escapeHTML(item.donor_name || "Donor")}</div>
                            <a href="mailto:${escapeHTML(item.donor_email)}" style="font-size:11px;color:#087e78;text-decoration:underline;">
                                ${escapeHTML(item.donor_email)}
                            </a>
                        </td>
                        <td>${escapeHTML(item.item_category)}</td>
                        <td>${formatLocationDisplay(item.location)}</td>
                        <td>${escapeHTML(item.item_details)}</td>
                        <td>${statusPill(item.status || "Available")}</td>
                        <td>${escapeHTML(item.pickup_message || "No pickup scheduled")}</td>
                    </tr>
                `).join("")
                : '<tr><td colspan="7">No donations yet.</td></tr>';
        }
    }

    setupIncidentForm(session);

    await Promise.all([
        render(),
        loadIncidents()
    ]);
}

// ========================================
// START APPLICATION
// ========================================
async function init() {
    setupLogin();
    setupVolunteerRegistration();
    setupLogout();

    const page = document.body.dataset.page;
    if (!page) return;

    const normalizedPage = normalizeRole(page);
    if (!normalizedPage) return;

    // User dashboard runs its own inline script.
    if (normalizedPage === "user") return;

    const session = await requireSession(normalizedPage);
    if (!session) return;

    try {
        if (normalizedPage === "volunteer") {
            await setupVolunteerDashboard(session);
        } else if (normalizedPage === "admin") {
            await setupAdminDashboard(session);
        }
    } catch (error) {
        console.error("Dashboard loading failed:", error);
        showError(error);
    }
}

document.addEventListener("DOMContentLoaded", init);