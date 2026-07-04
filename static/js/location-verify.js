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
            reject(new Error("Location permission denied. Please allow location access to continue."));
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

      const response = await fetch(form.action || form.getAttribute("action"), {
        method: "POST",
        body: fd,
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });

      let data = null;
      try {
        data = await response.json();
      } catch (_e) {
        data = null;
      }

      if (!response.ok) {
        throw new Error((data && data.message) || "Request failed. Please try again.");
      }

      if (options.isLogin) {
        if (data && data.redirect) {
          window.location.href = data.redirect;
        } else {
          window.location.reload();
        }
        return;
      }

      showMessage(form, (data && data.message) || "Success!", false);
      window.setTimeout(function () {
        window.location.reload();
      }, 800);
    } catch (err) {
      showMessage(form, err.message || "Something went wrong.", true);
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
