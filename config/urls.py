from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("shelf.urls")),
]

handler400 = "shelf.views.bad_request"
handler403 = "shelf.views.permission_denied"
handler404 = "shelf.views.page_not_found"
handler500 = "shelf.views.server_error"
