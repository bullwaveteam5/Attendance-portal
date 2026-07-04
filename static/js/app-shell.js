(function () {
  const sidebar = document.getElementById("appSidebar");
  const toggle = document.getElementById("sidebarToggle");
  const backdrop = document.getElementById("sidebarBackdrop");
  const panelsRoot = document.querySelector(".app-panels");
  const pageTitle = document.querySelector(".app-page-title");

  const panelTitles = {
    attendance: "Mark Attendance",
    holidays: "Holidays",
    "extra-days": "Extra Working Days",
    leaves: "Paid Leave",
    regularization: "Regularization",
    praise: "Praise Letters",
    history: "Attendance History",
    overview: "Overview",
    "my-attendance": "Mark Attendance",
    activity: "Today's Activity",
    pending: "Pending Reviews",
    overrides: "HR Overrides",
  };

  function closeSidebar() {
    document.body.classList.remove("sidebar-open");
  }

  function openSidebar() {
    document.body.classList.add("sidebar-open");
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

    panelsRoot.querySelectorAll(".app-panel").forEach(function (panel) {
      panel.classList.remove("active");
    });

    const panel = document.getElementById("panel-" + target);
    if (panel) {
      panel.classList.add("active");
    }

    document.querySelectorAll(".sidebar-link[data-panel-target]").forEach(function (link) {
      link.classList.toggle("active", link.dataset.panelTarget === target);
    });

    if (pageTitle && panelTitles[target]) {
      pageTitle.textContent = panelTitles[target];
    }

    if (window.innerWidth < 992) {
      closeSidebar();
    }

    if (history.replaceState) {
      history.replaceState(null, "", "#" + target);
    }
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
})();
