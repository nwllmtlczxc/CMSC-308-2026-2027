"""
CMSC 308 - Group 3
Classroom Scheduling and Academic Timetabling System
"""

import os
import secrets
from io import BytesIO
from functools import wraps
import click
from flask import abort
from flask_wtf.csrf import CSRFProtect
from datetime import time, datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from xhtml2pdf import pisa

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


@app.cli.command('add-user')
def add_user():
    username = click.prompt('Username').strip()
    if not username:
        raise click.ClickException('Username cannot be empty.')
    if len(username) > 80:
        raise click.ClickException('Username must be 80 characters or fewer.')
    if User.query.filter_by(username=username).first():
        raise click.ClickException(f'An account for {username!r} already exists.')

    password = click.prompt('Password', hide_input=True, confirmation_prompt=True)
    if not password:
        raise click.ClickException('Password cannot be empty.')

    db.session.add(User(
        username=username,
        password_hash=generate_password_hash(password),
    ))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise click.ClickException(f'An account for {username!r} already exists.')

    click.echo(f'Instructor account created for {username!r}.')

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
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
    year_level = db.Column(db.Integer, nullable=False, default=1)
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
        if new.get('term_id') is not None and s.term_id != new['term_id']: continue
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
    room_id = new.get('room_id')
    if room_id is not None:
        availability = Availability.query.filter_by(room_id=room_id).all()
        if availability and not any(
            window.day == new['day']
            and window.start_time <= new['start_time']
            and window.end_time >= new['end_time']
            for window in availability
        ):
            conflicts.append('Room is outside its available time window.')
    return conflicts

def check_room_suitability(room, section, course):
    problems = []
    if room.capacity < section.size:
        problems.append(f"Room {room.code} capacity ({room.capacity}) is smaller than section {section.name} ({section.size})")
    if room.room_type != course.room_type:
        problems.append(f"Course {course.code} requires a {course.room_type} room, but {room.code} is a {room.room_type} room")
    return problems

class AutoGenerateResult:
    def __init__(self, assigned, unassigned, missing_instructors, fallback_schedules=None):
        self.assigned = assigned
        self.unassigned = unassigned
        self.missing_instructors = missing_instructors
        self.fallback_schedules = fallback_schedules or []

    def __iter__(self):
        return iter((self.assigned, self.unassigned))


def auto_generate(term_id, faculty_id=None):
    term_schedules = Schedule.query.filter_by(term_id=term_id).all()
    existing = [schedule for schedule in term_schedules if not schedule.is_pending]
    completed_keys = {
        (schedule.section_id, schedule.course_id)
        for schedule in term_schedules if not schedule.is_pending
    }
    pending_by_key = {
        (schedule.section_id, schedule.course_id): schedule
        for schedule in term_schedules if schedule.is_pending
    }

    tasks = []
    missing_instructors = []
    fallback_schedules = []
    requirements = SectionSubject.query.order_by(
        SectionSubject.section_id, SectionSubject.course_id
    ).all()
    requirement_keys = set()
    processed_pending = set()

    for requirement in requirements:
        key = (requirement.section_id, requirement.course_id)
        requirement_keys.add(key)
        if key in completed_keys:
            continue
        if faculty_id is not None and not any(
            professor.id == faculty_id for professor in requirement.course.professors
        ):
            continue
        if key in pending_by_key:
            schedule = pending_by_key[key]
            processed_pending.add(key)
        else:
            schedule = Schedule(
                term_id=term_id,
                course_id=requirement.course_id,
                section_id=requirement.section_id,
            )
        tasks.append({
            'schedule': schedule,
            'course': requirement.course,
            'section': requirement.section,
        })

    for key, schedule in pending_by_key.items():
        if key not in processed_pending and key not in requirement_keys:
            if faculty_id is not None and not any(
                professor.id == faculty_id for professor in schedule.course.professors
            ):
                continue
            tasks.append({
                'schedule': schedule,
                'course': schedule.course,
                'section': schedule.section,
            })

    rooms = Room.query.order_by(Room.code).all()
    faculty_unavailability = {
        faculty.id: faculty.unavailabilities for faculty in Faculty.query.all()
    }
    room_availability = {room.id: room.availabilities for room in rooms}
    slots = [start for start, _ in TIME_SLOTS]

    for task in tasks:
        course = task['course']
        schedule = task['schedule']
        schedule.room_id = None
        schedule.day = None
        schedule.start_time = None
        schedule.end_time = None
        eligible = list(course.professors)
        if faculty_id is not None:
            eligible.sort(key=lambda professor: professor.id != faculty_id)
        elif schedule.id and schedule.faculty_id:
            eligible.sort(key=lambda professor: professor.id != schedule.faculty_id)
        if not eligible:
            missing_instructors.append(f'{course.code}/{task["section"].name}')
            task['placements'] = []
            task['missing_instructor'] = True
            continue

        schedule.faculty_id = eligible[0].id
        duration = max(1, int(course.units or 1))
        end_delta = timedelta(hours=duration)
        placements = []
        for professor in eligible:
            for room in rooms:
                if check_room_suitability(room, task['section'], course):
                    continue
                r_windows = room_availability[room.id]
                p_unavailable = faculty_unavailability[professor.id]
                for day in DAYS:
                    for start in slots:
                        end = (datetime.combine(datetime.today(), start) + end_delta).time()
                        if end > SCHOOL_END:
                            continue
                        if any(
                            window.day == day and overlaps(start, end, window.start_time, window.end_time)
                            for window in p_unavailable
                        ):
                            continue
                        if r_windows and not any(
                            window.day == day and window.start_time <= start and window.end_time >= end
                            for window in r_windows
                        ):
                            continue
                        candidate = {
                            'term_id': term_id,
                            'day': day,
                            'start_time': start,
                            'end_time': end,
                            'room_id': room.id,
                            'faculty_id': professor.id,
                            'section_id': task['section'].id,
                        }
                        if any(
                            schedule.day == day
                            and schedule.start_time is not None
                            and schedule.end_time is not None
                            and overlaps(start, end, schedule.start_time, schedule.end_time)
                            and (
                                schedule.faculty_id == professor.id
                                or schedule.room_id == room.id
                                or schedule.section_id == task['section'].id
                            )
                            for schedule in existing
                        ):
                            continue
                        placements.append((candidate, professor, room))
        task['placements'] = placements

    tasks.sort(key=lambda task: (
        len(task['placements']),
        -(task['course'].units or 1),
        0 if task['course'].room_type == 'lab' else 1,
        -task['section'].size,
    ))

    planned = []
    assigned_count = 0
    still_unassigned = []
    professor_load = {
        professor.id: sum(1 for schedule in existing if schedule.faculty_id == professor.id)
        for professor in Faculty.query.all()
    }
    room_load = {
        room.id: sum(1 for schedule in existing if schedule.room_id == room.id)
        for room in rooms
    }
    for task in tasks:
        if task.get('missing_instructor'):
            if task['schedule'] in term_schedules:
                still_unassigned.append(task['schedule'])
            continue
        chosen = None
        placements = sorted(
            task['placements'],
            key=lambda placement: (
                faculty_id is not None and placement[1].id != faculty_id,
                professor_load[placement[1].id],
                room_load[placement[2].id],
                DAYS.index(placement[0]['day']),
                placement[0]['start_time'],
            ),
        )
        for candidate, professor, room in placements:
            if any(
                candidate['day'] == other['day']
                and overlaps(
                    candidate['start_time'], candidate['end_time'],
                    other['start_time'], other['end_time'],
                )
                and (
                    candidate['faculty_id'] == other['faculty_id']
                    or candidate['room_id'] == other['room_id']
                    or candidate['section_id'] == other['section_id']
                )
                for other in planned
            ):
                continue
            chosen = (candidate, professor, room)
            break

        schedule = task['schedule']
        if chosen:
            candidate, professor, room = chosen
            schedule.faculty_id = professor.id
            schedule.day = candidate['day']
            schedule.start_time = candidate['start_time']
            schedule.end_time = candidate['end_time']
            schedule.room_id = room.id
            planned.append(candidate)
            professor_load[professor.id] += 1
            room_load[room.id] += 1
            assigned_count += 1
            if faculty_id is not None and professor.id != faculty_id:
                fallback_schedules.append(schedule)
        else:
            still_unassigned.append(schedule)
        if schedule not in term_schedules:
            db.session.add(schedule)

    db.session.commit()
    return AutoGenerateResult(
        assigned_count, still_unassigned, missing_instructors, fallback_schedules
    )

def parse_time(value):
    if not value: return None
    try: return datetime.strptime(value, '%H:%M').time()
    except ValueError: return None

def build_timetable(schedules):
    grid = {}
    for s in schedules:
        if s.day and s.start_time: grid[(s.day, s.start_time.strftime('%H:%M'))] = s
    return grid


def get_selected_schedule_resources():
    faculty_id = request.args.get('faculty_id', type=int)
    section_id = request.args.get('section_id', type=int)
    room_id = request.args.get('room_id', type=int)
    return (
        db.session.get(Faculty, faculty_id) if faculty_id else None,
        db.session.get(Section, section_id) if section_id else None,
        db.session.get(Room, room_id) if room_id else None,
    )


def filter_schedules_by_resource(schedules, faculty, section, room):
    if faculty:
        return [schedule for schedule in schedules if schedule.faculty_id == faculty.id]
    if section:
        return [schedule for schedule in schedules if schedule.section_id == section.id]
    if room:
        return [schedule for schedule in schedules if schedule.room_id == room.id]
    return []

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
    faculty = Faculty.query.order_by(Faculty.name).all()
    sections = Section.query.order_by(Section.name).all()
    rooms = Room.query.order_by(Room.code).all()
    selected_faculty, selected_section, selected_room = get_selected_schedule_resources()
    all_schedules = Schedule.query.order_by(Schedule.day, Schedule.start_time).all()
    scheduled_classes = [schedule for schedule in all_schedules if schedule.room_id is not None]
    grid = build_timetable(scheduled_classes)
    faculty_schedules = [
        schedule for schedule in all_schedules
        if selected_faculty and schedule.faculty_id == selected_faculty.id
    ]
    section_schedules = [
        schedule for schedule in all_schedules
        if selected_section and schedule.section_id == selected_section.id
    ]
    room_schedules = [
        schedule for schedule in all_schedules
        if selected_room and schedule.room_id == selected_room.id
    ]
    selected_schedules = filter_schedules_by_resource(
        all_schedules, selected_faculty, selected_section, selected_room
    )
    selected_grid = build_timetable([
        schedule for schedule in selected_schedules if schedule.room_id is not None
    ])

    stats = {
        'courses': Course.query.count(), 
        'faculty': Faculty.query.count(), 
        'rooms': Room.query.count(), 
        'sections': Section.query.count(), 
        'schedules': len(scheduled_classes),
        'pending': Schedule.query.filter_by(room_id=None).count()
    }
    return render_template(
        'index.html', stats=stats, grid=grid, days=DAYS, time_slots=TIME_SLOTS,
        faculty=faculty, sections=sections, rooms=rooms,
        selected_faculty_id=selected_faculty.id if selected_faculty else None,
        selected_faculty=selected_faculty, selected_section=selected_section,
        selected_room=selected_room,
        faculty_schedules=faculty_schedules,
        section_schedules=section_schedules,
        room_schedules=room_schedules,
        selected_grid=selected_grid,
    )


@app.route('/export-schedule')
@login_required
def export_schedule():
    selected_faculty, selected_section, selected_room = get_selected_schedule_resources()
    all_schedules = Schedule.query.order_by(Schedule.day, Schedule.start_time).all()
    if selected_faculty or selected_section or selected_room:
        displayed_schedules = filter_schedules_by_resource(
            all_schedules, selected_faculty, selected_section, selected_room
        )
    else:
        displayed_schedules = all_schedules
    grid = build_timetable([
        schedule for schedule in displayed_schedules if schedule.room_id is not None
    ])

    filename = 'schedule.pdf'
    if selected_faculty:
        filename = 'professorSchedule.pdf'
    elif selected_section:
        filename = 'sectionSchedule.pdf'
    elif selected_room:
        filename = 'roomSchedule.pdf'

    html = render_template(
        'schedule_export.html', grid=grid, days=DAYS, time_slots=TIME_SLOTS,
    )
    output = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode('utf-8')), output)
    if pdf.err:
        app.logger.error('Failed to generate schedule PDF: %s PDF error(s).', pdf.err)
        abort(500, description='Could not generate the schedule PDF.')
    output.seek(0)
    return send_file(
        output, mimetype='application/pdf', as_attachment=True,
        download_name=filename,
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
    if (
        day not in DAYS or not start or not end or start >= end
        or start < SCHOOL_START or end > SCHOOL_END
    ):
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
        assignments=SectionSubject.query.order_by(SectionSubject.section_id, SectionSubject.course_id).all(),
    )

@app.route('/manage-sections/subjects/add', methods=['POST'])
@admin_required
def assign_section_subject():
    try:
        section_id = int(request.form.get('section_id', ''))
        course_id = int(request.form.get('course_id', ''))
    except ValueError:
        flash('Select a valid section and subject.', 'danger')
        return redirect(url_for('manage_sections'))
    section, course = db.session.get(Section, section_id), db.session.get(Course, course_id)
    if not section or not course:
        flash('Select an existing section and subject.', 'danger')
        return redirect(url_for('manage_sections'))

    assignment = db.session.get(SectionSubject, (section_id, course_id))
    if assignment:
        flash(f"{course.code} is already assigned to {section.name}.", 'warning')
        return redirect(url_for('manage_sections'))
    db.session.add(SectionSubject(section_id=section_id, course_id=course_id))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(f"{course.code} is already assigned to {section.name}.", 'warning')
        return redirect(url_for('manage_sections'))
    flash(f"{course.code} assigned to {section.name}.", 'success')
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
    faculty = Faculty.query.order_by(Faculty.name).all()
    selected_faculty_id = request.args.get('faculty_id', type=int)
    selected_faculty = next(
        (professor for professor in faculty if professor.id == selected_faculty_id),
        None,
    )
    displayed_schedules = (
        [schedule for schedule in all_scheds if schedule.faculty_id == selected_faculty.id]
        if selected_faculty else all_scheds
    )
    statuses = {}
    for s in all_scheds:
        if s.is_pending: statuses[s.id] = ('pending', []); continue
        new = {'term_id': s.term_id, 'day': s.day, 'start_time': s.start_time, 'end_time': s.end_time, 'room_id': s.room_id, 'faculty_id': s.faculty_id, 'section_id': s.section_id, 'course_id': s.course_id}
        msgs = check_schedule_conflicts(new, all_scheds, exclude_id=s.id) + check_room_suitability(s.room, s.section, s.course)
        statuses[s.id] = ('ok' if not msgs else 'conflict', msgs)
    return render_template(
        'schedules.html', schedules=displayed_schedules, statuses=statuses,
        terms=Term.query.all(), courses=Course.query.order_by(Course.code).all(),
        faculty=faculty, sections=Section.query.order_by(Section.name).all(),
        selected_faculty_id=selected_faculty.id if selected_faculty else None,
        selected_faculty=selected_faculty,
    )

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
    new = {'term_id': s.term_id, 'day': day, 'start_time': start, 'end_time': end, 'room_id': room_id, 'faculty_id': s.faculty_id, 'section_id': s.section_id, 'course_id': s.course_id}
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
        new = {'term_id': s.term_id, 'day': s.day, 'start_time': s.start_time, 'end_time': s.end_time, 'room_id': s.room_id, 'faculty_id': s.faculty_id, 'section_id': s.section_id, 'course_id': s.course_id}
        rows.append({'schedule': s, 'messages': check_schedule_conflicts(new, all_scheds, exclude_id=s.id) + check_room_suitability(s.room, s.section, s.course)})
    return render_template('conflicts.html', rows=rows, total=len(rows))

@app.route('/generate', methods=['POST'])
@admin_required
def generate():
    terms = Term.query.order_by(Term.id).all()
    if not terms:
        flash('Create a term before generating schedules.', 'danger')
        return redirect(url_for('schedules'))
    faculty_id = request.form.get('faculty_id', type=int)
    if request.form.get('faculty_id', '').strip() and not faculty_id:
        flash('Select a valid professor.', 'danger')
        return redirect(url_for('schedules'))
    if faculty_id is None:
        flash('Select a professor to generate schedules one at a time.', 'danger')
        return redirect(url_for('schedules'))
    selected_faculty = db.session.get(Faculty, faculty_id)
    if not selected_faculty:
        flash('Select a valid professor.', 'danger')
        return redirect(url_for('schedules'))
    if not SectionSubject.query.first() and not Schedule.query.filter_by(room_id=None).first():
        flash('Assign subjects to sections and professors before generating schedules.', 'info')
        return redirect(url_for('schedules'))
    assigned_count, unassigned, missing_instructors, fallback_schedules = 0, [], [], []
    for term in terms:
        result = auto_generate(term.id, faculty_id=faculty_id)
        assigned_count += result.assigned
        unassigned.extend(result.unassigned)
        missing_instructors.extend(result.missing_instructors)
        fallback_schedules.extend(result.fallback_schedules)
    if assigned_count:
        flash(
            f'Auto-generator assigned {assigned_count} schedule(s), prioritizing {selected_faculty.name}.',
            'success',
        )
    if fallback_schedules:
        handoffs = ', '.join(
            f'{schedule.course.code}/{schedule.section.name} to {schedule.faculty.name}'
            for schedule in fallback_schedules
        )
        flash(
            f'{selected_faculty.name} had no conflict-free slot for: {handoffs}. '
            'These schedules were handed off to other qualified professors.',
            'warning',
        )
    if unassigned:
        flash(f"Could not place: {', '.join(f'{s.course.code}/{s.section.name}' for s in unassigned)}", 'warning')
    if missing_instructors:
        flash(f"Assign a professor to these subjects before generating: {', '.join(missing_instructors)}", 'warning')
    if not assigned_count and not unassigned and not missing_instructors:
        flash(f'No unscheduled section subjects are assigned to {selected_faculty.name}.', 'info')
    return redirect(
        url_for('schedules')
        if fallback_schedules else url_for('schedules', faculty_id=faculty_id)
    )

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
    with app.app_context(): db.create_all()
    app.run(debug=app.config['DEBUG'])
