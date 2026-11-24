// Sysopty marketing site: navigation, lightbox, topology demo and enquiry form.
(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  // ---------- Header and navigation ----------
  var header = $(".site-header");
  var nav = $("#site-nav");
  var toggle = $(".nav-toggle");

  function onScroll() { header.classList.toggle("scrolled", window.scrollY > 8); }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  function closeNav() {
    nav.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
  }
  toggle.addEventListener("click", function () {
    var open = !nav.classList.contains("open");
    nav.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
  });
  nav.addEventListener("click", function (e) { if (e.target.closest("a")) closeNav(); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && nav.classList.contains("open")) { closeNav(); toggle.focus(); }
  });

  // Highlight the nav item for the section in view.
  if ("IntersectionObserver" in window) {
    var links = $$(".nav-list a:not(.btn)");
    var byId = {};
    links.forEach(function (a) { byId[a.getAttribute("href").slice(1)] = a; });
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var link = byId[entry.target.id];
        if (!link) return;
        if (entry.isIntersecting) {
          links.forEach(function (a) { a.removeAttribute("aria-current"); });
          link.setAttribute("aria-current", "true");
        }
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    Object.keys(byId).forEach(function (id) { var s = document.getElementById(id); if (s) spy.observe(s); });
  }

  // Calls to action preselect the enquiry type.
  $$("[data-enquiry]").forEach(function (a) {
    a.addEventListener("click", function () {
      var select = $("#f-type");
      if (select) select.value = a.getAttribute("data-enquiry");
      setTimeout(function () { var f = $("#f-name"); if (f) f.focus({ preventScroll: true }); }, 450);
    });
  });

  var year = $("[data-year]");
  if (year) year.textContent = String(new Date().getFullYear());

  var copyEmail = $("[data-copy-email]");
  var emailAddress = $("#enquiry-address");
  var copyStatus = $("[data-copy-status]");
  if (copyEmail && emailAddress && copyStatus && navigator.clipboard) {
    copyEmail.hidden = false;
    copyEmail.addEventListener("click", async function () {
      try {
        await navigator.clipboard.writeText(emailAddress.textContent.trim());
        copyStatus.textContent = "Email address copied.";
      } catch (error) {
        copyStatus.textContent = "Select and copy the email address above.";
      }
    });
  }


  // ---------- Manual cost estimate ----------
  var estimate = $("[data-estimate]");
  if (estimate) {
    var estimateValue = function (name, low, high) {
      var v = parseFloat($('[data-estimate-input="' + name + '"]', estimate).value);
      return isFinite(v) ? Math.min(high, Math.max(low, v)) : null;
    };
    var updateEstimate = function () {
      var sites = estimateValue("sites", 1, 10000), days = estimateValue("days", 0.5, 365);
      var rate = estimateValue("rate", 100, 20000), cycles = estimateValue("cycles", 1, 52);
      if (sites === null || days === null || rate === null || cycles === null) return;
      var total = sites * days * cycles;
      $("[data-estimate-cost]", estimate).textContent = "$" + Math.round(total * rate).toLocaleString("en-AU");
      $("[data-estimate-days]", estimate).textContent = (Math.round(total * 10) / 10).toLocaleString("en-AU");
    };
    estimate.addEventListener("input", updateEstimate);
  }

  // ---------- Lightbox ----------
  var dialog = $("#lightbox");
  var viewport = $(".lb-viewport", dialog);
  var lbImg = $("img", viewport);
  var lbTitle = $("#lb-title");
  var lbCaption = $(".lb-caption", dialog);
  var group = [];
  var index = 0;
  var opener = null;
  var view = { scale: 1, x: 0, y: 0, fit: 1 };
  var MIN_ZOOM = 0.1, MAX_ZOOM = 6;

  function apply() {
    lbImg.style.transform = "translate(" + view.x + "px," + view.y + "px) scale(" + view.scale + ")";
  }
  function fit() {
    var w = lbImg.naturalWidth, h = lbImg.naturalHeight;
    if (!w || !h) return;
    var vw = viewport.clientWidth - 24, vh = viewport.clientHeight - 24;
    view.fit = Math.min(vw / w, vh / h, 1);
    view.scale = view.fit;
    center();
  }
  function center() {
    var w = lbImg.naturalWidth * view.scale, h = lbImg.naturalHeight * view.scale;
    // The image is positioned at 50%/50%; offsets are relative to that point.
    view.x = -w / 2;
    view.y = -h / 2;
    apply();
  }
  function zoomAt(factor, cx, cy) {
    var rect = viewport.getBoundingClientRect();
    var px = (cx === undefined ? rect.width / 2 : cx - rect.left) - rect.width / 2;
    var py = (cy === undefined ? rect.height / 2 : cy - rect.top) - rect.height / 2;
    var next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.scale * factor));
    var k = next / view.scale;
    view.x = px - (px - view.x) * k;
    view.y = py - (py - view.y) * k;
    view.scale = next;
    apply();
  }

  function show(i) {
    index = (i + group.length) % group.length;
    var el = group[index];
    var img = el.querySelector("img");
    lbTitle.textContent = el.getAttribute("data-title") || "";
    lbCaption.textContent = el.getAttribute("data-caption") || "";
    lbImg.alt = img ? img.alt : "";
    lbImg.style.transform = "";
    lbImg.hidden = false;
    lbImg.onload = fit;
    lbImg.onerror = function () {
      lbImg.hidden = true;
      lbCaption.textContent = "This image could not be loaded. Please try again later.";
    };
    lbImg.src = el.getAttribute("data-full");
    if (lbImg.complete && lbImg.naturalWidth) fit();
    $$(".lb-nav", dialog).forEach(function (b) { b.hidden = group.length < 2; });
  }

  function openLightbox(el) {
    var name = el.getAttribute("data-lightbox");
    group = $$('[data-lightbox="' + name + '"]').filter(function (item) {
      return !item.closest("details:not([open])") && item.getClientRects().length > 0;
    });
    opener = el;
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
    document.body.style.overflow = "hidden";
    show(group.indexOf(el));
    $('[data-lb="close"]', dialog).focus();
  }
  function closeLightbox() {
    if (dialog.open && typeof dialog.close === "function") dialog.close(); else dialog.removeAttribute("open");
  }
  dialog.addEventListener("close", function () {
    document.body.style.overflow = "";
    lbImg.removeAttribute("src");
    if (opener) opener.focus();
  });

  document.addEventListener("click", function (e) {
    var trigger = e.target.closest("[data-lightbox]");
    if (trigger) { e.preventDefault(); openLightbox(trigger); }
  });

  dialog.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-lb]");
    if (!btn) return;
    var act = btn.getAttribute("data-lb");
    if (act === "close") closeLightbox();
    else if (act === "in") zoomAt(1.4);
    else if (act === "out") zoomAt(1 / 1.4);
    else if (act === "fit") fit();
    else if (act === "actual") { view.scale = 1; center(); }
    else if (act === "prev") show(index - 1);
    else if (act === "next") show(index + 1);
  });

  dialog.addEventListener("keydown", function (e) {
    if (e.key === "+" || e.key === "=") { zoomAt(1.25); e.preventDefault(); }
    else if (e.key === "-" || e.key === "_") { zoomAt(0.8); e.preventDefault(); }
    else if (e.key === "0") { fit(); e.preventDefault(); }
    else if (e.key === "ArrowRight" && group.length > 1) { show(index + 1); e.preventDefault(); }
    else if (e.key === "ArrowLeft" && group.length > 1) { show(index - 1); e.preventDefault(); }
  });

  viewport.addEventListener("wheel", function (e) {
    e.preventDefault();
    zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY);
  }, { passive: false });

  // Drag to pan, two-finger pinch to zoom.
  var pointers = {};
  var last = null;
  var pinch = null;
  viewport.addEventListener("pointerdown", function (e) {
    if (e.target.closest("button")) return;
    viewport.setPointerCapture(e.pointerId);
    pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
    viewport.classList.add("dragging");
    last = { x: e.clientX, y: e.clientY };
  });
  viewport.addEventListener("pointermove", function (e) {
    if (!pointers[e.pointerId]) return;
    pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
    var ids = Object.keys(pointers);
    if (ids.length === 2) {
      var a = pointers[ids[0]], b = pointers[ids[1]];
      var d = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinch) zoomAt(d / pinch, (a.x + b.x) / 2, (a.y + b.y) / 2);
      pinch = d;
      return;
    }
    view.x += e.clientX - last.x;
    view.y += e.clientY - last.y;
    last = { x: e.clientX, y: e.clientY };
    apply();
  });
  function endPointer(e) {
    delete pointers[e.pointerId];
    pinch = null;
    var rest = Object.keys(pointers);
    if (rest.length) last = pointers[rest[0]]; else viewport.classList.remove("dragging");
  }
  viewport.addEventListener("pointerup", endPointer);
  viewport.addEventListener("pointercancel", endPointer);
  window.addEventListener("resize", function () { if (dialog.open) fit(); });

  // ---------- Interactive topology demo ----------
  var stage = $("[data-topology]");
  function loadTopology() {
    if (!stage || stage.querySelector("iframe")) return;
    var frame = document.createElement("iframe");
    frame.src = "/demo/topology.html";
    frame.title = "Interactive Sysopty topology map of the synthetic Riverside Technology Group network";
    frame.setAttribute("sandbox", "allow-scripts");
    frame.setAttribute("referrerpolicy", "no-referrer");
    var overlay = $(".topology-overlay", stage);
    if (overlay) overlay.remove();
    stage.appendChild(frame);
    frame.addEventListener("load", function () { var img = stage.querySelector("img"); if (img) img.remove(); });
  }
  $$("[data-load-topology]").forEach(function (b) { b.addEventListener("click", loadTopology); });
  $$("[data-open-demo]").forEach(function (a) {
    a.addEventListener("click", function () { setTimeout(loadTopology, 300); });
  });

  // ---------- Enquiry form ----------
  var form = $("#enquiry-form");
  if (!form) return;
  var status = $(".form-status", form);
  var submit = $('button[type="submit"]', form);
  var tokenInput = form.elements.form_token;
  var EMAIL = /^[^\s@<>()\[\],;:"]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/;

  function fetchToken() {
    return fetch("/api/form-token", { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && d.token) tokenInput.value = d.token; })
      .catch(function () { /* the server reports a missing token on submit */ });
  }
  fetchToken();

  var rules = {
    name: function (v) { return v ? (v.length > 100 ? "Use 100 characters or fewer." : "") : "Enter your name."; },
    company: function (v) { return v ? (v.length > 150 ? "Use 150 characters or fewer." : "") : "Enter your organisation name."; },
    email: function (v) {
      if (!v) return "Enter your business email address.";
      if (v.length > 254 || !EMAIL.test(v)) return "Enter a valid email address, like name@company.com.";
      return "";
    },
    enquiry_type: function (v) {
      return ["assessment", "proposal", "samples", "general"].indexOf(v) >= 0 ? "" : "Choose an enquiry type.";
    },
    sites: function (v) { return v.length > 40 ? "Use 40 characters or fewer." : ""; },
    devices: function (v) { return v.length > 40 ? "Use 40 characters or fewer." : ""; },
    message: function (v) {
      if (!v) return "Enter a message.";
      if (v.length < 10) return "Add a little more detail (at least 10 characters).";
      if (v.length > 5000) return "Keep the message under 5,000 characters.";
      return "";
    }
  };

  function setError(name, msg) {
    var field = form.elements[name];
    var err = document.getElementById(field.getAttribute("aria-describedby"));
    if (msg) field.setAttribute("aria-invalid", "true"); else field.removeAttribute("aria-invalid");
    if (err) err.textContent = msg || "";
  }
  function validate() {
    var first = null;
    Object.keys(rules).forEach(function (name) {
      var msg = rules[name](form.elements[name].value.trim());
      setError(name, msg);
      if (msg && !first) first = form.elements[name];
    });
    return first;
  }
  Object.keys(rules).forEach(function (name) {
    form.elements[name].addEventListener("blur", function () {
      if (this.value.trim() || this.getAttribute("aria-invalid")) setError(name, rules[name](this.value.trim()));
    });
  });

  function say(kind, text) {
    status.className = "form-status " + kind;
    status.textContent = text;
    status.focus();
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    status.textContent = "";
    var invalid = validate();
    if (invalid) { invalid.focus(); return; }

    var payload = {};
    ["name", "company", "email", "enquiry_type", "sites", "devices", "message", "hp_extra", "form_token"].forEach(function (k) {
      payload[k] = (form.elements[k].value || "").trim();
    });
    submit.disabled = true;
    submit.textContent = "Sending…";

    fetch("/api/enquiry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { return { status: r.status, data: d }; });
    }).then(function (res) {
      if (res.status === 200 && res.data.ok) {
        form.reset();
        say("ok", "Thanks — your enquiry has been sent. We'll reply to the email address you gave.");
      } else if (res.status === 422 && res.data.errors) {
        Object.keys(res.data.errors).forEach(function (k) { if (rules[k]) setError(k, res.data.errors[k]); });
        say("err", "Please correct the highlighted fields and try again.");
      } else if (res.status === 503) {
        say("err", "Online enquiries aren't available yet, so your message has not been sent. Please try again later.");
      } else if (res.data && res.data.code === "too_fast") {
        say("err", "Your enquiry has not been sent yet. Please wait a few seconds and press Send again.");
      } else if (res.status === 429) {
        say("err", "Too many enquiries from this connection. Please wait a while and try again.");
      } else {
        say("err", (res.data && res.data.message) || "Your enquiry could not be sent. Please try again.");
      }
    }).catch(function () {
      say("err", "Your enquiry could not be sent because the server could not be reached. Please try again.");
    }).then(function () {
      submit.disabled = false;
      submit.textContent = "Send enquiry";
      fetchToken();
    });
  });
})();
