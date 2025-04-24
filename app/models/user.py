# app/models/user.py
from flask import current_app as app
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from app.model import db


class UserService:
    @staticmethod
    def get_user(user_id):
        """Get a user by ID"""
        rows = db.session.execute(
            text('''
                SELECT user_id, email, first_name, last_name, address, 
                       current_balance, is_seller, created_at, updated_at
                FROM Accounts
                WHERE user_id = :user_id
                '''),
            {"user_id": user_id}
        ).fetchall()
        
        if not rows:
            return None
            
        user_dict = {
            'user_id': rows[0][0],
            'email': rows[0][1],
            'first_name': rows[0][2],
            'last_name': rows[0][3],
            'address': rows[0][4],
            'current_balance': rows[0][5],
            'is_seller': rows[0][6],
            'created_at': rows[0][7],
            'updated_at': rows[0][8],
            'name': f"{rows[0][2]} {rows[0][3]}"
        }
        
        return user_dict
    
    @staticmethod
    def get_by_email(email):
        """Get a user by email"""
        rows = db.session.execute(
            text('''
            SELECT user_id, email, first_name, last_name, password, 
                   current_balance, is_seller
            FROM Accounts
            WHERE email = :email
            '''),
            {"email": email}
        ).fetchall()
        
        return rows[0] if rows else None