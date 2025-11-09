"""
SQLite 데이터베이스 매니저
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from models import User, DocumentHistory

class Database:
    def __init__(self, db_path='hwp_agent.db'):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """데이터베이스 초기화"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 사용자 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                picture TEXT,
                created_at TEXT NOT NULL
            )
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
        
        conn.commit()
        conn.close()
    
    # ============ User 관련 메서드 ============
    
    def get_user(self, user_id):
        """사용자 조회"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return User(
                id=row['id'],
                email=row['email'],
                name=row['name'],
                picture=row['picture']
            )
        return None
    
    def get_user_by_email(self, email):
        """이메일로 사용자 조회"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return User(
                id=row['id'],
                email=row['email'],
                name=row['name'],
                picture=row['picture']
            )
        return None
    
    def create_or_update_user(self, user_id, email, name, picture):
        """사용자 생성 또는 업데이트"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 기존 사용자 확인
        cursor.execute('SELECT id FROM users WHERE id = ?', (user_id,))
        existing = cursor.fetchone()
        
        if existing:
            # 업데이트
            cursor.execute('''
                UPDATE users 
                SET email = ?, name = ?, picture = ?
                WHERE id = ?
            ''', (email, name, picture, user_id))
        else:
            # 신규 생성
            cursor.execute('''
                INSERT INTO users (id, email, name, picture, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, email, name, picture, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        return User(id=user_id, email=email, name=name, picture=picture)
    
    # ============ Document History 관련 메서드 ============
    
    def save_document(self, user_id, title, content):
        """문서 저장"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        cursor.execute('''
            INSERT INTO document_history (user_id, title, content, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, title, content, now, now))
        
        doc_id = cursor.lastrowid
        conn.commit()
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
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM document_history
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (user_id, limit))
        
        rows = cursor.fetchall()
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
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM document_history
            WHERE id = ? AND user_id = ?
        ''', (doc_id, user_id))
        
        row = cursor.fetchone()
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
        cursor = conn.cursor()
        
        # 소유권 확인
        cursor.execute('SELECT id FROM document_history WHERE id = ? AND user_id = ?', (doc_id, user_id))
        if not cursor.fetchone():
            conn.close()
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
        conn.close()
        
        return self.get_document(doc_id, user_id)
    
    def delete_document(self, doc_id, user_id):
        """문서 삭제"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM document_history
            WHERE id = ? AND user_id = ?
        ''', (doc_id, user_id))
        
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return deleted

# 전역 데이터베이스 인스턴스
db = Database()
