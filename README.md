# ReliefLink Dashboard Prototype

## Pages
- `login.html`: select Community User, Volunteer, or Administrator.
- `register-volunteer.html`: submit a volunteer application.
- `user-dashboard.html`: submit and track requests.
- `volunteer-dashboard.html`: view all requests and update statuses.
- `admin-dashboard.html`: approve/reject volunteer applications and monitor requests.
- `styles.css`: shared teal-and-white theme.
- `app.js`: demo interactions using browser localStorage.

## Run in VS Code
1. Extract this ZIP and open the `ReliefLink_Dashboards` folder in VS Code.
2. Open `login.html` in a browser, or use the Live Server extension.
3. Choose a role and enter any email/password to open that role's dashboard.
4. Test a volunteer application via `register-volunteer.html`, then sign in as Administrator to approve/reject it.
5. Sign in as Community User to submit a request, then as Volunteer to update its status.

## Important
This is a front-end prototype only. Login does not validate passwords, role selection is not secure authorization, and data is stored only in the same browser's localStorage. It is not shared across devices and is not suitable for real emergency response. A production system needs secure server-side authentication, role-based authorization, a database, audit logs, and emergency-response safeguards. Do not enter real or sensitive data.
