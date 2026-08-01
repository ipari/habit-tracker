document.querySelectorAll("[data-password-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.getAttribute("aria-controls"));
    if (!(input instanceof HTMLInputElement)) return;
    const willShow = input.type === "password";
    input.type = willShow ? "text" : "password";
    button.setAttribute("aria-pressed", String(willShow));
    button.textContent = willShow ? "숨김" : "표시";
  });
});
