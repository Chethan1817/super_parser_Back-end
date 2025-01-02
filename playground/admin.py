from django.contrib import admin
from .models import Users, UserSubscription, SubscriptionPlan, APIRequest

admin.site.register(Users)
admin.site.register(UserSubscription)
admin.site.register(SubscriptionPlan)
admin.site.register(APIRequest)