"""
Корневая конфигурация URL проекта «orders».

Все endpoints API доступны по префиксу /api/v1/ (см. backend/urls.py),
админка Django — по адресу /admin/,
интерактивная документация OpenAPI/Swagger — по адресу /api/docs/.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    # REST API приложения backend
    path('api/v1/', include('backend.urls', namespace='backend')),
    # Схема OpenAPI и интерактивная Swagger-документация
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
