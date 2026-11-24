const { t, translatePage } = window.JobfindI18n;
translatePage();
const error = new URLSearchParams(window.location.search).get("error");
const message = document.getElementById("login-error");
const passwordLogin = document.getElementById("password-login");
if (passwordLogin) {
  const supported = window.isSecureContext && !!window.PublicKeyCredential && !!navigator.credentials;
  passwordLogin.open = !supported || error === "pw" || error === "rate";
  document.getElementById("login-divider").hidden = !supported;
  passwordLogin.addEventListener("toggle", () => {
    if (passwordLogin.open) document.getElementById("password").focus({ preventScroll: true });
  });
}
const passwordToggle = document.getElementById("password-toggle");
passwordToggle?.addEventListener("click", () => {
  const input = document.getElementById("password");
  const visible = input.type === "text";
  input.type = visible ? "password" : "text";
  passwordToggle.setAttribute("aria-pressed", String(!visible));
  passwordToggle.setAttribute("aria-label", t(visible ? "Passwort anzeigen" : "Passwort verbergen"));
  input.focus({ preventScroll: true });
});
const next = new URLSearchParams(window.location.search).get("next");
const nextInput = document.getElementById("login-next");
if (nextInput && next && /^\/(?:gemerkte|bewerbungen)?(?:\?[^\r\n]*)?$/.test(next) && !/[\\\x00-\x1f]/.test(next)) nextInput.value = next;
if (error === "pw") {
  message.hidden = false;
  document.getElementById("password").focus();
} else if (error === "rate") {
  message.textContent = t("Zu viele Versuche. Bitte warte kurz und versuche es erneut.");
  message.hidden = false;
  document.getElementById("password").focus();
}
