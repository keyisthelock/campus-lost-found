import io
from datetime import date
import pytest
from PIL import Image
from werkzeug.security import generate_password_hash
from app import create_app
from models import db, User, Listing, Claim, Handover, ActivityLog
import azure_integration

@pytest.fixture
def app(tmp_path):
    app=create_app({'TESTING':True,'DEMO_MODE':False,'SECRET_KEY':'test-only-secret','SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'test.db'),'UPLOAD_FOLDER':str(tmp_path/'uploads')})
    with app.app_context():
        for name,role in [('alice','student'),('bob','student'),('carol','student'),('staff','staff')]:
            db.session.add(User(name=name,email=name+'@test.example',role=role,password_hash=generate_password_hash('test-password-123')))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

def post(client,url,data=None,**kwargs):
    client.get('/login')
    with client.session_transaction() as session:
        token=session['csrf']
    return client.post(url,data={'csrf':token,**(data or {})},**kwargs)

def login(client,name):
    return post(client,'/login',{'email':name+'@test.example','password':'test-password-123'})

def report(client,**values):
    return post(client,'/reports/new',{'title':'Blue headphones','description':'Headphones found beside the reading room.','kind':'found','category':'Electronics','location':'Library','event_date':str(date.today()),**values})

def claim(client,item=1):
    return post(client,f'/listings/{item}/claim',{'explanation':'Private evidence: my initials are underneath.','details':'Serial ABC123'})

def test_register_login_and_role(client,app):
    response=post(client,'/register',{'name':'New Student','email':'new@test.example','password':'a-strong-password','role':'staff'})
    assert response.status_code==302
    with app.app_context():
        assert User.query.filter_by(email='new@test.example').one().role=='student'
    post(client,'/logout')
    assert post(client,'/login',{'email':'new@test.example','password':'wrong'}).status_code==200
    assert post(client,'/login',{'email':'new@test.example','password':'a-strong-password'}).status_code==302

def test_access_and_csrf(client):
    assert client.get('/staff').status_code==302
    login(client,'alice')
    assert client.get('/staff').status_code==403
    assert post(client,'/staff/claims/1/approve').status_code==403
    assert client.post('/reports/new',data={}).status_code==400

def test_listings_filters_ownership_and_images(client,app):
    login(client,'alice')
    image=io.BytesIO()
    Image.new('RGB',(30,30),'blue').save(image,'PNG')
    image.seek(0)
    assert report(client,image=(image,'unsafe.html')).status_code==302
    assert client.get('/photos/1').status_code==200
    for query in ['q=headphones','category=Electronics','kind=found','location=Library','status=open','sort=oldest']:
        assert b'Blue headphones' in client.get('/listings?'+query).data
    assert b'Blue headphones' not in client.get('/listings?kind=lost').data
    assert client.get('/listings?page=2').status_code==200
    login(client,'bob')
    assert client.get('/reports/1/edit').status_code==403
    assert post(client,'/reports/1/edit',{'title':'Hijacked'}).status_code==403
    assert report(client,image=(io.BytesIO(b'fake'),'fake.png')).status_code==200
    with app.app_context():
        assert Listing.query.count()==1
        assert Listing.query.first().image.endswith('.jpg')
    post(client,'/logout')
    assert client.get('/photos/1').status_code==302

def test_claim_review_handover_and_privacy(client,app):
    login(client,'alice')
    report(client)
    assert claim(client).status_code==403
    login(client,'bob')
    assert claim(client).status_code==302
    claim(client)
    assert b'Private evidence' not in client.get('/listings/1').data
    assert b'Serial ABC123' not in client.get('/dashboard').data
    login(client,'carol')
    claim(client)
    login(client,'staff')
    assert b'Private evidence' in client.get('/staff').data
    assert post(client,'/staff/claims/1/approve').status_code==302
    assert post(client,'/staff/claims/2/approve').status_code==409
    assert post(client,'/staff/claims/1/handover',{'date':str(date.today()),'notes':'Identity verified; collected at desk.'}).status_code==302
    assert post(client,'/staff/claims/1/handover',{'date':str(date.today()),'notes':'Duplicate attempt'}).status_code==409
    with app.app_context():
        assert Claim.query.filter_by(status='approved').count()==1
        assert db.session.get(Claim,2).status=='rejected'
        assert db.session.get(Listing,1).status=='returned'
        assert Handover.query.count()==1
        assert ActivityLog.query.filter_by(action='Item handed over').count()==1

def test_local_mode_pages_and_demo(client,app,monkeypatch):
    monkeypatch.setattr(azure_integration,'available',lambda:False)
    monkeypatch.setattr(azure_integration,'operate',lambda *a,**k:pytest.fail('Local mode contacted Azure'))
    for url in ['/','/listings','/register','/login','/listings?status=hidden']:
        assert client.get(url).status_code==200
    login(client,'alice')
    for url in ['/dashboard','/profile','/reports/new','/integrations']:
        assert client.get(url).status_code==200
    assert b'Optional SDK not installed' in client.get('/integrations').data
    assert post(client,'/integrations',{'action':'test'}).status_code==200
    login(client,'staff')
    assert client.get('/staff').status_code==200
    runner=app.test_cli_runner()
    assert runner.invoke(args=['seed-demo']).exit_code==0
    assert 'already exists' in runner.invoke(args=['seed-demo']).output
    assert client.get('/staff').status_code==200
    with app.app_context():
        assert Listing.query.count()==12

def test_moderation_and_edit(client,app):
    login(client,'alice')
    report(client)
    assert post(client,'/reports/1/edit',{'title':'Updated headphones','description':'Updated description for the item.','kind':'found','category':'Electronics','location':'Library','event_date':str(date.today())}).status_code==302
    login(client,'staff')
    assert post(client,'/staff/listings/1/moderate').status_code==302
    login(client,'bob')
    assert client.get('/listings/1').status_code==404
    assert b'Updated headphones' not in client.get('/listings').data
    login(client,'staff')
    post(client,'/staff/listings/1/moderate')
    assert b'Updated headphones' in client.get('/listings').data

def test_cloud_validation():
    for account,container,token in [('evil.example','photos','x'),('validname','bad--name','x'),('validname','photos','sig=x')]:
        with pytest.raises(ValueError):
            azure_integration.operate(account,container,token)

def test_cli_staff_account(app):
    runner=app.test_cli_runner()
    response=runner.invoke(args=['create-staff','--email','desk@test.example','--name','Campus Desk'],input='secure-long-password\nsecure-long-password\n')
    assert response.exit_code==0,response.output
    with app.app_context():
        assert User.query.filter_by(email='desk@test.example').one().role=='staff'

def test_cloud_failure_does_not_echo_credentials(client,monkeypatch):
    login(client,'alice')
    monkeypatch.setattr(azure_integration,'available',lambda:True)
    def fail(*args,**kwargs):
        raise ValueError('SDK error containing SECRET-SAS-TOKEN')
    monkeypatch.setattr(azure_integration,'operate',fail)
    response=post(client,'/integrations',{'action':'test','account':'validaccount','container':'photos','token':'SECRET-SAS-TOKEN'})
    assert b'SECRET-SAS-TOKEN' not in response.data
    assert b'Azure operation failed' in response.data
    with client.session_transaction() as session:
        assert 'SECRET-SAS-TOKEN' not in str(dict(session))

def test_no_signup_demo_student_and_staff(client,app):
    app.config['DEMO_MODE']=True
    assert client.get('/dashboard').status_code==200
    assert report(client).status_code==302
    with client.session_transaction() as session:
        student=session['user_id']
    assert post(client,'/demo/role',{'role':'staff'}).status_code==302
    assert client.get('/staff').status_code==200
    assert post(client,'/demo/role',{'role':'student'}).status_code==302
    with client.session_transaction() as session:
        assert session['user_id']==student
    assert client.get('/staff').status_code==403
    assert client.get('/staff',environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code==403
