!(function (e, t) {
  "object" == typeof exports && "undefined" != typeof module
    ? t(exports)
    : "function" == typeof define && define.amd
    ? define(["exports"], t)
    : t(
        ((e =
          "undefined" != typeof globalThis
            ? globalThis
            : e || self).mapglstyleswitcher = {}),
      );
})(this, function (e) {
  "use strict";
  e.StyleSwitcherControl = class {
    constructor(e) {
      Object.defineProperty(this, "_container", {
        enumerable: !0,
        configurable: !0,
        writable: !0,
        value: null,
      }),
        Object.defineProperty(this, "_options", {
          enumerable: !0,
          configurable: !0,
          writable: !0,
          value: void 0,
        }),
        Object.defineProperty(this, "_activeStyleId", {
          enumerable: !0,
          configurable: !0,
          writable: !0,
          value: void 0,
        }),
        Object.defineProperty(this, "_expanded", {
          enumerable: !0,
          configurable: !0,
          writable: !0,
          value: !1,
        }),
        Object.defineProperty(this, "_classNames", {
          enumerable: !0,
          configurable: !0,
          writable: !0,
          value: void 0,
        }),
        Object.defineProperty(this, "_mediaQuery", {
          enumerable: !0,
          configurable: !0,
          writable: !0,
          value: null,
        }),
        Object.defineProperty(this, "_mediaQueryHandler", {
          enumerable: !0,
          configurable: !0,
          writable: !0,
          value: null,
        }),
        Object.defineProperty(this, "_focusedIndex", {
          enumerable: !0,
          configurable: !0,
          writable: !0,
          value: -1,
        }),
        Object.defineProperty(this, "_suppressFocusExpand", {
          enumerable: !0,
          configurable: !0,
          writable: !0,
          value: !1,
        });
      const t = !1 !== e.showLabels,
        s = !1 !== e.showImages;
      if (!t && !s)
        throw new Error(
          "At least one of showLabels or showImages must be true.",
        );
      const i =
        void 0 !== e.activeStyleId &&
        e.styles.some((t) => t.id === e.activeStyleId);
      void 0 === e.activeStyleId ||
        i ||
        console.warn(
          `StyleSwitcherControl: activeStyleId "${e.activeStyleId}" does not match any style. Using first style instead.`,
        ),
        (this._options = {
          showLabels: t,
          showImages: s,
          animationDuration: 200,
          maxHeight: 300,
          theme: "light",
          design: "default",
          ...e,
        }),
        (this._activeStyleId = i ? e.activeStyleId : e.styles[0]?.id),
        (this._classNames = {
          container:
            "maplibregl-ctrl maplibregl-ctrl-group mapboxgl-ctrl mapboxgl-ctrl-group style-switcher",
          list: "style-switcher-list",
          item: "style-switcher-item",
          itemSelected: "selected",
          itemHideLabel: "hide-label",
          dark: "style-switcher-dark",
          light: "style-switcher-light",
          outlined: "style-switcher-outlined",
          ...e.classNames,
        });
    }
    onAdd(e) {
      return (
        (this._container = document.createElement("div")),
        (this._container.className = this._classNames.container),
        (this._container.tabIndex = 0),
        this._container.setAttribute("role", "listbox"),
        this._container.setAttribute("aria-label", "Style switcher"),
        this._container.setAttribute("aria-expanded", "false"),
        this._options.rtl && this._container.setAttribute("dir", "rtl"),
        this._applyTheme(),
        "auto" === this._options.theme &&
          window.matchMedia &&
          ((this._mediaQuery = window.matchMedia(
            "(prefers-color-scheme: dark)",
          )),
          (this._mediaQueryHandler = () => this._applyTheme()),
          this._mediaQuery.addEventListener("change", this._mediaQueryHandler)),
        this._container.addEventListener("mouseenter", () =>
          this._setExpanded(!0),
        ),
        this._container.addEventListener("mouseleave", () =>
          this._setExpanded(!1),
        ),
        this._container.addEventListener("focus", () => {
          this._suppressFocusExpand
            ? (this._suppressFocusExpand = !1)
            : this._setExpanded(!0);
        }),
        this._container.addEventListener("blur", () => this._setExpanded(!1)),
        this._container.addEventListener("keydown", (e) =>
          this._handleKeyDown(e),
        ),
        this._render(),
        this._container
      );
    }
    _applyTheme() {
      if (this._container) {
        if (
          (this._container.classList.remove(
            this._classNames.dark,
            this._classNames.light,
          ),
          "dark" === this._options.theme)
        )
          this._container.classList.add(this._classNames.dark);
        else if ("light" === this._options.theme)
          this._container.classList.add(this._classNames.light);
        else if ("auto" === this._options.theme) {
          const e =
            window.matchMedia &&
            window.matchMedia("(prefers-color-scheme: dark)").matches;
          this._container.classList.add(
            e ? this._classNames.dark : this._classNames.light,
          );
        }
        this._applyDesign();
      }
    }
    _applyDesign() {
      this._container &&
        (this._container.classList.remove(this._classNames.outlined),
        "outlined" === this._options.design &&
          this._container.classList.add(this._classNames.outlined));
    }
    updateOptions(e) {
      "classNames" in e &&
        (this._classNames = { ...this._classNames, ...e.classNames }),
        Object.assign(this._options, e),
        this._resolveActiveStyleIdAfterUpdate(e),
        this._container &&
          ("rtl" in e &&
            (this._options.rtl
              ? this._container.setAttribute("dir", "rtl")
              : this._container.removeAttribute("dir")),
          this._render());
    }
    _resolveActiveStyleIdAfterUpdate(e) {
      const t = "styles" in e,
        s =
          "activeStyleId" in e && void 0 !== e.activeStyleId
            ? e.activeStyleId
            : void 0;
      if (void 0 !== s)
        return this._options.styles.some((e) => e.id === s)
          ? void (this._activeStyleId = s)
          : t
          ? (console.warn(
              `StyleSwitcherControl: activeStyleId "${s}" does not match any style. Using first style instead.`,
            ),
            void (this._activeStyleId = this._options.styles[0]?.id))
          : void console.warn(
              `StyleSwitcherControl: activeStyleId "${s}" does not match any style. Keeping previous selection.`,
            );
      !t ||
        (void 0 !== this._activeStyleId &&
          this._options.styles.some((e) => e.id === this._activeStyleId)) ||
        (this._activeStyleId = this._options.styles[0]?.id);
    }
    onRemove() {
      this._mediaQuery &&
        this._mediaQueryHandler &&
        (this._mediaQuery.removeEventListener(
          "change",
          this._mediaQueryHandler,
        ),
        (this._mediaQuery = null),
        (this._mediaQueryHandler = null)),
        this._container &&
          this._container.parentNode &&
          this._container.parentNode.removeChild(this._container),
        (this._container = null);
    }
    _setExpanded(e) {
      this._expanded !== e &&
        ((this._expanded = e),
        this._container?.setAttribute("aria-expanded", e.toString()),
        e || (this._focusedIndex = -1),
        this._render(),
        this._applyTheme());
    }
    _handleKeyDown(e) {
      if (!this._expanded)
        return void (
          ("Enter" !== e.key && " " !== e.key) ||
          (e.preventDefault(),
          this._setExpanded(!0),
          (this._focusedIndex = 0),
          this._updateFocus())
        );
      const t = this._options.styles;
      if (t.length)
        switch (e.key) {
          case "ArrowDown":
            e.preventDefault(),
              (this._focusedIndex = Math.min(
                this._focusedIndex + 1,
                t.length - 1,
              )),
              this._updateFocus();
            break;
          case "ArrowUp":
            e.preventDefault(),
              (this._focusedIndex = Math.max(this._focusedIndex - 1, 0)),
              this._updateFocus();
            break;
          case "Enter":
          case " ":
            e.preventDefault(),
              this._focusedIndex >= 0 &&
                this._focusedIndex < t.length &&
                this._handleStyleChange(t[this._focusedIndex]);
            break;
          case "Escape":
            e.preventDefault(),
              (this._suppressFocusExpand = !0),
              this._setExpanded(!1),
              this._container?.focus();
        }
    }
    _updateFocus() {
      if (!this._container) return;
      const e = this._container.querySelector("." + this._classNames.list);
      if (!e) return;
      e.querySelectorAll('[role="option"]').forEach((e, t) => {
        t === this._focusedIndex && e.focus();
      });
    }
    _handleStyleChange(e) {
      if (e.id === this._activeStyleId) return;
      const t = this._options.styles.find((e) => e.id === this._activeStyleId);
      t &&
        (this._options.onBeforeStyleChange?.(t, e),
        (this._activeStyleId = e.id),
        this._render(),
        this._options.onAfterStyleChange?.(t, e));
    }
    _render() {
      if (!this._container) return;
      (this._container.innerHTML = ""), this._applyTheme();
      const e =
        this._options.styles.find((e) => e.id === this._activeStyleId) ||
        this._options.styles[0];
      if (!e) return;
      if (this._expanded) {
        const e = document.createElement("div");
        (e.className = this._classNames.list),
          (e.style.display = "flex"),
          (e.style.maxHeight = this._options.maxHeight + "px"),
          (e.style.animationDuration = this._options.animationDuration + "ms");
        for (const t of this._options.styles) {
          const s = this._createStyleItem(t, t.id === this._activeStyleId);
          (s.onclick = () => this._handleStyleChange(t)), e.appendChild(s);
        }
        this._container.appendChild(e);
      }
      const t = this._createStyleItem(e, !0);
      this._container.appendChild(t);
    }
    _createStyleItem(e, t) {
      const s = document.createElement("div");
      let i = this._classNames.item;
      if (
        (t && (i += " " + this._classNames.itemSelected),
        !1 === this._options.showLabels &&
          (i += " " + this._classNames.itemHideLabel),
        (s.className = i),
        s.setAttribute("role", "option"),
        s.setAttribute("aria-selected", t.toString()),
        s.setAttribute("title", e.description || e.name),
        (s.tabIndex = 0),
        !1 !== this._options.showImages)
      ) {
        const t = document.createElement("img");
        (t.src = e.image),
          (t.alt = e.name),
          (t.loading = "lazy"),
          s.appendChild(t);
      }
      if (!1 !== this._options.showLabels) {
        const t = document.createElement("span");
        (t.textContent = e.name), s.appendChild(t);
      }
      return s;
    }
  };
});
//# sourceMappingURL=index.umd.js.map
