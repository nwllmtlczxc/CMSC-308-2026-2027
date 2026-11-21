from datetime import time
from app import app, db, Term, Course, Faculty, Room, Section, Availability, Schedule, User
from werkzeug.security import generate_password_hash

def seed():
    with app.app_context():
        db.create_all()
        
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            db.session.add(User(username="admin", password_hash=generate_password_hash("admin123"), role="Admin"))
            db.session.commit()
            print("Default Admin Account Created -> Username: admin | Password: admin123")
        elif admin.role != "Admin":
            admin.role = "Admin"
            db.session.commit()

        if Term.query.first(): return

        term = Term(name="1st Semester 2026 - 2027")
        db.session.add(term)
        db.session.add_all([
            Course(code="CSST 102", title="Machine Learning", units=3, room_type="lecture"),
            Course(code="CMSC 308", title="Programming Languages", units=3, room_type="lecture"),
            Course(code="CMSC 201", title="Data Structures", units=3, room_type="lab"),
            Faculty(name="Rolan Sotomayor", department="CCS"),
            Faculty(name="Maria Cruz", department="CCS"),
            Faculty(name="Juan Reyes", department="Math"),
            Room(code="Room 206", capacity=40, room_type="lecture"),
            Room(code="MAC LAB", capacity=30, room_type="lab"),
            Room(code="TESOL", capacity=38, room_type="lecture"),
            Section(name="BSCS 3A", program="BS Computer Science", size=35),
            Section(name="BSCS 3B", program="BS Computer Science", size=30),
            Section(name="BSIT 2A", program="BS Information Technology", size=40),
        ])
        db.session.commit()
        
        cruz = Faculty.query.filter_by(name="Maria Cruz").first()
        reyes = Faculty.query.filter_by(name="Juan Reyes").first()
        lab1 = Room.query.filter_by(code="MAC LAB").first()
        db.session.add_all([
            Availability(faculty_id=cruz.id, day="Mon", start_time=time(7, 0), end_time=time(9, 0)),
            Availability(faculty_id=reyes.id, day="Fri", start_time=time(15, 0), end_time=time(17, 0)),
            Availability(room_id=lab1.id, day="Wed", start_time=time(13, 0), end_time=time(15, 0)),
        ])
        
        csst102 = Course.query.filter_by(code="CSST 102").first()
        cmsc308 = Course.query.filter_by(code="CMSC 308").first()
        cmsc201 = Course.query.filter_by(code="CMSC 201").first()
        bscs3a = Section.query.filter_by(name="BSCS 3A").first()
        bscs3b = Section.query.filter_by(name="BSCS 3B").first()
        bsit2a = Section.query.filter_by(name="BSIT 2A").first()
        rolly = Faculty.query.filter_by(name="Rolan Sotomayor").first()
        r206 = Room.query.filter_by(code="Room 206").first()
        maclab = Room.query.filter_by(code="MAC LAB").first()

        db.session.add_all([
            Schedule(term_id=term.id, course_id=csst102.id, faculty_id=cruz.id, section_id=bscs3b.id, room_id=r206.id, day="Thu", start_time=time(7, 0), end_time=time(9, 0)),
            Schedule(term_id=term.id, course_id=cmsc308.id, faculty_id=rolly.id, section_id=bscs3a.id, room_id=r206.id, day="Thu", start_time=time(11, 0), end_time=time(13, 0)),
            Schedule(term_id=term.id, course_id=cmsc201.id, faculty_id=rolly.id, section_id=bsit2a.id, room_id=maclab.id, day="Thu", start_time=time(9, 0), end_time=time(11, 0)),
        ])
        db.session.commit()
        print("Database generated successfully with sample schedules!")

if __name__ == '__main__':
    seed()
