from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("discover/", views.discover, name="discover"),
    path("add/", views.add, name="add"),
    path("add/form/", views.add_modal, name="add_modal"),
    path("add/submit/", views.add_htmx, name="add_htmx"),
    path("e/<slug:slug>/", views.essay_detail, name="essay"),
    path("e/<slug:slug>/log/", views.log, name="log"),
    path("signup/", views.signup, name="signup"),
    path("login/", views.ShelfLoginView.as_view(), name="login"),
    path("logout/", views.ShelfLogoutView.as_view(), name="logout"),
    path("@<slug:handle>/", views.profile, name="profile"),
    path("@<slug:handle>/<slug:shelf_slug>/", views.shelf_detail, name="shelf"),
]
