(function initializeDyDataGalleryBridge(global) {
  "use strict";

  const cards = () => Array.from(document.querySelectorAll(".card"));
  let resizeFrame = 0;

  function reportHeight() {
    if (global.self === global.top) return;
    global.cancelAnimationFrame(resizeFrame);
    resizeFrame = global.requestAnimationFrame(() => {
      global.parent.postMessage({
        type: "dydata-chart-gallery-height",
        height: Math.ceil(document.documentElement.scrollHeight),
      }, "*");
    });
  }

  function applyFilter(query) {
    const normalized = String(query || "").trim().toLowerCase();
    let visible = 0;
    cards().forEach((card) => {
      const match = !normalized || card.innerText.toLowerCase().includes(normalized);
      card.hidden = !match;
      if (match) visible += 1;
    });
    global.parent?.postMessage({
      type: "dydata-chart-filter-result",
      total: cards().length,
      visible,
    }, "*");
    reportHeight();
  }

  global.addEventListener("message", (event) => {
    if (event.data?.type === "dydata-chart-filter") {
      applyFilter(event.data.query);
    }
  });

  global.addEventListener("DOMContentLoaded", () => {
    applyFilter("");
    new ResizeObserver(reportHeight).observe(document.body);
  });
  global.addEventListener("load", reportHeight);
})(window);
