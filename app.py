# app.py
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity, create_access_token
import os
from datetime import datetime, timedelta

app = Flask(__name__)
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

# Add this route for tracking
@app.route('/api/v1/track', methods=['POST'])
@jwt_required()
def track_event():
    current_user = get_jwt_identity()
    tenant_id = current_user  # In our simplified model, JWT identity is tenant_id
    
    # Verify tenant exists
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return jsonify({"error": "Invalid tenant"}), 401
    
    data = request.json
    if not data or 'customer_id' not in data or 'channel' not in data:
        return jsonify({"error": "Missing required fields"}), 400
    
    # Create tracking event
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
    
    # Verify tenant exists
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return jsonify({"error": "Invalid tenant"}), 401
    
    days = request.args.get('days', 30, type=int)
    
    # Get conversion events
    conversions = TrackingEvent.query.filter(
        TrackingEvent.tenant_id == tenant_id,
        TrackingEvent.is_conversion == True,
        TrackingEvent.timestamp >= datetime.utcnow() - timedelta(days=days)
    ).all()
    
    # Simple attribution calculation
    channel_counts = {}
    channel_values = {}
    
    for conv in conversions:
        channel = conv.channel
        channel_counts[channel] = channel_counts.get(channel, 0) + 1
        channel_values[channel] = channel_values.get(channel, 0) + conv.conversion_value
    
    # Format response
    report = {
        "period": f"last {days} days",
        "total_conversions": len(conversions),
        "total_value": sum(channel_values.values()),
        "channels": []
    }
    
    for channel, count in channel_counts.items():
        report["channels"].append({
            "channel": channel,
            "conversions": count,
            "value": channel_values.get(channel, 0),
            "percentage": round((channel_values.get(channel, 0) / report["total_value"] * 100) if report["total_value"] > 0 else 0, 2)
        })
    
    return jsonify(report), 200
@app.route('/tracker.js')
def serve_tracker():
    """Serve the tracking script to client websites"""
    return send_from_directory('static', 'tracker.js', mimetype='application/javascript')

@app.route('/dashboard')
def dashboard():
    """Serve the dashboard UI"""
    return send_file('dashboard.html')
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