const { t, translatePage } = window.JobfindI18n;
translatePage();
const error = new URLSearchParams(window.location.search).get("error");
const message = document.getElementById("login-error");
if (error === "pw") {
  message.hidden = false;
  document.getElementById("password").focus();
} else if (error === "rate") {
  message.textContent = t("Zu viele Versuche. Bitte warte kurz und versuche es erneut.");
  message.hidden = false;
}
