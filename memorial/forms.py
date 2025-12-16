from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Memorial, Tribute, GalleryImage, Story, ContactMessage


# --- Memorial Form ---
class MemorialForm(forms.ModelForm):
    """Form for creating/editing memorial profiles."""
    class Meta:
        model = Memorial
        fields = [
            'first_name', 'middle_name', 'last_name',
            'date_of_birth', 'date_of_death',
            'profile_picture', 'audio_file', 'quote'
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'date_of_birth': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}
            ),
            'date_of_death': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}
            ),
        }

    def clean_date_of_birth(self):
        """Validate that date of birth is not in the future"""
        date_of_birth = self.cleaned_data['date_of_birth']
        if date_of_birth and date_of_birth > timezone.now().date():
            raise ValidationError("Date of birth cannot be in the future. Please select a past date.")
        return date_of_birth

    def clean_date_of_death(self):
        """Validate that date of death is not in the future"""
        date_of_death = self.cleaned_data['date_of_death']
        if date_of_death and date_of_death > timezone.now().date():
            raise ValidationError("Date of death cannot be in the future. Please select a past date.")
        return date_of_death

    def clean(self):
        """Additional validation to ensure death date is after birth date"""
        cleaned_data = super().clean()
        date_of_birth = cleaned_data.get('date_of_birth')
        date_of_death = cleaned_data.get('date_of_death')
        
        # Only validate if both dates are provided
        if date_of_birth and date_of_death:
            if date_of_death < date_of_birth:
                raise ValidationError({
                    'date_of_death': 'Date of death cannot be before date of birth.'
                })
        
        return cleaned_data


# --- Tribute Form ---
class TributeForm(forms.ModelForm):
    """Form for submitting tributes/memories."""
    class Meta:
        model = Tribute
        fields = ['author_name', 'message']
        widgets = {
            'author_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your Name'
            }),
            'message': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Write your tribute...'
            }),
        }
        labels = {
            'author_name': 'Your Name',
            'message': 'Tribute Message',
        }


# --- Gallery Image Form ---
class GalleryImageForm(forms.ModelForm):
    """Form for uploading memorial gallery images."""
    class Meta:
        model = GalleryImage
        fields = ['image', 'caption']


# --- Story Form ---
class StoryForm(forms.ModelForm):
    """Form for sharing longer memorial stories."""
    class Meta:
        model = Story
        fields = ['author_name', 'title', 'content']
        widgets = {
            'author_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your Name'
            }),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Story Title'
            }),
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Share your story...'
            }),
        }
        labels = {
            'author_name': 'Your Name',
            'title': 'Story Title',
            'content': 'Your Story',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['content'].widget.attrs.update({'minlength': '50'})


# --- Contact Form ---
class ContactForm(forms.ModelForm):
    """Form for general website contact messages."""
    class Meta:
        model = ContactMessage
        fields = ['name', 'email', 'subject', 'message']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Your full name'}),
            'email': forms.EmailInput(attrs={
                'placeholder': 'Your email address'}),
            'subject': forms.TextInput(
                attrs={'placeholder': 'Message subject'}
            ),
            'message': forms.Textarea(attrs={
                'placeholder': 'Your message here...',
                'rows': 5
            }),
        }