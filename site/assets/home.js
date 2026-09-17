// Homepage entity selector: a search box (works everywhere), a Leaflet
// map (click a boundary to open its report), and a list (grouped by
// type) -- three ways to find the same 65 reports, per user request.
(function () {
  var DATA_URL = "data/map_boundaries.json";
  var LAYER_LABELS = { groundwater_districts: "Groundwater District", irrigation_organizations: "Irrigation Organization" };
  var LAYER_PATHS = { groundwater_districts: "groundwater_districts", irrigation_organizations: "irrigation_organizations" };
  var LAYER_COLORS = { groundwater_districts: "#1d5fa8", irrigation_organizations: "#1baf7a" };

  function reportUrl(feature) {
    var p = feature.properties;
    return LAYER_PATHS[p.layer] + "/" + p.slug + ".html";
  }

  // ---- Tabs -----------------------------------------------------------
  var tabs = document.querySelectorAll(".selector-tab");
  var panels = document.querySelectorAll(".selector-panel");
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      tabs.forEach(function (t) { t.setAttribute("aria-selected", "false"); });
      panels.forEach(function (p) { p.classList.remove("active"); });
      tab.setAttribute("aria-selected", "true");
      document.getElementById(tab.getAttribute("aria-controls")).classList.add("active");
      if (tab.dataset.tab === "map" && window._homeMap) {
        setTimeout(function () { window._homeMap.invalidateSize(); }, 50);
      }
    });
  });

  // ---- Data load, shared by search/map/list ----------------------------
  fetch(DATA_URL)
    .then(function (r) { return r.json(); })
    .then(function (geojson) {
      initSearch(geojson);
      initList(geojson);
      initMap(geojson);
    })
    .catch(function (err) {
      console.error("Failed to load boundary data", err);
    });

  // ---- Search -----------------------------------------------------------
  function initSearch(geojson) {
    var box = document.getElementById("home-search");
    var results = document.getElementById("home-search-results");
    if (!box || !results) return;

    var entries = geojson.features.map(function (f) {
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

  // ---- List (grouped, filterable) ---------------------------------------
  function initList(geojson) {
    var container = document.getElementById("home-list");
    if (!container) return;

    var byLayer = {};
    geojson.features.forEach(function (f) {
      var p = f.properties;
      (byLayer[p.layer] = byLayer[p.layer] || []).push(p);
    });

    Object.keys(byLayer).forEach(function (layer) {
      byLayer[layer].sort(function (a, b) { return a.name.localeCompare(b.name); });
      var section = document.createElement("div");
      section.className = "list-section";
      var h = document.createElement("h3");
      h.textContent = LAYER_LABELS[layer] + "s (" + byLayer[layer].length + ")";
      section.appendChild(h);
      var ul = document.createElement("ul");
      ul.className = "entry-list";
      byLayer[layer].forEach(function (p) {
        var li = document.createElement("li");
        var a = document.createElement("a");
        a.href = LAYER_PATHS[layer] + "/" + p.slug + ".html";
        a.textContent = p.name;
        li.appendChild(a);
        ul.appendChild(li);
      });
      section.appendChild(ul);
      container.appendChild(section);
    });
  }

  // ---- Map ---------------------------------------------------------------
  function initMap(geojson) {
    var el = document.getElementById("home-map");
    if (!el || typeof L === "undefined") return;

    var map = L.map(el, { scrollWheelZoom: false }).setView([44.0, -114.5], 6);
    window._homeMap = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 18,
    }).addTo(map);

    var layerGroup = L.geoJSON(geojson, {
      style: function (feature) {
        var color = LAYER_COLORS[feature.properties.layer] || "#888";
        return { color: color, weight: 1.5, fillColor: color, fillOpacity: 0.25 };
      },
      onEachFeature: function (feature, layer) {
        var p = feature.properties;
        layer.bindTooltip(p.name, { sticky: true });
        layer.on({
          mouseover: function () { layer.setStyle({ fillOpacity: 0.5, weight: 2.5 }); },
          mouseout: function () { layer.setStyle({ fillOpacity: 0.25, weight: 1.5 }); },
          click: function () { window.location.href = reportUrl(feature); },
        });
      },
    }).addTo(map);

    try {
      map.fitBounds(layerGroup.getBounds(), { padding: [16, 16] });
    } catch (e) { /* empty geojson, keep default view */ }

    map.on("focus", function () { map.scrollWheelZoom.enable(); });
    map.on("blur", function () { map.scrollWheelZoom.disable(); });
  }
})();
