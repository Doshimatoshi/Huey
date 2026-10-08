import re
from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from skintone import SkinToneError, analyze
from helpers import apology, login_required

# Configure application
app = Flask(__name__)

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///huey.db")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
def index():
    """Show the landing page to signed-out visitors, the profile page otherwise"""
    if not session.get("user_id"):
        return render_template("landing.html")

    rows = db.execute(
        """
        SELECT profiles.sensitivity_type, mst_scale.label, mst_scale.hex_value
        FROM profiles
        JOIN mst_scale ON profiles.mst_value = mst_scale.id
        WHERE profiles.user_id = ?
        """,
        session["user_id"],
    )
    profile = rows[0] if rows else None

    return render_template("index.html", profile=profile)

@app.route("/products")
def products():
    """List products, optionally filtered by search text, category and, when signed in, the user's tone"""
    category = request.args.get("category")
    q = request.args.get("q", "").strip()

    # Signed-in users with a profile only see products made for their MST tone
    mst_value = None
    if session.get("user_id"):
        rows = db.execute("SELECT mst_value FROM profiles WHERE user_id = ?", session["user_id"])
        if rows:
            mst_value = rows[0]["mst_value"]

    conditions = []
    params = []
    if category:
        conditions.append("category = ?")
        params.append(category)
    if q:
        # Searches through product's name, brand, category or flags
        for word in q.split():
            conditions.append(
                "(name LIKE ? OR brand LIKE ? OR category LIKE ? OR IFNULL(sensitivity_flags, '') LIKE ?)"
            )
            params.extend([f"%{word}%"] * 4)
    if mst_value is not None:
        conditions.append("mst_range_min <= ? AND mst_range_max >= ?")
        params.extend([mst_value, mst_value])

    query = "SELECT * FROM products"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY name"

    rows = db.execute(query, *params)
    return render_template(
        "products.html", products=rows, category=category, q=q, mst_value=mst_value
    )


@app.route("/matches")
@login_required
def matches():
    """The signed-in shop page: categories plus products matched to the user's profile"""
    rows = db.execute(
        """
        SELECT profiles.mst_value, profiles.sensitivity_type, mst_scale.label
        FROM profiles
        JOIN mst_scale ON profiles.mst_value = mst_scale.id
        WHERE profiles.user_id = ?
        """,
        session["user_id"],
    )
    if not rows:
        return redirect("/")
    profile = rows[0]

    # Each category's thumbnail is an image pulled from its first or last product cover image
    categories = db.execute(
        """
        SELECT category,
            (SELECT img_url FROM products AS p
             WHERE p.category = products.category AND p.img_url IS NOT NULL AND p.img_url != ''
             ORDER BY p.id DESC LIMIT 1) AS img_url
        FROM products
        GROUP BY category
        ORDER BY category
        """
    )

    matched_products = db.execute(
        """
        SELECT * FROM products
        WHERE mst_range_min <= ? AND mst_range_max >= ?
        ORDER BY brand, name
        """,
        profile["mst_value"], profile["mst_value"],
    )

    return render_template(
        "matches.html", profile=profile, categories=categories, products=matched_products
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]
        session["username"] = rows[0]["username"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Sign up a new user"""
    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username:
            return apology("You must provide a username", 400)

        if not email:
            return apology("You must provide an email", 400)

        if not password:
            return apology("You must provide a password", 400)

        if not confirmation:
            return apology("You must provide confirmation", 400)

        if password != confirmation:
            return apology("Your passwords must match", 400)

        # Emails are compared case-sensitively by the database, so normalise them
        email = email.strip().lower()

        # Checking if a user with the same username or email already exists
        rows = db.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?", username, email
        )
        if len(rows) > 0:
            return apology("Username or email already in use", 400)

        user_id = db.execute(
            "INSERT INTO users (username, email, hash) VALUES (?, ?, ?)",
            username,
            email,
            generate_password_hash(password),
        )

        # Logging in the user
        session["user_id"] = user_id
        session["username"] = username

        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("signup.html")


@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    """Change password"""
    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirmation = request.form.get("confirmation")

        if not current_password:
            return apology("You must provide the old password", 400)

        if not new_password:
            return apology("You must provide a new password", 400)

        if not confirmation:
            return apology("You must provide a password confirmation", 400)

        if new_password != confirmation:
            return apology("Your passwords must match", 400)

        rows = db.execute("SELECT hash FROM users WHERE id = ?", session["user_id"])

        # Verifying that the current password is correct
        if not check_password_hash(rows[0]["hash"], current_password):
            return apology("incorrect current password", 400)

        # Generating a brand new hash for the new password to overwrite the old one
        new_hash = generate_password_hash(new_password)
        db.execute("UPDATE users SET hash = ? WHERE id = ?", new_hash, session["user_id"])

        # Log user out of current session
        session.clear()

        # Redirect user to login form
        return redirect("/login")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("change_password.html")


# Monk skin setup page
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # reject uploads over 10 MB

METHODS = {"hex", "upload", "selfie"}
SENSITIVITIES = {"low", "moderate", "high"}

def get_mst_scale():
    # Lightest to darkest, so row 0 is tone 1
    return db.execute("SELECT id, label, hex_value FROM mst_scale ORDER BY id")


@app.route("/setup", methods=["GET", "POST"])
@login_required
def setup():
    mst_scale = get_mst_scale()

    if request.method == "GET":
        method = request.args.get("method", "hex")
        if method not in METHODS:
            return apology("invalid method", 400)
        return render_template("tone.html", method=method, mst_scale=mst_scale)

    # --- POST: save the profile ---
    sensitivity = request.form.get("sensitivity")
    if sensitivity not in SENSITIVITIES:
        return apology("choose how reactive your skin is", 400)

    # Every method ends with an MST id: picked from the dropdown,
    # or filled in from the photo analysis (which the user can still change).
    rows_by_id = {str(row["id"]): row for row in mst_scale}
    tone = rows_by_id.get(request.form.get("mst_value", ""))
    if tone is None:
        return apology("choose a skin tone", 400)

    db.execute(
        """
        INSERT INTO profiles (user_id, mst_value, sensitivity_type) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            mst_value = excluded.mst_value,
            sensitivity_type = excluded.sensitivity_type
        """,
        session["user_id"], tone["id"], sensitivity,
    )
    flash("Skin profile saved.")
    return redirect("/matches")


@app.route("/setup/analyze", methods=["POST"])
@login_required
def setup_analyze():
    """Called with fetch() from the upload and selfie pages. Returns JSON, saves nothing."""
    photo = request.files.get("photo")
    if not photo:
        return jsonify(error="Choose or take a photo first."), 400

    reference = None
    if request.form.get("ref_x") and request.form.get("ref_y"):
        try:
            reference = (float(request.form["ref_x"]), float(request.form["ref_y"]))
        except ValueError:
            return jsonify(error="Invalid white point."), 400
        if not all(0 <= v <= 1 for v in reference):
            return jsonify(error="Invalid white point."), 400

    mst_scale = get_mst_scale()
    try:
        result = analyze(photo.read(), reference, palette=[row["hex_value"] for row in mst_scale])
    except SkinToneError as e:
        return jsonify(error=str(e)), 400

    # Translate tone positions (1–10) into your mst_scale ids and labels
    for match in result["matches"]:
        row = mst_scale[match["tone"] - 1]
        match["id"] = row["id"]
        match["label"] = row["label"]
    result["mst_id"] = result["matches"][0]["id"]
    return jsonify(result)


# About Huey page
@app.route("/about")
def about():
    return render_template("about.html")
