from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView


urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),

    path('sitemap.xml', TemplateView.as_view(
        template_name='sitemap.xml', 
        content_type='application/xml'
    )),

    path('', include('memorial.urls')),

    path('plans/', include('plans.urls')),

    # Newsletter app with namespace
    path('newsletter/', include('newsletter.urls', namespace='newsletter')),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.STATIC_URL, document_root=settings.STATIC_ROOT
    )
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
