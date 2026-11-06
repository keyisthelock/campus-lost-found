import secrets
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from flask import current_app
from sqlalchemy import func, update
from models import db, Listing, Claim, ActivityLog

CATEGORIES = ['Electronics','Student ID','Books','Wallet','Keys','Bags','Other']

def log(actor, action, record):
    db.session.add(ActivityLog(actor_id=actor, action=action, record=record))

def save_image(upload):
    if not upload or not upload.filename:
        return None
    try:
        with Image.open(upload.stream) as im:
            if im.format not in ('JPEG','PNG','WEBP') or im.width * im.height > 16000000:
                raise ValueError('Use a JPEG, PNG or WebP image under 16 megapixels.')
            im.load()
            name = secrets.token_hex(20) + '.jpg'
            im.convert('RGB').save(Path(current_app.config['UPLOAD_FOLDER']) / name, 'JPEG', quality=85)
            return name
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError('Please upload a valid image.') from None

def approve(claim):
    # Atomic compare-and-set serializes competing approvals on SQLite and SQL Server.
    result = db.session.execute(update(Listing).where(Listing.id == claim.listing_id, Listing.kind == 'found', Listing.status == 'open').values(status='claimed'))
    if result.rowcount != 1 or claim.status != 'pending':
        db.session.rollback()
        raise ValueError('This item is no longer available for approval.')
    claim.status = 'approved'
    db.session.execute(update(Claim).where(Claim.listing_id == claim.listing_id, Claim.id != claim.id, Claim.status == 'pending').values(status='rejected'))

def analytics():
    def groups(column):
        return db.session.query(column, func.count(Listing.id)).filter(Listing.status != 'hidden').group_by(column).order_by(func.count(Listing.id).desc()).all()
    counts = dict(groups(Listing.status))
    kinds = dict(groups(Listing.kind))
    return dict(total=sum(kinds.values()), lost=kinds.get('lost',0), found=kinds.get('found',0), returned=counts.get('returned',0), pending=db.session.query(Claim).filter_by(status='pending').count(), categories=groups(Listing.category), locations=groups(Listing.location), timeline=sorted(groups(Listing.event_date)))
