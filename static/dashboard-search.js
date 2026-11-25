/* Cinnamon Dashboard: accessible search and multi-select pickers. */
(function () {
  "use strict";

  function initChoicePickers() {
    document.querySelectorAll("[data-choice-picker]").forEach(function (picker) {
      if (picker.dataset.choiceReady === "true") return;
      picker.dataset.choiceReady = "true";
      var search = picker.querySelector(".choice-search");
      var options = Array.from(picker.querySelectorAll(".choice-option"));
      var selected = picker.querySelector(".choice-selected");
      var count = picker.querySelector(".choice-count");
      var list = picker.querySelector(".choice-options");

      function refresh() {
        var term = (search.value || "").trim().toLocaleLowerCase();
        var checked = options.filter(function (label) {
          return !!label.querySelector("input[type=checkbox]").checked;
        });
        options.forEach(function (label) {
          var input = label.querySelector("input[type=checkbox]");
          var text = (label.dataset.choiceLabel || label.textContent || "").toLocaleLowerCase();
          label.hidden = !!term && !text.includes(term) && !input.checked;
        });
        count.textContent = checked.length + " selected";
        selected.replaceChildren();
        if (!checked.length) {
          selected.textContent = "No selections yet";
          return;
        }
        checked.forEach(function (label) {
          var input = label.querySelector("input[type=checkbox]");
          var chip = document.createElement("button");
          chip.type = "button";
          chip.className = "choice-chip";
          chip.textContent = label.textContent.trim() + " ×";
          chip.setAttribute("aria-label", "Remove " + label.textContent.trim());
          chip.addEventListener("click", function () {
            input.checked = false;
            input.dispatchEvent(new Event("change", { bubbles: true }));
          });
          selected.appendChild(chip);
        });
      }

      search.addEventListener("input", refresh);
      options.forEach(function (label) {
        label.querySelector("input[type=checkbox]").addEventListener("change", refresh);
      });
      if (list) list.addEventListener("keydown", function (event) {
        if (event.key === "Escape") { search.value = ""; refresh(); search.focus(); }
      });
      refresh();
    });
  }

  function initNativeSelectSearch() {
    document.querySelectorAll(".layout select").forEach(function (select) {
      if (select.multiple) return;
      if (select.closest(".searchable-select")) return;
      // Table row controls stay compact: a filter box there would break the action layout.
      if (select.closest("td") || select.closest(".actions")) return;
      // The server switcher is short and already labelled; a filter box adds noise.
      if (select.closest(".serverbox")) return;
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

  function onReady() {
    initChoicePickers();
    initNativeSelectSearch();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", onReady);
  else onReady();
}());
