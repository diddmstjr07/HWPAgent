import tempfile
import unittest
import sqlite3
from datetime import date
from pathlib import Path

from database import Database
from models import (
    User,
    calculate_admission_year_from_student_number,
    calculate_current_grade,
    get_academic_year,
    parse_student_number,
    should_update_student_number,
)


class AcademicYearTests(unittest.TestCase):
    def test_grade_changes_on_march_first(self):
        self.assertEqual(get_academic_year(date(2026, 2, 28)), 2025)
        self.assertEqual(calculate_current_grade(2025, date(2026, 2, 28)), 1)
        self.assertEqual(get_academic_year(date(2026, 3, 1)), 2026)
        self.assertEqual(calculate_current_grade(2025, date(2026, 3, 1)), 2)

    def test_out_of_school_range_returns_none(self):
        self.assertIsNone(calculate_current_grade(2022, date(2026, 7, 1)))

    def test_student_number_maps_to_grade_class_number_and_admission_year(self):
        parsed = parse_student_number('2412')
        self.assertEqual(parsed['grade'], 2)
        self.assertEqual(parsed['classroom'], 4)
        self.assertEqual(parsed['number'], 12)
        self.assertEqual(
            calculate_admission_year_from_student_number('2412', date(2026, 7, 21)),
            2025,
        )

    def test_student_number_rejects_invalid_components(self):
        self.assertIsNone(parse_student_number('0412'))
        self.assertIsNone(parse_student_number('2012'))
        self.assertIsNone(parse_student_number('2400'))

    def test_number_requires_update_after_next_march(self):
        self.assertFalse(
            should_update_student_number('2412', 2026, 2025, date(2027, 2, 28))
        )
        self.assertTrue(
            should_update_student_number('2412', 2026, 2025, date(2027, 3, 1))
        )

    def test_user_payload_contains_derived_grade_without_exposing_number(self):
        user = User(
            'student',
            'student@example.com',
            '학생',
            admission_year=2025,
            student_number='2412',
            student_number_academic_year=2026,
        )
        payload = user.to_dict()
        self.assertEqual(payload['admission_year'], 2025)
        self.assertEqual(payload['current_grade'], calculate_current_grade(2025))
        self.assertTrue(payload['has_student_number'])
        self.assertNotIn('student_number', payload)


class AdmissionYearDatabaseTests(unittest.TestCase):
    def test_student_number_columns_are_migrated_and_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / 'test.db'
            connection = sqlite3.connect(database_path)
            connection.execute('''
                CREATE TABLE users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    picture TEXT,
                    password_hash TEXT,
                    created_at TEXT NOT NULL,
                    last_login TEXT
                )
            ''')
            connection.commit()
            connection.close()

            database = Database(str(database_path))
            user = database.create_local_user(
                'student@example.com',
                'hashed-password',
                '학생',
                admission_year=2025,
                student_number='2412',
                student_number_academic_year=2026,
            )
            self.assertEqual(user.admission_year, 2025)
            self.assertEqual(database.get_user(user.id).admission_year, 2025)
            self.assertEqual(database.get_user(user.id).student_number, '2412')

            updated = database.update_user_student_number(user.id, '3511', 2025, 2027)
            self.assertEqual(updated.student_number, '3511')
            self.assertEqual(updated.admission_year, 2025)
            self.assertEqual(updated.student_number_academic_year, 2027)

            preserved = database.create_or_update_user(
                user.id,
                user.email,
                user.name,
                user.picture,
            )
            self.assertEqual(preserved.admission_year, 2025)
            self.assertEqual(preserved.student_number, '3511')

    def test_reminder_is_due_once_per_academic_year(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(str(Path(temp_dir) / 'test.db'))
            user = database.create_local_user(
                'student@example.com',
                'hashed-password',
                '학생',
                admission_year=2025,
                student_number='2412',
                student_number_academic_year=2026,
            )

            due = database.get_due_student_number_reminders(2027)
            self.assertEqual([item.id for item in due], [user.id])
            self.assertTrue(database.claim_student_number_reminder(user.id, 2027))
            self.assertFalse(database.claim_student_number_reminder(user.id, 2027))
            database.complete_student_number_reminder(user.id, 2027)
            self.assertEqual(database.get_due_student_number_reminders(2027), [])


if __name__ == '__main__':
    unittest.main()
