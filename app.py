import os
import random
import io
import base64
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
import qrcode  # Offline QR Code Generation Matrix

app = Flask(__name__)
app.secret_key = 'quickq_multi_tenant_websocket_key_2026'

# 🗄️ Database Setup (SQLite Engine)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///queue.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 🔌 Initialize WebSockets Engine for Live TV Sync
socketio = SocketIO(app, cors_allowed_origins="*")

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
    stats = {}
    total_platform_footfall = 0
    for sector in DEPARTMENTS.keys():
        total = Booking.query.filter_by(location=sector).count()
        waiting = Booking.query.filter_by(location=sector, status="Waiting").count()
        serving = Booking.query.filter_by(location=sector, status="Serving").count()
        total_platform_footfall += total
        stats[sector] = {'total': total, 'waiting': waiting, 'serving': serving}
    return render_template('index.html', departments=DEPARTMENTS, stats=stats, overall_footfall=total_platform_footfall)

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

# 🎯 3. Live Token Status Tracker (Fixed High Contrast Layout + Jinja2 Safe String Conversion)
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

    # 📡 Pure Offline Base64 QR Generator Engine
    live_track_url = request.url_root + f"{sector}/status/{token}"
    qr = qrcode.QRCode(version=1, box_size=10, border=1)
    qr.add_data(live_track_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

    # 🌟 FIXED FOR JINJA: Explicit string casting ensures template stability
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
    serving_now = Booking.query.filter_by(status="Serving", location=sector).order_by(db.desc(Booking.served_at)).limit(4).all()
    top_waiting = Booking.query.filter_by(status="Waiting", location=sector).all()
    top_waiting.sort(key=lambda x: (not x.is_emergency, not (x.age >= 60), x.id))
    return render_template('tv_display.html', serving=serving_now, waiting=top_waiting[:5], config=DEPARTMENTS[sector], sector=sector)

# 🔐 5. Staff Console Secure Login (Bypassed for instant operational efficiency)
@app.route('/<sector>/admin/login', methods=['GET', 'POST'])
def admin_login(sector):
    if sector not in DEPARTMENTS: 
        abort(404)
    if request.method == 'POST':
        session[f'staff_logged_{sector}'] = True
        session[f'staff_counter_{sector}'] = request.form['counter']
        return redirect(url_for('admin', sector=sector))
    return render_template('admin_login.html', sector=sector, config=DEPARTMENTS[sector])

# 🛠️ 6. Staff Operator Control Terminal
@app.route('/<sector>/admin')
def admin(sector):
    if not session.get(f'staff_logged_{sector}'): 
        return redirect(url_for('admin_login', sector=sector))
    my_counter = session.get(f'staff_counter_{sector}', 'Counter 01')
    current_serving = Booking.query.filter_by(status="Serving", counter_assigned=my_counter, location=sector).first()
    waiting_list = Booking.query.filter_by(status="Waiting", location=sector).all()
    waiting_list.sort(key=lambda x: (not x.is_emergency, not (x.age >= 60), x.id))
    active_emergency = Booking.query.filter_by(status="Waiting", is_emergency=True, location=sector).first()
    return render_template('admin.html', current_serving=current_serving, waiting_list=waiting_list, counter=my_counter, active_emergency=active_emergency, sector=sector, config=DEPARTMENTS[sector])

# 📢 7. Route to Dispatch & Signal Next Waiting Customer Ticket
@app.route('/<sector>/admin/next')
def serve_next(sector):
    if not session.get(f'staff_logged_{sector}'): 
        return redirect(url_for('admin_login', sector=sector))
    my_counter = session.get(f'staff_counter_{sector}', 'Counter 01')
    current = Booking.query.filter_by(status="Serving", counter_assigned=my_counter, location=sector).first()
    if current: 
        current.status = "Completed"
    
    waiting_list = Booking.query.filter_by(status="Waiting", location=sector).all()
    waiting_list.sort(key=lambda x: (not x.is_emergency, not (x.age >= 60), x.id))
    
    announced_token = ""
    if waiting_list:
        next_person = waiting_list[0]
        next_person.status = "Serving"
        next_person.counter_assigned = my_counter
        next_person.served_at = datetime.utcnow()
        announced_token = next_person.token
        
    db.session.commit()
    socketio.emit('update_and_call', {'sector': sector, 'token': announced_token, 'counter': my_counter})
    return redirect(url_for('admin', sector=sector))

# ❌ 8. Ticket Cancellation Node Pipeline
@app.route('/<sector>/cancel/<token>', methods=['POST'])
def cancel_ticket(sector, token):
    booking = Booking.query.filter_by(token=token, location=sector).first()
    if booking:
        booking.status = "Cancelled"
        db.session.commit()
        socketio.emit('queue_updated', {'sector': sector})
    return redirect(url_for('status', sector=sector, token=token))

# 📊 9. Deep Operational Intelligence Analytics (Chart.js Metric Maps API)
@app.route('/<sector>/analytics')
def analytics(sector):
    if sector not in DEPARTMENTS: 
        abort(404)
    
    all_bookings = Booking.query.filter_by(location=sector).all()
    completed = Booking.query.filter_by(status="Completed", location=sector).all()
    
    total_wait = sum([(b.served_at - b.created_at).total_seconds() / 60 for b in completed if b.served_at])
    avg_wait = round(total_wait / len(completed), 1) if completed else 0

    # Metric Dataset mapping for ChartJS Engine 
    service_labels = DEPARTMENTS[sector]['services']
    service_counts = [Booking.query.filter_by(location=sector, service=s).count() for s in service_labels]

    slots_labels = ['09:00 AM', '11:00 AM', '02:00 PM', '04:00 PM']
    slots_counts = [Booking.query.filter_by(location=sector, time_slot=s).count() for s in slots_labels]

    return render_template('analytics.html', 
                           total=len(all_bookings), served=len(completed), 
                           waiting=Booking.query.filter_by(status="Waiting", location=sector).count(), 
                           avg_wait=avg_wait, service_labels=service_labels, 
                           service_counts=service_counts, slots_labels=slots_labels, 
                           slots_counts=slots_counts, sector=sector, config=DEPARTMENTS[sector])

# DB Init Context Trigger Block
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    # 🌟 Production Dynamic Port Detection Engine for Render/Cloud Platforms
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)