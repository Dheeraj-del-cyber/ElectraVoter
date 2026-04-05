from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import random, time, os, re, requests, uuid, hashlib
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from pymongo import MongoClient

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super-secret-key")

def generate_hash(data):
    return hashlib.sha256(data.encode()).hexdigest()

# ---- MONGODB SETUP ----
# If no URI is provided in .env, default to a local MongoDB instance
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client['electravoter_db']
cdb = db['candidates']
vdb = db['votes']
sdb = db['settings']

def get_settings():
    settings = sdb.find_one({"id": "global_settings"})
    if not settings:
        settings = {
            "id": "global_settings",
            "voting_start_time": None,
            "voting_end_time": None
        }
        sdb.insert_one(settings)
    return settings

def check_voting_status():
    settings = get_settings()
    current_time = time.time()
    
    start_time = settings.get('voting_start_time')
    end_time = settings.get('voting_end_time')
    
    # If no times are set at all
    if start_time is None and end_time is None:
        return "active", "Voting is currently open (No schedule set)", None
        
    # Check Start Time if set
    if start_time is not None and current_time < start_time:
        return "not_started", f"Voting has not started yet. Starts at {time.strftime('%Y-%m-%d %H:%M', time.localtime(start_time))}", start_time
    
    # Check End Time if set
    if end_time is not None and current_time > end_time:
        return "ended", f"Voting has ended. Finished at {time.strftime('%Y-%m-%d %H:%M', time.localtime(end_time))}", end_time
        
    # If we are between start and end, or only one is set and we are within it
    if end_time is not None:
        return "active", f"Voting ends at {time.strftime('%Y-%m-%d %H:%M', time.localtime(end_time))}", end_time
    
    return "active", "Voting is currently open", None

# Initial Seed Data (if DB is empty)
def seed_candidates():
    if cdb.count_documents({}) == 0:
        initial_data = [
            {"id": "p001", "name": "Aditya Sharma", "category": "president", "image": "https://api.dicebear.com/7.x/avataaars/svg?seed=Aditya"},
            {"id": "p002", "name": "Priya Patel", "category": "president", "image": "https://api.dicebear.com/7.x/avataaars/svg?seed=Priya"},
            {"id": "v001", "name": "Vikram Singh", "category": "vice_president", "image": "https://api.dicebear.com/7.x/avataaars/svg?seed=Vikram"},
            {"id": "v002", "name": "Neha Gupta", "category": "vice_president", "image": "https://api.dicebear.com/7.x/avataaars/svg?seed=Neha"}
        ]
        cdb.insert_many(initial_data)

seed_candidates()

# ---- UPLOAD CONFIGURATION ----
UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Transitory OTP Storage (Can be moved to DB later if needed)
otp_store = {}


@app.route('/send_otp', methods=['POST'])
def send_otp():
    data = request.get_json()
    name = data.get('name')
    usn = data.get('usn')
    phone = data.get('phone')
    
    # Generate user_hash for SECURE Identity
    user_hash = generate_hash(f"{usn}{phone}")
    
    # 🛡️ SECURITY CHECK: Voting time
    status, message, target_ts = check_voting_status()
    if status != "active":
        return jsonify({"success": False, "message": message}), 403

    # 🛡️ SECURITY CHECK: Has this phone or USN already voted?
    if vdb.find_one({"$or": [{"phone": phone}, {"usn": usn}, {"user_hash": user_hash}]}):
        return jsonify({"success": False, "message": "You have already voted"}), 403
        
    otp = "123456" # Presentation Mode OTP
    otp_store[phone] = {"otp": otp, "expires": time.time() + 120, "name": name, "usn": usn}
    
    return jsonify({"success": True, "message": "OTP (123456) sent to your device."})

@app.route('/verify-page')
def verify_page():
    phone = request.args.get('phone', '')
    return render_template('verify.html', phone=phone)

@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    data = request.get_json()
    phone = data.get('phone')
    otp_input = data.get('otp')
    
    if not phone or otp_input != "123456":
        return jsonify({"success": False, "message": "Invalid OTP"}), 401
        
    session['authenticated'] = True
    session['user_name'] = otp_store[phone]['name']
    session['usn'] = otp_store[phone]['usn']
    session['phone'] = phone
    session['has_voted'] = vdb.find_one({"usn": session['usn']}) is not None
    
    return jsonify({"success": True})

@app.route('/')
def index():
    if session.get('authenticated'):
        return redirect(url_for('dashboard'))
    
    status, status_message, target_ts = check_voting_status()
    return render_template('index.html', 
                          voting_status=status, 
                          status_message=status_message,
                          target_ts=target_ts,
                          time=time)

@app.route('/dashboard')
def dashboard():
    if not session.get('authenticated'):
        return redirect(url_for('index'))
    
    # Check current status
    user_voted = vdb.find_one({"usn": session['usn']}) is not None
    
    # Fetch all candidates and group them by category
    candidates_list = list(cdb.find({}, {"_id": 0}))
    grouped_candidates = {}
    for c in candidates_list:
        cat = c['category']
        if cat not in grouped_candidates:
            grouped_candidates[cat] = []
        grouped_candidates[cat].append(c)
    
    # Get voting status
    status, status_message, target_ts = check_voting_status()
    
    return render_template('dashboard.html', 
                          name=session.get('user_name'), 
                          candidates=grouped_candidates, 
                          has_voted=user_voted,
                          voting_status=status,
                          status_message=status_message,
                          target_ts=target_ts,
                          time=time)

@app.route('/submit-vote', methods=['POST'])
def submit_vote():
    if not session.get('authenticated'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    user_hash = generate_hash(f"{session.get('usn')}{session.get('phone')}")
    
    # 🛡️ FINAL DOUBLE CHECK: Voting time
    status, message, target_ts = check_voting_status()
    if status != "active":
        return jsonify({"success": False, "message": message}), 403

    # 🛡️ FINAL DOUBLE CHECK:
    if vdb.find_one({"$or": [{"usn": session['usn']}, {"phone": session['phone']}, {"user_hash": user_hash}]}):
        return jsonify({"success": False, "message": "You have already voted"}), 403

    data = request.get_json()
    voting_id = f"EV-{uuid.uuid4().hex[:12].upper()}"
    
    timestamp = time.time()
    
    # Generate Secure Hash for Vote Storage
    votes_dict = data.get('votes', {})
    # Using candidate_id + position + timestamp format
    vote_data_string = "".join([f"{cid}{cat}" for cat, cid in sorted(votes_dict.items())]) + str(timestamp)
    
    # Optional Advanced Feature: Blockchain-like chain
    last_vote = vdb.find_one(sort=[("timestamp", -1)])
    previous_hash = last_vote.get("vote_hash", "0" * 64) if last_vote else "0" * 64
    
    vote_hash = generate_hash(vote_data_string + previous_hash)
    
    vote_entry = {
        "voting_id": voting_id,
        "user_name": session.get('user_name'),
        "usn": session.get('usn'),
        "phone": session.get('phone'),
        "votes": votes_dict, # Dynamic dictionary of category: selection
        "timestamp": timestamp,
        "user_hash": user_hash,
        "vote_hash": vote_hash,
        "previous_hash": previous_hash
    }
    
    vdb.insert_one(vote_entry)
    session['has_voted'] = True
    
    return jsonify({
        "success": True, 
        "receipt": {"voting_id": voting_id, "name": session.get('user_name'), "usn": session.get('usn')}
    })

# ---- ADMIN SECTION ----
@app.route('/admin')
def admin_page():
    return render_template('admin_login.html')

@app.route('/admin-login', methods=['POST'])
def admin_login():
    data = request.get_json()
    if data.get('password') == "election":
        session['admin_authenticated'] = True
        session['admin_name'] = data.get('name')
        session['admin_designation'] = data.get('designation')
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Unauthorized"}), 401

@app.route('/admin-dashboard')
def admin_dashboard():
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_page'))
    
    # Candidates list (exclude ObjectId)
    candidates_list = list(cdb.find({}, {"_id": 0}))
    grouped_candidates = {}
    for c in candidates_list:
        cat = c['category']
        if cat not in grouped_candidates:
            grouped_candidates[cat] = []
        grouped_candidates[cat].append(c)
    
    # Result Aggregation for ALL categories
    results = {cat: {c['id']: 0 for c in grouped_candidates[cat]} for cat in grouped_candidates}
        
    for vote in vdb.find():
        user_votes = vote.get('votes', {})
        # Fallback for old votes (pre-migration)
        if not user_votes:
            user_votes = {}
            if vote.get('president'): user_votes['president'] = vote.get('president')
            if vote.get('vice_president'): user_votes['vice_president'] = vote.get('vice_president')

        for cat, cid in user_votes.items():
            if cat in results and cid in results[cat]:
                results[cat][cid] += 1

    return render_template('admin_dashboard.html', 
                          name=session.get('admin_name'), 
                          designation=session.get('admin_designation'),
                          candidates=grouped_candidates,
                          results=results,
                          total_votes=vdb.count_documents({}),
                          settings=get_settings(),
                          time=time)

@app.route('/update-settings', methods=['POST'])
def update_settings():
    if not session.get('admin_authenticated'): return jsonify({"success": False}), 401
    
    data = request.get_json()
    start_time_str = data.get('start_time')
    end_time_str = data.get('end_time')
    
    try:
        def parse_dt(dt_str):
            if not dt_str: return None
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
                try:
                    return time.mktime(time.strptime(dt_str, fmt))
                except ValueError:
                    continue
            raise ValueError(f"Invalid format: {dt_str}")

        start_ts = parse_dt(start_time_str)
        end_ts = parse_dt(end_time_str)
        
        sdb.update_one({"id": "global_settings"}, {"$set": {
            "voting_start_time": start_ts,
            "voting_end_time": end_ts
        }})
        return jsonify({"success": True})
    except Exception as e:
        print(f"Update settings error: {e}")
        return jsonify({"success": False, "message": str(e)}), 400

@app.route('/add-candidate', methods=['POST'])
def add_candidate():
    if not session.get('admin_authenticated'): return jsonify({"success": False}), 401
    
    name = request.form.get('name')
    category = request.form.get('category')
    file = request.files.get('image')
    
    image_url = f"https://api.dicebear.com/7.x/avataaars/svg?seed={name}"
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{name}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        image_url = f"/static/uploads/{filename}"

    cdb.insert_one({"id": uuid.uuid4().hex[:8], "name": name, "category": category, "image": image_url})
    return jsonify({"success": True})

@app.route('/edit-candidate', methods=['POST'])
def edit_candidate():
    if not session.get('admin_authenticated'): return jsonify({"success": False}), 401
    
    cid = request.form.get('id')
    new_name = request.form.get('name')
    file = request.files.get('image')
    
    update_data = {"name": new_name}
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{new_name}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        update_data["image"] = f"/static/uploads/{filename}"
    
    cdb.update_one({"id": cid}, {"$set": update_data})
    return jsonify({"success": True})

@app.route('/delete-candidate/<category>/<cid>', methods=['POST'])
def delete_candidate(category, cid):
    if not session.get('admin_authenticated'): return jsonify({"success": False}), 401
    cdb.delete_one({"id": cid})
    return jsonify({"success": True})

@app.route('/verify-vote-status', methods=['POST'])
def verify_vote_status():
    data = request.get_json()
    vid = data.get('voting_id', '').strip().upper()
    if not vid: return jsonify({"success": False, "message": "ID required"}), 400
    
    vote = vdb.find_one({"voting_id": vid}, {"_id": 0, "timestamp": 1, "usn": 1})
    if vote:
        return jsonify({
            "success": True, 
            "status": "Counted", 
            "timestamp": time.strftime('%Y-%m-%d %H:%M', time.localtime(vote['timestamp'])),
            "usn": f"***{vote['usn'][-4:]}" # Partially masked for privacy
        })
    return jsonify({"success": False, "status": "Not Found"})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
