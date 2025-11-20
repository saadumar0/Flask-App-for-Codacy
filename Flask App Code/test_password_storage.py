import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import app, db, AuthUser


def run_test():
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.create_all()
    with app.test_client() as client:
        data = {
            'first_name': 'Auth',
            'last_name': 'Tester',
            'email': 'auth_test@example.com',
            'password': 'Secur3Pass!',
            'confirm': 'Secur3Pass!'
        }
        # register
        rv = client.post('/register', data=data, follow_redirects=True)
        print('Register status:', rv.status_code)
        with app.app_context():
            user = AuthUser.query.filter_by(email='auth_test@example.com').first()
            if not user:
                print('AuthUser not found')
                return
            print('Stored password_hash:', user.password_hash)
            assert user.password_hash != data['password'], 'Password stored in plaintext!'
            print('Password is hashed (not equal to plaintext).')
            # verify using model method
            if user.check_password(data['password']):
                print('Password verification via bcrypt succeeded.')
            else:
                print('Password verification FAILED')


if __name__ == '__main__':
    run_test()
