from odoo import http
from odoo.http import request, Response
import json

class MainController(http.Controller):
    @http.route('/', type='http', auth='none', methods=['GET', 'HEAD', 'OPTIONS'], csrf=False)
    def index(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return Response(
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                    ('Access-Control-Max-Age', '86400'),  # Cache preflight for 24 hours
                ]
            )
        
        # For GET/HEAD requests, send redirect response with CORS headers
        return Response(
            status=303,  # See Other
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ('Access-Control-Allow-Credentials', 'true'),
                ('Location', '/web'),  # Redirect to Odoo web interface
            ]
        )