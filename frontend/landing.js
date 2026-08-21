(function () {
  "use strict";

  const sourceNotes = {
    exodus: "Shabbat is set apart from work and rooted in the memory of creation.",
    deuteronomy: "Shabbat rest includes everyone in the household and recalls liberation from servitude.",
    isaiah: "Sacred time can be approached with intention and delight rather than as ordinary business.",
    shabbat: "Rabbinic tradition praises honoring Shabbat and making it a source of delight.",
  };

  const tabs = Array.from(document.querySelectorAll("[data-source]"));
  const panel = document.getElementById("source-note");

  function selectTab(nextTab) {
    tabs.forEach((tab) => {
      const selected = tab === nextTab;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    if (panel) panel.textContent = sourceNotes[nextTab.dataset.source] || "";
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let nextIndex = index;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = tabs.length - 1;
      selectTab(tabs[nextIndex]);
      tabs[nextIndex].focus();
    });
  });
})();
