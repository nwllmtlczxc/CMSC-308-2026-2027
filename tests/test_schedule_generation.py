from datetime import time
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import create_engine
from flask import template_rendered
from werkzeug.security import check_password_hash

import app as system


@pytest.fixture()
def app(tmp_path):
    system.app.config.update(
        TESTING=True, WTF_CSRF_ENABLED=False, SECRET_KEY="test-secret"
    )
    test_engine = create_engine(f"sqlite:///{tmp_path / 'schedule-test.db'}")
    app_context = system.app.app_context()
    app_context.push()
    previous_engine = system.db.engines[None]
    system.db.engines[None] = test_engine
    try:
        system.db.create_all()
        yield system.app
        system.db.session.remove()
        system.db.drop_all()
    finally:
        test_engine.dispose()
        system.db.engines[None] = previous_engine
        app_context.pop()


def test_auto_generate_uses_subjects_and_unavailability_without_conflicts(app):
    with app.app_context():
        term = system.Term(name="Fall")
        course_a = system.Course(code="CS101", title="Programming", units=2)
        course_b = system.Course(code="CS102", title="Algorithms", units=2)
        professor = system.Faculty(name="Ada")
        room = system.Room(code="R1", capacity=40)
        section = system.Section(name="A", size=30)
        system.db.session.add_all([term, course_a, course_b, professor, room, section])
        system.db.session.commit()
        professor.subjects.extend([course_a, course_b])
        section.section_subjects.extend([
            system.SectionSubject(course=course_a),
            system.SectionSubject(course=course_b),
        ])
        system.db.session.add_all([
            system.Availability(
                faculty_id=professor.id, day="Fri",
                start_time=time(7), end_time=time(8),
            ),
            system.Availability(
                room_id=room.id, day="Mon",
                start_time=time(7), end_time=time(16),
            ),
            system.Unavailability(
                faculty_id=professor.id, day="Mon",
                start_time=time(7), end_time=time(9),
            ),
        ])
        system.db.session.commit()

        result = system.auto_generate(term.id)

        schedules = system.Schedule.query.filter_by(term_id=term.id).all()
        assert result.assigned == 2
        assert result.unassigned == []
        assert len(schedules) == 2
        assert {schedule.faculty_id for schedule in schedules} == {professor.id}
        assert all(schedule.day == "Mon" for schedule in schedules)
        assert all(schedule.start_time >= time(9) for schedule in schedules)
        assert all(schedule.room_id == room.id for schedule in schedules)
        first, second = sorted(schedules, key=lambda schedule: schedule.start_time)
        assert first.end_time <= second.start_time
        for schedule in schedules:
            candidate = {
                "term_id": schedule.term_id, "day": schedule.day,
                "start_time": schedule.start_time, "end_time": schedule.end_time,
                "room_id": schedule.room_id, "faculty_id": schedule.faculty_id,
                "section_id": schedule.section_id,
            }
            assert system.check_schedule_conflicts(
                candidate, schedules, exclude_id=schedule.id
            ) == []


def test_signup_page_and_route_are_removed(app):
    client = app.test_client()

    assert client.get("/register").status_code == 404
    response = client.post(
        "/register", data={"username": "new-user", "password": "secret"}
    )
    assert response.status_code == 404
    login_page = client.get("/login")
    assert login_page.status_code == 200
    assert b"Signup" not in login_page.data


def test_add_user_cli_creates_instructor_with_hashed_password(app):
    result = app.test_cli_runner().invoke(
        args=["add-user"], input="new-user\nsecret\nsecret\n"
    )

    assert result.exit_code == 0, result.output
    with app.app_context():
        user = system.User.query.filter_by(username="new-user").first()
        assert user is not None
        assert user.role == "Instructor"
        assert check_password_hash(user.password_hash, "secret")


def test_add_user_cli_rejects_duplicate_username(app):
    with app.app_context():
        system.db.session.add(
            system.User(username="existing-user", password_hash="already-hashed")
        )
        system.db.session.commit()

    result = app.test_cli_runner().invoke(
        args=["add-user"], input="existing-user\n"
    )

    assert result.exit_code != 0
    assert "already exists" in result.output


def test_auto_generate_reports_missing_qualified_professor(app):
    with app.app_context():
        term = system.Term(name="Fall")
        course = system.Course(code="CS101", title="Programming")
        section = system.Section(name="A")
        system.db.session.add_all([term, course, section])
        system.db.session.commit()
        section.section_subjects.append(
            system.SectionSubject(course=course)
        )
        system.db.session.commit()

        result = system.auto_generate(term.id)

        assert result.assigned == 0
        assert result.unassigned == []
        assert result.missing_instructors == ["CS101/A"]
        assert system.Schedule.query.filter_by(term_id=term.id).count() == 0


def test_conflict_check_ignores_other_terms(app):
    with app.app_context():
        term = system.Term(name="Fall")
        other_term = system.Term(name="Spring")
        course = system.Course(code="CS101", title="Programming")
        professor = system.Faculty(name="Ada")
        room = system.Room(code="R1", capacity=40)
        section = system.Section(name="A")
        system.db.session.add_all([term, other_term, course, professor, room, section])
        system.db.session.commit()
        scheduled = system.Schedule(
            term_id=other_term.id, course_id=course.id, faculty_id=professor.id,
            section_id=section.id, room_id=room.id, day="Mon",
            start_time=time(9), end_time=time(11),
        )
        system.db.session.add(scheduled)
        system.db.session.commit()

        candidate = {
            "term_id": term.id, "day": "Mon",
            "start_time": time(9), "end_time": time(11),
            "faculty_id": professor.id, "room_id": room.id,
            "section_id": section.id,
        }

        assert system.check_schedule_conflicts(candidate, [scheduled]) == []


def test_schedule_and_availability_pages_render_for_admin(app):
    client = app.test_client()
    with app.app_context():
        admin = system.User(username="admin", password_hash="unused", role="Admin")
        system.db.session.add(admin)
        system.db.session.commit()
        admin_id = admin.id
    with client.session_transaction() as session:
        session["_user_id"] = str(admin_id)
        session["_fresh"] = True

    assert client.get("/schedules").status_code == 200
    assert client.get("/availability").status_code == 200


def test_manage_sections_subject_assignment_does_not_require_year_level(app):
    client = app.test_client()
    with app.app_context():
        section = system.Section(name="BSCS 1A")
        course = system.Course(code="CS101", title="Programming")
        admin = system.User(username="admin", password_hash="unused", role="Admin")
        system.db.session.add_all([section, course, admin])
        system.db.session.commit()
        section_id, course_id, admin_id = section.id, course.id, admin.id
    with client.session_transaction() as session:
        session["_user_id"] = str(admin_id)
        session["_fresh"] = True

    page = client.get("/manage-sections")
    assert page.status_code == 200
    assert b"Year Level" not in page.data

    response = client.post("/manage-sections/subjects/add", data={
        "section_id": str(section_id),
        "course_id": str(course_id),
    })

    assert response.status_code == 302
    assignment = system.db.session.get(system.SectionSubject, (section_id, course_id))
    assert assignment is not None
    assert assignment.year_level == 1


def test_dashboard_shows_schedule_tables_for_each_resource(app):
    client = app.test_client()
    rendered = []

    def capture_dashboard(sender, template, context, **extra):
        if template.name == "index.html":
            rendered.append(context)

    with app.app_context():
        term = system.Term(name="Fall")
        course = system.Course(code="CS101", title="Programming")
        professor = system.Faculty(name="Ada")
        room = system.Room(code="R1", capacity=40)
        section = system.Section(name="A")
        admin = system.User(username="admin", password_hash="unused", role="Admin")
        system.db.session.add_all([term, course, professor, room, section, admin])
        system.db.session.commit()
        schedule = system.Schedule(
            term_id=term.id, course_id=course.id, faculty_id=professor.id,
            section_id=section.id, room_id=room.id, day="Mon",
            start_time=time(7), end_time=time(8),
        )
        system.db.session.add(schedule)
        system.db.session.commit()
        admin_id = admin.id
        resource_ids = {
            "faculty_id": professor.id,
            "section_id": section.id,
            "room_id": room.id,
        }

    with client.session_transaction() as session:
        session["_user_id"] = str(admin_id)
        session["_fresh"] = True

    template_rendered.connect(capture_dashboard, system.app)
    try:
        response = client.get("/")
        assert b'id="overall-timetable"' in response.data
        assert b'href="/export-schedule"' in response.data
        for parameter, resource_id, schedule_list in (
            ("faculty_id", resource_ids["faculty_id"], "faculty_schedules"),
            ("section_id", resource_ids["section_id"], "section_schedules"),
            ("room_id", resource_ids["room_id"], "room_schedules"),
        ):
            response = client.get(f"/?{parameter}={resource_id}")
            assert response.status_code == 200
            assert f"/export-schedule?{parameter}={resource_id}".encode() in response.data
            assert len(rendered[-1][schedule_list]) == 1
            assert b'id="resource-schedule-timetable"' in response.data
            assert b'id="overall-timetable"' not in response.data
            assert b">Time</th>" in response.data
            assert b">Mon</th>" in response.data
            assert b"4:00 PM" in response.data
            assert b"5:00 PM" not in response.data
        assert system.TIME_SLOTS[-1][1] == time(16)
    finally:
        template_rendered.disconnect(capture_dashboard, system.app)


def test_export_schedule_requires_login(app):
    assert app.test_client().get("/export-schedule").status_code == 302


def test_export_schedule_pdf_matches_selected_professor_section_and_room(app):
    client = app.test_client()
    rendered = {}

    def capture_export(sender, template, context, **extra):
        if template.name == "schedule_export.html":
            rendered.update(context)

    with app.app_context():
        term = system.Term(name="Fall")
        course_a = system.Course(code="CS101", title="Programming")
        course_b = system.Course(code="CS202", title="Algorithms")
        professor_a = system.Faculty(name="Ada")
        professor_b = system.Faculty(name="Grace")
        room_a = system.Room(code="R1", capacity=40)
        room_b = system.Room(code="R2", capacity=40)
        section_a = system.Section(name="A", size=30)
        section_b = system.Section(name="B", size=30)
        user = system.User(username="export-user", password_hash="unused")
        system.db.session.add_all([
            term, course_a, course_b, professor_a, professor_b,
            room_a, room_b, section_a, section_b, user,
        ])
        system.db.session.commit()
        system.db.session.add_all([
            system.Schedule(
                term_id=term.id, course_id=course_a.id,
                faculty_id=professor_a.id, section_id=section_a.id,
                room_id=room_a.id, day="Mon",
                start_time=time(9), end_time=time(10),
            ),
            system.Schedule(
                term_id=term.id, course_id=course_b.id,
                faculty_id=professor_b.id, section_id=section_b.id,
                room_id=room_b.id, day="Tue",
                start_time=time(10), end_time=time(11),
            ),
        ])
        system.db.session.commit()
        user_id = user.id
        filters = [
            (
                "faculty_id", professor_a.id, "professorSchedule.pdf",
                "CS101", "Mon", "09:00",
            ),
            (
                "section_id", section_b.id, "sectionSchedule.pdf",
                "CS202", "Tue", "10:00",
            ),
            (
                "room_id", room_a.id, "roomSchedule.pdf",
                "CS101", "Mon", "09:00",
            ),
        ]

    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True

    template_rendered.connect(capture_export, app)
    try:
        for filter_name, filter_id, filename, course_code, day, start_time in filters:
            response = client.get(
                f"/export-schedule?{filter_name}={filter_id}"
            )

            assert response.status_code == 200
            assert response.mimetype == "application/pdf"
            assert response.headers["Content-Disposition"].endswith(filename)
            assert response.data.startswith(b"%PDF")
            pdf_reader = PdfReader(BytesIO(response.data))
            assert len(pdf_reader.pages) == 1
            text = pdf_reader.pages[0].extract_text()
            headings = [
                "Laguna State Polytechnic University",
                "College of Computer Studies",
                "CLASS SCHEDULE",
            ]
            assert all(heading in text for heading in headings)
            assert [text.index(heading) for heading in headings] == sorted(
                text.index(heading) for heading in headings
            )
            text_positions = {}

            def capture_positions(value, matrix, text_matrix, font, font_size):
                if "CLASS SCHEDULE" in value:
                    text_positions["title"] = (matrix, text_matrix)
                if value.strip() == "Time":
                    text_positions["table"] = (matrix, text_matrix)

            pdf_reader.pages[0].extract_text(visitor_text=capture_positions)
            title_y = text_positions["title"][0][5]
            table_y = text_positions["table"][0][5]
            assert title_y - table_y >= 50
            exported_grid = rendered["grid"]
            assert len(exported_grid) == 1
            assert exported_grid[(day, start_time)].course.code == course_code

        response = client.get("/export-schedule")
        assert response.status_code == 200
        assert response.headers["Content-Disposition"].endswith("schedule.pdf")
        assert len(PdfReader(BytesIO(response.data)).pages) == 1
        assert len(rendered["grid"]) == 2

        with app.app_context():
            term = system.Term.query.first()
            course = system.Course.query.filter_by(code="CS101").first()
            professor = system.Faculty.query.filter_by(name="Ada").first()
            room = system.Room.query.filter_by(code="R1").first()
            section = system.Section.query.filter_by(name="A").first()
            professor.name = "Professor " + "Ada " * 10
            section.name = "Section " + "A " * 20
            room.code = "Room " + "1 " * 5
            existing_slots = {("Mon", time(9)), ("Tue", time(10))}
            system.db.session.add_all([
                system.Schedule(
                    term_id=term.id, course_id=course.id,
                    faculty_id=professor.id, section_id=section.id,
                    room_id=room.id, day=day,
                    start_time=start, end_time=end,
                )
                for day in system.DAYS
                for start, end in system.TIME_SLOTS
                if (day, start) not in existing_slots
            ])
            system.db.session.commit()

        response = client.get("/export-schedule")
        assert response.status_code == 200
        dense_pdf = PdfReader(BytesIO(response.data))
        assert len(dense_pdf.pages) == 1
        assert len(rendered["grid"]) == len(system.DAYS) * len(system.TIME_SLOTS)
    finally:
        template_rendered.disconnect(capture_export, app)


def test_schedules_page_filters_by_selected_professor(app):
    client = app.test_client()
    with app.app_context():
        term = system.Term(name="Fall")
        course_a = system.Course(code="CS101", title="Programming")
        course_b = system.Course(code="CS202", title="Algorithms")
        professor_a = system.Faculty(name="Ada")
        professor_b = system.Faculty(name="Grace")
        room = system.Room(code="R1", capacity=40)
        section_a = system.Section(name="A")
        section_b = system.Section(name="B")
        admin = system.User(username="admin", password_hash="unused", role="Admin")
        system.db.session.add_all([
            term, course_a, course_b, professor_a, professor_b, room,
            section_a, section_b, admin,
        ])
        system.db.session.commit()
        system.db.session.add_all([
            system.Schedule(
                term_id=term.id, course_id=course_a.id, faculty_id=professor_a.id,
                section_id=section_a.id, room_id=room.id, day="Mon",
                start_time=time(7), end_time=time(8),
            ),
            system.Schedule(
                term_id=term.id, course_id=course_b.id, faculty_id=professor_b.id,
                section_id=section_b.id, room_id=room.id, day="Tue",
                start_time=time(7), end_time=time(8),
            ),
        ])
        system.db.session.commit()
        professor_id = professor_a.id
        admin_id = admin.id
    with client.session_transaction() as session:
        session["_user_id"] = str(admin_id)
        session["_fresh"] = True

    response = client.get(f"/schedules?faculty_id={professor_id}")

    assert response.status_code == 200
    assert b"CS101" in response.data
    assert b"CS202" not in response.data
    assert b"All professors" not in response.data


def test_unavailability_is_limited_to_school_hours(app):
    client = app.test_client()
    with app.app_context():
        professor = system.Faculty(name="Ada")
        admin = system.User(username="admin", password_hash="unused", role="Admin")
        system.db.session.add_all([professor, admin])
        system.db.session.commit()
        professor_id = professor.id
        admin_id = admin.id
    with client.session_transaction() as session:
        session["_user_id"] = str(admin_id)
        session["_fresh"] = True

    response = client.post("/availability/add", data={
        "faculty_id": professor_id,
        "day": "Mon",
        "start_time": "16:00",
        "end_time": "17:00",
    })

    assert response.status_code == 302
    assert system.Unavailability.query.count() == 0


def test_generate_schedules_only_selected_professor(app):
    client = app.test_client()
    with app.app_context():
        term = system.Term(name="Fall")
        course_a = system.Course(code="CS101", title="Programming")
        course_b = system.Course(code="CS202", title="Algorithms")
        professor_a = system.Faculty(name="Ada")
        professor_b = system.Faculty(name="Grace")
        room = system.Room(code="R1", capacity=40)
        section = system.Section(name="A")
        admin = system.User(username="admin", password_hash="unused", role="Admin")
        system.db.session.add_all([
            term, course_a, course_b, professor_a, professor_b, room, section, admin,
        ])
        system.db.session.commit()
        professor_a.subjects.append(course_a)
        professor_b.subjects.extend([course_a, course_b])
        section.section_subjects.extend([
            system.SectionSubject(course=course_a),
            system.SectionSubject(course=course_b),
        ])
        system.db.session.commit()
        term_id = term.id
        professor_id = professor_a.id
        admin_id = admin.id
    with client.session_transaction() as session:
        session["_user_id"] = str(admin_id)
        session["_fresh"] = True

    response = client.post("/generate", data={})

    assert response.status_code == 302
    assert system.Schedule.query.filter_by(term_id=term_id).count() == 0

    response = client.post("/generate", data={"faculty_id": str(professor_id)})

    assert response.status_code == 302
    assert response.location.endswith(f"/schedules?faculty_id={professor_id}")
    schedules = system.Schedule.query.filter_by(term_id=term_id).all()
    assert len(schedules) == 1
    assert schedules[0].course.code == "CS101"
    assert schedules[0].faculty_id == professor_id


def test_generate_falls_back_to_another_qualified_professor(app):
    client = app.test_client()
    with app.app_context():
        term = system.Term(name="Fall")
        course = system.Course(code="CS101", title="Programming", units=1)
        professor_a = system.Faculty(name="Ada")
        professor_b = system.Faculty(name="Grace")
        room = system.Room(code="R1", capacity=40)
        section = system.Section(name="A")
        admin = system.User(username="admin", password_hash="unused", role="Admin")
        system.db.session.add_all([
            term, course, professor_a, professor_b, room, section, admin,
        ])
        system.db.session.commit()
        professor_a.subjects.append(course)
        professor_b.subjects.append(course)
        section.section_subjects.append(system.SectionSubject(course=course))
        system.db.session.add_all([
            system.Unavailability(
                faculty_id=professor_a.id, day=day,
                start_time=system.SCHOOL_START, end_time=system.SCHOOL_END,
            )
            for day in system.DAYS
        ])
        system.db.session.commit()
        professor_a_id, professor_b_id = professor_a.id, professor_b.id
        admin_id = admin.id
    with client.session_transaction() as session:
        session["_user_id"] = str(admin_id)
        session["_fresh"] = True

    response = client.post(
        "/generate",
        data={"faculty_id": str(professor_a_id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"handed off to other qualified professors" in response.data
    schedules = system.Schedule.query.all()
    assert len(schedules) == 1
    assert schedules[0].faculty_id == professor_b_id
