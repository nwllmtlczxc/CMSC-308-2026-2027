"""
CMSC 308 - Group 3
Classroom Scheduling and Academic Timetabling System
"""

import os
import secrets
from functools import wraps
import click
from flask import abort
from flask_wtf.csrf import CSRFProtect
from datetime import time, datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
APP_ENV = os.environ.get('APP_ENV', 'development').lower()
secret_key = os.environ.get('FLASK_SECRET_KEY')
if APP_ENV == 'production' and not secret_key:
    raise RuntimeError('FLASK_SECRET_KEY must be set when APP_ENV=production.')
app.config['SECRET_KEY'] = secret_key or secrets.token_hex(32)
app.config['DEBUG'] = APP_ENV == 'development' and os.environ.get('FLASK_DEBUG') == '1'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = APP_ENV == 'production'
csrf = CSRFProtect(app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'timetable.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped_view(*args, **kwargs):
        if current_user.role != 'Admin':
            abort(403)
        return view(*args, **kwargs)
    return wrapped_view


@app.cli.command('init-db')
def init_db():
    db.create_all()
    click.echo('Database tables created.')


@app.cli.command('make-admin')
@click.argument('username')
def make_admin(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        raise click.ClickException(f'No account found for {username!r}.')
    user.role = 'Admin'
    db.session.commit()
    click.echo(f'{username} is now an administrator.')

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
YEAR_LEVELS = [(1, '1st Year'), (2, '2nd Year'), (3, '3rd Year'), (4, '4th Year')]
SCHOOL_START = time(7, 0)
SCHOOL_END = time(16, 0)
TIME_SLOTS = [
    (time(7, 0), time(8, 0)), (time(8, 0), time(9, 0)), (time(9, 0), time(10, 0)),
    (time(10, 0), time(11, 0)), (time(11, 0), time(12, 0)), (time(12, 0), time(13, 0)),
    (time(13, 0), time(14, 0)), (time(14, 0), time(15, 0)), (time(15, 0), time(16, 0)),
]

faculty_subjects = db.Table(
    'faculty_subjects',
    db.Column('faculty_id', db.Integer, db.ForeignKey('faculty.id'), primary_key=True),
    db.Column('course_id', db.Integer, db.ForeignKey('course.id'), primary_key=True),
)

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
    professors = db.relationship('Faculty', secondary=faculty_subjects, back_populates='subjects')
    section_subjects = db.relationship('SectionSubject', back_populates='course', cascade='all, delete-orphan')

class Faculty(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(80))
    schedules = db.relationship('Schedule', backref='faculty', lazy=True)
    availabilities = db.relationship('Availability', backref='faculty', lazy=True)
    unavailabilities = db.relationship('Unavailability', backref='faculty', lazy=True)
    subjects = db.relationship('Course', secondary=faculty_subjects, back_populates='professors')

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
    section_subjects = db.relationship('SectionSubject', back_populates='section', cascade='all, delete-orphan')

class SectionSubject(db.Model):
    __tablename__ = 'section_subjects'
    section_id = db.Column(db.Integer, db.ForeignKey('section.id'), primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), primary_key=True)
    year_level = db.Column(db.Integer, nullable=False)
    section = db.relationship('Section', back_populates='section_subjects')
    course = db.relationship('Course', back_populates='section_subjects')

class Availability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'), nullable=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=True)
    day = db.Column(db.String(3), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

class Unavailability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'), nullable=False)
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
        return (
            self.room_id is None
            or self.day is None
            or self.start_time is None
            or self.end_time is None
        )

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
    if not SCHOOL_START <= new['start_time'] < new['end_time'] <= SCHOOL_END:
        conflicts.append('Classes must be scheduled between 7:00 AM and 4:00 PM.')

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

    faculty_id = new.get('faculty_id')
    if faculty_id is not None:
        windows = Unavailability.query.filter_by(faculty_id=faculty_id).all()
        if any(
            window.day == new['day']
            and overlaps(new['start_time'], new['end_time'], window.start_time, window.end_time)
            for window in windows
        ):
            conflicts.append(
                "Professor is unavailable during "
                f"{new['day']} {new['start_time'].strftime('%H:%M')}-"
                f"{new['end_time'].strftime('%H:%M')}"
            )
    return conflicts

def check_room_suitability(room, section, course):
    problems = []
    if room.capacity < section.size:
        problems.append(f"Room {room.code} capacity ({room.capacity}) is smaller than section {section.name} ({section.size})")
    if room.room_type != course.room_type:
        problems.append(f"Course {course.code} requires a {course.room_type} room, but {room.code} is a {room.room_type} room")
    return problems

def auto_generate(term_id):
    pending = [
        schedule for schedule in Schedule.query.filter_by(term_id=term_id).all()
        if schedule.room_id is None
        or schedule.day is None
        or schedule.start_time is None
        or schedule.end_time is None
    ]
    pending.sort(key=lambda s: (0 if s.course.room_type == 'lab' else 1, -s.section.size))
    assigned_count, still_unassigned = 0, []
    rooms = Room.query.order_by(Room.code).all()
    existing = Schedule.query.filter(
        Schedule.term_id == term_id,
        Schedule.room_id.isnot(None),
    ).all()
    room_usage = {
        room.id: sum(
            1 for schedule in existing
            if schedule.room_id == room.id and not schedule.is_pending
        )
        for room in rooms
    }

    for sched in pending:
        placed = False
        for day in DAYS:
            for start, end in TIME_SLOTS:
                for room in sorted(rooms, key=lambda room: (room_usage[room.id], room.code)):
                    if check_room_suitability(room, sched.section, sched.course): continue
                    candidate = {'day': day, 'start_time': start, 'end_time': end, 'room_id': room.id, 'faculty_id': sched.faculty_id, 'section_id': sched.section_id, 'course_id': sched.course_id}
                    if not check_schedule_conflicts(candidate, existing, exclude_id=sched.id):
                        sched.day, sched.start_time, sched.end_time, sched.room_id = day, start, end, room.id
                        db.session.commit()
                        existing.append(sched)
                        room_usage[room.id] += 1
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

def build_schedule_grid(schedules):
    grid = {}
    for schedule in schedules:
        key = (schedule.day, schedule.start_time.strftime('%H:%M'))
        grid.setdefault(key, []).append(schedule)
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
        flash('Username or password is incorrect.', 'danger')
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

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ============================================================
# MAIN ROUTES
# ============================================================
@app.route('/')
@login_required
def index():
    schedules = Schedule.query.filter(
        Schedule.room_id.isnot(None),
        Schedule.day.isnot(None),
        Schedule.start_time.isnot(None),
        Schedule.end_time.isnot(None),
    ).order_by(Schedule.start_time).all()
    term = Term.query.order_by(Term.id.desc()).first()
    rooms = Room.query.order_by(Room.code).all()
    faculty = Faculty.query.order_by(Faculty.name).all()
    sections = Section.query.order_by(Section.name).all()
    return render_template(
        'index.html',
        rooms=rooms,
        faculty=faculty,
        sections=sections,
        room_grids={
            room.id: build_schedule_grid([s for s in schedules if s.room_id == room.id])
            for room in rooms
        },
        professor_grids={
            professor.id: build_schedule_grid([s for s in schedules if s.faculty_id == professor.id])
            for professor in faculty
        },
        section_grids={
            section.id: build_schedule_grid([s for s in schedules if s.section_id == section.id])
            for section in sections
        },
        days=DAYS,
        time_slots=TIME_SLOTS,
        term=term,
    )

@app.route('/academic')
@admin_required
def academic():
    return render_template('academic.html', courses=Course.query.order_by(Course.code).all(), faculty=Faculty.query.order_by(Faculty.name).all(), rooms=Room.query.order_by(Room.code).all(), sections=Section.query.order_by(Section.name).all(), terms=Term.query.all())

@app.route('/academic/course/add', methods=['POST'])
@admin_required
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
@admin_required
def delete_course(id):
    c = db.session.get(Course, id)
    if not c: flash('Course not found.', 'danger')
    elif c.schedules: flash(f"Cannot delete {c.code}: schedule(s) reference it.", 'danger')
    else: db.session.delete(c); db.session.commit(); flash(f"Course '{c.code}' deleted.", 'success')
    return redirect(url_for('academic'))

@app.route('/academic/faculty/add', methods=['POST'])
@admin_required
def add_faculty():
    name, dept = request.form.get('name', '').strip(), request.form.get('department', '').strip()
    if not name: flash('Faculty name is required.', 'danger'); return redirect(url_for('academic'))
    db.session.add(Faculty(name=name, department=dept))
    db.session.commit(); flash(f"Faculty '{name}' added.", 'success')
    return redirect(url_for('academic'))

@app.route('/academic/faculty/<int:id>/delete', methods=['POST'])
@admin_required
def delete_faculty(id):
    f = db.session.get(Faculty, id)
    if not f: flash('Faculty not found.', 'danger')
    elif f.schedules: flash(f"Cannot delete {f.name}: schedule(s) reference them.", 'danger')
    else: db.session.delete(f); db.session.commit(); flash(f"Faculty '{f.name}' deleted.", 'success')
    return redirect(url_for('academic'))

@app.route('/academic/room/add', methods=['POST'])
@admin_required
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
@admin_required
def delete_room(id):
    r = db.session.get(Room, id)
    if not r: flash('Room not found.', 'danger')
    elif r.schedules: flash(f"Cannot delete {r.code}: schedule(s) reference it.", 'danger')
    else: db.session.delete(r); db.session.commit(); flash(f"Room '{r.code}' deleted.", 'success')
    return redirect(url_for('academic'))

@app.route('/academic/section/add', methods=['POST'])
@admin_required
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
@admin_required
def delete_section(id):
    s = db.session.get(Section, id)
    if not s: flash('Section not found.', 'danger')
    elif s.schedules: flash(f"Cannot delete {s.name}: schedule(s) reference it.", 'danger')
    else: db.session.delete(s); db.session.commit(); flash(f"Section '{s.name}' deleted.", 'success')
    return redirect(url_for('academic'))

@app.route('/academic/term/add', methods=['POST'])
@admin_required
def add_term():
    name = request.form.get('name', '').strip()
    if not name: flash('Term name required.', 'danger'); return redirect(url_for('academic'))
    try:
        db.session.add(Term(name=name)); db.session.commit(); flash(f"Term '{name}' added.", 'success')
    except IntegrityError: db.session.rollback(); flash(f"Term '{name}' already exists.", 'danger')
    return redirect(url_for('academic'))

@app.route('/academic/term/<int:id>/delete', methods=['POST'])
@admin_required
def delete_term(id):
    t = db.session.get(Term, id)
    if not t: flash('Term not found.', 'danger')
    elif t.schedules: flash(f"Cannot delete {t.name}: schedule(s) reference it.", 'danger')
    else: db.session.delete(t); db.session.commit(); flash(f"Term '{t.name}' deleted.", 'success')
    return redirect(url_for('academic'))

@app.route('/availability')
@admin_required
def availability():
    return render_template(
        'availability.html',
        unavailabilities=Unavailability.query.order_by(Unavailability.day, Unavailability.start_time).all(),
        faculty=Faculty.query.order_by(Faculty.name).all(),
        courses=Course.query.order_by(Course.code).all(),
        days=DAYS,
    )

@app.route('/availability/add', methods=['POST'])
@admin_required
def add_unavailability():
    day = request.form.get('day', '')
    start, end = parse_time(request.form.get('start_time', '')), parse_time(request.form.get('end_time', ''))
    try:
        faculty_id = int(request.form.get('faculty_id', ''))
    except ValueError:
        flash('Select a valid professor.', 'danger')
        return redirect(url_for('availability'))
    if not db.session.get(Faculty, faculty_id):
        flash('Select a valid professor.', 'danger')
        return redirect(url_for('availability'))
    if day not in DAYS or not start or not end or start >= end:
        flash('Invalid day or time range.', 'danger')
        return redirect(url_for('availability'))
    db.session.add(Unavailability(faculty_id=faculty_id, day=day, start_time=start, end_time=end))
    db.session.commit(); flash('Professor unavailability added.', 'success')
    return redirect(url_for('availability'))

@app.route('/availability/<int:id>/delete', methods=['POST'])
@admin_required
def delete_unavailability(id):
    unavailability = db.session.get(Unavailability, id)
    if not unavailability:
        flash('Professor unavailability not found.', 'danger')
        return redirect(url_for('availability'))
    db.session.delete(unavailability); db.session.commit(); flash('Professor unavailability removed.', 'success')
    return redirect(url_for('availability'))

@app.route('/availability/subjects/add', methods=['POST'])
@admin_required
def assign_subject():
    try:
        faculty_id = int(request.form.get('faculty_id', ''))
        course_id = int(request.form.get('course_id', ''))
    except ValueError:
        flash('Select a valid professor and subject.', 'danger')
        return redirect(url_for('availability'))
    professor, subject = db.session.get(Faculty, faculty_id), db.session.get(Course, course_id)
    if not professor or not subject:
        flash('Select an existing professor and subject.', 'danger')
        return redirect(url_for('availability'))
    if subject in professor.subjects:
        flash(f"{subject.code} is already assigned to {professor.name}.", 'warning')
        return redirect(url_for('availability'))
    professor.subjects.append(subject)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(f"{subject.code} is already assigned to {professor.name}.", 'warning')
        return redirect(url_for('availability'))
    flash(f"{subject.code} assigned to {professor.name}.", 'success')
    return redirect(url_for('availability'))

@app.route('/availability/subjects/<int:faculty_id>/<int:course_id>/remove', methods=['POST'])
@admin_required
def remove_subject(faculty_id, course_id):
    professor, subject = db.session.get(Faculty, faculty_id), db.session.get(Course, course_id)
    if not professor or not subject or subject not in professor.subjects:
        flash('Professor subject assignment not found.', 'danger')
        return redirect(url_for('availability'))
    professor.subjects.remove(subject)
    db.session.commit()
    flash(f"{subject.code} removed from {professor.name}.", 'success')
    return redirect(url_for('availability'))

@app.route('/manage-sections')
@admin_required
def manage_sections():
    return render_template(
        'manage_sections.html',
        sections=Section.query.order_by(Section.name).all(),
        courses=Course.query.order_by(Course.code).all(),
        assignments=SectionSubject.query.order_by(SectionSubject.section_id, SectionSubject.year_level, SectionSubject.course_id).all(),
        year_levels=YEAR_LEVELS,
    )

@app.route('/manage-sections/subjects/add', methods=['POST'])
@admin_required
def assign_section_subject():
    try:
        section_id = int(request.form.get('section_id', ''))
        year_level = int(request.form.get('year_level', ''))
        course_id = int(request.form.get('course_id', ''))
    except ValueError:
        flash('Select a valid section, year level, and subject.', 'danger')
        return redirect(url_for('manage_sections'))
    if year_level not in [level for level, _ in YEAR_LEVELS]:
        flash('Select a valid year level.', 'danger')
        return redirect(url_for('manage_sections'))
    section, course = db.session.get(Section, section_id), db.session.get(Course, course_id)
    if not section or not course:
        flash('Select an existing section and subject.', 'danger')
        return redirect(url_for('manage_sections'))

    assignment = db.session.get(SectionSubject, (section_id, course_id))
    if assignment and assignment.year_level == year_level:
        flash(f"{course.code} is already assigned to {section.name} for year {year_level}.", 'warning')
        return redirect(url_for('manage_sections'))
    if assignment:
        assignment.year_level = year_level
        db.session.commit()
        flash(f"{course.code} year updated for {section.name}.", 'success')
        return redirect(url_for('manage_sections'))
    db.session.add(SectionSubject(section_id=section_id, course_id=course_id, year_level=year_level))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(f"{course.code} is already assigned to {section.name}.", 'warning')
        return redirect(url_for('manage_sections'))
    flash(f"{course.code} assigned to {section.name} for year {year_level}.", 'success')
    return redirect(url_for('manage_sections'))

@app.route('/manage-sections/subjects/remove', methods=['POST'])
@admin_required
def remove_section_subject():
    try:
        section_id = int(request.form.get('section_id', ''))
        course_id = int(request.form.get('course_id', ''))
    except ValueError:
        flash('Invalid section subject assignment.', 'danger')
        return redirect(url_for('manage_sections'))
    assignment = db.session.get(SectionSubject, (section_id, course_id))
    if not assignment:
        flash('Section subject assignment not found.', 'danger')
        return redirect(url_for('manage_sections'))
    course_code, section_name = assignment.course.code, assignment.section.name
    db.session.delete(assignment)
    db.session.commit()
    flash(f"{course_code} removed from {section_name}.", 'success')
    return redirect(url_for('manage_sections'))

@app.route('/schedules')
@admin_required
def schedules():
    all_scheds = Schedule.query.order_by(Schedule.day, Schedule.start_time).all()
    statuses = {}
    for s in all_scheds:
        if s.is_pending: statuses[s.id] = ('pending', []); continue
        new = {'day': s.day, 'start_time': s.start_time, 'end_time': s.end_time, 'room_id': s.room_id, 'faculty_id': s.faculty_id, 'section_id': s.section_id, 'course_id': s.course_id}
        msgs = check_schedule_conflicts(new, all_scheds, exclude_id=s.id) + check_room_suitability(s.room, s.section, s.course)
        statuses[s.id] = ('ok' if not msgs else 'conflict', msgs)
    return render_template('schedules.html', schedules=all_scheds, statuses=statuses, terms=Term.query.all(), courses=Course.query.order_by(Course.code).all(), faculty=Faculty.query.order_by(Faculty.name).all(), sections=Section.query.order_by(Section.name).all())

@app.route('/schedules/add', methods=['POST'])
@admin_required
def add_schedule():
    try: term_id, course_id, faculty_id, section_id = int(request.form['term_id']), int(request.form['course_id']), int(request.form['faculty_id']), int(request.form['section_id'])
    except (KeyError, ValueError): flash('Select term, course, faculty, and section.', 'danger'); return redirect(url_for('schedules'))
    if not all(db.session.get(model, identifier) for model, identifier in (
        (Term, term_id), (Course, course_id), (Faculty, faculty_id), (Section, section_id)
    )):
        flash('Select an existing term, course, professor, and section.', 'danger')
        return redirect(url_for('schedules'))
    db.session.add(Schedule(term_id=term_id, course_id=course_id, faculty_id=faculty_id, section_id=section_id))
    db.session.commit()
    flash('Schedule request added. Auto-Generate will choose an available time and room.', 'success')
    return redirect(url_for('schedules'))

@app.route('/schedules/<int:id>/assign', methods=['POST'])
@admin_required
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
@admin_required
def delete_schedule(id):
    s = db.session.get(Schedule, id)
    if s: db.session.delete(s); db.session.commit(); flash('Schedule deleted.', 'success')
    return redirect(url_for('schedules'))

@app.route('/schedules/clear', methods=['POST'])
@admin_required
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
@admin_required
def generate():
    terms = Term.query.order_by(Term.id).all()
    if not terms:
        flash('Create a term before generating schedules.', 'danger')
        return redirect(url_for('schedules'))
    pending = [
        schedule for schedule in Schedule.query.all()
        if schedule.room_id is None
        or schedule.day is None
        or schedule.start_time is None
        or schedule.end_time is None
    ]
    if not pending:
        flash('Add course, professor, section, and term assignments before generating schedules.', 'info')
        return redirect(url_for('schedules'))
    assigned_count, unassigned = 0, []
    for term in terms:
        assigned, term_unassigned = auto_generate(term.id)
        assigned_count += assigned
        unassigned.extend(term_unassigned)
    if assigned_count:
        flash(f'Auto-generator assigned {assigned_count} schedule(s).', 'success')
    if unassigned:
        flash(f"Could not place: {', '.join(f'{s.course.code}/{s.section.name}' for s in unassigned)}", 'warning')
    return redirect(url_for('schedules'))

@app.route('/reports')
@login_required
def reports():
    report_type = request.args.get('report', 'room-utilization')
    if report_type not in ('room-utilization', 'faculty-load'):
        abort(404)
    term = Term.query.first()
    room_util, faculty_load = [], []
    if term:
        term_id = term.id
        if report_type == 'room-utilization':
            total_slots = len(DAYS) * len(TIME_SLOTS)
            for r in Room.query.all():
                used = Schedule.query.filter_by(term_id=term_id, room_id=r.id).count()
                room_util.append({'room': r, 'used': used, 'total': total_slots, 'pct': round((used / total_slots) * 100, 1)})
        else:
            for f in Faculty.query.all():
                load = Schedule.query.filter_by(term_id=term_id, faculty_id=f.id).count()
                faculty_load.append({'faculty': f, 'load': load})
    return render_template('reports.html', report_type=report_type, room_util=room_util, faculty_load=faculty_load)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        admin = User.query.filter_by(username='admin').first()
        if admin and admin.role != 'Admin':
            admin.role = 'Admin'
            db.session.commit()
    app.run(debug=app.config['DEBUG'])
