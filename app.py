# app.py
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity, create_access_token
import os
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET', 'super-secret-key-for-testing')
jwt = JWTManager(app)
# Configuration
if os.environ.get('RENDER'):
    database_url = os.getenv('DATABASE_URL', '')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    if not database_url:
        database_url = 'sqlite:///local.db'
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///development.db'
    print("⚠️ Using SQLite for local development (PostgreSQL will be used in production)")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET', 'super-secret-key-for-testing')

# Initialize extensions

db = SQLAlchemy(app)
jwt = JWTManager(app)

# Models
class Tenant(db.Model):
    __tablename__ = 'tenants'
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    revenue_tier = db.Column(db.String(20), default='smb')
    api_key = db.Column(db.String(64), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Routes
@app.route('/api/v1/auth/register', methods=['POST'])
def register():
    data = request.json
    if not data or 'name' not in data or 'revenue_tier' not in data:
        return jsonify({"error": "Missing required fields"}), 400
    
    # Create tenant
    new_tenant = Tenant(
        id=os.urandom(16).hex(),
        name=data['name'],
        revenue_tier=data['revenue_tier'],
        api_key=os.urandom(24).hex()  # Keep API key for future use
    )
    
    db.session.add(new_tenant)
    db.session.commit()
    
    # CRITICAL FIX: Generate proper JWT token
    access_token = create_access_token(identity=new_tenant.id)
    
    return jsonify({
        'tenant_id': new_tenant.id,
        'api_key': new_tenant.api_key,
        'access_token': access_token,  # This is what you should use for auth
        'message': 'Account created! Use access_token for authentication'
    }), 201
@app.route('/api/v1/auth/login', methods=['POST'])
def login():
    data = request.json
    if not data or 'tenant_id' not in data or 'api_key' not in data:
        return jsonify({"error": "Missing required fields"}), 400
    
    # Verify tenant exists and API key matches
    tenant = Tenant.query.filter_by(id=data['tenant_id'], api_key=data['api_key']).first()
    if not tenant:
        return jsonify({"error": "Invalid credentials"}), 401
    
    # Generate access token
    access_token = create_access_token(identity=tenant.id)
    
    return jsonify({
        'access_token': access_token,
        'tenant_id': tenant.id
    }), 200
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"}), 200
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

# Add this route for the tracking script to use
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

    # The customer_id, channel, etc., should be in the request body
    if 'customer_id' not in data or 'channel' not in data:
        return jsonify({"error": "Missing required event fields (customer_id, channel)"}), 400

    # Create tracking event
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

# Keep the existing JWT-protected one for potential future use (e.g., server-to-server)
# But rename it to avoid confusion
@app.route('/api/v1/track_authenticated', methods=['POST'])
@jwt_required()
def track_event_authenticated():
    # ... (keep the existing code for this one) ...
    # This is the code you had before, just renamed.
    current_user = get_jwt_identity()
    tenant_id = current_user
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return jsonify({"error": "Invalid tenant"}), 401
    data = request.json
    if not data or 'customer_id' not in data or 'channel' not in data:
        return jsonify({"error": "Missing required fields"}), 400
    event = TrackingEvent(
        tenant_id=tenant_id,
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

# Add this route for reports
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
    report = {
        "period": f"last {days} days",
        "total_page_views": len(page_views),
        "total_conversions": len(conversions),
        "total_value": sum(c.conversion_value for c in conversions),
        "channels": []
    }

    for channel, stats in channel_stats.items():
        report["channels"].append({
            "channel": channel,
            "page_views": stats['page_views'],
            "conversions": stats['conversions'],
            "value": stats['value'],
            "percentage": round((stats['value'] / report["total_value"] * 100) if report["total_value"] > 0 else 0, 2)
        })

    # Sort channels by total value for better display
    report["channels"].sort(key=lambda x: x['value'], reverse=True)

    return jsonify(report), 200
@app.route('/tracker.js')
def serve_tracker():
    """Serve the tracking script to client websites"""
    return send_from_directory('static', 'tracker.js', mimetype='application/javascript')

@app.route('/dashboard')
def dashboard():
    """Serve the dashboard UI"""
    return send_file('dashboard.html')

######temp debug route

@app.route('/debug/report', methods=['GET'])
@jwt_required()
def debug_report():
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

    # Return raw events for debugging
    return jsonify([{
        'id': event.id,
        'tenant_id': event.tenant_id,
        'customer_id': event.customer_id,
        'channel': event.channel,
        'value': event.value,
        'is_conversion': event.is_conversion,
        'conversion_value': event.conversion_value,
        'timestamp': event.timestamp
    } for event in all_events]), 200
if __name__ == '__main__':
    with app.app_context():
        print("✨ Creating database tables...")
        db.create_all()
        print("✅ Database tables created successfully")
        app.run(debug=True)
else:
    # This runs when deployed to Render (not via python app.py)
    with app.app_context():
        print("✨ Creating database tables for production...")
        db.create_all()
        print("✅ Database tables created successfully")