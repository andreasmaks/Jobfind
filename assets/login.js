const error = new URLSearchParams(window.location.search).get("error");
const message = document.getElementById("login-error");
if (error === "pw") {
  message.hidden = false;
  document.getElementById("password").focus();
} else if (error === "rate") {
  message.textContent = "Zu viele Versuche. Bitte warte kurz und versuche es erneut.";
  message.hidden = false;
}
