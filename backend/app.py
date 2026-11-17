import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import re
import json
from io import BytesIO
from mimetypes import guess_type
import urllib.request

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, jsonify, request, send_from_directory, send_file, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ==================================================
# 1. PROJECT CONFIGURATION
# ==================================================

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent
UPLOAD_DIR = BASE_DIR / "uploads"
AVATAR_DIR = UPLOAD_DIR / "avatars"
PROOF_DIR = UPLOAD_DIR / "proofs"

AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
S3_BUCKET = os.environ.get("S3_BUCKET")
s3_client = boto3.client("s3", region_name=AWS_REGION) if S3_BUCKET else None

# AWS Lambda Client configuration for async alerts
lambda_client = boto3.client(
    "lambda",
    region_name=AWS_REGION,
    config=Config(retries={"max_attempts": 2})
)
LAMBDA_ALERT_FUNCTION = os.environ.get("LAMBDA_ALERT_FUNCTION", "relieflink-alert-processor")

# Amazon SES Client configuration
ses_client = boto3.client("ses", region_name=AWS_REGION)
SES_SENDER_EMAIL = os.environ.get("SES_SENDER_EMAIL", "pcasiyadh@gmail.com")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
AVATAR_DIR.mkdir(parents=True, exist_ok=True)
PROOF_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB

app = Flask(
    __name__,
    static_folder=str(FRONTEND_DIR),
    static_url_path="/static"
)
CORS(app, supports_credentials=True)

# Database Connection (RDS MySQL if DB_HOST exists, else SQLite)
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

app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or "relieflink-production-secret-key-2026"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_SIZE
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

db = SQLAlchemy(app)

# ==================================================
# 2. DATABASE MODELS
# ==================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")
    phone = db.Column(db.String(30), nullable=True)
    blood_group = db.Column(db.String(10), nullable=True)
    pincode = db.Column(db.String(10), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class EmergencyRequest(db.Model):
    __tablename__ = "emergency_request"
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
    proof_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class VolunteerApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False, unique=True)
    phone = db.Column(db.String(30), nullable=False)
    skill = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="Pending")
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class HelpOffer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, nullable=False, index=True)
    helper_email = db.Column(db.String(150), nullable=True)
    helper_name = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(30), nullable=True)
    volunteer_email = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=True)

class Incident(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(80), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)
    posted_by = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

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
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

# ==================================================
# 3. DATABASE INITIALIZATION & MIGRATION
# ==================================================

def initialize_database():
    with app.app_context():
        db.create_all()

        admin_email = os.environ.get("ADMIN_EMAIL", "admin@relieflink.org").strip().lower()
        admin_password = os.environ.get("ADMIN_INITIAL_PASSWORD", "Admin@123")
        if admin_email and admin_password and valid_email(admin_email):
            existing_admin = User.query.filter(db.func.lower(User.email) == admin_email).first()
            if not existing_admin:
                db.session.add(User(
                    name="Administrator",
                    email=admin_email,
                    password_hash=generate_password_hash(admin_password),
                    role="admin"
                ))
                db.session.commit()

        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()

        if "emergency_request" in table_names:
            existing_columns = {
                column["name"]
                for column in inspector.get_columns("emergency_request")
            }

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
                "proof_filename": "VARCHAR(255)",
                "created_at": "DATETIME"
            }

            with db.engine.begin() as connection:
                for column_name, column_type in new_columns.items():
                    if column_name not in existing_columns:
                        connection.exec_driver_sql(
                            f"ALTER TABLE emergency_request ADD COLUMN {column_name} {column_type}"
                        )

        if "volunteer_application" in table_names:
            existing_vol_cols = {
                column["name"]
                for column in inspector.get_columns("volunteer_application")
            }
            vol_columns = {
                "phone": "VARCHAR(30)",
                "skill": "VARCHAR(100)",
                "status": "VARCHAR(30)",
                "created_at": "DATETIME"
            }
            with db.engine.begin() as connection:
                for column_name, column_type in vol_columns.items():
                    if column_name not in existing_vol_cols:
                        connection.exec_driver_sql(
                            f"ALTER TABLE volunteer_application ADD COLUMN {column_name} {column_type}"
                        )

        if "user" in table_names:
            existing_user_cols = {
                column["name"]
                for column in inspector.get_columns("user")
            }
            user_columns = {
                "phone": "VARCHAR(30)",
                "blood_group": "VARCHAR(10)",
                "pincode": "VARCHAR(10)",
                "created_at": "DATETIME"
            }
            with db.engine.begin() as connection:
                for column_name, column_type in user_columns.items():
                    if column_name not in existing_user_cols:
                        connection.exec_driver_sql(
                            f"ALTER TABLE user ADD COLUMN {column_name} {column_type}"
                        )

# ==================================================
# 4. STORAGE & AWS LAMBDA / SES HELPERS
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
        app.logger.exception("Could not remove stored image %s", key)

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

API_GATEWAY_URL = "https://pxksn3peq5.execute-api.ap-south-1.amazonaws.com/alerts"

def trigger_lambda_emergency_alert(req_data):
    """Invokes Lambda serverlessly through Amazon API Gateway."""
    try:
        payload = json.dumps({
            "request_id": req_data.get("id"),
            "category": req_data.get("type") or req_data.get("category"),
            "blood_group": req_data.get("blood_group", "N/A"),
            "location": req_data.get("location"),
            "phone": req_data.get("phone", "N/A"),
            "requester": req_data.get("name") or req_data.get("owner"),
            "priority": req_data.get("priority", "Medium")
        }).encode("utf-8")

        req = urllib.request.Request(
            API_GATEWAY_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=5) as response:
            print(f"--> [API GATEWAY TRIGGERED] Dispatched Request #{req_data.get('id')} (HTTP {response.status})", flush=True)

    except Exception as e:
        print(f"--> [API GATEWAY ERROR] Failed to dispatch via Gateway: {e}", flush=True)

def send_transactional_email(to_email, subject, body_text, body_html=None):
    """Sends transactional emails via Amazon SES."""
    if not SES_SENDER_EMAIL or not to_email:
        return False

    try:
        message_body = {
            "Text": {"Charset": "UTF-8", "Data": body_text}
        }
        if body_html:
            message_body["Html"] = {"Charset": "UTF-8", "Data": body_html}

        response = ses_client.send_email(
            Source=SES_SENDER_EMAIL,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Charset": "UTF-8", "Data": subject},
                "Body": message_body
            }
        )
        msg_id = response.get("MessageId", "N/A")
        app.logger.info(f"--> [SES SENT] Delivered transactional email to {to_email} (Msg ID: {msg_id})")
        print(f"--> [SES SENT] Delivered transactional email to {to_email} (Msg ID: {msg_id})", flush=True)
        return True
    except Exception as e:
        app.logger.error(f"--> [SES ERROR] Failed to send email to {to_email}: {e}")
        print(f"--> [SES ERROR] Failed to send email to {to_email}: {e}", flush=True)
        return False

# ==================================================
# 5. GENERAL HELPERS & SERIALIZERS
# ==================================================

def error_response(message, status_code=400):
    return jsonify({"success": False, "error": message, "message": message}), status_code

def valid_email(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))

def request_to_dict(item):
    owner = (item.owner or item.name or "").strip()
    phone = "Not provided"
    blood_group = "N/A"
    pincode = "N/A"

    user = None
    if owner and "@" in owner:
        user = User.query.filter(db.func.lower(User.email) == owner.lower()).first()

    if not user and item.name:
        user = User.query.filter(db.func.lower(User.name) == item.name.strip().lower()).first()

    if not user and owner:
        clean_user_name = owner.split("@")[0].strip().lower()
        user = User.query.filter(db.func.lower(User.name) == clean_user_name).first()

    if user:
        if user.phone and str(user.phone).strip() and str(user.phone).strip().lower() != "none":
            phone = str(user.phone).strip()
        if user.blood_group and str(user.blood_group).strip() and str(user.blood_group).strip().lower() != "none":
            blood_group = str(user.blood_group).strip()
        if user.pincode and str(user.pincode).strip() and str(user.pincode).strip().lower() != "none":
            pincode = str(user.pincode).strip()

    proof_url = (
        f"/api/requests/proofs/{item.proof_filename}"
        if getattr(item, "proof_filename", None) else None
    )

    return {
        "id": item.id,
        "name": item.name,
        "owner": owner,
        "email": owner,
        "phone": phone,
        "contact": phone,
        "blood_group": blood_group,
        "bloodGroup": blood_group,
        "blood": blood_group,
        "pincode": pincode,
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
        "offer_status": item.offer_status,
        "proof_filename": getattr(item, "proof_filename", None),
        "proof_url": proof_url,
        "created_at": item.created_at.isoformat() if getattr(item, "created_at", None) else ""
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
        "title": item.category,
        "category": item.category,
        "location": item.location,
        "description": item.description,
        "image": image_url,
        "image_url": image_url,
        "image_filename": item.image_filename,
        "posted_by": item.posted_by or "Community member",
        "created_at": created_at.isoformat() if created_at else None
    }

def donation_to_dict(item):
    created_at = item.created_at
    if created_at and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    phone = "Not provided"
    if item.donor_email:
        donor_user = User.query.filter(db.func.lower(User.email) == item.donor_email.strip().lower()).first()
        if donor_user and donor_user.phone and str(donor_user.phone).strip().lower() != "none":
            phone = str(donor_user.phone).strip()

    return {
        "id": item.id,
        "donor_email": item.donor_email,
        "donor_name": item.donor_name,
        "phone": phone,
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
# 6. STATIC FRONTEND PAGES
# ==================================================

@app.route("/")
def home():
    return send_from_directory(FRONTEND_DIR, "login.html")

@app.route("/<path:filename>")
def serve_static(filename):
    if (FRONTEND_DIR / filename).is_file():
        return send_from_directory(FRONTEND_DIR, filename)
    return error_response("File not found", 404)

# ==================================================
# 7. AUTHENTICATION (STRICT PASSWORD VERIFICATION)
# ==================================================

def current_user():
    user_id = session.get("user_id")
    if user_id:
        return db.session.get(User, user_id)
    email = request.headers.get("X-User-Email")
    if email:
        return User.query.filter(db.func.lower(User.email) == email.strip().lower()).first()
    return None

@app.route("/api/auth/register", methods=["POST"])
@app.route("/api/register", methods=["POST"])
def register_account():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    phone = str(data.get("phone", "")).strip()
    blood = str(data.get("bloodGroup") or data.get("blood_group") or "").strip()
    pincode = str(data.get("pincode", "")).strip()

    if not name or not valid_email(email) or len(password) < 8:
        return error_response("Enter a valid name and email. Password must contain at least 8 characters.")

    if User.query.filter(db.func.lower(User.email) == email).first():
        return error_response("An account with this email already exists. Please sign in.", 409)

    user = User(
        name=name,
        email=email,
        password_hash=generate_password_hash(password),
        role="user",
        phone=phone or None,
        blood_group=blood or None,
        pincode=pincode or None
    )
    try:
        db.session.add(user)
        db.session.commit()
        session.clear()
        session.permanent = True
        session["user_id"] = user.id
        return jsonify({
            "success": True,
            "message": "Account created successfully.",
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role,
                "phone": user.phone or "",
                "bloodGroup": user.blood_group or "",
                "blood_group": user.blood_group or "",
                "pincode": user.pincode or ""
            }
        }), 201
    except IntegrityError:
        db.session.rollback()
        return error_response("This email is already registered.", 409)

@app.route("/api/auth/login", methods=["POST"])
@app.route("/api/login", methods=["POST"])
def login_account():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    requested_role = str(data.get("role", "")).strip().lower()

    if not email or not password:
        return error_response("Email and password are required.", 400)

    user = User.query.filter(db.func.lower(User.email) == email).first()
    if not user or not user.password_hash:
        return error_response("Invalid email or password. Please register first.", 401)

    try:
        is_valid_password = check_password_hash(user.password_hash, password)
    except ValueError:
        is_valid_password = False

    if not is_valid_password:
        return error_response("Incorrect email or password.", 401)

    actual_role = (user.role or "user").strip().lower()
    if requested_role and requested_role != actual_role:
        return error_response(f"This account is registered as a {actual_role}, not as {requested_role}.", 403)

    session.clear()
    session.permanent = True
    session["user_id"] = user.id

    return jsonify({
        "success": True,
        "message": "Login successful.",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": actual_role,
            "phone": user.phone or "",
            "bloodGroup": user.blood_group or "",
            "blood_group": user.blood_group or "",
            "pincode": user.pincode or ""
        }
    })

@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    user = current_user()
    if not user:
        return error_response("Not signed in.", 401)
    return jsonify({
        "success": True,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "phone": user.phone or "",
            "bloodGroup": user.blood_group or "",
            "blood_group": user.blood_group or "",
            "pincode": user.pincode or ""
        }
    })

@app.route("/api/auth/logout", methods=["POST"])
@app.route("/api/logout", methods=["POST"])
def logout_account():
    session.clear()
    return jsonify({"success": True, "message": "Signed out."})

# ==================================================
# 8. HEALTH CHECK
# ==================================================

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "success": True,
        "message": "ReliefLink backend is running",
        "status": "success",
        "database_mode": "mysql" if os.environ.get("DB_HOST") else "sqlite",
        "image_storage": "s3" if s3_client else "local",
        "lambda_alerts": "enabled"
    })

# ==================================================
# 9. EMERGENCY REQUESTS API (Cross-Dashboard Sync + Photo Proof)
# ==================================================

@app.route("/api/requests", methods=["GET"])
def list_requests():
    try:
        user = current_user()
        scope = request.args.get("scope", "").strip().lower()
        query = EmergencyRequest.query

        if scope == "my" and user:
            query = query.filter(db.func.lower(EmergencyRequest.owner) == user.email.lower())
        elif user and hasattr(user, "role") and user.role == "user" and scope != "all":
            query = query.filter(db.func.lower(EmergencyRequest.owner) == user.email.lower())

        items = query.order_by(EmergencyRequest.id.desc()).all()
        data = [request_to_dict(item) for item in items]
        return jsonify({"requests": data, "data": data, "items": data})
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Could not retrieve emergency requests")
        return error_response("Could not load emergency requests.", 500)

@app.route("/api/requests", methods=["POST"])
def create_request():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("Invalid request data. Please submit JSON.")

    user = current_user()
    owner = str(data.get("owner") or (user.email if user else "") or data.get("email") or "").strip().lower()
    name = str(data.get("name") or (user.name if user else "") or (owner.split("@")[0] if owner else "Community Member")).strip()
    request_type = str(data.get("type") or data.get("category") or "General Help").strip()
    location = str(data.get("location") or "").strip()
    priority = str(data.get("priority") or "Medium").strip().title()
    details = str(data.get("details") or data.get("description") or "").strip()

    req_phone = str(data.get("phone") or "").strip()
    req_blood = str(data.get("bloodGroup") or data.get("blood_group") or "").strip()
    req_pincode = str(data.get("pincode") or "").strip()

    if not owner:
        return error_response("User email is required.")
    if not location:
        return error_response("Please enter the request location.")
    if not details:
        return error_response("Please enter the request details.")
    if priority not in {"Low", "Medium", "High"}:
        priority = "Medium"

    if user and (req_phone or req_blood or req_pincode):
        if req_phone and not user.phone:
            user.phone = req_phone
        if req_blood and not user.blood_group:
            user.blood_group = req_blood
        if req_pincode and not user.pincode:
            user.pincode = req_pincode

    item = EmergencyRequest(
        name=name,
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

        trigger_lambda_emergency_alert(saved_request)

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

    item.helper_email = helper_email
    item.helper_name = helper_name
    item.offer_status = "Offered"

    try:
        db.session.commit()

        if item.owner and valid_email(item.owner):
            offer_subject = f"ReliefLink - Help Offered for Request #{item.id}"
            offer_body = (
                f"Hello {item.name},\n\n"
                f"{helper_name} ({helper_email}) has offered to assist with your request for '{item.category}'.\n"
                f"Location: {item.location}\n"
                f"Status: Waiting for volunteer coordinator review.\n\n"
                f"ReliefLink Emergency Response Team"
            )
            send_transactional_email(item.owner, offer_subject, offer_body)

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

        if item.helper_email and valid_email(item.helper_email):
            approval_subject = f"ReliefLink - Offer Approved for Request #{item.id}"
            approval_body = (
                f"Hello {item.helper_name},\n\n"
                f"Your offer to assist with '{item.category}' at {item.location} has been approved.\n"
                f"Requester Contact: {item.owner}\n"
                f"Coordinating Volunteer: {item.volunteer_email or 'Volunteer Coordinator'}\n\n"
                f"Thank you for your active support!\nReliefLink Team"
            )
            send_transactional_email(item.helper_email, approval_subject, approval_body)

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

    if "status" in data:
        status = data.get("status")
        if status in {"Pending", "In Progress", "Resolved"}:
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

@app.route("/api/requests/<int:request_id>/proof", methods=["POST"])
def upload_request_proof(request_id):
    item = db.session.get(EmergencyRequest, request_id)
    if item is None:
        return error_response("Request not found.", 404)

    image_file = request.files.get("photo") or request.files.get("proof")
    if not image_file or not image_file.filename:
        return error_response("No photo proof file provided.")

    original_name = secure_filename(image_file.filename)
    if not original_name or "." not in original_name:
        return error_response("Please select a valid image file.")

    extension = original_name.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return error_response("Unsupported image format. Use PNG, JPG, JPEG, GIF, or WEBP.")

    saved_filename = f"proof_{request_id}_{uuid4().hex}.{extension}"
    upload_path = PROOF_DIR / saved_filename
    s3_key = f"proofs/{saved_filename}"

    try:
        store_image(image_file, s3_key, upload_path)
    except (BotoCoreError, ClientError, OSError):
        app.logger.exception("Failed to store proof image for request %s", request_id)
        return error_response("Could not upload photo proof to storage.", 500)

    item.proof_filename = saved_filename
    item.offer_status = "Helped"
    item.status = "Resolved"

    try:
        db.session.commit()
        updated_request = request_to_dict(item)
        return jsonify({
            "success": True,
            "message": "Photo proof uploaded and request marked as Helped.",
            "proof_url": updated_request["proof_url"],
            "request": updated_request,
            **updated_request
        }), 201
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Failed to save proof filename in database")
        return error_response("Could not save photo proof record.", 500)

@app.route("/api/requests/proofs/<path:filename>", methods=["GET"])
def get_request_proof_image(filename):
    return serve_stored_image(f"proofs/{filename}", filename, PROOF_DIR)

# ==================================================
# 10. VOLUNTEER REGISTRATION API
# ==================================================

@app.route("/api/volunteers", methods=["GET"])
def list_volunteers():
    try:
        items = VolunteerApplication.query.order_by(VolunteerApplication.id.desc()).all()
        data = [volunteer_to_dict(item) for item in items]
        return jsonify({"volunteers": data, "data": data, "items": data})
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
    if not valid_email(email):
        return error_response("Please enter a valid email address.")

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

    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {"Approved", "Rejected"}:
        return error_response("Status must be Approved or Rejected.")

    try:
        item.status = status
        applicant_email = item.email.strip().lower()
        existing_user = User.query.filter(db.func.lower(User.email) == applicant_email).first()

        if status == "Approved":
            if existing_user:
                existing_user.role = "volunteer"
                if item.phone and not existing_user.phone:
                    existing_user.phone = item.phone
                login_note = "Sign in on ReliefLink using your existing email and password (select the Volunteer role)."
            else:
                default_pw = os.environ.get("VOLUNTEER_DEFAULT_PASSWORD", "Volunteer@123")
                db.session.add(User(
                    name=item.name,
                    email=applicant_email,
                    password_hash=generate_password_hash(default_pw),
                    role="volunteer",
                    phone=item.phone
                ))
                login_note = f"Sign in on ReliefLink using your email ({applicant_email}) and temporary password: {default_pw} (select the Volunteer role)."

            send_transactional_email(
                applicant_email,
                "ReliefLink - Volunteer Application Approved!",
                f"Hello {item.name},\n\n"
                f"Congratulations! Your ReliefLink volunteer application ({item.skill}) has been approved by an administrator.\n\n"
                f"{login_note}\n\n"
                f"Thank you for serving your community,\nReliefLink Team"
            )
        elif status == "Rejected" and existing_user and existing_user.role == "volunteer":
            existing_user.role = "user"

        db.session.commit()
        updated_volunteer = volunteer_to_dict(item)
        return jsonify({
            "success": True,
            "message": f"Volunteer application {status.lower()} and login access updated.",
            "volunteer": updated_volunteer,
            **updated_volunteer
        })
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Failed to update volunteer")
        return error_response("Could not update volunteer status.", 500)

# ==================================================
# 11. COMMUNITY ALERTS & INCIDENTS (Supports Image Uploads)
# ==================================================

@app.route("/api/incidents", methods=["GET"])
def list_incidents():
    try:
        items = Incident.query.order_by(Incident.id.desc()).all()
        data = [incident_to_dict(item) for item in items]
        return jsonify({"incidents": data, "alerts": data, "data": data})
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Could not retrieve community alerts")
        return error_response("Could not load community alerts.", 500)

@app.route("/api/incidents", methods=["POST"])
def create_incident():
    category = request.form.get("category", "").strip() or request.form.get("title", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    posted_by = request.form.get("posted_by", "").strip() or "Volunteer Coordinator"

    if not all([category, location, description]):
        return error_response("Category, location, and description are required.")

    image_file = request.files.get("image")
    saved_filename = None

    if image_file and image_file.filename:
        original_name = secure_filename(image_file.filename)
        if original_name and "." in original_name:
            extension = original_name.rsplit(".", 1)[1].lower()
            if extension in ALLOWED_IMAGE_EXTENSIONS:
                saved_filename = f"{uuid4().hex}.{extension}"
                upload_path = UPLOAD_DIR / saved_filename
                s3_key = f"incidents/{saved_filename}"

                try:
                    store_image(image_file, s3_key, upload_path)
                except (BotoCoreError, ClientError, OSError):
                    app.logger.exception("Failed to store uploaded incident image")
                    saved_filename = None

    item = Incident(
        category=category,
        location=location,
        description=description,
        image_filename=saved_filename,
        posted_by=posted_by
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
        return error_response("Could not save the alert. Please try again.", 500)

@app.route("/api/incidents/uploads/<path:filename>", methods=["GET"])
def get_incident_image(filename):
    return serve_stored_image(f"incidents/{filename}", filename, UPLOAD_DIR)

# ==================================================
# 12. ITEM DONATIONS API
# ==================================================

@app.route("/api/donations", methods=["GET"])
def list_donations():
    try:
        query = ItemDonation.query
        donor_email = request.args.get("donor_email", "").strip().lower()
        if donor_email:
            query = query.filter(db.func.lower(ItemDonation.donor_email) == donor_email)

        items = query.order_by(ItemDonation.id.desc()).all()
        data = [donation_to_dict(item) for item in items]
        return jsonify({"donations": data, "data": data, "items": data})
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
    category = str(data.get("category") or data.get("item_category") or "General").strip()
    location = str(data.get("location") or "").strip()
    details = str(data.get("details") or data.get("item_details") or "").strip()

    if not donor_email:
        return error_response("Donor email is required.")
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

        receipt_subject = "ReliefLink - Donation Receipt & Acknowledgment"
        receipt_body = f"Hello {donor_name},\n\nThank you for contributing to relief efforts! Your donation of '{category}' has been listed. A volunteer will coordinate pickup at: {location}.\n\nThank you,\nReliefLink Team"
        send_transactional_email(donor_email, receipt_subject, receipt_body)

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
    volunteer_email = str(data.get("volunteer_email") or data.get("assigned_volunteer") or "Volunteer Team").strip().lower()
    pickup_message = str(data.get("pickup_message") or "").strip()

    if not pickup_message:
        return error_response("Please provide a pickup message.")

    item.assigned_volunteer = volunteer_email
    item.pickup_message = pickup_message
    item.status = "Scheduled"

    try:
        db.session.commit()

        if item.donor_email and valid_email(item.donor_email):
            pickup_subject = f"ReliefLink - Pickup Scheduled for {item.item_category}"
            pickup_body = (
                f"Hello {item.donor_name},\n\n"
                f"A volunteer ({volunteer_email}) has scheduled pickup for your donation.\n\n"
                f"Message from Volunteer:\n\"{pickup_message}\"\n\n"
                f"Pickup Location: {item.location}\n\n"
                f"Thank you,\nReliefLink Volunteer Dispatch"
            )
            send_transactional_email(item.donor_email, pickup_subject, pickup_body)

        return jsonify({
            "success": True,
            "message": "Pickup scheduled and message sent to donor.",
            "donation": donation_to_dict(item)
        })
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Failed to schedule donation pickup")
        return error_response("Could not schedule pickup. Please try again.", 500)

@app.route("/api/donations/<int:donation_id>", methods=["PATCH"])
def update_donation_status(donation_id):
    item = db.session.get(ItemDonation, donation_id)
    if item is None:
        return error_response("Donation not found.", 404)

    data = request.get_json(silent=True) or {}
    status = str(data.get("status") or "").strip()
    if status in {"Available", "Scheduled", "Picked", "Picked Up"}:
        item.status = "Picked" if status in {"Picked", "Picked Up"} else status

    try:
        db.session.commit()
        return jsonify({
            "success": True,
            "message": f"Donation marked as {item.status}.",
            "donation": donation_to_dict(item)
        })
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Failed to update donation status")
        return error_response("Could not update donation status.", 500)

@app.route("/api/donations/<int:donation_id>/resend-receipt", methods=["POST"])
def resend_donation_receipt(donation_id):
    item = db.session.get(ItemDonation, donation_id)
    if not item:
        return error_response("Donation not found.", 404)

    data = request.get_json(silent=True) or {}
    target_email = (data.get("email") or item.donor_email).strip().lower()

    receipt_subject = "ReliefLink - Donation Receipt & Acknowledgment (Copy)"
    receipt_body = (
        f"Hello {item.donor_name},\n\n"
        f"Here is a copy of your donation receipt for '{item.item_category}'.\n"
        f"Location: {item.location}\n"
        f"Current Status: {item.status}\n\n"
        f"Thank you,\nReliefLink Team"
    )

    sent = send_transactional_email(target_email, receipt_subject, receipt_body)
    if sent:
        return jsonify({"success": True, "message": f"Receipt sent to {target_email}."})
    else:
        return error_response("Unable to send receipt via Amazon SES.", 500)

# ==================================================
# 13. PROFILE PHOTO UPLOAD & AVATAR API
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
# 14. ERROR HANDLERS
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
# 15. START APPLICATION
# ==================================================

initialize_database()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)