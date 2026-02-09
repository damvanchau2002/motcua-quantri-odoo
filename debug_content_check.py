
import sys
import logging
import base64
from odoo import api, SUPERUSER_ID

# Set up logging
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

def run(env):
    # Search for the attachment shown in the screenshot
    # Name starts with 3156b075-86a3-4951-9849
    name_pattern = '3156b075-86a3-4951-9849%'
    atts = env['ir.attachment'].sudo().search([('name', 'like', name_pattern)], limit=1)
    
    if not atts:
        print(f"No attachment found matching {name_pattern}")
        # Try searching by ID 456 from previous debug if it's the same
        atts = env['ir.attachment'].sudo().browse(456)
        if not atts.exists():
            print("Attachment 456 not found either.")
            return

    att = atts[0]
    print(f"\n--- Analyzing Attachment {att.id} ---")
    print(f"Name: {att.name}")
    print(f"Mimetype (DB): {att.mimetype}")
    print(f"File Size (DB): {att.file_size}")
    
    datas = att.datas
    if not datas:
        print("No datas content!")
        return
        
    file_content = base64.b64decode(datas)
    print(f"Actual Content Length: {len(file_content)} bytes")
    
    # Check first 20 bytes (Hex)
    header_hex = file_content[:20].hex()
    print(f"Header (Hex): {header_hex}")
    
    # Check text content if possible
    try:
        text_preview = file_content[:100].decode('utf-8')
        print(f"Text Preview: {text_preview}")
    except:
        print("Content is binary (not valid utf-8 text)")

    # Simulate magic bytes check
    def guess_mime(content):
         if content.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
         if content.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
         if content.startswith(b'GIF87a') or content.startswith(b'GIF89a'): return 'image/gif'
         if content.startswith(b'%PDF'): return 'application/pdf'
         if content.startswith(b'PK\x03\x04'): return 'application/zip'
         return None

    guessed = guess_mime(file_content)
    print(f"Guessed Mimetype: {guessed}")

if __name__ == '__main__':
    run(env)
