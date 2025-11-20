import os
import sys

# Ensure package import path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app, db
from sqlalchemy import text


def run_example(email_param):
    with app.app_context():
        # Example of a parameterized raw SQL query using SQLAlchemy text()
        stmt = text('SELECT id, first_name, last_name, email, phone, address FROM user WHERE email = :email')
        result = db.session.execute(stmt, {'email': email_param})
        rows = result.fetchall()
        if not rows:
            print('No rows returned for', email_param)
        else:
            for r in rows:
                # r._mapping provides a dict-like mapping of column names to values
                print(dict(r._mapping))


if __name__ == '__main__':
    # Example usage: query for the XSS test user created earlier
    run_example('someone@gmail.com')
