(function () {
  "use strict";

  function getConfig() {
    return window.OFFICE_VERIFICATION || { requireGps: false, requireIp: false };
  }

  function requiresVerification() {
    const cfg = getConfig();
    return Boolean(cfg.requireGps || cfg.requireIp);
  }

  function getCsrfToken(form) {
    const input = form.querySelector('[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  function getMessageEl(form) {
    let el = form.querySelector(".location-msg");
    if (!el) {
      el = document.createElement("div");
      el.className = "location-msg d-none";
      form.appendChild(el);
    }
    return el;
  }

  function showMessage(form, message, isError) {
    const el = getMessageEl(form);
    el.textContent = message;
    el.className = "location-msg alert mt-2 " + (isError ? "alert-danger" : "alert-success");
    el.classList.remove("d-none");
  }

  function hideMessage(form) {
    const el = form.querySelector(".location-msg");
    if (el) {
      el.classList.add("d-none");
    }
  }

  function dismissLocationPopup() {
    const overlay = document.getElementById("locationToastOverlay");
    if (overlay) overlay.remove();
  }

  function showLocationPopup(message, options) {
    const opts = options || {};
    const isError = opts.isError !== false;
    dismissLocationPopup();

    const overlay = document.createElement("div");
    overlay.className = "toast-overlay";
    overlay.id = "locationToastOverlay";

    const popup = document.createElement("div");
    popup.className = "toast-popup " + (isError ? "error" : "success");
    popup.setAttribute("data-toast", "");

    const icon = document.createElement("div");
    icon.className = "toast-popup-icon";
    icon.textContent = isError ? "!" : "✓";

    const title = document.createElement("div");
    title.className = "toast-popup-title";
    title.textContent = opts.title || (isError ? "Access Denied" : "Success");

    const body = document.createElement("div");
    body.className = "toast-popup-body";
    body.textContent = message;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-primary btn-sm btn-dismiss";
    button.textContent = "Got it";
    button.addEventListener("click", dismissLocationPopup);

    popup.appendChild(icon);
    popup.appendChild(title);
    popup.appendChild(body);
    popup.appendChild(button);
    overlay.appendChild(popup);
    document.body.appendChild(overlay);

    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) dismissLocationPopup();
    });

    if (!opts.persist) {
      window.setTimeout(dismissLocationPopup, 8000);
    }
  }

  function getLocation() {
    return new Promise(function (resolve, reject) {
      if (!navigator.geolocation) {
        reject(new Error("Geolocation is not supported by your browser."));
        return;
      }
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          resolve({
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
          });
        },
        function (err) {
          if (err.code === 1) {
            reject(
              new Error(
                "Location permission denied. Please allow location access to continue. Without location, you cannot sign in or mark attendance."
              )
            );
          } else if (err.code === 2) {
            reject(new Error("Unable to determine your location. Please try again."));
          } else {
            reject(new Error("Location request timed out. Please try again."));
          }
        },
        { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }
      );
    });
  }

  function setButtonLoading(button, loading) {
    if (!button) return;
    button.disabled = loading;
    if (loading) {
      button.dataset.originalText = button.innerHTML;
      button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Verifying...';
    } else if (button.dataset.originalText) {
      button.innerHTML = button.dataset.originalText;
    }
  }

  function isOutsideOfficeMessage(message, code) {
    if (code === "outside_office") return true;
    const text = (message || "").toLowerCase();
    return (
      text.includes("not near the company") ||
      text.includes("outside the office") ||
      text.includes("cannot access")
    );
  }

  async function submitWithLocation(form, options) {
    const submitBtn = form.querySelector('[type="submit"]');
    hideMessage(form);
    setButtonLoading(submitBtn, true);

    try {
      const fd = new FormData(form);
      const cfg = getConfig();
      if (cfg.requireGps || options.requireGps) {
        const coords = await getLocation();
        fd.set("latitude", String(coords.latitude));
        fd.set("longitude", String(coords.longitude));
      }

      const response = await fetch(form.action || window.location.href, {
        method: "POST",
        body: fd,
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCsrfToken(form),
        },
        credentials: "same-origin",
      });

      let data = null;
      try {
        data = await response.json();
      } catch (_e) {
        data = null;
      }

      if (!response.ok) {
        const message =
          (data && data.message) ||
          "Your current location is not near the company office, so you cannot access the portal.";
        const code = data && data.code;
        if (options.isLogin || isOutsideOfficeMessage(message, code)) {
          showLocationPopup(message, {
            isError: true,
            title: isOutsideOfficeMessage(message, code) ? "Outside Campus" : "Access Denied",
            persist: true,
          });
        }
        showMessage(form, message, true);
        throw new Error(message);
      }

      if (options.isLogin) {
        if (data && data.redirect) {
          window.location.href = data.redirect;
        } else {
          window.location.reload();
        }
        return;
      }

      showLocationPopup((data && data.message) || "Success!", {
        isError: false,
        title: "Success",
      });
      showMessage(form, (data && data.message) || "Success!", false);
      window.setTimeout(function () {
        window.location.reload();
      }, 800);
    } catch (err) {
      if (!document.getElementById("locationToastOverlay")) {
        showLocationPopup(err.message || "Something went wrong.", {
          isError: true,
          title: "Access Denied",
          persist: true,
        });
        showMessage(form, err.message || "Something went wrong.", true);
      }
      setButtonLoading(submitBtn, false);
    }
  }

  function bindForm(form, options) {
    form.addEventListener(
      "submit",
      function (event) {
        if (!requiresVerification()) {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        submitWithLocation(form, options);
      },
      true
    );
  }

  function initLoginForms() {
    document.querySelectorAll("form.js-office-login").forEach(function (form) {
      const cfg = getConfig();
      bindForm(form, {
        requireGps: cfg.requireGps,
        requireIp: cfg.requireIp,
        isLogin: true,
      });
    });
  }

  function initAttendanceForms() {
    const cfg = getConfig();
    document.querySelectorAll("form.js-attendance-form").forEach(function (form) {
      bindForm(form, {
        requireGps: cfg.requireGps,
        requireIp: cfg.requireIp,
        isLogin: false,
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initLoginForms();
    initAttendanceForms();
  });
})();
