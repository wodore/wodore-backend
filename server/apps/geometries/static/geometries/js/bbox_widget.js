/**
 * BBoxWidget: draw a rectangle on an OpenLayers map and store it as
 * "lon_min,lat_min,lon_max,lat_max" (WGS84) in the paired text input.
 *
 * Drawing works two ways:
 * - toggle "Draw rectangle" and drag (single-finger drag on touch —
 *   map panning is suspended while draw mode is on), or
 * - Shift + drag without toggling (desktop shortcut).
 *
 * Typing coordinates draws the rectangle and fits the view. The widget
 * template links this file after the OpenLayers full build (global `ol`).
 */
(function () {
  "use strict";

  function initWidget(el) {
    if (el.dataset.bboxInitialized) return;
    el.dataset.bboxInitialized = "1";
    var input = document.getElementById(el.dataset.bboxInputId);
    var container = el.closest(".bbox-container") || el.parentElement;
    var drawButton = container.querySelector(".bbox-draw-btn");
    var clearButton = container.querySelector(".bbox-clear-btn");
    if (!input || !drawButton) return;

    var vectorSource = new ol.source.Vector();
    var map = new ol.Map({
      target: el,
      layers: [
        new ol.layer.Tile({ source: new ol.source.OSM() }),
        new ol.layer.Vector({
          source: vectorSource,
          style: new ol.style.Style({
            stroke: new ol.style.Stroke({ color: "#2f6fdb", width: 2 }),
            fill: new ol.style.Fill({ color: "rgba(47, 111, 219, 0.15)" }),
          }),
        }),
      ],
      view: new ol.View({
        center: ol.proj.fromLonLat([8.2, 46.8]), // Switzerland
        zoom: 7,
      }),
    });

    // Map panning must yield while draw mode is on (single-finger drag
    // draws on touch); pinch-zoom stays available.
    var dragPan = null;
    map.getInteractions().forEach(function (interaction) {
      if (interaction instanceof ol.interaction.DragPan) dragPan = interaction;
    });

    var drawMode = false;
    var dragBox = new ol.interaction.DragBox({
      condition: function (evt) {
        return drawMode || ol.events.condition.shiftKeyOnly(evt);
      },
    });
    dragBox.setActive(false);
    dragBox.on("boxend", function () {
      setInputFromExtent(dragBox.getGeometry().getExtent());
      drawFromInput();
    });
    map.addInteraction(dragBox);

    function setDrawMode(active) {
      drawMode = active;
      dragBox.setActive(active);
      if (dragPan) dragPan.setActive(!active);
      drawButton.setAttribute("aria-pressed", active ? "true" : "false");
      drawButton.classList.toggle("bbox-active", active);
    }

    drawButton.addEventListener("click", function () {
      setDrawMode(!drawMode);
    });

    function clear() {
      vectorSource.clear();
      input.value = "";
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
    clearButton.addEventListener("click", clear);

    function setInputFromExtent(extent3857) {
      var ext = ol.proj.transformExtent(extent3857, "EPSG:3857", "EPSG:4326");
      input.value = ext
        .map(function (v) {
          return v.toFixed(5);
        })
        .join(",");
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function drawFromInput() {
      var parts = input.value.split(",").map(parseFloat);
      if (
        parts.length !== 4 ||
        parts.some(function (v) {
          return !isFinite(v);
        })
      ) {
        return;
      }
      var extent3857 = ol.proj.transformExtent(parts, "EPSG:4326", "EPSG:3857");
      vectorSource.clear();
      vectorSource.addFeature(
        new ol.Feature(ol.geom.Polygon.fromExtent(extent3857)),
      );
      map.getView().fit(extent3857, { maxZoom: 12, padding: [24, 24, 24, 24] });
    }

    input.addEventListener("change", drawFromInput);
    if (input.value) drawFromInput();
  }

  function initAll() {
    document.querySelectorAll(".bbox-widget").forEach(initWidget);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})();
