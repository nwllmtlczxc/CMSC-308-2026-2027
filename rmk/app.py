

import os

from xhtml2pdf import pisa
from io import BytesIO
from flask import make_response
from datetime import time, datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = 'cmsc308-group3-secret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'timetable.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
TIME_SLOTS = [
    (time(7, 0), time(8, 0)), (time(8, 0), time(9, 0)), (time(9, 0), time(10, 0)),
    (time(10, 0), time(11, 0)), (time(11, 0), time(12, 0)), (time(12, 0), time(13, 0)),
    (time(13, 0), time(14, 0)), (time(14, 0), time(15, 0)), (time(15, 0), time(16, 0)),
    (time(16, 0), time(17, 0)),
]

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='Instructor') 

class Term(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    schedules = db.relationship('Schedule', backref='term', lazy=True)

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    title = db.Column(db.String(120), nullable=False)
    units = db.Column(db.Integer, default=3)
    room_type = db.Column(db.String(20), default='lecture')
    schedules = db.relationship('Schedule', backref='course', lazy=True)

class Faculty(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(80))
    schedules = db.relationship('Schedule', backref='faculty', lazy=True)
    availabilities = db.relationship('Availability', backref='faculty', lazy=True)

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    capacity = db.Column(db.Integer, default=30)
    room_type = db.Column(db.String(20), default='lecture')
    schedules = db.relationship('Schedule', backref='room', lazy=True)
    availabilities = db.relationship('Availability', backref='room', lazy=True)

class Section(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    program = db.Column(db.String(50))
    size = db.Column(db.Integer, default=30)
    schedules = db.relationship('Schedule', backref='section', lazy=True)

class Availability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'), nullable=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=True)
    day = db.Column(db.String(3), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    term_id = db.Column(db.Integer, db.ForeignKey('term.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'), nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey('section.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=True)
    day = db.Column(db.String(3), nullable=True)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)

    @property
    def is_pending(self):
        return self.room_id is None or self.day is None

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class ConflictError(Exception): pass

def overlaps(s1, e1, s2, e2):
    return s1 < e2 and e1 > s2

def check_schedule_conflicts(new, existing_schedules, exclude_id=None):
    conflicts = []
    if new.get('day') is None or new.get('start_time') is None or new.get('end_time') is None:
        return conflicts

    for s in existing_schedules:
        if s.id == exclude_id: continue
        if s.day is None or s.start_time is None or s.end_time is None: continue
        if s.day != new['day']: continue
        if not overlaps(new['start_time'], new['end_time'], s.start_time, s.end_time): continue
        
        if new.get('faculty_id') and s.faculty_id == new['faculty_id']:
            conflicts.append(f"Faculty conflict: {s.faculty.name} already teaching {s.course.code} at {s.start_time.strftime('%H:%M')}")
        if new.get('room_id') and s.room_id == new['room_id']:
            conflicts.append(f"Room conflict: {s.room.code} already booked for {s.course.code} at {s.start_time.strftime('%H:%M')}")
        if new.get('section_id') and s.section_id == new['section_id']:
            conflicts.append(f"Section conflict: {s.section.name} already has {s.course.code} at {s.start_time.strftime('%H:%M')}")

    for avail in Availability.query.filter_by(day=new['day']).all():
        if not overlaps(new['start_time'], new['end_time'], avail.start_time, avail.end_time): continue
        if avail.faculty_id and avail.faculty_id == new.get('faculty_id'):
            conflicts.append(f"Faculty {avail.faculty.name} is unavailable at this time")
        if avail.room_id and avail.room_id == new.get('room_id'):
            conflicts.append(f"Room {avail.room.code} is unavailable at this time")
    return conflicts

def check_room_suitability(room, section, course):
    problems = []
    if room.capacity < section.size:
        problems.append(f"Room {room.code} capacity ({room.capacity}) is smaller than section {section.name} ({section.size})")
    if course.room_type == 'lab' and room.room_type != 'lab':
        problems.append(f"Course {course.code} requires a lab, but {room.code} is a {room.room_type} room")
    return problems

def auto_generate(term_id):
    pending = Schedule.query.filter_by(term_id=term_id, room_id=None).all()
    pending.sort(key=lambda s: (0 if s.course.room_type == 'lab' else 1, -s.section.size))
    assigned_count, still_unassigned = 0, []

    for sched in pending:
        placed = False
        for day in DAYS:
            for start, end in TIME_SLOTS:
                for room in Room.query.all():
                    if check_room_suitability(room, sched.section, sched.course): continue
                    candidate = {'day': day, 'start_time': start, 'end_time': end, 'room_id': room.id, 'faculty_id': sched.faculty_id, 'section_id': sched.section_id, 'course_id': sched.course_id}
                    existing = Schedule.query.filter(Schedule.term_id == term_id, Schedule.room_id.isnot(None)).all()
                    if not check_schedule_conflicts(candidate, existing, exclude_id=sched.id):
                        sched.day, sched.start_time, sched.end_time, sched.room_id = day, start, end, room.id
                        db.session.commit()
                        assigned_count += 1
                        placed = True
                        break
                if placed: break
            if placed: break
        if not placed: still_unassigned.append(sched)
    return assigned_count, still_unassigned

def parse_time(value):
    if not value: return None
    try: return datetime.strptime(value, '%H:%M').time()
    except ValueError: return None

def build_timetable(schedules):
    grid = {}
    for s in schedules:
        if s.day and s.start_time: grid[(s.day, s.start_time.strftime('%H:%M'))] = s
    return grid

# ============================================================
# AUTH ROUTES
# ============================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password_hash, request.form.get('password')):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
        else:
            db.session.add(User(username=username, password_hash=generate_password_hash(request.form.get('password'))))
            db.session.commit()
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# MAIN ROUTES
@app.route('/')
@login_required
def index():
    sections = Section.query.all()
    
    # Get the selected section from the URL (default to the first one)
    section_id = request.args.get('section_id', type=int)
    if not section_id and sections:
        section_id = sections[0].id

    # Only fetch schedules for the selected section
    if section_id:
        all_scheds = Schedule.query.filter(
            Schedule.room_id.isnot(None),
            Schedule.section_id == section_id
        ).all()
    else:
        all_scheds = []

    grid = build_timetable(all_scheds)
    selected_section = db.session.get(Section, section_id) if section_id else None

    stats = {
        'courses': Course.query.count(), 
        'faculty': Faculty.query.count(), 
        'rooms': Room.query.count(), 
        'sections': Section.query.count(), 
        'schedules': len(all_scheds), 
        'pending': Schedule.query.filter(Schedule.room_id.is_(None), Schedule.section_id == section_id).count() if section_id else 0
    }
    
    return render_template('index.html', stats=stats, grid=grid, days=DAYS, time_slots=TIME_SLOTS, sections=sections, selected_section=selected_section)

@app.route('/academic')
@login_required
def academic():
    return render_template('academic.html', courses=Course.query.order_by(Course.code).all(), faculty=Faculty.query.order_by(Faculty.name).all(), rooms=Room.query.order_by(Room.code).all(), sections=Section.query.order_by(Section.name).all(), terms=Term.query.all())

@app.route('/academic/course/add', methods=['POST'])
@login_required
def add_course():
    code, title = request.form.get('code', '').strip().upper(), request.form.get('title', '').strip()
    try: units = int(request.form.get('units', 3))
    except ValueError: flash('Units must be a number.', 'danger'); return redirect(url_for('academic'))
    if not code or not title or units <= 0: flash('Code, title, and positive units required.', 'danger'); return redirect(url_for('academic'))
    try:
        db.session.add(Course(code=code, title=title, units=units, room_type=request.form.get('room_type', 'lecture')))
        db.session.commit(); flash(f"Course '{code}' added.", 'success')
    except IntegrityError: db.session.rollback(); flash(f"Course code '{code}' already exists.", 'danger')
    return redirect(url_for('academic'))

@app.route('/academic/course/<int:id>/delete', methods=['POST'])
@login_required
def delete_course(id):
    c = db.session.get(Course, id)
    if not c: flash('Course not found.', 'danger')
    elif c.schedules: flash(f"Cannot delete {c.code}: schedule(s) reference it.", 'danger')
    else: db.session.delete(c); db.session.commit(); flash(f"Course '{c.code}' deleted.", 'success')
    return redirect(url_for('academic'))

@app.route('/academic/faculty/add', methods=['POST'])
@login_required
def add_faculty():
    name, dept = request.form.get('name', '').strip(), request.form.get('department', '').strip()
    if not name: flash('Faculty name is required.', 'danger'); return redirect(url_for('academic'))
    db.session.add(Faculty(name=name, department=dept))
    db.session.commit(); flash(f"Faculty '{name}' added.", 'success')
    return redirect(url_for('academic'))

@app.route('/academic/faculty/<int:id>/delete', methods=['POST'])
@login_required
def delete_faculty(id):
    f = db.session.get(Faculty, id)
    if not f: flash('Faculty not found.', 'danger')
    elif f.schedules: flash(f"Cannot delete {f.name}: schedule(s) reference them.", 'danger')
    else: db.session.delete(f); db.session.commit(); flash(f"Faculty '{f.name}' deleted.", 'success')
    return redirect(url_for('academic'))

@app.route('/academic/room/add', methods=['POST'])
@login_required
def add_room():
    code = request.form.get('code', '').strip().upper()
    try: cap = int(request.form.get('capacity', 30))
    except ValueError: flash('Capacity must be a number.', 'danger'); return redirect(url_for('academic'))
    if not code or cap <= 0: flash('Code and positive capacity required.', 'danger'); return redirect(url_for('academic'))
    try:
        db.session.add(Room(code=code, capacity=cap, room_type=request.form.get('room_type', 'lecture')))
        db.session.commit(); flash(f"Room '{code}' added.", 'success')
    except IntegrityError: db.session.rollback(); flash(f"Room code '{code}' already exists.", 'danger')
    return redirect(url_for('academic'))

@app.route('/academic/room/<int:id>/delete', methods=['POST'])
@login_required
def delete_room(id):
    r = db.session.get(Room, id)
    if not r: flash('Room not found.', 'danger')
    elif r.schedules: flash(f"Cannot delete {r.code}: schedule(s) reference it.", 'danger')
    else: db.session.delete(r); db.session.commit(); flash(f"Room '{r.code}' deleted.", 'success')
    return redirect(url_for('academic'))

@app.route('/academic/section/add', methods=['POST'])
@login_required
def add_section():
    name = request.form.get('name', '').strip().upper()
    try: size = int(request.form.get('size', 30))
    except ValueError: flash('Section size must be a number.', 'danger'); return redirect(url_for('academic'))
    if not name or size <= 0: flash('Name and positive size required.', 'danger'); return redirect(url_for('academic'))
    try:
        db.session.add(Section(name=name, program=request.form.get('program', '').strip(), size=size))
        db.session.commit(); flash(f"Section '{name}' added.", 'success')
    except IntegrityError: db.session.rollback(); flash(f"Section '{name}' already exists.", 'danger')
    return redirect(url_for('academic'))

@app.route('/academic/section/<int:id>/delete', methods=['POST'])
@login_required
def delete_section(id):
    s = db.session.get(Section, id)
    if not s: flash('Section not found.', 'danger')
    elif s.schedules: flash(f"Cannot delete {s.name}: schedule(s) reference it.", 'danger')
    else: db.session.delete(s); db.session.commit(); flash(f"Section '{s.name}' deleted.", 'success')
    return redirect(url_for('academic'))

@app.route('/academic/term/add', methods=['POST'])
@login_required
def add_term():
    name = request.form.get('name', '').strip()
    if not name: flash('Term name required.', 'danger'); return redirect(url_for('academic'))
    try:
        db.session.add(Term(name=name)); db.session.commit(); flash(f"Term '{name}' added.", 'success')
    except IntegrityError: db.session.rollback(); flash(f"Term '{name}' already exists.", 'danger')
    return redirect(url_for('academic'))

@app.route('/academic/term/<int:id>/delete', methods=['POST'])
@login_required
def delete_term(id):
    t = db.session.get(Term, id)
    if not t: flash('Term not found.', 'danger')
    elif t.schedules: flash(f"Cannot delete {t.name}: schedule(s) reference it.", 'danger')
    else: db.session.delete(t); db.session.commit(); flash(f"Term '{t.name}' deleted.", 'success')
    return redirect(url_for('academic'))

@app.route('/availability')
@login_required
def availability():
    return render_template('availability.html', availabilities=Availability.query.order_by(Availability.day).all(), faculty=Faculty.query.order_by(Faculty.name).all(), rooms=Room.query.order_by(Room.code).all(), days=DAYS)

@app.route('/availability/add', methods=['POST'])
@login_required
def add_availability():
    entity, day = request.form.get('entity', ''), request.form.get('day', '')
    start, end = parse_time(request.form.get('start_time', '')), parse_time(request.form.get('end_time', ''))
    if not entity or day not in DAYS or not start or not end or start >= end:
        flash('Invalid entity, day, or time range.', 'danger'); return redirect(url_for('availability'))
    kind, _, eid = entity.partition(':')
    try: eid = int(eid)
    except ValueError: flash('Invalid entity.', 'danger'); return redirect(url_for('availability'))
    if kind == 'faculty': db.session.add(Availability(faculty_id=eid, day=day, start_time=start, end_time=end))
    elif kind == 'room': db.session.add(Availability(room_id=eid, day=day, start_time=start, end_time=end))
    db.session.commit(); flash('Unavailability block added.', 'success')
    return redirect(url_for('availability'))

@app.route('/availability/<int:id>/delete', methods=['POST'])
@login_required
def delete_availability(id):
    a = db.session.get(Availability, id)
    if a: db.session.delete(a); db.session.commit(); flash('Block removed.', 'success')
    return redirect(url_for('availability'))

@app.route('/schedules')
@login_required
def schedules():
    all_scheds = Schedule.query.order_by(Schedule.day, Schedule.start_time).all()
    statuses = {}
    for s in all_scheds:
        if s.is_pending: statuses[s.id] = ('pending', []); continue
        new = {'day': s.day, 'start_time': s.start_time, 'end_time': s.end_time, 'room_id': s.room_id, 'faculty_id': s.faculty_id, 'section_id': s.section_id, 'course_id': s.course_id}
        msgs = check_schedule_conflicts(new, all_scheds, exclude_id=s.id) + check_room_suitability(s.room, s.section, s.course)
        statuses[s.id] = ('ok' if not msgs else 'conflict', msgs)
    return render_template('schedules.html', schedules=all_scheds, statuses=statuses, terms=Term.query.all(), courses=Course.query.order_by(Course.code).all(), faculty=Faculty.query.order_by(Faculty.name).all(), sections=Section.query.order_by(Section.name).all(), rooms=Room.query.order_by(Room.code).all(), days=DAYS)

@app.route('/schedules/add', methods=['POST'])
@login_required
def add_schedule():
    try: term_id, course_id, faculty_id, section_id = int(request.form['term_id']), int(request.form['course_id']), int(request.form['faculty_id']), int(request.form['section_id'])
    except (KeyError, ValueError): flash('Select term, course, faculty, and section.', 'danger'); return redirect(url_for('schedules'))
    room_raw, day = request.form.get('room_id', '').strip(), request.form.get('day', '').strip() or None
    start, end = parse_time(request.form.get('start_time', '')), parse_time(request.form.get('end_time', ''))
    if room_raw and day and start and end:
        if start >= end: flash('Start must be before end.', 'danger'); return redirect(url_for('schedules'))
        new = {'day': day, 'start_time': start, 'end_time': end, 'room_id': int(room_raw), 'faculty_id': faculty_id, 'section_id': section_id, 'course_id': course_id}
        conflicts = check_schedule_conflicts(new, Schedule.query.all()) + check_room_suitability(db.session.get(Room, int(room_raw)), db.session.get(Section, section_id), db.session.get(Course, course_id))
        if conflicts: flash(' | '.join(conflicts), 'danger'); return redirect(url_for('schedules'))
        db.session.add(Schedule(term_id=term_id, course_id=course_id, faculty_id=faculty_id, section_id=section_id, room_id=int(room_raw), day=day, start_time=start, end_time=end))
        db.session.commit(); flash('Schedule added.', 'success'); return redirect(url_for('schedules'))
    db.session.add(Schedule(term_id=term_id, course_id=course_id, faculty_id=faculty_id, section_id=section_id))
    db.session.commit(); flash('Pending schedule added.', 'info'); return redirect(url_for('schedules'))

@app.route('/schedules/<int:id>/assign', methods=['POST'])
@login_required
def assign_schedule(id):
    s = db.session.get(Schedule, id)
    if not s: flash('Schedule not found.', 'danger'); return redirect(url_for('schedules'))
    room_id, day = int(request.form['room_id']), request.form['day']
    start, end = parse_time(request.form['start_time']), parse_time(request.form['end_time'])
    if not day or not start or not end or start >= end: flash('Invalid day or time.', 'danger'); return redirect(url_for('schedules'))
    new = {'day': day, 'start_time': start, 'end_time': end, 'room_id': room_id, 'faculty_id': s.faculty_id, 'section_id': s.section_id, 'course_id': s.course_id}
    conflicts = check_schedule_conflicts(new, Schedule.query.all(), exclude_id=s.id) + check_room_suitability(db.session.get(Room, room_id), s.section, s.course)
    if conflicts: flash(' | '.join(conflicts), 'danger'); return redirect(url_for('schedules'))
    s.room_id, s.day, s.start_time, s.end_time = room_id, day, start, end
    db.session.commit(); flash('Schedule assigned.', 'success'); return redirect(url_for('schedules'))

@app.route('/schedules/<int:id>/delete', methods=['POST'])
@login_required
def delete_schedule(id):
    s = db.session.get(Schedule, id)
    if s: db.session.delete(s); db.session.commit(); flash('Schedule deleted.', 'success')
    return redirect(url_for('schedules'))

@app.route('/schedules/clear', methods=['POST'])
@login_required
def clear_schedules():
    Schedule.query.delete(); db.session.commit(); flash('All schedules cleared.', 'success'); return redirect(url_for('schedules'))

@app.route('/conflicts')
@login_required
def conflicts():
    all_scheds = Schedule.query.all(); rows = []
    for s in [x for x in all_scheds if not x.is_pending]:
        new = {'day': s.day, 'start_time': s.start_time, 'end_time': s.end_time, 'room_id': s.room_id, 'faculty_id': s.faculty_id, 'section_id': s.section_id, 'course_id': s.course_id}
        rows.append({'schedule': s, 'messages': check_schedule_conflicts(new, all_scheds, exclude_id=s.id) + check_room_suitability(s.room, s.section, s.course)})
    return render_template('conflicts.html', rows=rows, total=len(rows))

@app.route('/generate', methods=['POST'])
@login_required
def generate():
    term = Term.query.first()
    if not term: flash('Create a term first.', 'danger'); return redirect(url_for('schedules'))
    assigned, unassigned = auto_generate(term.id)
    if assigned: flash(f'Auto-generator assigned {assigned} schedule(s).', 'success')
    if unassigned: flash(f"Could not place: {', '.join(f'{s.course.code}/{s.section.name}' for s in unassigned)}", 'warning')
    if not assigned and not unassigned: flash('No pending schedules to generate.', 'info')
    return redirect(url_for('schedules'))

@app.route('/reports')
@login_required
def reports():
    # 1. Default to 'section' view
    view = request.args.get('view', 'section')
    entity_id = request.args.get('entity_id', type=int)
    
    # 2. If no entity is selected, auto-pick the first section
    if not entity_id and view == 'section':
        first_sec = Section.query.first()
        if first_sec: 
            entity_id = first_sec.id
            
    term_id = request.args.get('term_id', type=int) or (Term.query.first().id if Term.query.first() else None)
    
    # 3. Fetch the schedules
    selected_scheds, title = [], 'Select a view'
    if view and entity_id and term_id:
        if view == 'section': 
            selected_scheds = Schedule.query.filter_by(term_id=term_id, section_id=entity_id).all()
            sec = db.session.get(Section, entity_id)
            if sec: title = f"Timetable — Section {sec.name}"
        elif view == 'faculty': 
            selected_scheds = Schedule.query.filter_by(term_id=term_id, faculty_id=entity_id).all()
            fac = db.session.get(Faculty, entity_id)
            if fac: title = f"Timetable — {fac.name}"
        elif view == 'room': 
            selected_scheds = Schedule.query.filter_by(term_id=term_id, room_id=entity_id).all()
            room = db.session.get(Room, entity_id)
            if room: title = f"Timetable — Room {room.code}"
            
    grid = build_timetable(selected_scheds)
    
    # 4. Generate reports data
    room_util, faculty_load, pending = [], [], []
    if term_id:
        total_slots = len(DAYS) * len(TIME_SLOTS)
        for r in Room.query.all(): 
            used = Schedule.query.filter_by(term_id=term_id, room_id=r.id).count()
            room_util.append({'room': r, 'used': used, 'total': total_slots, 'pct': round((used / total_slots) * 100, 1)})
        for f in Faculty.query.all(): 
            faculty_load.append({'faculty': f, 'load': Schedule.query.filter_by(term_id=term_id, faculty_id=f.id).count()})
        pending = Schedule.query.filter_by(room_id=None).all()
        
    return render_template('reports.html', view=view, entity_id=entity_id, title=title, sections=Section.query.all(), faculty=Faculty.query.all(), rooms=Room.query.all(), terms=Term.query.all(), term_id=term_id, grid=grid, days=DAYS, time_slots=TIME_SLOTS, room_util=room_util, faculty_load=faculty_load, pending=pending)

@app.route('/download_pdf')
@login_required
def download_pdf():
    section_id = request.args.get('section_id', type=int)
    
    if section_id:
        all_scheds = Schedule.query.filter(Schedule.room_id.isnot(None), Schedule.section_id == section_id).all()
        sec = db.session.get(Section, section_id)
    else:
        all_scheds = Schedule.query.filter(Schedule.room_id.isnot(None)).all()
        sec = None
        
    grid = build_timetable(all_scheds)
    term = Term.query.first()
    
    html = render_template('pdf_template.html', grid=grid, days=DAYS, time_slots=TIME_SLOTS, term=term, section=sec)
    
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode("utf-8")), result)
    
    if not pdf.err:
        response = make_response(result.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'attachment; filename=Master_Timetable.pdf'
        return response
        
    return "Error generating PDF", 400


if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)