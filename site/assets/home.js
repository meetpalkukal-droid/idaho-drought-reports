// Homepage: pick a boundary type first (three type cards), then browse
// that type's map or list -- groundwater districts, irrigation
// organizations, and water districts overlap heavily on one combined map,
// which made individual boundaries hard to click (user-reported). Search
// stays global across all types, since typing a name has no overlap
// problem. Map is lazily created on the first type pick, then re-filtered
// in place on subsequent picks.
(function () {
  var DATA_URL = "data/map_boundaries.json";
  var LAYER_LABELS = { groundwater_districts: "Groundwater District", irrigation_organizations: "Irrigation Organization", water_districts: "Water District" };
  var LAYER_PATHS = { groundwater_districts: "groundwater_districts", irrigation_organizations: "irrigation_organizations", water_districts: "water_districts" };
  var LAYER_COLORS = { groundwater_districts: "#1d5fa8", irrigation_organizations: "#1baf7a", water_districts: "#c9862a" };

  var activeType = null;
  var map = null;
  var mapLayer = null;
  var allFeatures = [];

  function reportUrl(feature) {
    var p = feature.properties;
    return LAYER_PATHS[p.layer] + "/" + p.slug + ".html";
  }

  // ---- Tabs (Map / List, for whichever type is currently active) --------
  var tabs = document.querySelectorAll(".selector-tab");
  var panels = document.querySelectorAll(".selector-panel");
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      tabs.forEach(function (t) { t.setAttribute("aria-selected", "false"); });
      panels.forEach(function (p) { p.classList.remove("active"); });
      tab.setAttribute("aria-selected", "true");
      document.getElementById(tab.getAttribute("aria-controls")).classList.add("active");
      if (tab.dataset.tab === "map" && map) {
        setTimeout(function () { map.invalidateSize(); }, 50);
      }
    });
  });

  // ---- Type cards ---------------------------------------------------------
  var typeCards = document.querySelectorAll(".type-card");
  typeCards.forEach(function (card) {
    var type = card.dataset.type;
    card.style.setProperty("--type-color", LAYER_COLORS[type] || "#888");
    var swatch = card.querySelector(".type-card-swatch");
    if (swatch) swatch.style.background = LAYER_COLORS[type] || "#888";
    card.addEventListener("click", function () { selectType(type); });
  });

  function selectType(type) {
    activeType = type;
    typeCards.forEach(function (c) {
      c.setAttribute("aria-pressed", c.dataset.type === type ? "true" : "false");
    });
    renderMapForType(type);
    renderListForType(type);
  }

  // ---- Data load, shared by search/map/list ------------------------------
  fetch(DATA_URL)
    .then(function (r) { return r.json(); })
    .then(function (geojson) {
      allFeatures = geojson.features;
      initSearch();
    })
    .catch(function (err) {
      console.error("Failed to load boundary data", err);
    });

  // ---- Search (global, across all types) ---------------------------------
  function initSearch() {
    var box = document.getElementById("home-search");
    var results = document.getElementById("home-search-results");
    if (!box || !results) return;

    var entries = allFeatures.map(function (f) {
      return { name: f.properties.name, layer: f.properties.layer, url: reportUrl(f) };
    }).sort(function (a, b) { return a.name.localeCompare(b.name); });

    function render(q) {
      results.innerHTML = "";
      if (!q) { results.hidden = true; return; }
      var ql = q.toLowerCase();
      var matches = entries.filter(function (e) { return e.name.toLowerCase().indexOf(ql) !== -1; }).slice(0, 25);
      if (!matches.length) {
        results.innerHTML = '<li class="no-match">No matches.</li>';
        results.hidden = false;
        return;
      }
      matches.forEach(function (e) {
        var li = document.createElement("li");
        var a = document.createElement("a");
        a.href = e.url;
        a.textContent = e.name;
        var badge = document.createElement("span");
        badge.className = "type-badge";
        badge.textContent = LAYER_LABELS[e.layer];
        li.appendChild(a);
        li.appendChild(badge);
        results.appendChild(li);
      });
      results.hidden = false;
    }

    box.addEventListener("input", function () { render(box.value.trim()); });
  }

  // ---- List (just the active type, alphabetical) --------------------------
  function renderListForType(type) {
    var container = document.getElementById("home-list");
    var placeholder = document.getElementById("home-list-placeholder");
    if (!container) return;
    placeholder.hidden = true;

    var items = allFeatures
      .filter(function (f) { return f.properties.layer === type; })
      .map(function (f) { return f.properties; })
      .sort(function (a, b) { return a.name.localeCompare(b.name); });

    container.innerHTML = "";
    var section = document.createElement("div");
    section.className = "list-section";
    var h = document.createElement("h3");
    h.textContent = LAYER_LABELS[type] + "s (" + items.length + ")";
    section.appendChild(h);
    var ul = document.createElement("ul");
    ul.className = "entry-list";
    items.forEach(function (p) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = LAYER_PATHS[type] + "/" + p.slug + ".html";
      a.textContent = p.name;
      li.appendChild(a);
      ul.appendChild(li);
    });
    section.appendChild(ul);
    container.appendChild(section);
  }

  // ---- Map (lazy-created on first type pick, re-filtered after that) ------
  function renderMapForType(type) {
    var placeholder = document.getElementById("home-map-placeholder");
    var mapEl = document.getElementById("home-map");
    var hint = document.getElementById("home-map-hint");
    if (!mapEl || typeof L === "undefined") return;

    placeholder.hidden = true;
    mapEl.hidden = false;
    hint.hidden = false;

    var filtered = {
      type: "FeatureCollection",
      features: allFeatures.filter(function (f) { return f.properties.layer === type; }),
    };

    if (!map) {
      map = L.map(mapEl, { scrollWheelZoom: false }).setView([44.0, -114.5], 6);
      window._homeMap = map;
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 18,
      }).addTo(map);
    } else {
      setTimeout(function () { map.invalidateSize(); }, 50);
    }

    if (mapLayer) { map.removeLayer(mapLayer); }

    var color = LAYER_COLORS[type] || "#888";
    mapLayer = L.geoJSON(filtered, {
      style: function () {
        return { color: color, weight: 1.5, fillColor: color, fillOpacity: 0.28 };
      },
      onEachFeature: function (feature, layer) {
        var p = feature.properties;
        layer.bindTooltip(p.name, { sticky: true });
        layer.on({
          mouseover: function () { layer.setStyle({ fillOpacity: 0.55, weight: 2.5 }); },
          mouseout: function () { layer.setStyle({ fillOpacity: 0.28, weight: 1.5 }); },
          click: function () { window.location.href = reportUrl(feature); },
        });
      },
    }).addTo(map);

    try {
      map.fitBounds(mapLayer.getBounds(), { padding: [16, 16] });
    } catch (e) { /* empty geojson, keep default view */ }

    map.on("focus", function () { map.scrollWheelZoom.enable(); });
    map.on("blur", function () { map.scrollWheelZoom.disable(); });
  }
})();
