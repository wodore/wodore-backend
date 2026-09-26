// server/apps/meta_image_field/static/meta_image_field/js/meta_image_widget.js
(function () {
  class FileWidget {
    constructor(elem) {
      this.selectedPoint = 0;
      // x1/y1 -----+
      //   |        |
      //   +------x2/y2
      this.focalArea = undefined; // { x1, y1, x2, y2}
      this.cropArea = { x1: 0, y1: 0, x2: 1, y2: 1 };
      this.getDOM(elem);
      let opt = {
        shade: true,
        shadeOpacity: 0.3,
        cropperClass: "",
        canRemove: true,
        multiMin: 1,
      };
      this.stage = Jcrop.attach(this.imageFrame, opt);
      this.getFocusPointInputValue();
      this.addEventListeners();
    }

    getDOM(elem) {
      this.rootEl = elem;
      this.fileInput = elem.querySelector('input[type="file"]');
      this.urlInput = elem.querySelector("#url_upload");
      this.downloadRawBtn = elem.querySelector(".mfu-download-raw");
      //this.metaInput = document.querySelector('.imagefocus-input[data-image-field="' + this.fileInput.name + '"]')
      // TODO this does not work with different meta field name
      this.metaInput = document.querySelector("#id_image_meta");
      this.imageFrame = elem.querySelector(".imagefocus-file-upload__image");
      this.removeAreaBtn = elem.querySelector(".imagefocus-file-remove-area");
      this.previewImage = this.imageFrame.querySelector("img");
      this.inputName = this.fileInput.name;
    }

    ensurePreviewImage() {
      // Pinned external images render their raw URL; a brand-new form has no
      // image at all — create the element on demand so URL input and focal
      // selection always have something to work with.
      if (!this.previewImage) {
        this.previewImage = document.createElement("img");
        this.previewImage.id = "image-preview";
        this.imageFrame.appendChild(this.previewImage);
      }
      return this.previewImage;
    }

    getFocusPointInputValue() {
      const metaValue = JSON.parse(this.metaInput.value || "{}");
      if (!metaValue || metaValue.focal === undefined) {
        return;
      }
      const { x1, y1, x2, y2 } = metaValue.focal;
      console.log("Update with initial data", x1, y1, x2, y2);
      if (!(isNaN(x1) || isNaN(y1) || isNaN(x2) || isNaN(y2))) {
        const img_x1 = x1 * this.imageFrame.clientWidth;
        const img_x2 = x2 * this.imageFrame.clientWidth;
        const img_y1 = y1 * this.imageFrame.clientHeight;
        const img_y2 = y2 * this.imageFrame.clientHeight;
        const rect = Jcrop.Rect.fromPoints([img_x1, img_y1], [img_x2, img_y2]);
        this.stage.newWidget(rect);
      }
    }

    addEventListeners() {
      this.removeAreaBtn.addEventListener("click", () =>
        this.handleRemoveArea(),
      );
      this.fileInput.addEventListener("change", (evnt) =>
        this.handleFileChange(evnt),
      );
      this.urlInput.addEventListener("input", (evnt) =>
        this.handleUrlChange(evnt),
      );
      if (this.downloadRawBtn) {
        this.downloadRawBtn.addEventListener("click", () => {
          // "Download raw": localize a pinned external image — fills the URL
          // input with the source URL and reuses the regular upload-from-URL
          // flow (live preview + server-side download on save).
          this.urlInput.value = this.downloadRawBtn.dataset.rawUrl;
          this.urlInput.dispatchEvent(new Event("input"));
        });
      }
      this.stage.listen("crop.change", (widget, evnt) =>
        this.handleFocusAreaClick(widget, evnt),
      );
    }

    handleFocusAreaClick(widget, evnt) {
      const pos = widget.pos.normalize();
      console.log(pos.x, pos.y, pos.w, pos.h);
      const x1 = Number((pos.x / this.imageFrame.clientWidth).toFixed(2));
      const y1 = Number((pos.y / this.imageFrame.clientHeight).toFixed(2));
      const x2 = Number((pos.x2 / this.imageFrame.clientWidth).toFixed(2));
      const y2 = Number((pos.y2 / this.imageFrame.clientHeight).toFixed(2));
      console.log("Selected points:", x1, y1, x2, y2);
      this.setFocalArea(x1, y1, x2, y2);
    }

    handleRemoveArea(evnt) {
      this.stage.active.emit("crop.remove");
      this.stage.active.el.remove();
      this.stage.crops.delete(this.stage.active);
      this.stage.activate();
      this.focalArea = undefined;
      this.updateMetadata();
    }

    setFocalArea(x1, y1, x2, y2) {
      this.focalArea = { x1, y1, x2, y2 };
      this.updateMetadata();
    }

    updateMetadata() {
      const metaValue = JSON.stringify({
        focal: this.focalArea,
        crop: this.cropArea,
        width: this.previewImage ? this.previewImage.naturalWidth : undefined,
        height: this.previewImage ? this.previewImage.naturalHeight : undefined,
      });
      this.metaInput.value = metaValue;
      this.metaInput.dispatchEvent(new Event("change"));
    }

    handleFileChange(evnt) {
      const file = this.fileInput.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (evnt) => {
        this.ensurePreviewImage().src = evnt.target.result;
        this.handleRemoveArea();
        this.updateMetadata();
      };
      reader.readAsDataURL(file);
    }

    handleUrlChange(evnt) {
      this.ensurePreviewImage().src = evnt.target.value;
      this.updateMetadata();
      this.handleRemoveArea();
    }
  }

  const meta_image_field = (function () {
    let fileWidgets = [];

    const init = () => {
      const fileinputs = document.querySelectorAll(".imagefocus-file-upload");
      fileinputs.forEach((fileinput) => {
        const fileWidget = new FileWidget(fileinput);
        fileWidgets.push(fileWidget);
      });
    };
    return {
      init,
    };
  })();

  const djangoPollingInterval = setInterval(() => {
    if (window.django && window.django.jQuery) {
      clearInterval(djangoPollingInterval);
      window.django.jQuery(() => meta_image_field.init());
    }
  }, 100);
})();
