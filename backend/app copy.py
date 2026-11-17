
from pathlib import Path

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy

FRONTEND_DIR = Path(__file__).resolve().parent.parent

app = Flask(
    __name__,
    static_folder=str(FRONTEND_DIR),
    static_url_path="/static"
)

# Database configuration
BASE_DIR = Path(__file__).resolve().parent
app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + str(BASE_DIR / "relieflink.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# Emergency request database model
class EmergencyRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(
        db.String(30), nullable=False, default="Pending"
    )


# Volunteer application database model
class VolunteerApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False, unique=True)
    phone = db.Column(db.String(30), nullable=False)
    skill = db.Column(db.String(100), nullable=False)
    status = db.Column(
        db.String(30), nullable=False, default="Pending"
    )


# Home page
@app.route("/")
def home():
    return app.send_static_file("login.html")


@app.route("/login.html")
def login_page():
    return app.send_static_file("login.html")


@app.route("/register-volunteer.html")
def volunteer_registration_page():
    return app.send_static_file("register-volunteer.html")


@app.route("/user-dashboard.html")
def user_dashboard_page():
    return app.send_static_file("user-dashboard.html")


@app.route("/volunteer-dashboard.html")
def volunteer_dashboard_page():
    return app.send_static_file("volunteer-dashboard.html")


@app.route("/admin-dashboard.html")
def admin_dashboard_page():
    return app.send_static_file("admin-dashboard.html")


# Backend health check
@app.route("/api/health")
def health():
    return jsonify({
        "message": "ReliefLink backend is running",
        "status": "success"
    })


# Get all emergency requests
@app.route("/api/requests", methods=["GET"])
def list_requests():
    items = EmergencyRequest.query.order_by(
        EmergencyRequest.id.desc()
    ).all()

    return jsonify([
        {
            "id": item.id,
            "name": item.name,
            "category": item.category,
            "description": item.description,
            "status": item.status
        }
        for item in items
    ])


# Create an emergency request
@app.route("/api/requests", methods=["POST"])
def create_request():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "")).strip()
    description = str(data.get("description", "")).strip()

    if not name or not category or not description:
        return jsonify({
            "error": "Name, category, and description are required"
        }), 400

    item = EmergencyRequest(
        name=name,
        category=category,
        description=description,
        status="Pending"
    )

    db.session.add(item)
    db.session.commit()

    return jsonify({
        "message": "Emergency request created",
        "id": item.id,
        "status": item.status
    }), 201


# Update an emergency request status
@app.route("/api/requests/<int:request_id>", methods=["PATCH"])
def update_request(request_id):
    item = db.session.get(EmergencyRequest, request_id)

    if item is None:
        return jsonify({"error": "Request not found"}), 404

    data = request.get_json(silent=True) or {}
    status = data.get("status")

    allowed_statuses = {
        "Pending", "In Progress", "Resolved"
    }

    if status not in allowed_statuses:
        return jsonify({"error": "Invalid status"}), 400

    item.status = status
    db.session.commit()

    return jsonify({
        "message": "Request status updated",
        "id": item.id,
        "status": item.status
    })


# Get all volunteer applications
@app.route("/api/volunteers", methods=["GET"])
def list_volunteers():
    items = VolunteerApplication.query.order_by(
        VolunteerApplication.id.desc()
    ).all()

    return jsonify([
        {
            "id": item.id,
            "name": item.name,
            "email": item.email,
            "phone": item.phone,
            "skill": item.skill,
            "status": item.status
        }
        for item in items
    ])


# Submit a volunteer application
@app.route("/api/volunteers", methods=["POST"])
def create_volunteer():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    phone = str(data.get("phone", "")).strip()
    skill = str(data.get("skill", "")).strip()

    if not all([name, email, phone, skill]):
        return jsonify({
            "error": "Name, email, phone, and skill are required"
        }), 400

    existing = VolunteerApplication.query.filter_by(
        email=email
    ).first()

    if existing:
        return jsonify({
            "error": "An application with this email already exists"
        }), 409

    item = VolunteerApplication(
        name=name,
        email=email,
        phone=phone,
        skill=skill,
        status="Pending"
    )

    db.session.add(item)
    db.session.commit()

    return jsonify({
        "message": "Volunteer application submitted",
        "id": item.id,
        "status": item.status
    }), 201


# Approve or reject a volunteer application
@app.route("/api/volunteers/<int:volunteer_id>", methods=["PATCH"])
def update_volunteer(volunteer_id):
    item = db.session.get(
        VolunteerApplication, volunteer_id
    )

    if item is None:
        return jsonify({"error": "Volunteer not found"}), 404

    data = request.get_json(silent=True) or {}
    status = data.get("status")

    if status not in {"Approved", "Rejected"}:
        return jsonify({"error": "Invalid status"}), 400

    item.status = status
    db.session.commit()

    return jsonify({
        "message": "Volunteer application updated",
        "id": item.id,
        "status": item.status
    })


# Create database tables if they do not exist
with app.app_context():
    db.create_all()


# Start the Flask server
if __name__ == "__main__":
    app.run(debug=True)
