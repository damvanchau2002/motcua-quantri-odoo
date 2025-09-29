from odoo import http
from odoo.http import request, Response
import requests
import logging

_logger = logging.getLogger(__name__)

class ImageProxyController(http.Controller):
    @http.route('/api/proxy/image', type='http', auth='public', methods=['GET', 'OPTIONS'], csrf=False)
    def proxy_image(self, url=None, **kwargs):
        """
        Proxy endpoint to fetch images from external domains and add CORS headers
        Example usage: /api/proxy/image?url=http://ql.ktxhcm.edu.vn/SharedData/HinhSV/image.jpg
        """
        if request.httprequest.method == 'OPTIONS':
            return Response(
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                    ('Access-Control-Max-Age', '86400'),
                ]
            )

        if not url:
            return Response(
                json.dumps({'error': 'URL parameter is required'}),
                content_type='application/json',
                status=400,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )

        try:
            # Only allow images from trusted domains
            allowed_domains = ['ql.ktxhcm.edu.vn']
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            if parsed_url.netloc not in allowed_domains:
                return Response(
                    json.dumps({'error': 'Domain not allowed'}),
                    content_type='application/json',
                    status=403,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true'),
                    ]
                )

            # Fetch the image
            response = requests.get(url, stream=True)
            response.raise_for_status()

            # Return the image with CORS headers
            return Response(
                response.content,
                content_type=response.headers.get('Content-Type', 'image/jpeg'),
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                    ('Cache-Control', 'public, max-age=86400'),  # Cache images for 24 hours
                ]
            )

        except Exception as e:
            _logger.error(f"Error proxying image: {str(e)}")
            return Response(
                json.dumps({'error': str(e)}),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )