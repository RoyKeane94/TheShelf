from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
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
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault("class", "field")

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
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault("class", "field")


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
