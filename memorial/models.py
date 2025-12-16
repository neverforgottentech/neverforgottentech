"""
Memorial models for NeverForgotten application.
Includes models for memorial profiles, tributes, gallery images, stories,
and contact messages.
"""

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from cloudinary.models import CloudinaryField
from cloudinary.uploader import upload
from cloudinary_storage.storage import MediaCloudinaryStorage
import qrcode
from io import BytesIO
from plans.models import Plan
from django.conf import settings


class Memorial(models.Model):
    """
    Core model representing a memorial profile.
    Handles all memorial data including personal information, media uploads,
    and subscription details.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    banner_type = models.CharField(
        max_length=10,
        choices=[('image', 'Image'), ('color', 'Color')],
        default='color'
    )
    banner_value = models.CharField(
        max_length=255, blank=True, default='#f7e8c9'
    )
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    date_of_death = models.DateField(blank=True, null=True)
    quote = models.TextField(blank=True, null=True)
    biography = models.TextField(
        blank=True, null=True, verbose_name="Memorial Biography"
    )
    created_at = models.DateTimeField(default=timezone.now)

    # Cloudinary references
    profile_public_id = models.CharField(max_length=300, blank=True, null=True)
    audio_public_id = models.CharField(max_length=300, blank=True, null=True)
    qr_code_public_id = models.CharField(max_length=300, blank=True, null=True)

    # Profile picture
    def profile_picture_upload_path(instance, filename):
        """Generate upload path for profile pictures."""
        return f"memorials/{instance.id}/profile_pictures/{filename}"

    profile_picture = models.ImageField(
        upload_to=profile_picture_upload_path,
        blank=True,
        null=True,
        storage=MediaCloudinaryStorage()
    )

    # Audio file
    def audio_file_upload_path(instance, filename):
        """Generate upload path for audio files."""
        return f"memorials/{instance.id}/audio/{filename}"

    audio_file = CloudinaryField(
        resource_type='raw',
        folder=audio_file_upload_path,
        blank=True,
        null=True
    )

    # QR Code
    def qr_code_upload_path(instance, filename):
        """Generate upload path for QR codes."""
        return f"memorials/{instance.id}/qr_codes/{filename}"

    qr_code = models.ImageField(
        upload_to=qr_code_upload_path,
        blank=True,
        null=True,
        storage=MediaCloudinaryStorage()
    )

    # Subscription fields
    plan = models.ForeignKey(
        Plan, on_delete=models.SET_NULL, null=True, blank=True
    )
    stripe_subscription_id = models.CharField(
        max_length=255, blank=True, null=True
    )

    def save(self, *args, **kwargs):
        """Custom save to handle QR code generation."""
        if not self.id:
            super().save(*args, **kwargs)

        if not self.qr_code:
            self.generate_qr_code()

        super().save(*args, **kwargs)

    def generate_qr_code(self):
        """Generates and uploads QR code to Cloudinary."""
        url = f"{settings.SITE_URL}/memorials/{self.id}/"
        qr_img = qrcode.make(url)

        buffer = BytesIO()
        qr_img.save(buffer, format="PNG")
        buffer.seek(0)

        try:
            upload_result = upload(
                buffer,
                folder=f"memorials/{self.id}/qr_codes",
                public_id=f"qr_code_{self.id}",
                overwrite=True,
                resource_type="image",
                format="png"
            )
            self.qr_code_public_id = upload_result['public_id']
            self.qr_code = None
        except Exception as e:
            print(f"Failed to upload QR code: {str(e)}")
            raise

    def get_qr_code_url(self):
        """Returns full Cloudinary URL for the QR code."""
        if self.qr_code_public_id:
            return (
                "https://res.cloudinary.com/neverforgotten/image/upload/"
                f"{self.qr_code_public_id}.png"
            )
        return None

    @property
    def can_upload_to_gallery(self):
        """Check if memorial can upload gallery images."""
        if not self.plan:
            return False
        return self.plan.allow_gallery

    @property
    def max_gallery_images(self):
        """Return the maximum allowed gallery images."""
        if self.can_upload_to_gallery:
            return 9  # Premium limit
        return 3  # Free tier limit

    @property
    def remaining_gallery_slots(self):
        """Return how many more images can be uploaded."""
        return max(0, self.max_gallery_images - self.gallery.count())

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Tribute(models.Model):
    """
    Model for memorial tributes/messages.
    Allows users to leave messages for the memorialized individual.
    """
    memorial = models.ForeignKey(
        Memorial, related_name='tributes', on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    author_name = models.CharField(max_length=100)
    message = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Tribute by {self.author_name} for {self.memorial}"


class GalleryImage(models.Model):
    """
    Model for memorial gallery images.
    Stores images associated with a memorial with optional captions.
    """
    memorial = models.ForeignKey(
        Memorial, on_delete=models.CASCADE, related_name='gallery'
    )
    image = CloudinaryField('image')
    caption = models.CharField(max_length=255, blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Image for {self.memorial}"


class Story(models.Model):
    """
    Model for longer memorial stories.
    Allows for more detailed narratives about the memorialized individual.
    """
    memorial = models.ForeignKey(
        Memorial, related_name='stories', on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    author_name = models.CharField(max_length=100)
    title = models.CharField(max_length=200)
    content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Stories"

    def __str__(self):
        return f"Story: {self.title} by {self.author_name}"


class ContactMessage(models.Model):
    """
    Model for website contact form submissions.
    Stores messages from users contacting the site administrators.
    """
    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=100)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.subject} - {self.name}"
