document.body.addEventListener("htmx:beforeSwap", (event) => {
  const response = event.detail.xhr;
  if (response.status >= 400 && response.getResponseHeader("HX-Retarget")) {
    event.detail.shouldSwap = true;
    event.detail.isError = true;
  }
});

const offlineStatus = document.querySelector("#offline-status");

function updateConnectionStatus() {
  const isOffline = !navigator.onLine;
  document.documentElement.classList.toggle("is-offline", isOffline);
  if (offlineStatus) {
    offlineStatus.hidden = !isOffline;
  }
}

function blockOfflineMutation(event, method) {
  if (navigator.onLine || method.toUpperCase() === "GET") {
    return;
  }
  event.preventDefault();
  updateConnectionStatus();
  offlineStatus?.focus();
}

window.addEventListener("online", updateConnectionStatus);
window.addEventListener("offline", updateConnectionStatus);
updateConnectionStatus();

const appAlertDialog = document.querySelector("#app-alert-dialog");
const appAlertTitle = document.querySelector("#app-alert-title");
const appAlertMessage = document.querySelector("#app-alert-message");
const appAlertCancel = document.querySelector("[data-app-alert-cancel]");
const appAlertConfirm = document.querySelector("[data-app-alert-confirm]");
let resolveAppAlert = null;

function closeAppAlert(result) {
  if (!appAlertDialog?.open) {
    return;
  }
  appAlertDialog.close();
  document.documentElement.classList.remove("app-modal-open");
  const resolve = resolveAppAlert;
  resolveAppAlert = null;
  resolve?.(result);
}

function openAppAlert(message, options = {}) {
  if (!appAlertDialog || !appAlertTitle || !appAlertMessage || !appAlertConfirm || !appAlertCancel) {
    return Promise.resolve(false);
  }
  if (appAlertDialog.open) {
    closeAppAlert(false);
  }

  const isConfirm = options.variant === "confirm";
  appAlertTitle.textContent = options.title || (isConfirm ? "확인" : "알림");
  appAlertMessage.textContent = message;
  appAlertConfirm.textContent = options.confirmLabel || "확인";
  appAlertCancel.textContent = options.cancelLabel || "취소";
  appAlertCancel.hidden = !isConfirm;
  appAlertConfirm.classList.toggle("danger", options.tone === "danger");
  document.documentElement.classList.add("app-modal-open");
  appAlertDialog.showModal();
  (isConfirm ? appAlertCancel : appAlertConfirm).focus();

  return new Promise((resolve) => {
    resolveAppAlert = resolve;
  });
}

window.appAlert = (message, options = {}) => openAppAlert(message, options);
window.appConfirm = (message, options = {}) =>
  openAppAlert(message, { ...options, variant: "confirm" });

appAlertConfirm?.addEventListener("click", () => closeAppAlert(true));
appAlertCancel?.addEventListener("click", () => closeAppAlert(false));
appAlertDialog?.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeAppAlert(false);
});
appAlertDialog?.addEventListener("click", (event) => {
  if (event.target === appAlertDialog) {
    closeAppAlert(false);
  }
});

const emojiInput = document.querySelector("[data-single-grapheme]");

function firstGrapheme(value) {
  if (typeof Intl.Segmenter === "function") {
    return new Intl.Segmenter(undefined, { granularity: "grapheme" })
      .segment(value)[Symbol.iterator]().next().value?.segment || "";
  }
  return Array.from(value)[0] || "";
}

emojiInput?.addEventListener("input", () => {
  emojiInput.value = firstGrapheme(emojiInput.value);
});

const timeEnabledInput = document.querySelector("#time-enabled");
const timeSettings = document.querySelector("[data-time-settings]");
const reminderTimeInput = document.querySelector("#reminder-time");
const reminderEnabledInput = document.querySelector("#reminder-enabled");

function currentTimeRoundedDown(intervalMinutes = 10) {
  const now = new Date();
  const hours = String(now.getHours()).padStart(2, "0");
  const minutes = String(
    Math.floor(now.getMinutes() / intervalMinutes) * intervalMinutes,
  ).padStart(2, "0");
  return `${hours}:${minutes}`;
}

if (reminderTimeInput?.hasAttribute("data-default-current-time")) {
  reminderTimeInput.value = currentTimeRoundedDown();
}

function syncTimeSettings(fromUser = false) {
  if (!timeEnabledInput || !timeSettings) {
    return;
  }
  const isEnabled = timeEnabledInput.checked;
  timeSettings.disabled = !isEnabled;
  timeSettings.classList.toggle("is-disabled", !isEnabled);
  timeSettings.setAttribute("aria-disabled", String(!isEnabled));
  timeEnabledInput.setAttribute("aria-expanded", String(isEnabled));

  if (!reminderEnabledInput) {
    return;
  }
  if (!isEnabled) {
    reminderEnabledInput.checked = false;
  } else if (fromUser && !reminderEnabledInput.hasAttribute("data-reminder-locked")) {
    reminderEnabledInput.checked = true;
  }
}

timeEnabledInput?.addEventListener("change", () => syncTimeSettings(true));
syncTimeSettings();

reminderTimeInput?.addEventListener("input", () => {
  if (
    timeEnabledInput?.checked &&
    reminderTimeInput.value &&
    reminderEnabledInput &&
    !reminderEnabledInput.disabled
  ) {
    reminderEnabledInput.checked = true;
  }
});

document.querySelectorAll("[data-copy-value]").forEach((button) => {
  button.addEventListener("click", async () => {
    const value = button.dataset.copyValue;
    if (!value || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(value);
      button.textContent = "복사됨";
    } catch {
      button.textContent = "복사 실패";
    }
  });
});

document.querySelectorAll("[data-reset-link-form]").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!navigator.onLine) {
      updateConnectionStatus();
      offlineStatus?.focus();
      return;
    }
    if (!navigator.clipboard?.writeText) {
      await window.appAlert("이 브라우저에서는 클립보드 복사를 사용할 수 없습니다.");
      return;
    }

    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.reset_url) {
        throw new Error(payload.error || "재설정 링크를 만들지 못했습니다.");
      }
      await navigator.clipboard.writeText(payload.reset_url);
      await window.appAlert("비밀번호 재설정 링크를 복사했습니다.");
    } catch (error) {
      await window.appAlert(error.message || "재설정 링크를 복사하지 못했습니다.");
    } finally {
      if (button) button.disabled = false;
    }
  });
});

const passwordDialog = document.querySelector("#password-dialog");
const passwordDialogOpen = document.querySelector("[data-password-dialog-open]");
const passwordDialogCloseButtons = document.querySelectorAll("[data-password-dialog-close]");
const passwordChangeForm = document.querySelector("[data-password-change-form]");
const passwordChangeError = document.querySelector("[data-password-error]");

function closePasswordDialog() {
  if (!passwordDialog?.open) return;
  passwordDialog.close();
  document.documentElement.classList.remove("app-modal-open");
  passwordChangeForm?.reset();
  if (passwordChangeError) {
    passwordChangeError.hidden = true;
    passwordChangeError.textContent = "";
  }
  passwordDialogOpen?.focus();
}

passwordDialogOpen?.addEventListener("click", () => {
  if (!passwordDialog) return;
  document.documentElement.classList.add("app-modal-open");
  passwordDialog.showModal();
  passwordDialog.querySelector("#current-password")?.focus();
});

passwordDialogCloseButtons.forEach((button) => {
  button.addEventListener("click", closePasswordDialog);
});

passwordDialog?.addEventListener("cancel", (event) => {
  event.preventDefault();
  closePasswordDialog();
});

passwordDialog?.addEventListener("click", (event) => {
  if (event.target === passwordDialog) closePasswordDialog();
});

passwordChangeForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!navigator.onLine) {
    updateConnectionStatus();
    offlineStatus?.focus();
    return;
  }

  const submitButton = passwordChangeForm.querySelector('button[type="submit"]');
  if (passwordChangeError) {
    passwordChangeError.hidden = true;
    passwordChangeError.textContent = "";
  }
  if (submitButton) submitButton.disabled = true;

  try {
    const response = await fetch(passwordChangeForm.action, {
      method: "POST",
      body: new FormData(passwordChangeForm),
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.redirect_url) {
      throw new Error(payload.error || "비밀번호를 변경하지 못했습니다.");
    }
    window.location.assign(payload.redirect_url);
  } catch (error) {
    if (passwordChangeError) {
      passwordChangeError.textContent = error.message || "비밀번호를 변경하지 못했습니다.";
      passwordChangeError.hidden = false;
      passwordChangeError.focus();
    }
  } finally {
    if (submitButton) submitButton.disabled = false;
  }
});

const deviceTimezoneForm = document.querySelector("[data-device-timezone-form]");
const deviceTimezoneInput = document.querySelector("[data-device-timezone-input]");

function detectedDeviceTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

function syncDeviceTimezone() {
  if (!deviceTimezoneForm || !deviceTimezoneInput) {
    return;
  }
  const detectedTimezone = detectedDeviceTimezone();
  if (!detectedTimezone) {
    return;
  }
  deviceTimezoneInput.value = detectedTimezone;
  if (detectedTimezone === deviceTimezoneForm.dataset.savedTimezone) {
    return;
  }
  deviceTimezoneForm.requestSubmit();
}

syncDeviceTimezone();

document.body.addEventListener("htmx:beforeRequest", (event) => {
  blockOfflineMutation(event, event.detail.requestConfig.verb);
});

const confirmedForms = new WeakSet();

document.addEventListener(
  "submit",
  async (event) => {
    const form = event.target;
    blockOfflineMutation(event, form.method || "GET");
    if (event.defaultPrevented) {
      return;
    }
    if (confirmedForms.delete(form)) {
      return;
    }
    const message = form.dataset.confirm;
    if (!message) {
      return;
    }

    event.preventDefault();
    const approved = await window.appConfirm(message, {
      title: form.dataset.confirmTitle,
      confirmLabel: form.dataset.confirmLabel,
      cancelLabel: form.dataset.cancelLabel,
      tone: form.dataset.confirmTone,
    });
    if (approved) {
      confirmedForms.add(form);
      if (event.submitter) {
        form.requestSubmit(event.submitter);
      } else {
        form.requestSubmit();
      }
    }
  },
  true,
);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" });
  });
}

const notificationPrompt = document.querySelector("#notification-permission-prompt");
const notificationMessage = document.querySelector("#notification-permission-message");
const notificationAllow = document.querySelector("[data-notification-allow]");
const notificationLater = document.querySelector("[data-notification-later]");
const notificationOpen = document.querySelector("[data-notification-open]");
const notificationDisconnect = document.querySelector("[data-notification-disconnect]");
const notificationPermissionStatus = document.querySelector("#notification-permission-status");
const NOTIFICATION_PROMPT_KEY = "habit-tracker.notification-prompted-v1";
const DEFAULT_NOTIFICATION_MESSAGE = "설정한 시간에 습관을 잊지 않도록 알려드릴게요.";

function isInstalledApp() {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true
  );
}

function notificationsAreSupported() {
  return (
    "Notification" in window &&
    "serviceWorker" in navigator &&
    "PushManager" in window
  );
}

function notificationPromptWasHandled() {
  try {
    return window.localStorage.getItem(NOTIFICATION_PROMPT_KEY) === "true";
  } catch {
    return false;
  }
}

function rememberNotificationPrompt() {
  try {
    window.localStorage.setItem(NOTIFICATION_PROMPT_KEY, "true");
  } catch {
    // The permission flow still works when private browsing blocks storage.
  }
}

function closeNotificationPrompt() {
  if (notificationPrompt) {
    notificationPrompt.hidden = true;
  }
}

function prepareNotificationPrompt(message = DEFAULT_NOTIFICATION_MESSAGE, action = "알림 허용") {
  if (!notificationPrompt || !notificationMessage || !notificationAllow || !notificationLater) {
    return;
  }
  notificationMessage.textContent = message;
  notificationAllow.textContent = action;
  notificationAllow.hidden = false;
  notificationAllow.disabled = false;
  notificationLater.textContent = "나중에";
  notificationPrompt.hidden = false;
  notificationAllow.focus();
}

function base64urlToUint8Array(value) {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const decoded = window.atob((value + padding).replaceAll("-", "+").replaceAll("_", "/"));
  return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
}

function arrayBufferToBase64url(value) {
  if (!value) {
    return "";
  }
  const bytes = new Uint8Array(value);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return window.btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function loadPushConfig() {
  const response = await window.fetch("/api/push/config", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error("알림 서버 설정을 확인하지 못했습니다.");
  }
  return response.json();
}

async function connectPushSubscription(config) {
  if (!config.configured || !config.publicKey) {
    throw new Error("서버의 Web Push 키가 아직 설정되지 않았습니다.");
  }
  const registration = await navigator.serviceWorker.ready;
  let subscription = await registration.pushManager.getSubscription();
  if (
    subscription &&
    arrayBufferToBase64url(subscription.options.applicationServerKey) !== config.publicKey
  ) {
    await subscription.unsubscribe();
    subscription = null;
  }
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: base64urlToUint8Array(config.publicKey),
    });
  }
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const response = await window.fetch("/api/push/subscriptions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify(subscription.toJSON()),
  });
  if (!response.ok) {
    throw new Error("기기 알림 정보를 서버에 저장하지 못했습니다.");
  }
}

async function matchingPushSubscription(config) {
  if (!config.configured || !config.publicKey) {
    return null;
  }
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  if (
    subscription &&
    arrayBufferToBase64url(subscription.options.applicationServerKey) === config.publicKey
  ) {
    return subscription;
  }
  return null;
}

async function disconnectPushSubscription() {
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  if (!subscription) {
    return;
  }
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const response = await window.fetch("/api/push/subscriptions", {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify({ endpoint: subscription.endpoint }),
  });
  if (!response.ok) {
    throw new Error("기기 알림 연결을 서버에서 해제하지 못했습니다.");
  }
  const unsubscribed = await subscription.unsubscribe();
  if (!unsubscribed) {
    throw new Error("브라우저의 알림 연결을 해제하지 못했습니다.");
  }
}

async function updateNotificationPermissionStatus() {
  if (notificationDisconnect) {
    notificationDisconnect.hidden = true;
  }
  if (!notificationPermissionStatus) {
    return;
  }
  if (!notificationsAreSupported()) {
    notificationPermissionStatus.textContent = "지원되지 않음";
  } else if (window.Notification.permission === "granted") {
    notificationPermissionStatus.textContent = "확인 중";
    try {
      const config = await loadPushConfig();
      if (!config.configured || !config.publicKey) {
        notificationPermissionStatus.textContent = "서버 설정 필요";
      } else if (await matchingPushSubscription(config)) {
        notificationPermissionStatus.textContent = "연결됨";
        if (notificationDisconnect) {
          notificationDisconnect.hidden = false;
        }
      } else {
        notificationPermissionStatus.textContent = "허용됨 · 연결 필요";
      }
    } catch {
      notificationPermissionStatus.textContent = "상태 확인 실패";
    }
  } else if (window.Notification.permission === "denied") {
    notificationPermissionStatus.textContent = "차단됨";
  } else {
    notificationPermissionStatus.textContent = "요청 전";
  }
}

function showNotificationResult(message) {
  if (!notificationPrompt || !notificationMessage || !notificationAllow || !notificationLater) {
    return;
  }
  notificationMessage.textContent = message;
  notificationAllow.hidden = true;
  notificationLater.textContent = "닫기";
  notificationPrompt.hidden = false;
  notificationLater.focus();
}

async function maybeShowNotificationPrompt() {
  if (!notificationPrompt) {
    return;
  }
  if (!notificationsAreSupported()) {
    showNotificationResult("이 기기 또는 브라우저에서는 웹 알림을 사용할 수 없습니다.");
    return;
  }
  if (window.Notification.permission === "granted") {
    try {
      const config = await loadPushConfig();
      if (await matchingPushSubscription(config)) {
        rememberNotificationPrompt();
        return;
      }
      if (!config.configured || !config.publicKey) {
        showNotificationResult("서버의 Web Push 키가 아직 설정되지 않았습니다.");
        return;
      }
      prepareNotificationPrompt(
        "알림 권한은 허용되어 있습니다. 이 기기를 예약 알림에 연결해 주세요.",
        "기기 연결",
      );
    } catch {
      prepareNotificationPrompt("이 기기를 예약 알림에 연결해 주세요.", "기기 연결");
    }
    return;
  }
  if (notificationPromptWasHandled()) {
    return;
  }
  if (window.Notification.permission === "denied") {
    showNotificationResult("알림이 차단되어 있습니다. 기기의 알림 설정에서 이 앱을 허용해 주세요.");
    return;
  }
  prepareNotificationPrompt();
}

window.addEventListener("appinstalled", maybeShowNotificationPrompt);
if (isInstalledApp()) {
  maybeShowNotificationPrompt();
}
updateNotificationPermissionStatus();

notificationOpen?.addEventListener("click", () => {
  if (!notificationsAreSupported()) {
    showNotificationResult("이 기기 또는 브라우저에서는 웹 알림을 사용할 수 없습니다.");
  } else if (window.Notification.permission === "granted") {
    prepareNotificationPrompt(
      "알림 권한은 허용되어 있습니다. 이 기기를 예약 알림에 연결해 주세요.",
      "기기 연결",
    );
  } else if (window.Notification.permission === "denied") {
    showNotificationResult("알림이 차단되어 있습니다. 기기의 알림 설정에서 이 앱을 허용해 주세요.");
  } else {
    prepareNotificationPrompt();
  }
});

notificationAllow?.addEventListener("click", async () => {
  notificationAllow.disabled = true;
  try {
    const config = await loadPushConfig();
    if (!config.configured || !config.publicKey) {
      throw new Error("서버의 Web Push 키가 아직 설정되지 않았습니다.");
    }
    const permission =
      window.Notification.permission === "granted"
        ? "granted"
        : await window.Notification.requestPermission();
    if (permission === "granted") {
      await connectPushSubscription(config);
      rememberNotificationPrompt();
      updateNotificationPermissionStatus();
      showNotificationResult("이 기기의 예약 알림 연결을 완료했습니다.");
    } else if (permission === "denied") {
      rememberNotificationPrompt();
      updateNotificationPermissionStatus();
      showNotificationResult("알림이 차단되었습니다. 다시 사용하려면 기기의 알림 설정에서 이 앱을 허용해 주세요.");
    } else {
      notificationMessage.textContent = "권한 요청이 완료되지 않았습니다. 준비되면 다시 시도해 주세요.";
      notificationAllow.disabled = false;
      notificationAllow.focus();
    }
  } catch (error) {
    notificationMessage.textContent =
      error instanceof Error && error.message
        ? error.message
        : "알림 기기를 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.";
    notificationAllow.textContent = window.Notification.permission === "granted" ? "다시 연결" : "다시 시도";
    notificationAllow.disabled = false;
    notificationAllow.focus();
  }
});

notificationDisconnect?.addEventListener("click", async () => {
  notificationDisconnect.disabled = true;
  try {
    await disconnectPushSubscription();
    await updateNotificationPermissionStatus();
    showNotificationResult("이 기기의 예약 알림 연결을 해제했습니다. 브라우저의 알림 권한은 그대로 유지됩니다.");
  } catch (error) {
    showNotificationResult(
      error instanceof Error && error.message
        ? error.message
        : "기기 알림 연결을 해제하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    );
  } finally {
    notificationDisconnect.disabled = false;
  }
});

notificationLater?.addEventListener("click", () => {
  rememberNotificationPrompt();
  closeNotificationPrompt();
});
