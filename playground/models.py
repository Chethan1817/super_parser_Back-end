from django.db import models
from django.utils import timezone

from playground.apisix_subscription_manager import APISIXSubscriptionManager

class Users(models.Model):
    email = models.EmailField(unique=True)
    api_key = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)


class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=50)  # basic, advance, premium
    monthly_limit = models.IntegerField()   # 500, 2000, 5000 credits
    rate_limit = models.IntegerField()      # 5 calls/sec for all plans
    price = models.DecimalField(max_digits=10, decimal_places=2)  # 50, 100, 250
    excess_usage_price = models.DecimalField(max_digits=10, decimal_places=2)  # 0.1, 0.05, 0.05

    def __str__(self):
        return f"{self.name} - {self.monthly_limit} credits/month"

class UserSubscription(models.Model):
    user = models.OneToOneField(Users, on_delete=models.CASCADE, related_name='subscription')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    
    def save(self, *args, **kwargs):
        is_new = self.pk is None  # Check if this is a new subscription
        super().save(*args, **kwargs)  # Save first
        
        # Update APISIX configuration after saving
        if is_new or self.is_active:  # Only update APISIX for new or active subscriptions
            manager = APISIXSubscriptionManager()
            success, error = manager.create_or_update_consumer(
                self.user.email, 
                self.user.api_key, 
                self.plan.name
            )
            if not success:
                print(f"Warning: Failed to update APISIX subscription: {error}")
                
class APIRequest(models.Model):
    user = models.ForeignKey(Users, on_delete=models.CASCADE, related_name='requests')
    endpoint = models.CharField(max_length=255)
    status_code = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    response_time = models.FloatField(null=True)