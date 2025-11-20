import os
import sys
import sqlite3

# Ensure parent folder (Flask App) is on sys.path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import app, db, User


# Use the same SQLite file SQLAlchemy is configured to use so the test
# inspects the exact same database file that the app writes to.
db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
if db_uri.startswith('sqlite:///'):
    # strip the sqlite URI prefix to get a filesystem path
    DB_PATH = db_uri.replace('sqlite:///', '')
else:
    # fallback to the old default (keeps compatibility)
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'firstapp.db')


def get_tables():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def get_last_user():
    # Return last user row
    u = User.query.order_by(User.id.desc()).first()
    if not u:
        return None
    return {'id': u.id, 'first_name': u.first_name, 'last_name': u.last_name, 'email': u.email, 'phone': u.phone, 'address': u.address}


def run_tests():
    print('DB path:', DB_PATH)
    before = get_tables()
    print('Tables before test:', before)

    # Disable CSRF for testing
    app.config['WTF_CSRF_ENABLED'] = False

    with app.test_client() as client:
        # Test SQL injection-like payload
        sql_payload = "Robert'); DROP TABLE user;--"
        data = {
            'first_name': sql_payload,
            'last_name': 'Hacker',
            'email': 'hacker_sql@example.com',
            'phone': '123456',
            'address': "123 Main St"
        }
        rv = client.post('/', data=data, follow_redirects=True)
        print('POST SQL-payload status:', rv.status_code)

        # Test XSS payload
        xss_payload = '<script>alert(1)</script>'
        data2 = {
            'first_name': 'XssTest',
            'last_name': 'User',
            'email': 'xss@example.com',
            'phone': '000',
            'address': xss_payload
        }
        rv2 = client.post('/', data=data2, follow_redirects=True)
        print('POST XSS-payload status:', rv2.status_code)

        after = get_tables()
        print('Tables after test:', after)

        last_sql_user = User.query.filter_by(email='hacker_sql@example.com').first()
        last_xss_user = User.query.filter_by(email='xss@example.com').first()

        print('\nLast SQL-injection user row:')
        print(get_last_user() if last_sql_user else 'Not found')
        print('\nXSS user stored address field:')
        if last_xss_user:
            print('stored address:', repr(last_xss_user.address))
        else:
            print('XSS user not found')

        # Check that 'user' table still exists
        if 'user' in after or 'users' in after:
            print('\nTable check: user table still present.')
        else:
            print('\nTable check: user table MISSING - potential SQL injection succeeded!')


if __name__ == '__main__':
    # Ensure DB exists and tables created
    with app.app_context():
        db.create_all()
    run_tests()
