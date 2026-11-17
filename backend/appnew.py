import os
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
import re
from io import BytesIO
from mimetypes import guess_type

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.utils import secure_filename

# ==================================================
# 1. PROJECT CONFIGURATION
# ==================================================

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent
UPLOAD_DIR = BASE_DIR / "uploads"
AVATAR_DIR = UPLOAD_DIR / "avatars"

AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
S3_BUCKET = os.environ.get("S3_BUCKET")
s3_client = boto3.client("s3", region_name=AWS_REGION) if S3_BUCKET else None

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
AVATAR_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB

app = Flask(
    __name__,
    static_folder=str(FRONTEND_DIR),
    static_url_path="/static"
)

# Local development uses SQLite by default.
# To connect to RDS, set DB_HOST, DB_USER, and DB_PASSWORD in the environment.
if os.environ.get("DB_HOST"):
    required_db_settings = ("DB_USER", "DB_PASSWORD", "DB_HOST")
    missing_settings = [
        key for key in required_db_settings if not os.environ.get(key)
    ]
    if missing_settings:
        raise RuntimeError(
            "Missing database environment variables: "
            + ", ".join(missing_settings)
        )

    database_url = URL.create(
        drivername="mysql+pymysql",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        database=os.environ.get("DB_NAME", "relieflink")
    )
else:
    database_url = URL.create(
        drivername="sqlite",
        database=str(BASE_DIR / "relieflink.db")
    )

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_SIZE
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

db = SQLAlchemy(app)

# ==================================================
# 2. DATABASE MODELS
# ==================================================

class EmergencyRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    owner = db.Column(db.String(150), nullable=True)
    type = db.Column(db.String(50), nullable=True)
    location = db.Column(db.String(200), nullable=True)
    priority = db.Column(db.String(20), nullable=True)
    details = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="Pending")

    helper_email = db.Column(db.String(150), nullable=True)
    helper_name = db.Column(db.String(100), nullable=True)
    volunteer_email = db.Column(db.String(150), nullable=True)
    volunteer_name = db.Column(db.String(100), nullable=True)
    offer_status = db.Column(db.String(30), nullable=True, default=None)


class VolunteerApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False, unique=True)
    phone = db.Column(db.String(30), nullable=False)
    skill = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="Pending")


class HelpOffer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, nullable=False, index=True)
    helper_email = db.Column(db.String(150), nullable=True)
    helper_name = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(30), nullable=True)
    volunteer_email = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)


class Incident(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(80), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)
    posted_by = db.Column(db.String(150), nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )


class ItemDonation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    donor_email = db.Column(db.String(150), nullable=False)
    donor_name = db.Column(db.String(100), nullable=False)
    item_category = db.Column(db.String(50), nullable=False)
    item_details = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="Available")
    assigned_volunteer = db.Column(db.String(150), nullable=True)
    pickup_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

# ==================================================
# 3. DATABASE INITIALIZATION & MIGRATION
# ==================================================

def initialize_database():
    with app.app_context():
        db.create_all()

        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()

        if "emergency_request" in table_names:
            existing_columns = {
                column["name"]
                for column in inspector.get_columns("emergency_request")
            }

            # Add columns used by the current application when upgrading an
            # older SQLite or MySQL database. Names/types are fixed constants.
            new_columns = {
                "owner": "VARCHAR(150)",
                "type": "VARCHAR(50)",
                "location": "VARCHAR(200)",
                "priority": "VARCHAR(20)",
                "details": "TEXT",
                "helper_email": "VARCHAR(150)",
                "helper_name": "VARCHAR(100)",
                "volunteer_email": "VARCHAR(150)",
                "volunteer_name": "VARCHAR(100)",
                "offer_status": "VARCHAR(30)",
            }

            with db.engine.begin() as connection:
                for column_name, column_type in new_columns.items():
                    if column_name not in existing_columns:
                        connection.exec_driver_sql(
                            f"ALTER TABLE emergency_request "
                            f"ADD COLUMN {column_name} {column_type}"
                        )

# ==================================================
# 4. STORAGE HELPERS (S3 with local-development fallback)
# ==================================================

def store_image(file_storage, key, local_path):
    if s3_client:
        content_type = file_storage.mimetype or guess_type(file_storage.filename)[0] or "application/octet-stream"
        file_storage.stream.seek(0)
        s3_client.upload_fileobj(
            file_storage.stream, S3_BUCKET, key,
            ExtraArgs={"ContentType": content_type}
        )
    else:
        file_storage.save(local_path)


def remove_stored_image(key, local_path):
    try:
        if s3_client:
            s3_client.delete_object(Bucket=S3_BUCKET, Key=key)
        elif local_path.exists():
            local_path.unlink()
    except (BotoCoreError, ClientError, OSError):
        app.logger.exception("Could not remove uploaded image %s", key)


def serve_stored_image(key, filename, local_directory):
    if not s3_client:
        return send_from_directory(local_directory, filename)
    try:
        result = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        content_type = result.get("ContentType") or guess_type(filename)[0] or "application/octet-stream"
        return send_file(
            BytesIO(result["Body"].read()),
            mimetype=content_type,
            download_name=filename,
            max_age=0
        )
    except (BotoCoreError, ClientError):
        app.logger.exception("Could not retrieve image from S3: %s", key)
        return error_response("Image not found or unavailable.", 404)


# ==================================================
# 5. HELPER FUNCTIONS
# ==================================================

def error_response(message, status_code=400):
    return jsonify({"success": False, "error": message}), status_code

def valid_email(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))

def request_to_dict(item):
    owner = item.owner or item.name or ""
    return {
        "id": item.id,
        "name": item.name,
        "owner": owner,
        "email": owner,
        "category": item.category,
        "type": item.type or item.category,
        "location": item.location or "",
        "priority": item.priority or "Medium",
        "description": item.description,
        "details": item.details or item.description,
        "status": item.status,
        "helper_email": item.helper_email,
        "helper_name": item.helper_name,
        "volunteer_email": item.volunteer_email,
        "volunteer_name": item.volunteer_name,
        "offer_status": item.offer_status
    }

def volunteer_to_dict(item):
    return {
        "id": item.id,
        "name": item.name,
        "email": item.email,
        "phone": item.phone,
        "skill": item.skill,
        "status": item.status
    }

def incident_to_dict(item):
    image_url = (
        f"/api/incidents/uploads/{item.image_filename}"
        if item.image_filename else None
    )
    created_at = item.created_at
    if created_at and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return {
        "id": item.id,
        "category": item.category,
        "location": item.location,
        "description": item.description,
        "image": image_url,
        "image_url": image_url,
        "posted_by": item.posted_by or "Community member",
        "created_at": created_at.isoformat() if created_at else None
    }

def donation_to_dict(item):
    created_at = item.created_at
    if created_at and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return {
        "id": item.id,
        "donor_email": item.donor_email,
        "donor_name": item.donor_name,
        "item_category": item.item_category,
        "item_details": item.item_details,
        "location": item.location,
        "status": item.status,
        "assigned_volunteer": item.assigned_volunteer,
        "pickup_message": item.pickup_message,
        "created_at": created_at.isoformat() if created_at else None
    }

@app.after_request
def disable_browser_cache(response):
    path = request.path
    if path == "/" or path.endswith(".html") or path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response

# ==================================================
# 5. FRONTEND PAGES
# ==================================================

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

# ==================================================
# 6. HEALTH CHECK
# ==================================================

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "success": True,
        "message": "ReliefLink backend is running",
        "status": "success",
        "database_mode": "mysql" if os.environ.get("DB_HOST") else "sqlite",
        "image_storage": "s3" if s3_client else "local"
    })

# ==================================================
# 7. EMERGENCY REQUEST API
# ==================================================

@app.route("/api/requests", methods=["GET"])
def list_requests():
    try:
        query = EmergencyRequest.query
        owner = request.args.get("owner", "").strip().lower()
        if owner:
            query = query.filter(db.func.lower(EmergencyRequest.owner) == owner)

        items = query.order_by(EmergencyRequest.id.desc()).all()
        return jsonify([request_to_dict(item) for item in items])
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Could not retrieve emergency requests")
        return error_response("Could not load emergency requests.", 500)

@app.route("/api/requests", methods=["POST"])
def create_request():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("Invalid request data. Please submit JSON.")

    owner = str(data.get("owner") or data.get("email") or "").strip().lower()
    request_type = str(data.get("type") or data.get("category") or "").strip()
    location = str(data.get("location") or "").strip()
    priority = str(data.get("priority") or "Medium").strip().title()
    details = str(data.get("details") or data.get("description") or "").strip()

    if not owner:
        return error_response("User email is missing. Please sign in again.")
    if len(owner) > 150:
        return error_response("User email must be 150 characters or fewer.")
    if not request_type:
        return error_response("Please select a request type.")
    if len(request_type) > 50:
        return error_response("Request type must be 50 characters or fewer.")
    if not location:
        return error_response("Please enter the request location.")
    if len(location) > 200:
        return error_response("Location must be 200 characters or fewer.")
    if not details:
        return error_response("Please enter the request details.")
    if priority not in {"Low", "Medium", "High"}:
        priority = "Medium"

    item = EmergencyRequest(
        name=owner.split("@")[0],
        category=request_type,
        description=details,
        owner=owner,
        type=request_type,
        location=location,
        priority=priority,
        details=details,
        status="Pending"
    )

    try:
        db.session.add(item)
        db.session.commit()
        saved_request = request_to_dict(item)
        return jsonify({
            "success": True,
            "message": "Emergency request submitted successfully.",
            "request": saved_request,
            **saved_request
        }), 201
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Failed to create emergency request")
        return error_response("Could not save the emergency request. Please try again.", 500)

@app.route("/api/requests/<int:request_id>/offers", methods=["POST"])
def offer_help(request_id):
    item = db.session.get(EmergencyRequest, request_id)
    if item is None:
        return error_response("Request not found.", 404)

    data = request.get_json(silent=True) or {}
    helper_email = str(data.get("helper_email") or "").strip().lower()
    helper_name = str(data.get("helper_name") or "Community Member").strip()

    if not helper_email:
        return error_response("Helper email is required.")
    if item.owner and item.owner.strip().lower() == helper_email:
        return error_response("You cannot offer help for your own request.")
    if item.status == "Resolved":
        return error_response("This request has already been resolved.")
    if item.offer_status in {"Offered", "Approved"} and (item.helper_email or "").strip().lower() != helper_email:
        return error_response("Another community member has already offered help for this request.", 409)

    item.helper_email = helper_email
    item.helper_name = helper_name
    item.offer_status = "Offered"

    try:
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Your help offer was sent. Please wait for volunteer approval.",
            "request": request_to_dict(item)
        })
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Failed to submit help offer")
        return error_response("Could not submit help offer.", 500)

@app.route("/api/requests/<int:request_id>", methods=["PATCH"])
def update_request(request_id):
    item = db.session.get(EmergencyRequest, request_id)
    if item is None:
        return error_response("Request not found.", 404)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("Please submit valid JSON data.")

    if data.get("action") in ["proceed", "approve"]:
        volunteer_email = str(data.get("volunteer_email") or "").strip().lower()
        item.volunteer_email = volunteer_email or item.volunteer_email
        item.offer_status = "Approved"
        item.status = "In Progress"

    if "confirmation" in data:
        confirmation = data.get("confirmation")
        if confirmation == "Helped":
            item.offer_status = "Helped"
            item.status = "Resolved"
        elif confirmation == "Not Helped":
            item.offer_status = "Not Helped"
            item.status = "Pending"
            item.helper_email = None
            item.helper_name = None
        else:
            return error_response("Confirmation must be Helped or Not Helped.")

    if "status" in data:
        status = data.get("status")
        if status not in {"Pending", "In Progress", "Resolved"}:
            return error_response("Status must be Pending, In Progress, or Resolved.")
        item.status = status

    try:
        db.session.commit()
        updated_request = request_to_dict(item)
        return jsonify({
            "success": True,
            "message": "Request updated successfully.",
            "request": updated_request,
            **updated_request
        })
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Failed to update emergency request")
        return error_response("Could not update request status.", 500)

# ==================================================
# 8. VOLUNTEER REGISTRATION API
# ==================================================

@app.route("/api/volunteers", methods=["GET"])
def list_volunteers():
    try:
        items = VolunteerApplication.query.order_by(VolunteerApplication.id.desc()).all()
        return jsonify([volunteer_to_dict(item) for item in items])
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Could not retrieve volunteers")
        return error_response("Could not load volunteer applications.", 500)

@app.route("/api/volunteers", methods=["POST"])
def create_volunteer():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("Please submit valid JSON data.")

    name = str(data.get("name") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    phone = str(data.get("phone") or "").strip()
    skill = str(data.get("skill") or "").strip()

    if not all([name, email, phone, skill]):
        return error_response("Name, email, phone, and skill are required.")
    if len(name) > 100:
        return error_response("Name must be 100 characters or fewer.")
    if len(email) > 150 or not valid_email(email):
        return error_response("Please enter a valid email address.")
    if len(phone) > 30:
        return error_response("Phone must be 30 characters or fewer.")
    if len(skill) > 100:
        return error_response("Skill must be 100 characters or fewer.")

    existing = VolunteerApplication.query.filter_by(email=email).first()
    if existing:
        return error_response("An application with this email already exists.", 409)

    item = VolunteerApplication(name=name, email=email, phone=phone, skill=skill, status="Pending")
    try:
        db.session.add(item)
        db.session.commit()
        saved_volunteer = volunteer_to_dict(item)
        return jsonify({
            "success": True,
            "message": "Volunteer application submitted successfully.",
            "volunteer": saved_volunteer,
            **saved_volunteer
        }), 201
    except IntegrityError:
        db.session.rollback()
        return error_response("An application with this email already exists.", 409)
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Failed to register volunteer")
        return error_response("Could not save the volunteer application.", 500)

@app.route("/api/volunteers/<int:volunteer_id>", methods=["PATCH"])
def update_volunteer(volunteer_id):
    item = db.session.get(VolunteerApplication, volunteer_id)
    if item is None:
        return error_response("Volunteer not found.", 404)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("Please submit valid JSON data.")

    status = data.get("status")
    if status not in {"Approved", "Rejected"}:
        return error_response("Status must be Approved or Rejected.")

    try:
        item.status = status
        db.session.commit()
        updated_volunteer = volunteer_to_dict(item)
        return jsonify({
            "success": True,
            "message": "Volunteer application updated.",
            "volunteer": updated_volunteer,
            **updated_volunteer
        })
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Failed to update volunteer")
        return error_response("Could not update volunteer status.", 500)

# ==================================================
# 9. COMMUNITY ALERTS API
# ==================================================

@app.route("/api/incidents", methods=["GET"])
def list_incidents():
    try:
        items = Incident.query.order_by(Incident.id.desc()).all()
        return jsonify([incident_to_dict(item) for item in items])
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Could not retrieve community alerts")
        return error_response("Could not load community alerts.", 500)

@app.route("/api/incidents", methods=["POST"])
def create_incident():
    category = request.form.get("category", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    posted_by = request.form.get("posted_by", "").strip()

    if not all([category, location, description]):
        return error_response("Category, location, and description are required.")
    if len(category) > 80:
        return error_response("Category must be 80 characters or fewer.")
    if len(location) > 200:
        return error_response("Location must be 200 characters or fewer.")
    if len(posted_by) > 150:
        return error_response("Posted-by value is too long.")

    image_file = request.files.get("image")
    saved_filename = None

    if image_file and image_file.filename:
        original_name = secure_filename(image_file.filename)
        if not original_name or "." not in original_name:
            return error_response("Please select a valid image file.")

        extension = original_name.rsplit(".", 1)[1].lower()
        if extension not in ALLOWED_IMAGE_EXTENSIONS:
            return error_response("Unsupported image type. Use PNG, JPG, JPEG, GIF, or WEBP.")

        saved_filename = f"{uuid4().hex}.{extension}"
        upload_path = UPLOAD_DIR / saved_filename
        s3_key = f"incidents/{saved_filename}"

        try:
            store_image(image_file, s3_key, upload_path)
        except (BotoCoreError, ClientError, OSError):
            app.logger.exception("Failed to store uploaded incident image")
            return error_response("Could not save the uploaded image.", 500)

    item = Incident(
        category=category,
        location=location,
        description=description,
        image_filename=saved_filename,
        posted_by=posted_by or "Community member"
    )

    try:
        db.session.add(item)
        db.session.commit()
        saved_incident = incident_to_dict(item)
        return jsonify({
            "success": True,
            "message": "Community alert published successfully.",
            "incident": saved_incident,
            **saved_incident
        }), 201
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Could not save community alert")
        if saved_filename:
            remove_stored_image(f"incidents/{saved_filename}", UPLOAD_DIR / saved_filename)
        return error_response("Could not save the alert. Please try again.", 500)

@app.route("/api/incidents/uploads/<path:filename>", methods=["GET"])
def get_incident_image(filename):
    return serve_stored_image(f"incidents/{filename}", filename, UPLOAD_DIR)

# ==================================================
# 10. ITEM DONATIONS API
# ==================================================

@app.route("/api/donations", methods=["GET"])
def list_donations():
    try:
        query = ItemDonation.query
        donor_email = request.args.get("donor_email", "").strip().lower()
        if donor_email:
            query = query.filter(db.func.lower(ItemDonation.donor_email) == donor_email)

        items = query.order_by(ItemDonation.id.desc()).all()
        return jsonify([donation_to_dict(item) for item in items])
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Could not retrieve donations")
        return error_response("Could not load donations.", 500)

@app.route("/api/donations", methods=["POST"])
def create_donation():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("Invalid request data. Please submit JSON.")

    donor_email = str(data.get("donor_email") or "").strip().lower()
    donor_name = str(data.get("donor_name") or donor_email.split("@")[0]).strip()
    category = str(data.get("category") or data.get("item_category") or "").strip()
    location = str(data.get("location") or "").strip()
    details = str(data.get("details") or data.get("item_details") or "").strip()

    if not donor_email:
        return error_response("Donor email is required.")
    if not category:
        return error_response("Please select a donation category (Food, Medicine, Clothing, etc.).")
    if not location:
        return error_response("Pickup location is required.")
    if not details:
        return error_response("Please describe the items you wish to donate.")

    donation = ItemDonation(
        donor_email=donor_email,
        donor_name=donor_name,
        item_category=category,
        item_details=details,
        location=location,
        status="Available"
    )

    try:
        db.session.add(donation)
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Donation posted successfully! A volunteer will arrange pickup.",
            "donation": donation_to_dict(donation)
        }), 201
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Failed to create item donation")
        return error_response("Could not submit your donation. Please try again.", 500)

@app.route("/api/donations/<int:donation_id>/schedule", methods=["PATCH"])
def schedule_donation_pickup(donation_id):
    item = db.session.get(ItemDonation, donation_id)
    if item is None:
        return error_response("Donation not found.", 404)

    data = request.get_json(silent=True) or {}
    volunteer_email = str(data.get("volunteer_email") or "").strip().lower()
    pickup_message = str(data.get("pickup_message") or "").strip()

    if not pickup_message:
        return error_response("Please provide a pickup message (e.g., 'We will pick up today by 4 PM').")

    item.assigned_volunteer = volunteer_email or "Volunteer Team"
    item.pickup_message = pickup_message
    item.status = "Scheduled"

    try:
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Pickup scheduled and message sent to donor.",
            "donation": donation_to_dict(item)
        })
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Failed to schedule donation pickup")
        return error_response("Could not schedule pickup. Please try again.", 500)

@app.route("/api/donations/<int:donation_id>/status", methods=["PATCH"])
def update_donation_status(donation_id):
    item = db.session.get(ItemDonation, donation_id)
    if item is None:
        return error_response("Donation not found.", 404)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("Please submit valid JSON data.")

    status = data.get("status")
    if status not in {"Available", "Scheduled", "Picked Up"}:
        return error_response("Status must be Available, Scheduled, or Picked Up.")

    volunteer_email = str(data.get("volunteer_email") or "").strip().lower()
    if volunteer_email and not item.assigned_volunteer:
        item.assigned_volunteer = volunteer_email

    item.status = status

    try:
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Donation status updated.",
            "donation": donation_to_dict(item)
        })
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Failed to update donation status")
        return error_response("Could not update donation status.", 500)

# ==================================================
# 11. PROFILE PHOTO UPLOAD & AVATAR API
# ==================================================

@app.route("/api/profile-photo", methods=["POST"])
def upload_profile_photo():
    image_file = request.files.get("profile_photo")
    if not image_file or not image_file.filename:
        return error_response("No profile photo file provided.")

    original_name = secure_filename(image_file.filename)
    if not original_name or "." not in original_name:
        return error_response("Please select a valid image file.")

    extension = original_name.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return error_response("Unsupported image format. Use PNG, JPG, JPEG, GIF, or WEBP.")

    saved_filename = f"avatar_{uuid4().hex}.{extension}"
    upload_path = AVATAR_DIR / saved_filename
    s3_key = f"avatars/{saved_filename}"

    try:
        store_image(image_file, s3_key, upload_path)
    except (BotoCoreError, ClientError, OSError):
        app.logger.exception("Failed to store avatar image")
        return error_response("Could not save the avatar image.", 500)

    photo_url = f"/api/avatars/{saved_filename}"
    return jsonify({
        "success": True,
        "message": "Profile photo uploaded successfully.",
        "photo_url": photo_url
    }), 201

@app.route("/api/avatars/<path:filename>", methods=["GET"])
def get_avatar_image(filename):
    return serve_stored_image(f"avatars/{filename}", filename, AVATAR_DIR)

# ==================================================
# 12. ERROR HANDLERS
# ==================================================

@app.errorhandler(413)
def file_too_large(error):
    return error_response("Request or image is too large. Maximum upload size is 5 MB.", 413)

@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return error_response("API endpoint not found.", 404)
    return error

@app.errorhandler(405)
def method_not_allowed(error):
    if request.path.startswith("/api/"):
        return error_response("HTTP method not allowed for this endpoint.", 405)
    return error

# ==================================================
# 13. START APPLICATION (0.0.0.0 for LAN / ngrok access)
# ==================================================

if __name__ == "__main__":
    initialize_database()
    app.run(host="0.0.0.0", port=5000, debug=True)