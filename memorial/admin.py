from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.utils.html import format_html
from .models import Memorial, Tribute, GalleryImage, ContactMessage, Story


# --- Admin Registrations ---
admin.site.register(Tribute)
admin.site.register(Story)


# --- Inline Admin Classes ---
class GalleryImageInline(admin.TabularInline):
    """Inline editor for memorial gallery images."""
    model = GalleryImage
    extra = 1  # Number of empty image slots shown by default


class PlanStatusFilter(SimpleListFilter):
    """Custom filter for memorial plan status."""
    title = 'Plan Status'
    parameter_name = 'plan_status'

    def lookups(self, request, model_admin):
        return [
            ('has_plan', 'Has Plan'),
            ('no_plan', 'No Plan'),
            ('active_plan', 'Active Plan'),
            ('inactive_plan', 'Inactive Plan'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'has_plan':
            return queryset.filter(plan__isnull=False)
        if self.value() == 'no_plan':
            return queryset.filter(plan__isnull=True)
        if self.value() == 'active_plan':
            return queryset.filter(plan__is_active=True)
        if self.value() == 'inactive_plan':
            return queryset.filter(plan__is_active=False)
        return queryset


# --- Custom ModelAdmin Classes ---
@admin.register(Memorial)
class MemorialAdmin(admin.ModelAdmin):
    """Admin interface for Memorials with gallery inline."""
    inlines = [GalleryImageInline]

    # Fields to display in the list view
    list_display = [
        'memorial_name',
        'user',
        'plan_status',
        'current_plan',
        'gallery_count',
        'has_music',
        'has_custom_banner',
        'created_at'
    ]

    # Fields that can be filtered
    list_filter = [
        PlanStatusFilter,
        'plan',
        'created_at',
        'plan__allow_gallery',
        'plan__allow_music',
        'plan__allow_custom_banner'
    ]

    # Fields that can be searched
    search_fields = [
        'first_name',
        'last_name',
        'user__username',
        'user__email',
        'plan__name'
    ]

    # Readonly fields
    readonly_fields = ['created_at', 'gallery_count_display']

    # Fields to display in the edit form
    fieldsets = [
        ('Personal Information', {
            'fields': [
                'user',
                'first_name',
                'middle_name',
                'last_name',
                'date_of_birth',
                'date_of_death',
                'quote',
                'biography'
            ]
        }),
        ('Media & Appearance', {
            'fields': [
                'banner_type',
                'banner_value',
                'profile_picture',
                'audio_file',
                'qr_code'
            ]
        }),
        ('Subscription & Plan', {
            'fields': [
                'plan',
                'stripe_subscription_id',
                'gallery_count_display'
            ]
        }),
        ('System Information', {
            'fields': ['created_at'],
            'classes': ['collapse']
        })
    ]

    # Custom actions
    actions = ['assign_free_plan', 'assign_premium_plan']

    def memorial_name(self, obj):
        """Display full memorial name."""
        return f"{obj.first_name} {obj.last_name}"
    memorial_name.short_description = "Memorial Name"
    memorial_name.admin_order_field = 'first_name'

    def plan_status(self, obj):
        """Display plan status with colored indicators."""
        if obj.plan:
            color = 'green' if obj.plan.is_active else 'orange'
            status_text = "Active" if obj.plan.is_active else "Inactive"
            return format_html(
                '<span style="color: {};">●</span> {} Plan',
                color,
                status_text
            )
        return format_html('<span style="color: red;">●</span> No Plan')
    plan_status.short_description = "Plan Status"

    def current_plan(self, obj):
        """Display current plan name."""
        return obj.plan.name if obj.plan else "No Plan"
    current_plan.short_description = "Current Plan"
    current_plan.admin_order_field = 'plan__name'

    def gallery_count(self, obj):
        """Display gallery image count with limits."""
        count = obj.gallery.count()
        max_allowed = obj.max_gallery_images if obj.plan else 3

        if count > max_allowed:
            color = 'red'
            status = f"{count}/{max_allowed} (OVER)"
        elif count == max_allowed:
            color = 'orange'
            status = f"{count}/{max_allowed} (FULL)"
        else:
            color = 'green'
            status = f"{count}/{max_allowed}"

        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            status
        )
    gallery_count.short_description = "Gallery Usage"

    def gallery_count_display(self, obj):
        """Display gallery count in edit view."""
        count = obj.gallery.count()
        max_allowed = obj.max_gallery_images
        remaining = obj.remaining_gallery_slots
        return f"{count}/{max_allowed} ({remaining} slots remaining)"
    gallery_count_display.short_description = "Gallery Images"

    def has_music(self, obj):
        """Check if memorial has music feature."""
        if obj.plan and obj.plan.allow_music:
            if obj.audio_file:
                return format_html('<span style="color: green;">✓</span>')
            return format_html('<span style="color: orange;">⚠</span>')
        return format_html('<span style="color: red;">✗</span>')
    has_music.short_description = "Music"

    def has_custom_banner(self, obj):
        """Check if memorial has custom banner feature."""
        if obj.plan and obj.plan.allow_custom_banner:
            if obj.banner_type == 'image':
                return format_html('<span style="color: green;">✓</span>')
            return format_html('<span style="color: orange;">⚠</span>')
        return format_html('<span style="color: red;">✗</span>')
    has_custom_banner.short_description = "Custom Banner"

    def assign_free_plan(self, request, queryset):
        """Admin action to assign free plan to selected memorials."""
        from plans.models import Plan
        free_plan = Plan.objects.filter(price=0).first()

        if free_plan:
            updated = queryset.update(plan=free_plan)
            self.message_user(
                request,
                f'Assigned free plan to {updated} memorial(s).'
            )
        else:
            self.message_user(request, 'No free plan found.', level='error')
    assign_free_plan.short_description = "Assign Free Plan"

    def assign_premium_plan(self, request, queryset):
        """Admin action to assign first available premium plan."""
        from plans.models import Plan
        premium_plan = Plan.objects.filter(
            price__gt=0,
            is_active=True
        ).first()

        if premium_plan:
            updated = queryset.update(plan=premium_plan)
            self.message_user(
                request,
                f'Assigned {premium_plan.name} to {updated} memorial(s).'
            )
        else:
            self.message_user(
                request, 'No premium plans found.', level='error'
            )
    assign_premium_plan.short_description = "Assign Premium Plan"


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    """Admin interface for contact messages with enhanced list view."""
    list_display = ('name', 'email', 'subject', 'created_at', 'is_read')
    list_filter = ('is_read', 'created_at')
    search_fields = ('name', 'email', 'subject', 'message')
    readonly_fields = ('created_at',)
    list_editable = ('is_read',)
    date_hierarchy = 'created_at'
