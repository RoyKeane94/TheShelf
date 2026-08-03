from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.text import slugify

from .models import Profile
from .urlnorm import normalise_url

User = get_user_model()


class SignupForm(UserCreationForm):
    handle = forms.SlugField(
        max_length=40,
        help_text="Your public name. Letters, numbers, hyphens.",
    )
    display_name = forms.CharField(max_length=120, required=False)
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("handle", "display_name", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # UserCreationForm always includes username; we drive auth from handle instead.
        if "username" in self.fields:
            del self.fields["username"]
        placeholders = {
            "handle": "tom",
            "display_name": "Tom Jones",
            "email": "you@example.com",
            "password1": "At least 8 characters",
            "password2": "Repeat your password",
        }
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "field")
            if name in placeholders:
                field.widget.attrs.setdefault("placeholder", placeholders[name])

    def clean_handle(self):
        handle = slugify(self.cleaned_data["handle"])
        if not handle:
            raise forms.ValidationError("Pick a handle.")
        if Profile.objects.filter(handle=handle).exists() or User.objects.filter(username=handle).exists():
            raise forms.ValidationError("That handle is taken.")
        return handle

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["handle"]
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
            profile = user.profile
            profile.handle = self.cleaned_data["handle"]
            profile.display_name = (
                self.cleaned_data.get("display_name") or self.cleaned_data["handle"]
            )
            profile.save(update_fields=["handle", "display_name", "updated_at"])
        return user


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Handle"
        placeholders = {
            "username": "tom",
            "password": "Your password",
        }
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "field")
            if name in placeholders:
                field.widget.attrs.setdefault("placeholder", placeholders[name])


class AccountSettingsForm(forms.Form):
    handle = forms.SlugField(
        max_length=40,
        help_text="Your public name. Letters, numbers, hyphens.",
    )
    display_name = forms.CharField(max_length=120, required=False)
    email = forms.EmailField(required=True)
    bio = forms.CharField(
        max_length=280,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional. One or two lines on your profile.",
    )
    new_password1 = forms.CharField(
        label="New password",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Leave blank to keep your current password.",
    )
    new_password2 = forms.CharField(
        label="Confirm new password",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        placeholders = {
            "handle": "tom",
            "display_name": "Tom Jones",
            "email": "you@example.com",
            "bio": "What you keep on the shelf.",
            "new_password1": "At least 8 characters",
            "new_password2": "Repeat new password",
        }
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "field")
            if name in placeholders:
                field.widget.attrs.setdefault("placeholder", placeholders[name])

    def clean_handle(self):
        handle = slugify(self.cleaned_data["handle"])
        if not handle:
            raise forms.ValidationError("Pick a handle.")
        taken = (
            Profile.objects.filter(handle=handle).exclude(user=self.user).exists()
            or User.objects.filter(username=handle).exclude(pk=self.user.pk).exists()
        )
        if taken:
            raise forms.ValidationError("That handle is taken.")
        return handle

    def clean_email(self):
        return self.cleaned_data["email"].strip()

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password1") or ""
        p2 = cleaned.get("new_password2") or ""
        if p1 or p2:
            if p1 != p2:
                self.add_error("new_password2", "The two passwords don’t match.")
            else:
                try:
                    validate_password(p1, self.user)
                except DjangoValidationError as exc:
                    self.add_error("new_password1", exc)
        return cleaned

    def save(self):
        profile = self.user.profile
        handle = self.cleaned_data["handle"]
        self.user.username = handle
        self.user.email = self.cleaned_data["email"]
        if self.cleaned_data.get("new_password1"):
            self.user.set_password(self.cleaned_data["new_password1"])
        self.user.save()
        profile.handle = handle
        profile.display_name = (
            self.cleaned_data.get("display_name") or handle
        )
        profile.bio = self.cleaned_data.get("bio") or ""
        profile.save(update_fields=["handle", "display_name", "bio", "updated_at"])
        return self.user


class AddEssayForm(forms.Form):
    title = forms.CharField(max_length=500)
    url = forms.CharField(max_length=1000)
    blurb = forms.CharField(min_length=15, max_length=2000, widget=forms.Textarea)
    half_stars = forms.IntegerField(required=False, min_value=0, max_value=10)

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if not title:
            raise forms.ValidationError("Give it a title.")
        return title

    def clean_url(self):
        raw = self.cleaned_data["url"].strip()
        normalised = normalise_url(raw)
        host = normalised.split("://", 1)[-1].split("/")[0] if normalised else ""
        if not normalised or "." not in host:
            raise forms.ValidationError("That URL does not look right.")
        return normalised

    def clean_blurb(self):
        return self.cleaned_data["blurb"].strip()

    def clean_half_stars(self):
        value = self.cleaned_data.get("half_stars")
        if value in (None, ""):
            return None
        value = int(value)
        if value == 0:
            return None
        return value
