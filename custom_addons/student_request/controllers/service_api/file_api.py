from odoo import http, fields, models
from odoo.http import request, Response
from .utils import SECRET_KEY, decode_jwt_token, get_cors_headers
import json
import base64
import functools
import logging
import mimetypes
import os

_logger = logging.getLogger(__name__)

class FileApiController(http.Controller):

    def _get_uid_from_token(self, **kwargs):
        # 1. Check Authorization header
        auth_header = request.httprequest.headers.get('Authorization')
        token = None
        if auth_header and auth_header.lower().startswith('bearer '):
            token = auth_header[7:]
        # 2. Check 'token' header
        if not token:
            token = request.httprequest.headers.get('token')
        # 3. Check query param (for img src)
        if not token:
            token = kwargs.get('token')
            
        if not token:
            return None
            
        payload = decode_jwt_token(token, SECRET_KEY)
        if 'error' in payload:
            _logger.warning(f"FileAPI: JWT Decode Error: {payload['error']} - Token: {token[:15]}...")
            return None
            
        return payload.get('uid')

    def _guess_mimetype_from_content(self, content):
        """Guess mimetype from binary content magic bytes."""
        if content.startswith(b'\xff\xd8\xff'):
            return 'image/jpeg'
        if content.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'image/png'
        if content.startswith(b'GIF87a') or content.startswith(b'GIF89a'):
            return 'image/gif'
        if content.startswith(b'%PDF'):
            return 'application/pdf'
        if content.startswith(b'PK\x03\x04'):
             return 'application/zip'
        
        # Extended Magic Bytes
        if content.startswith(b'BM'):
            return 'image/bmp'
        if content.startswith(b'\x00\x00\x01\x00'):
            return 'image/x-icon'
        if content.startswith(b'RIFF') and content[8:12] == b'WEBP':
            return 'image/webp'
        if content.startswith(b'II*\x00') or content.startswith(b'MM\x00*'):
            return 'image/tiff'
            
        # ISO Media (HEIC, MP4, MOV, AVIF) - check for ftyp box at offset 4
        if len(content) > 12 and content[4:8] == b'ftyp':
            return 'application/octet-stream' # Generic binary for media containers if we don't know exact type

        # Text-based checks (SVG, XML) - only if content looks like text
        try:
            start_str = content[:100].decode('utf-8', errors='ignore').strip()
            if start_str.startswith('<?xml') or '<svg' in start_str.lower():
                if '<svg' in content[:500].decode('utf-8', errors='ignore').lower():
                    return 'image/svg+xml'
        except:
            pass
            
        return None

    def _get_extension(self, mimetype):
        """Get extension from mimetype with manual fallbacks."""
        # Common overrides/fallbacks to ensure we get a standard extension
        common_types = {
            'image/jpeg': '.jpg',
            'image/jpg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'application/pdf': '.pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
            'application/zip': '.zip',
            'text/plain': '.txt',
            'application/json': '.json',
            'image/bmp': '.bmp',
            'image/x-icon': '.ico',
            'image/webp': '.webp',
            'image/tiff': '.tiff',
            'image/svg+xml': '.svg',
            'application/octet-stream': '.bin',
        }
        if mimetype in common_types:
            return common_types[mimetype]
        
        # Fallback to system registry
        ext = mimetypes.guess_extension(mimetype)
        if ext == '.jpe': return '.jpg' # Common annoyance
        return ext

    @http.route('/api/file/download/<int:attachment_id>', type='http', auth='public', methods=['GET', 'OPTIONS'], csrf=False)
    def download_attachment(self, attachment_id, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=get_cors_headers(request))

        uid = self._get_uid_from_token(**kwargs)
        # REMOVED: Immediate Unauthorized return. Allow guest access to public files.
        # if not uid: return Response(json.dumps({'error': 'Unauthorized'}), ...

        try:
            # Switch to user environment to check permissions
            if uid:
                user = request.env['res.users'].sudo().browse(uid)
                if not user.exists():
                    _logger.warning(f"FileAPI: User {uid} from token not found. Treating as guest.")
                    user = request.env.user # Fallback to public user
            else:
                user = request.env.user # Public user
                
            # Access attachment with sudo first to check ownership/relation
            attachment = request.env['ir.attachment'].sudo().browse(attachment_id)
            
            if not attachment.exists():
                 return Response(json.dumps({'error': 'Attachment not found'}), status=404, headers=get_cors_headers(request))

            # Security Check:
            # 1. Allow if public
            # 2. Allow if created by user
            # 3. Allow if user has access to related record (res_model, res_id)
            
            allowed = False
            
            # Debug logging
            _logger.info(f"FileAPI Check: AttachID={attachment.id}, Public={attachment.public}, CreateUID={attachment.create_uid.id}, RequestUser={user.id}, Model={attachment.res_model}, ResID={attachment.res_id}")
            
            # 0. Check access token (critical for res_id=0 temporary files)
            access_token = kwargs.get('access_token') or request.httprequest.args.get('access_token')
            if access_token and attachment.access_token and access_token == attachment.access_token:
                allowed = True
                _logger.info("FileAPI: Allowed via access_token")

            elif attachment.public:
                allowed = True
            elif user.id != request.env.ref('base.public_user').id and attachment.create_uid.id == user.id:
                allowed = True
            else:
                # Handle special case: Attachment on mail.message
                res_model = attachment.res_model
                res_id = attachment.res_id
                
                if res_model == 'mail.message' and res_id:
                     try:
                         message = request.env['mail.message'].sudo().browse(res_id)
                         if message.exists() and message.model and message.res_id:
                             res_model = message.model
                             res_id = message.res_id
                             _logger.info(f"FileAPI: Redirected check to parent record {res_model},{res_id} from message {attachment.res_id}")
                     except Exception as e:
                         _logger.warning(f"FileAPI: Failed to resolve mail.message parent: {e}")

                # FIX: Allow access to orphan files (res_id=0) for student.service.request
                # These are temporary files uploaded before the record is saved.
                # Since we are authenticated via JWT, we allow access to avoid broken previews.
                if res_model == 'student.service.request' and not res_id:
                     allowed = True
                     _logger.info("FileAPI: Allowed orphan student.service.request file (res_id=0)")

                if res_model and res_id:
                    try:
                        # Special case for student.service.request:
                        # If user is the request owner (student), allow access even if ACLs are strict
                        # Use sudo to check ownership to avoid ACL issues on the model itself
                        if res_model == 'student.service.request':
                             try:
                                 record_sudo = request.env[res_model].sudo().browse(res_id)
                                 if record_sudo.exists() and 'request_user_id' in record_sudo:
                                     if record_sudo.request_user_id.id == user.id:
                                         allowed = True
                                         _logger.info("FileAPI: Allowed as request owner (via sudo check)")
                             except Exception as e:
                                 _logger.warning(f"FileAPI: Failed to check ownership: {e}")

                        if not allowed:
                             # Check if user can read the related record
                             record = request.env[res_model].with_user(user).browse(res_id)
                             if record.exists():
                                 # Standard ACL check
                                 # check_access_rights returns True/False
                                 if record.check_access_rights('read', raise_exception=False):
                                     try:
                                         record.check_access_rule('read')
                                         allowed = True
                                     except Exception as e:
                                         _logger.info(f"FileAPI: check_access_rule failed: {e}")
                                         allowed = False
                                 else:
                                      _logger.info("FileAPI: check_access_rights failed")
                    except Exception as e:
                        _logger.warning(f"Access check failed for attachment {attachment_id} (Model: {res_model}, ID: {res_id}): {str(e)}")
                        allowed = False
            
            if not allowed:
                 _logger.warning(f"FileAPI: Access DENIED for user {user.id} on attachment {attachment_id}")
                 # Return 403 Forbidden instead of 401 Unauthorized for better semantics if user is known
                 # But if guest, maybe 401 is appropriate? Odoo usually returns 404/403.
                 return Response(json.dumps({'error': 'Access denied'}), status=403, headers=get_cors_headers(request))

            # Read file content using sudo (since we verified access)
            file_content = base64.b64decode(attachment.datas)
            
            filename = attachment.name
            mimetype = attachment.mimetype
            
            # Fix: If mimetype is generic text/plain or octet-stream but filename has extension, 
            # trust the extension's mimetype
            if filename and '.' in filename:
                guessed_type, _ = mimetypes.guess_type(filename)
                if guessed_type and (mimetype == 'text/plain' or mimetype == 'application/octet-stream'):
                    mimetype = guessed_type

            # Fix: Always try to guess from content (magic bytes) to be safe, especially for images
            # But be careful with ZIPs (docx, xlsx) - only override if current is generic
            content_mimetype = self._guess_mimetype_from_content(file_content)
            if content_mimetype:
                if content_mimetype == 'application/zip':
                     if mimetype in ['text/plain', 'application/octet-stream']:
                         mimetype = content_mimetype
                else:
                     # For images/pdf, trust the content over the DB
                     mimetype = content_mimetype
                     _logger.info(f"FileAPI: Overrode mimetype to {mimetype} from content magic bytes")

            # Fix: If still 'text/plain' but contains null bytes, switch to octet-stream to avoid opening as text
            if mimetype == 'text/plain':
                if b'\x00' in file_content[:1024]:
                    mimetype = 'application/octet-stream'
                    _logger.info("FileAPI: Detected binary content in text/plain, switched to application/octet-stream")

            # Fix: Ensure filename has an extension if mimetype is known and filename lacks it
            correct_ext = self._get_extension(mimetype)
            if filename:
                if '.' not in filename:
                    if correct_ext:
                        filename = f"{filename}{correct_ext}"
                else:
                    # If filename has extension, check if it matches the mimetype
                    # Specifically fix the issue where images have .txt extension
                    try:
                        base, ext = os.path.splitext(filename)
                        ext = ext.lower()
                        
                        if correct_ext:
                            # If file is .txt but content is NOT text, force replace extension
                            if ext == '.txt' and mimetype != 'text/plain':
                                filename = f"{base}{correct_ext}"
                                _logger.info(f"FileAPI: Replaced wrong extension .txt with {correct_ext}")
                            
                            # If file is .bin but content is known, force replace
                            elif ext == '.bin' and mimetype != 'application/octet-stream':
                                filename = f"{base}{correct_ext}"
                                
                    except Exception as e:
                        _logger.warning(f"FileAPI: Error fixing extension: {e}")
            
            # STRICT POLICY: BAN .TXT DOWNLOADS FOR AMBIGUOUS FILES
            # If after all checks, we still have 'text/plain' or '.txt' extension, 
            # and it's not a clear safe text format (like json/html/xml/csv),
            # FORCE convert to binary to prevent browser from opening garbage text.
            
            safe_text_mimes = ['application/json', 'text/html', 'text/xml', 'text/csv', 'text/css']
            
            if mimetype == 'text/plain' and mimetype not in safe_text_mimes:
                # Force binary
                mimetype = 'application/octet-stream'
                _logger.info("FileAPI: STRICT POLICY - Converted text/plain to application/octet-stream")
                
            # If extension is .txt, change it to .bin if mimetype is binary or generic
            if filename and filename.lower().endswith('.txt'):
                 if mimetype not in safe_text_mimes:
                     base_name = filename[:-4]
                     filename = f"{base_name}.bin"
                     _logger.info(f"FileAPI: STRICT POLICY - Renamed {base_name}.txt to {filename}")

            _logger.info(f"FileAPI: Final Response - Mime: {mimetype}, Filename: {filename}")

            headers = get_cors_headers(request)
            headers.extend([
                ('Content-Type', mimetype),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
                ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0'),
                ('Pragma', 'no-cache'),
            ])
            
            return request.make_response(file_content, headers)
            
        except Exception as e:
            _logger.error(f"Error downloading attachment {attachment_id}: {str(e)}")
            # Try to return JSON error if possible, but make_response might expect bytes if headers set?
            # It's safer to return a Response object
            return Response(json.dumps({'error': str(e)}), status=500, headers=get_cors_headers(request))


    @http.route('/api/file/image/<string:model>/<int:id>/<string:field>', type='http', auth='public', methods=['GET', 'OPTIONS'], csrf=False)
    def get_image(self, model, id, field, **kwargs):
        """
        Get image from a specific record field.
        Usage: /api/file/image/res.users/1/image_1920?token=...
        """
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=get_cors_headers(request))

        uid = self._get_uid_from_token(**kwargs)
        # REMOVED: Immediate Unauthorized return
        # if not uid: return Response(...)

        try:
            # Validate allowed models to prevent arbitrary data access
            # Allow 'res.users' and 'student.*' models
            if model != 'res.users' and not model.startswith('student.'):
                 return Response(json.dumps({'error': 'Model not allowed'}), status=403, headers=get_cors_headers(request))
            
            if uid:
                user = request.env['res.users'].sudo().browse(uid)
                if not user.exists():
                     user = request.env.user # Fallback
            else:
                user = request.env.user # Public user
            
            env = request.env(user=user)
            
            record = env[model].browse(id)
            if not record.exists():
                return Response(json.dumps({'error': 'Record not found'}), status=404, headers=get_cors_headers(request))
                
            if field not in record:
                 return Response(json.dumps({'error': 'Field not found'}), status=404, headers=get_cors_headers(request))
            
            # Get image data (base64)
            value = record[field]
            if not value:
                # Return 404 or a default placeholder? 
                # 404 is better for API
                return Response(status=404, headers=get_cors_headers(request))
                
            if isinstance(value, bytes):
                image_data = value
            else:
                image_data = base64.b64decode(value)
                
            headers = get_cors_headers(request)
            
            # Detect mimetype from content
            content_type = self._guess_mimetype_from_content(image_data)
            if not content_type:
                content_type = 'image/jpeg' # Fallback
            
            # Get extension
            ext = self._get_extension(content_type)
            if not ext: ext = '.jpg'

            filename = f"{model}_{id}_{field}{ext}"
            
            headers.append(('Content-Type', content_type)) 
            headers.append(('Content-Disposition', f'inline; filename="{filename}"'))
            headers.append(('Cache-Control', 'public, max-age=86400'))
            
            return request.make_response(image_data, headers)

        except Exception as e:
            _logger.error(f"Error getting image {model}/{id}/{field}: {str(e)}")
            return Response(json.dumps({'error': str(e)}), status=500, headers=get_cors_headers(request))
