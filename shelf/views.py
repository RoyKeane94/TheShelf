import json

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import AccountSettingsForm, AddEssayForm, LoginForm, SignupForm
from .models import Essay, Log, Note, Profile, Rating, Shelf, Shelving
from .ranking import circulation, ranked, with_stats
from .services import add_essay, log_essay, user_has_logged, user_rating


def _shelf_cards():
    active = Q(shelvings__removed_at__isnull=True)
    return (
        Shelf.objects.filter(is_public=True)
        .annotate(n_items=Count("shelvings", filter=active, distinct=True))
        .filter(n_items__gt=0)
        .select_related("owner__profile")
        .prefetch_related(
            Prefetch(
                "shelvings",
                queryset=Shelving.objects.filter(removed_at__isnull=True)
                .select_related("essay")
                .order_by("-created_at"),
                to_attr="active_shelvings",
            )
        )
    )


def _featured_shelves(limit=6):
    """Shelves for the discovery grid, named ones first.

    A default shelf is where everything lands, so it is always the biggest and
    almost never the most interesting. Naming a shelf is the act of curation this
    section exists to show, so named shelves win regardless of size.
    """
    cards = _shelf_cards()
    named = list(cards.filter(is_default=False).order_by("-n_items", "name")[:limit])
    if len(named) >= limit:
        return named
    # Before anyone has named a shelf there is nothing else to show, so fall back
    # to the fullest default shelves rather than rendering an empty section.
    fallback = cards.filter(is_default=True).order_by("-n_items", "name")[
        : limit - len(named)
    ]
    return named + list(fallback)


def _newly_logged(limit=8, per_user=2, per_essay=2):
    """The most recent stamps, capped per person and per essay.

    Both caps exist for the same reason: this is a browsing surface, and a row spent
    repeating something already above it is a row wasted. Without them one person
    filing a shelf in a sitting, or one popular piece having a good week, takes the
    whole feed.
    """
    rows = (
        Shelving.objects.filter(removed_at__isnull=True)
        .select_related("user__profile", "essay", "shelf")
        .order_by("-created_at")[: limit * 20]
    )
    by_user = {}
    by_essay = {}
    out = []
    for shelving in rows:
        if by_user.get(shelving.user_id, 0) >= per_user:
            continue
        if by_essay.get(shelving.essay_id, 0) >= per_essay:
            continue
        by_user[shelving.user_id] = by_user.get(shelving.user_id, 0) + 1
        by_essay[shelving.essay_id] = by_essay.get(shelving.essay_id, 0) + 1
        out.append(shelving)
        if len(out) == limit:
            break
    return out


def _related(essay, limit=4):
    tags = set(essay.tags or [])
    if not tags:
        return []
    candidates = Essay.objects.filter(is_published=True).exclude(pk=essay.pk)
    scored = []
    for other in candidates:
        overlap = tags.intersection(other.tags or [])
        if overlap:
            scored.append((len(overlap), other, sorted(overlap)))
    scored.sort(key=lambda t: (-t[0], t[1].title))
    return [{"essay": e, "shared": shared} for _, e, shared in scored[:limit]]


def _attach_viewer_state(request, essays):
    """Hang the viewer's own log and rating on each essay.

    Every list that shows an essay also offers to log it, and the button has to know
    whether this reader already has. Two queries for the whole page rather than one
    per row.
    """
    ids = [e.pk for e in essays]
    logged = set()
    ratings = {}
    if request.user.is_authenticated and ids:
        logged = set(
            Shelving.objects.filter(
                user=request.user, essay_id__in=ids, removed_at__isnull=True
            ).values_list("essay_id", flat=True)
        )
        ratings = {
            r.essay_id: r
            for r in Rating.objects.filter(user=request.user, essay_id__in=ids)
        }
    for essay in essays:
        essay.viewer_logged = essay.pk in logged
        essay.viewer_rating = ratings.get(essay.pk)
    return essays


def _discovery_example():
    """Three things one curator filed, and the piece the overlap points at.

    Built from real rows rather than a fixture, so the landing page demonstrates the
    mechanic instead of describing it. Returns None when the catalogue cannot support
    the example and the section is skipped.
    """
    shelf = (
        Shelf.objects.filter(is_public=True, is_default=False)
        .annotate(
            n_items=Count(
                "shelvings", filter=Q(shelvings__removed_at__isnull=True), distinct=True
            )
        )
        .filter(n_items__gte=3)
        .select_related("owner__profile")
        .order_by("-n_items")
        .first()
    )
    if shelf is None:
        return None

    picks = [
        s.essay
        for s in Shelving.objects.filter(shelf=shelf, removed_at__isnull=True)
        .select_related("essay")
        .order_by("-created_at")[:3]
    ]
    if len(picks) < 3:
        return None

    tags = set()
    for essay in picks:
        tags.update(essay.tags or [])
    if not tags:
        return None

    already_read = set(
        Shelving.objects.filter(user=shelf.owner, removed_at__isnull=True).values_list(
            "essay_id", flat=True
        )
    )
    scored = []
    for candidate in Essay.objects.filter(is_published=True).exclude(
        pk__in=already_read
    ):
        overlap = len(tags.intersection(candidate.tags or []))
        if overlap:
            scored.append((-overlap, candidate.title, candidate))
    if not scored:
        return None
    scored.sort()

    def named_holder(essay):
        return (
            Shelving.objects.filter(
                essay=essay,
                removed_at__isnull=True,
                shelf__is_default=False,
                shelf__is_public=True,
            )
            .exclude(user=shelf.owner)
            .select_related("user__profile")
            .order_by("created_at")
            .first()
        )

    # Prefer a piece somebody filed on a shelf they bothered to name: the point of the
    # card is that a person put it there, not that two tags matched.
    holder = None
    for _, _, essay in scored[:40]:
        holder = named_holder(essay)
        if holder:
            candidate = essay
            break
    else:
        # Nothing curated overlaps, so fall back to the circulation record instead of
        # crediting whichever default shelf happens to hold it.
        candidate = scored[0][2]

    since = (
        holder.created_at.year
        if holder
        else Shelving.objects.filter(essay=candidate, removed_at__isnull=True)
        .order_by("created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    return {
        "shelf": shelf,
        "picks": picks,
        "found": candidate,
        "holder": holder,
        "since_year": since if isinstance(since, int) else getattr(since, "year", None),
    }


@require_GET
def landing(request):
    essays = ranked(Essay.objects.filter(is_published=True), limit=40)
    shelves = _featured_shelves()
    feed = _newly_logged(6)
    held = ranked(Essay.objects.filter(is_published=True), limit=6)
    for e in held:
        e.circ = circulation(e)
    held_years = [e.circ["first_year"] for e in held if e.circ]
    return render(
        request,
        "shelf/landing.html",
        {
            "spines": essays,
            "shelves": shelves,
            "example": _discovery_example(),
            "feed": feed,
            "held": held,
            "held_min_year": min(held_years) if held_years else None,
            "add_form": AddEssayForm(),
            "form_prefix": "sec",
        },
    )


@require_GET
def essay_detail(request, slug):
    essay = get_object_or_404(
        with_stats(Essay.objects.filter(is_published=True)), slug=slug
    )
    notes = (
        Note.objects.filter(essay=essay, is_hidden=False)
        .select_related("user__profile")
        .order_by("-created_at")[:20]
    )
    # Named shelves only. Every logger's default shelf technically holds this piece,
    # so listing those would just be the log count again in a slower form.
    on_shelves = (
        Shelf.objects.filter(
            is_public=True,
            is_default=False,
            shelvings__essay=essay,
            shelvings__removed_at__isnull=True,
        )
        .select_related("owner__profile")
        .distinct()[:12]
    )
    logged = user_has_logged(request.user, essay)
    rating = user_rating(request.user, essay)
    return render(
        request,
        "shelf/essay.html",
        {
            "essay": essay,
            "circ": circulation(essay),
            "notes": notes,
            "on_shelves": on_shelves,
            "related": _related(essay),
            "logged": logged,
            "rating": rating,
        },
    )


@require_GET
def profile(request, handle):
    profile = get_object_or_404(Profile.objects.select_related("user"), handle=handle)
    shelves = (
        Shelf.objects.filter(owner=profile.user, is_public=True)
        .annotate(
            n_items=Count(
                "shelvings", filter=Q(shelvings__removed_at__isnull=True), distinct=True
            )
        )
        .prefetch_related(
            Prefetch(
                "shelvings",
                queryset=Shelving.objects.filter(removed_at__isnull=True)
                .select_related("essay")
                .order_by("-created_at"),
                to_attr="active_shelvings",
            )
        )
        .order_by("position", "name")
    )
    recent = list(
        Shelving.objects.filter(user=profile.user, removed_at__isnull=True)
        .select_related("essay", "shelf")
        .order_by("-created_at")[:12]
    )
    ratings = {
        r.essay_id: r
        for r in Rating.objects.filter(
            user=profile.user, essay_id__in=[s.essay_id for s in recent]
        )
    }
    for s in recent:
        s.user_rating = ratings.get(s.essay_id)
    return render(
        request,
        "shelf/profile.html",
        {
            "profile": profile,
            "shelves": shelves,
            "recent": recent,
        },
    )


@require_GET
def shelf_detail(request, handle, shelf_slug):
    profile = get_object_or_404(Profile.objects.select_related("user"), handle=handle)
    shelf = get_object_or_404(
        Shelf.objects.filter(owner=profile.user, is_public=True), slug=shelf_slug
    )
    shelvings = list(
        Shelving.objects.filter(shelf=shelf, removed_at__isnull=True)
        .select_related("essay")
        .order_by("-created_at")
    )
    essay_ids = [s.essay_id for s in shelvings]
    user_logged = set()
    user_ratings = {}
    if request.user.is_authenticated and essay_ids:
        user_logged = set(
            Shelving.objects.filter(
                user=request.user, essay_id__in=essay_ids, removed_at__isnull=True
            ).values_list("essay_id", flat=True)
        )
        user_ratings = {
            r.essay_id: r
            for r in Rating.objects.filter(user=request.user, essay_id__in=essay_ids)
        }
    for s in shelvings:
        s.viewer_logged = s.essay_id in user_logged
        s.viewer_rating = user_ratings.get(s.essay_id)
    return render(
        request,
        "shelf/shelf.html",
        {
            "profile": profile,
            "shelf": shelf,
            "shelvings": shelvings,
        },
    )


@require_GET
def discover(request):
    feed = _newly_logged(24)
    held = ranked(Essay.objects.filter(is_published=True), limit=24)
    for e in held:
        e.circ = circulation(e)
    held_years = [e.circ["first_year"] for e in held if e.circ]
    _attach_viewer_state(request, held + [f.essay for f in feed])
    return render(
        request,
        "shelf/discover.html",
        {
            "feed": feed,
            "held": held,
            "held_min_year": min(held_years) if held_years else None,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def add(request):
    if request.method == "POST":
        form = AddEssayForm(request.POST)
        if form.is_valid():
            result = add_essay(
                request.user,
                title=form.cleaned_data["title"],
                url=form.cleaned_data["url"],
                blurb=form.cleaned_data["blurb"],
                half_stars=form.cleaned_data.get("half_stars"),
            )
            if result.created:
                messages.success(request, f"Added {result.essay.title}.")
            else:
                messages.info(
                    request,
                    f"Already on the shelf — logged {result.essay.title} for you.",
                )
            return redirect(result.essay.get_absolute_url())
    else:
        form = AddEssayForm()
    return render(
        request,
        "shelf/add.html",
        {"form": form, "form_prefix": "page"},
    )


@login_required
@require_POST
def log(request, slug):
    essay = get_object_or_404(Essay, slug=slug, is_published=True)
    half_stars = request.POST.get("half_stars")
    if half_stars is not None and half_stars != "":
        try:
            half_stars = int(half_stars)
        except (TypeError, ValueError):
            half_stars = None
    else:
        half_stars = None

    result = log_essay(request.user, essay, half_stars=half_stars)
    logged = True
    rating = result.rating

    if request.headers.get("HX-Request"):
        response = render(
            request,
            "shelf/partials/log_control.html",
            {
                "essay": essay,
                "logged": logged,
                "rating": rating,
                "compact": request.POST.get("compact") == "1",
            },
        )
        if result.created:
            message = "Logged · stamped on your shelf"
        elif half_stars == 0:
            message = "Rating cleared"
        elif half_stars is not None:
            message = "Rating saved"
        else:
            message = "Already on your shelf"
        response["HX-Trigger"] = json.dumps({"toast": message})
        return response

    return redirect(essay.get_absolute_url())


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("landing")
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome, @{user.profile.handle}.")
            return redirect("landing")
    else:
        form = SignupForm()
    return render(request, "shelf/signup.html", {"form": form})


class ShelfLoginView(LoginView):
    template_name = "shelf/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@login_required
@require_http_methods(["GET", "POST"])
def account_settings(request):
    profile = request.user.profile
    if request.method == "POST":
        form = AccountSettingsForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            if form.cleaned_data.get("new_password1"):
                update_session_auth_hash(request, request.user)
            messages.success(request, "Settings saved.")
            return redirect("settings")
    else:
        form = AccountSettingsForm(
            request.user,
            initial={
                "handle": profile.handle,
                "display_name": profile.display_name,
                "email": request.user.email,
                "bio": profile.bio,
            },
        )
    return render(request, "shelf/settings.html", {"form": form})


@require_http_methods(["GET", "POST"])
def logout_view(request):
    if not request.user.is_authenticated:
        return redirect("landing")
    if request.method == "POST":
        logout(request)
        messages.success(request, "You’re logged out.")
        return redirect("landing")
    return render(request, "shelf/logout.html")


_ERROR_COPY = {
    400: {
        "title": "That request didn’t make sense.",
        "sub": "Something in the ask was off. Go back to the shelf and try again from there.",
    },
    403: {
        "title": "You’re not allowed on this page.",
        "sub": "This corner of the shelf is closed. Browse what’s public, or log in if you have an account.",
    },
    404: {
        "title": "This page isn’t on the shelf.",
        "sub": "Nothing lives at that address. The shelves below are still open — pick one up from there.",
    },
    500: {
        "title": "Something broke on our side.",
        "sub": "The request didn’t finish. We’ve noted it. Give it a moment, then try again.",
    },
}


def _error_shelves():
    try:
        return _featured_shelves()
    except Exception:
        return []


def _render_error(request, status_code, exception=None):
    copy = _ERROR_COPY.get(status_code, _ERROR_COPY[500])
    path = getattr(request, "path", "") or ""
    Log.record(
        kind=f"error.{status_code}",
        status_code=status_code,
        path=path,
        message=str(exception) if exception else "",
        user=getattr(request, "user", None),
        meta={"method": getattr(request, "method", "")},
    )
    return render(
        request,
        "shelf/error.html",
        {
            "status_code": status_code,
            "error_title": copy["title"],
            "error_sub": copy["sub"],
            "shelves": _error_shelves(),
        },
        status=status_code,
    )


def bad_request(request, exception):
    return _render_error(request, 400, exception)


def permission_denied(request, exception):
    return _render_error(request, 403, exception)


def page_not_found(request, exception):
    return _render_error(request, 404, exception)


def server_error(request):
    return _render_error(request, 500)


@login_required
@require_GET
def add_modal(request):
    """HTMX fragment: the add form for the nav modal."""
    return render(
        request,
        "shelf/partials/add_form.html",
        {"form": AddEssayForm(), "form_prefix": "mod", "in_modal": True},
    )


@login_required
@require_POST
def add_htmx(request):
    """HTMX submit of the shared add form (landing section or modal)."""
    form = AddEssayForm(request.POST)
    prefix = request.POST.get("form_prefix", "sec")
    in_modal = request.POST.get("in_modal") == "1"
    if not form.is_valid():
        return render(
            request,
            "shelf/partials/add_form.html",
            {"form": form, "form_prefix": prefix, "in_modal": in_modal},
            status=422,
        )
    result = add_essay(
        request.user,
        title=form.cleaned_data["title"],
        url=form.cleaned_data["url"],
        blurb=form.cleaned_data["blurb"],
        half_stars=form.cleaned_data.get("half_stars"),
    )
    response = render(
        request,
        "shelf/partials/add_done.html",
        {
            "essay": result.essay,
            "created": result.created,
            "rating": result.rating,
            "form_prefix": prefix,
        },
    )
    # json.dumps, not an f-string: the title is user input and a stray quote would
    # produce a header HTMX cannot parse.
    trigger = {"toast": f"Added {result.essay.title}"}
    if in_modal:
        trigger["closeModal"] = True
    response["HX-Trigger"] = json.dumps(trigger)
    # Prefer a redirect header so HTMX can navigate to the new page.
    response["HX-Redirect"] = result.essay.get_absolute_url()
    return response
