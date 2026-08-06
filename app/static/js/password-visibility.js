document.querySelectorAll("[data-password-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.getAttribute("aria-controls"));
    if (!(input instanceof HTMLInputElement)) return;
    const willShow = input.type === "password";
    input.type = willShow ? "text" : "password";
    button.setAttribute("aria-pressed", String(willShow));
    const label = willShow ? "비밀번호 숨기기" : "비밀번호 표시";
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
    const showIcon = button.querySelector("[data-password-show]");
    const hideIcon = button.querySelector("[data-password-hide]");
    if (showIcon) showIcon.toggleAttribute("hidden", willShow);
    if (hideIcon) hideIcon.toggleAttribute("hidden", !willShow);
  });
});
