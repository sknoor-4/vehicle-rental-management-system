"""Roadly customer rental portal and administration dashboard."""
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
from uuid import uuid4

import mysql.connector
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from mysql.connector import Error
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "local-dev-change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
UPLOAD_FOLDER = Path(app.root_path) / "static" / "uploads"
ADMIN_USER = os.environ.get("ROADLY_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ROADLY_ADMIN_PASSWORD", "admin123")
MODEL_IMAGES = {
    ("bmw", "m2"): "https://images.unsplash.com/photo-1723389729200-2cd14b37f10f?auto=format&fit=crop&w=1200&q=85",
    ("bmw", "m2 competition"): "https://images.unsplash.com/photo-1723389729232-17b974a92bbe?auto=format&fit=crop&w=1200&q=85",
    ("toyota", "innova"): "https://images.unsplash.com/photo-1748215210950-536c6621629a?auto=format&fit=crop&w=1200&q=85",
    ("bajaj", "pulsar n160"): "https://cdn-s3.autocarindia.com/Bajaj/Pulsar-N160/500_0376.JPG",
    ("honda", "city"): "https://cdni.autocarindia.com/ExtraImages/20210406010759_2020_Honda_City_LT_1.jpg",
}
MAKE_IMAGES = {
    "bmw": "https://images.unsplash.com/photo-1723389729200-2cd14b37f10f?auto=format&fit=crop&w=1200&q=85",
}
TYPE_IMAGES = {
    "suv": "https://images.unsplash.com/photo-1519641471654-76ce0107ad1b?auto=format&fit=crop&w=1200&q=85",
    "sedan": "https://images.unsplash.com/photo-1552519507-da3b142c6e3d?auto=format&fit=crop&w=1200&q=85",
    "bike": "https://images.unsplash.com/photo-1558981806-ec527fa84c39?auto=format&fit=crop&w=1200&q=85",
}


def attach_vehicle_images(vehicles):
    """Resolve model-aware image URLs consistently for both site experiences."""
    for vehicle in vehicles:
        make = str(vehicle.get("Make", "")).strip().lower()
        model = " ".join(str(vehicle.get("Model", "")).strip().lower().split())
        vehicle["ImageURL"] = MODEL_IMAGES.get((make, model)) or MAKE_IMAGES.get(make) or TYPE_IMAGES.get(
            str(vehicle.get("Type", "")).strip().lower(), TYPE_IMAGES["sedan"])
    return vehicles


def apply_saved_vehicle_images(cursor, vehicles):
    """Create the optional image table and apply admin-selected URLs to both views."""
    cursor.execute("""CREATE TABLE IF NOT EXISTS VEHICLE_IMAGE (
        VehicleID INT PRIMARY KEY,
        ImageURL VARCHAR(500) NOT NULL,
        UpdatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_vehicle_image_vehicle FOREIGN KEY (VehicleID)
            REFERENCES VEHICLE(VehicleID) ON DELETE CASCADE
    ) ENGINE=InnoDB""")
    cursor.execute("SELECT VehicleID, ImageURL FROM VEHICLE_IMAGE")
    custom = {row["VehicleID"]: row["ImageURL"] for row in cursor.fetchall()}
    for vehicle in attach_vehicle_images(vehicles):
        vehicle["ImageURL"] = custom.get(vehicle["VehicleID"], vehicle["ImageURL"])
    return vehicles


def age_on(dob, on_date=None):
    if not dob:
        return 0
    on_date = on_date or date.today()
    dob = dob if isinstance(dob, date) else date.fromisoformat(str(dob))
    return on_date.year - dob.year - ((on_date.month, on_date.day) < (dob.month, dob.day))


def apply_vehicle_policies(cursor, vehicles):
    cursor.execute("""CREATE TABLE IF NOT EXISTS VEHICLE_POLICY (
        VehicleID INT PRIMARY KEY,
        Provider VARCHAR(100) NOT NULL,
        PolicyNumber VARCHAR(80) NOT NULL,
        CoverageStart DATE NOT NULL,
        CoverageEnd DATE NOT NULL,
        CoverageLimit DECIMAL(12,2) NOT NULL,
        CustomerExcess DECIMAL(12,2) NOT NULL DEFAULT 0,
        Notes VARCHAR(500),
        FOREIGN KEY (VehicleID) REFERENCES VEHICLE(VehicleID) ON DELETE CASCADE
    ) ENGINE=InnoDB""")
    cursor.execute("SELECT * FROM VEHICLE_POLICY")
    policies = {row["VehicleID"]: row for row in cursor.fetchall()}
    for vehicle in vehicles:
        policy = policies.get(vehicle["VehicleID"])
        vehicle["Policy"] = policy
        vehicle["PolicyReady"] = bool(policy and policy["CoverageEnd"] >= date.today())
    return vehicles


def apply_vehicle_returns(cursor, vehicles):
    """Attach latest rental end dates to vehicles currently marked as rented."""
    rented_ids = [v["VehicleID"] for v in vehicles if v.get("Status") == "Rented"]
    latest = {}
    if rented_ids:
        cursor.execute("""SELECT r.VehicleID,r.RentalID,r.StartDate,r.EndDate,r.CustomerID,
                c.FirstName AS RenterFirstName,c.LastName AS RenterLastName
            FROM RENTAL r JOIN VEHICLE v ON v.VehicleID=r.VehicleID
            JOIN CUSTOMER c ON c.CustomerID=r.CustomerID
            WHERE v.Status='Rented' ORDER BY r.RentalID DESC""")
        for row in cursor.fetchall():
            latest.setdefault(row["VehicleID"], row)
    today = date.today()
    for vehicle in vehicles:
        rental = latest.get(vehicle["VehicleID"])
        vehicle["CurrentRental"] = rental
        vehicle["ExpectedReturnDate"] = rental["EndDate"] if rental else None
        vehicle["ExpectedAvailableDate"] = (
            rental["EndDate"] + timedelta(days=1)
            if rental and rental["EndDate"] >= today else None
        )
        vehicle["ReturnOverdue"] = bool(
            vehicle.get("Status") == "Rented" and
            (not rental or rental["EndDate"] < today)
        )
    return vehicles


def ensure_business_tables(cursor):
    """Keep customer controls and service calls outside the user's source schema."""
    cursor.execute("""CREATE TABLE IF NOT EXISTS CUSTOMER_MANAGEMENT (
        CustomerID INT PRIMARY KEY,
        BookingsEnabled TINYINT(1) NOT NULL DEFAULT 1,
        AdminNote VARCHAR(300),
        UpdatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (CustomerID) REFERENCES CUSTOMER(CustomerID) ON DELETE CASCADE
    ) ENGINE=InnoDB""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS SERVICE_REQUEST (
        ServiceRequestID INT PRIMARY KEY,
        CustomerID INT NOT NULL,
        VehicleID INT NULL,
        PreferredDate DATE NULL,
        ContactPhone VARCHAR(20) NOT NULL,
        ServiceAddress VARCHAR(250) NOT NULL,
        IssueDescription VARCHAR(500) NOT NULL,
        Status VARCHAR(30) NOT NULL DEFAULT 'Requested',
        StaffID INT NULL,
        CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (CustomerID) REFERENCES CUSTOMER(CustomerID),
        FOREIGN KEY (VehicleID) REFERENCES VEHICLE(VehicleID),
        FOREIGN KEY (StaffID) REFERENCES STAFF(StaffID)
    ) ENGINE=InnoDB""")


def help_fallback(message, vehicles):
    text = message.lower()
    if any(word in text for word in ("mechanic", "service", "breakdown", "repair", "puncture", "engine")):
        return "Need a mechanic? Sign in, open Need Help → Request a mechanic, and send the vehicle, location, preferred date, and issue. The rental team will review and confirm the visit. If anyone is in immediate danger, call local emergency services first."
    if any(word in text for word in ("accident", "insurance", "damage", "excess", "deductible")):
        return "Accident costs depend on the selected vehicle's actual policy, exclusions, insurer decision, and repair assessment. Check the insurance details on its vehicle card, contact the rental team promptly, and do not rely on this chat to determine liability."
    if any(word in text for word in ("payment", "paid", "pending", "booking", "rent", "reserve")):
        return "Sign in and open My bookings to review your rental and payment status. Pending payment means the rental office has not marked it paid yet; the admin team updates that status after confirming the payment."
    if any(word in text for word in ("available", "car", "vehicle", "bike", "return")):
        available = [f"{v['Make']} {v['Model']} (₹{v['HourlyRate']}/day)" for v in vehicles if v.get("Status") == "Available"]
        rented = [f"{v['Make']} {v['Model']} expected back {v['ExpectedReturnDate']}" for v in vehicles if v.get("Status") == "Rented" and v.get("ExpectedReturnDate")]
        summary = "Available now: " + (", ".join(available[:8]) if available else "none listed at the moment.")
        if rented:
            summary += " Expected returns: " + "; ".join(rented[:6]) + "."
        return summary
    return "I can help with bookings, payments, insurance terms, and mechanic service requests. Tell me what you need, or sign in and use Request a mechanic for roadside/service help."


def get_db_connection():
    return mysql.connector.connect(host="localhost", user="root", password="MyNewPass@123",
                                   database="VehicleRentalDB", connect_timeout=5)


def ensure_account_table(db):
    """Add password storage separately; supplied CUSTOMER schema remains unchanged."""
    with closing(db.cursor()) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS CUSTOMER_ACCOUNT (
                CustomerID INT PRIMARY KEY,
                PasswordHash VARCHAR(255) NOT NULL,
                CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_customer_account_customer FOREIGN KEY (CustomerID)
                    REFERENCES CUSTOMER(CustomerID) ON DELETE CASCADE
            ) ENGINE=InnoDB
        """)


def admin_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


def customer_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("customer_id"):
            flash("Sign in or create an account to continue.", "error")
            return redirect(url_for("customer_login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
def home():
    try:
        with closing(get_db_connection()) as db, closing(db.cursor(dictionary=True)) as cursor:
            ensure_business_tables(cursor)
            cursor.execute("SELECT * FROM VEHICLE ORDER BY VehicleID DESC")
            vehicles = apply_saved_vehicle_images(cursor, cursor.fetchall())
            vehicles = apply_vehicle_policies(cursor, vehicles)
            vehicles = apply_vehicle_returns(cursor, vehicles)
            customer_eligible = True
            customer_block_reason = ""
            customer_service_vehicles = []
            if session.get("customer_id"):
                cursor.execute("""SELECT c.DateOfBirth,c.Phone,c.Address,COALESCE(cm.BookingsEnabled,1) AS BookingsEnabled
                    FROM CUSTOMER c LEFT JOIN CUSTOMER_MANAGEMENT cm ON cm.CustomerID=c.CustomerID
                    WHERE c.CustomerID=%s""", (session["customer_id"],))
                customer = cursor.fetchone()
                customer_eligible = bool(customer and age_on(customer["DateOfBirth"]) >= 18 and customer["BookingsEnabled"])
                if not customer:
                    customer_block_reason = "Sign in again to continue booking."
                elif not customer["BookingsEnabled"]:
                    customer_block_reason = "Online bookings for this account are paused. Contact the rental office."
                elif age_on(customer["DateOfBirth"]) < 18:
                    customer_block_reason = "Bookings require the customer to be at least 18 years old."
                cursor.execute("""SELECT DISTINCT v.VehicleID,v.Make,v.Model,v.PlateNumber
                    FROM RENTAL r JOIN VEHICLE v ON v.VehicleID=r.VehicleID
                    WHERE r.CustomerID=%s AND r.EndDate >= CURDATE()
                    ORDER BY v.Make,v.Model""", (session["customer_id"],))
                customer_service_vehicles = cursor.fetchall()
        return render_template("index.html", vehicles=vehicles, customer_eligible=customer_eligible,
                               customer_service_vehicles=customer_service_vehicles,
                               customer_profile=customer if session.get("customer_id") else {},
                               customer_block_reason=customer_block_reason,
                               today=date.today(), db_error=None)
    except Error as exc:
        app.logger.exception("Could not load customer vehicle catalog")
        return render_template("index.html", vehicles=[], customer_eligible=False,
                               customer_service_vehicles=[], customer_block_reason="",
                               customer_profile={},
                               today=date.today(), db_error=exc.msg), 503


@app.route("/customer/register", methods=["GET", "POST"])
def customer_register():
    if request.method == "GET":
        return render_template("auth.html", mode="register",
                               max_dob=date.today().replace(year=date.today().year - 18).isoformat())
    names = ("first_name", "last_name", "email", "phone", "address", "license_number", "dob", "password")
    data = {key: request.form.get(key, "").strip() for key in names}
    if any(not value for value in data.values()) or len(data["password"]) < 8:
        flash("Complete all fields. Passwords must be at least 8 characters.", "error")
        return render_template("auth.html", mode="register", form=data,
                               max_dob=date.today().replace(year=date.today().year - 18).isoformat()), 400
    try:
        dob = date.fromisoformat(data["dob"])
        if age_on(dob) < 18:
            flash("Bookings are available only to customers aged 18 or older.", "error")
            return render_template("auth.html", mode="register", form=data,
                                   max_dob=date.today().replace(year=date.today().year - 18).isoformat()), 403
        db = get_db_connection()
        ensure_account_table(db)
        db.start_transaction()
        with closing(db.cursor()) as cursor:
            cursor.execute("SELECT CustomerID FROM CUSTOMER WHERE Email = %s", (data["email"],))
            if cursor.fetchone():
                db.rollback()
                db.close()
                flash("An account already exists for that email. Please sign in.", "error")
                return render_template("auth.html", mode="register", form=data,
                                       max_dob=date.today().replace(year=date.today().year - 18).isoformat()), 409
            cursor.execute("SELECT COALESCE(MAX(CustomerID), 200) + 1 FROM CUSTOMER")
            customer_id = cursor.fetchone()[0]
            cursor.execute("""INSERT INTO CUSTOMER
                (CustomerID, FirstName, LastName, Email, Phone, Address, LicenseNumber, DateOfBirth)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (customer_id, data["first_name"], data["last_name"], data["email"].lower(),
                 data["phone"], data["address"], data["license_number"], data["dob"]))
            cursor.execute("INSERT INTO CUSTOMER_ACCOUNT (CustomerID, PasswordHash) VALUES (%s,%s)",
                           (customer_id, generate_password_hash(data["password"])))
        db.commit()
        db.close()
        session.clear()
        session["customer_id"] = customer_id
        session["customer_name"] = data["first_name"]
        flash("Your account is ready. Choose a vehicle to book.", "success")
        return redirect(url_for("home"))
    except (ValueError, Error) as exc:
        app.logger.exception("Customer registration failed")
        if "db" in locals() and db.is_connected():
            db.rollback(); db.close()
        flash("Please check the date and details, then try again.", "error")
        return render_template("auth.html", mode="register", form=data,
                               max_dob=date.today().replace(year=date.today().year - 18).isoformat()), 400


@app.route("/customer/login", methods=["GET", "POST"])
def customer_login():
    if request.method == "GET":
        return render_template("auth.html", mode="login")
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    try:
        with closing(get_db_connection()) as db:
            ensure_account_table(db)
            with closing(db.cursor(dictionary=True)) as cursor:
                cursor.execute("""SELECT c.CustomerID,c.FirstName,a.PasswordHash FROM CUSTOMER c
                                  JOIN CUSTOMER_ACCOUNT a ON a.CustomerID=c.CustomerID WHERE c.Email=%s""", (email,))
                account = cursor.fetchone()
        if account and check_password_hash(account["PasswordHash"], password):
            session.clear(); session["customer_id"] = account["CustomerID"]
            session["customer_name"] = account["FirstName"]
            return redirect(url_for("my_rentals"))
        flash("Email or password is incorrect.", "error")
    except Error as exc:
        app.logger.exception("Customer login failed")
        flash(f"Could not connect to the rental database: {exc.msg}", "error")
    return render_template("auth.html", mode="login", email=email), 401


@app.route("/customer/logout", methods=["POST"])
def customer_logout():
    session.clear(); flash("You have been signed out.", "success")
    return redirect(url_for("home"))


@app.route("/api/help/chat", methods=["POST"])
def help_chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "")
    if not isinstance(message, str) or not message.strip() or len(message) > 1000:
        return jsonify(error="Type a short question to continue."), 400
    vehicles = []
    try:
        with closing(get_db_connection()) as db, closing(db.cursor(dictionary=True)) as cursor:
            cursor.execute("SELECT * FROM VEHICLE ORDER BY VehicleID DESC")
            vehicles = apply_vehicle_returns(cursor, cursor.fetchall())
    except Error:
        app.logger.exception("Help assistant could not read live fleet status")
    return jsonify(reply=help_fallback(message.strip(), vehicles), mode="local")


@app.route("/service/request", methods=["POST"])
@customer_required
def create_service_request():
    vehicle_id = request.form.get("vehicle_id", type=int)
    phone = request.form.get("phone", "").strip()
    address = request.form.get("service_address", "").strip()
    issue = request.form.get("issue", "").strip()
    preferred = request.form.get("preferred_date", "").strip()
    try:
        preferred_date = date.fromisoformat(preferred) if preferred else None
        if (not phone or len(phone) > 20 or not address or len(address) > 250 or
                not issue or len(issue) > 500 or (preferred_date and preferred_date < date.today())):
            raise ValueError
        with closing(get_db_connection()) as db, closing(db.cursor(dictionary=True)) as cursor:
            ensure_business_tables(cursor)
            if vehicle_id:
                cursor.execute("""SELECT RentalID FROM RENTAL WHERE CustomerID=%s AND VehicleID=%s
                    AND EndDate >= CURDATE() ORDER BY RentalID DESC LIMIT 1""",
                    (session["customer_id"], vehicle_id))
                if not cursor.fetchone():
                    flash("Choose a vehicle from one of your current or upcoming rentals.", "error")
                    return redirect(url_for("home") + "#help-widget")
            cursor.execute("SELECT COALESCE(MAX(ServiceRequestID),700)+1 AS next_id FROM SERVICE_REQUEST")
            service_id = cursor.fetchone()["next_id"]
            cursor.execute("""INSERT INTO SERVICE_REQUEST
                (ServiceRequestID,CustomerID,VehicleID,PreferredDate,ContactPhone,ServiceAddress,IssueDescription,Status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'Requested')""",
                (service_id,session["customer_id"],vehicle_id or None,preferred_date,phone,address,issue))
            db.commit()
        flash(f"Mechanic service request #{service_id} sent. The team will contact you to confirm timing.", "success")
        return redirect(url_for("my_rentals") + "#service-requests")
    except (ValueError, Error):
        app.logger.exception("Customer service request failed")
        flash("Check the service location, contact number, date, and issue details.", "error")
        return redirect(url_for("home") + "#help-widget")


@app.route("/my-rentals")
@customer_required
def my_rentals():
    try:
        with closing(get_db_connection()) as db, closing(db.cursor(dictionary=True)) as cursor:
            ensure_business_tables(cursor)
            cursor.execute("""SELECT r.*,v.Make,v.Model,v.PlateNumber,v.HourlyRate
                FROM RENTAL r JOIN VEHICLE v ON v.VehicleID=r.VehicleID
                WHERE r.CustomerID=%s ORDER BY r.RentalID DESC""", (session["customer_id"],))
            rentals = cursor.fetchall()
            cursor.execute("""SELECT q.*,v.Make,v.Model,v.PlateNumber,s.FirstName AS StaffFirstName,
                s.LastName AS StaffLastName FROM SERVICE_REQUEST q
                LEFT JOIN VEHICLE v ON v.VehicleID=q.VehicleID
                LEFT JOIN STAFF s ON s.StaffID=q.StaffID WHERE q.CustomerID=%s
                ORDER BY q.ServiceRequestID DESC""", (session["customer_id"],))
            service_requests = cursor.fetchall()
            cursor.execute("SELECT Phone,Address FROM CUSTOMER WHERE CustomerID=%s", (session["customer_id"],))
            customer_profile = cursor.fetchone() or {}
            cursor.execute("""SELECT DISTINCT v.VehicleID,v.Make,v.Model,v.PlateNumber
                FROM RENTAL r JOIN VEHICLE v ON v.VehicleID=r.VehicleID
                WHERE r.CustomerID=%s AND r.EndDate >= CURDATE() ORDER BY v.Make,v.Model""",
                (session["customer_id"],))
            customer_service_vehicles = cursor.fetchall()
        return render_template("my_rentals.html", rentals=rentals, service_requests=service_requests,
                               customer_profile=customer_profile,customer_service_vehicles=customer_service_vehicles,
                               customer_block_reason="",today=date.today())
    except Error as exc:
        app.logger.exception("Could not load customer rentals")
        flash(f"Could not load your rentals: {exc.msg}", "error")
        return redirect(url_for("home"))


@app.route("/book/<int:vehicle_id>", methods=["POST"])
@customer_required
def book_vehicle(vehicle_id):
    try:
        start = date.fromisoformat(request.form.get("start_date", ""))
        end = date.fromisoformat(request.form.get("end_date", ""))
        if start < date.today() or end <= start:
            raise ValueError
        db = get_db_connection(); db.start_transaction()
        with closing(db.cursor(dictionary=True)) as cursor:
            cursor.execute("""SELECT c.DateOfBirth,c.LicenseNumber,
                COALESCE(cm.BookingsEnabled,1) AS BookingsEnabled
                FROM CUSTOMER c LEFT JOIN CUSTOMER_MANAGEMENT cm ON cm.CustomerID=c.CustomerID
                WHERE c.CustomerID=%s""", (session["customer_id"],))
            customer = cursor.fetchone()
            if not customer or age_on(customer["DateOfBirth"]) < 18:
                db.rollback(); db.close()
                flash("You must be at least 18 to book a vehicle.", "error")
                return redirect(url_for("home"))
            if not customer["BookingsEnabled"]:
                db.rollback(); db.close()
                flash("Online bookings for this account are paused. Please contact the rental office.", "error")
                return redirect(url_for("home"))
            if not customer["LicenseNumber"]:
                db.rollback(); db.close()
                flash("Add a valid driving-license number to your customer profile before booking.", "error")
                return redirect(url_for("home"))
            cursor.execute("SELECT * FROM VEHICLE WHERE VehicleID=%s FOR UPDATE", (vehicle_id,))
            vehicle = cursor.fetchone()
            if not vehicle or vehicle["Status"] != "Available":
                db.rollback(); db.close()
                flash("This vehicle is no longer available. Choose another vehicle.", "error")
                return redirect(url_for("home"))
            cursor.execute("SELECT * FROM VEHICLE_POLICY WHERE VehicleID=%s", (vehicle_id,))
            policy = cursor.fetchone()
            if (not policy or policy["CoverageStart"] > start or policy["CoverageEnd"] < end
                    or policy["CoverageLimit"] is None):
                db.rollback(); db.close()
                flash("This vehicle has no verified insurance covering those dates. Contact the rental office.", "error")
                return redirect(url_for("home"))
            cursor.execute("SELECT LocationID FROM LOCATION ORDER BY LocationID LIMIT 1")
            location = cursor.fetchone()
            cursor.execute("SELECT StaffID FROM STAFF WHERE Role='Agent' ORDER BY StaffID LIMIT 1")
            staff = cursor.fetchone()
            if not location or not staff:
                db.rollback(); db.close()
                flash("Bookings need at least one LOCATION and one Agent in the database.", "error")
                return redirect(url_for("home"))
            cursor.execute("SELECT COALESCE(MAX(RentalID),500)+1 AS next_id FROM RENTAL")
            rental_id = cursor.fetchone()["next_id"]
            days = (end - start).days
            total = Decimal(str(vehicle["HourlyRate"])) * 24 * days
            loc_id, staff_id = location["LocationID"], staff["StaffID"]
            cursor.execute("""INSERT INTO RENTAL
                (RentalID,StartDate,EndDate,PickupLocationID,ReturnLocationID,TotalCost,PaymentStatus,
                 CustomerID,VehicleID,StaffID) VALUES (%s,%s,%s,%s,%s,%s,'Pending',%s,%s,%s)""",
                (rental_id, start, end, loc_id, loc_id, total, session["customer_id"], vehicle_id, staff_id))
            cursor.execute("UPDATE VEHICLE SET Status='Rented' WHERE VehicleID=%s", (vehicle_id,))
        db.commit(); db.close()
        flash(f"Booking request confirmed. Rental #{rental_id} is awaiting payment.", "success")
        return redirect(url_for("my_rentals"))
    except (ValueError, Error) as exc:
        app.logger.exception("Vehicle booking failed")
        if "db" in locals() and db.is_connected():
            db.rollback(); db.close()
        flash("Choose a valid future date range and try again.", "error")
        return redirect(url_for("home"))


@app.route("/cancel-rental/<int:rental_id>", methods=["POST"])
@customer_required
def cancel_rental(rental_id):
    try:
        db = get_db_connection(); db.start_transaction()
        with closing(db.cursor(dictionary=True)) as cursor:
            cursor.execute("SELECT VehicleID,StartDate,PaymentStatus FROM RENTAL WHERE RentalID=%s AND CustomerID=%s FOR UPDATE",
                           (rental_id, session["customer_id"]))
            rental = cursor.fetchone()
            if not rental or rental["PaymentStatus"] != "Pending" or rental["StartDate"] <= date.today():
                db.rollback(); db.close()
                flash("Only your upcoming, unpaid rentals can be cancelled online.", "error")
                return redirect(url_for("my_rentals"))
            cursor.execute("SELECT COUNT(*) AS n FROM MAINTENANCE WHERE VehicleID=%s AND Status<>'Completed'",
                           (rental["VehicleID"],))
            status = "Maintenance" if cursor.fetchone()["n"] else "Available"
            cursor.execute("UPDATE VEHICLE SET Status=%s WHERE VehicleID=%s", (status, rental["VehicleID"]))
        db.commit(); db.close()
        flash("Rental cancelled. The vehicle is available again.", "success")
    except Error as exc:
        app.logger.exception("Rental cancellation failed")
        if "db" in locals() and db.is_connected(): db.rollback(); db.close()
        flash("Could not cancel that rental safely.", "error")
    return redirect(url_for("my_rentals"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASSWORD:
            session.clear(); session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Admin username or password is incorrect.", "error")
    return render_template("auth.html", mode="admin")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear(); flash("Admin signed out.", "success")
    return redirect(url_for("home"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    try:
        with closing(get_db_connection()) as db, closing(db.cursor(dictionary=True)) as cursor:
            ensure_business_tables(cursor)
            cursor.execute("SELECT * FROM VEHICLE ORDER BY VehicleID DESC"); vehicles = apply_saved_vehicle_images(cursor, cursor.fetchall())
            vehicles = apply_vehicle_policies(cursor, vehicles)
            vehicles = apply_vehicle_returns(cursor, vehicles)
            cursor.execute("""SELECT c.*,COALESCE(cm.BookingsEnabled,1) AS BookingsEnabled,
                cm.AdminNote FROM CUSTOMER c LEFT JOIN CUSTOMER_MANAGEMENT cm
                ON cm.CustomerID=c.CustomerID ORDER BY c.CustomerID DESC""")
            customers = cursor.fetchall()
            cursor.execute("SELECT StaffID,FirstName,LastName,Role FROM STAFF ORDER BY StaffID"); staff = cursor.fetchall()
            staff = [member for member in staff if str(member.get("Role", "")).lower() == "mechanic"]
            cursor.execute("""SELECT m.*,v.Make,v.Model,v.PlateNumber,s.FirstName AS StaffFirstName,s.LastName AS StaffLastName
                FROM MAINTENANCE m LEFT JOIN VEHICLE v ON v.VehicleID=m.VehicleID
                LEFT JOIN STAFF s ON s.StaffID=m.StaffID ORDER BY m.`Date` DESC,m.MaintenanceID DESC""")
            maintenance = cursor.fetchall()
            cursor.execute("""SELECT r.*,c.FirstName,c.LastName,c.Email,c.Phone,c.Address,c.LicenseNumber,
                v.Make,v.Model,v.PlateNumber,v.Type,v.Year,v.Color,v.FuelType,v.HourlyRate,
                pickup.Name AS PickupLocationName,returning.Name AS ReturnLocationName,
                s.FirstName AS StaffFirstName,s.LastName AS StaffLastName
                FROM RENTAL r LEFT JOIN CUSTOMER c ON c.CustomerID=r.CustomerID
                LEFT JOIN VEHICLE v ON v.VehicleID=r.VehicleID
                LEFT JOIN LOCATION pickup ON pickup.LocationID=r.PickupLocationID
                LEFT JOIN LOCATION returning ON returning.LocationID=r.ReturnLocationID
                LEFT JOIN STAFF s ON s.StaffID=r.StaffID
                ORDER BY r.RentalID DESC""")
            rentals = cursor.fetchall()
            current_by_vehicle = {v["VehicleID"]: v.get("CurrentRental") for v in vehicles}
            for rental in rentals:
                current = current_by_vehicle.get(rental["VehicleID"])
                rental["VehicleStatus"] = next((v["Status"] for v in vehicles if v["VehicleID"] == rental["VehicleID"]), "")
                rental["IsCurrentRental"] = bool(current and current["RentalID"] == rental["RentalID"])
                rental["ExpectedAvailableDate"] = next(
                    (v["ExpectedAvailableDate"] for v in vehicles if v["VehicleID"] == rental["VehicleID"]), None)
            cursor.execute("""SELECT q.*,c.FirstName,c.LastName,c.Email,v.Make,v.Model,v.PlateNumber,
                s.FirstName AS StaffFirstName,s.LastName AS StaffLastName
                FROM SERVICE_REQUEST q JOIN CUSTOMER c ON c.CustomerID=q.CustomerID
                LEFT JOIN VEHICLE v ON v.VehicleID=q.VehicleID
                LEFT JOIN STAFF s ON s.StaffID=q.StaffID
                ORDER BY FIELD(q.Status,'Requested','Assigned','In Progress','Completed','Cancelled'),q.ServiceRequestID DESC""")
            service_requests = cursor.fetchall()
        available = sum(v["Status"] == "Available" for v in vehicles)
        rented_count = sum(v["Status"] == "Rented" for v in vehicles)
        pending = sum(str(r.get("PaymentStatus", "")).lower() == "pending" for r in rentals)
        return render_template("admin.html", vehicles=vehicles, customers=customers, rentals=rentals,
                               available_count=available, rented_count=rented_count, active_count=pending,
                               staff=staff, maintenance=maintenance, service_requests=service_requests,
                               today=date.today(), customer_profile={}, customer_service_vehicles=[], db_error=None)
    except Error as exc:
        app.logger.exception("Could not load admin dashboard")
        return render_template("admin.html", vehicles=[], customers=[], rentals=[], available_count=0,
                               rented_count=0, active_count=0, staff=[], maintenance=[],service_requests=[],
                               today=date.today(),
                               customer_profile={}, customer_service_vehicles=[], db_error=exc.msg), 503


@app.route("/admin/add_vehicle", methods=["POST"])
@admin_required
def add_vehicle():
    fields = ("make", "model", "type", "year", "color", "fuel_type", "plate_number", "hourly_rate")
    values = {name: request.form.get(name, "").strip() for name in fields}
    try:
        year = int(values["year"]); rate = Decimal(values["hourly_rate"])
        if not all(values.values()) or not 1886 <= year <= 2100 or rate <= 0: raise ValueError
        with closing(get_db_connection()) as db:
            db.start_transaction()
            with closing(db.cursor()) as cursor:
                cursor.execute("SELECT COALESCE(MAX(VehicleID),400)+1 AS next_id FROM VEHICLE")
                vid = cursor.fetchone()[0]
                cursor.execute("""INSERT INTO VEHICLE(VehicleID,Make,Model,Type,Year,Color,FuelType,PlateNumber,HourlyRate,Status)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'Available')""",
                    (vid,values["make"],values["model"],values["type"],year,values["color"],values["fuel_type"],values["plate_number"].upper(),rate))
            db.commit()
        flash("Vehicle added to the fleet.", "success")
    except (ValueError, Error) as exc:
        app.logger.exception("Could not add vehicle")
        flash("Please check the vehicle details and plate number, then try again.", "error")
    return redirect(url_for("admin_dashboard")+"#vehicles")


@app.route("/admin/vehicle/<int:vehicle_id>/photo", methods=["POST"])
@admin_required
def update_vehicle_photo(vehicle_id):
    photo = request.files.get("photo")
    if not photo or not photo.filename:
        flash("Choose a photo file from your device first.", "error")
        return redirect(url_for("admin_dashboard") + "#vehicles")
    safe_name = secure_filename(photo.filename)
    extension = Path(safe_name).suffix.lower()
    signatures = {
        ".jpg": lambda data: data.startswith(b"\xff\xd8\xff"),
        ".jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
        ".png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
        ".webp": lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    }
    header = photo.stream.read(16)
    photo.stream.seek(0)
    if extension not in signatures or not signatures[extension](header):
        flash("Choose a valid JPG, PNG, or WEBP image.", "error")
        return redirect(url_for("admin_dashboard") + "#vehicles")
    filename = f"{uuid4().hex}{extension}"
    image_url = f"/static/uploads/{filename}"
    saved_path = UPLOAD_FOLDER / filename
    try:
        with closing(get_db_connection()) as db, closing(db.cursor()) as cursor:
            cursor.execute("SELECT VehicleID FROM VEHICLE WHERE VehicleID=%s", (vehicle_id,))
            if not cursor.fetchone():
                flash("Vehicle not found.", "error")
            else:
                UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
                photo.save(saved_path)
                cursor.execute("""INSERT INTO VEHICLE_IMAGE (VehicleID, ImageURL) VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE ImageURL=VALUES(ImageURL)""", (vehicle_id, image_url))
                db.commit()
                flash("Vehicle photo uploaded and updated on customer and admin pages.", "success")
    except Error as exc:
        saved_path.unlink(missing_ok=True)
        app.logger.exception("Could not update vehicle photo")
        flash("Could not save this photo. Please try again.", "error")
    except OSError:
        saved_path.unlink(missing_ok=True)
        app.logger.exception("Could not write vehicle photo")
        flash("Could not store the selected photo on this device.", "error")
    return redirect(url_for("admin_dashboard") + "#vehicles")


@app.route("/admin/vehicle/<int:vehicle_id>/policy", methods=["POST"])
@admin_required
def save_vehicle_policy(vehicle_id):
    fields = ("provider", "policy_number", "coverage_start", "coverage_end", "coverage_limit", "customer_excess")
    values = {key: request.form.get(key, "").strip() for key in fields}
    notes = request.form.get("notes", "").strip()
    try:
        start = date.fromisoformat(values["coverage_start"])
        end = date.fromisoformat(values["coverage_end"])
        limit = Decimal(values["coverage_limit"])
        excess = Decimal(values["customer_excess"])
        if (not all(values.values()) or not values["provider"] or not values["policy_number"]
                or start > end or limit <= 0 or excess < 0 or len(notes) > 500):
            raise ValueError
        with closing(get_db_connection()) as db, closing(db.cursor()) as cursor:
            cursor.execute("SELECT VehicleID FROM VEHICLE WHERE VehicleID=%s", (vehicle_id,))
            if not cursor.fetchone():
                flash("Vehicle not found.", "error")
            else:
                cursor.execute("""INSERT INTO VEHICLE_POLICY
                    (VehicleID,Provider,PolicyNumber,CoverageStart,CoverageEnd,CoverageLimit,CustomerExcess,Notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE Provider=VALUES(Provider),PolicyNumber=VALUES(PolicyNumber),
                    CoverageStart=VALUES(CoverageStart),CoverageEnd=VALUES(CoverageEnd),
                    CoverageLimit=VALUES(CoverageLimit),CustomerExcess=VALUES(CustomerExcess),Notes=VALUES(Notes)""",
                    (vehicle_id,values["provider"],values["policy_number"],start,end,limit,excess,notes))
                db.commit()
                flash("Insurance policy and customer accident excess saved.", "success")
    except (ValueError, InvalidOperation, Error):
        app.logger.exception("Could not save vehicle policy")
        flash("Enter complete policy dates, positive coverage limit, and a valid excess amount.", "error")
    return redirect(url_for("admin_dashboard") + "#vehicles")


@app.route("/admin/add_maintenance", methods=["POST"])
@admin_required
def add_maintenance():
    vehicle_id = request.form.get("vehicle_id", type=int)
    staff_id = request.form.get("staff_id", type=int)
    description = request.form.get("description", "").strip()
    status = request.form.get("status", "In Progress")
    try:
        work_date = date.fromisoformat(request.form.get("work_date", ""))
        cost = Decimal(request.form.get("cost", ""))
        if not vehicle_id or not staff_id or not description or len(description)>200 or cost < 0 or status not in ("Scheduled","In Progress","Completed"):
            raise ValueError
        with closing(get_db_connection()) as db:
            db.start_transaction()
            with closing(db.cursor(dictionary=True)) as cursor:
                cursor.execute("SELECT Status FROM VEHICLE WHERE VehicleID=%s FOR UPDATE", (vehicle_id,))
                vehicle = cursor.fetchone()
                if not vehicle or vehicle["Status"] == "Rented":
                    db.rollback()
                    flash("Vehicle not found or currently rented; maintenance cannot start.", "error")
                    return redirect(url_for("admin_dashboard") + "#maintenance")
                cursor.execute("SELECT StaffID FROM STAFF WHERE StaffID=%s AND LOWER(Role)='mechanic'", (staff_id,))
                if not cursor.fetchone():
                    db.rollback()
                    flash("Assign maintenance to a staff member with the Mechanic role.", "error")
                    return redirect(url_for("admin_dashboard") + "#maintenance")
                cursor.execute("SELECT COALESCE(MAX(MaintenanceID),600)+1 AS next_id FROM MAINTENANCE")
                maintenance_id = cursor.fetchone()["next_id"]
                cursor.execute("""INSERT INTO MAINTENANCE
                    (MaintenanceID,`Date`,Description,Cost,StaffID,Status,VehicleID)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (maintenance_id,work_date,description,cost,staff_id,status,vehicle_id))
                cursor.execute("UPDATE VEHICLE SET Status=%s WHERE VehicleID=%s",
                               ("Available" if status == "Completed" else "Maintenance",vehicle_id))
            db.commit()
        flash("Maintenance record added.", "success")
    except (ValueError, InvalidOperation, Error):
        app.logger.exception("Could not add maintenance record")
        flash("Check the vehicle, mechanic, service date, and cost, then try again.", "error")
    return redirect(url_for("admin_dashboard") + "#maintenance")


@app.route("/admin/maintenance/<int:maintenance_id>/status", methods=["POST"])
@admin_required
def update_maintenance_status(maintenance_id):
    status = request.form.get("status")
    if status not in ("Scheduled","In Progress","Completed"):
        flash("Invalid maintenance status.", "error")
        return redirect(url_for("admin_dashboard") + "#maintenance")
    try:
        with closing(get_db_connection()) as db, closing(db.cursor(dictionary=True)) as cursor:
            cursor.execute("SELECT VehicleID FROM MAINTENANCE WHERE MaintenanceID=%s", (maintenance_id,))
            record = cursor.fetchone()
            if not record:
                flash("Maintenance record not found.", "error")
            else:
                cursor.execute("UPDATE MAINTENANCE SET Status=%s WHERE MaintenanceID=%s", (status,maintenance_id))
                cursor.execute("SELECT COUNT(*) AS n FROM MAINTENANCE WHERE VehicleID=%s AND Status<>'Completed'", (record["VehicleID"],))
                active_work = cursor.fetchone()["n"]
                cursor.execute("UPDATE VEHICLE SET Status=%s WHERE VehicleID=%s",
                               ("Maintenance" if active_work else "Available",record["VehicleID"]))
                db.commit()
                flash("Maintenance status updated.", "success")
    except Error:
        app.logger.exception("Could not update maintenance status")
        flash("Could not update this service record.", "error")
    return redirect(url_for("admin_dashboard") + "#maintenance")


@app.route("/admin/delete_vehicle/<int:vehicle_id>", methods=["POST"])
@admin_required
def delete_vehicle(vehicle_id):
    try:
        with closing(get_db_connection()) as db, closing(db.cursor(dictionary=True)) as cursor:
            cursor.execute("SELECT Make,Model FROM VEHICLE WHERE VehicleID=%s",(vehicle_id,)); vehicle=cursor.fetchone()
            if not vehicle: flash("Vehicle not found.","error")
            else:
                cursor.execute("SELECT (SELECT COUNT(*) FROM RENTAL WHERE VehicleID=%s)+(SELECT COUNT(*) FROM MAINTENANCE WHERE VehicleID=%s) AS linked_count",(vehicle_id,vehicle_id))
                if cursor.fetchone()["linked_count"]:
                    flash("This vehicle has rental or maintenance history and was kept safely.","error")
                else:
                    cursor.execute("DELETE FROM VEHICLE WHERE VehicleID=%s",(vehicle_id,)); db.commit()
                    flash(f"{vehicle['Make']} {vehicle['Model']} deleted.","success")
    except Error as exc:
        app.logger.exception("Could not delete vehicle"); flash("Could not delete vehicle safely.","error")
    return redirect(url_for("admin_dashboard")+"#vehicles")


@app.route("/admin/rental/<int:rental_id>/payment", methods=["POST"])
@admin_required
def update_payment(rental_id):
    status = request.form.get("status")
    if status not in ("Pending", "Paid"):
        flash("Invalid payment status.", "error")
    else:
        try:
            with closing(get_db_connection()) as db, closing(db.cursor()) as cursor:
                cursor.execute("UPDATE RENTAL SET PaymentStatus=%s WHERE RentalID=%s",(status,rental_id))
                db.commit()
            flash("Payment status updated.", "success")
        except Error as exc:
            app.logger.exception("Payment update failed"); flash("Could not update payment status.","error")
    return redirect(url_for("admin_dashboard")+"#rentals")


@app.route("/admin/customer/<int:customer_id>/details", methods=["POST"])
@admin_required
def update_customer_details(customer_id):
    phone = request.form.get("phone", "").strip()
    address = request.form.get("address", "").strip()
    license_number = request.form.get("license_number", "").strip()
    note = request.form.get("admin_note", "").strip()
    try:
        if not phone or len(phone) > 15 or not address or len(address) > 200 or len(license_number) > 50 or len(note) > 300:
            raise ValueError
        with closing(get_db_connection()) as db, closing(db.cursor()) as cursor:
            ensure_business_tables(cursor)
            cursor.execute("SELECT CustomerID FROM CUSTOMER WHERE CustomerID=%s", (customer_id,))
            if not cursor.fetchone():
                flash("Customer not found.", "error")
                return redirect(url_for("admin_dashboard") + "#customers")
            cursor.execute("""UPDATE CUSTOMER SET Phone=%s,Address=%s,LicenseNumber=%s WHERE CustomerID=%s""",
                           (phone,address,license_number,customer_id))
            cursor.execute("""INSERT INTO CUSTOMER_MANAGEMENT(CustomerID,BookingsEnabled,AdminNote)
                VALUES (%s,1,%s) ON DUPLICATE KEY UPDATE AdminNote=VALUES(AdminNote)""",(customer_id,note))
            db.commit()
            flash("Customer details saved.", "success")
    except (ValueError, Error):
        app.logger.exception("Could not update customer details")
        flash("Check the customer contact, address, and licence fields.", "error")
    return redirect(url_for("admin_dashboard") + "#customers")


@app.route("/admin/customer/<int:customer_id>/booking-access", methods=["POST"])
@admin_required
def update_customer_booking_access(customer_id):
    enabled = request.form.get("enabled") == "1"
    try:
        with closing(get_db_connection()) as db, closing(db.cursor(dictionary=True)) as cursor:
            ensure_business_tables(cursor)
            cursor.execute("SELECT CustomerID FROM CUSTOMER WHERE CustomerID=%s", (customer_id,))
            if not cursor.fetchone():
                flash("Customer not found.", "error")
            else:
                cursor.execute("""INSERT INTO CUSTOMER_MANAGEMENT(CustomerID,BookingsEnabled)
                    VALUES (%s,%s) ON DUPLICATE KEY UPDATE BookingsEnabled=VALUES(BookingsEnabled)""",
                    (customer_id,int(enabled)))
                db.commit()
                flash("Customer booking access updated.", "success")
    except Error:
        app.logger.exception("Could not update customer booking access")
        flash("Could not update this customer's booking access.", "error")
    return redirect(url_for("admin_dashboard") + "#customers")


@app.route("/admin/rental/<int:rental_id>/vehicle-status", methods=["POST"])
@admin_required
def update_rental_vehicle_status(rental_id):
    status = request.form.get("status")
    if status not in ("Rented", "Available"):
        flash("Invalid vehicle status.", "error")
        return redirect(url_for("admin_dashboard") + "#rented-panel")
    try:
        with closing(get_db_connection()) as db, closing(db.cursor(dictionary=True)) as cursor:
            cursor.execute("SELECT VehicleID FROM RENTAL WHERE RentalID=%s", (rental_id,))
            rental = cursor.fetchone()
            if not rental:
                flash("Rental record not found.", "error")
            else:
                if status == "Available":
                    cursor.execute("SELECT COUNT(*) AS n FROM MAINTENANCE WHERE VehicleID=%s AND Status<>'Completed'",
                                   (rental["VehicleID"],))
                    status = "Maintenance" if cursor.fetchone()["n"] else "Available"
                cursor.execute("UPDATE VEHICLE SET Status=%s WHERE VehicleID=%s", (status,rental["VehicleID"]))
                db.commit()
                flash("Vehicle marked as returned." if status == "Available" else
                      ("Vehicle remains unavailable for maintenance." if status == "Maintenance" else
                       "Vehicle kept on rent and removed from availability."), "success")
    except Error:
        app.logger.exception("Could not update rented vehicle status")
        flash("Could not update this vehicle's rental status.", "error")
    return redirect(url_for("admin_dashboard") + "#rented-panel")


@app.route("/admin/service-request/<int:service_id>", methods=["POST"])
@admin_required
def update_service_request(service_id):
    status = request.form.get("status", "Requested")
    staff_id = request.form.get("staff_id", type=int)
    allowed = ("Requested", "Assigned", "In Progress", "Completed", "Cancelled")
    if status not in allowed:
        flash("Choose a valid service request status.", "error")
        return redirect(url_for("admin_dashboard") + "#service-requests")
    if status in ("Assigned", "In Progress") and not staff_id:
        flash("Select a mechanic before assigning or starting this service request.", "error")
        return redirect(url_for("admin_dashboard") + "#service-requests")
    try:
        with closing(get_db_connection()) as db, closing(db.cursor(dictionary=True)) as cursor:
            if staff_id:
                cursor.execute("SELECT StaffID FROM STAFF WHERE StaffID=%s AND LOWER(Role)='mechanic'", (staff_id,))
                if not cursor.fetchone():
                    flash("Assign this request to a Mechanic.", "error")
                    return redirect(url_for("admin_dashboard") + "#service-requests")
                if status == "Requested":
                    status = "Assigned"
            cursor.execute("UPDATE SERVICE_REQUEST SET Status=%s,StaffID=%s WHERE ServiceRequestID=%s",
                           (status,staff_id,service_id))
            db.commit()
            flash("Service request updated. Contact the customer to confirm the visit.", "success")
    except Error:
        app.logger.exception("Could not update service request")
        flash("Could not update this service request.", "error")
    return redirect(url_for("admin_dashboard") + "#service-requests")


@app.route("/admin/rental/<int:rental_id>/return", methods=["POST"])
@admin_required
def mark_returned(rental_id):
    try:
        with closing(get_db_connection()) as db, closing(db.cursor()) as cursor:
            cursor.execute("SELECT VehicleID FROM RENTAL WHERE RentalID=%s", (rental_id,))
            rental = cursor.fetchone()
            if not rental:
                flash("Rental not found.", "error")
            else:
                cursor.execute("SELECT COUNT(*) FROM MAINTENANCE WHERE VehicleID=%s AND Status<>'Completed'", (rental[0],))
                status = "Maintenance" if cursor.fetchone()[0] else "Available"
                cursor.execute("UPDATE VEHICLE SET Status=%s WHERE VehicleID=%s", (status, rental[0]))
                db.commit()
                flash("Vehicle marked as returned and available.", "success")
    except Error as exc:
        app.logger.exception("Could not mark vehicle returned")
        flash("Could not update this rental.", "error")
    return redirect(url_for("admin_dashboard") + "#rentals")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
