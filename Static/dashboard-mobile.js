(function () {
  "use strict";
  function initMobileNavigation() {
    const side = document.getElementById("liveSidebar");
    const backdrop = document.getElementById("liveNavBackdrop");
    const openButton = document.getElementById("liveMenuBtn");
    const closeButton = document.getElementById("liveMenuClose");
    if (!side || !backdrop || !openButton) return;

    function closeMenu() {
      side.classList.remove("mobile-open");
      backdrop.classList.remove("visible");
      document.body.classList.remove("nav-open");
      openButton.setAttribute("aria-expanded", "false");
    }
    function openMenu() {
      side.classList.add("mobile-open");
      backdrop.classList.add("visible");
      document.body.classList.add("nav-open");
      openButton.setAttribute("aria-expanded", "true");
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
      });
    }
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeMenu();
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 650) closeMenu();
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initMobileNavigation, { once: true });
  } else {
    initMobileNavigation();
  }
})();
