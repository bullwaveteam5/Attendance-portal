(function () {
  const sidebar = document.getElementById("appSidebar");
  const toggle = document.getElementById("sidebarToggle");
  const backdrop = document.getElementById("sidebarBackdrop");
  const panelsRoot = document.querySelector(".app-panels");
  const pageTitle = document.querySelector(".app-page-title");
  const pageSubtitle = document.querySelector(".app-page-subtitle");

  const panelMeta = {
    attendance: {
      title: "Mark Attendance",
      subtitle: "Check in and check out for today",
    },
    holidays: {
      title: "Holidays",
      subtitle: "Official company holidays approved by HR and CEO",
    },
    "extra-days": {
      title: "Extra Working Days",
      subtitle: "Approved extra working days for this month",
    },
    leaves: {
      title: "Paid Leave Balance",
      subtitle: "Live leave balance and deductions from the server",
    },
    regularization: {
      title: "Regularization",
      subtitle: "Your regularization requests and status",
    },
    praise: {
      title: "Praise Letters",
      subtitle: "CEO recognition letters",
    },
    history: {
      title: "Quick Attendance History",
      subtitle: "Recent attendance fetched from your records",
    },
    overview: { title: "Overview", subtitle: "" },
    "my-attendance": { title: "Mark Attendance", subtitle: "Your own attendance actions" },
    activity: { title: "Today's Activity", subtitle: "" },
    pending: { title: "Pending Reviews", subtitle: "" },
    overrides: { title: "HR Overrides", subtitle: "" },
  };

  function closeSidebar() {
    document.body.classList.remove("sidebar-open");
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      document.body.classList.toggle("sidebar-open");
    });
  }

  if (backdrop) {
    backdrop.addEventListener("click", closeSidebar);
  }

  function showPanel(target) {
    if (!panelsRoot || !target) return;

    const panel = document.getElementById("panel-" + target);
    if (!panel) return;

    panelsRoot.querySelectorAll(".app-panel").forEach(function (p) {
      p.classList.remove("active");
    });
    panel.classList.add("active");

    document.querySelectorAll(".sidebar-link[data-panel-target]").forEach(function (link) {
      link.classList.toggle("active", link.dataset.panelTarget === target);
    });

    // When a panel is open, clear active state on full-page sidebar links
    document.querySelectorAll(".sidebar-nav > a.sidebar-link").forEach(function (link) {
      if (!link.dataset.panelTarget) {
        link.classList.remove("active");
      }
    });

    const meta = panelMeta[target];
    if (pageTitle && meta) {
      pageTitle.textContent = meta.title;
    }
    if (pageSubtitle && meta && meta.subtitle) {
      pageSubtitle.textContent = meta.subtitle;
    }

    if (window.innerWidth < 992) {
      closeSidebar();
    }

    if (history.replaceState) {
      history.replaceState(null, "", "#" + target);
    }

    // Keep focused content in view on mobile after panel switch
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  document.querySelectorAll("[data-panel-target]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      const target = el.dataset.panelTarget;
      if (!target) return;

      if (el.tagName === "A" && el.getAttribute("href") && !panelsRoot) {
        return;
      }

      if (panelsRoot) {
        e.preventDefault();
        showPanel(target);
      }
    });
  });

  if (panelsRoot) {
    const hash = window.location.hash.replace("#", "");
    const defaultPanel = panelsRoot.dataset.defaultPanel || "attendance";
    showPanel(hash || defaultPanel);

    window.addEventListener("hashchange", function () {
      const h = window.location.hash.replace("#", "");
      if (h) showPanel(h);
    });
  }

  // Close sidebar after navigating to a full page link on mobile
  document.querySelectorAll(".sidebar-nav a.sidebar-link").forEach(function (link) {
    link.addEventListener("click", function () {
      if (window.innerWidth < 992) closeSidebar();
    });
  });
})();
