// Transaction Marker - Background Service Worker
// Adds custom headers to requests when recording is active.

const TX_HEADER = "x-transaction-name";
const TX_START_HEADER = "x-transaction-start";
const TX_END_HEADER = "x-transaction-end";

let isActive = false;
let currentTransaction = "";

// Listen for messages from popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "START_TRANSACTION") {
    isActive = true;
    currentTransaction = message.name || "Unnamed";
    sendResponse({ ok: true, transaction: currentTransaction });
  } else if (message.type === "STOP_TRANSACTION") {
    isActive = false;
    currentTransaction = "";
    sendResponse({ ok: true });
  } else if (message.type === "GET_STATUS") {
    sendResponse({ active: isActive, transaction: currentTransaction });
  }
  return true;
});

// Modify headers on outgoing requests when active
chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    if (!isActive || !currentTransaction) return { requestHeaders: details.requestHeaders };

    const headers = details.requestHeaders || [];

    // Add or update transaction name header
    const txIdx = headers.findIndex(
      (h) => h.name.toLowerCase() === TX_HEADER
    );
    if (txIdx >= 0) {
      headers[txIdx].value = currentTransaction;
    } else {
      headers.push({ name: TX_HEADER, value: currentTransaction });
    }

    // Mark transaction start on first request
    const startIdx = headers.findIndex(
      (h) => h.name.toLowerCase() === TX_START_HEADER
    );
    if (startIdx >= 0) {
      headers[startIdx].value = "true";
    } else {
      headers.push({ name: TX_START_HEADER, value: "true" });
    }

    return { requestHeaders: headers };
  },
  { urls: ["<all_urls>"] },
  ["blocking", "requestHeaders"]
);
