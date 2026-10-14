import os
import logging
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv
from models import db
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

# ---------- Service role (microservice split) ----------
# One codebase, one image, three deployable services:
#   web        -> public site + customer QR menu/ordering
#   owner      -> restaurant owner/staff dashboard   (/owner/...)
#   superadmin -> platform admin                     (/superadmin/...)
#   all        -> everything in one process (default, same as before)
SERVICE_ROLE = os.environ.get("SERVICE_ROLE", "all").lower()
ROLE_BLUEPRINTS = {
    "all": None,
    "web": {"public", "customer"},
    "owner": {"owner"},
    "superadmin": {"superadmin"},
}


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """Several containers share one SQLite file: WAL + busy timeout avoid 'database is locked'."""
    if dbapi_conn.__class__.__module__.startswith("sqlite3"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# DB and log live here. In Docker this is a mounted volume (/data) so data survives rebuilds.
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(DATA_DIR, "app.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("rtrms")


def create_app():
    app = Flask(__name__)
    # Behind the nginx gateway: trust X-Forwarded-* so redirects / OAuth callback URLs are correct.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_only_change_me")

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(DATA_DIR, "rtrms_saas.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "static", "images", "food")
    app.config["UPLOAD_FOLDER_HD"] = os.path.join(BASE_DIR, "static", "images", "food_hd")
    app.config["BG_FOLDER"] = os.path.join(BASE_DIR, "static", "images", "bg")
    app.config["QR_FOLDER"] = os.path.join(BASE_DIR, "static", "images", "qr")
    app.config["BACKUP_FOLDER"] = os.path.join(BASE_DIR, "backups")
    for folder_key in ["UPLOAD_FOLDER", "UPLOAD_FOLDER_HD", "BG_FOLDER", "QR_FOLDER", "BACKUP_FOLDER"]:
        os.makedirs(app.config[folder_key], exist_ok=True)

    app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID")
    app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET")
    app.config["SUPERADMIN_USERNAME"] = os.environ.get("SUPERADMIN_USERNAME")
    app.config["SUPERADMIN_PASSWORD"] = os.environ.get("SUPERADMIN_PASSWORD")
    app.config["PUBLIC_URL"] = os.environ.get("PUBLIC_URL", "http://127.0.0.1:5000")

    db.init_app(app)

    from oauth import init_oauth
    init_oauth(app)

    from blueprints.customer import customer_bp
    from blueprints.owner import owner_bp
    from blueprints.superadmin import superadmin_bp
    from blueprints.public import public_bp

    app.register_blueprint(customer_bp)
    app.register_blueprint(owner_bp, url_prefix="/owner")
    app.register_blueprint(superadmin_bp, url_prefix="/superadmin")
    app.register_blueprint(public_bp)

    with app.app_context():
        db.create_all()

    # ---------- Microservice guard ----------
    # All blueprints stay registered (so url_for() links between pages keep working),
    # but each service only ANSWERS the routes that belong to its role.
    allowed = ROLE_BLUEPRINTS.get(SERVICE_ROLE)

    if allowed is not None:
        @app.before_request
        def _role_guard():
            if request.blueprint is not None and request.blueprint not in allowed:
                from flask import abort
                abort(404)

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    # ---------- Resilience: one crashing request never brings down the app ----------
    # Flask/WSGI already isolates each request in its own thread/worker — an
    # unhandled exception in one visitor's request does not stop the server
    # from serving everyone else. These handlers just make sure that instead of
    # a raw traceback, people see a normal page, and every failure gets logged
    # so it can be fixed without anyone being locked out of the whole system.

    @app.errorhandler(404)
    def handle_404(e):
        return render_template("error.html", code=404,
                                message="Page not found."), 404

    @app.errorhandler(500)
    def handle_500(e):
        logger.exception("Unhandled server error on %s %s", request.method, request.path)
        db.session.rollback()  # never leave a half-committed transaction hanging
        if request.is_json:
            return jsonify({"success": False, "error": "server_error"}), 500
        return render_template("error.html", code=500,
                                message="Something went wrong on our side. Please try again."), 500

    @app.errorhandler(Exception)
    def handle_uncaught(e):
        logger.exception("Uncaught exception on %s %s", request.method, request.path)
        db.session.rollback()
        if request.is_json:
            return jsonify({"success": False, "error": "server_error"}), 500
        return render_template("error.html", code=500,
                                message="Something went wrong on our side. Please try again."), 500

    return app


if __name__ == "__main__":
    app = create_app()
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
