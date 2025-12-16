# plans/admin.py
from django.contrib import admin
from .models import Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    """Admin configuration for the Plan model"""

    # Fields to display in the list view
    list_display = [
        'name',
        'price',
        'billing_cycle',
        'is_active',
        'allow_gallery',
        'allow_music',
        'allow_custom_banner'
    ]

    # Fields that can be filtered in the admin
    list_filter = [
        'is_active',
        'billing_cycle',
        'allow_gallery',
        'allow_music',
        'allow_custom_banner'
    ]

    # Fields that can be searched
    search_fields = ['name', 'description']

    # Fields to display in the edit form with grouping
    fieldsets = [
        ('Basic Information', {
            'fields': [
                'name',
                'description',
                'price',
                'billing_cycle',
                'is_active'
            ]
        }),
        ('Stripe Integration', {
            'fields': [
                'stripe_price_id',
            ],
            'classes': ['collapse']
        }),
        ('Feature Flags', {
            'fields': [
                'allow_gallery',
                'allow_music',
                'allow_custom_banner'
            ],
            'description': 'Toggle available features for this plan'
        })
    ]

    # Order plans by price in admin
    ordering = ['price']

    # Actions you can perform on multiple plans
    actions = ['activate_plans', 'deactivate_plans']

    def activate_plans(self, request, queryset):
        """Admin action to activate selected plans"""
        updated = queryset.update(is_active=True)
        self.message_user(
            request, f'{updated} plans activated successfully.'
        )

    activate_plans.short_description = "Activate selected plans"

    def deactivate_plans(self, request, queryset):
        """Admin action to deactivate selected plans"""
        updated = queryset.update(is_active=False)
        self.message_user(
            request, f'{updated} plans deactivated successfully.'
        )

    deactivate_plans.short_description = "Deactivate selected plans"


# Custom admin site header and title
admin.site.site_header = 'NeverForgotten Admin'
admin.site.site_title = 'NeverForgotten Administration'
admin.site.index_title = 'Welcome to NeverForgotten Admin'
