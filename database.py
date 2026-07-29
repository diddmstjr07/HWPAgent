"""
SQLite 데이터베이스 매니저
"""
import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from models import User, DocumentHistory, ChatSession, RiroDocument
from werkzeug.security import generate_password_hash, check_password_hash

DEFAULT_ADMIN_ID = os.getenv("ADMIN_BOOTSTRAP_ID", "diddmstjr")
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_BOOTSTRAP_PASSWORD", "diddmstjrdiddmstjrCOM*********")
DEFAULT_ADMIN_NAME = os.getenv("ADMIN_BOOTSTRAP_NAME", "Admin")

class Database:
    def __init__(self, db_path='hwp_agent.db'):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # WAL 모드 활성화 (동시성 향상)
        conn.execute('PRAGMA journal_mode=WAL')
        return conn
    
    def init_database(self):
        """데이터베이스 초기화"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            
            # 사용자 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    picture TEXT,
                    password_hash TEXT,
                    admission_year INTEGER,
                    student_number TEXT,
                    student_number_academic_year INTEGER,
                    student_number_updated_at TEXT,
                    created_at TEXT NOT NULL,
                    last_login TEXT
                )
            ''')
            # legacy DB 대응: 누락된 컬럼을 추가
            self._ensure_column(cursor, 'users', 'password_hash', 'TEXT')
            self._ensure_column(cursor, 'users', 'last_login', 'TEXT')
            self._ensure_column(cursor, 'users', 'admission_year', 'INTEGER')
            self._ensure_column(cursor, 'users', 'student_number', 'TEXT')
            self._ensure_column(cursor, 'users', 'student_number_academic_year', 'INTEGER')
            self._ensure_column(cursor, 'users', 'student_number_updated_at', 'TEXT')
            # ChatGPT(Codex) 계정 로그인 식별자. 원문 이메일이 아니라 HMAC을 키로 쓴다.
            self._ensure_column(cursor, 'users', 'codex_account_hash', 'TEXT')
            cursor.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_codex_account
                ON users(codex_account_hash) WHERE codex_account_hash IS NOT NULL
            ''')
            
            # 문서 히스토리 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS document_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # 인덱스 생성
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_document_user 
                ON document_history(user_id, created_at DESC)
            ''')

            # 리로스쿨 문서 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS riro_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    riro_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    image_urls TEXT,
                    created_at TEXT NOT NULL
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_riro_documents
                ON riro_documents(riro_id, created_at DESC)
            ''')

            # 채팅 세션 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    messages TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_user
                ON chat_sessions(user_id, updated_at DESC)
            ''')

            # 사이드바 HISTORY는 대화를 폴더로 나눠 보여준다.
            # folder: '설계'(연구 서사) / '실험'(과목별 실험) / NULL(그 밖의 대화)
            # plan_id: 실험 대화가 어느 과목 플랜의 것인지.
            self._ensure_column(cursor, 'chat_sessions', 'folder', 'TEXT')
            self._ensure_column(cursor, 'chat_sessions', 'plan_id', 'INTEGER')

            # 사용자 분석 이벤트 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS analytics_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    user_id TEXT,
                    session_id TEXT,
                    path TEXT,
                    referrer TEXT,
                    ip TEXT,
                    user_agent TEXT,
                    status_code INTEGER,
                    created_at TEXT NOT NULL
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_analytics_events_type_time
                ON analytics_events(event_type, created_at)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_analytics_events_path
                ON analytics_events(path)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_analytics_events_session
                ON analytics_events(session_id)
            ''')

            # 학년 변경 후 학번 갱신 이메일 발송 이력
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS student_number_reminders (
                    user_id TEXT NOT NULL,
                    academic_year INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_attempt_at TEXT,
                    sent_at TEXT,
                    error TEXT,
                    PRIMARY KEY (user_id, academic_year),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')

            self._init_research_narrative(cursor)
            self._seed_admin_user(cursor)

            conn.commit()
        finally:
            conn.close()

    def _init_research_narrative(self, cursor):
        """연구 서사(Research Narrative) 관련 테이블을 생성합니다."""
        # Phase 1: 심층 프로파일링. 사용자당 1개이며 진로 탐색 플랫폼 확장을 위해 extra를 둔다.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS student_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL UNIQUE,
                interests TEXT,
                problem_statement TEXT,
                aspired_track TEXT,
                strength_subjects TEXT,
                activity_history TEXT,
                interview_state TEXT,
                extra TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')

        # Phase 2: 3년 테마 후보. is_selected=1인 행이 확정 테마다.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS research_themes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                profile_id INTEGER,
                title TEXT NOT NULL,
                rationale TEXT,
                expansion TEXT,
                differentiation TEXT,
                is_selected INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (profile_id) REFERENCES student_profiles(id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_research_themes_user
            ON research_themes(user_id, updated_at DESC)
        ''')

        # Phase 3: 연구 프레임
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS research_frameworks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                theme_id INTEGER,
                core_question TEXT,
                sub_areas TEXT,
                final_destination TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (theme_id) REFERENCES research_themes(id)
            )
        ''')

        # Phase 3 분해: 학년별 계획. 한 프레임 안에서 학년은 유일하다.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS grade_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                framework_id INTEGER,
                grade INTEGER NOT NULL,
                goal TEXT,
                anchor_project TEXT,
                curriculum_alignment TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (framework_id, grade),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (framework_id) REFERENCES research_frameworks(id)
            )
        ''')

        # Phase 5: 과목별 세특 플랜
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subject_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                grade_plan_id INTEGER,
                subject TEXT NOT NULL,
                subject_uid TEXT,
                approach TEXT,
                approach_rationale TEXT,
                area_name TEXT,
                standard_codes TEXT,
                motivation TEXT,
                activity_design TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (grade_plan_id) REFERENCES grade_plans(id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_subject_plans_grade
            ON subject_plans(grade_plan_id, subject)
        ''')
        # 실험은 설계에서 끝나지 않는다. 학생이 Agent와 함께 진행한 대화방과
        # 그 끝에서 만들어진 보고서 파일을 세특에 붙여 둔다.
        # experiment_status: NULL(시작 전) / 'running'(진행 중) / 'done'(학습 완료)
        self._ensure_column(cursor, 'subject_plans', 'experiment_chat_id', 'TEXT')
        self._ensure_column(cursor, 'subject_plans', 'experiment_status', 'TEXT')
        self._ensure_column(cursor, 'subject_plans', 'report_file', 'TEXT')

        # 연구 서사 대화 기록. 새로고침해도 이어서 보이도록 서버에 남긴다.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS research_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                action TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_research_messages_user
            ON research_messages(user_id, id)
        ''')
        # 폴더가 생기기 전에 만들어진 실험 대화방에 꼬리표를 붙인다.
        # 이걸 하지 않으면 예전 방이 '폴더 없는 일반 대화'로 보여 실험이 열리지 않는다.
        cursor.execute('''
            UPDATE chat_sessions
               SET folder = '실험',
                   plan_id = (SELECT sp.id FROM subject_plans sp
                               WHERE sp.experiment_chat_id = chat_sessions.id)
             WHERE folder IS NULL
               AND id IN (SELECT experiment_chat_id FROM subject_plans
                           WHERE experiment_chat_id IS NOT NULL)
        ''')

        # 설계 대화도 사이드바 HISTORY에 한 칸씩 놓이므로, 어느 대화방의 말인지 붙여 둔다.
        # 값이 없는 예전 기록은 그 사용자의 첫 설계 대화방에 속한 것으로 본다.
        self._ensure_column(cursor, 'research_messages', 'session_id', 'TEXT')

        # Agentic 실행 로그
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                subject_plan_id INTEGER,
                grade_plan_id INTEGER,
                run_type TEXT NOT NULL DEFAULT 'experiment',
                status TEXT NOT NULL DEFAULT 'running',
                steps TEXT,
                report_markdown TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (subject_plan_id) REFERENCES subject_plans(id),
                FOREIGN KEY (grade_plan_id) REFERENCES grade_plans(id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_agent_runs_user
            ON agent_runs(user_id, created_at DESC)
        ''')

        # CurriculumDB: 2022 개정 교육과정 조회용 정적 데이터.
        # 코드도 접두사도 전국 단위로 유일하지 않아 '별책:코드'를 기본키로 쓴다.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS curriculum_subjects (
                subject_uid TEXT PRIMARY KEY,
                code_prefix TEXT NOT NULL,
                subject TEXT NOT NULL,
                subject_type TEXT,
                curriculum_area TEXT,
                volume INTEGER NOT NULL,
                grade_band TEXT,
                areas TEXT,
                standard_count INTEGER NOT NULL DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_curriculum_subjects_lookup
            ON curriculum_subjects(grade_band, subject_type, subject)
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS curriculum_standards (
                uid TEXT PRIMARY KEY,
                code TEXT NOT NULL,
                code_prefix TEXT NOT NULL,
                subject_uid TEXT NOT NULL,
                subject TEXT NOT NULL,
                subject_type TEXT,
                curriculum_area TEXT,
                volume INTEGER NOT NULL,
                grade_band TEXT,
                area_no TEXT,
                area_name TEXT,
                seq_no TEXT,
                statement TEXT NOT NULL,
                source_pdf TEXT,
                FOREIGN KEY (subject_uid) REFERENCES curriculum_subjects(subject_uid)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_curriculum_standards_subject
            ON curriculum_standards(subject_uid, area_no, seq_no)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_curriculum_standards_code
            ON curriculum_standards(code)
        ''')

    def _ensure_column(self, cursor, table, column, definition):
        """테이블에 특정 컬럼이 없으면 추가"""
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [row['name'] for row in cursor.fetchall()]
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _seed_admin_user(self, cursor):
        """기본 관리자 계정을 생성하거나 보강"""
        admin_id = DEFAULT_ADMIN_ID.strip()
        admin_password = DEFAULT_ADMIN_PASSWORD
        admin_name = DEFAULT_ADMIN_NAME.strip() or "Admin"

        if not admin_id or not admin_password:
            return

        cursor.execute('SELECT id, email, password_hash, name FROM users WHERE email = ?', (admin_id,))
        row = cursor.fetchone()
        password_hash = generate_password_hash(admin_password)
        now = datetime.now().isoformat()

        if row:
            existing_hash = row['password_hash'] or ''
            needs_update = not existing_hash or not check_password_hash(existing_hash, admin_password)
            if needs_update:
                cursor.execute(
                    'UPDATE users SET password_hash = ?, name = COALESCE(NULLIF(name, \'\'), ?), last_login = COALESCE(last_login, ?) WHERE id = ?',
                    (password_hash, admin_name, now, row['id'])
                )
            return

        admin_user_id = f"admin_{admin_id}"
        cursor.execute('''
            INSERT INTO users (id, email, name, picture, password_hash, created_at, last_login)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (admin_user_id, admin_id, admin_name, None, password_hash, now, now))
    
    # ============ User 관련 메서드 ============
    
    def get_user(self, user_id):
        """사용자 조회"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
            row = cursor.fetchone()
        finally:
            conn.close()
        
        if row:
            return User(
                id=row['id'],
                email=row['email'],
                name=row['name'],
                picture=row['picture'],
                password_hash=row['password_hash'],
                admission_year=row['admission_year'],
                student_number=row['student_number'],
                student_number_academic_year=row['student_number_academic_year']
            )
        return None
    
    def get_user_by_email(self, email):
        """이메일로 사용자 조회"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
            row = cursor.fetchone()
        finally:
            conn.close()
        
        if row:
            return User(
                id=row['id'],
                email=row['email'],
                name=row['name'],
                picture=row['picture'],
                password_hash=row['password_hash'],
                admission_year=row['admission_year'],
                student_number=row['student_number'],
                student_number_academic_year=row['student_number_academic_year']
            )
        return None

    def get_user_credentials(self, email):
        """이메일로 사용자 계정 조회 (패스워드 포함)"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
            row = cursor.fetchone()
        finally:
            conn.close()

        if not row:
            return None
        return {
            'id': row['id'],
            'email': row['email'],
            'name': row['name'],
            'picture': row['picture'],
            'password_hash': row['password_hash'],
            'admission_year': row['admission_year'],
            'student_number': row['student_number'],
            'student_number_academic_year': row['student_number_academic_year'],
            'created_at': row['created_at'],
            'last_login': row['last_login']
        }
    
    def create_or_update_user(
        self,
        user_id,
        email,
        name,
        picture,
        password_hash=None,
        last_login=None,
        admission_year=None,
        student_number=None,
        student_number_academic_year=None,
    ):
        """사용자 생성 또는 업데이트"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            
            # 기존 사용자 확인
            cursor.execute('SELECT id FROM users WHERE id = ?', (user_id,))
            existing = cursor.fetchone()
            
            if existing:
                # 업데이트
                cursor.execute('''
                    UPDATE users 
                    SET email = ?, name = ?, picture = ?, password_hash = COALESCE(?, password_hash),
                        last_login = COALESCE(?, last_login), admission_year = COALESCE(?, admission_year),
                        student_number = COALESCE(?, student_number),
                        student_number_academic_year = COALESCE(?, student_number_academic_year),
                        student_number_updated_at = CASE
                            WHEN ? IS NOT NULL THEN ?
                            ELSE student_number_updated_at
                        END
                    WHERE id = ?
                ''', (
                    email, name, picture, password_hash, last_login, admission_year,
                    student_number, student_number_academic_year,
                    student_number, datetime.now().isoformat(), user_id
                ))
            else:
                # 신규 생성
                cursor.execute('''
                    INSERT INTO users (
                        id, email, name, picture, password_hash, admission_year,
                        student_number, student_number_academic_year, student_number_updated_at,
                        created_at, last_login
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id, email, name, picture, password_hash, admission_year,
                    student_number, student_number_academic_year,
                    datetime.now().isoformat() if student_number else None,
                    datetime.now().isoformat(), last_login
                ))
            
            conn.commit()
        finally:
            conn.close()
        
        # 기존 값이 COALESCE로 보존된 경우까지 반영한 최신 레코드를 반환합니다.
        return self.get_user(user_id)

    def create_local_user(
        self,
        email,
        password_hash,
        name=None,
        picture=None,
        admission_year=None,
        student_number=None,
        student_number_academic_year=None,
    ):
        """로컬 로그인용 사용자 생성"""
        user_id = f"user_{uuid4().hex}"
        now = datetime.now().isoformat()
        display_name = name or email.split('@')[0]

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (
                    id, email, name, picture, password_hash, admission_year,
                    student_number, student_number_academic_year, student_number_updated_at,
                    created_at, last_login
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, email, display_name, picture, password_hash, admission_year,
                student_number, student_number_academic_year,
                now if student_number else None, now, now
            ))
            conn.commit()
        finally:
            conn.close()
        return User(
            id=user_id,
            email=email,
            name=display_name,
            picture=picture,
            password_hash=password_hash,
            admission_year=admission_year,
            student_number=student_number,
            student_number_academic_year=student_number_academic_year
        )

    def get_or_create_codex_user(self, account_hash, email=None, name=None):
        """ChatGPT 계정 해시로 사용자를 찾고, 없으면 만듭니다.

        로그인에는 쓰지 마세요. ChatGPT 연결은 사용 한도를 빌려오는 것일 뿐이고
        앱 신원은 이메일/비밀번호 로그인이 정합니다. 예전에 이 함수로 찾은 사용자를
        세션에 심었더니, 같은 ChatGPT 계정을 연결한 사람이 남의 설계·실험·보고서를
        그대로 열어볼 수 있었습니다. 지금은 테스트에서 사용자를 만들 때만 씁니다.

        같은 이메일로 이미 가입한 계정이 있으면 새로 만들지 않고 그 계정에 연결합니다.
        학번·입학연도는 ChatGPT 계정에 없는 정보라 비워 두고, 기존 학번 입력 흐름이 채웁니다.
        """
        if not account_hash:
            return None

        now = datetime.now().isoformat()
        normalized_email = (email or '').strip().lower() or None

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            row = cursor.execute(
                'SELECT id FROM users WHERE codex_account_hash = ?', (account_hash,)
            ).fetchone()

            if not row and normalized_email:
                # 이메일/비밀번호로 이미 가입한 사용자가 같은 계정으로 들어온 경우 연결한다.
                row = cursor.execute(
                    'SELECT id FROM users WHERE email = ?', (normalized_email,)
                ).fetchone()
                if row:
                    cursor.execute(
                        'UPDATE users SET codex_account_hash = ?, last_login = ? WHERE id = ?',
                        (account_hash, now, row['id'])
                    )

            if row:
                cursor.execute('UPDATE users SET last_login = ? WHERE id = ?', (now, row['id']))
                conn.commit()
                return self.get_user(row['id'])

            user_id = f"codex_{account_hash[:24]}"
            # 이메일을 못 받은 경우에도 UNIQUE NOT NULL 제약을 지키도록 대체 주소를 쓴다.
            stored_email = normalized_email or f'{user_id}@codex.local'
            display_name = (name or '').strip() or (
                normalized_email.split('@')[0] if normalized_email else 'ChatGPT 사용자'
            )
            cursor.execute('''
                INSERT INTO users (id, email, name, picture, password_hash,
                                   codex_account_hash, created_at, last_login)
                VALUES (?, ?, ?, NULL, NULL, ?, ?, ?)
            ''', (user_id, stored_email, display_name, account_hash, now, now))
            conn.commit()
            return self.get_user(user_id)
        finally:
            conn.close()

    def update_user_admission_year(self, user_id, admission_year):
        """기존 사용자의 입학연도를 갱신합니다."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE users SET admission_year = ? WHERE id = ?',
                (int(admission_year), user_id)
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_user(user_id)

    def update_user_student_number(self, user_id, student_number, admission_year, academic_year):
        """학번과 해당 학번이 유효한 학사연도를 함께 저장합니다."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE users
                SET student_number = ?, admission_year = ?,
                    student_number_academic_year = ?, student_number_updated_at = ?
                WHERE id = ?
                ''',
                (
                    str(student_number),
                    int(admission_year),
                    int(academic_year),
                    datetime.now().isoformat(),
                    user_id,
                )
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_user(user_id)

    def get_due_student_number_reminders(self, academic_year):
        """현재 학년도에 갱신 안내가 필요한 재학생을 조회합니다."""
        academic_year = int(academic_year)
        retry_before = (datetime.now() - timedelta(minutes=30)).isoformat()
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT users.*
                FROM users
                LEFT JOIN student_number_reminders AS reminder
                  ON reminder.user_id = users.id
                 AND reminder.academic_year = ?
                WHERE users.student_number IS NOT NULL
                  AND users.student_number_academic_year IS NOT NULL
                  AND users.student_number_academic_year < ?
                  AND users.admission_year BETWEEN ? AND ?
                  AND (
                    reminder.status IS NULL
                    OR reminder.status = 'failed'
                    OR (reminder.status = 'pending' AND reminder.last_attempt_at < ?)
                  )
                ORDER BY users.id
                ''',
                (
                    academic_year,
                    academic_year,
                    academic_year - 2,
                    academic_year,
                    retry_before,
                )
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [
            User(
                id=row['id'],
                email=row['email'],
                name=row['name'],
                picture=row['picture'],
                password_hash=row['password_hash'],
                admission_year=row['admission_year'],
                student_number=row['student_number'],
                student_number_academic_year=row['student_number_academic_year'],
            )
            for row in rows
        ]

    def claim_student_number_reminder(self, user_id, academic_year):
        """동일 사용자·학사연도 이메일을 한 작업자만 발송하도록 선점합니다."""
        now = datetime.now().isoformat()
        retry_before = (datetime.now() - timedelta(minutes=30)).isoformat()
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('BEGIN IMMEDIATE')
            cursor.execute(
                '''
                INSERT INTO student_number_reminders (
                    user_id, academic_year, status, attempts, last_attempt_at
                )
                VALUES (?, ?, 'pending', 1, ?)
                ON CONFLICT(user_id, academic_year) DO UPDATE SET
                    status = 'pending',
                    attempts = student_number_reminders.attempts + 1,
                    last_attempt_at = excluded.last_attempt_at,
                    error = NULL
                WHERE student_number_reminders.status = 'failed'
                   OR (
                        student_number_reminders.status = 'pending'
                        AND student_number_reminders.last_attempt_at < ?
                   )
                ''',
                (user_id, int(academic_year), now, retry_before)
            )
            claimed = cursor.rowcount == 1
            conn.commit()
        finally:
            conn.close()
        return claimed

    def complete_student_number_reminder(self, user_id, academic_year, error=None):
        """학번 갱신 이메일 발송 결과를 기록합니다."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            if error:
                cursor.execute(
                    '''
                    UPDATE student_number_reminders
                    SET status = 'failed', error = ?, sent_at = NULL
                    WHERE user_id = ? AND academic_year = ?
                    ''',
                    (str(error)[:500], user_id, int(academic_year))
                )
            else:
                cursor.execute(
                    '''
                    UPDATE student_number_reminders
                    SET status = 'sent', error = NULL, sent_at = ?
                    WHERE user_id = ? AND academic_year = ?
                    ''',
                    (datetime.now().isoformat(), user_id, int(academic_year))
                )
            conn.commit()
        finally:
            conn.close()

    def update_last_login(self, user_id):
        """마지막 로그인 시각 업데이트"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET last_login = ? WHERE id = ?', (datetime.now().isoformat(), user_id))
            conn.commit()
        finally:
            conn.close()

    def log_analytics_event(
        self,
        event_type,
        user_id=None,
        session_id=None,
        path=None,
        referrer=None,
        ip=None,
        user_agent=None,
        status_code=None,
    ):
        """사용자 분석 이벤트 기록"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO analytics_events (
                    event_type,
                    user_id,
                    session_id,
                    path,
                    referrer,
                    ip,
                    user_agent,
                    status_code,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    event_type,
                    user_id,
                    session_id,
                    path,
                    referrer,
                    ip,
                    user_agent,
                    status_code,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def fetch_analytics_summary(self, days=14, top_limit=8, recent_limit=20):
        """관리자용 사용자 분석 요약"""
        days = max(1, int(days or 14))
        start_date = (datetime.now() - timedelta(days=days - 1)).date().isoformat()

        conn = self.get_connection()
        try:
            cursor = conn.cursor()

            def daily_counts(event_type, unique_sessions=False):
                if unique_sessions:
                    cursor.execute(
                        '''
                        SELECT date(created_at) AS day,
                               COUNT(DISTINCT COALESCE(session_id, ip)) AS count
                        FROM analytics_events
                        WHERE event_type = ? AND created_at >= ?
                        GROUP BY day
                        ORDER BY day ASC
                        ''',
                        (event_type, start_date),
                    )
                else:
                    cursor.execute(
                        '''
                        SELECT date(created_at) AS day,
                               COUNT(*) AS count
                        FROM analytics_events
                        WHERE event_type = ? AND created_at >= ?
                        GROUP BY day
                        ORDER BY day ASC
                        ''',
                        (event_type, start_date),
                    )
                return [dict(row) for row in cursor.fetchall()]

            daily_visits = daily_counts("page_view", unique_sessions=True)
            daily_signups = daily_counts("signup")
            daily_logins = daily_counts("login")

            cursor.execute(
                '''
                SELECT path, COUNT(*) AS count
                FROM analytics_events
                WHERE event_type = 'page_view' AND path IS NOT NULL AND path != ''
                GROUP BY path
                ORDER BY count DESC
                LIMIT ?
                ''',
                (top_limit,),
            )
            top_paths = [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                '''
                SELECT referrer, COUNT(*) AS count
                FROM analytics_events
                WHERE event_type = 'page_view' AND referrer IS NOT NULL AND referrer != ''
                GROUP BY referrer
                ORDER BY count DESC
                LIMIT ?
                ''',
                (top_limit,),
            )
            top_referrers = [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                '''
                SELECT path, referrer, user_id, session_id, status_code, created_at
                FROM analytics_events
                WHERE event_type = 'page_view'
                ORDER BY id DESC
                LIMIT ?
                ''',
                (recent_limit,),
            )
            recent_routes = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

        return {
            "days": days,
            "daily_visits": daily_visits,
            "daily_signups": daily_signups,
            "daily_logins": daily_logins,
            "top_paths": top_paths,
            "top_referrers": top_referrers,
            "recent_routes": recent_routes,
        }
    
    # ============ Document History 관련 메서드 ============
    
    def save_document(self, user_id, title, content):
        """문서 저장"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO document_history (user_id, title, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, title, content, now, now))
            
            doc_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()
        
        return DocumentHistory(
            id=doc_id,
            user_id=user_id,
            title=title,
            content=content,
            created_at=now,
            updated_at=now
        )
    
    def get_user_documents(self, user_id, limit=50):
        """사용자의 문서 목록 조회"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM document_history
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (user_id, limit))
            
            rows = cursor.fetchall()
        finally:
            conn.close()
        
        documents = []
        for row in rows:
            documents.append(DocumentHistory(
                id=row['id'],
                user_id=row['user_id'],
                title=row['title'],
                content=row['content'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            ))
        
        return documents
    
    def get_document(self, doc_id, user_id):
        """특정 문서 조회 (소유권 확인)"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM document_history
                WHERE id = ? AND user_id = ?
            ''', (doc_id, user_id))
            
            row = cursor.fetchone()
        finally:
            conn.close()
        
        if row:
            return DocumentHistory(
                id=row['id'],
                user_id=row['user_id'],
                title=row['title'],
                content=row['content'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
        return None
    
    def update_document(self, doc_id, user_id, title=None, content=None):
        """문서 업데이트"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            
            # 소유권 확인
            cursor.execute('SELECT id FROM document_history WHERE id = ? AND user_id = ?', (doc_id, user_id))
            if not cursor.fetchone():
                return None
            
            now = datetime.now().isoformat()
            
            if title and content:
                cursor.execute('''
                    UPDATE document_history
                    SET title = ?, content = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                ''', (title, content, now, doc_id, user_id))
            elif title:
                cursor.execute('''
                    UPDATE document_history
                    SET title = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                ''', (title, now, doc_id, user_id))
            elif content:
                cursor.execute('''
                    UPDATE document_history
                    SET content = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                ''', (content, now, doc_id, user_id))
            
            conn.commit()
        finally:
            conn.close()
        
        return self.get_document(doc_id, user_id)
    
    def delete_document(self, doc_id, user_id):
        """문서 삭제"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM document_history
                WHERE id = ? AND user_id = ?
            ''', (doc_id, user_id))
            
            deleted = cursor.rowcount > 0
            conn.commit()
        finally:
            conn.close()
        
        return deleted

    # ============ Chat Sessions ============

    def create_chat_session(self, user_id, title, messages, folder=None, plan_id=None):
        session_id = f"chat_{uuid4().hex}"
        now = datetime.now().isoformat()
        payload = json.dumps(messages or [])

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO chat_sessions
                    (id, user_id, title, messages, created_at, updated_at, folder, plan_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (session_id, user_id, title, payload, now, now, folder, plan_id))
            conn.commit()
        finally:
            conn.close()

        return ChatSession(
            id=session_id,
            user_id=user_id,
            title=title,
            messages=messages or [],
            created_at=now,
            updated_at=now,
            folder=folder,
            plan_id=plan_id
        )

    def get_chat_sessions(self, user_id, limit=50, folder=None):
        """대화 목록. folder를 주면 그 폴더의 대화만 돌려줍니다."""
        query = '''
            SELECT id, user_id, title, created_at, updated_at, folder, plan_id
            FROM chat_sessions
            WHERE user_id = ?
        '''
        params = [user_id]
        if folder is not None:
            query += ' AND folder = ?'
            params.append(folder)
        query += ' ORDER BY updated_at DESC LIMIT ?'
        params.append(limit)

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
        finally:
            conn.close()

        sessions = []
        for row in rows:
            sessions.append(ChatSession(
                id=row['id'],
                user_id=row['user_id'],
                title=row['title'],
                messages=[],
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                folder=row['folder'],
                plan_id=row['plan_id']
            ))
        return sessions

    def get_chat_session(self, session_id, user_id):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM chat_sessions
                WHERE id = ? AND user_id = ?
            ''', (session_id, user_id))
            row = cursor.fetchone()
        finally:
            conn.close()

        if not row:
            return None

        messages = []
        if row['messages']:
            try:
                messages = json.loads(row['messages'])
            except json.JSONDecodeError:
                messages = []

        return ChatSession(
            id=row['id'],
            user_id=row['user_id'],
            title=row['title'],
            messages=messages,
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            folder=row['folder'],
            plan_id=row['plan_id']
        )

    def update_chat_session(self, session_id, user_id, title=None, messages=None,
                            folder=None, plan_id=None):
        fields = []
        values = []

        if title is not None:
            fields.append('title = ?')
            values.append(title)

        if messages is not None:
            fields.append('messages = ?')
            values.append(json.dumps(messages))

        if folder is not None:
            fields.append('folder = ?')
            values.append(folder)

        if plan_id is not None:
            fields.append('plan_id = ?')
            values.append(plan_id)

        if not fields:
            return self.get_chat_session(session_id, user_id)

        now = datetime.now().isoformat()
        fields.append('updated_at = ?')
        values.append(now)
        values.extend([session_id, user_id])

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE chat_sessions
                SET {", ".join(fields)}
                WHERE id = ? AND user_id = ?
            ''', values)
            updated = cursor.rowcount > 0
            conn.commit()
        finally:
            conn.close()

        if not updated:
            return None
        return self.get_chat_session(session_id, user_id)

    def delete_chat_session(self, session_id, user_id):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM chat_sessions
                WHERE id = ? AND user_id = ?
            ''', (session_id, user_id))
            deleted = cursor.rowcount > 0
            conn.commit()
        finally:
            conn.close()
        return deleted

    # ============ RiRoSchool Documents ============

    def save_riro_document(self, riro_id, title, content, image_urls=None):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            payload = json.dumps(image_urls or [])
            cursor.execute('''
                INSERT INTO riro_documents (riro_id, title, content, image_urls, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (riro_id, title, content, payload, now))
            doc_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()
        return RiroDocument(
            id=doc_id,
            riro_id=riro_id,
            title=title,
            content=content,
            image_urls=image_urls or [],
            created_at=now
        )

    def get_riro_documents(self, riro_id, limit=50):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM riro_documents
                WHERE riro_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (riro_id, limit))
            rows = cursor.fetchall()
        finally:
            conn.close()
        documents = []
        for row in rows:
            image_urls = []
            if row['image_urls']:
                try:
                    image_urls = json.loads(row['image_urls'])
                except json.JSONDecodeError:
                    image_urls = []
            documents.append(RiroDocument(
                id=row['id'],
                riro_id=row['riro_id'],
                title=row['title'],
                content=row['content'],
                image_urls=image_urls,
                created_at=row['created_at']
            ))
        return documents
    
    def get_riro_document(self, doc_id, riro_id):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM riro_documents
                WHERE id = ? AND riro_id = ?
            ''', (doc_id, riro_id))
            row = cursor.fetchone()
        finally:
            conn.close()
        
        if not row:
            return None
        
        image_urls = []
        if row['image_urls']:
            try:
                image_urls = json.loads(row['image_urls'])
            except json.JSONDecodeError:
                image_urls = []
        
        return RiroDocument(
            id=row['id'],
            riro_id=row['riro_id'],
            title=row['title'],
            content=row['content'],
            image_urls=image_urls,
            created_at=row['created_at']
        )

    # ============ 연구 서사 대화 기록 ============

    def add_research_message(self, user_id, role, text, action=None, session_id=None):
        """대화 한 줄을 남깁니다. session_id는 이 말이 속한 설계 대화방입니다."""
        conn = self.get_connection()
        try:
            conn.execute(
                'INSERT INTO research_messages '
                '(user_id, role, text, action, created_at, session_id) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (user_id, role, text, action, datetime.now().isoformat(), session_id)
            )
            conn.commit()
        finally:
            conn.close()

    def get_research_messages(self, user_id, limit=60, session_id=None,
                              include_orphans=False):
        """최근 대화를 시간순으로 반환합니다.

        session_id를 주면 그 대화방의 말만 돌려줍니다. session_id가 생기기 전에 쌓인
        기록은 어느 방에도 속하지 않으므로, 첫 설계 대화방을 열 때만
        include_orphans=True로 함께 보여줍니다.
        """
        query = ('SELECT role, text, action, created_at FROM research_messages '
                 'WHERE user_id = ?')
        params = [user_id]
        if session_id is not None:
            query += ' AND (session_id = ?' + (' OR session_id IS NULL)' if include_orphans else ')')
            params.append(session_id)
        query += ' ORDER BY id DESC LIMIT ?'
        params.append(int(limit))

        conn = self.get_connection()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in reversed(rows)]

    def pop_last_research_reply(self, user_id, session_id=None):
        """마지막 학생 발화 뒤에 붙은 답변들을 지우고 그 발화를 돌려줍니다.

        '다시 생성'용이다. 학생이 같은 말을 또 타이핑하게 하지 않으려고,
        직전 발화는 남겨 두고 그 뒤의 답변만 걷어낸다. 발화가 없으면 None.
        """
        conn = self.get_connection()
        try:
            query = ('SELECT id, role, text FROM research_messages WHERE user_id = ?'
                     + (' AND session_id = ?' if session_id is not None else '')
                     + ' ORDER BY id DESC LIMIT 20')
            params = [user_id] + ([session_id] if session_id is not None else [])
            rows = conn.execute(query, params).fetchall()
            last_user = next((row for row in rows if row['role'] == 'user'), None)
            if not last_user:
                return None
            conn.execute(
                'DELETE FROM research_messages WHERE user_id = ? AND id > ?'
                + (' AND session_id = ?' if session_id is not None else ''),
                [user_id, last_user['id']]
                + ([session_id] if session_id is not None else []))
            conn.commit()
            return last_user['text']
        finally:
            conn.close()

    def clear_research_messages(self, user_id, session_id=None, include_orphans=False):
        """대화를 비웁니다(새로 시작하기)."""
        query = 'DELETE FROM research_messages WHERE user_id = ?'
        params = [user_id]
        if session_id is not None:
            query += ' AND (session_id = ?' + (' OR session_id IS NULL)' if include_orphans else ')')
            params.append(session_id)
        conn = self.get_connection()
        try:
            conn.execute(query, params)
            conn.commit()
        finally:
            conn.close()

    # ============ CurriculumDB (2022 개정 교육과정 조회) ============

    def load_curriculum(self, curriculum_dir=None):
        """정규화된 교육과정 JSON을 DB로 적재합니다(멱등, 전량 교체).

        원본 PDF 파싱은 tools/normalize_curriculum.py가 담당하고,
        여기서는 산출물만 읽으므로 대용량 코퍼스가 없어도 동작합니다.
        """
        base = Path(curriculum_dir or Path(__file__).resolve().parent / 'data' / 'curriculum')
        subjects_path = base / 'subjects.json'
        standards_path = base / 'achievement_standards.json'
        if not subjects_path.exists() or not standards_path.exists():
            return {'subjects': 0, 'standards': 0, 'skipped': True}

        with open(subjects_path, encoding='utf-8') as handle:
            subjects = json.load(handle)['subjects']
        with open(standards_path, encoding='utf-8') as handle:
            standards = json.load(handle)['records']

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM curriculum_standards')
            cursor.execute('DELETE FROM curriculum_subjects')
            cursor.executemany('''
                INSERT INTO curriculum_subjects
                    (subject_uid, code_prefix, subject, subject_type, curriculum_area,
                     volume, grade_band, areas, standard_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (
                    entry['subject_uid'], entry['code_prefix'], entry['subject'],
                    entry.get('subject_type'), entry.get('curriculum_area'),
                    entry['volume'], entry.get('grade_band'),
                    json.dumps(entry.get('areas', []), ensure_ascii=False),
                    entry.get('standard_count', 0),
                )
                for entry in subjects
            ])
            cursor.executemany('''
                INSERT INTO curriculum_standards
                    (uid, code, code_prefix, subject_uid, subject, subject_type,
                     curriculum_area, volume, grade_band, area_no, area_name,
                     seq_no, statement, source_pdf)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (
                    record['uid'], record['code'], record['code_prefix'],
                    f"{record['volume']}:{record['code_prefix']}",
                    record['subject'], record.get('subject_type'),
                    record.get('curriculum_area'), record['volume'],
                    record.get('grade_band'), record.get('area_no'),
                    record.get('area_name'), record.get('seq_no'),
                    record['statement'], record.get('source_pdf'),
                )
                for record in standards
            ])
            conn.commit()
            return {'subjects': len(subjects), 'standards': len(standards), 'skipped': False}
        finally:
            conn.close()

    def get_curriculum_subjects(self, grade_band=None, subject_type=None, curriculum_area=None):
        """조건에 맞는 교육과정 과목 목록을 반환합니다."""
        clauses, params = [], []
        if grade_band:
            clauses.append('grade_band = ?')
            params.append(grade_band)
        if subject_type:
            clauses.append('subject_type = ?')
            params.append(subject_type)
        if curriculum_area:
            clauses.append('curriculum_area = ?')
            params.append(curriculum_area)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''

        conn = self.get_connection()
        try:
            rows = conn.execute(
                f'SELECT * FROM curriculum_subjects {where} ORDER BY volume, subject',
                params,
            ).fetchall()
        finally:
            conn.close()

        result = []
        for row in rows:
            entry = dict(row)
            try:
                entry['areas'] = json.loads(entry['areas'] or '[]')
            except json.JSONDecodeError:
                entry['areas'] = []
            result.append(entry)
        return result

    def get_curriculum_standards(self, subject_uid=None, codes=None, area_no=None):
        """과목 또는 성취기준 코드로 성취기준을 조회합니다."""
        clauses, params = [], []
        if subject_uid:
            clauses.append('subject_uid = ?')
            params.append(subject_uid)
        if area_no:
            clauses.append('area_no = ?')
            params.append(area_no)
        if codes:
            codes = list(codes)
            clauses.append(f"code IN ({','.join('?' * len(codes))})")
            params.extend(codes)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''

        conn = self.get_connection()
        try:
            rows = conn.execute(
                f'SELECT * FROM curriculum_standards {where} ORDER BY subject_uid, area_no, seq_no',
                params,
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def search_curriculum_standards(self, query, grade_band=None, limit=30):
        """성취기준 문구/과목명/영역명을 키워드로 검색합니다."""
        term = f"%{(query or '').strip()}%"
        clauses = ['(statement LIKE ? OR subject LIKE ? OR area_name LIKE ?)']
        params = [term, term, term]
        if grade_band:
            clauses.append('grade_band = ?')
            params.append(grade_band)
        params.append(int(limit))

        conn = self.get_connection()
        try:
            rows = conn.execute(
                f"SELECT * FROM curriculum_standards WHERE {' AND '.join(clauses)} "
                'ORDER BY subject_uid, area_no, seq_no LIMIT ?',
                params,
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]


# 전역 데이터베이스 인스턴스
db = Database()
