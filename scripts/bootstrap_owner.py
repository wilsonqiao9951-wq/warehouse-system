"""Interactive first-owner setup; refuses to modify an already initialized service."""
import argparse,getpass
from uuid import uuid4
from sqlalchemy import select
from app.core.database import SessionLocal,Base,engine
from app.core.security import hash_password
from app.models import Organization,User,UserRole

def create_owner(db,email,password,organization):
    if db.scalar(select(User.id).limit(1)) is not None:raise ValueError('Service already has users; use normal account administration')
    if '@' not in email or not organization.strip() or len(password)<12:raise ValueError('Provide email, organization and a password of at least 12 characters')
    org=Organization(name=organization.strip(),slug='owner-'+uuid4().hex);db.add(org);db.flush()
    user=User(organization_id=org.id,name='Project owner',email=email.strip().lower(),password_hash=hash_password(password),role=UserRole.ADMIN,is_platform_admin=True,is_active=True);db.add(user);db.commit();return user.id

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--email',required=True);parser.add_argument('--organization',required=True);args=parser.parse_args()
    password=getpass.getpass('New owner password: ')
    if password!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords differ')
    Base.metadata.create_all(engine)
    with SessionLocal() as db:uid=create_owner(db,args.email,password,args.organization)
    print('Owner created; user ID:',uid)
if __name__=='__main__':main()
