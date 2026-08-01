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

document.addEventListener(
  "submit",
  (event) => {
    blockOfflineMutation(event, event.target.method || "GET");
    if (event.defaultPrevented) {
      return;
    }
    const message = event.target.dataset.confirm;
    if (message && !window.confirm(message)) {
      event.preventDefault();
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
