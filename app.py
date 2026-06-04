import os
import random
import io
import base64
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
import qrcode

app = Flask(__name__)
# Render ke environment variable se key uthayega, nahi toh fallback default use karega
app.secret_key = os.environ.get('SECRET_KEY', 'quickq_multi_tenant_websocket_key_2026')

# 🗄️ Database Setup (Render Production Secure Absolute Path Fix)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'queue.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 🔌 WebSockets Engine Base Configuration
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# 📋 Database Model Architecture
class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15), nullable=False)
    age = db.Column(db.Integer, nullable=False, default=25)
    is_emergency = db.Column(db.Boolean, default=False)
    location = db.Column(db.String(100), nullable=False)                   # 'bank', 'hospital', 'govt'
    service = db.Column(db.String(100), nullable=False)
    booking_date = db.Column(db.String(50), nullable=False)
    time_slot = db.Column(db.String(50), nullable=False)
    token = db.Column(db.String(10), unique=True, nullable=False)
    status = db.Column(db.String(20), default="Waiting")                   # Waiting, Serving, Completed, Cancelled
    counter_assigned = db.Column(db.String(20), nullable=True)
    rating = db.Column(db.Integer, nullable=True)
    review = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    served_at = db.Column(db.DateTime, nullable=True)

# 🌍 Department Configuration Matrices
DEPARTMENTS = {
    'bank': {
        'title': 'Quick-Q National Bank',
        'prefix': 'B',
        'services': ['Cash Counter', 'Account Management', 'Loan Desk', 'Cheque Clearance'],
        'icon': 'fa-building-columns',
        'color': 'primary'
    },
    'hospital': {
        'title': 'Quick-Q Lifecare Hospital',
        'prefix': 'H',
        'services': ['OPD Doctor Consultation', 'Blood Test Lab', 'Emergency Trauma', 'Pharmacy Store'],
        'icon': 'fa-hospital-user',
        'color': 'danger'
    },
    'govt': {
        'title': 'Quick-Q Citizen Seva Kendra',
        'prefix': 'G',
        'services': ['Aadhaar Services', 'Passport Verification', 'Tax & Revenue Desk', 'Certificates Counter'],
        'icon': 'fa-id-card',
        'color': 'success'
    }
}

# 🏠 1. Multi-Tenant Central Hub Route
@app.route('/')
def home():
    try:
        stats = {}
        total_platform_footfall = 0
        for sector in DEPARTMENTS.keys():
            total = Booking.query.filter_by(location=sector).count()
            waiting = Booking.query.filter_by(location=sector, status="Waiting").count()
            serving = Booking.query.filter_by(location=sector, status="Serving").count()
            total_platform_footfall += total
            stats[sector] = {'total': total, 'waiting': waiting, 'serving': serving}
        return render_template('index.html', departments=DEPARTMENTS, stats=stats, overall_footfall=total_platform_footfall)
    except Exception as e:
        return f"Database Hub Error: {str(e)}", 500

# 🎫 2. Token Booking Terminal Route
@app.route('/<sector>/book', methods=['GET', 'POST'])
def book(sector):
    if sector not in DEPARTMENTS: 
        abort(404)
    config = DEPARTMENTS[sector]
    if request.method == 'POST':
        otp_status = request.form.get('backend_otp_verify', 'unverified')
        if otp_status != "verified": 
            return "Security Alert: Verification failed!", 403

        name = request.form['name']
        phone = request.form['phone']
        age = int(request.form['age'])
        service = request.form['service']
        booking_date = request.form['booking_date']
        time_slot = request.form['time_slot']
        is_emergency = 'is_emergency' in request.form

        prefix = "EMERG" if (is_emergency and sector == 'hospital') else config['prefix']
        
        while True:
            token = f"{prefix}{random.randint(10, 99)}"
            exists = Booking.query.filter_by(token=token, location=sector).first()
            if not exists: 
                break
                
        new_booking = Booking(
            name=name, phone=phone, age=age, is_emergency=is_emergency,
            location=sector, service=service, booking_date=booking_date, 
            time_slot=time_slot, token=token
        )
        db.session.add(new_booking)
        db.session.commit()

        socketio.emit('queue_updated', {'sector': sector})
        return redirect(url_for('status', sector=sector, token=token))
        
    return render_template('booking.html', sector=sector, config=config)

# 🎯 3. Live Token Status Tracker
@app.route('/<sector>/status/<token>')
def status(sector, token):
    if sector not in DEPARTMENTS: 
        abort(404)

    booking = Booking.query.filter_by(token=token, location=sector).first()
    if not booking: 
        return "Token error!", 404

    # Algorithmic Position Verification
    if booking.status == "Cancelled":
        position_str, wait_time = "Cancelled", 0
    elif booking.status == "Serving":
        position_str, wait_time = f"Serving at {booking.counter_assigned}", 0
    elif booking.status == "Completed":
        position_str, wait_time = "Completed", 0
    else:
        all_waiting = Booking.query.filter_by(status="Waiting", location=sector).all()
        all_waiting.sort(key=lambda x: (not x.is_emergency, not (x.age >= 60), x.id))
        pos_num = all_waiting.index(booking) + 1 if booking in all_waiting else 0
        position_str = f"#{pos_num}"

        past_completed = Booking.query.filter_by(status="Completed", service=booking.service, location=sector).all()
        total_handling_time = sum([(b.served_at - b.created_at).total_seconds() / 60 for b in past_completed if b.served_at])
        avg_handling_time = total_handling_time / len(past_completed) if past_completed else (12 if sector == 'hospital' else 5)
        wait_time = 0 if booking.is_emergency else round((pos_num - 1) * avg_handling_time)
        if wait_time < 1 and not booking.is_emergency: 
            wait_time = 2

    # 📡 Base64 QR Generator Node
    live_track_url = request.url_root + f"{sector}/status/{token}"
    qr = qrcode.QRCode(version=1, box_size=10, border=1)
    qr.add_data(live_track_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

    return render_template('status.html', 
                           booking=booking, 
                           position=str(position_str), 
                           wait_time=str(wait_time), 
                           sector=sector, 
                           qr_data=qr_base64)

# 📺 4. Real-Time TV Display System Node
@app.route('/<sector>/tv-display')
def tv_display(sector):
    if sector not in DEPARTMENTS: 
        abort(404)
    serving_now = Booking.query.filter_by(status="Serving", location
