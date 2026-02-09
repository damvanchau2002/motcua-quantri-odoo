
import sys
import logging
import requests
import jwt
from datetime import datetime, timedelta
from odoo import api, SUPERUSER_ID

# Set up logging
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

SECRET_KEY = 'access-motcua-student-service-maiatech'

def generate_token(uid):
    payload = {
        'uid': uid,
        'exp': datetime.utcnow() + timedelta(days=30),
        'app': 'student_service_maiatech',
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

def run(env):
    # 1. Find the attachment
    name_pattern = '3156b075-86a3-4951-9849%'
    atts = env['ir.attachment'].sudo().search([('name', 'like', name_pattern)], limit=1)
    
    if not atts:
        print(f"No attachment found matching {name_pattern}")
        return

    att = atts[0]
    print(f"Testing Attachment ID: {att.id}")
    print(f"Name in DB: {att.name}")
    print(f"Mime in DB: {att.mimetype}")
    
    # 2. Generate Token for admin (ID 2)
    token = generate_token(2)
    
    # 3. Call API
    url = f"http://localhost:8069/api/file/download/{att.id}?token={token}"
    print(f"\nCalling URL: {url}")
    
    try:
        response = requests.get(url, allow_redirects=False)
        print(f"Status Code: {response.status_code}")
        print("Headers:")
        for k, v in response.headers.items():
            print(f"  {k}: {v}")
            
        print(f"\nFirst 20 bytes of content: {response.content[:20]}")
        
    except Exception as e:
        print(f"Error calling API: {e}")

if __name__ == '__main__':
    run(env)
