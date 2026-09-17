// Client-side filter for an index page's entry list -- no backend, no
// dependencies. Expects a `.search-box` input and an `.entry-list` of <li>
// elements whose text is matched case-insensitively.
(function () {
  var box = document.querySelector(".search-box");
  var list = document.querySelector(".entry-list");
  if (!box || !list) return;
  var items = Array.prototype.slice.call(list.querySelectorAll("li"));

  box.addEventListener("input", function () {
    var q = box.value.trim().toLowerCase();
    items.forEach(function (li) {
      li.style.display = li.textContent.toLowerCase().indexOf(q) === -1 ? "none" : "";
    });
  });
})();
