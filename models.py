from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint

db = SQLAlchemy()
def now():
    return datetime.now(timezone.utc)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(10), nullable=False, default='student')
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    __table_args__ = (CheckConstraint("role IN ('student','staff')"),)

class Listing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(10), nullable=False, index=True)
    category = db.Column(db.String(30), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(100), nullable=False, index=True)
    event_date = db.Column(db.Date, nullable=False, index=True)
    image = db.Column(db.String(80))
    status = db.Column(db.String(15), default='open', nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    reporter = db.relationship(User)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)
    __table_args__ = (CheckConstraint("kind IN ('lost','found')"), CheckConstraint("status IN ('open','claimed','returned','hidden')"))

class Claim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('listing.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    explanation = db.Column(db.Text, nullable=False)
    details = db.Column(db.Text, nullable=False, default='')
    status = db.Column(db.String(15), default='pending', nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    listing = db.relationship(Listing)
    claimant = db.relationship(User)
    __table_args__ = (db.UniqueConstraint('listing_id','user_id'), CheckConstraint("status IN ('pending','approved','rejected')"))

class Handover(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('listing.id'), unique=True, nullable=False)
    claim_id = db.Column(db.Integer, db.ForeignKey('claim.id'), unique=True, nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    record = db.Column(db.String(80), nullable=False)
    timestamp = db.Column(db.DateTime, default=now, nullable=False, index=True)
    actor = db.relationship(User)
