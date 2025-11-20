from flask import Flask, render_template, request, redirect, flash, session
import logging
from flask_sqlalchemy import SQLAlchemy
import os
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from flask_wtf import CSRFProtect
import bleach

from forms import UserForm, DeleteForm
from datetime import timedelta
from flask_bcrypt import Bcrypt
from forms import RegistrationForm, LoginForm


app = Flask(__name__)
# Configuration
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(BASE_DIR, 'instance', 'firstapp.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# SECRET_KEY is required for Flask-WTF (CSRF). In production set via environment variable.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')
# Session cookie security settings
# In production ensure SESSION_COOKIE_SECURE is True (requires HTTPS)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
# Make sessions permanent by default and set a sensible lifetime
app.permanent_session_lifetime = timedelta(days=7)

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
bcrypt = Bcrypt(app)


@app.before_request
def make_session_permanent():
    # Ensure session uses the configured permanent lifetime
    session.permanent = True


# --- Secure error handling -------------------------------------------------
# Configure basic logging for errors. In production, use a more robust
# logging configuration (file, external aggregator, levels, rotation).
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.errorhandler(404)
def not_found_error(error):
    # Render a generic 404 page without sensitive details
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    # Log the exception with stack trace for server-side diagnosis but do
    # not expose details to users.
    logger.exception('An internal server error occurred: %s', error)
    return render_template('500.html'), 500

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    # Note: this model stores contact information. Authentication credentials
    # are stored in a separate `AuthUser` model so existing data remains
    # unaffected when introducing authentication.

    def __repr__(self):
        return f"<User {self.id} {self.first_name}>"


class AuthUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

@app.route('/', methods=['GET', 'POST'])
def index():
    form = UserForm()
    delete_form = DeleteForm()
    if form.validate_on_submit():
        # Use sanitized/validated inputs
        first_name = bleach.clean(form.first_name.data.strip(), strip=True)
        last_name = bleach.clean(form.last_name.data.strip(), strip=True)
        email = form.email.data.strip()
        phone = bleach.clean((form.phone.data or '').strip(), strip=True)
        address = bleach.clean((form.address.data or '').strip(), strip=True)
        new_user = User(first_name=first_name, last_name=last_name, email=email, phone=phone, address=address)
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('User added successfully.', 'success')
            return redirect('/')
        except IntegrityError:
            db.session.rollback()
            flash('A user with that email already exists.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            flash('An error occurred while saving the user.', 'danger')
    users = User.query.all()
    return render_template('index.html', users=users, form=form, delete_form=delete_form)


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        with app.app_context():
            existing = AuthUser.query.filter_by(email=email).first()
            if existing:
                flash('An account with that email already exists.', 'danger')
            else:
                au = AuthUser(email=email)
                au.set_password(form.password.data)
                db.session.add(au)
                db.session.commit()
                flash('Registration successful. You can now log in.', 'success')
                return redirect('/login')
    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = AuthUser.query.filter_by(email=email).first()
        if user and user.check_password(form.password.data):
            session['auth_user_id'] = user.id
            flash('Logged in successfully.', 'success')
            return redirect('/')
        else:
            flash('Invalid email or password.', 'danger')
    return render_template('login.html', form=form)


@app.route('/logout')
def logout():
    session.pop('auth_user_id', None)
    flash('Logged out.', 'success')
    return redirect('/')

@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    # Delete must be a POST request to mitigate CSRF and accidental deletes.
    user = User.query.get_or_404(id)
    try:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted.', 'success')
    except SQLAlchemyError:
        db.session.rollback()
        flash('An error occurred while deleting the user.', 'danger')
    return redirect('/')

@app.route('/update/<int:id>', methods=['GET', 'POST'])
def update(id):
    user = User.query.get_or_404(id)
    form = UserForm(obj=user)
    if form.validate_on_submit():
        user.first_name = bleach.clean(form.first_name.data.strip(), strip=True)
        user.last_name = bleach.clean(form.last_name.data.strip(), strip=True)
        user.email = form.email.data.strip()
        user.phone = bleach.clean((form.phone.data or '').strip(), strip=True)
        user.address = bleach.clean((form.address.data or '').strip(), strip=True)
        try:
            db.session.commit()
            flash('User updated successfully.', 'success')
            return redirect('/')
        except IntegrityError:
            db.session.rollback()
            flash('A user with that email already exists.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            flash('An error occurred while updating the user.', 'danger')
    return render_template('update.html', user=user, form=form)

if __name__ == '__main__':
    os.makedirs('instance', exist_ok=True)
    with app.app_context():
        db.create_all()
    # Note: debug must be False in production to avoid exposing tracebacks.
    app.run(debug=False)
