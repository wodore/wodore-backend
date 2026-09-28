/* Changelog quick actions — AJAX without page reload.
 *
 * The per-row review buttons (approve/disable/reject) and the download-raw
 * button call their admin views with X-Requested-With; the views answer
 * JSON and the row updates in place: the serving badge flips to local after
 * a download, the review trio highlights the active status. No polling is
 * needed — both operations complete within the single request.
 * */
(function () {
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

  function updateServingCell(row, servingHtml) {
    const cell = row && row.querySelector("td.field-serving");
    if (!cell) return;
    // Prefer the server-rendered snippet — identical markup to a fresh page.
    if (servingHtml) {
      cell.innerHTML = servingHtml;
      return;
    }
    cell.innerHTML =
      '<span class="inline-block font-semibold rounded-default text-[11px] ' +
      "uppercase whitespace-nowrap h-6 leading-6 px-2 " +
      'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400" ' +
      ">local</span>";
  }

  function updateReviewPill(row, reviewHtml) {
    const cell = row && row.querySelector("td.field-review_tag");
    if (!cell) return;
    // Server-rendered snippet: pill + buttons, identical to a reload.
    if (reviewHtml) {
      cell.innerHTML = reviewHtml;
    }
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
        updateServingCell(row, data.serving_html);
      } else {
        updateReviewPill(row, data.review_html);
      }
    } catch (error) {
      flashError(btn);
    } finally {
      setBusy(btn, false);
    }
  });
})();
