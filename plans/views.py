import stripe
from django.conf import settings
from django.shortcuts import (
    render, get_object_or_404, redirect, reverse
)
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from .models import Plan
from memorial.models import Memorial
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
import logging
from cloudinary.uploader import destroy
from urllib.parse import urlparse
import re

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY


@login_required
def choose_plan(request, memorial_id):
    """View for selecting a plan for a memorial."""
    memorial = get_object_or_404(Memorial, pk=memorial_id)
    plans = Plan.objects.filter(is_active=True).order_by('price')
    context = {
        'plans': plans,
        'memorial': memorial,
        'memorial_id': memorial_id,
    }
    return render(request, 'plans/choose_plan.html', context)


@login_required
def create_checkout_session(request, plan_id, memorial_id):
    """Create Stripe checkout session for selected plan."""
    plan = get_object_or_404(Plan, id=plan_id)
    memorial = get_object_or_404(
        Memorial, id=memorial_id, user=request.user
    )

    if plan.price == 0:
        memorial.plan = plan
        memorial.save()
        return redirect(reverse(
            'memorials:memorial_edit',
            kwargs={'pk': memorial_id}
        ))

    mode = 'payment' if plan.billing_cycle == 'lifetime' else 'subscription'

    try:
        success_url = (
            request.build_absolute_uri(reverse('plans:payment_success')) +
            f"?memorial_id={memorial_id}&session_id={{CHECKOUT_SESSION_ID}}"
        )

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': plan.stripe_price_id,
                'quantity': 1,
            }],
            mode=mode,
            success_url=success_url,
            cancel_url=request.build_absolute_uri(
                reverse('plans:payment_cancel')
            ),
            customer_email=request.user.email,
            metadata={
                'user_id': request.user.id,
                'plan_id': plan.id,
                'memorial_id': memorial.id,
            }
        )
        return redirect(checkout_session.url)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def get_public_id_from_url(url):
    """Extract public ID from Cloudinary URL."""
    parsed = urlparse(url)
    path = parsed.path
    match = re.search(r'/upload/(?:v\d+/)?(?P<public_id>.+)', path)
    return match.group('public_id') if match else None


@csrf_exempt
def stripe_webhook(request):
    """Handle Stripe webhook events."""
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET
    print("🔔 Webhook received")

    try:
        print("🔐 Verifying signature...")
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except Exception as e:
        print("⚠️ Webhook signature/parse error:", e)
        return HttpResponse(status=400)

    print("✅ Received event:", event['type'])

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        print("   session metadata:", session.get('metadata'))

        user_id = session['metadata'].get('user_id')
        plan_id = session['metadata'].get('plan_id')
        memorial_id = session['metadata'].get('memorial_id')

        print(f"   Looking up User({user_id}), Plan({plan_id}), "
              f"Memorial({memorial_id})…")
        try:
            user = User.objects.get(id=user_id)
            plan = Plan.objects.get(id=plan_id)
            memorial = Memorial.objects.get(id=memorial_id, user=user)

            memorial.plan = plan

            subscription_id = session.get('subscription')
            if subscription_id:
                memorial.stripe_subscription_id = subscription_id

            memorial.save()
            print(f"✅ Assigned plan '{plan.name}' to Memorial ID "
                  f"{memorial.id} with subscription {subscription_id}")
        except Exception as e:
            print("⚠️ Error assigning plan or subscription id:", e)

    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        subscription_id = subscription.get('id')
        print(f"🔔 Subscription cancelled: {subscription_id}")

        try:
            memorials = Memorial.objects.filter(
                stripe_subscription_id=subscription_id
            )
            free_plan = Plan.objects.get(name__iexact='free')

            for memorial in memorials:
                memorial.plan = free_plan
                memorial.stripe_subscription_id = None

                if memorial.audio_file:
                    print(f"Deleting audio for Memorial {memorial.id}")
                    memorial.audio_file.delete()
                    memorial.audio_file = None
                    memorial.save()

                gallery_images = memorial.gallery.order_by('-uploaded_at')[:6]
                if gallery_images:
                    print(f"Deleting {len(gallery_images)} most recent "
                          f"gallery images for Memorial {memorial.id}")
                    for image in gallery_images:
                        public_id = None
                        if image.image and hasattr(image.image, 'public_id'):
                            public_id = image.image.public_id
                        else:
                            url = image.image.url if image.image else None
                            if url:
                                public_id = get_public_id_from_url(url)

                        if public_id:
                            print(f" -> Deleting Cloudinary image "
                                  f"public_id: {public_id}")
                            destroy(public_id)

                        image.delete()

                print(f"Set Memorial {memorial.id} to Free plan and "
                      f"cleaned media on subscription cancel.")
        except Exception as e:
            print(f"⚠️ Error handling subscription cancellation cleanup: {e}")

    return HttpResponse(status=200)


@login_required
def cancel_plan(request, memorial_id):
    """Cancel current plan and revert to free plan."""
    memorial = get_object_or_404(
        Memorial, pk=memorial_id, user=request.user
    )
    free_plan = Plan.objects.filter(name__iexact='free').first()

    if request.method == 'POST':
        if memorial.stripe_subscription_id:
            try:
                stripe.Subscription.delete(
                    memorial.stripe_subscription_id
                )
            except Exception as e:
                print("Stripe cancel subscription error:", e)

        memorial.plan = free_plan
        memorial.stripe_subscription_id = None
        memorial.banner_type = 'color'
        memorial.banner_value = '#f7e8c9'
        memorial.save()

        return redirect('memorials:account_profile')

    return redirect('memorials:account_profile')


@login_required
def payment_success(request):
    """Render success page after successful payment."""
    memorial_id = request.session.get('memorial_id')

    if not memorial_id:
        memorial_id = request.GET.get('memorial_id')

    if not memorial_id and request.GET.get('session_id'):
        try:
            session = stripe.checkout.Session.retrieve(
                request.GET['session_id']
            )
            memorial_id = session.metadata.get('memorial_id')
        except Exception as e:
            logger.error(f"Error retrieving Stripe session: {e}")

    logger.info(f"Payment success - memorial_id: {memorial_id}")
    logger.info(f"Session data: {dict(request.session)}")
    logger.info(f"GET params: {dict(request.GET)}")

    if not memorial_id:
        logger.error("No memorial_id found in request or session")
        return render(request, 'plans/success.html', {
            'memorial': None,
            'error': 'Payment successful! Your plan has been activated.'
        })

    try:
        memorial = Memorial.objects.get(pk=memorial_id, user=request.user)
        if 'memorial_id' in request.session:
            del request.session['memorial_id']

        return render(request, 'plans/success.html', {
            'memorial': memorial,
            'memorial_id': memorial_id
        })
    except Memorial.DoesNotExist:
        logger.error(
            (
                f"Memorial not found with ID: {memorial_id} "
                f"for user: {request.user}"
            )
        )
        return render(request, 'plans/success.html', {
            'memorial': None,
            'error': 'Payment successful! Your plan has been activated.'
        })


@login_required
def payment_cancel(request):
    """Render cancellation page."""
    return render(request, 'plans/cancel.html')
