document.addEventListener("keydown", (event) => {
  const target = event.target.closest("[data-calendar-day]");
  if (!target) return;
  const days = Array.from(document.querySelectorAll("[data-calendar-day]"));
  const currentIndex = days.indexOf(target);
  const offsets = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
  const offset = offsets[event.key];
  if (offset === undefined) return;
  const next = days[currentIndex + offset];
  if (!next) return;
  event.preventDefault();
  next.focus();
});
