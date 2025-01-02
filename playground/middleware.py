from django.http import JsonResponse
from .models import Users, APIRequest
import time

class APIRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        public_paths = [
            '/api/update-subscription',
            '/api/update-subscription/',
            '/user/sendverificationlink',
            '/user/verifyemail',
            '/dashboard/',
            '/health',
            '/admin',
            '/subscription/',
            '/docs',
            '/user'
        ]

        # Check if current path matches any public path
        current_path = request.path.rstrip('/')
        if any(current_path.startswith(path) for path in public_paths):
            return self.get_response(request)

        # API key validation for protected paths
        api_key = request.headers.get('X-API-KEY')
        
        if not api_key:
            return JsonResponse({
                "status": "Fail",
                "message": "API key is required"
            }, status=401)
            
        try:
            user = Users.objects.get(api_key=api_key, is_active=True)
        except Users.DoesNotExist:
            return JsonResponse({
                "status": "Fail",
                "message": "Invalid API key"
            }, status=401)
            
        # Process request and record metrics only for /api/test/ endpoint
        start_time = time.time()
        response = self.get_response(request)
        
        # Only save metrics for /api/test/ endpoint
        if current_path == '/api/test':
            response_time = time.time() - start_time
            APIRequest.objects.create(
                user=user,
                endpoint=request.path,
                status_code=response.status_code,
                response_time=response_time
            )
        
        return response