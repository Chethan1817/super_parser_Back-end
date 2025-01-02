from django.urls import path
from . import views

urlpatterns = [
    path('sendverificationlink/', views.send_verification_link, name='send_verification_link'),
    path('verifyemail/', views.verify_email, name='verify_email'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('subscription/', views.fetch_subscription, name='fetch_subscription'),
    path('update-subscription/', views.update_subscription, name='update_subscription'),
    path('test/', views.test_api, name='test_api'),
]
