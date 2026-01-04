# memorial/sitemaps.py
from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Memorial


class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = 'monthly'

    def items(self):
        return ['memorials:index', 'memorials:about', 'memorials:contact', 
                'memorials:browse', 'memorials:plans', 'memorials:privacy_policy', 
                'memorials:terms_and_conditions']

    def location(self, item):
        return reverse(item)
    
    def priority(self, item):
        priorities = {
            'memorials:index': 1.0,
            'memorials:browse': 0.9,
            'memorials:plans': 0.9,
            'memorials:about': 0.8,
            'memorials:contact': 0.8,
            'memorials:privacy_policy': 0.3,
            'memorials:terms_and_conditions': 0.3,
        }
        return priorities.get(item, 0.5)


class MemorialSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        # Only include public memorials
        # Adjust this filter based on your model - e.g., if you have an is_public field
        return Memorial.objects.all()

    def lastmod(self, obj):
        # Return the last modified date if you have one
        # If you have an 'updated_at' field, use that
        if hasattr(obj, 'updated_at'):
            return obj.updated_at
        return None

    def location(self, obj):
        return reverse('memorials:memorial_detail', kwargs={'pk': obj.pk})