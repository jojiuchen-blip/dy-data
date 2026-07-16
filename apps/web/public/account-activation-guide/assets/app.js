(function () {
  "use strict";

  document.documentElement.classList.add("js-enabled");

  var siteHeader = document.querySelector(".site-header");

  function syncSiteHeaderHeight() {
    document.documentElement.style.setProperty("--site-header-height", siteHeader.offsetHeight + "px");
  }

  if (siteHeader) {
    syncSiteHeaderHeight();

    if ("ResizeObserver" in window) {
      var headerResizeObserver = new ResizeObserver(syncSiteHeaderHeight);
      headerResizeObserver.observe(siteHeader);
    } else {
      window.addEventListener("resize", syncSiteHeaderHeight);
    }
  }

  var address = "https://dy-business-engine.com";
  var copyButton = document.querySelector("[data-copy-address]");
  var copyStatus = document.getElementById("copy-status");

  if (copyButton && copyStatus) {
    copyButton.addEventListener("click", function () {
      if (!navigator.clipboard || !navigator.clipboard.writeText) {
        copyStatus.textContent = "复制功能不可用，请手动选择并复制上方地址。";
        copyStatus.className = "copy-status is-error";
        return;
      }

      navigator.clipboard.writeText(address).then(
        function () {
          copyStatus.textContent = "地址已复制。";
          copyStatus.className = "copy-status is-success";
        },
        function () {
          copyStatus.textContent = "复制失败，请手动选择并复制上方地址。";
          copyStatus.className = "copy-status is-error";
        }
      );
    });
  }

  var tocLinks = Array.prototype.slice.call(document.querySelectorAll("[data-toc-link]"));
  var sections = tocLinks
    .map(function (link) {
      return document.querySelector(link.getAttribute("href"));
    })
    .filter(Boolean);

  if (!("IntersectionObserver" in window) || !tocLinks.length || !sections.length) {
    return;
  }

  function setCurrentSection(sectionId) {
    tocLinks.forEach(function (link) {
      if (link.getAttribute("href") === "#" + sectionId) {
        link.setAttribute("aria-current", "true");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  }

  var visibleSections = new Map();
  function updateCurrentSection() {
    if (Math.ceil(window.scrollY + window.innerHeight) >= document.documentElement.scrollHeight) {
      setCurrentSection(sections[sections.length - 1].id);
      return;
    }

    var current = sections
      .filter(function (section) {
        return visibleSections.has(section.id);
      })
      .sort(function (first, second) {
        var firstState = visibleSections.get(first.id);
        var secondState = visibleSections.get(second.id);

        return secondState.ratio - firstState.ratio || Math.abs(firstState.top) - Math.abs(secondState.top);
      })[0];

    if (current) {
      setCurrentSection(current.id);
    }
  }

  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          visibleSections.set(entry.target.id, {
            ratio: entry.intersectionRatio,
            top: entry.boundingClientRect.top
          });
        } else {
          visibleSections.delete(entry.target.id);
        }
      });

      updateCurrentSection();
    },
    {
      rootMargin: "-10% 0px -10% 0px",
      threshold: [0, 0.1, 0.25, 0.5, 0.75, 1]
    }
  );

  sections.forEach(function (section) {
    observer.observe(section);
  });

  window.addEventListener("scroll", updateCurrentSection, { passive: true });
})();
