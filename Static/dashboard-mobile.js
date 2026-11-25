(function () {
  "use strict";

  function initMobileNavigation() {
    const side = document.getElementById("liveSidebar");
    const backdrop = document.getElementById("liveNavBackdrop");
    const openButton = document.getElementById("liveMenuBtn");
    const closeButton = document.getElementById("liveMenuClose");
    if (!side || !backdrop || !openButton) return;

    let lastFocused = null;

    function closeMenu() {
      side.classList.remove("mobile-open");
      backdrop.classList.remove("visible");
      document.body.classList.remove("nav-open");
      openButton.setAttribute("aria-expanded", "false");
      if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
      lastFocused = null;
    }
    function openMenu() {
      lastFocused = document.activeElement;
      side.classList.add("mobile-open");
      backdrop.classList.add("visible");
      document.body.classList.add("nav-open");
      openButton.setAttribute("aria-expanded", "true");
      if (closeButton) closeButton.focus();
    }

    openButton.addEventListener("click", function () {
      side.classList.contains("mobile-open") ? closeMenu() : openMenu();
    });
    backdrop.addEventListener("click", closeMenu);
    if (closeButton) closeButton.addEventListener("click", closeMenu);
    side.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", closeMenu);
    });

    const search = document.getElementById("dashboardNavSearch");
    const nav = document.getElementById("dashboardNav");
    if (search && nav) {
      search.addEventListener("input", function () {
        const query = search.value.trim().toLocaleLowerCase();
        nav.querySelectorAll("a").forEach(function (link) {
          link.hidden = !!query && !link.textContent.toLocaleLowerCase().includes(query);
        });
        nav.querySelectorAll(".navgroup").forEach(function (group) {
          const links = Array.from(group.querySelectorAll("a"));
          group.hidden = !!query && links.length > 0 && links.every(function (link) { return link.hidden; });
        });
      });
    }

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeMenu();
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 760) closeMenu();
    });
  }

  function initSubmitFeedback() {
    document.querySelectorAll("main form").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        // Inline handlers are blocked by the dashboard CSP, so confirmations use data-confirm.
        const question = form.getAttribute("data-confirm");
        if (question && !window.confirm(question)) {
          event.preventDefault();
          return;
        }
        form.querySelectorAll("button[type=submit], button:not([type])").forEach(function (button) {
          if (button.disabled) return;
          button.disabled = true;
          button.textContent = "Working…";
        });
      });
    });
  }

  function onReady() {
    initMobileNavigation();
    initSubmitFeedback();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", onReady, { once: true });
  } else {
    onReady();
  }
})();
