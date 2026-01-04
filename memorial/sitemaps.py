# memorial/sitemaps.py
from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Memorial


class StaticViewSitemap(Sitemap):
    changefreq = 'monthly'

    def items(self):
        return [
            ('memorials:index', 1.0),
            ('memorials:about', 0.8),
            ('memorials:contact', 0.8),
            ('memorials:browse', 0.9),
            ('memorials:plans', 0.9),
            ('memorials:privacy_policy', 0.3),
            ('memorials:terms_and_conditions', 0.3),
        ]

    def location(self, item):
        return reverse(item[0])
    
    def priority(self, item):
        return item[1]


class MemorialSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        return Memorial.objects.all()

    def lastmod(self, obj):
        return obj.created_at

    def location(self, obj):
        return reverse('memorials:memorial_detail', kwargs={'pk': obj.pk})