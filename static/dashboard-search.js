/* Cinnamon Dashboard: progressive name search for big native dropdowns.
   No network calls, no IDs typed by users, and native selects work without JS. */
(function () {
  "use strict";
  function onReady() {
    document.querySelectorAll(".layout select").forEach(function (select) {
      if (select.options.length < 9 || select.multiple) return;
      if (select.closest(".searchable-select")) return;
      var box = document.createElement("div");
      box.className = "searchable-select";
      var input = document.createElement("input");
      input.type = "search";
      input.placeholder = "Search by name…";
      input.autocomplete = "off";
      var label = select.getAttribute("aria-label") ||
        (select.closest(".field") && select.closest(".field").querySelector("label") || {}).textContent ||
        select.name || "option";
      input.setAttribute("aria-label", "Filter " + label.trim() + " choices");
      box.appendChild(input);
      select.parentNode.insertBefore(box, select);
      box.appendChild(select);
      var opts = Array.from(select.options);
      input.addEventListener("input", function () {
        var term = input.value.trim().toLocaleLowerCase();
        opts.forEach(function (opt) {
          var display = !term || opt.selected || opt.value === "" ||
            opt.textContent.toLocaleLowerCase().includes(term);
          opt.hidden = !display;
          opt.disabled = !display;
        });
      });
      select.addEventListener("change", function () {
        if (input.value) input.dispatchEvent(new Event("input"));
      });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", onReady);
  else onReady();
}());
