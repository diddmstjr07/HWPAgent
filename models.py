"""
데이터베이스 모델 정의
"""
from datetime import datetime
from flask_login import UserMixin
import json

class User(UserMixin):
    """사용자 모델"""
    def __init__(self, id, email, name, picture=None, password_hash=None):
        self.id = id
        self.email = email
        self.name = name
        self.picture = picture
        self.password_hash = password_hash
    
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'picture': self.picture
        }

class DocumentHistory:
    """문서 히스토리 모델"""
    def __init__(self, id, user_id, title, content, created_at=None, updated_at=None):
        self.id = id
        self.user_id = user_id
        self.title = title
        self.content = content
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'content': self.content,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }

class RiroDocument:
    """리로스쿨 사용자 문서"""
    def __init__(self, id, riro_id, title, content, image_urls=None, created_at=None):
        self.id = id
        self.riro_id = riro_id
        self.title = title
        self.content = content
        self.image_urls = image_urls or []
        self.created_at = created_at or datetime.now().isoformat()
    
    def to_dict(self):
        return {
            'id': self.id,
            'riro_id': self.riro_id,
            'title': self.title,
            'content': self.content,
            'image_urls': self.image_urls,
            'created_at': self.created_at
        }
