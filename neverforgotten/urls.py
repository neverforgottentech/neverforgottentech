from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from memorial.sitemaps import StaticViewSitemap, MemorialSitemap

sitemaps = {
    'static': StaticViewSitemap,
    'memorials': MemorialSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps},
         name='django.contrib.sitemaps.views.sitemap'),
    
    path('', include('memorial.urls')),
    path('plans/', include('plans.urls')),
    path('newsletter/', include('newsletter.urls', namespace='newsletter')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)