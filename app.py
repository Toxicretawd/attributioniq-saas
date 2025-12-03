# app.py
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity, create_access_token, decode_token
import os
from datetime import datetime, timedelta

# --- App Initialization ---
app = Flask(__name__)
CORS(app)  # Enable Cross-Origin Resource Sharing for all routes

# --- Configuration ---
# This block determines the database URI based on the environment.
if os.environ.get('RENDER'):  # Check if we are running on Render
    database_url = os.getenv('DATABASE_URL')
    
    # If DATABASE_URL is not set, fail with a clear error message.
    if not database_url:
        raise RuntimeError("FATAL: RENDER environment detected, but DATABASE_URL is not set. Please check your Render environment variables.")

    # Render provides a postgres:// URL, but SQLAlchemy needs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url

else:  # Local development
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///development.db'
    print("⚠️ Using SQLite for local development (PostgreSQL will be used in production)")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Set the JWT secret key ONCE from environment variables or a default.
app.config['JWT_SECRET_KEY'] = 'a-temporary-hardcoded-secret-key-for-debugging-12345'
# --- Extensions Initialization ---
db = SQLAlchemy(app)
jwt = JWTManager(app)

# This tells flask-jwt-extended how to handle expired/invalid tokens
@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return jsonify({"error": "Token has expired"}), 401

@jwt.invalid_token_loader
def invalid_token_callback(error):
    return jsonify({"error": "Invalid token"}), 401

@jwt.unauthorized_loader
def missing_token_callback(error):
    return jsonify({"error": "Authorization token is required"}), 401

# --- Models ---
class Tenant(db.Model):
    __tablename__ = 'tenants'
    id = db.Column(db.String(36), primary_key=True, default=lambda: os.urandom(16).hex())
    name = db.Column(db.String(100), nullable=False)
    revenue_tier = db.Column(db.String(20), default='smb')
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TrackingEvent(db.Model):
    __tablename__ = 'tracking_events'
    id = db.Column(db.String(36), primary_key=True, default=lambda: os.urandom(16).hex())
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False)
    customer_id = db.Column(db.String(100), nullable=False)
    channel = db.Column(db.String(50), nullable=False)
    value = db.Column(db.Float, default=1.0)
    is_conversion = db.Column(db.Boolean, default=False)
    conversion_value = db.Column(db.Float, default=0.0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- API Routes ---
@app.route('/api/v1/auth/register', methods=['POST'])
def register():
    data = request.json
    if not data or 'name' not in data or 'revenue_tier' not in data:
        return jsonify({"error": "Missing required fields: name, revenue_tier"}), 400

    # Create a new tenant with a random API key
    new_tenant = Tenant(
        name=data['name'],
        revenue_tier=data['revenue_tier'],
        api_key=os.urandom(32).hex() # Use a longer, more secure key
    )
    db.session.add(new_tenant)
    db.session.commit()

    # Generate a JWT access token for the new tenant
    access_token = create_access_token(identity=new_tenant.id)
    return jsonify({
        'tenant_id': new_tenant.id,
        'api_key': new_tenant.api_key,
        'access_token': access_token,
        'message': 'Account created! Use access_token for authentication.'
    }), 201

@app.route('/api/v1/auth/login', methods=['POST'])
def login():
    data = request.json
    if not data or 'tenant_id' not in data or 'api_key' not in data:
        return jsonify({"error": "Missing required fields: tenant_id, api_key"}), 400

    # Verify tenant exists and API key matches
    tenant = Tenant.query.filter_by(id=data['tenant_id'], api_key=data['api_key']).first()
    if not tenant:
        return jsonify({"error": "Invalid credentials"}), 401

    # Generate a new access token
    access_token = create_access_token(identity=tenant.id)
    return jsonify({
        'access_token': access_token,
        'tenant_id': tenant.id
    }), 200

@app.route('/api/v1/track', methods=['POST'])
def track_event_from_script():
    """
    Accepts tracking data from the client-side script using tenant_id and api_key.
    This is simpler for the client than using JWT.
    """
    data = request.json
    if not data or 'tenant_id' not in data or 'api_key' not in data:
        return jsonify({"error": "Missing tenant_id or api_key"}), 400

    # Verify tenant exists and API key matches
    tenant = Tenant.query.filter_by(id=data['tenant_id'], api_key=data['api_key']).first()
    if not tenant:
        return jsonify({"error": "Invalid credentials"}), 401

    # Validate required event fields
    if 'customer_id' not in data or 'channel' not in data:
        return jsonify({"error": "Missing required event fields: customer_id, channel"}), 400

    # Create and save the tracking event
    event = TrackingEvent(
        tenant_id=tenant.id,
        customer_id=data['customer_id'],
        channel=data['channel'],
        value=data.get('value', 1.0),
        is_conversion=data.get('is_conversion', False),
        conversion_value=data.get('conversion_value', 0.0)
    )
    db.session.add(event)
    db.session.commit()

    return jsonify({
        "status": "success",
        "message": "Event tracked",
        "event_id": event.id
    }), 201

@app.route('/api/v1/report/attribution', methods=['GET'])
@jwt_required()
def get_attribution_report():
    tenant_id = get_jwt_identity()
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return jsonify({"error": "Invalid tenant"}), 401

    days = request.args.get('days', 30, type=int)
    since_date = datetime.utcnow() - timedelta(days=days)

    # Get ALL events for the period
    all_events = TrackingEvent.query.filter(
        TrackingEvent.tenant_id == tenant_id,
        TrackingEvent.timestamp >= since_date
    ).all()

    # Separate them into page views and conversions
    page_views = [e for e in all_events if not e.is_conversion]
    conversions = [e for e in all_events if e.is_conversion]

    # Aggregate data by channel
    channel_stats = {}
    for event in all_events:
        channel = event.channel
        if channel not in channel_stats:
            channel_stats[channel] = {'page_views': 0, 'conversions': 0, 'value': 0}
        
        channel_stats[channel]['page_views'] += 1
        if event.is_conversion:
            channel_stats[channel]['conversions'] += 1
            channel_stats[channel]['value'] += event.conversion_value

    # Format response
    total_value = sum(c.conversion_value for c in conversions)
    report = {
        "period": f"last {days} days",
        "total_page_views": len(page_views),
        "total_conversions": len(conversions),
        "total_value": total_value,
        "channels": []
    }

    for channel, stats in channel_stats.items():
        report["channels"].append({
            "channel": channel,
            "page_views": stats['page_views'],
            "conversions": stats['conversions'],
            "value": stats['value'],
            "percentage": round((stats['value'] / total_value * 100) if total_value > 0 else 0, 2)
        })

    # Sort channels by total value for better display
    report["channels"].sort(key=lambda x: x['value'], reverse=True)

    return jsonify(report), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"}), 200

# --- Frontend & Static File Routes ---
@app.route('/tracker.js')
def serve_tracker():
    """Serves the tracking script to client websites."""
    return send_from_directory('static', 'tracker.js', mimetype='application/javascript')

@app.route('/dashboard')
def dashboard():
    """Serves the dashboard UI."""
    return send_file('dashboard.html')

# --- Temporary Debug Route (Remove in production) ---
@app.route('/debug/report', methods=['GET'])
def debug_report():
    """
    A temporary route to inspect raw tracking data for a tenant.
    Uses the access_token from a URL parameter for easy debugging.
    """
    token = request.args.get('access_token')
    if not token:
        return jsonify({"error": "Missing access_token in URL"}), 400

    try:
        # Decode the token to get the tenant_id
        decoded_token = decode_token(token)
        tenant_id = decoded_token['sub']
    except Exception:
        return jsonify({"error": "Invalid or expired access_token"}), 401

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return jsonify({"error": "Invalid tenant"}), 401

    days = request.args.get('days', 30, type=int)
    since_date = datetime.utcnow() - timedelta(days=days)

    all_events = TrackingEvent.query.filter(
        TrackingEvent.tenant_id == tenant_id,
        TrackingEvent.timestamp >= since_date
    ).all()

    # Return raw events for debugging
    return jsonify([{
        'id': event.id,
        'customer_id': event.customer_id,
        'channel': event.channel,
        'is_conversion': event.is_conversion,
        'conversion_value': event.conversion_value,
        'timestamp': event.timestamp.isoformat()
    } for event in all_events]), 200

# --- Database Initialization ---
# This block ensures that tables are created when the app starts.
with app.app_context():
    print("✨ Creating database tables if they do not exist...")
    db.create_all()
    print("✅ Database tables are ready.")

if __name__ == '__main__':
    # Run the app in debug mode for local development
    app.run(debug=True)