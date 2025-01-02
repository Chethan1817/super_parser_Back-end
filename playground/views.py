from urllib.request import Request
import jwt
import uuid
import json
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db.models import Count
from datetime import datetime, timedelta
from django.conf import settings
from playground.apisix_subscription_manager import APISIXSubscriptionManager
from .models import Users, UserSubscription, SubscriptionPlan, APIRequest
from django.template.loader import render_to_string
from django.utils.html import strip_tags

def generate_verification_token(email):
    payload = {
        'email': email,
        'exp': timezone.now() + timezone.timedelta(hours=1),  
        'token_type': 'email_verification'
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')


def test_service(request):
    return JsonResponse({"message": "Service is running!"})


def send_verification_email(email, verification_token):
    verification_link = f"{settings.FRONTEND_URL}/verify-email?token={verification_token}"
    
    # Updated template path
    html_message = render_to_string('email/verification.html', {
        'verification_link': verification_link
    })
    
    plain_message = strip_tags(html_message)
    
    try:
        send_mail(
            subject="Verify Your SuperParser Account",
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            html_message=html_message
        )
        return True
    except Exception as e:
        print(f"Email sending failed: {e}")
        return False
    
@csrf_exempt
@require_http_methods(["POST"])
def send_verification_link(request):
    try:
        data = json.loads(request.body)
        email = data.get('email', '').strip()
        validate_email(email)
        user, created = Users.objects.get_or_create(
            email=email,
            defaults={
                'created_at': timezone.now(),
                'updated_at': timezone.now(),
                'is_active': False,
                'api_key': str(uuid.uuid4())
            }
        )
        verification_token = generate_verification_token(email)
        email_sent = send_verification_email(email, verification_token)

        if email_sent:
            return JsonResponse({
                "status": "success", 
                "message": f"Verification link sent to {email}"
            })
        else:
            return JsonResponse({
                "status": "Fail", 
                "Message": "Email server issues"
            }, status=500)

    except ValidationError:
        return JsonResponse({
            "status": "Fail", 
            "Message": "Invalid email address"
        }, status=400)
    except Exception as e:
        return JsonResponse({
            "status": "Fail", 
            "Message": str(e)
        }, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def verify_email(request):
    try:
        token = request.GET.get('token', '')
        
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        
        if payload.get('token_type') != 'email_verification':
            raise ValueError("Invalid token type")
        
        if payload.get('exp') < timezone.now().timestamp():
            raise ValueError("Token has expired")
        
        email = payload.get('email')
        
        # Create or get user
        user, user_created = Users.objects.get_or_create(
            email=email,
            defaults={
                'created_at': timezone.now(),
                'updated_at': timezone.now(),
                'is_active': True,
                'api_key': str(uuid.uuid4())
            }
        )
        
        if not user.api_key:
            user.api_key = str(uuid.uuid4())
            user.updated_at = timezone.now()
            user.save()
        
        if not user.is_active:
            user.is_active = True
            user.updated_at = timezone.now()
            user.save()

        # Create APISIX consumer first
        manager = APISIXSubscriptionManager()
        success, error = manager.create_or_update_consumer(email, user.api_key, "free")
        if not success:
            print(f"Warning: Failed to create initial APISIX consumer: {error}")

        # If user was just created or doesn't have an active subscription, create free subscription
        try:
            subscription = UserSubscription.objects.get(user=user, is_active=True)
        except UserSubscription.DoesNotExist:
            # Get free plan - get the one with lowest price in case of duplicates
            free_plan = SubscriptionPlan.objects.filter(
                name='free'
            ).order_by('price', 'id').first()
            
            if not free_plan:
                raise SubscriptionPlan.DoesNotExist("Free plan not found")
            
            # Create subscription with 30 days validity
            subscription = UserSubscription.objects.create(
                user=user,
                plan=free_plan,
                start_date=timezone.now(),
                end_date=timezone.now() + timedelta(days=30),
                is_active=True
            )
        
        jwt_token = generate_jwt_token(user)
        
        return JsonResponse({
            "status": "True", 
            "Data": {
                "user_id": user.id,
                "created_at": user.created_at.isoformat(),
                "is_active": user.is_active,
                "api_key": user.api_key,
                "user_created": user_created,
                "subscription": {
                    "plan": subscription.plan.name,
                    "end_date": subscription.end_date.isoformat()
                },
                "past_data": user.requests.exists(),
                "jwt_token": jwt_token
            }
        })
    
    except jwt.ExpiredSignatureError:
        return JsonResponse({
            "status": "Fail", 
            "Message": "Token has expired"
        }, status=400)
    
    except (jwt.InvalidTokenError, ValueError):
        return JsonResponse({
            "status": "Fail", 
            "Message": "Invalid or expired token"
        }, status=400)
    except SubscriptionPlan.DoesNotExist:
        return JsonResponse({
            "status": "Fail", 
            "Message": "Free subscription plan not found"
        }, status=500)
    except Exception as e:
        return JsonResponse({
            "status": "Fail", 
            "Message": str(e)
        }, status=500)
    
def generate_jwt_token(user):
    payload = {
        'user_id': user.id,
        'email': user.email,
        'exp': timezone.now() + timezone.timedelta(days=80)
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

def verify_jwt_token(token):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        return payload
    except Exception:
        return None

@csrf_exempt
@require_http_methods(["GET"])
def dashboard(request):
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer '):
        return JsonResponse({
            "status": "Fail", 
            "Message": "Invalid or missing token"
        }, status=401)
    
    token = auth_header.split(' ')[1]
    
    payload = verify_jwt_token(token)
    if not payload:
        return JsonResponse({
            "status": "Fail", 
            "Message": "Invalid or expired token"
        }, status=401)
    
    user_id = payload.get('user_id')
    
    try:
        user = Users.objects.get(id=user_id)
        
        # Get API key info
        api_key_response = {
            "status": "True", 
            "Data": {
                "api_key": user.api_key
            }
        }
        
        # Get current time and 30 days ago
        now = timezone.now()
        thirty_days_ago = now - timedelta(days=30)
        
        # Get monthly requests - only for /api/test/
        monthly_requests = APIRequest.objects.filter(
            user_id=user_id, 
            created_at__gte=thirty_days_ago,
            endpoint__startswith='/api/test/'
        )
        
        total_test_requests = monthly_requests.count()
        
        total_requests_response = {
            "status": "True", 
            "Data": {
                "total_requests": total_test_requests,
                "request_types": {
                    "/api/test/": total_test_requests
                }
            }
        }
        
        # Get daily requests for the last 30 days
        daily_requests = {}
        for i in range(30):
            day_date = now - timedelta(days=i)
            day_start = day_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            
            requests_count = APIRequest.objects.filter(
                user_id=user_id,
                created_at__gte=day_start,
                created_at__lt=day_end,
                endpoint__startswith='/api/test/'
            ).count()
            
            # Format date as YYYY-MM-DD
            date_key = day_start.strftime('%Y-%m-%d')
            daily_requests[date_key] = requests_count
        
        # Sort the daily requests by date
        sorted_daily_requests = dict(sorted(daily_requests.items()))
        
        daily_requests_response = {
            "status": "True", 
            "Data": {
                "requests_by_day": sorted_daily_requests
            }
        }
        
        # Get subscription info
        try:
            user_subscription = UserSubscription.objects.get(
                user=user,
                is_active=True
            )
            subscription_response = {
                "status": "True", 
                "Data": {
                    "subscription": {
                        "plan": user_subscription.plan.name,
                        "limit": user_subscription.plan.monthly_limit,
                        "end_date": user_subscription.end_date.isoformat()
                    }
                }
            }
        except UserSubscription.DoesNotExist:
            subscription_response = {
                "status": "Fail", 
                "Message": "No active subscription found"
            }
        
        return JsonResponse({
            "status": "True",
            "Data": {
                "api_key": api_key_response["Data"],
                "total_requests": total_requests_response["Data"],
                "requests_by_day": daily_requests_response["Data"],
                "subscription": subscription_response["Data"]["subscription"] if subscription_response["status"] == "True" else None
            }
        })

    except Users.DoesNotExist:
        return JsonResponse({
            "status": "Fail", 
            "Message": "User not found"
        }, status=404)
    except Exception as e:
        return JsonResponse({
            "status": "Fail", 
            "Message": str(e)
        }, status=500)@csrf_exempt
@require_http_methods(["GET"])
def dashboard(request):
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer '):
        return JsonResponse({
            "status": "Fail", 
            "Message": "Invalid or missing token"
        }, status=401)
    
    token = auth_header.split(' ')[1]
    
    payload = verify_jwt_token(token)
    if not payload:
        return JsonResponse({
            "status": "Fail", 
            "Message": "Invalid or expired token"
        }, status=401)
    
    user_id = payload.get('user_id')
    
    try:
        user = Users.objects.get(id=user_id)
        
        # Get API key info
        api_key_response = {
            "status": "True", 
            "Data": {
                "api_key": user.api_key
            }
        }
        
        # Get current time and 30 days ago
        now = timezone.now()
        thirty_days_ago = now - timedelta(days=30)
        
        # Get monthly requests - only for /api/test/
        monthly_requests = APIRequest.objects.filter(
            user_id=user_id, 
            created_at__gte=thirty_days_ago,
            endpoint__startswith='/api/test/'
        )
        
        total_test_requests = monthly_requests.count()
        
        total_requests_response = {
            "status": "True", 
            "Data": {
                "total_requests": total_test_requests,
                "request_types": {
                    "/api/test/": total_test_requests
                }
            }
        }
        
        # Get daily requests for the last 30 days
        daily_requests = {}
        for i in range(30):
            day_date = now - timedelta(days=i)
            day_start = day_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            
            requests_count = APIRequest.objects.filter(
                user_id=user_id,
                created_at__gte=day_start,
                created_at__lt=day_end,
                endpoint__startswith='/api/test/'
            ).count()
            
            # Format date as YYYY-MM-DD
            date_key = day_start.strftime('%Y-%m-%d')
            daily_requests[date_key] = requests_count
        
        # Sort the daily requests by date
        sorted_daily_requests = dict(sorted(daily_requests.items()))
        
        daily_requests_response = {
            "status": "True", 
            "Data": {
                "requests_by_day": sorted_daily_requests
            }
        }
        
        # Get subscription info
        try:
            user_subscription = UserSubscription.objects.get(
                user=user,
                is_active=True
            )
            subscription_response = {
                "status": "True", 
                "Data": {
                    "subscription": {
                        "plan": user_subscription.plan.name,
                        "limit": user_subscription.plan.monthly_limit,
                        "end_date": user_subscription.end_date.isoformat()
                    }
                }
            }
        except UserSubscription.DoesNotExist:
            subscription_response = {
                "status": "Fail", 
                "Message": "No active subscription found"
            }
        
        return JsonResponse({
            "status": "True",
            "Data": {
                "api_key": api_key_response["Data"],
                "total_requests": total_requests_response["Data"],
                "requests_by_day": daily_requests_response["Data"],
                "subscription": subscription_response["Data"]["subscription"] if subscription_response["status"] == "True" else None
            }
        })

    except Users.DoesNotExist:
        return JsonResponse({
            "status": "Fail", 
            "Message": "User not found"
        }, status=404)
    except Exception as e:
        return JsonResponse({
            "status": "Fail", 
            "Message": str(e)
        }, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def fetch_subscription(request):
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer '):
        return JsonResponse({
            "status": "Fail", 
            "Message": "Invalid or missing token"
        }, status=401)
    
    token = auth_header.split(' ')[1]
    
    payload = verify_jwt_token(token)
    if not payload:
        return JsonResponse({
            "status": "Fail", 
            "Message": "Invalid or expired token"
        }, status=401)
    
    user_id = payload.get('user_id')
    
    try:
        user = Users.objects.get(id=user_id)
        user_subscription = UserSubscription.objects.get(
            user=user,
            is_active=True
        )
        
        # Get the current month's usage
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_usage = APIRequest.objects.filter(
            user=user,
            created_at__gte=month_start
        ).count()
        
        return JsonResponse({
            "status": "True",
            "Data": {
                "subscription": {
                    "plan": user_subscription.plan.name,
                    "monthly_limit": user_subscription.plan.monthly_limit,
                    "current_usage": current_usage,
                    "rate_limit": user_subscription.plan.rate_limit,
                    "start_date": user_subscription.start_date.isoformat(),
                    "end_date": user_subscription.end_date.isoformat(),
                    "is_active": user_subscription.is_active,
                    "price": float(user_subscription.plan.price),
                    "excess_usage_price": float(user_subscription.plan.excess_usage_price)
                }
            }
        })
        
    except Users.DoesNotExist:
        return JsonResponse({
            "status": "Fail",
            "Message": "User not found"
        }, status=404)
        
    except UserSubscription.DoesNotExist:
        # If no active subscription exists, return information about the free plan
        try:
            free_plan = SubscriptionPlan.objects.filter(name='free').first()
            if free_plan:
                return JsonResponse({
                    "status": "True",
                    "Data": {
                        "subscription": {
                            "plan": free_plan.name,
                            "monthly_limit": free_plan.monthly_limit,
                            "current_usage": 0,
                            "rate_limit": free_plan.rate_limit,
                            "is_active": False,
                            "price": float(free_plan.price),
                            "excess_usage_price": float(free_plan.excess_usage_price)
                        }
                    }
                })
            else:
                return JsonResponse({
                    "status": "Fail",
                    "Message": "No subscription plans available"
                }, status=404)
        except Exception as e:
            return JsonResponse({
                "status": "Fail",
                "Message": f"Error fetching free plan: {str(e)}"
            }, status=500)
        
    except Exception as e:
        return JsonResponse({
            "status": "Fail",
            "Message": str(e)
        }, status=500)



### Testing ### 

@csrf_exempt
@require_http_methods(["GET"])
def test_api(request):
    return JsonResponse({
        "status": "success",
        "message": "API request successful",
        "timestamp": timezone.now().isoformat()
    })


### Update subscription plan API #####
# playground/views.py

@csrf_exempt
@require_http_methods(["POST"])
def update_subscription(request):
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer '):
        return JsonResponse({
            "status": "Fail", 
            "message": "Invalid or missing token"
        }, status=401)
    
    token = auth_header.split(' ')[1]
    
    payload = verify_jwt_token(token)
    if not payload:
        return JsonResponse({
            "status": "Fail", 
            "message": "Invalid or expired token"
        }, status=401)
    
    try:
        data = json.loads(request.body)
        plan_name = data.get('plan')  # Should be "basic", "advance", or "premium"
        
        if not plan_name:
            return JsonResponse({
                "status": "Fail",
                "message": "Plan name is required"
            }, status=400)
        
        # Validate plan name
        if plan_name not in ["basic", "advance", "premium"]:
            return JsonResponse({
                "status": "Fail",
                "message": "Invalid plan. Choose from: basic, advance, premium"
            }, status=400)
        
        user_id = payload.get('user_id')
        user = Users.objects.get(id=user_id)
        
        # Get the plan
        new_plan = SubscriptionPlan.objects.get(name=plan_name)
        
        # Update or create subscription
        subscription, created = UserSubscription.objects.update_or_create(
            user=user,
            defaults={
                'plan': new_plan,
                'start_date': timezone.now(),
                'end_date': timezone.now() + timedelta(days=30),
                'is_active': True
            }
        )
        
        # Update APISIX configuration
        manager = APISIXSubscriptionManager()
        success, error = manager.create_or_update_consumer(
            user.email, 
            user.api_key, 
            new_plan.name
        )
        
        if not success:
            return JsonResponse({
                "status": "Fail",
                "message": f"Failed to update API limits: {error}"
            }, status=500)
        
        return JsonResponse({
            "status": "success",
            "message": f"Successfully subscribed to {new_plan.name} plan",
            "data": {
                "plan_name": new_plan.name,
                "monthly_limit": new_plan.monthly_limit,
                "rate_limit": f"{new_plan.rate_limit} calls/sec",
                "price": f"${float(new_plan.price)}/mo",
                "excess_usage_price": f"${float(new_plan.excess_usage_price)}/call",
                "valid_until": subscription.end_date.isoformat()
            }
        })
        
    except Users.DoesNotExist:
        return JsonResponse({
            "status": "Fail",
            "message": "User not found"
        }, status=404)
    except SubscriptionPlan.DoesNotExist:
        return JsonResponse({
            "status": "Fail",
            "message": "Invalid subscription plan"
        }, status=404)
    except Exception as e:
        return JsonResponse({
            "status": "Fail",
            "message": str(e)
        }, status=500)