/* Changelog quick actions — AJAX without page reload.
 *
 * The per-row review buttons (approve/disable/reject) and the download-raw
 * button call their admin views with X-Requested-With; the views answer
 * JSON and the row updates in place: the serving badge flips to local after
 * a download, the review trio highlights the active status. No polling is
 * needed — both operations complete within the single request.
 * */
(function () {
  function statusOf(btn) {
    if (btn.classList.contains("mfu-qa-approved")) return "approved";
    if (btn.classList.contains("mfu-qa-disabled")) return "disabled";
    if (btn.classList.contains("mfu-qa-rejected")) return "rejected";
    return null;
  }

  function setBusy(btn, busy) {
    const icon = btn.querySelector(".material-symbols-outlined");
    if (!icon) return;
    if (busy) {
      btn.dataset.icon = icon.textContent;
      icon.textContent = "progress_activity";
      btn.classList.add("mfu-qa-busy");
    } else {
      icon.textContent = btn.dataset.icon || icon.textContent;
      btn.classList.remove("mfu-qa-busy");
    }
  }

  function flashError(btn) {
    const icon = btn.querySelector(".material-symbols-outlined");
    if (!icon) return;
    const original = btn.dataset.icon || icon.textContent;
    icon.textContent = "error";
    setTimeout(() => {
      icon.textContent = original;
    }, 2000);
  }

  function updateServingCell(row) {
    const cell = row && row.querySelector("td.field-serving");
    if (!cell) return;
    cell.innerHTML =
      '<span class="mfu-badge mfu-badge-local">' +
      '<span class="material-symbols-outlined">cloud_done</span> local</span>';
  }

  function updateReviewPill(row, status) {
    const cell = row && row.querySelector("td.field-review_tag");
    if (!cell) return;
    const label = {
      approved: "success",
      disabled: "warning",
      rejected: "danger",
    }[status];
    cell.innerHTML = `<span class="mfu-pill mfu-pill-${label}">${status}</span>`;
  }

  document.addEventListener("click", async (event) => {
    const btn = event.target.closest("a.mfu-qa");
    if (!btn || btn.classList.contains("mfu-qa-busy")) return;
    event.preventDefault();
    const row = btn.closest("tr");
    const isDownload = btn.classList.contains("mfu-qa-download");
    setBusy(btn, true);
    try {
      const response = await fetch(btn.getAttribute("href"), {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json();
      if (!response.ok || data.status !== "ok") {
        throw new Error(data.message || `HTTP ${response.status}`);
      }
      if (isDownload) {
        btn.remove();
        updateServingCell(row);
      } else {
        const status = statusOf(btn);
        row
          .querySelectorAll(
            ".mfu-qa-approved, .mfu-qa-disabled, .mfu-qa-rejected",
          )
          .forEach((other) => other.classList.remove("mfu-qa-active"));
        btn.classList.add("mfu-qa-active");
        updateReviewPill(row, status);
      }
    } catch (error) {
      flashError(btn);
    } finally {
      setBusy(btn, false);
    }
  });
})();
