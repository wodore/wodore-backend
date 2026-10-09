/**
 * Bundled by jsDelivr using Rollup v4.62.2 and esbuild v0.28.1.
 * Original file: /npm/maplibre-gl-inspect@0.0.10/dist/index.js
 *
 * Do NOT use SRI with dynamically generated files! More information: https://www.jsdelivr.com/using-sri-with-dynamic-files
 */
import * as a from "/npm/maplibre-gl@6.3.0/+esm";
import b from "/npm/randomcolor@0.6.2/+esm";
const h = (t, e, o) => {
    const s = {
      id: [e, o, "circle"].join("_"),
      source: e,
      type: "circle",
      paint: { "circle-color": t, "circle-radius": 2 },
      filter: ["==", "$type", "Point"],
    };
    return o && (s["source-layer"] = o), s;
  },
  u = (t, e, o, s) => {
    const n = {
      id: [o, s, "polygon"].join("_"),
      source: o,
      type: "fill",
      paint: { "fill-antialias": !0, "fill-color": t, "fill-outline-color": e },
      filter: ["==", "$type", "Polygon"],
    };
    return s && (n["source-layer"] = s), n;
  },
  m = (t, e, o) => {
    const s = {
      id: [e, o, "line"].join("_"),
      source: e,
      layout: { "line-join": "round", "line-cap": "round" },
      type: "line",
      paint: { "line-color": t },
      filter: ["==", "$type", "LineString"],
    };
    return o && (s["source-layer"] = o), s;
  },
  k = (t, e) => {
    const o = [],
      s = [],
      n = [],
      c = (i) => {
        const p = e.bind(null, i);
        return {
          circle: p(0.8),
          line: p(0.6),
          polygon: p(0.3),
          polygonOutline: p(0.6),
          default: p(1),
        };
      };
    return (
      Object.keys(t).forEach((i) => {
        const p = t[`${i}`];
        if (!p || p.length === 0) {
          const r = c(i);
          s.push(h(r.circle, i)),
            n.push(m(r.line, i)),
            o.push(u(r.polygon, r.polygonOutline, i));
        } else
          p.forEach((r) => {
            const l = c(r);
            s.push(h(l.circle, i, r)),
              n.push(m(l.line, i, r)),
              o.push(u(l.polygon, l.polygonOutline, i, r));
          });
      }),
      [...o, ...n, ...s]
    );
  },
  v = (t, e, o = {}) => {
    const s = {
        id: "background",
        type: "background",
        paint: { "background-color": o.backgroundColor ?? "#fff" },
      },
      n = {};
    return (
      Object.keys(t.sources).forEach((c) => {
        const i = t.sources[`${c}`];
        i && (i.type === "vector" || i.type === "geojson") && (n[`${c}`] = i);
      }),
      { ...t, layers: [s, ...e], sources: n }
    );
  };
var C = class {
  _btn;
  elem;
  constructor(t = {}) {
    const { show: e = !0, onToggle: o = () => {} } = t;
    (this._btn = this.button()),
      (this._btn.onclick = o),
      (this.elem = this.container(this._btn, e));
  }
  container(t, e) {
    const o = document.createElement("div");
    return (
      (o.className = "maplibregl-ctrl maplibregl-ctrl-group"),
      o.appendChild(t),
      e || (o.style.display = "none"),
      o
    );
  }
  button() {
    const t = document.createElement("button");
    return (
      (t.className = "maplibregl-ctrl-icon maplibregl-ctrl-inspect"),
      (t.type = "button"),
      (t.ariaLabel = "Inspect"),
      t
    );
  }
  setInspectIcon() {
    this._btn.className = "maplibregl-ctrl-icon maplibregl-ctrl-inspect";
  }
  setMapIcon() {
    this._btn.className = "maplibregl-ctrl-icon maplibregl-ctrl-map";
  }
};
const S = (t) =>
    typeof t > "u" || t === null
      ? t
      : t instanceof Date
      ? t.toLocaleString()
      : typeof t == "object"
      ? JSON.stringify(t)
      : t.toString(),
  d = (t, e) =>
    `<div class="maplibregl-inspect-property"><div class="maplibregl-inspect-property-name">${t}</div><div class="maplibregl-inspect-property-value">${S(
      e,
    )}</div></div>`,
  M = (t) => `<div class="maplibregl-inspect-layer">${t}</div>`,
  w = (t) => {
    const e = M(t.layer["source-layer"] || t.layer.source),
      o = d("$type", t.geometry.type),
      s = Object.keys(t.properties).map((n) => d(n, t.properties[`${n}`]));
    return [e, o].concat(s).join("");
  },
  T = (t) =>
    t
      .map((e) => `<div class="maplibregl-inspect-feature">${w(e)}</div>`)
      .join(""),
  O = (t) => `<div class="maplibregl-inspect-popup">${T(t)}</div>`,
  P = (t, e) => {
    let o = "bright",
      s;
    return (
      /water|ocean|lake|sea|river/.test(t) && (s = "blue"),
      /state|country|place/.test(t) && (s = "pink"),
      /road|highway|transport|streets/.test(t) && (s = "orange"),
      /contour|building/.test(t) && (s = "monochrome"),
      /building/.test(t) && (o = "dark"),
      /contour|landuse/.test(t) && (s = "yellow"),
      /wood|forest|park|landcover|land/.test(t) && (s = "green"),
      `rgba(${`${b({ luminosity: o, hue: s, seed: t, format: "rgbArray" })},${
        e || 1
      }`})`
    );
  },
  y = {
    popupText: "#333333",
    popupBg: "#ffffff",
    popupBorder: "#e5e7eb",
    buttonIcon: "#333333",
    ctrlBg: "#ffffff",
    inspectBackground: "#ffffff",
  },
  g = {
    popupText: "#e5e7eb",
    popupBg: "#1f2937",
    popupBorder: "#4b5563",
    buttonIcon: "#e5e7eb",
    ctrlBg: "#374151",
    inspectBackground: "#1f2937",
  },
  I = (t) => !!(t.metadata && "maplibregl-inspect:inspect" in t.metadata),
  L = (t) => ({
    ...t,
    metadata: Object.assign({}, t.metadata, {
      "maplibregl-inspect:inspect": !0,
    }),
  });
var f = class _ {
    _map;
    _popup;
    _popupBlocked = !1;
    _showInspectMap;
    _originalStyle;
    _toggle;
    options;
    sources;
    assignLayerColor;
    _currentTheme;
    _mediaQuery;
    _lightColors;
    _darkColors;
    constructor(e) {
      if (!(this instanceof _))
        throw new Error(
          "MaplibreInspect needs to be called with the new keyword",
        );
      let o = null;
      a
        ? (o = new a.Popup({ closeButton: !1, closeOnClick: !1 }))
        : e?.popup ||
          console.error(
            "Maplibre GL JS can not be found. Make sure to include it or pass an initialized MaplibreGL Popup to MaplibreInspect if you are using moduleis.",
          );
      const s = {
        showInspectMap: !1,
        showInspectButton: !0,
        showInspectMapPopup: !0,
        showMapPopup: !1,
        showMapPopupOnHover: !0,
        showInspectMapPopupOnHover: !1,
        blockHoverPopupOnClick: !1,
        backgroundColor: "#fff",
        assignLayerColor: P,
        buildInspectStyle: v,
        renderPopup: O,
        popup: o,
        selectThreshold: 5,
        useInspectStyle: !0,
        queryParameters: {},
        sources: {},
        toggleCallback() {},
      };
      (this.options = Object.assign(s, e)),
        (this.sources = this.options.sources),
        (this.assignLayerColor = this.options.assignLayerColor),
        (this._popup = this.options.popup),
        (this._popupBlocked = !1),
        (this._showInspectMap = this.options.showInspectMap),
        (this._currentTheme = this.options.theme ?? "system"),
        (this._lightColors = { ...y, ...this.options.lightColors }),
        (this._darkColors = { ...g, ...this.options.darkColors }),
        this._currentTheme === "system" &&
        typeof window < "u" &&
        window.matchMedia
          ? ((this._mediaQuery = window.matchMedia(
              "(prefers-color-scheme: dark)",
            )),
            this._mediaQuery.addEventListener(
              "change",
              this._onSystemThemeChange,
            ))
          : (this._mediaQuery = null),
        this._applyTheme(),
        (this._originalStyle = null),
        (this._toggle = new C({
          show: this.options.showInspectButton,
          onToggle: this.toggleInspector,
        }));
    }
    _inspectStyle() {
      let e = this._map?.getStyle();
      if (this._map) {
        const o = k(this.sources, this.assignLayerColor);
        e = this.options.buildInspectStyle(this._map.getStyle(), o, {
          backgroundColor: this.options.backgroundColor,
        });
      }
      return e;
    }
    _onSourceChange = (e) => {
      const o = this.sources;
      if (this._map) {
        const s = this._map,
          n = s.getStyle(),
          c = Object.keys(n.sources),
          i = Object.assign({}, o);
        if (e.isSourceLoaded) {
          const { tileManagers: p } = s.style;
          for (const r of Object.keys(p)) {
            const l = p[r]?.getSource();
            l?.vectorLayerIds
              ? (o[r] = l.vectorLayerIds)
              : l?.type === "geojson" && (o[r] = []);
          }
          Object.keys(o).forEach((r) => {
            c.indexOf(r) === -1 && delete o[`${r}`];
          }),
            JSON.stringify(i) !== JSON.stringify(o) &&
              Object.keys(o).length > 0 &&
              this.render();
        }
      }
    };
    _onStyleChange = () => {
      const e = this._map?.getStyle();
      e && !I(e) && (this._originalStyle = e);
    };
    _onRightClick = () => {
      !this.options.showMapPopupOnHover &&
        !this.options.showInspectMapPopupOnHover &&
        !this.options.blockHoverPopupOnClick &&
        this._popup &&
        this._popup.remove();
    };
    _onMouseMove = (e) => {
      if (this._showInspectMap) {
        if (
          !this.options.showInspectMapPopup ||
          (e.type === "mousemove" && !this.options.showInspectMapPopupOnHover)
        )
          return;
        e.type === "click" &&
          this.options.showInspectMapPopupOnHover &&
          this.options.blockHoverPopupOnClick &&
          (this._popupBlocked = !this._popupBlocked);
      } else {
        if (
          !this.options.showMapPopup ||
          (e.type === "mousemove" && !this.options.showMapPopupOnHover)
        )
          return;
        e.type === "click" &&
          this.options.showMapPopupOnHover &&
          this.options.blockHoverPopupOnClick &&
          (this._popupBlocked = !this._popupBlocked);
      }
      if (!this._popupBlocked && this._map) {
        let o;
        this.options.selectThreshold === 0
          ? (o = e.point)
          : (o = [
              [
                e.point.x - this.options.selectThreshold,
                e.point.y + this.options.selectThreshold,
              ],
              [
                e.point.x + this.options.selectThreshold,
                e.point.y - this.options.selectThreshold,
              ],
            ]);
        const s =
          this._map.queryRenderedFeatures(o, this.options.queryParameters) ||
          [];
        if (
          ((this._map.getCanvas().style.cursor = s.length ? "pointer" : ""),
          s.length > 0 && this._popup instanceof a.Popup)
        ) {
          this._popup.setLngLat(e.lngLat);
          const n = this.options.renderPopup(s);
          typeof n == "string"
            ? this._popup.setHTML(n)
            : this._popup.setDOMContent(n),
            this._popup.addTo(this._map);
        } else this._popup?.remove();
      }
    };
    toggleInspector = () => {
      (this._showInspectMap = !this._showInspectMap),
        this.options.toggleCallback(this._showInspectMap),
        this.render();
    };
    get theme() {
      return this._currentTheme;
    }
    setTheme(e) {
      const o = this._currentTheme;
      (this._currentTheme = e),
        o === "system" && e !== "system" && this._mediaQuery
          ? this._mediaQuery.removeEventListener(
              "change",
              this._onSystemThemeChange,
            )
          : o !== "system" &&
            e === "system" &&
            this._mediaQuery &&
            this._mediaQuery.addEventListener(
              "change",
              this._onSystemThemeChange,
            ),
        this._applyTheme();
    }
    _onSystemThemeChange = () => {
      this._currentTheme === "system" && this._applyTheme();
    };
    _getResolvedTheme() {
      return this._currentTheme === "system"
        ? this._mediaQuery && this._mediaQuery.matches
          ? "dark"
          : "light"
        : this._currentTheme;
    }
    _applyTheme() {
      const e = this._getResolvedTheme(),
        o = e === "dark" ? this._darkColors : this._lightColors;
      document.documentElement.style.setProperty(
        "--inspect-popup-text",
        o.popupText,
      ),
        document.documentElement.style.setProperty(
          "--inspect-popup-bg",
          o.popupBg,
        ),
        document.documentElement.style.setProperty(
          "--inspect-popup-border",
          o.popupBorder,
        ),
        document.documentElement.style.setProperty(
          "--inspect-button-icon",
          o.buttonIcon,
        ),
        document.documentElement.style.setProperty(
          "--inspect-ctrl-bg",
          o.ctrlBg,
        ),
        document.documentElement.style.setProperty(
          "--inspect-background",
          o.inspectBackground,
        ),
        this._currentTheme === "system"
          ? document.documentElement.removeAttribute("data-inspect-theme")
          : document.documentElement.setAttribute("data-inspect-theme", e);
    }
    render() {
      if (this._showInspectMap) {
        if (this.options.useInspectStyle) {
          const e = this._inspectStyle();
          this._map?.setStyle(L(e));
        }
        this._toggle.setMapIcon();
      }
      !this._showInspectMap &&
        this._originalStyle &&
        (this.options.useInspectStyle &&
          this._map?.setStyle(this._originalStyle),
        this._popup && this._popup.remove(),
        this._toggle.setInspectIcon());
    }
    onAdd(e) {
      return (
        (this._map = e),
        Object.keys(this.sources).length === 0 &&
          e.on("sourcedata", this._onSourceChange),
        e.on("styledata", this._onStyleChange),
        e.on("load", this._onStyleChange),
        e.on("mousemove", this._onMouseMove),
        e.on("click", this._onMouseMove),
        e.on("contextmenu", this._onRightClick),
        this._toggle.elem
      );
    }
    onRemove() {
      this._map?.off("styledata", this._onStyleChange),
        this._map?.off("load", this._onStyleChange),
        this._map?.off("sourcedata", this._onSourceChange),
        this._map?.off("mousemove", this._onMouseMove),
        this._map?.off("click", this._onMouseMove),
        this._map?.off("contextmenu", this._onRightClick),
        this._mediaQuery &&
          this._mediaQuery.removeEventListener(
            "change",
            this._onSystemThemeChange,
          ),
        document.documentElement.removeAttribute("data-inspect-theme");
      const e = this._toggle.elem;
      e.parentNode?.removeChild(e), (this._map = void 0);
    }
  },
  B = f;
export {
  g as DEFAULT_DARK_COLORS,
  y as DEFAULT_LIGHT_COLORS,
  f as MaplibreInspect,
  B as default,
};
//# sourceMappingURL=/sm/5873fdeb5f0eb14a3eda5c819e28cedb5fca7fd72d8368cfb7129547dc2c3d24.map
