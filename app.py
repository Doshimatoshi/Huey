import json
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

# Older copies of huey.db predate profiles.confidence (NULL when the tone was picked by hand)
if not db.execute("SELECT 1 FROM pragma_table_info('profiles') WHERE name = 'confidence'"):
    db.execute(
        "ALTER TABLE profiles ADD COLUMN confidence TEXT CHECK (confidence IN ('high', 'medium', 'low'))"
    )

# Messages sent from /contact; user_id is set when the sender was signed in
db.execute(
    """
    CREATE TABLE IF NOT EXISTS contact_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reason TEXT NOT NULL CHECK (reason IN ('brand', 'help', 'other')),
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        company TEXT,
        website TEXT,
        message TEXT NOT NULL,
        user_id INTEGER,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """
)

# Answers from /questionnaire. Multi-choice answers are JSON lists, e.g. '["foundation", "hosiery"]';
# every answer is optional, so any column may be NULL.
db.execute(
    """
    CREATE TABLE IF NOT EXISTS questionnaire_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        categories_bought TEXT,
        categories_bought_other TEXT,
        shade_method TEXT,
        shade_method_other TEXT,
        wrong_shade TEXT,
        given_up TEXT,
        most_useful TEXT,
        categories_first TEXT,
        categories_first_other TEXT,
        tone_input TEXT,
        photo_comfort TEXT,
        photo_comfort_improve TEXT,
        trust_level TEXT,
        trust_boosters TEXT,
        trust_other TEXT,
        buy_where TEXT,
        buy_where_other TEXT,
        buy_via_link TEXT,
        wish TEXT,
        age_range TEXT,
        tone_description TEXT,
        email TEXT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """
)


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


def get_profile(user_id):
    """The user's saved tone and sensitivity, or None if they haven't set a tone yet"""
    rows = db.execute(
        """
        SELECT profiles.mst_value, profiles.sensitivity_type, profiles.confidence,
            mst_scale.label, mst_scale.hex_value
        FROM profiles
        JOIN mst_scale ON profiles.mst_value = mst_scale.id
        WHERE profiles.user_id = ?
        """,
        user_id,
    )
    return rows[0] if rows else None


def home_for(user_id):
    """Shop for users with a saved tone, the profile page to set one up otherwise"""
    return "/matches" if get_profile(user_id) else "/profile"


@app.route("/")
def index():
    """Show the landing page to signed-out visitors; send everyone else home"""
    if not session.get("user_id"):
        # Gallery cards for categories without products yet are marked "Coming soon"
        categories = {row["category"] for row in db.execute("SELECT DISTINCT category FROM products")}
        return render_template("landing.html", categories=categories)
    return redirect(home_for(session["user_id"]))

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
    profile = get_profile(session["user_id"])
    if profile is None:
        return redirect("/profile")

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

        return redirect(home_for(session["user_id"]))

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

        # A new account has no tone yet
        return redirect("/profile")

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


@app.route("/delete_account", methods=["POST"])
@login_required
def delete_account():
    """Delete the user and everything stored about them, after re-checking their password"""
    rows = db.execute("SELECT hash FROM users WHERE id = ?", session["user_id"])
    if not check_password_hash(rows[0]["hash"], request.form.get("password", "")):
        return apology("incorrect password", 400)

    db.execute("DELETE FROM contact_messages WHERE user_id = ?", session["user_id"])
    db.execute("DELETE FROM questionnaire_responses WHERE user_id = ?", session["user_id"])
    db.execute("DELETE FROM gallery_entries WHERE user_id = ?", session["user_id"])
    db.execute("DELETE FROM profiles WHERE user_id = ?", session["user_id"])
    db.execute("DELETE FROM users WHERE id = ?", session["user_id"])

    session.clear()
    flash("Your account and skin profile have been deleted.")
    return redirect("/")


# Monk skin setup page
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # reject uploads over 10 MB

METHODS = {"hex", "upload", "selfie"}
CONFIDENCES = {"high", "medium", "low"}
SENSITIVITIES = {"low", "moderate", "high"}

def get_mst_scale():
    # Lightest to darkest, so row 0 is tone 1
    return db.execute("SELECT id, label, hex_value FROM mst_scale ORDER BY id")


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Everything about the user: tone, sensitivity, password, privacy and account deletion"""
    profile = get_profile(session["user_id"])
    mst_scale = get_mst_scale()

    if request.method == "POST":
        # Small edits to an existing profile; a first tone is set through /setup
        if profile is None:
            return redirect("/profile")

        if "mst_value" in request.form:
            rows_by_id = {str(row["id"]): row for row in mst_scale}
            tone = rows_by_id.get(request.form.get("mst_value", ""))
            if tone is None:
                return apology("choose a skin tone", 400)
            # Picking a neighbouring tone is a choice by hand, so the photo's confidence no longer applies
            db.execute(
                "UPDATE profiles SET mst_value = ?, confidence = NULL WHERE user_id = ?",
                tone["id"], session["user_id"],
            )
            flash(f"Tone updated to {tone['id']} of 10.")

        if "sensitivity" in request.form:
            sensitivity = request.form.get("sensitivity")
            if sensitivity not in SENSITIVITIES:
                return apology("choose how reactive your skin is", 400)
            db.execute(
                "UPDATE profiles SET sensitivity_type = ? WHERE user_id = ?",
                sensitivity, session["user_id"],
            )
            flash("Sensitivity updated.")

        return redirect("/profile")

    # Offer the tones either side of a reading that wasn't certain
    neighbours = []
    if profile and profile["confidence"] in ("medium", "low"):
        neighbours = [
            row for row in mst_scale if abs(row["id"] - profile["mst_value"]) == 1
        ]

    return render_template("profile.html", profile=profile, neighbours=neighbours)


@app.route("/setup", methods=["GET", "POST"])
@login_required
def setup():
    mst_scale = get_mst_scale()

    if request.method == "GET":
        method = request.args.get("method", "hex")
        if method not in METHODS:
            return apology("invalid method", 400)
        # The saved tone stays in place, and on screen, until a new one is confirmed
        return render_template(
            "tone.html", method=method, mst_scale=mst_scale, profile=get_profile(session["user_id"])
        )

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

    # Only sent when the photo analysis' top match was kept; anything else counts as picked by hand
    confidence = request.form.get("confidence")
    if confidence not in CONFIDENCES:
        confidence = None

    db.execute(
        """
        INSERT INTO profiles (user_id, mst_value, sensitivity_type, confidence) VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            mst_value = excluded.mst_value,
            sensitivity_type = excluded.sensitivity_type,
            confidence = excluded.confidence
        """,
        session["user_id"], tone["id"], sensitivity, confidence,
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


CONTACT_REASONS = {
    "brand": "List my brand's products",
    "help": "Help with my account or tone",
    "other": "Something else",
}
MAX_MESSAGE_LENGTH = 5000


@app.route("/contact", methods=["GET", "POST"])
def contact():
    """Brands asking to be listed, and users who need help"""
    if request.method == "GET":
        # Prefill what we already know about a signed-in user; ?reason=brand preselects the topic
        form = {"reason": request.args.get("reason", "")}
        if session.get("user_id"):
            rows = db.execute("SELECT username, email FROM users WHERE id = ?", session["user_id"])
            form.update(name=rows[0]["username"], email=rows[0]["email"])
        return render_template("contact.html", reasons=CONTACT_REASONS, form=form)

    form = {key: request.form.get(key, "").strip() for key in
            ("reason", "name", "email", "company", "website", "message")}

    # Brand fields are hidden for other topics, so ignore anything left in them
    if form["reason"] != "brand":
        form["company"] = form["website"] = ""

    # Bots fill in every field, including this one that people never see
    if request.form.get("nickname"):
        return redirect("/contact")

    error = None
    if form["reason"] not in CONTACT_REASONS:
        error = "Choose what you're getting in touch about."
    elif not form["name"]:
        error = "Tell us your name."
    elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", form["email"]):
        error = "Enter a valid email address so we can reply."
    elif form["reason"] == "brand" and not form["company"]:
        error = "Tell us your brand's name."
    elif not form["message"]:
        error = "Write a message."
    elif len(form["message"]) > MAX_MESSAGE_LENGTH:
        error = f"Keep your message under {MAX_MESSAGE_LENGTH} characters."
    if error:
        return render_template("contact.html", reasons=CONTACT_REASONS, form=form, error=error), 400

    db.execute(
        """
        INSERT INTO contact_messages (reason, name, email, company, website, message, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        form["reason"], form["name"], form["email"].lower(),
        form["company"] or None, form["website"] or None, form["message"],
        session.get("user_id"),
    )
    flash("Thanks, your message has been sent. We'll reply by email.")
    return redirect("/contact")


# Customer research questionnaire. Each list is (stored value, label shown).
SURVEY_CATEGORIES = [
    ("foundation", "Foundation or concealer"),
    ("bandages", "Bandages or plasters"),
    ("hosiery", "Tights or hosiery"),
    ("sunscreen", "Tinted sunscreen"),
    ("shoes", "Shoes, such as ballet flats"),
    ("underwear", "Underwear or shapewear"),
    ("dancewear", "Dance wear"),
    ("hearing_aids", "Hearing aids"),
    ("compression", "Compression wear"),
    ("art_supplies", "Art supplies, such as skin-tone crayons"),
    ("prosthetics", "Prosthetics"),
    ("dolls_toys", "Dolls and toys"),
    ("other", "Other"),
]
SURVEY_OPTIONS = {
    "categories_bought": SURVEY_CATEGORIES + [("none", "None of these")],
    "shade_method": [
        ("swatch", "Swatched or tried it in store"),
        ("trial_error", "Trial and error"),
        ("reviews", "Read reviews"),
        ("shade_finder", "Used the brand's shade finder"),
        ("friend", "Asked a friend"),
        ("guessed", "Guessed"),
        ("other", "Other"),
    ],
    "wrong_shade": [
        ("never", "Never"),
        ("once_twice", "Once or twice"),
        ("often", "Often"),
        ("almost_always", "Almost every time"),
    ],
    "most_useful": [
        ("across_categories", "Finding products in my tone across categories"),
        ("discovery", "Seeing products I wouldn't have found elsewhere"),
        ("compare_brands", "Comparing brands in my tone"),
        ("single_match", "A shade match for one specific product"),
        ("favourites", "Saving a list of favourites"),
        ("alerts", "Alerts when new products arrive in my tone"),
    ],
    "categories_first": SURVEY_CATEGORIES,
    "tone_input": [
        ("selfie", "Take a selfie"),
        ("upload", "Upload a photo"),
        ("scale", "Pick from a scale of tones"),
        ("words", "Describe it in words"),
        ("no_preference", "No preference"),
    ],
    "photo_comfort": [
        ("very", "Very comfortable"),
        ("if_deleted", "Fine if it's deleted afterwards"),
        ("no_upload", "Only if I never have to upload it"),
        ("not", "Not comfortable"),
    ],
    "trust_level": [
        ("not_at_all", "Not at all"),
        ("a_little", "A little"),
        ("quite_a_lot", "Quite a lot"),
        ("completely", "Completely"),
    ],
    "trust_boosters": [
        ("real_skin_photo", "A photo of the product on real skin"),
        ("reviews_my_tone", "Reviews from people in my tone"),
        ("brand_shade_info", "The brand's own shade information"),
        ("tone_scale", "The tone shown on a scale"),
        ("other", "Other"),
    ],
    "buy_where": [
        ("brand_sites", "Brand websites"),
        ("large_retailers", "Large retailers"),
        ("marketplaces", "Marketplaces"),
        ("pharmacies", "Pharmacies"),
        ("in_store", "In store"),
        ("other", "Other"),
    ],
    "buy_via_link": [("yes", "Yes"), ("maybe", "Maybe"), ("no", "No")],
    "age_range": [
        ("under_18", "Under 18"),
        ("18_24", "18–24"),
        ("25_34", "25–34"),
        ("35_44", "35–44"),
        ("45_54", "45–54"),
        ("55_64", "55–64"),
        ("65_plus", "65 or over"),
        ("prefer_not", "Prefer not to say"),
    ],
}
SURVEY_MULTI = {"categories_bought", "most_useful", "categories_first", "trust_boosters", "buy_where"}
SURVEY_TEXT = [
    "categories_bought_other", "shade_method_other", "given_up", "categories_first_other",
    "photo_comfort_improve", "trust_other", "buy_where_other", "wish", "tone_description", "email",
]
MAX_ANSWER_LENGTH = 2000
MAX_MOST_USEFUL = 3


@app.route("/questionnaire", methods=["GET", "POST"])
def questionnaire():
    """Short research survey about shade-matching pain points; open to anyone"""
    if request.method == "GET":
        return render_template("questionnaire.html", options=SURVEY_OPTIONS, answers=request.form)

    # Bots fill in every field, including this one that people never see
    if request.form.get("nickname"):
        return redirect("/questionnaire/thanks")

    # Keep only answers that are real options, so the table holds clean values
    answers = {}
    for field, options in SURVEY_OPTIONS.items():
        allowed = {value for value, _ in options}
        if field in SURVEY_MULTI:
            chosen = [value for value in request.form.getlist(field) if value in allowed]
            answers[field] = json.dumps(chosen) if chosen else None
        else:
            value = request.form.get(field)
            answers[field] = value if value in allowed else None
    for field in SURVEY_TEXT:
        answers[field] = request.form.get(field, "").strip() or None

    # error_step is the question the page reopens at, so the problem is in view
    error, error_step = None, 1
    bought = request.form.getlist("categories_bought")
    if "none" in bought and len(bought) > 1:
        error = "In question 1, choose either “None of these” or the products you bought, not both."
    elif len(request.form.getlist("most_useful")) > MAX_MOST_USEFUL:
        error, error_step = f"In question 5, choose up to {MAX_MOST_USEFUL} options.", 5
    elif any(len(answers[field] or "") > MAX_ANSWER_LENGTH for field in SURVEY_TEXT):
        error = f"Please keep each written answer under {MAX_ANSWER_LENGTH} characters."
    elif answers["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", answers["email"]):
        error, error_step = "Enter a valid email address in question 13, or leave it blank.", 13
    elif not any(answers.values()):
        error = "Please answer at least one question before sending."
    if error:
        return render_template(
            "questionnaire.html", options=SURVEY_OPTIONS, answers=request.form,
            error=error, error_step=error_step,
        ), 400

    if answers["email"]:
        answers["email"] = answers["email"].lower()
    columns = list(answers)
    db.execute(
        f"INSERT INTO questionnaire_responses ({', '.join(columns)}, user_id) "
        f"VALUES ({', '.join('?' * len(columns))}, ?)",
        *answers.values(), session.get("user_id"),
    )
    return redirect("/questionnaire/thanks")


@app.route("/questionnaire/thanks")
def questionnaire_thanks():
    return render_template("questionnaire.html", thanks=True)
