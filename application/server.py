import os
import uuid
import redis
import time
import csv
import io
from datetime import timedelta
import requests
import sentry_sdk
from functools import wraps
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId
from flask_session import Session
from flask_social_oauth import Config, initialize_social_login
from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    session,
    jsonify,
    request,
    abort,
    Response,
)

# Helper functions


def is_user_authenticated(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user" in session:
            return redirect(url_for("index"))
        else:
            return func(*args, **kwargs)

    return wrapper


def generate_user_session(user, provider):
    if provider == "google":
        mongodb_cursor["users"].find_one_and_update(
            {"user_email": user["email"].lower()},
            {
                "$set": {
                    "user_info": {
                        "user_name": user["name"],
                        "user_avatar_url": user["picture"],
                        "user_provider": provider,
                    },
                    "account_info": {
                        "last_login": time.time(),
                    },
                }
            },
            upsert=True,
        )
    elif provider == "github":
        mongodb_cursor["users"].find_one_and_update(
            {"user_email": user["email"].lower()},
            {
                "$set": {
                    "user_info": {
                        "user_name": user["name"],
                        "user_avatar_url": user["avatar_url"],
                        "user_provider": provider,
                    },
                    "account_info": {
                        "last_login": time.time(),
                    },
                }
            },
            upsert=True,
        )

    user_info = mongodb_cursor["users"].find_one({"user_email": user["email"].lower()})

    return {
        "id": str(user_info["_id"]),
        "email": user_info["user_email"],
        "name": user_info["user_info"]["user_name"],
        "user_avatar_url": user_info["user_info"]["user_avatar_url"],
        "provider": user_info["user_info"]["user_provider"],
    }


def is_session_valid(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user" in session:
            return func(*args, **kwargs)
        else:
            session["next"] = request.url
            return redirect(url_for("auth_register"))

    return wrapper


def image_uploader(image):
    try:

        response = requests.post(
            "https://api.imgbb.com/1/upload",
            files={"image": image},
            data={
                "key": "34ac0186cc7075a3a6cf707006ecfef9",
                "name": f"{uuid.uuid4()}",
            },
            timeout=10,
        )

        if response.status_code != 200:
            return None

        return response.json()["data"]["url"]

    except TimeoutError:
        return None


# Load environment variables
load_dotenv()

# Initialize MongoDB client

mongdb_connection = MongoClient(
    os.getenv("MONGODB_URI"),
)
mongodb_cursor = mongdb_connection["prod"]

# Initialize Social OAuth configuration
config = Config(
    social_auth_providers=["google"],
    application_root_url="https://techodyssey.dev",
)

config.google_auth(
    google_auth_client_id=os.getenv("GOOGLE_CLIENT_ID"),
    google_auth_client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    google_auth_scope="email profile",
    google_auth_initialization_handler_uri="/authentication/initialize/google",
    google_auth_callback_handler_uri="/api/v1/authentication/handler/google",
    google_auth_initialization_handler_wrapper=is_user_authenticated,
)

# Initialize Flask app

app = Flask(__name__)

# Flask configuration

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

# Session configuration

app.config["SESSION_TYPE"] = "redis"
app.config["SESSION_REDIS"] = redis.from_url(
    os.getenv("REDIS_URI"),
)
app.config["SESSION_PERMANENT"] = True
app.config["SESSION_USE_SIGNER"] = True
app.config["SESSION_KEY_PREFIX"] = "techodyssey-"
app.config["SESSION_COOKIE_NAME"] = "techodyssey-session"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_PATH"] = "/"
app.config["SESSION_COOKIE_DOMAIN"] = ".techodyssey.dev"

# Set session lifetime to 6 months (in seconds)
six_months_in_seconds = 6 * 30 * 24 * 60 * 60
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(seconds=six_months_in_seconds)

# Optionally refresh the session each request
app.config["SESSION_REFRESH_EACH_REQUEST"] = True

# Initialize session
Session(app)


# Flask OAuth initialization

initialize_social_login(session, app, config)


# Request Preprocessor


@app.before_request
def before_request():
    if session.get("user") is not None:
        if session["user"].get("provider") is None:
            session["user"] = generate_user_session(session["user"], "google")

@app.before_request
def before_request():
    if request.url.startswith("http://"):
        url = request.url.replace("http://", "https://", 1)
        return redirect(url, code=301)
    
@app.before_request
def before_request():
    # Block routes to pages, that are closed when the event is completed
    if request.path in ["/register"]:
        return abort(404)


@app.after_request
def after_request(response):
    response.headers["Server"] = "TechOdyssey"
    if (
        request.path == "/api/v1/authentication/handler/google"
        or request.path == "/api/v1/authentication/handler/github"
    ):
        print("Redirecting to next page")
        if session.get("next") is not None:
            response = redirect(session["next"])
            session.pop("next", None)
    return response


# Basic routes


@app.route("/favicon.ico")
def favicon():
    return redirect("https://storage.techodyssey.dev/favicon.ico")


@app.route("/")
def index():
    return render_template("public/home.html")


@app.route("/support")
def support():
    return render_template("public/support.html")


@app.route("/terms-of-service")
def terms_of_service():
    return render_template("public/terms-of-service.html")


@app.route("/privacy-policy")
def privacy_policy():
    return render_template("public/privacy-policy.html")


@app.route("/cancellation")
def cancelation_policy():
    return render_template("public/cancellation-policy.html")


# User routes


@app.route("/user/events")
# @is_session_valid
def user_my_events():
    user_events = mongodb_cursor["registrations"].find(
        {"email": session["user"]["email"]}
    )
    return render_template("user/my-events.html", user_events=user_events)


# Auth routes


@app.route("/authentication/register")
def auth_register():
    return render_template("auth/authentication.html")


@app.route("/authentication/sign-out")
def auth_sign_out():
    session.clear()
    return redirect(url_for("index"))


# Event routes


@app.route("/events/battle-blitz")
def event_battle_blitz():
    return render_template("events/battle-blitz.html")


@app.route("/events/treasure-quest")
def event_treasure_quest():
    return render_template("events/treasure-quest.html")


@app.route("/events/code-clash")
def event_code_clash():
    return render_template("events/code-clash.html")


@app.route("/events/web-dash")
def event_web_dash():
    return render_template("events/web-dash.html")


@app.route("/events/reel-craft")
def event_reel_craft():
    return render_template("events/reel-craft.html")


@app.route("/gallery")
def gallery():
    return render_template("public/gallery.html")


# Registration routes


@app.route("/register")
@is_session_valid
def register():
    return render_template("public/register.html")


# # Registration API routes


@app.route("/api/v1/register", methods=["POST"])
@is_session_valid
def api_register():
    event_reference = {
        "0": "Code Clash",
        "1": "Web Dash",
        "2": "Treasure Quest",
        "3": "Reel Craft",
        "4": "Battle Blitz: Valorant",
        "5": "Battle Blitz: BGMI Mobile",
        "6": "Battle Blitz: Free Fire",
    }

    form_data = request.form
    event_id = form_data.get("event")

    if event_id is None:
        return jsonify(
            {"status": "error", "message": "Please select an event to register."}
        )

    event_name = event_reference.get(event_id)

    if event_id in ["4", "5", "6", "1"]:
        team_name = form_data.get("teamName")

        team_members = form_data.get("teamMembers").split(",")

        for index, member in enumerate(team_members):
            team_members[index] = member.strip().title()
            if team_members[index] == "" or team_members[index] == " ":
                team_members.pop(index)

        if len(team_members) == 0:
            return jsonify(
                {
                    "status": "error",
                    "message": "Please provide the names of all team members.",
                }
            )

        if team_name is None:
            return jsonify(
                {"status": "error", "message": "Please provide a team name."}
            )

        if event_id == "4" and len(team_members) != 5:
            return jsonify(
                {
                    "status": "error",
                    "message": "To participate in Battle Blitz: Valorant, you need to have 5 members in your team.",
                }
            )

        if event_id in ["5", "6", "1"] and len(team_members) != 4:
            return jsonify(
                {
                    "status": "error",
                    "message": "To participate in Battle Blitz: BGMI Mobile or Battle Blitz: Free Fire, you need to have 4 members in your team.",
                }
            )

        if session["user"]["name"].strip().title() not in team_members:
            return jsonify(
                {
                    "status": "error",
                    "message": "You need to be part of the team to register for the event. Please provide your name in the team members list.",
                }
            )

    if form_data.get("phone") is None:
        return jsonify(
            {"status": "error", "message": "Please provide your phone number."}
        )

    if form_data.get("phone").strip() == "":
        return jsonify(
            {"status": "error", "message": "Please provide a valid phone number."}
        )

    if len(form_data.get("phone").strip()) != 10:
        return jsonify(
            {
                "status": "error",
                "message": "Please provide a valid 10-digit phone number.",
            }
        )

    if request.files.get("paymentScreenshot") is None:
        return jsonify(
            {"status": "error", "message": "Please provide the payment screenshot."}
        )

    payment_transaction_id = form_data.get("paymentTransactionId")
    if payment_transaction_id is None:
        return jsonify(
            {"status": "error", "message": "Please provide the payment transaction ID."}
        )

    payment_screenshot_url = image_uploader(request.files.get("paymentScreenshot"))
    if payment_screenshot_url is None:
        return jsonify(
            {
                "status": "error",
                "message": "An error occurred while uploading the payment screenshot. Please try again.",
            }
        )

    try:
        registrations = mongodb_cursor["registrations"]

        if event_id in ["4", "5", "6", "1"]:
            existing_team = registrations.find_one(
                {
                    "event": event_name,
                    "teamName": form_data.get("teamName").strip().title(),
                }
            )
            if existing_team:
                return jsonify(
                    {
                        "status": "error",
                        "message": f"The team name `{form_data.get('teamName').strip().title()}` has already been registered for this event. Please provide a different team name.",
                    }
                )

            if registrations.find_one(
                {
                    "event": event_name,
                    "email": session["user"]["email"],
                }
            ):
                return jsonify(
                    {
                        "status": "error",
                        "message": "You have already registered for this event. You can view your registration status in the `My Events` section.",
                    }
                )

            registrations.insert_one(
                {
                    "event": event_name,
                    "name": form_data.get("name").strip().title(),
                    "email": form_data.get("email").strip().lower(),
                    "phone": form_data.get("phone"),
                    "teamName": form_data.get("teamName").strip().title(),
                    "teamMembers": team_members,
                    "paymentScreenshot": payment_screenshot_url,
                    "paymentTransactionId": payment_transaction_id,
                    "status": "pending",
                }
            )

        else:
            if registrations.find_one(
                {"event": event_name, "email": form_data.get("email").strip().lower()}
            ):
                return jsonify(
                    {
                        "status": "error",
                        "message": "You have already registered for this event. You can view your registration status in the `My Events` section.",
                    }
                )

            registrations.insert_one(
                {
                    "event": event_name,
                    "name": form_data.get("name").strip().title(),
                    "email": form_data.get("email").strip().lower(),
                    "phone": form_data.get("phone"),
                    "paymentScreenshot": payment_screenshot_url,
                    "paymentTransactionId": payment_transaction_id,
                    "status": "pending",
                }
            )

        return jsonify(
            {
                "status": "success",
                "message": "Registration successful. Please wait while our team verifies your payment.",
            }
        )

    except Exception as e:
        return jsonify(
            {
                "status": "error",
                "message": "An error occurred while registering. Please try again.",
            }
        )


# Site map routes


@app.route("/sitemap.xml")
def sitemap():
    return (
        render_template("public/sitemap.xml"),
        200,
        {"Content-Type": "application/xml"},
    )


# Admin Routes


@app.route("/stats")
@is_session_valid
def stats():
    if session["user"]["email"] not in ["om.2472004@gmail.com", "saswatdas1104@gmail.com"]:
        return abort(404)
    number_of_application_users = mongodb_cursor["users"].count_documents({})
    application_users = mongodb_cursor["users"].find({})
    number_of_event_registrations = mongodb_cursor["registrations"].count_documents({})
    event_registrations = mongodb_cursor["registrations"].find({})
    total_amount_received = 0
    for registration in mongodb_cursor["registrations"].find({}):
        if registration["status"] == "approved":
            if registration["event"] == "Code Clash":
                total_amount_received += 150
            elif registration["event"] == "Web Dash":
                total_amount_received += 200
            elif registration["event"] == "Treasure Quest":
                total_amount_received += 100
            elif registration["event"] == "Reel Craft":
                total_amount_received += 100
            else:
                total_amount_received += 400
        else:
            continue

    return render_template(
        "admin/stats.html",
        number_of_application_users=number_of_application_users,
        number_of_event_registrations=number_of_event_registrations,
        application_users=application_users,
        event_registrations=event_registrations,
        total_amount_received=total_amount_received
    )


@app.route("/admin/<registration_id>/<action>")
@is_session_valid
def admin_action(registration_id, action):
    if session["user"]["email"] not in ["om.2472004@gmail.com", "saswatdas1104@gmail.com"]:
        return abort(404)

    registration = mongodb_cursor["registrations"].find_one(
        {"_id": ObjectId(registration_id)}
    )

    if registration is None:
        return abort(404)

    if action == "approve":
        mongodb_cursor["registrations"].find_one_and_update(
            {"_id": ObjectId(registration_id)},
            {
                "$set": {
                    "status": "approved",
                }
            },
        )

    elif action == "reject":
        mongodb_cursor["registrations"].find_one_and_update(
            {"_id": ObjectId(registration_id)},
            {
                "$set": {
                    "status": "rejected",
                }
            },
        )

    else:
        return abort(404)

    return redirect(url_for("stats"))


@app.route("/admin/export/<type_of_data>")
@is_session_valid
def admin_export(type_of_data):
    if session["user"]["email"] not in ["om.2472004@gmail.com", "saswatdas1104@gmail.com"]:
        return abort(404)
    total_registrations = mongodb_cursor["registrations"].find({})

    if type_of_data == "student-info":
        data = []
        for registration in total_registrations:
            if registration["event"] in ["Code Clash", "Treasure Quest", "Reel Craft"]:
                data.append([
                    registration["name"],
                    registration["event"],
                    registration["email"],
                    registration["phone"],
                ])
            else:
                for member in registration["teamMembers"]:
                    if len(member) > 4:
                        data.append([
                            member,
                            registration["event"],
                            registration["email"],
                            registration["phone"],
                        ])

        # Convert list to CSV
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(["Student Name", "Event Name", "Student Email", "Student Phone"])  # CSV Header
        cw.writerows(data)
        output = si.getvalue()

    elif type_of_data == "event-info":
        data = {}
        for registration in total_registrations:
            event = registration["event"]
            if event in data:
                data[event]["Total Registrations"] += 1
                if event == "Battle Blitz: Valorant":
                    data[event]["Total Amount Received"] += 400
                    data[event]["Number of Participants"] += 5
                elif event == "Battle Blitz: BGMI Mobile" or event == "Battle Blitz: Free Fire":
                    data[event]["Total Amount Received"] += 400
                    data[event]["Number of Participants"] += 4
                elif event == "Web Dash":
                    data[event]["Total Amount Received"] += 200
                    data[event]["Number of Participants"] += 4
                elif event == "Code Clash":
                    data[event]["Total Amount Received"] += 150
                    data[event]["Number of Participants"] += 1
                else:
                    data[event]["Total Amount Received"] += 100
                    data[event]["Number of Participants"] += 1
            else:
                # Initialize data structure for new events
                initial_amount = 400 if event == "Battle Blitz: Valorant" else 400 if event in ["Battle Blitz: BGMI Mobile", "Battle Blitz: Free Fire"] else 200 if event == "Web Dash" else 150 if event == "Code Clash" else 100
                participants = 5 if event == "Battle Blitz: Valorant" else 4 if event in ["Battle Blitz: BGMI Mobile", "Battle Blitz: Free Fire", "Web Dash"] else 1

                data[event] = {
                    "Total Registrations": 1,
                    "Total Amount Received": initial_amount,
                    "Number of Participants": participants, 
                }

        # Convert dict to CSV
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(["Event", "Total Registrations", "Total Amount Received", "Number of Participants"])  # CSV Header
        for key, val in data.items():
            cw.writerow([key, val["Total Registrations"], val["Total Amount Received"], val["Number of Participants"]])
        output = si.getvalue()

    else:
        return abort(404)
    
    return Response(output, mimetype="text/csv", headers={"Content-disposition": "attachment; filename=data.csv"})


@app.route("/clue")
def clue():
    return ("""zycyr rd yjicg, ajlfh nwsgc bw ulkq,
ydgrc tqkkgw wgye'q zvczgb rzjsul,
e uasdbxswr pevjvhp tq xfx pcdb,
ecfwera mvz gkyvw, xfx ttpnh gk vvypr | VIGENERE""")
        


# Error handlers


@app.errorhandler(404)
def page_not_found(error):
    return (
        render_template(
            "public/error.html",
            error_code=404,
            error_message="The requested page was not found.",
            error_description="The page you are looking for might have been removed, had its name changed, or is temporarily unavailable.",
        ),
        404,
    )


@app.errorhandler(500)
def internal_server_error(error):
    return (
        render_template(
            "public/error.html",
            error_code=500,
            error_message="Something went wrong.",
            error_description="The server encountered a situation it doesn't know how to handle.",
        ),
        500,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=False)
