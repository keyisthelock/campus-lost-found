import os
import re
import secrets
from datetime import date, timedelta
from functools import wraps
from pathlib import Path
import click
from dotenv import load_dotenv
from flask import Flask, abort, flash, g, redirect, render_template, request, send_from_directory, session, url_for
from sqlalchemy import or_, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Listing, Claim, Handover, ActivityLog
from services import CATEGORIES, analytics, approve, log, save_image
import azure_integration

@event.listens_for(Engine, 'connect')
def enable_foreign_keys(connection, record):
    if connection.__class__.__module__.startswith('sqlite3'):
        connection.execute('PRAGMA foreign_keys=ON')

def create_app(config=None):
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY') or secrets.token_hex(32), SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL','sqlite:///campus.db'), SQLALCHEMY_TRACK_MODIFICATIONS=False, MAX_CONTENT_LENGTH=5*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE','false').lower() == 'true', PERMANENT_SESSION_LIFETIME=timedelta(hours=8), UPLOAD_FOLDER=str(Path(app.instance_path)/'uploads'))
    if config:
        app.config.update(config)
    app.config.setdefault('DEMO_MODE',os.getenv('DEMO_MODE','true').lower() == 'true')
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    with app.app_context():
        db.create_all()

    def protected(staff=False):
        def decorator(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if not g.user:
                    return redirect(url_for('login'))
                if staff and g.user.role != 'staff':
                    abort(403)
                return fn(*args, **kwargs)
            return wrapped
        return decorator

    @app.before_request
    def prepare():
        g.user = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        if request.method == 'POST' and not secrets.compare_digest(session['csrf'], request.form.get('csrf','')):
            abort(400, 'Your form expired. Refresh the page and try again.')
        g.demo = app.config['DEMO_MODE'] and request.remote_addr in ('127.0.0.1','::1')
        if g.demo and not g.user and request.endpoint != 'static':
            user = User(name='Campus Explorer',email=f'demo-{secrets.token_hex(12)}@campus.invalid',password_hash=generate_password_hash(secrets.token_urlsafe(40)),role='student')
            db.session.add(user)
            db.session.commit()
            session['user_id'] = user.id
            session['demo_student'] = user.id
            g.user = user

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.context_processor
    def context():
        return dict(categories=CATEGORIES, today=date.today(), csrf=session.get('csrf'))

    @app.post('/demo/role')
    def demo_role():
        if not g.demo:
            abort(403)
        role = request.form.get('role')
        if role not in ('student','staff'):
            abort(400)
        key = 'demo_' + role
        user = db.session.get(User,session[key]) if session.get(key) else None
        if not user:
            user = User(name='Demo Service Desk' if role=='staff' else 'Campus Explorer',email=f'demo-{secrets.token_hex(12)}@campus.invalid',password_hash=generate_password_hash(secrets.token_urlsafe(40)),role=role)
            db.session.add(user)
            db.session.commit()
            session[key] = user.id
        session['user_id'] = user.id
        session['csrf'] = secrets.token_urlsafe(32)
        return redirect(url_for('staff' if role=='staff' else 'dashboard'))

    def text(name, maximum, minimum=1):
        value = request.form.get(name,'').strip()
        if not minimum <= len(value) <= maximum:
            raise ValueError(f'{name.replace("_"," ").capitalize()} must be {minimum}–{maximum} characters.')
        return value

    def owned(item):
        if item.user_id != g.user.id:
            abort(403)

    def get_listing(item_id):
        item = db.get_or_404(Listing,item_id)
        if item.status == 'hidden' and (not g.user or (g.user.role != 'staff' and g.user.id != item.user_id)):
            abort(404)
        return item

    @app.route('/')
    def home():
        return render_template('home.html', stats=analytics(), items=Listing.query.filter_by(status='open').order_by(Listing.created_at.desc()).limit(3).all())

    @app.route('/register', methods=['GET','POST'])
    def register():
        if request.method == 'POST':
            try:
                name, email, password = text('name',80), text('email',254).lower(), text('password',128,10)
                if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
                    raise ValueError('Enter a valid email address.')
                user = User(name=name,email=email,password_hash=generate_password_hash(password),role='student')
                db.session.add(user)
                db.session.commit()
                session.clear()
                session.update(user_id=user.id, csrf=secrets.token_urlsafe(32))
                session.permanent = True
                return redirect(url_for('dashboard'))
            except IntegrityError:
                db.session.rollback()
                flash('Unable to register with that email. Try signing in.','danger')
            except ValueError as exc:
                flash(str(exc),'danger')
        return render_template('auth.html', registering=True)

    @app.route('/login', methods=['GET','POST'])
    def login():
        if request.method == 'POST':
            user = User.query.filter_by(email=request.form.get('email','').strip().lower()).first()
            if user and len(request.form.get('password','')) <= 128 and check_password_hash(user.password_hash,request.form.get('password','')):
                session.clear()
                session.update(user_id=user.id,csrf=secrets.token_urlsafe(32))
                session.permanent = True
                return redirect(url_for('dashboard'))
            flash('Email or password is incorrect.','danger')
        return render_template('auth.html',registering=False)

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('home'))

    @app.get('/listings')
    def listings():
        query = Listing.query.filter(Listing.status != 'hidden')
        keyword = request.args.get('q','')[:120].strip()
        if keyword:
            pattern = '%' + keyword.replace('!','!!').replace('%','!%').replace('_','!_') + '%'
            query = query.filter(or_(Listing.title.ilike(pattern,escape='!'), Listing.description.ilike(pattern,escape='!')))
        for field in ('category','kind','status','location'):
            value = request.args.get(field,'')[:100]
            if value:
                query = query.filter(getattr(Listing,field) == value)
        query = query.order_by(Listing.event_date.asc() if request.args.get('sort') == 'oldest' else Listing.event_date.desc(),Listing.id.desc())
        page = query.paginate(page=request.args.get('page',1,type=int), per_page=12, error_out=False)
        locations = db.session.query(Listing.location).filter(Listing.status != 'hidden').distinct().order_by(Listing.location).all()
        return render_template('listings.html',page=page,items=page.items,locations=locations)

    @app.route('/reports/new', methods=['GET','POST'])
    @app.route('/reports/<int:item_id>/edit', methods=['GET','POST'])
    @protected()
    def report(item_id=None):
        item = db.get_or_404(Listing,item_id) if item_id else None
        if item:
            owned(item)
            if item.status != 'open':
                abort(403,'Only open reports can be edited.')
        if request.method == 'POST':
            try:
                title, description, location = text('title',120,3), text('description',4000,10), text('location',100,2)
                kind, category = request.form.get('kind'), request.form.get('category')
                if kind not in ('lost','found') or category not in CATEGORIES:
                    raise ValueError('Select a valid type and category.')
                when = date.fromisoformat(request.form.get('event_date',''))
                if when > date.today():
                    raise ValueError('The item date cannot be in the future.')
                if item and item.kind != kind and Claim.query.filter_by(listing_id=item.id).first():
                    raise ValueError('Reports with claims cannot change type.')
                image = save_image(request.files.get('image'))
                if not item:
                    item = Listing(user_id=g.user.id)
                    db.session.add(item)
                item.title, item.description, item.location, item.kind, item.category, item.event_date = title, description, location, kind, category, when
                if image:
                    item.image = image
                db.session.flush()
                log(g.user.id,'Report updated' if item_id else 'Report created',f'Listing #{item.id}')
                db.session.commit()
                flash('Your report has been saved.','success')
                return redirect(url_for('detail',item_id=item.id))
            except ValueError as exc:
                flash(str(exc) or 'Enter a valid date.','danger')
        return render_template('report.html',item=item)

    @app.get('/listings/<int:item_id>')
    def detail(item_id):
        item = get_listing(item_id)
        mine = Claim.query.filter_by(listing_id=item.id,user_id=g.user.id).first() if g.user else None
        return render_template('detail.html',item=item,mine=mine)

    @app.get('/photos/<int:item_id>')
    @protected()
    def photo(item_id):
        item = get_listing(item_id)
        if not item.image:
            abort(404)
        return send_from_directory(app.config['UPLOAD_FOLDER'],item.image)

    @app.post('/listings/<int:item_id>/claim')
    @protected()
    def claim(item_id):
        item = get_listing(item_id)
        if item.kind != 'found' or item.status != 'open' or item.user_id == g.user.id or g.user.role != 'student':
            abort(403)
        try:
            evidence, details = text('explanation',3000,15), text('details',2000,0)
            db.session.add(Claim(listing_id=item.id,user_id=g.user.id,explanation=evidence,details=details))
            log(g.user.id,'Claim submitted',f'Listing #{item.id}')
            db.session.commit()
            flash('Claim submitted privately to campus staff.','success')
        except ValueError as exc:
            flash(str(exc),'danger')
        except IntegrityError:
            db.session.rollback()
            flash('You have already claimed this item.','danger')
        return redirect(url_for('detail',item_id=item.id))

    @app.get('/dashboard')
    @protected()
    def dashboard():
        return render_template('dashboard.html',items=Listing.query.filter_by(user_id=g.user.id).order_by(Listing.created_at.desc()).all(),claims=Claim.query.filter_by(user_id=g.user.id).order_by(Claim.created_at.desc()).all())

    @app.route('/profile',methods=['GET','POST'])
    @protected()
    def profile():
        if request.method == 'POST':
            try:
                g.user.name = text('name',80)
                db.session.commit()
                flash('Profile updated.','success')
            except ValueError as exc:
                flash(str(exc),'danger')
        return render_template('profile.html')

    @app.get('/staff')
    @protected(staff=True)
    def staff():
        return render_template('staff.html',stats=analytics(),claims=Claim.query.order_by(Claim.created_at.desc()).limit(200).all(),reports=Listing.query.order_by(Listing.created_at.desc()).limit(200).all(),logs=ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(100).all())

    @app.post('/staff/claims/<int:claim_id>/<action>')
    @protected(staff=True)
    def review(claim_id,action):
        entry = db.get_or_404(Claim,claim_id)
        if entry.status != 'pending' or action not in ('approve','reject'):
            abort(409)
        try:
            if action == 'approve':
                approve(entry)
                log(g.user.id,'Competing pending claims rejected',f'Listing #{entry.listing_id}')
            else:
                entry.status = 'rejected'
            log(g.user.id,'Claim '+action+'d',f'Claim #{entry.id}')
            db.session.commit()
            flash('Claim decision recorded.','success')
        except ValueError as exc:
            flash(str(exc),'danger')
            return render_template('error.html',message=str(exc)),409
        return redirect(url_for('staff'))

    @app.post('/staff/claims/<int:claim_id>/handover')
    @protected(staff=True)
    def handover(claim_id):
        entry = db.get_or_404(Claim,claim_id)
        if entry.status != 'approved':
            abort(409)
        try:
            when = date.fromisoformat(request.form.get('date',''))
            if when > date.today() or when < entry.created_at.date():
                raise ValueError('Choose a handover date between claim submission and today.')
            notes = text('notes',2000,3)
            if entry.listing.status != 'claimed':
                abort(409)
            db.session.add(Handover(listing_id=entry.listing_id,claim_id=entry.id,staff_id=g.user.id,date=when,notes=notes))
            entry.listing.status = 'returned'
            log(g.user.id,'Item handed over',f'Listing #{entry.listing_id}')
            db.session.commit()
            flash('Handover recorded. Another item, back where it belongs.','success')
        except (ValueError,IntegrityError):
            db.session.rollback()
            flash('Unable to record handover. Check the date, notes and current status.','danger')
        return redirect(url_for('staff'))

    @app.post('/staff/listings/<int:item_id>/moderate')
    @protected(staff=True)
    def moderate(item_id):
        item = db.get_or_404(Listing,item_id)
        if item.status not in ('open','hidden'):
            abort(409)
        item.status = 'open' if item.status == 'hidden' else 'hidden'
        log(g.user.id,'Report '+item.status,f'Listing #{item.id}')
        db.session.commit()
        return redirect(url_for('staff'))

    @app.route('/integrations',methods=['GET','POST'])
    @protected()
    def integrations():
        enabled = azure_integration.available()
        result = None
        if request.method == 'POST':
            if request.form.get('action') == 'clear':
                result = 'Disconnected. No credentials are stored.'
            elif not enabled:
                flash('Install optional Azure dependencies to enable cloud actions.','danger')
            else:
                try:
                    action = request.form.get('action')
                    if action not in ('test','copy'):
                        abort(400)
                    path = None
                    if action == 'copy':
                        item = db.get_or_404(Listing,request.form.get('listing_id',type=int))
                        owned(item)
                        if not item.image:
                            raise azure_integration.ValidationError('Select one of your reports with a photograph.')
                        path = Path(app.config['UPLOAD_FOLDER'])/item.image
                    azure_integration.operate(request.form.get('account',''),request.form.get('container',''),request.form.get('token',''),path)
                    result = 'Photo copied; the local original is retained.' if path else 'Private container connection verified for this request.'
                except azure_integration.ValidationError as exc:
                    flash(str(exc),'danger')
                except Exception:
                    # Deliberately never log SDK exceptions: they may contain a SAS.
                    flash('Azure operation failed. Check credentials, permissions and connectivity. Local files are safe.','danger')
        return render_template('integrations.html',enabled=enabled,result=result,sql=app.config['SQLALCHEMY_DATABASE_URI'].startswith('mssql'),items=Listing.query.filter(Listing.user_id==g.user.id,Listing.image.isnot(None)).all())

    @app.cli.command('create-staff')
    @click.option('--email',prompt=True)
    @click.option('--name',prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_staff(email,name,password):
        if len(password)<12 or len(password)>128 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or not 1<=len(name)<=80:
            raise click.ClickException('Use a valid email/name and a 12–128 character password.')
        if User.query.filter_by(email=email.strip().lower()).first():
            raise click.ClickException('Email already exists; no changes made.')
        db.session.add(User(name=name,email=email.strip().lower(),password_hash=generate_password_hash(password),role='staff'))
        db.session.commit()
        click.echo('Staff account created.')

    @app.cli.command('seed-demo')
    def seed_demo():
        if User.query.filter_by(email='maya@campus.example').first():
            click.echo('Demo data already exists; no changes made.')
            return
        password=secrets.token_urlsafe(15)
        users=[User(name=n,email=e,password_hash=generate_password_hash(password),role='student') for n,e in [('Maya Chen','maya@campus.example'),('Arjun Rao','arjun@campus.example'),('Sam Taylor','sam@campus.example')]]
        db.session.add_all(users)
        db.session.flush()
        titles=['Wireless headphones','Blue campus backpack','Engineering mathematics notes','Student identity card','Silver keyring','Brown leather wallet','USB-C charger','Library textbook','Black spectacles case','Canvas tote bag','Scientific calculator','Water bottle']
        cats=['Electronics','Bags','Books','Student ID','Keys','Wallet','Electronics','Books','Other','Bags','Electronics','Other']
        locations=['Central Library','Engineering Block','Student Centre','North Cafeteria']
        entries=[]
        for i,title in enumerate(titles):
            item=Listing(title=title,kind='lost' if i%3==0 else 'found',category=cats[i],description=f'{title}, reported near {locations[i%4]}. Please provide identifying details when claiming this item.',location=locations[i%4],event_date=date.today()-timedelta(days=i*2),user_id=users[i%3].id)
            db.session.add(item)
            db.session.flush()
            log(item.user_id,'Report created',f'Listing #{item.id}')
            entries.append(item)
        for i in (1,2,4):
            entry=Claim(listing_id=entries[i].id,user_id=users[0].id,explanation='Synthetic demo evidence: initials inside the item.',details='Demo identifying mark',status='approved' if i==2 else 'pending')
            db.session.add(entry)
            db.session.flush()
            log(users[0].id,'Claim submitted',f'Claim #{entry.id}')
            if i==2:
                # Use a separate disabled-login fictional staff actor for historical demo records.
                actor=User(name='Demo Campus Desk',email='desk@campus.example',password_hash=generate_password_hash(secrets.token_urlsafe(40)),role='staff')
                db.session.add(actor)
                db.session.flush()
                entries[i].status='returned'
                db.session.add(Handover(listing_id=entries[i].id,claim_id=entry.id,staff_id=actor.id,date=date.today(),notes='Synthetic demonstration handover.'))
                log(actor.id,'Claim approved',f'Claim #{entry.id}')
                log(actor.id,'Item handed over',f'Listing #{entries[i].id}')
        db.session.commit()
        click.echo(f'Demo seeded. Student: maya@campus.example | temporary password: {password}')

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    @app.errorhandler(500)
    def error(exc):
        db.session.rollback()
        messages={400:'Your form expired or contained invalid data. Refresh and try again.',403:'You do not have access to this action.',404:'We could not find that page or item.',409:'This record has changed. Refresh before trying again.',413:'Uploads must be smaller than 5 MB.',500:'Something went wrong. Please try again later.'}
        return render_template('error.html',message=messages.get(exc.code,'Request unsuccessful.')),exc.code
    return app

if __name__ == '__main__':
    create_app().run(host='127.0.0.1',port=5000,debug=False)
