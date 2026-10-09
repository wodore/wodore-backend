/* Wodore basemap compare — dev tool (demos/mapcompare).
 *
 * No build step. Pin notes:
 *  - maplibre-gl@5.6.0 UMD (global maplibregl)
 *  - map-gl-style-switcher@0.10.1 UMD (global mapglstyleswitcher)
 *  - @maplibre/maplibre-gl-compare@0.5.0 + maplibre-gl-inspect@0.0.10 ship
 *    ESM-only bundles -> loaded via dynamic import() through jsDelivr +esm
 *  - FPS: stats.js@0.17.0 driven by requestAnimationFrame (labelled FPS).
 *    mapbox-gl-framerate is not published on npm (documented in the PR).
 */
(function () {
  "use strict";

  var q = new URLSearchParams(location.search);
  var TILE_BASE = (q.get("tileserver") || "http://localhost:3739").replace(
    /\/+$/,
    "",
  );
  var FALLBACK_STYLES = [
    "wd-outdoor-base-mtk",
    "wd-outdoor-base-mtk-hill",
    "wd-outdoor-base-ofm",
    "wd-outdoor-base-ofm-hill",
  ];
  var state = {
    style: q.get("style") || "wd-outdoor-base-mtk",
    styleB: q.get("styleB") || "wd-outdoor-base-ofm",
    zoom: parseFloat(q.get("z") || "12"),
    center: [
      parseFloat(q.get("lon") || "11.4041"),
      parseFloat(q.get("lat") || "47.2692"),
    ],
    mode: q.get("mode") === "compare" ? "compare" : "normal",
    inspect: false,
  };
  var styleIds = FALLBACK_STYLES.slice();

  var els = {
    modeToggle: document.getElementById("mode-toggle"),
    inspectToggle: document.getElementById("inspect-toggle"),
    tileserver: document.getElementById("tileserver"),
    permalink: document.getElementById("permalink"),
    normal: document.getElementById("normal"),
    compare: document.getElementById("compare"),
  };

  var normalMap = null;
  var compareMaps = null; // {a, b, handle}
  var fpsStats = null;
  var fpsRaf = 0;
  var inspectControl = null;
  var InspectCtor = null;

  // ---------- helpers ----------
  function styleUrl(id) {
    return TILE_BASE + "/style/" + id + ".json";
  }

  function switcherStyles() {
    return styleIds.map(function (id) {
      return {
        id: id,
        name: id.replace(/^wd-outdoor-base-/, ""),
        uri: styleUrl(id) + "?v=" + Date.now(),
      };
    });
  }

  function syncPermalink() {
    var p = new URLSearchParams();
    p.set("tileserver", TILE_BASE);
    p.set("style", state.style);
    if (state.mode === "compare") p.set("styleB", state.styleB);
    p.set("z", state.zoom.toFixed(2));
    p.set("lon", state.center[0].toFixed(5));
    p.set("lat", state.center[1].toFixed(5));
    if (state.mode === "compare") p.set("mode", "compare");
    var url = location.pathname + "?" + p.toString();
    history.replaceState(null, "", url);
    els.permalink.textContent = "z" + state.zoom.toFixed(1) + " " + state.style;
  }

  function trackView(map) {
    map.on("moveend", function () {
      state.center = map.getCenter().toArray();
      state.zoom = map.getZoom();
      syncPermalink();
    });
  }

  function makeMap(container, styleId) {
    return new maplibregl.Map({
      container: container,
      style: styleUrl(styleId),
      center: state.center,
      zoom: state.zoom,
      attributionControl: { compact: true },
    });
  }

  function addSwitcher(map, which) {
    var ctrl = new mapglstyleswitcher.StyleSwitcherControl({
      styles: switcherStyles(),
      activeStyleId: which === "B" ? state.styleB : state.style,
      showImages: false, // no preview thumbnails — text labels only
      // the control only fires callbacks — applying the style is on us
      onAfterStyleChange: function (prev, next) {
        if (!next) return;
        map.setStyle(next.uri);
        if (which === "B") state.styleB = next.id;
        else state.style = next.id;
        syncPermalink();
      },
    });
    map.addControl(ctrl, "top-left");
  }

  // ---------- FPS (stats.js, rAF driven, labelled FPS) ----------
  function startFps() {
    if (fpsStats) return;
    fpsStats = new Stats();
    fpsStats.showPanel(0); // 0: fps
    fpsStats.dom.id = "fps-dom";
    var wrap = document.createElement("div");
    wrap.id = "fps-panel";
    wrap.appendChild(fpsStats.dom);
    document.body.appendChild(wrap);
    var tick = function () {
      fpsStats.begin();
      fpsStats.end();
      fpsRaf = requestAnimationFrame(tick);
    };
    fpsRaf = requestAnimationFrame(tick);
  }
  function stopFps() {
    if (!fpsStats) return;
    cancelAnimationFrame(fpsRaf);
    var wrap = document.getElementById("fps-panel");
    if (wrap) wrap.remove();
    fpsStats = null;
  }

  // ---------- inspect (maplibre-gl-inspect, ESM) ----------
  function toggleInspect() {
    state.inspect = !state.inspect;
    els.inspectToggle.textContent =
      "Inspect: " + (state.inspect ? "on" : "off");
    if (state.inspect) enableInspect();
    else disableInspect();
  }

  function enableInspect() {
    if (!InspectCtor) {
      import(
        "https://cdn.jsdelivr.net/npm/maplibre-gl-inspect@0.0.10/+esm"
      ).then(function (m) {
        InspectCtor = m.default || m.MaplibreGlInspect;
        enableInspect();
      });
      return;
    }
    if (normalMap && !inspectControl) {
      inspectControl = new InspectCtor({
        showMapPopupOnHover: true,
        showMapPopupOnClick: false,
        blockHoverPopupOnInspect: true,
      });
      normalMap.addControl(inspectControl, "bottom-right");
    }
  }

  function disableInspect() {
    if (normalMap && inspectControl) {
      try {
        normalMap.removeControl(inspectControl);
      } catch (err) {
        // control may already be gone after style switches
        void err;
      }
      inspectControl = null;
    }
  }

  // ---------- modes ----------
  function enterNormal() {
    teardown();
    els.normal.hidden = false;
    els.compare.hidden = true;
    els.inspectToggle.hidden = false;
    normalMap = makeMap("map", state.style);
    addSwitcher(normalMap, "A");
    trackView(normalMap);
    startFps();
    if (state.inspect) enableInspect();
    els.modeToggle.textContent = "Compare mode";
  }

  function enterCompare() {
    teardown();
    els.normal.hidden = true;
    els.compare.hidden = false;
    els.inspectToggle.hidden = true;
    disableInspect();

    var a = makeMap("compare-a", state.style);
    var b = makeMap("compare-b", state.styleB);
    addSwitcher(a, "A");
    addSwitcher(b, "B");
    trackView(a);
    compareMaps = {
      a: a,
      b: b,
      handle: makeCompareSlider(a, b, "compare-wrap"),
    };
    els.modeToggle.textContent = "Normal mode";
  }

  /* Minimal compare slider (the maplibre-gl-compare CDN bundle exposes no
     usable global/ESM export — documented in the PR). Syncs both cameras
     and clips side B at a draggable vertical divider. */
  function makeCompareSlider(mapA, mapB, wrapId) {
    var wrap = document.getElementById(wrapId);
    var sideB = document.getElementById("compare-b");
    var handle = document.createElement("div");
    handle.id = "compare-handle";
    wrap.appendChild(handle);

    var pos = 0.5;
    var syncA = true;
    function apply() {
      var x = Math.round(pos * wrap.clientWidth);
      sideB.style.clipPath = "inset(0 0 0 " + x + "px)";
      handle.style.left = x + "px";
    }
    function syncCameras(src, dst) {
      dst.jumpTo({
        center: src.getCenter(),
        zoom: src.getZoom(),
        bearing: src.getBearing(),
        pitch: src.getPitch(),
      });
    }
    mapA.on("move", function () {
      if (syncA) syncCameras(mapA, mapB);
    });
    mapB.on("move", function () {
      if (!syncA) syncCameras(mapB, mapA);
    });
    mapA.on("movestart", function () {
      syncA = true;
    });
    mapB.on("movestart", function () {
      syncA = false;
    });

    var dragging = false;
    handle.addEventListener("pointerdown", function (e) {
      dragging = true;
      handle.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    handle.addEventListener("pointermove", function (e) {
      if (!dragging) return;
      var rect = wrap.getBoundingClientRect();
      pos = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      apply();
    });
    handle.addEventListener("pointerup", function () {
      dragging = false;
    });

    mapA.on("resize", apply);
    apply();
    return {
      remove: function () {
        handle.remove();
        sideB.style.clipPath = "";
      },
    };
  }

  function teardown() {
    stopFps();
    inspectControl = null;
    if (compareMaps) {
      if (compareMaps.handle && compareMaps.handle.remove) {
        try {
          compareMaps.handle.remove();
        } catch (err) {
          // best effort
          void err;
        }
      }
      if (compareMaps.a) compareMaps.a.remove();
      if (compareMaps.b) compareMaps.b.remove();
      compareMaps = null;
    }
    if (normalMap) {
      normalMap.remove();
      normalMap = null;
    }
  }

  // ---------- boot ----------
  els.tileserver.textContent = "tileserver: " + TILE_BASE;
  els.modeToggle.addEventListener("click", function () {
    state.mode = state.mode === "compare" ? "normal" : "compare";
    if (state.mode === "compare") {
      enterCompare();
    } else {
      enterNormal();
    }
    syncPermalink();
  });
  els.inspectToggle.addEventListener("click", toggleInspect);

  fetch(TILE_BASE + "/catalog")
    .then(function (r) {
      return r.ok ? r.json() : null;
    })
    .then(function (cat) {
      if (cat && cat.styles && Object.keys(cat.styles).length) {
        var ids = Object.keys(cat.styles).filter(function (id) {
          return id !== "huts";
        });
        // keep the four basemaps first, then any extras (mtk-outdoor, ...)
        ids.sort(function (x, y) {
          var ix = FALLBACK_STYLES.indexOf(x);
          var iy = FALLBACK_STYLES.indexOf(y);
          ix = ix < 0 ? 99 + (x < y ? -1 : x > y ? 1 : 0) : ix;
          iy = iy < 0 ? 99 + (x < y ? -1 : x > y ? 1 : 0) : iy;
          return ix - iy;
        });
        styleIds = ids;
      }
    })
    .catch(function () {
      /* offline catalog: keep fallback list */
    })
    .finally(function () {
      if (state.mode === "compare") {
        enterCompare();
      } else {
        enterNormal();
      }
      syncPermalink();
    });
})();
