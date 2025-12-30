"""
Views for NeverForgotten application.
Handles memorial creation, management, and all related functionality.
"""

# Standard Library
from datetime import datetime, time
import json

# Django Core
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect, reverse
from django.urls import reverse_lazy
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST, require_http_methods
from django.views.generic import (
    ListView, CreateView, UpdateView, FormView
)

# Third Party
import cloudinary
import cloudinary.uploader
import stripe
from cloudinary.uploader import upload, destroy

# Local Apps
from plans.models import Plan
from .forms import MemorialForm, ContactForm, GalleryImageForm
from .models import Memorial, Story, GalleryImage, Tribute
from newsletter.forms import SubscribeForm
# ---------------------------
# Basic Views
# ---------------------------


def index(request):
    """Homepage view showing recent memorials"""
    recent_memorials = Memorial.objects.all().order_by('-created_at')[:6]
    context = {
        'recent_memorials': recent_memorials,
        'form': SubscribeForm(),
    }
    return render(request, 'index.html', context)


def plans(request):
    """Display available memorial plans"""
    plans = Plan.objects.all()
    return render(request, 'plans.html', {'plans': plans})


def about(request):
    """Simple about page view"""
    return render(request, 'about.html')


def privacy_policy(request):
    return render(request, 'privacy_policy.html')


def terms_and_conditions(request):
    return render(request, 'terms_and_conditions.html')

# ---------------------------
# Memorial CRUD Views
# ---------------------------


class MemorialCreateView(LoginRequiredMixin, CreateView):
    """View for creating new memorials"""
    model = Memorial
    form_class = MemorialForm
    template_name = 'memorials/memorial_form.html'

    def form_valid(self, form):
        """Assign user and default free plan before saving"""
        form.instance.user = self.request.user

        try:
            free_plan = Plan.objects.get(name='free')
            form.instance.plan = free_plan
        except Plan.DoesNotExist:
            pass

        response = super().form_valid(form)
        messages.success(self.request, 'Memorial created successfully!')
        return response

    def get_success_url(self):
        """Redirect to choose plan page after successful creation"""
        return reverse('plans:choose_plan', kwargs={'memorial_id': self.object.pk})


class MemorialEditView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    """View for editing existing memorials"""
    model = Memorial
    form_class = MemorialForm
    template_name = 'memorials/memorial_edit.html'

    def get_success_url(self):
        """Redirect to memorial detail after edit"""
        return reverse_lazy(
            'memorials:memorial_detail',
            kwargs={'pk': self.object.pk}
        )

    def form_valid(self, form):
        """Add success message after successful edit"""
        response = super().form_valid(form)
        messages.success(self.request, 'Memorial updated successfully!')
        return response

    def test_func(self):
        """Ensure only memorial owner can edit"""
        return self.request.user == self.get_object().user

    def get_context_data(self, **kwargs):
        """Add update URLs to context"""
        context = super().get_context_data(**kwargs)
        context['update_name_url'] = reverse_lazy(
            'memorials:update_name',
            kwargs={'pk': self.object.pk}
        )
        context['update_dates_url'] = reverse_lazy(
            'memorials:update_dates',
            kwargs={'pk': self.object.pk}
        )
        return context


@login_required
def delete_memorial(request, pk):
    """View for deleting a memorial and its associated data"""
    memorial = get_object_or_404(Memorial, pk=pk, user=request.user)

    if request.method == "POST":
        if memorial.stripe_subscription_id:
            try:
                stripe.Subscription.delete(memorial.stripe_subscription_id)
            except stripe.error.StripeError:
                messages.error(
                    request,
                    "Error canceling subscription. Please try again."
                )
                return redirect('memorials:memorial_detail', pk=pk)
            except Exception:
                messages.warning(
                    request,
                    "Memorial deleted but subscription cancel failed."
                )

        memorial.delete()
        messages.success(request, "Memorial has been deleted.")
        return redirect('memorials:account_profile')

    return redirect('memorials:memorial_detail', pk=pk)

# ---------------------------
# Memorial Content Views
# ---------------------------


@csrf_protect
def memorial_detail(request, pk):
    """Detailed view of a memorial with tributes and stories"""
    memorial = get_object_or_404(Memorial, pk=pk)
    memorial.refresh_from_db()

    tributes = memorial.tributes.all().order_by('-created_at')[:6]
    stories = memorial.stories.all().order_by('-created_at')[:3]

    plan_name = memorial.plan.name.lower() if memorial.plan else ""
    is_premium_plan = plan_name in ['premium', 'lifetime']
    is_premium = (
        request.user.is_authenticated and
        request.user == memorial.user and
        is_premium_plan
    )

    if (request.method == 'POST' and
            request.headers.get('x-requested-with') == 'XMLHttpRequest'):
        if 'story_content' in request.POST:
            return create_story(request, pk)
        return create_tribute(request, pk)

    return render(
        request,
        'memorials/memorial_detail.html',
        {
            'memorial': memorial,
            'tributes': tributes,
            'stories': stories,
            'is_premium': is_premium,
            'request': request,
        }
    )

# ---------------------------
# AJAX Update Views
# ---------------------------


@require_POST
def update_name(request, pk):
    """AJAX endpoint for updating memorial name"""
    try:
        memorial = Memorial.objects.get(pk=pk)
        memorial.first_name = request.POST.get('first_name', '')
        memorial.middle_name = request.POST.get('middle_name', '')
        memorial.last_name = request.POST.get('last_name', '')
        memorial.save()

        full_name = (
            f"{memorial.first_name} "
            f"{memorial.middle_name + ' ' if memorial.middle_name else ''}"
            f"{memorial.last_name}"
        )

        return JsonResponse({
            'status': 'success',
            'new_name': full_name.strip()
        })
    except Memorial.DoesNotExist:
        return JsonResponse(
            {'status': 'error', 'message': 'Memorial not found'},
            status=404
        )
    except Exception as e:
        return JsonResponse(
            {'status': 'error', 'message': str(e)},
            status=400
        )


@require_POST
def update_dates(request, pk):
    """AJAX endpoint for updating memorial dates"""
    try:
        memorial = Memorial.objects.get(pk=pk)

        date_of_birth_str = request.POST.get('date_of_birth')
        date_of_death_str = request.POST.get('date_of_death')

        try:
            date_of_birth = datetime.strptime(
                date_of_birth_str,
                '%Y-%m-%d'
            ).date()
            date_of_death = datetime.strptime(
                date_of_death_str,
                '%Y-%m-%d'
            ).date()
        except (ValueError, TypeError):
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid date format. Use YYYY-MM-DD.'
            }, status=400)

        memorial.date_of_birth = date_of_birth
        memorial.date_of_death = date_of_death
        memorial.save()

        return JsonResponse({
            'status': 'success',
            'new_dates': (
                f"{date_of_birth.strftime('%B %d, %Y')} - "
                f"{date_of_death.strftime('%B %d, %Y')}"
            )
        })
    except Memorial.DoesNotExist:
        return JsonResponse(
            {'status': 'error', 'message': 'Memorial not found'},
            status=404
        )
    except Exception as e:
        return JsonResponse(
            {'status': 'error', 'message': str(e)},
            status=400
        )


@require_POST
@login_required
def update_quote(request, pk):
    """AJAX endpoint for updating memorial quote"""
    memorial = get_object_or_404(Memorial, pk=pk, user=request.user)

    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            quote = data.get('quote', '').strip()
        else:
            quote = request.POST.get('quote', '').strip()

        memorial.quote = quote
        memorial.save()

        return JsonResponse({
            'status': 'success',
            'quote': memorial.quote,
            'message': 'Quote updated successfully'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)


@require_POST
@login_required
def update_banner(request, pk):
    """AJAX endpoint for updating memorial banner"""
    try:
        memorial = Memorial.objects.get(pk=pk, user=request.user)

        banner_type = request.POST.get('banner_type')
        banner_value = request.POST.get('banner_value')

        if not banner_type or not banner_value:
            return JsonResponse({
                'status': 'error',
                'message': 'Missing required fields'
            }, status=400)

        if banner_type not in ['image', 'color']:
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid banner type'
            }, status=400)

        if banner_type == 'image' and banner_value.startswith('/static/'):
            banner_value = banner_value.replace('/static/', '')

        memorial.banner_type = banner_type
        memorial.banner_value = banner_value
        memorial.save()

        return JsonResponse({
            'status': 'success',
            'banner_type': banner_type,
            'banner_value': banner_value
        })

    except Memorial.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Memorial not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@require_POST
@login_required
def update_biography(request, pk):
    """AJAX endpoint for updating memorial biography"""
    try:
        memorial = get_object_or_404(Memorial, pk=pk, user=request.user)
        biography = request.POST.get('biography', '')
        memorial.biography = biography
        memorial.save()
        return JsonResponse({
            'success': True,
            'biography': biography.replace('\n', '<br>')
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


# ---------------------------
# File Upload Views
# ---------------------------

import time
import logging

logger = logging.getLogger(__name__)


@login_required
def upload_profile_picture(request, pk):
    """View for uploading profile pictures to Cloudinary"""
    memorial = get_object_or_404(Memorial, pk=pk, user=request.user)

    if request.method == 'POST' and 'profile_picture' in request.FILES:
        profile_pic = request.FILES['profile_picture']

        # Validation
        if profile_pic.size > 5 * 1024 * 1024:
            return JsonResponse(
                {'status': 'error', 'message': 'Image too large (max 5MB)'},
                status=400
            )

        if not profile_pic.content_type.startswith('image/'):
            return JsonResponse(
                {'status': 'error', 'message': 'Invalid file type'},
                status=400
            )

        try:
            file_content = profile_pic.read()
            
            upload_result = upload(
                file_content,
                folder=f"memorials/{memorial.id}/profile_pictures",
                public_id=f"profile_{memorial.id}",
                overwrite=True,
                invalidate=True,
                resource_type="image"
            )
            
            # Log the upload result to see what Cloudinary returns
            logger.info(f"Cloudinary upload result: {upload_result}")
            
            memorial.profile_picture = None
            memorial.profile_public_id = upload_result['public_id']
            memorial.save()
            
            # Use timestamp for cache busting (safer than version)
            cache_buster = int(time.time())
            
            return JsonResponse({
                'status': 'success',
                'profile_picture_url': f"https://res.cloudinary.com/dols0zev1/image/upload/{upload_result['public_id']}.png?v={cache_buster}",
                'public_id': upload_result['public_id'],
                'message': 'Profile picture updated!'
            })

        except Exception as e:
            # Log the full error
            logger.exception(f"Profile picture upload failed for memorial {pk}: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': f'Upload failed: {str(e)}'
            }, status=500)

    return JsonResponse(
        {'status': 'error', 'message': 'Invalid request'},
        status=400
    )


# ---------------------------
# Tribute Views with Approval System
# ---------------------------

# Add these imports at the top of your views.py if not already there
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.urls import reverse

@require_POST
@login_required
def create_tribute(request, pk):
    """AJAX endpoint for creating memorial tributes."""
    memorial = get_object_or_404(Memorial, pk=pk)

    author_name = request.POST.get('author_name', '').strip()
    message = request.POST.get('message', '').strip()

    if not author_name:
        return JsonResponse(
            {'success': False, 'error': 'Name is required'},
            status=400
        )
    if not message:
        return JsonResponse(
            {'success': False, 'error': 'Message is required'},
            status=400
        )
    if len(message) > 2000:
        return JsonResponse(
            {'success': False, 'error': 'Message too long'},
            status=400
        )

    try:
        # Auto-approve if the user is the memorial owner
        if request.user == memorial.user:
            status = Tribute.STATUS_APPROVED
            success_message = 'Your tribute has been posted!'
            response_message = 'Your tribute has been posted successfully.'
        else:
            status = Tribute.STATUS_PENDING
            success_message = 'Tribute submitted for approval!'
            response_message = 'Tribute submitted for approval. The memorial owner will review it.'

        tribute = memorial.tributes.create(
            user=request.user,
            author_name=author_name,
            message=message,
            status=status  # Use the status determined above
        )

        # Only send email notification if it's NOT the memorial owner
        if request.user != memorial.user:
            send_tribute_notification_email(request, tribute, memorial)

        messages.success(request, success_message)

        can_edit = (
            request.user == memorial.user or
            request.user == tribute.user
        )

        return JsonResponse({
            'success': True,
            'message': response_message,
            'tribute': {
                'id': tribute.id,
                'author_name': tribute.author_name,
                'message': tribute.message,
                'status': tribute.status,  # This will be 'approved' for owner
                'created_at': tribute.created_at.strftime("%b %d, %Y")
            },
            'can_edit': can_edit,
            'is_owner': request.user == memorial.user  # Important for JavaScript
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_POST
@login_required
def edit_tribute(request, pk):
    """AJAX endpoint for editing memorial tributes."""
    try:
        tribute = Tribute.objects.get(id=pk)
        is_owner = request.user == tribute.memorial.user
        is_author = request.user == tribute.user

        if not is_owner and not is_author:
            return JsonResponse(
                {'success': False, 'error': 'Permission denied'},
                status=403
            )

        author_name = request.POST.get('author_name', '').strip()
        message = request.POST.get('message', '').strip()

        if not author_name:
            return JsonResponse(
                {'success': False, 'error': 'Name is required'},
                status=400
            )
        if not message:
            return JsonResponse(
                {'success': False, 'error': 'Message is required'},
                status=400
            )
        if len(message) > 2000:
            return JsonResponse(
                {'success': False, 'error': 'Message too long'},
                status=400
            )

        tribute.author_name = author_name
        tribute.message = message
        tribute.save()

        return JsonResponse({
            'success': True,
            'tribute': {
                'id': tribute.id,
                'author_name': tribute.author_name,
                'message': tribute.message,
                'status': tribute.status,
                'created_at': tribute.created_at.strftime("%b %d, %Y")
            },
            'can_edit': True
        })
    except Tribute.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Tribute not found'},
            status=404
        )


@require_POST
@login_required
def delete_tribute(request, pk):
    """AJAX endpoint for deleting memorial tributes."""
    try:
        tribute = Tribute.objects.get(id=pk)
        memorial_id = tribute.memorial.id

        if (request.user != tribute.memorial.user and
                request.user != tribute.user):
            return JsonResponse(
                {'success': False, 'error': 'Permission denied'},
                status=403
            )

        tribute.delete()
        return JsonResponse(
            {'success': True, 'memorial_id': memorial_id}
        )
    except Tribute.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Tribute not found'},
            status=404
        )


def get_tributes(request, pk):
    """AJAX endpoint for loading more memorial tributes."""
    memorial = get_object_or_404(Memorial, pk=pk)
    offset = int(request.GET.get('offset', 0))
    limit = 3

    # If user is memorial owner, show all tributes
    # If not, show only approved tributes
    if request.user == memorial.user:
        tributes = memorial.tributes.all()
    else:
        tributes = memorial.tributes.filter(status=Tribute.STATUS_APPROVED)
    
    tributes = tributes.order_by('-created_at')[offset:offset + limit]

    return JsonResponse({
        'tributes': [{
            'id': t.id,
            'author_name': t.author_name,
            'message': t.message,
            'status': t.status,
            'created_at': t.created_at.strftime("%b %d, %Y")
        } for t in tributes],
        'is_owner': request.user == memorial.user
    })


# NEW VIEWS FOR APPROVAL SYSTEM

@require_POST
@login_required
def approve_tribute(request, pk):
    """Approve a pending tribute."""
    try:
        tribute = Tribute.objects.get(id=pk)
        
        # Check if user is the memorial owner
        if request.user != tribute.memorial.user:
            return JsonResponse(
                {'success': False, 'error': 'Permission denied'},
                status=403
            )
        
        tribute.status = Tribute.STATUS_APPROVED
        tribute.save()
        
        # Optional: Send notification to tribute author
        # send_tribute_approved_email(request, tribute)
        
        return JsonResponse({
            'success': True,
            'message': 'Tribute approved successfully',
            'tribute_id': tribute.id
        })
        
    except Tribute.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Tribute not found'},
            status=404
        )


@require_POST
@login_required
def reject_tribute(request, pk):
    """Reject a pending tribute."""
    try:
        tribute = Tribute.objects.get(id=pk)
        
        # Check if user is the memorial owner
        if request.user != tribute.memorial.user:
            return JsonResponse(
                {'success': False, 'error': 'Permission denied'},
                status=403
            )
        
        tribute.status = Tribute.STATUS_REJECTED
        tribute.save()
        
        # Optional: Send notification to tribute author
        # send_tribute_rejected_email(request, tribute)
        
        return JsonResponse({
            'success': True,
            'message': 'Tribute rejected',
            'tribute_id': tribute.id
        })
        
    except Tribute.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Tribute not found'},
            status=404
        )


@require_POST
@login_required
def delete_rejected_tribute(request, pk):
    """Permanently delete a rejected tribute."""
    try:
        tribute = Tribute.objects.get(id=pk)
        
        # Check if user is the memorial owner and tribute is rejected
        if (request.user != tribute.memorial.user or 
                tribute.status != Tribute.STATUS_REJECTED):
            return JsonResponse(
                {'success': False, 'error': 'Permission denied'},
                status=403
            )
        
        tribute.delete()
        return JsonResponse({
            'success': True,
            'message': 'Tribute deleted permanently'
        })
        
    except Tribute.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Tribute not found'},
            status=404
        )


# EMAIL HELPER FUNCTIONS

def send_tribute_notification_email(request, tribute, memorial):
    """Send email to memorial owner about new tribute."""
    try:
        # Memorial owner's email
        recipient_email = memorial.user.email
        
        # Create email content
        memorial_url = request.build_absolute_uri(
            reverse('memorials:memorial_edit', args=[memorial.pk])
        )
        
        subject = f'New Tribute Pending Approval for {memorial.first_name} {memorial.last_name}'
        
        html_message = render_to_string('newsletter/emails/tribute_notification.html', {
            'tribute': tribute,
            'memorial': memorial,
            'memorial_url': memorial_url,
            'site_name': 'NeverForgotten',
        })
        
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject=subject,
            message=plain_message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            fail_silently=False,
        )
        
    except Exception as e:
        # Log the error but don't break the tribute creation
        print(f"Failed to send email: {e}")
        # You might want to log this to a proper logging system


def send_tribute_approved_email(request, tribute):
    """Optional: Send email to tribute author when approved."""
    try:
        if tribute.user and tribute.user.email:
            subject = f'Your Tribute Has Been Approved'
            
            html_message = render_to_string('newsletter/emails/tribute_approved.html', {
                'tribute': tribute,
                'memorial': tribute.memorial,
                'site_name': 'NeverForgotten',
            })
            
            plain_message = strip_tags(html_message)
            
            send_mail(
                subject=subject,
                message=plain_message,
                html_message=html_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[tribute.user.email],
                fail_silently=False,
            )
    except Exception as e:
        print(f"Failed to send approval email: {e}")


def send_tribute_rejected_email(request, tribute):
    """Optional: Send email to tribute author when rejected."""
    try:
        if tribute.user and tribute.user.email:
            subject = f'Update on Your Tribute Submission'
            
            html_message = render_to_string('newsletteremails/tribute_rejected.html', {
                'tribute': tribute,
                'memorial': tribute.memorial,
                'site_name': 'NeverForgotten',
            })
            
            plain_message = strip_tags(html_message)
            
            send_mail(
                subject=subject,
                message=plain_message,
                html_message=html_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[tribute.user.email],
                fail_silently=False,
            )
    except Exception as e:
        print(f"Failed to send rejection email: {e}")


@login_required
def upload_audio(request, pk):
    """View for uploading audio files to Cloudinary"""
    memorial = get_object_or_404(Memorial, pk=pk, user=request.user)

    if request.method == 'POST' and 'audio_file' in request.FILES:
        audio_file = request.FILES['audio_file']

        try:
            if memorial.audio_public_id:
                destroy(memorial.audio_public_id, resource_type="video")

            upload_result = upload(
                audio_file,
                folder=f"memorials/{memorial.id}/audio",
                resource_type="video"
            )

            memorial.audio_file = upload_result['secure_url']
            memorial.audio_public_id = upload_result['public_id']
            memorial.save()

            messages.success(request, "Audio file updated successfully!")
        except Exception as e:
            messages.error(request, f"Error updating audio: {str(e)}")

    return redirect('memorials:memorial_edit', pk=memorial.id)


@login_required
def upload_gallery_image(request, memorial_id):
    """View for uploading single gallery image"""
    memorial = get_object_or_404(
        Memorial,
        id=memorial_id,
        user=request.user
    )

    current_count = memorial.gallery_images.count()
    is_premium = memorial.plan in ['premium', 'lifetime']
    max_allowed = 9 if is_premium else 3

    if current_count >= max_allowed:
        messages.error(
            request,
            f"You can upload up to {max_allowed} images."
        )
        return redirect('memorial_edit', memorial_id=memorial.id)

    if request.method == 'POST':
        form = GalleryImageForm(request.POST, request.FILES)
        if form.is_valid():
            upload_result = cloudinary.uploader.upload(
                request.FILES['image'],
                folder=f"memorials/{memorial.id}/gallery",
                use_filename=True,
                unique_filename=False,
                overwrite=False
            )

            gallery_image = form.save(commit=False)
            gallery_image.memorial = memorial
            gallery_image.image = upload_result['public_id']
            gallery_image.save()

            messages.success(request, "Image uploaded successfully.")
            return redirect('memorial_edit', memorial_id=memorial.id)
    else:
        form = GalleryImageForm()

    return render(
        request,
        'upload_gallery_image.html',
        {'form': form, 'memorial': memorial}
    )


@require_http_methods(["POST"])
@login_required
@transaction.atomic
def upload_gallery_images(request, pk):
    """View for bulk uploading gallery images with AJAX support."""
    memorial = get_object_or_404(Memorial, pk=pk, user=request.user)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    try:
        # Validate upload limits
        if memorial.remaining_gallery_slots <= 0:
            error_msg = (
                f"Gallery limit reached ({memorial.max_gallery_images} "
                "images max)"
            )
            if is_ajax:
                return JsonResponse(
                    {'success': False, 'error': error_msg},
                    status=400
                )
            messages.error(request, error_msg)
            return redirect('memorials:memorial_edit', pk=pk)

        images = request.FILES.getlist('images')
        if not images:
            error_msg = "Please select at least one image"
            if is_ajax:
                return JsonResponse(
                    {'success': False, 'error': error_msg},
                    status=400
                )
            messages.error(request, error_msg)
            return redirect('memorials:memorial_edit', pk=pk)

        # Process uploads
        images_to_upload = images[:memorial.remaining_gallery_slots]
        new_images = []

        for image in images_to_upload:
            upload_result = cloudinary.uploader.upload(
                image,
                folder=f"memorials/{memorial.id}/gallery",
                use_filename=True,
                unique_filename=False,
                overwrite=False
            )

            gallery_image = GalleryImage.objects.create(
                memorial=memorial,
                image=upload_result['secure_url'],
                order=memorial.gallery.count() + 1
            )
            new_images.append({
                'id': gallery_image.id,
                'url': gallery_image.image,
                'caption': gallery_image.caption or ''
            })

        # Prepare response
        response_data = {
            'success': True,
            'new_images': new_images,
            'message': f"Uploaded {len(new_images)} images successfully!",
            'remaining_slots': (
                memorial.remaining_gallery_slots - len(new_images)
            )
        }

        if len(images) > len(images_to_upload):
            response_data['message'] += (
                f" ({len(images) - len(images_to_upload)} skipped)"
            )

        if is_ajax:
            return JsonResponse(response_data)
        messages.success(request, f"Uploaded {len(new_images)} images successfully!")
        return redirect('memorials:memorial_edit', pk=pk)

    except Exception as e:
        error_msg = f"Upload error: {str(e)}"
        if is_ajax:
            return JsonResponse(
                {'success': False, 'error': error_msg},
                status=500
            )
        messages.error(request, error_msg)
        return redirect('memorials:memorial_edit', pk=pk)


@login_required
def delete_gallery_image(request, memorial_id, image_id):
    """View for deleting gallery images from memorial."""
    if request.method == 'POST':
        image = get_object_or_404(
            GalleryImage,
            id=image_id,
            memorial__id=memorial_id
        )

        if image.memorial.user != request.user:
            messages.error(
                request,
                "You don't have permission to delete this image."
            )
            return redirect('memorials:memorial_detail', pk=memorial_id)

        # With CloudinaryField, the field itself stores the public_id
        # image.image is the CloudinaryResource, str() gives the public_id
        public_id = str(image.image) if image.image else None
        
        logger.info(f"Attempting to delete gallery image. public_id: {public_id}")

        if public_id:
            try:
                result = destroy(public_id)
                logger.info(f"Cloudinary destroy result: {result}")
                
                # Check if deletion was successful
                if result.get('result') != 'ok':
                    logger.warning(f"Cloudinary deletion may have failed: {result}")
            except Exception as e:
                logger.error(f"Cloudinary destroy failed: {e}")

        # Delete from database
        image.delete()
        messages.success(request, "Image deleted successfully.")
        return redirect('memorials:memorial_edit', pk=memorial_id)

    messages.error(request, "Invalid request.")
    return redirect('memorials:memorial_edit', pk=memorial_id)


# ---------------------------
# Story Views with Approval System
# ---------------------------

@require_POST
@login_required
def create_story(request, pk):
    """AJAX endpoint for creating memorial stories."""
    memorial = get_object_or_404(Memorial, pk=pk)

    author_name = request.POST.get('author_name', '').strip()
    title = request.POST.get('title', '').strip()
    content = request.POST.get('content', '').strip()

    if not author_name:
        return JsonResponse(
            {'success': False, 'error': 'Name is required'},
            status=400
        )
    if not title:
        return JsonResponse(
            {'success': False, 'error': 'Title is required'},
            status=400
        )
    if not content:
        return JsonResponse(
            {'success': False, 'error': 'Content is required'},
            status=400
        )
    if len(content) > 5000:
        return JsonResponse(
            {'success': False, 'error': 'Story is too long'},
            status=400
        )

    try:
        # Auto-approve if the user is the memorial owner
        if request.user == memorial.user:
            status = Story.STATUS_APPROVED
            success_message = 'Your story has been posted!'
            response_message = 'Your story has been posted successfully.'
        else:
            status = Story.STATUS_PENDING
            success_message = 'Story submitted for approval!'
            response_message = 'Story submitted for approval. The memorial owner will review it.'

        story = memorial.stories.create(
            user=request.user,
            author_name=author_name,
            title=title,
            content=content,
            status=status
        )

        # Only send email notification if it's NOT the memorial owner
        if request.user != memorial.user:
            send_story_notification_email(request, story, memorial)

        messages.success(request, success_message)

        can_edit = (
            request.user == memorial.user or
            request.user == story.user
        )

        return JsonResponse({
            'success': True,
            'message': response_message,
            'story': {
                'id': story.id,
                'author_name': story.author_name,
                'title': story.title,
                'content': story.content,
                'status': story.status,
                'created_at': story.created_at.strftime("%b %d, %Y")
            },
            'can_edit': can_edit,
            'is_owner': request.user == memorial.user
        })

    except Exception as e:
        return JsonResponse(
            {'success': False, 'error': str(e)},
            status=500
        )


@require_POST
@login_required
def edit_story(request, pk):
    """AJAX endpoint for editing memorial stories."""
    try:
        story = Story.objects.get(id=pk)
        is_owner = request.user == story.memorial.user
        is_author = request.user == story.user

        if not is_owner and not is_author:
            return JsonResponse(
                {'success': False, 'error': 'Permission denied'},
                status=403
            )

        author_name = request.POST.get('author_name', '').strip()
        title = request.POST.get('title', '').strip()
        content = request.POST.get('content', '').strip()

        if not all([author_name, title, content]):
            return JsonResponse(
                {'success': False, 'error': 'All fields are required'},
                status=400
            )
        if len(content) > 5000:
            return JsonResponse(
                {'success': False, 'error': 'Story too long'},
                status=400
            )

        story.author_name = author_name
        story.title = title
        story.content = content
        story.save()

        return JsonResponse({
            'success': True,
            'story': {
                'id': story.id,
                'author_name': story.author_name,
                'title': story.title,
                'content': story.content,
                'status': story.status,
                'created_at': story.created_at.strftime("%b %d, %Y")
            },
            'can_edit': True,
            'is_owner': request.user == story.memorial.user
        })
    except Story.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Story not found'},
            status=404
        )


@require_POST
@login_required
def delete_story(request, pk):
    """AJAX endpoint for deleting memorial stories."""
    try:
        story = Story.objects.get(id=pk)
        memorial_id = story.memorial.id

        if (request.user != story.memorial.user and
                request.user != story.user):
            return JsonResponse(
                {'success': False, 'error': 'Permission denied'},
                status=403
            )

        story.delete()
        return JsonResponse(
            {'success': True, 'memorial_id': memorial_id}
        )
    except Story.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Story not found'},
            status=404
        )


def get_stories(request, pk):
    """AJAX endpoint for loading more memorial stories."""
    memorial = get_object_or_404(Memorial, pk=pk)
    offset = int(request.GET.get('offset', 0))
    limit = 3

    # If user is memorial owner, show all stories
    # If not, show only approved stories
    if request.user == memorial.user:
        stories = memorial.stories.all()
    else:
        stories = memorial.stories.filter(status=Story.STATUS_APPROVED)
    
    stories = stories.order_by('-created_at')[offset:offset + limit]

    return JsonResponse({
        'stories': [{
            'id': s.id,
            'author_name': s.author_name,
            'title': s.title,
            'content': s.content,
            'status': s.status,
            'created_at': s.created_at.strftime("%b %d, %Y")
        } for s in stories],
        'is_owner': request.user == memorial.user
    })


# NEW VIEWS FOR STORY APPROVAL SYSTEM

@require_POST
@login_required
def approve_story(request, pk):
    """Approve a pending story."""
    try:
        story = Story.objects.get(id=pk)
        
        # Check if user is the memorial owner
        if request.user != story.memorial.user:
            return JsonResponse(
                {'success': False, 'error': 'Permission denied'},
                status=403
            )
        
        story.status = Story.STATUS_APPROVED
        story.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Story approved successfully',
            'story_id': story.id
        })
        
    except Story.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Story not found'},
            status=404
        )


@require_POST
@login_required
def reject_story(request, pk):
    """Reject a pending story."""
    try:
        story = Story.objects.get(id=pk)
        
        # Check if user is the memorial owner
        if request.user != story.memorial.user:
            return JsonResponse(
                {'success': False, 'error': 'Permission denied'},
                status=403
            )
        
        story.status = Story.STATUS_REJECTED
        story.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Story rejected',
            'story_id': story.id
        })
        
    except Story.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Story not found'},
            status=404
        )


@require_POST
@login_required
def delete_rejected_story(request, pk):
    """Permanently delete a rejected story."""
    try:
        story = Story.objects.get(id=pk)
        
        # Check if user is the memorial owner and story is rejected
        if (request.user != story.memorial.user or 
                story.status != Story.STATUS_REJECTED):
            return JsonResponse(
                {'success': False, 'error': 'Permission denied'},
                status=403
            )
        
        story.delete()
        return JsonResponse({
            'success': True,
            'message': 'Story deleted permanently'
        })
        
    except Story.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Story not found'},
            status=404
        )


# EMAIL HELPER FUNCTION

def send_story_notification_email(request, story, memorial):
    """Send email to memorial owner about new story."""
    try:
        # Memorial owner's email
        recipient_email = memorial.user.email
        
        # Create email content
        memorial_url = request.build_absolute_uri(
            reverse('memorials:memorial_edit', args=[memorial.pk])
        )
        
        subject = f'New Story Pending Approval for {memorial.first_name} {memorial.last_name}'
        
        html_message = render_to_string('newsletter/emails/story_notification.html', {
            'story': story,
            'memorial': memorial,
            'memorial_url': memorial_url,
            'site_name': 'NeverForgotten',
        })
        
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject=subject,
            message=plain_message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            fail_silently=False,
        )
        
    except Exception as e:
        # Log the error but don't break the story creation
        print(f"Failed to send email: {e}")


# ---------------------------
# Account Management Views
# ---------------------------

class MyAccountView(LoginRequiredMixin, ListView):
    """View showing user's memorials"""
    model = Memorial
    template_name = 'account/my_account.html'
    context_object_name = 'memorials'

    def get_queryset(self):
        """Filter memorials to only those owned by current user"""
        return Memorial.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        """Add free plan info to context"""
        context = super().get_context_data(**kwargs)
        free_plan = Plan.objects.filter(name__iexact='free').first()
        context['plans_free_plan'] = free_plan
        return context


class UserEditForm(forms.ModelForm):
    """Form for editing user profile information"""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']


@login_required
def edit_profile(request):
    """View for editing user profile"""
    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('memorials:account_profile')
    else:
        form = UserEditForm(instance=request.user)

    return render(
        request,
        'account/edit_profile.html',
        {'form': form}
    )


# ---------------------------
# Upgrade Views
# ---------------------------

class UpgradeMemorialForm(forms.Form):
    """Form for selecting a memorial upgrade plan."""
    plan = forms.ModelChoiceField(
        queryset=Plan.objects.exclude(name__iexact='free'),
        empty_label=None,
        widget=forms.RadioSelect
    )


class UpgradeMemorialView(LoginRequiredMixin, FormView):
    """View for upgrading memorial plans."""
    template_name = 'memorials/upgrade_memorial.html'
    form_class = UpgradeMemorialForm

    def dispatch(self, request, *args, **kwargs):
        """Get memorial and check permissions."""
        self.memorial = get_object_or_404(
            Memorial,
            pk=kwargs['pk'],
            user=request.user
        )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """Handle form submission for plan upgrade."""
        selected_plan = form.cleaned_data['plan']
        self.memorial.plan = selected_plan
        self.memorial.save()
        messages.success(self.request, 'Memorial upgraded successfully!')
        return redirect(reverse_lazy('memorials:my_account'))

    def get_context_data(self, **kwargs):
        """Add memorial to template context."""
        context = super().get_context_data(**kwargs)
        context['memorial'] = self.memorial
        return context


# ---------------------------
# Browse and Search Views
# ---------------------------

def browse_memorials(request):
    """View for browsing and searching memorials."""
    memorials_list = Memorial.objects.all().order_by('-created_at')
    search_query = None
    search_results = False

    if request.method == 'GET':
        first_name = request.GET.get('first_name', '').strip()
        middle_name = request.GET.get('middle_name', '').strip()
        last_name = request.GET.get('last_name', '').strip()
        date_of_birth = request.GET.get('date_of_birth', '').strip()
        date_of_death = request.GET.get('date_of_death', '').strip()

        if any([
            first_name,
            middle_name,
            last_name,
            date_of_birth,
            date_of_death
        ]):
            search_results = True
            query = Q()

            if first_name:
                query &= Q(first_name__icontains=first_name)
            if middle_name:
                query &= Q(middle_name__icontains=middle_name)
            if last_name:
                query &= Q(last_name__icontains=last_name)
            if date_of_birth:
                query &= Q(date_of_birth=date_of_birth)
            if date_of_death:
                query &= Q(date_of_death=date_of_death)

            memorials_list = memorials_list.filter(query)
            search_query = {
                'first_name': first_name,
                'middle_name': middle_name,
                'last_name': last_name,
                'date_of_birth': date_of_birth,
                'date_of_death': date_of_death,
            }

    paginator = Paginator(memorials_list, 9)
    page_number = request.GET.get('page')
    memorials = paginator.get_page(page_number)

    context = {
        'memorials': memorials,
        'search_query': search_query,
        'search_results': search_results,
    }

    return render(request, 'browse.html', context)


# ---------------------------
# Contact View
# ---------------------------

def contact(request):
    """View for handling contact form submissions."""
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            contact_message = form.save()

            try:
                send_mail(
                    f"New Contact Message: {contact_message.subject}",
                    (
                        f"From: {contact_message.name} "
                        f"<{contact_message.email}>\n\n"
                        f"Message:\n{contact_message.message}"
                    ),
                    settings.DEFAULT_FROM_EMAIL,
                    [settings.CONTACT_EMAIL],
                    fail_silently=False,
                )
            except Exception as e:
                print(f"Email sending failed: {e}")

            messages.success(request, 'Your message has been sent!')
            return redirect('memorials:contact')
    else:
        form = ContactForm()

    return render(request, 'contact.html', {'form': form})



