// Hover tooltip + crosshair-ish highlight for the long-term trend chart's
// SVG points (see dataviz skill interaction.md: a line chart ships a
// tooltip on hover by default). No dependencies, one chart per page.
(function () {
  function initChart(svg) {
    var tooltip = document.querySelector('.ltc-tooltip[data-for="' + svg.id + '"]');
    if (!tooltip) return;
    var wrap = svg.closest(".chart-wrap") || svg.parentElement;

    function show(pt) {
      var year = pt.getAttribute("data-year");
      var value = parseFloat(pt.getAttribute("data-value"));
      tooltip.textContent = year + ": " + (value > 0 ? "+" : "") + value.toFixed(2);
      tooltip.hidden = false;

      var svgRect = svg.getBoundingClientRect();
      var wrapRect = wrap.getBoundingClientRect();
      var cx = parseFloat(pt.getAttribute("cx"));
      var cy = parseFloat(pt.getAttribute("cy"));
      var vb = svg.viewBox.baseVal;
      var scaleX = svgRect.width / vb.width;
      var scaleY = svgRect.height / vb.height;

      var left = svgRect.left - wrapRect.left + cx * scaleX;
      var top = svgRect.top - wrapRect.top + cy * scaleY;
      tooltip.style.left = left + "px";
      tooltip.style.top = top + "px";
    }

    function hide() {
      tooltip.hidden = true;
    }

    svg.querySelectorAll(".ltc-pt").forEach(function (pt) {
      pt.addEventListener("mouseenter", function () { show(pt); });
      pt.addEventListener("mouseleave", hide);
      pt.addEventListener("focus", function () { show(pt); });
      pt.addEventListener("blur", hide);
    });
  }

  document.querySelectorAll(".long-term-chart").forEach(initChart);
})();
