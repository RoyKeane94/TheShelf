/* The Shelf — client behaviour.
   Stars, add modal, engraved footer, toasts, scroll reveals.
   Logging itself is HTMX; this file only wires the local widgets.
*/

const STAR_D = "M12 2.6l2.9 5.9 6.5.95-4.7 4.6 1.1 6.45L12 17.45 6.2 20.5l1.1-6.45-4.7-4.6 6.5-.95z";

/* ── toast ───────────────────────────── */
function showToast(html) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.innerHTML = html;
  t.classList.add("on");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => t.classList.remove("on"), 2400);
}
// HTMX only swaps 2xx by default. A form that fails validation comes back as 422
// carrying the re-rendered fields, so without this the submit button does nothing
// and the errors never reach the page.
document.body.addEventListener("htmx:beforeSwap", (ev) => {
  if (ev.detail.xhr.status === 422) {
    ev.detail.shouldSwap = true;
    ev.detail.isError = false;
  }
});
document.body.addEventListener("toast", (ev) => {
  const detail = ev.detail;
  const msg = typeof detail === "string" ? detail : detail && detail.value;
  if (msg) showToast(msg);
});
document.body.addEventListener("closeModal", () => closeModal());

/* ── stars ───────────────────────────── */
function wireStars(root) {
  const row = root.querySelector(".star-row");
  if (!row || row.dataset.wired) return null;
  row.dataset.wired = "1";
  const val = root.querySelector(".star-val");
  const clear = root.querySelector(".star-clear");
  const input = root.querySelector('input[name="half_stars"]');
  const stars = [...row.querySelectorAll(".star")];
  let set = parseInt(row.dataset.value || "0", 10) || 0;

  const paint = (h) => {
    stars.forEach((st, i) => {
      const full = (i + 1) * 2;
      const clip = st.querySelector(".star-clip");
      clip.style.width = h >= full ? "100%" : h === full - 1 ? "50%" : "0%";
    });
    const shown = h || set;
    if (val) {
      val.innerHTML = shown
        ? (shown / 2).toFixed(1).replace(".0", "") + " <em>/ 5</em>"
        : "<em>No rating</em>";
    }
    row.setAttribute("aria-valuenow", (shown / 2).toString());
    if (input) input.value = set || "";
    if (clear) clear.hidden = !set;
  };

  const halfAt = (ev) => {
    const st = ev.target.closest(".star");
    if (!st) return 0;
    const r = st.getBoundingClientRect();
    return +st.dataset.i * 2 - (ev.clientX - r.left < r.width / 2 ? 1 : 0);
  };

  // Inside a log control the stars write straight through to the server. On the add
  // form there is nothing to post to yet, so the value just rides along on submit.
  const logForm = root.closest("form[data-log-form]");
  let committed = set;
  const commit = () => {
    if (!logForm || set === committed) return;
    committed = set;
    const hs = logForm.querySelector('input[name="half_stars"]');
    // String(set) so clearing sends an explicit 0. paint() writes "" for "no rating",
    // which the server reads as "leave the rating alone" — right for the Log it
    // button, wrong for somebody deliberately clearing a star.
    if (hs) hs.value = String(set);
    if (window.htmx) htmx.trigger(logForm, "submit");
  };

  const apply = (value) => {
    set = value;
    row.dataset.value = String(set);
    paint(set);
  };

  row.addEventListener("mousemove", (ev) => {
    const h = halfAt(ev);
    if (h) paint(h);
  });
  row.addEventListener("mouseleave", () => paint(set));
  row.addEventListener("click", (ev) => {
    const h = halfAt(ev);
    if (!h) return;
    apply(set === h ? 0 : h); // tapping the same value again clears it
    commit();
  });
  row.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowRight" || ev.key === "ArrowUp") apply(Math.min(10, set + 1));
    else if (ev.key === "ArrowLeft" || ev.key === "ArrowDown") apply(Math.max(0, set - 1));
    else if (ev.key === "Home") apply(0);
    else if (ev.key === "End") apply(10);
    else if (ev.key === "Enter" || ev.key === " ") commit();
    else return;
    ev.preventDefault();
  });
  // Arrow keys step without posting so holding a key does not fire ten requests;
  // leaving the control saves whatever it landed on.
  row.addEventListener("blur", commit);
  if (clear) {
    clear.addEventListener("click", () => {
      apply(0);
      commit();
    });
  }
  paint(set);
  return {
    get value() {
      return set;
    },
    reset() {
      set = 0;
      row.dataset.value = "0";
      paint(0);
    },
  };
}

function wireAllStars(scope) {
  (scope || document).querySelectorAll("[data-stars]").forEach(wireStars);
}

/* ── modal ───────────────────────────── */
let lastFocus = null;
function openModal() {
  const modal = document.getElementById("modal");
  const mscrim = document.getElementById("mscrim");
  if (!modal) return;
  lastFocus = document.activeElement;
  modal.classList.add("on");
  mscrim.classList.add("on");
  modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  const mount = document.getElementById("modalmount");
  if (mount && window.htmx && !mount.dataset.loaded) {
    htmx.ajax("GET", mount.dataset.url, { target: "#modalmount", swap: "innerHTML" }).then(() => {
      mount.dataset.loaded = "1";
      wireAllStars(mount);
      const first = mount.querySelector("input,textarea,button");
      if (first) first.focus();
    });
  } else {
    setTimeout(() => {
      const first = modal.querySelector("input,textarea,button");
      if (first) first.focus();
    }, 200);
  }
}
function closeModal() {
  const modal = document.getElementById("modal");
  const mscrim = document.getElementById("mscrim");
  if (!modal) return;
  modal.classList.remove("on");
  mscrim.classList.remove("on");
  modal.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  if (lastFocus) lastFocus.focus();
}

/* ── engraving ───────────────────────── */
function mulberry32(a) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function buildEngraving() {
  const host = document.getElementById("engraving");
  if (!host) return;
  const W = 1600,
    H = 330,
    BASE = 306,
    INK = "#15181F",
    CREAM = "#F7F6F2";
  const rng = mulberry32(31072026);
  const hatches = ["url(#hA)", "url(#hB)", "url(#hC)", "url(#hX)", "url(#hA)", "url(#hB)"];
  const pick = (a) => a[Math.floor(rng() * a.length)];
  const env = (x) => 0.5 + 0.3 * Math.sin(x / 236 + 0.9) + 0.2 * Math.sin(x / 88 + 2.2);
  let g = "";

  const spine = (x, w, h, accent) => {
    const top = BASE - h;
    const fill = accent || pick(hatches);
    let s = `<rect x="${x}" y="${top}" width="${w}" height="${h}" fill="${fill}" stroke="${INK}" stroke-width="${accent ? 1.1 : 1}"/>`;
    if (w > 18) {
      const b1 = top + 13,
        b2 = BASE - 16;
      s +=
        `<line x1="${x + 2}" y1="${b1}" x2="${x + w - 2}" y2="${b1}" stroke="${INK}" stroke-width=".9"/>` +
        `<line x1="${x + 2}" y1="${b1 + 4}" x2="${x + w - 2}" y2="${b1 + 4}" stroke="${INK}" stroke-width=".9"/>` +
        `<line x1="${x + 2}" y1="${b2}" x2="${x + w - 2}" y2="${b2}" stroke="${INK}" stroke-width=".9"/>`;
    }
    if (w > 22 && rng() < 0.7) {
      const ty = top + 34,
        n = 1 + Math.floor(rng() * 3);
      for (let i = 0; i < n; i++) {
        s += `<line x1="${x + 5}" y1="${ty + i * 7}" x2="${x + w - 5}" y2="${ty + i * 7}" stroke="${accent ? CREAM : INK}" stroke-width="1.4" opacity=".8"/>`;
      }
    }
    return s;
  };

  const stack = (x, n) => {
    let s = "",
      yy = BASE;
    for (let i = 0; i < n; i++) {
      const w = 44 + Math.round(rng() * 34),
        h = 9 + Math.round(rng() * 5);
      yy -= h;
      s +=
        `<rect x="${x}" y="${yy}" width="${w}" height="${h}" fill="${pick(hatches)}" stroke="${INK}" stroke-width="1"/>` +
        `<line x1="${x + 3}" y1="${yy + h / 2}" x2="${x + w - 3}" y2="${yy + h / 2}" stroke="${INK}" stroke-width=".8" opacity=".55"/>`;
    }
    return s;
  };

  let x = 4;
  while (x < W - 8) {
    const roll = rng();
    if (roll < 0.055) {
      g += stack(x, 2 + Math.floor(rng() * 3));
      x += 52 + Math.round(rng() * 30);
      continue;
    }
    const w = 15 + Math.round(rng() * 29);
    if (x + w > W - 4) break;
    const h = Math.max(70, Math.round(96 + env(x) * 152 + (rng() - 0.5) * 46));
    const accent = rng() < 0.13 ? (rng() < 0.5 ? "var(--blue)" : "var(--orange)") : null;
    if (roll > 0.94) {
      g += `<g transform="rotate(${(rng() < 0.5 ? -1 : 1) * (6 + rng() * 5)} ${x} ${BASE})">${spine(x, w, Math.round(h * 0.9), accent)}</g>`;
      x += w + 6;
    } else {
      g += spine(x, w, h, accent);
      x += w + 1;
    }
  }

  host.innerHTML = `
  <svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="An engraved range of book spines">
    <defs>
      <pattern id="hA" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="8" height="8" fill="${CREAM}"/><line x1="0" y1="0" x2="0" y2="8" stroke="${INK}" stroke-width=".7"/></pattern>
      <pattern id="hB" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="5" height="5" fill="${CREAM}"/><line x1="0" y1="0" x2="0" y2="5" stroke="${INK}" stroke-width=".65"/></pattern>
      <pattern id="hC" width="3.2" height="3.2" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="3.2" height="3.2" fill="${CREAM}"/><line x1="0" y1="0" x2="0" y2="3.2" stroke="${INK}" stroke-width=".6"/></pattern>
      <pattern id="hX" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(30)">
        <rect width="7" height="7" fill="${CREAM}"/>
        <line x1="0" y1="0" x2="0" y2="7" stroke="${INK}" stroke-width=".55"/>
        <line x1="0" y1="0" x2="7" y2="0" stroke="${INK}" stroke-width=".55"/></pattern>
    </defs>
    ${g}
    <rect x="0" y="${BASE}" width="${W}" height="13" fill="${CREAM}" stroke="${INK}" stroke-width="1.4"/>
    <line x1="0" y1="${BASE + 17}" x2="${W}" y2="${BASE + 17}" stroke="${INK}" stroke-width=".7" opacity=".45"/>
    <line x1="0" y1="${BASE + 21}" x2="${W}" y2="${BASE + 21}" stroke="${INK}" stroke-width=".7" opacity=".28"/>
  </svg>`;
}

/* ── reveals ─────────────────────────── */
function initReveals() {
  const els = [...document.querySelectorAll(".rv")];
  if (!("IntersectionObserver" in window)) {
    els.forEach((el) => el.classList.add("in"));
    return;
  }
  const io = new IntersectionObserver(
    (entries) => {
      entries
        .filter((en) => en.isIntersecting)
        .forEach((en, i) => {
          setTimeout(() => en.target.classList.add("in"), i * 90);
          io.unobserve(en.target);
        });
    },
    { threshold: 0.16, rootMargin: "0px 0px -8% 0px" }
  );
  els.forEach((el) => io.observe(el));
}

/* ── boot ────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  wireAllStars();
  buildEngraving();
  initReveals();

  document.querySelectorAll("[data-addmodal]").forEach((a) =>
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      if (a.dataset.auth === "0") {
        window.location = a.getAttribute("href") || "/login/";
        return;
      }
      openModal();
    })
  );
  const mclose = document.getElementById("mclose");
  const mscrim = document.getElementById("mscrim");
  if (mclose) mclose.addEventListener("click", closeModal);
  if (mscrim) mscrim.addEventListener("click", closeModal);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  const modal = document.getElementById("modal");
  if (modal) {
    modal.addEventListener("keydown", (ev) => {
      if (ev.key !== "Tab") return;
      const f = [...modal.querySelectorAll('a[href],button:not([hidden]),input,textarea,[tabindex="0"]')].filter(
        (el) => el.offsetParent !== null
      );
      if (!f.length) return;
      const first = f[0],
        last = f[f.length - 1];
      if (ev.shiftKey && document.activeElement === first) {
        ev.preventDefault();
        last.focus();
      } else if (!ev.shiftKey && document.activeElement === last) {
        ev.preventDefault();
        first.focus();
      }
    });
  }
});

document.body.addEventListener("htmx:afterSwap", (ev) => {
  wireAllStars(ev.target);
});
