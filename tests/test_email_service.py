import os
import unittest
from unittest.mock import patch

from modules.email_service import build_student_number_update_message


class StudentNumberEmailTests(unittest.TestCase):
    def test_message_contains_grade_example_and_update_link(self):
        with patch.dict(
            os.environ,
            {
                'SMTP_FROM_EMAIL': 'noreply@example.com',
                'SMTP_FROM_NAME': 'DOC Agent',
            },
            clear=False,
        ):
            message = build_student_number_update_message(
                recipient_email='student@example.com',
                recipient_name='학생',
                academic_year=2027,
                current_grade=3,
                update_url='https://example.com/student-number/update?token=signed',
            )

        self.assertIn('2027학년도', message['Subject'])
        body = message.get_body(preferencelist=('plain',)).get_content()
        self.assertIn('3학년', body)
        self.assertIn('3412 = 3학년 4반 12번', body)
        self.assertIn('token=signed', body)


if __name__ == '__main__':
    unittest.main()
