from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('user/', include('playground.urls')),  # Include playground URLs under user/
    path('api/', include('playground.urls')),   # Include playground URLs under api/
    path('', include('playground.urls')),       # Include playground URLs at root level
]